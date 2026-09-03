# Architecture

This is the map of the code: what the pieces are called, how a post travels from the channel to a main page, how a command turns into four hundred edits, and where to find the code behind each behaviour. The commands and the settings are documented in [README.md](README.md); this file is about structure.

## The one idea

Confederate Fandom does wiki work on the Fandom farm, under one account and in one process. Three kinds of it:

- **the news** — the news block of two main pages, kept in step with a Telegram channel, four times an hour;
- **the species names** — one wiki's articles walked once a night, the Russian names of Pokémon species brought to the standard ones;
- **whatever it is asked** — nineteen mechanics over any Fandom wiki, set going by a command in Discord or Telegram, once or on a schedule.

All of it is slow, all of it is the same kind of slow, and none of it may interrupt the rest. That is why everything hangs off one queue (`scheduler.py`), and why the queue has priorities.

**Pywikibot is synchronous**, and that fact shapes the whole design. Every wiki call blocks, so the loop hands work to a worker thread (`asyncio.to_thread`), and that thread is the only place a wiki is spoken to. There is exactly one of it — not for tidiness but because Pywikibot keeps its cookie jar in a process-global (`wiki/site.py`), and two threads on two wikis would take turns unseating each other's session. The database is reached from both, which is why `db/__init__.py` wraps its single connection in a re-entrant lock.

The two halves of the news never touch each other directly. The Telegram half **collects**; the wiki half **publishes** a finished plan. Between them sits `modules/telepedia/publisher.py`, the only module that knows both.

```
                      ┌──────────────── scheduler.py ────────────────┐
                      │  one worker, one queue, ordered by priority  │
                      └──────────────────────────────────────────────┘
                          │                │                  │
              priority 0  │    priority 0  │      priority 10 │
                          ▼                ▼                  ▼
                 modules/telepedia  modules/pokemon      tasks/queue.py
                   (news, :00…)      (species, 20:00)    (one chunk per turn)
                          │                │                  │
                          └────────────────┴──────────────────┘
                                           │
                                    asyncio.to_thread
                                           ▼
                                    wiki/ ── Pywikibot
```

## The path of a post

