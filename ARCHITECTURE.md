# Architecture

This is the map of the code: how a post travels from the channel to the main page, what the moving parts are called, and where to find the code behind each behaviour. The commands and the settings are documented in [README.md](README.md); this file is about structure.

## The one idea

TeleRadiopedia-Bot has one job with two halves that never touch each other directly. The Telegram half **collects**: it receives the posts of one channel and writes them to SQLite, and that is all it does with them. The wiki half **publishes**: it is handed a finished plan — three pages, three files, the exact wikitext and the exact bytes — and carries it out. Between them sits `publisher.py`, the only module that knows both, and `news.py`, which knows neither and decides what a news is.

Everything runs in one process on one asyncio loop, with one exception that shapes the whole design: **Pywikibot is synchronous**. Every wiki call blocks, so a pass builds its plan on the loop and then hands it to a worker thread (`asyncio.to_thread`), which is the only place a wiki is spoken to. The database is reached from both, which is why `db/__init__.py` wraps its single connection in a re-entrant lock.

The news can go to several wikis at once (`config.WIKIS`). They are the same three news everywhere, built once; what is per wiki is the plan — its template titles, its file names, the CSS prefix its stylesheet knows the cards by, and its own answer to what each slot already holds — and the turn in the worker thread. A wiki that is down costs its own news and nobody else's.

```
channel_post ──▶ telegram_bot/channel.py ──▶ db.channel_posts
                                                   │
                     at :00, :15, :30, :45 (main.py: publish_loop)
                                                   ▼
                                        publisher.run_pass
                                          │            │
                              news.collect_news    telegram_bot.download_photo
                                          │            │
                                          ▼            ▼
                                     a plan per wiki ──▶ asyncio.to_thread ──▶ wiki/pages.py: apply_plan
                                                                                 │
                                                                     upload the file, then edit the template
                                                                                 │
                                                                     db.wiki_slots ◀── what went through
```

## The path of a post

0. **`backfill.py: sync`** runs first, before each pass (`config.PREVIEW_SYNC`) and on `/backfill`: it reads the channel's public web preview through `preview.py`, stores the posts the bot was not there for and refreshes the preview-sourced ones that have changed. Its rows carry a picture *URL* where a Bot API row carries a `file_id`, which is the one difference the rest of the code has to know about (`publisher.py: _download`), and `channel_posts.source` is what keeps it from overwriting a row the bot heard itself.
1. **`telegram_bot/channel.py: on_channel_post`** fires for every post of every channel the bot administrates; `telegram_bot/client.py: is_source_chat` is what decides whether this is the followed one. The row written to `channel_posts` holds the text (or the caption), the Telegram timestamp, the `media_group_id` and both identifiers of the largest photo size — `file_id` to download it with, `file_unique_id` because it is the same for the same picture and is what lets a later pass skip an upload. Then `db.cleanup_old_posts` drops everything past the newest 60.
2. **`main.py: publish_loop`** wakes up. It makes sure the channel is resolved (`resolve_source_channel`, once, retried at every tick until it works) and calls `publisher.run_pass`.
3. **`news.py: collect_news`** turns the stored rows into at most three news, newest first — folding albums, skipping textless posts, shortening the text, formatting the date in `NEWS_TIMEZONE`, and building the link from the channel's `@name`.
4. **`publisher.py: _fetch_pictures` and `_build_plan`** decide what has to move. A picture is downloaded once per pass and only when *some* wiki is missing it (`wiki_slots` holds each wiki's answer, as the `file_unique_id` of what its slot holds). Then one plan is built per wiki: each entry carries the template title, the file name, the finished wikitext (`news.render_template`), the bytes to upload or `None`, and the two edit summaries. A slot whose picture this wiki neither holds nor can be given is rendered with no image block at all, so a card never points at a file holding an older news' picture.
5. **`wiki/pages.py: apply_plan`** runs in the worker thread, once per wiki: for each slot, upload the file *then* edit the template — that order, so a template never points at a file that has not arrived yet. Each slot is wrapped on its own, so one failure costs one slot; each wiki is wrapped on its own too.
6. **`publisher.py`** records the slots that succeeded in `wiki_slots`, under the key `'<family>:<lang>'` of the wiki they went to, writes the timestamp and the errors of the pass into `state`, and hands the counts back. `main.py` turns them into a service event, or nothing at all when the pass changed nothing.

`/update` enters at step 3 through the same `run_pass`; `/update force` makes step 4 ignore what the slots remember, so all three pictures are uploaded again.

## What a news is

`news.py` is the whole of the editorial logic, and it reaches for nothing but `config` and `richtext`. Five rules — an album is one news, only posts with text count, the post keeps its formatting and its paragraphs, a repost says where it came from, and the first picture wins while a news without one is published with no image block — are documented in [README.md](README.md#what-becomes-a-news); what matters here is that they live in one function, `collect_news`, and that the cut (`cut_length`, `shorten`, `cut_chars`), the date (`format_date`) and the card itself (`render_template`) are separate functions beside it. A change to how a card looks is a change to `render_template` and nothing else. The one thing it takes from outside is the stem of the CSS classes: the same news is `tp-news__item` on one wiki and `rp-news__item` on another, so the prefix travels in with the call (`publisher.wiki_css_prefix`) rather than being written into the module.

The formatting is `richtext.py`'s, and it is built around one deliberately dumb shape: a list of `(character, formats)` pairs, one entry per character. Offsets — where formatting code usually breaks — exist only at the doors, where the Bot API's UTF-16 units are converted once and the preview's HTML is parsed; cutting, collapsing whitespace and grouping runs are then list operations that cannot put a tag in the wrong place.

`richtext.escape` is the security-shaped one. A post is written by whoever writes the channel and lands inside HTML inside wikitext, where either layer can be broken by one character: `<` opens a tag, `|` ends a template parameter, `[[` starts a link. Everything that means something to either layer becomes its HTML entity, which renders as the character and parses as nothing.

## Background loops

There is one, in `main.py`:

- **`publish_loop`** — resolve the channel if it is not resolved yet, run a pass, sleep until the next mark on the clock (`utils.publish_marks`, from `config.PUBLISH_AT_MINUTES`). Waiting on the clock rather than on a stopwatch is what keeps the passes at :00, :15, :30 and :45 however long one of them took and whenever the bot was started; one pass also runs at start-up. Every failure is caught inside the loop: a wiki that is down, a network that is out and a bug alike must cost one pass and not the process, because the next round is minutes away and the posts are already stored.

Beside it runs `telegram_bot.main`, aiogram's long polling. `main()` gathers the two, reports `service_started` five seconds in, and reports `service_stopped` however the gather ends.

## Feature → file

| Feature | Where it lives |
|---|---|
| Collecting the channel's posts | `telegram_bot/channel.py` |
| Which channel is followed, and its `@name` | `telegram_bot/client.py` (`_source`, `is_source_chat`, `resolve_source_channel`) |
| Downloading a picture | `telegram_bot/files.py` (Bot API), `preview.py` (the web preview) |
| Recovering older posts, and noticing edits | `preview.py` (read and parse), `backfill.py` (store and refresh) |
| The four commands | `telegram_bot/commands/user.py` |
| What a news is; shortening; the card's wikitext | `news.py` |
| Formatting: Telegram entities and preview HTML into wikitext | `richtext.py` |
| The sequence of a pass; what may be skipped | `publisher.py` |
| Logging in to each wiki; where Pywikibot keeps its files | `wiki/site.py` |
| Editing a template; uploading a file | `wiki/pages.py` |
| The schedule; service events | `main.py` |
| Localization runtime; the admin check; service chats | `utils.py` |
| Tables and migrations | `db/schema.py` |
| Stored posts | `db/posts.py` |
| Slot state and bookkeeping | `db/slots.py` |

## Import order is registration order

`@router.message`, `@router.channel_post` and `@router.edited_channel_post` fire when their module is *imported*. A module nobody imports registers nothing and the bot silently loses those handlers. `telegram_bot/__init__.py` therefore imports in dependency order — `client` first, the domain module `channel` next, `commands` last — and re-exports the public API by explicit name lists, never `import *`.

`wiki/__init__.py` has an order requirement of its own, for a different reason: `wiki/site.py` sets `PYWIKIBOT_DIR` in the environment *before* it imports `pywikibot`, and the library reads that variable at import time and never again. `site` must stay the first module of the package to be imported.

`db/__init__.py` opens the one `sqlite3` connection and defines `conn` / `cur` *above* the submodule imports; the submodules do `from db import conn, cur` against the partially initialized package. Keep new submodule imports at the bottom.

## Module-level mutable state

Each of these exists exactly once, declared in one module and imported by name everywhere else. Two modules each declaring "their own" copy is the classic split bug: one writes, the other reads.

| Name | Module | What it holds |
|---|---|---|
| `_source` | `telegram_bot/client.py` | The resolved id and `@name` of the followed channel |
| `_pass_lock`, `_pass_state` | `publisher.py` | The lock that keeps two passes from running at once, and whether one is running |
| `_session` | `wiki/site.py` | The logged-in Pywikibot Site |
| `_LOCALE`, `_LOCALE_STATUS` | `utils.py` | The localization tables, read once at import |
| `_channel` | `main.py` | Whether the source channel has been resolved yet |

## The database

`src/tprp.db`, opened by relative path — the process must run with cwd = `src/`. Three tables, documented in `--` comments inside `db/schema.py`:

- **`channel_posts`** — one row per message seen in the channel, with its formatting as JSON, the channel or person it was reposted from, and a `source` saying whether it came from Telegram or from the preview. Written by the Telegram half and by the preview sync, read by `news.py`. Trimmed to the newest 60.
- **`wiki_slots`** — one row per wiki and slot: the post the slot came from and the `file_unique_id` of the picture uploaded into it. Written only after that wiki accepted the change, which is what makes a failed slot retry itself. An older database may still carry its single-wiki predecessor `news_slots`; nothing reads it, and the additive-only migration policy is why it is left alone rather than dropped.
- **`state`** — the bot's own bookkeeping: the resolved channel, the time of the last pass, the last error.

Migrations are additive only: `CREATE TABLE IF NOT EXISTS`, and new columns through a `PRAGMA table_info` check followed by `ALTER TABLE ADD COLUMN`. No `DROP`, no rebuilds — the file is live data.

## Where to go for a typical task

- **Change what a news card looks like** → `news.py: render_template`, and nothing else.
- **Change what becomes a news** → `news.py: collect_news`.
- **Change how long the text may be, or how it is cut** → `config.NEWS_TEXT_LIMIT` and `news.py: shorten`.
- **Add a fourth news** → add one entry to `NEWS_TEMPLATES` and one to `NEWS_FILES` in `config.py`; nothing in the code counts to three.
- **Add a command** → `telegram_bot/commands/user.py`, plus its six i18n keys and a line in the `help` key.
- **Add a service report** → an i18n key in the six files, and a `send_service_event` call where the thing happens.
- **Publish to another wiki** → one more entry in `config.WIKIS`, and its family file in `src/botconfig/families/`. Give it `templates` / `files` of its own if it keeps the news under other titles, and a `css_prefix` if its stylesheet calls the cards something else.
- **Add a table** → `db/schema.py` (`CREATE TABLE IF NOT EXISTS`, with a `--` comment saying what it stores and who reads it), accessors in a `db/<domain>.py`, re-export in `db/__init__.py`.