0. **`modules/telepedia/backfill.py: sync`** runs first, before each pass (`config.PREVIEW_SYNC`) and on `/backfill`: it reads the channel's public web preview through `preview.py`, stores the posts the bot was not there for and refreshes the preview-sourced ones that have changed. Its rows carry a picture *URL* where a Bot API row carries a `file_id`, which is the one difference the rest of the code has to know about (`publisher.py: _download`), and `channel_posts.source` is what keeps it from overwriting a row the bot heard itself.
1. **`telegram_bot/channel.py: on_channel_post`** fires for every post of every channel the bot administrates; `telegram_bot/client.py: is_source_chat` decides whether this is the followed one. The row written to `channel_posts` holds the text (or the caption), the Telegram timestamp, the `media_group_id` and both identifiers of the largest photo size — `file_id` to download it with, `file_unique_id` because it is the same for the same picture and is what lets a later pass skip an upload. Then `db.cleanup_old_posts` drops everything past the newest 60.
2. **`modules/telepedia: job`** comes due. It makes sure the channel is resolved (`resolve_source_channel`, once, retried at every tick until it works) and calls `publisher.run_pass`.
3. **`news.py: collect_news`** turns the stored rows into at most three news, newest first — folding albums, skipping textless posts, shortening the text, formatting the date in `NEWS_TIMEZONE`, and building the link from the channel's `@name`.
4. **`publisher.py: _fetch_pictures` and `_build_plan`** decide what has to move. A picture is downloaded once per pass and only when *some* wiki is missing it (`wiki_slots` holds each wiki's answer, as the `file_unique_id` of what its slot holds). Then one plan is built per wiki: each entry carries the template title, the file name, the finished wikitext (`news.render_template`), the bytes to upload or `None`, and the two edit summaries. A slot whose picture this wiki neither holds nor can be given is rendered with no image block at all, so a card never points at a file holding an older news' picture. A download that will not work is tried three times before it comes to that (`publisher.PICTURE_ATTEMPTS` — Telegram's CDN answers the occasional `HTTP 500` for a file that is there), and the slot is then recorded holding *no* picture, which is the state the next pass reads as "this wiki is missing it" and acts on.
5. **`wiki/site.py: get_site`** hands over that wiki's session, having first asked the wiki whether it still recognises it — a session that expired is renewed here rather than discovered by six failing edits. **`wiki/pages.py: apply_plan`** then runs in the worker thread, once per wiki: for each slot, upload the file *then* edit the template — that order, so a template never points at a file that has not arrived yet. Each slot is wrapped on its own, so one failure costs one slot; each wiki is wrapped on its own too.
6. **`publisher.py`** records the slots that succeeded in `wiki_slots`, under the key `'<family>:<lang>'` of the wiki they went to, writes the timestamp and the errors of the pass into `state`, and hands the counts back. The module turns them into a service event, or nothing at all when the pass changed nothing.

`/update` enters at step 3 through the same `run_pass`; `/update force` makes step 4 ignore what the slots remember.

## The path of a command

1. **`/run`** on either messenger builds a `Conversation` — `telegram_bot/dialogs.py` or `discord_bot/dialogs.py` — and hands it to `tasks/dialog.py: build`, which is the only place the questions live. The two halves differ in one thing only: aiogram cannot block for an answer, so it parks a future in `_pending_inputs` and `telegram_bot/catchall.py` resolves it; discord.py blocks on `wait_for` and needs neither.
2. The dialog asks which mechanics, which wiki, where the pages come from, what each mechanic must be told, **every optional switch in one numbered message**, the summary, and whether it repeats. Then it writes a row: a `tasks` row, or a `schedules` row that will open one later.
3. **`tasks/queue.py: tick`** is the scheduler job. It fires the schedules that are due, then works through the tasks chunk after chunk until there is nothing left or something more important is due. The loop is inside the job because `scheduler.enqueue` refuses a job that is already running, so a job that tried to re-queue itself would advance one chunk a minute.
4. **`tasks/runner.py: plan`** opens the wiki (generating a Pywikibot family for it if the bot has never seen it — `wiki/families.py`), puts the caller and the bot through every check (`tasks/access.py`), lets each mechanic `prepare` itself, and settles the page list into `task_pages`. Nothing is written. The person is told how many pages there are and shown the first twenty.
5. **`/go`** moves the task to `running`. **`tasks/runner.py: run_chunk`** then walks fifty pages, or a minute's worth, or until something more important arrives in the queue — whichever comes first — and returns whether there is more. When a module job is due the whole task job steps aside, the news pass goes through, and the clock hands the worker back a minute later.
6. Per page: the TEXT mechanics see the text one after another and it is saved **once**, with a summary built from what all of them actually did; then the ACTION mechanics act; then the REPORT ones collect. Every diff goes into a file.
7. **`tasks/runner.py: finish`** lets the standalone mechanics do their work, writes the files, stores the counters. **`tasks/notify.py`** sends them to the person who asked and a line to the service chats.

## What a news is

`news.py` is the whole of the editorial logic, and it reaches for nothing but `config` and `richtext`. Five rules — an album is one news, only posts with text count, the post keeps its formatting and its paragraphs, a repost says where it came from, and the first picture wins while a news without one is published with no image block — are documented in [README.md](README.md#what-becomes-a-news); what matters here is that they live in one function, `collect_news`, and that the cut (`cut_length`, `shorten`, `cut_chars`), the date (`format_date`) and the card itself (`render_template`) are separate functions beside it. A change to how a card looks is a change to `render_template` and nothing else. The one thing it takes from outside is the stem of the CSS classes: the same news is `tp-news__item` on one wiki and `rp-news__item` on another, so the prefix travels in with the call (`publisher.wiki_css_prefix`) rather than being written into the module.

The formatting is `richtext.py`'s, and it is built around one deliberately dumb shape: a list of `(character, formats)` pairs, one entry per character. Offsets — where formatting code usually breaks — exist only at the doors, where the Bot API's UTF-16 units are converted once and the preview's HTML is parsed; cutting, collapsing whitespace and grouping runs are then list operations that cannot put a tag in the wrong place.

`richtext.escape` is the security-shaped one. A post is written by whoever writes the channel and lands inside HTML inside wikitext, where either layer can be broken by one character: `<` opens a tag, `|` ends a template parameter, `[[` starts a link. Everything that means something to either layer becomes its HTML entity, which renders as the character and parses as nothing.

## What a mechanic is

`tasks/mechanic.py: Mechanic` — a code, a kind, the MediaWiki rights it needs, and the parameters it must be told. Nothing else. The module under `scripts/` named after the script it came from provides the functions, and the kind decides which:

| Kind | Function | When it runs |
|---|---|---|
| `TEXT` | `apply(ctx, page, text) -> (text, labels)` | Several compose over one page and share one save |
| `ACTION` | `act(ctx, page) -> (state, note)` | After the text ones, one page at a time |
| `REPORT` | `collect(ctx, page) -> lines` | Changes nothing; the task ends with a file |

Every kind may have `prepare(ctx)` (compile the rules, read the deletion log, work out the sister wikis) and `summary_part(ctx, labels)` (what this mechanic contributed to the edit summary). A `standalone` mechanic has no page list at all and does its work in `finish(ctx)` — counting a template's uses, drawing a category tree.

`Mechanic` lives in a module of its own so that a mechanic and the catalogue can be imported in either order: the catalogue imports every mechanic, and every mechanic declares itself with the class.

## Jobs, the clock and the queue

`scheduler.py` holds the registry, the clock and the worker. `register(name, run, minutes=…|daily_at=…, priority=…)` puts a job on the schedule; the clock sleeps until the nearest due moment across all jobs — one timer, not one loop per job — and calls `enqueue`. The worker takes them one at a time.

**Priority is what makes the three kinds of work live together.** Module jobs are 0 and are inserted ahead of everything; the task queue is 10. `enqueue` refuses a job that is already running or already waiting, which is the whole protection against a slow night: without it the queue would grow a news pass per quarter of an hour for as long as a walk lasted.

**And `waiting_ahead` is what a long job asks between chunks.** `tasks/runner.py: run_chunk` calls it after every page; the moment a module job is queued, the chunk ends and the worker goes back. The task's position is `tasks.cursor`, a row in the database, so it also survives a restart.

## Feature → file

| Feature | Where it lives |
|---|---|
| Collecting the channel's posts | `telegram_bot/channel.py` |
| Which channel is followed, and its `@name` | `telegram_bot/client.py` (`_source`, `is_source_chat`, `resolve_source_channel`) |
| Downloading a picture | `telegram_bot/files.py` (Bot API), `modules/telepedia/preview.py` (the web preview) |
| Recovering older posts, and noticing edits | `modules/telepedia/preview.py`, `modules/telepedia/backfill.py` |
| What a news is; shortening; the card's wikitext | `modules/telepedia/news.py` |
| The sequence of a news pass; what may be skipped | `modules/telepedia/publisher.py` |
| Formatting: Telegram entities and preview HTML into wikitext | `richtext.py` |
| The Pokémon names: rules, engine, the walk | `modules/pokemon/names.py`, `rules.py`, `walk.py` |
| The catalogue of mechanics | `tasks/registry.py`, `tasks/mechanic.py` |
| The questions, and what an answer means | `tasks/dialog.py`, `tasks/params.py` |
| Waiting for an answer | `telegram_bot/dialogs.py` + `catchall.py`, `discord_bot/dialogs.py` |
| Where the pages come from | `tasks/pagesets.py` |
| Who may ask, and what the bot may do there | `tasks/access.py`, `wiki/rights.py` |
| Planning, chunking, editing | `tasks/runner.py` |
| The files that come back, and what may go into them | `tasks/report.py` (`safe_error`) |
| Getting answers to the person and the service log | `tasks/notify.py` |
| The task queue as a scheduler job | `tasks/queue.py` |
| Masking, cosmetics, the AWB rule format, the summary | `scripts/wikitools.py` |
| The nineteen mechanics | `scripts/<name>.py`, one per script |
| Turning a domain into a Pywikibot family | `wiki/families.py` |
| Logging in, keeping sessions apart, noticing a forgotten one | `wiki/site.py` (`get_site`, `_use_cookies`, `use_cookies`, `is_signed_in`, `_sign_in_again`) |
| Keeping the credentials file unreadable to others | `wiki/site.py` (`_write_password_file`) |
| Making Pywikibot's own lines go through this bot's log | `wiki/site.py` (`_route_library_logging`) |
| Editing a template; uploading a file | `wiki/pages.py` |
| The schedule, the queue and the priorities | `scheduler.py` |
| The standing jobs and what each reports | `modules/telepedia/__init__.py`, `modules/pokemon/__init__.py` |
| The slash commands and the log channels | `discord_bot/` |
| Localization runtime; the admin check; service chats | `utils.py` |
| Tables and migrations | `db/schema.py` |
| Stored posts / slots / appointments / tasks / schedules | `db/posts.py`, `slots.py`, `admins.py`, `tasks.py`, `schedules.py` |

## Import order is registration order

`@router.message`, `@router.channel_post`, `@router.edited_channel_post` and `@tree.command` fire when their module is *imported*. A module nobody imports registers nothing and the bot silently loses those handlers.

`telegram_bot/__init__.py` imports in dependency order — `client` first, the domain module `channel` next, `commands`, and **`catchall` last**. That last one is not a matter of taste: `telegram_bot/catchall.py` is a `@router.message()` with no filter at all, aiogram dispatches in registration order, and registered any earlier it silently swallows every command below it.

`discord_bot/__init__.py` imports `client` (which builds the `CommandTree`) and then `commands`. The tree is synced once in `on_ready`.

`wiki/__init__.py` has an order requirement of its own, for a different reason: `wiki/site.py` sets `PYWIKIBOT_DIR` in the environment *before* it imports `pywikibot`, and the library reads that variable at import time and never again. `site` must stay the first module of the package to be imported, and `wiki/families.py` imports it before it touches the library.

`tasks/registry.py` imports every mechanic; every mechanic imports `tasks/mechanic.py`, which imports nothing. That is what keeps the two importable in either order.

`db/__init__.py` opens the one `sqlite3` connection and defines `conn` / `cur` *above* the submodule imports; the submodules do `from db import conn, cur` against the partially initialized package. Keep new submodule imports at the bottom.

## Module-level mutable state

Each of these exists exactly once, declared in one module and imported by name everywhere else. Two modules each declaring "their own" copy is the classic split bug: one writes, the other reads.

| Name | Module | What it holds |
|---|---|---|
| `_source` | `telegram_bot/client.py` | The resolved id and `@name` of the followed channel |
| `_pending_inputs` | `telegram_bot/dialogs.py` | The futures a dialog is waiting on, keyed by (chat, person) |
| `_pass_lock`, `_pass_state` | `modules/telepedia/publisher.py` | The lock that keeps two passes from running at once |
| `_channel` | `modules/telepedia/__init__.py` | Whether the source channel has been resolved yet |
| `_session`, `_jars` | `wiki/site.py` | The logged-in Site and the cookie jar, one of each per wiki |
| `_jobs`, `_queue`, `_state` | `scheduler.py` | The registry, the queue and what is running |
| `_contexts` | `tasks/runner.py` | The prepared context of each running task, kept between chunks |
| `_LOCALE`, `_LOCALE_STATUS` | `utils.py` | The localization tables, read once at import |

## The database

`src/fd.db`, opened by relative path — the process must run with cwd = `src/`. Documented in `--` comments inside `db/schema.py`:

- **`channel_posts`** — one row per message seen in the channel, with its formatting as JSON, the channel or person it was reposted from, and a `source` saying whether it came from Telegram or from the preview. Trimmed to the newest 60.
- **`wiki_slots`** — one row per wiki and slot: the post the slot came from and the `file_unique_id` of the picture uploaded into it. Written only after that wiki accepted the change, which is what makes a failed slot retry itself.
- **`state`** — the bot's own bookkeeping: the resolved channel, the time of the last pass, the last error.
- **`wiki_admins`** — the people appointed with `/wikiadmin`: platform, numeric id, display name, Fandom account. The appointment; never the standing, which is asked of the wiki.
- **`tasks`** — one run: the wiki, the mechanics, the parameters, who asked, the state, the cursor and the counters.
- **`task_pages`** — that run's page list, settled before the first edit. This is the table that makes a long run interruptible, resumable and countable.
- **`schedules`** — a task that repeats, and when it is next due.

An older database may still carry `news_slots`, the single-wiki predecessor of `wiki_slots`; nothing reads it, and the additive-only migration policy is why it is left alone rather than dropped.

Migrations are additive only: `CREATE TABLE IF NOT EXISTS`, and new columns through a `PRAGMA table_info` check followed by `ALTER TABLE ADD COLUMN`. No `DROP`, no rebuilds — the file is live data.

## Where to go for a typical task

- **Change what a news card looks like** → `modules/telepedia/news.py: render_template`, and nothing else.
- **Change what becomes a news** → `modules/telepedia/news.py: collect_news`.
- **Add a fourth news** → one more entry in `NEWS_TEMPLATES` and one in `NEWS_FILES`; nothing in the code counts to three.
- **Add a mechanic** → a module in `scripts/` with a `SPEC`, its name in `tasks/registry.py: _load` (**at the end** — the numbers people are holding must keep meaning the same thing), and its i18n keys in the six files.
- **Add a page source** → `tasks/pagesets.py` (`SOURCES` and `collect`), plus `pageset_<code>` and `dialog_source_argument_<code>` in the six files.
- **Change what a run may do to a wiki** → `wiki/rights.py` (the group and right tables) and `tasks/access.py` (the order of the checks and their wording).
- **Add a command** → the matching `commands/` module on *both* messengers, plus its six i18n keys and a line in the `help` key.
- **Add a module** → a package under `modules/` with a `jobs()`, and one line in `modules/__init__.py: MODULES`.
- **Add a service report** → an i18n key in the six files, and a `send_service_event` call where the thing happens.
- **Publish to another wiki** → one more entry in `config.WIKIS`, and its family file in `src/botconfig/families/`.
- **Add a table** → `db/schema.py` (`CREATE TABLE IF NOT EXISTS`, with a `--` comment saying what it stores and who reads it), accessors in a `db/<domain>.py`, re-export in `db/__init__.py`. Name the accessors for their domain — `set_task_state`, not `set_state`. The re-export is flat, so two submodules with the same name means the later import silently wins and every caller of the other one starts failing on its own arguments; `db/__init__.py: _check_for_shadowed_names` now refuses to import rather than let that happen again.
