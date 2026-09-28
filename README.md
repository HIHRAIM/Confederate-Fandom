# Confederate Fandom

Confederate Fandom is a bot for automating work on the wikis of the Fandom farm from Discord and Telegram. The people its operator appoints set it to work with a command and a short dialog: nineteen mechanics — find and replace, Russian and Ukrainian spelling and punctuation, markup cleanup, categories, interlanguage links, redirects, files, renames, protection, deletion, undoing a run of edits, page lists, template counts and category trees — over any Fandom wiki named by its address, once or on a schedule. Every run is planned before it writes anything: the pages are counted and the first twenty shown, a preview returns every diff as a file without touching the wiki, the rights of both the bot and the person who asked are checked on that very wiki, and the run ends with a report. Everything goes through one queue, so a walk of nine thousand articles and the work that cannot wait never stand in each other's way. The bot speaks six languages, and each person chooses their own with `/lang`; English until they do. Beside the work it is asked for, the bot can run standing modules on schedules of their own: it keeps the news block on the main pages of Telepedia and Radiopedia in step with a Telegram channel, standardises the Russian names of Pokémon species on the Pokémon Wiki once a night, and commits chosen wiki pages to a GitHub repository every midnight. The modules ship switched off: a bot set up for wiki work alone never mentions them and spends nothing on them.

## Requirements

- Python **3.11**
- A Discord bot token, with the **Message Content Intent** switched on in the Developer Portal — the dialogs are answered with ordinary messages, and without that intent every answer arrives empty. The bot needs permission to write in the channels it is used in, and the application needs `applications.commands` when it is invited, or the slash commands do not appear
- A Telegram bot token — and, for the news module, the bot must be an **administrator of the channel** it follows
- A Fandom account with a **BotPassword**, holding one of the groups **bot**, **content moderator** or **administrator** on every wiki it is to work on
- SQLite (uses local `src/fd.db`, no external database)
- Python packages, all in `requirements.txt`:
  - `aiogram`
  - `discord.py`
  - `pywikibot`
  - `regex` — the spelling rules come from AWB lists that use variable-length lookbehind, which the built-in `re` will not compile. Without it seven of the 607 Russian rules are lost and the bot says so once at start-up
  - `requests` and `aiohttp` — the first request to a wiki the bot has never seen, and the channel's public web preview
  - `tzdata` — the time-zone database for `NEWS_TIMEZONE` and the archive's midnight in Kyiv, on a system that ships none
- For the archive module only, a GitHub token — see [The archive module](#the-archive-module)

## Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/HIHRAIM/Confederate-Fandom
   cd Confederate-Fandom
   ```

2. **Create and activate a virtual environment**
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Prepare the wiki account.** On `Special:BotPasswords` create a BotPassword with the grants the work needs: *Edit existing pages* and *Create, edit, and move pages* for the text mechanics and the renames, *Protect and unprotect pages* and *Delete pages, revisions, and log entries* for the two mechanics that do that, *Rollback changes to pages* if `revertbot` is to use the rollback flag, *Upload new files* and *Upload, replace, and move files* for the news pictures, and *High-volume (bot) access* for the edits to be marked as bot edits. A grant only lets the session use a right the account already holds, so on each wiki the account also needs its group there — see [Who may ask, and what the bot checks](#who-may-ask-and-what-the-bot-checks) and [The wiki login](#the-wiki-login).

5. **Fill in the secrets.** Copy `src/.env.example` to `src/.env`:
   - `TELEGRAM_BOT_TOKEN` — the token from [@BotFather](https://t.me/BotFather).
   - `DISCORD_BOT_TOKEN` — the token from the Discord developer portal.
   - `WIKI_USERNAME` — the wiki account, without any suffix (`Example Bot`).
   - `WIKI_BOT_PASSWORD_SUFFIX` — the *name* of the BotPassword from `Special:BotPasswords` (`ExampleBot`), not the account name. The bot logs in as `<WIKI_USERNAME>@<WIKI_BOT_PASSWORD_SUFFIX>`.
   - `WIKI_BOT_PASSWORD` — the password that page generated.
   - `MYARCHIVE_GITHUB_TOKEN` — for the archive module only; see [The archive module](#the-archive-module). Without it the module stays off.
   - `BACKUP_KEY` — any long random string, this project's own and not another bot's, used to encrypt the database backups. Optional: without it the bot runs exactly as before and simply makes none. Keep a copy somewhere other than this server — lose the key and every backup already made is unreadable for good.

   Environment variables that are already set take precedence over the file. `src/.env` must never be committed; neither must `src/botconfig/user-password.cfg`, which the bot writes from these values for Pywikibot to read (see [The wiki login](#the-wiki-login)).

6. **Fill in the configuration.** Copy `src/config.example.py` to `src/config.py` and edit. The bot itself:
   - `ADMINS["telegram"]` and `ADMINS["discord"]` — the numeric user IDs of the bot's own administrators, on each messenger, as lists: the first Discord id is the one pinged when a repeating run waits for approval. They are not stored in the database on purpose: no mishap there can hand out or take away control of the bot. Everybody else who is to run wiki work is appointed at runtime with `/wikiadmin`.
   - `SERVICE_CHATS["telegram"]` and `SERVICE_CHATS["discord"]` — where the bot reports what it did and what failed: Telegram chats as `"<chat_id>:<thread_id>"` (thread `0` is the plain group), Discord channels as numeric ids. Every report goes to both. Empty sets leave the log as the only record.
   - `BACKUP_CHATS["telegram"]` and `BACKUP_CHATS["discord"]` — where the encrypted database copies go, in the same shape as `SERVICE_CHATS`. Deliberately a separate setting rather than a default to it: the file is the whole database, and the chat that reads status lines is rarely the chat that should keep one. Empty sets (the default) mean no automatic backups.
   - `SERVICE_LANG` — the language those reports are written in. It is the service chats' language and nobody else's: every person reads the bot in the language they chose with `/lang`, English until they choose.
   - `SCHEDULE_APPROVAL` — whether a repeating run set up by a wiki administrator waits for a bot administrator's yes (see [Once, or on a schedule](#once-or-on-a-schedule)). `True` by default; `False` lets wiki administrators set up repeating runs on their own.
   - `WIKI_PUT_THROTTLE` — seconds Pywikibot waits between two edits. `0`, and deliberately so: an account with the bot flag is expected to edit at speed and the wiki throttles it on its own. Raise it for a wiki that asks.

   The three modules follow, each off until it is set up: `config.example.py` ships them switched off, and a `config.py` that does not name their settings at all starts just the same.

   The news module (see [The news module](#the-news-module)) — on when `SOURCE_CHANNEL` and `WIKIS` are both set:
   - `SOURCE_CHANNEL` — the channel to follow, as `@name` or as the numeric id.
   - `WIKIS` — every wiki the news go to, each as a Pywikibot family and language code; a wiki that keeps its news under other titles may carry its own `templates` and `files` tuples, and one whose stylesheet names the card's classes differently its own `css_prefix`.
   - `NEWS_TEMPLATES` / `NEWS_FILES` — the template pages and the file names, newest news first. Both tuples must be the same length, and that length is how many news the bot keeps.
   - `NEWS_CSS_PREFIX` — the stem of the card's CSS classes (`tp-news` gives `tp-news__item`, `tp-news__img`, `tp-news__body`, `tp-news__text` and `tp-news__tag`), for every wiki that does not name its own.
   - `NEWS_DATE_FORMAT` / `NEWS_MONTHS` — how the date is written (`26 августа 2026`) and the month names it is written with, which is a question of language rather than of the server's installed locales.
   - `FORWARD_FROM_CHAT` / `FORWARD_FROM_USER` — what a card says about a repost; `{name}` is the channel or the person it came from. Empty means say nothing.
   - `PUBLISH_AT_MINUTES`, `NEWS_TEXT_LIMIT`, `NEWS_TIMEZONE` — the minutes past the hour the wikis are written at, how long a news text may be, and the time zone its date is written in.
   - `PREVIEW_SYNC` / `PREVIEW_LIMIT` — whether to read the channel's public preview before every pass (which is how older posts and missed edits are picked up), and how many of its posts to consider.
   - `EDIT_SUMMARY` / `UPLOAD_SUMMARY` — the edit summaries, in the wikis' own language; `{link}` is the post the news came from.

   The species module (see [The species module](#the-species-module)) — on when `SPECIES_WIKI` is set:
   - `SPECIES_WIKI` / `SPECIES_AT` / `SPECIES_SUMMARY` / `SPECIES_LIMIT` — the wiki the walk goes over, the time of day it runs at, the summary its edits carry, and a page cap for trying it out. `SPECIES_WIKI = None` switches the module off.
   - `SPECIES_REQUIRE_BOT_FLAG` — whether the walk refuses to start on a wiki where the account has no bot flag. On by default: hundreds of unflagged edits at once flood Recent changes.

   The archive module (see [The archive module](#the-archive-module)) — on when `MYARCHIVE` is set and `MYARCHIVE_GITHUB_TOKEN` is in `.env`:
   - `MYARCHIVE` — a dict: `repo`, the `pages` to archive, the Fandom `owner` whose lone edits make a plain update, `coauthors` (Fandom account → GitHub login), the commit `messages`, and optionally `branch`, `at`, `timezone` and `main_pages`. `config.example.py` shows its shape.

7. **Set up the Discord application.** In the Developer Portal, on the *Bot* page, switch on the **Message Content Intent**: the dialogs are answered with ordinary messages, and without it every answer arrives empty. Invite the application with both `bot` and `applications.commands`, or the slash commands never appear. The tree is synced once when the gateway comes up, so a new command shows after a restart.

8. **Add a family file per module wiki.** A wiki named in a task needs nothing: it is looked up once and its Pywikibot family file generated (`wiki/families.py`). Only the wikis of `WIKIS` and `SPECIES_WIKI` need a file written by hand, at `src/botconfig/families/<family>_family.py`, mapping the language code to the host and the script path. The ones shipped with the project are the example to copy:

   ```python
   from pywikibot import family


   class Family(family.Family):

       name = 'radiopedia'
       langs = {'ru': 'radiopedia.fandom.com'}

       def scriptpath(self, code):
           return '/ru'

       def protocol(self, code):
           return 'https'
   ```

9. **Run the bot** — from `src/`, because the database, `.env` and Pywikibot's own directory are opened by relative path:
   ```bash
   cd src && python main.py
   ```

### Running as a service

The bot is meant to run unattended, as a `systemd` unit with `WorkingDirectory=` pointing at `src/`. Its output goes to the journal — `journalctl -u fd_bot -f` — because nothing in the code opens a log file.

Stopping is orderly. aiogram answers `SIGTERM` by stopping its polling, and `main()` ends on the first of its tasks to finish, cancels the others, tells the service chats that the bot is stopping and closes both clients, so `TimeoutStopSec=` can stay at its default. A killed process is not a disaster — nothing is written mid-edit — but it leaves the database's log to be replayed at the next start, which is exactly the state worth not being in when files are being swapped.

**Stop the service before you replace files.** `src/fd.db` is open by the running process. Replacing it underneath leaves the process writing through its old handle into a file nobody will read again — and the write-ahead log (`fd.db-wal`) beside it belongs to the file that was there when it was written. Never delete a `-wal` file to "clean up": it holds the newest rows, and SQLite folds it back in on the next open. `systemctl stop fd_bot`, copy, `systemctl start fd_bot`.

---

## Project structure

The code lives in `src/`, split into packages by domain. [ARCHITECTURE.md](ARCHITECTURE.md) describes how the pieces work together and carries a feature → file table.

```
src/
  main.py              entry point: the two messengers, the modules, the task
                       queue, the nightly sweep and the twice-daily backup
  scheduler.py         the clock and the queue: what runs when, who goes first,
                       and never two at once
  config.py            this deployment's admins, chats and wikis (untracked;
                       config.example.py is the template)
  env_loader.py        reads src/.env
  utils.py             localization runtime, the admin check, service and
                       backup chats, paging, durations
  richtext.py          Telegram's formatting carried over into wikitext
  backup_crypto.py     encrypted database snapshots
  restore_backup.py    their restore tool

  tasks/               the task engine
    mechanic.py          what a mechanic is, and its three kinds
    registry.py          the numbered catalogue
    params.py            what a mechanic must be told, and reading an answer
    dialog.py            the questions, written once for both messengers
    pagesets.py          the twelve page sources
    access.py            who may ask; what the bot may do on that wiki
    runner.py            the plan, the chunks, the edits
    report.py            the files that come back
    notify.py            answering the person, and the service log
    queue.py             the job that drives it all; places and estimates
    lists.py             what /tasks, /jobs, /schedule, /help and
                         /wikiadmin say, for both messengers

  scripts/             the nineteen mechanics, each named after its script
    wikitools.py         masking, cosmetics, the AWB rule format, summaries
    data/                the typo lists and the 2019 Ukrainian rules

  wiki/                the wiki side
    site.py              Pywikibot's directory, one session and cookie jar
                         per wiki
    families.py          a Pywikibot family generated from a domain
    rights.py            groups and rights
    pages.py             writing the news templates and files

  modules/             the standing work
    teleradiopedia/      the news: settings, news, publisher, preview, backfill
    pokemon/             the species names: names, rules, walk, data/
    myarchive/           the page archive: fandom, github, archive

  db/                  SQLite layer: one connection, one module per domain
    __init__.py          connection (conn/cur), init(), the whole public API
    schema.py            every CREATE TABLE + additive migrations
    admins.py            wiki administrators and Telegram invitations
    tasks.py  schedules.py  posts.py  slots.py

  telegram_bot/        the Telegram half
    client.py            bot, dispatcher, router, the followed channel
    people.py            @name invitations turned into appointments
    channel.py           the posts of the followed channel
    dialogs.py  pages.py  files.py
    commands/            user, tasks, admins
    catchall.py          feeds the dialogs; registered last

  discord_bot/         the Discord half
    client.py            the client, the command tree, the log channels
    dialogs.py  pages.py
    status.py            the presence line
    approvals.py         the buttons that approve a repeating run
    commands/            tasks, admins

  i18n/                the six localization files
  botconfig/           Pywikibot's directory: its config, the family files,
                       one cookie file per wiki
  reports/             the files a run sends back (untracked)
```

---

## Commands

Permission roles used below:

- **Everyone** — any user who can see the bot.
- **Wiki Admins** — users appointed with `/wikiadmin`, by their account on the messenger and their account on Fandom (see [Wiki administrators](#wiki-administrators)). The appointment is global and deliberately cheap to give: it is not what grants anything by itself.
- **Bot Admins** — global admins defined in `config.py` (`ADMINS`); they hold Wiki Admin rights everywhere plus the bot-wide commands.

> Notes:
> - Being a Wiki Admin is not what lets a run happen. Before a task starts the bot asks *that wiki* whether the person holds rollback, content moderator, discussions moderator, administrator, bureaucrat or bot there, and refuses if they do not — see [Who may ask, and what the bot checks](#who-may-ask-and-what-the-bot-checks).
> - The bot checks itself the same way: it must hold bot, content moderator or administrator on that wiki, and a missing right is reported as the *group* that would grant it, never as the bare right.
> - `/update` and `/backfill` exist on Telegram only: the news module is administered from the messenger the followed channel lives on.
> - `/backup` answers privately — ephemeral on Discord, where it is also allowed in a DM, and in private chats only on Telegram.
> - `/help` and `/status` are open to more people on Discord than on Telegram; the tables below say which.
> - Anything long — the task list, the queue, the repeating runs, `/help` — comes back as a page with arrows under it when it does not fit on one: an embed with buttons on Discord, a message with an inline keyboard on Telegram.
> - Replies come in the language each person chose for themselves with `/lang` — English until they choose one. See [Localization](#localization).

### Discord commands

| Command | Purpose | Everyone | Wiki Admins | Bot Admins |
|---|---|:---:|:---:|:---:|
| `/tasks` | The numbered list of tasks the bot can be set to: the name, the code, and what each one does | ❌ | ✅ | ✅ |
| `/run [what]` | Set up a run, in a dialog in this channel. `/run what: 1 4` and `/run what: replace typos-ru` skip the first question | ❌ | ✅ | ✅ |
| `/go <task_id> [dry]` | Confirm a prepared task and start it. With `dry` it writes nothing: every diff is computed and sent back as a file, the wiki untouched | ❌ | ✅ | ✅ |
| `/jobs` | What is running, what is queued, and how the last few tasks ended | ❌ | ✅ | ✅ |
| `/stop <task_id>` | Stop a task. What it has already written stays written | ❌ | ✅ | ✅ |
| `/schedule [action] [schedule_id]` | The repeating runs; `action` is `list`, `on`, `off` or `del`. A run waiting for approval cannot be switched on | ❌ | ✅ | ✅ |
| `/status` | The followed channel, the news wikis and their schedule, what is running and waiting, and the last error | ❌ | ✅ | ✅ |
| `/help` | What the bot does and which commands it takes | ✅ | ✅ | ✅ |
| `/wikiadmin [user] [wiki_user]` | Appoint a Wiki Admin by Discord user and Fandom account; with no arguments, list who is appointed and which Telegram invitations are still waiting | ❌ | ❌ | ✅ |
| `/remwikiadmin <user>` | Take the appointment away | ❌ | ❌ | ✅ |
| `/backup` | Send an encrypted copy of the database, right now, to the person who asked and nobody else | ❌ | ❌ | ✅ |
| `/lang [code]` | The language the bot answers you in, picked from a list; without a choice, which one it is now | ✅ | ✅ | ✅ |

### Telegram commands

| Command | Purpose | Everyone | Wiki Admins | Bot Admins |
|---|---|:---:|:---:|:---:|
| `/tasks` | The numbered list of tasks the bot can be set to: the name, the code, and what each one does | ❌ | ✅ | ✅ |
| `/run [numbers or codes]` | Set up a run, in a dialog in this chat. `/run 1 4` and `/run replace typos-ru` skip the first question | ❌ | ✅ | ✅ |
| `/go <id> [dry]` | Confirm a prepared task and start it. With `dry` it writes nothing: every diff is computed and sent back as a file, the wiki untouched | ❌ | ✅ | ✅ |
| `/jobs` | What is running, what is queued, and how the last few tasks ended | ❌ | ✅ | ✅ |
| `/stop <id>` | Stop a task. What it has already written stays written | ❌ | ✅ | ✅ |
| `/schedule [on\|off\|del <id>]` | The repeating runs; with no arguments, list them. A run waiting for approval cannot be switched on | ❌ | ✅ | ✅ |
| `/status` | The channel, the news wikis, how many posts are stored, when the last pass ran and what it left behind, and what each slot holds | ❌ | ❌ | ✅ |
| `/update [force]` | Run a news pass now instead of waiting for the next one. With `force`, ignore which picture each slot already holds and upload every file again — the answer to a file changed or deleted on a wiki behind the bot's back | ❌ | ❌ | ✅ |
| `/backfill [all]` | Read the channel's public web preview now: recover the posts published before the bot was added and pick up their edits. With `all`, also refresh the posts the bot heard from Telegram itself, for one edited while the bot was down | ❌ | ❌ | ✅ |
| `/help` | What the bot does and which commands it takes | ❌ | ❌ | ✅ |
| `/wikiadmin [<who> <Fandom account>]` | Appoint a Wiki Admin; *who* is an `@name` or a numeric id. An `@name` the bot has not heard from yet waits as an invitation until that account first writes to the bot. With no arguments, list who is appointed and who is invited | ❌ | ❌ | ✅ |
| `/remwikiadmin <who>` | Take the appointment away, or withdraw a waiting invitation | ❌ | ❌ | ✅ |
| `/backup` | Send an encrypted copy of the database, right now. Private chats only | ❌ | ❌ | ✅ |
| `/lang [en\|es\|pl\|pt\|ru\|uk]` | The language the bot answers you in; with no code, which one it is now | ✅ | ✅ | ✅ |

---

## Mechanics

Everything Confederate Fandom does, in one place.

### Tasks on any Fandom wiki

Nineteen mechanics, each a Pywikibot script (or one of the operator's own) with its command line replaced by a dialog. `/tasks` prints them numbered; `/run` sets one going.

| # | Code | What it does | Rights it needs |
|---|---|---|---|
| 1 | `replace` | Find and replace text or a regular expression | edit |
| 2 | `addtext` | Add a block of text at the top, at the bottom or before the categories | edit |
| 3 | `unlink` | Take the links to one page out and leave the words | edit |
| 4 | `typos-ru` | Russian: 607 typo rules, with punctuation and cosmetics on request | edit |
| 5 | `punct-ru` | Russian punctuation alone, words untouched | edit |
| 6 | `pravopys-uk` | Ukrainian: §35, §36 and §126 of the 2019 spelling rules, plus 172 typo rules | edit |
| 7 | `cosmetic` | The markup alone: spaces in headings, indents, spare blank lines, a dash for a hyphen | edit |
| 8 | `category` | Add, remove or move a category | edit |
| 9 | `interwiki` | Complete the interlanguage links, gather them at the end, sort them | edit |
| 10 | `redirect` | Fix double redirects, point links straight at the target, find the broken ones | edit |
| 11 | `image` | Swap a file for another, or take it off the pages that show it | edit |
| 12 | `delinker` | Take files already deleted from the wiki off the pages that still show them | edit |
| 13 | `movepages` | Rename from a list of pairs, or by a prefix, a suffix or a regular expression | move |
| 14 | `protect` | Set or lift protection on editing, moving, re-uploading | protect |
| 15 | `delete` | Delete a list of pages | delete |
| 16 | `revertbot` | Undo an account's contribution: every page where its edit is still the latest | edit |
| 17 | `listpages` | Write the page list to a file | — |
| 18 | `templatecount` | How many pages use the templates, and which | — |
| 19 | `category-graph` | The tree of subcategories, as text or as a `.dot` file | — |

**They compose.** Everything that rewrites wikitext runs over the same page in one pass and saves once: `replace` + `typos-ru` + `cosmetic` is one line in the history, with a summary built from what all three actually did. `/run replace typos-ru cosmetic` is how that is asked for.

**Any Fandom wiki, by domain.** The dialog asks for the wiki and takes anything a person is likely to paste — `telepedia.fandom.com/ru`, a link to an article, or the `family:lang` shorthand the bot prints. A wiki the bot has never seen is looked up once (`meta=siteinfo`) and a Pywikibot family file is generated for it; from then on it costs nothing.

**A rename leaves redirects behind, and the redirects that pointed at the old title become double.** MediaWiki on Fandom does not repoint them on its own. A `redirect` run that fixes the double ones, after a batch of renames, is what closes that gap.

### The dialog

Short on purpose. Which mechanics, which wiki, where the pages come from, what each mechanic must be told — and then **every optional switch of every chosen mechanic in one numbered message**, answered with the numbers you want separated by spaces, or `0` for none. Four mechanics with five switches each is one question, not twenty. Then the edit summary — or `0`, and the bot writes what it actually did — and whether the run happens once or regularly.

**`0` is the one answer for "nothing".** No limit on the pages, no summary of your own, no switches, a replacement that deletes what was found, a file taken out rather than swapped: every question that can be answered with nothing takes `0` and says so. Some of them used to take a dash and some a dash or a zero, and people rightly asked why there were two. Where `0` could be a real answer — a search for the digit zero — it is exactly that.

**Renaming can be a list rather than a rule.** A rule — add this prefix, strip that suffix, rewrite by a regular expression — is the right shape for a hundred pages named alike and the wrong shape for nine pages named nothing alike. So `movepages` also takes the renames themselves: page source “a list of renames I will send”, then one rename per line,

```
Список_серий Список_эпизодов
Первый_сезон Сезон_1
```

and the pages of the run are the left-hand column. A space in a title is written as an underscore, the way MediaWiki writes it in a URL — and on Discord that is not optional: its markdown turns text between underscores into italics and eats them, so the whole block goes inside a ``` fence, which the bot strips. A line written in lower case still finds its page: the wiki capitalises the first letter, and both spellings are looked for.

### Where the pages come from

One numbered question, one argument where the source needs it, then the namespaces and how many pages to take at most (`0` — all of them).

**The namespaces narrow every source except the two lists.** The question names the common ones by number — 0 articles, 2 users, 4 project pages, 6 files, 10 templates, 14 categories, 828 modules — so nobody has to know them by heart, and “all” (in the reader's language) takes every namespace the wiki has. A list of titles or of renames is not asked it at all, since the titles are taken as sent. The first source is called “all pages of the chosen namespace”: it used to read “every page of the wiki”, and several people chose it expecting exactly that and were then asked which namespaces, which was confusing.

**A mechanic may bring its own pages.** `revertbot` walks the contributions of the account it is told to undo, so a task of it alone asks no page source at all.

| # | Source | What it lists |
|---|---|---|
| 1 | all pages of the chosen namespace | Every page of the chosen namespaces |
| 2 | the pages of a category | The pages of one category |
| 3 | the pages that use a template | The pages that include one template |
| 4 | search results | What the wiki's own search finds |
| 5 | the pages that link to one page | The pages that link to the page given |
| 6 | the pages one page links to | The pages the page given links to |
| 7 | the pages that use a file | The pages that show the file given |
| 8 | the pages whose title starts with | The pages whose title starts with the text given |
| 9 | a list of titles I will send | Exactly the titles sent, one per line |
| 10 | recently created pages | The newest pages, 200 unless a limit says otherwise |
| 11 | pages changed in the last seven days | The pages changed in the last seven days, from the newest 500 changes |
| 12 | a list of renames I will send | The left-hand column of a list of renames (see above) |

**The sources that walk the wiki list what the mechanics can work on.** All pages, a title prefix, new pages and recent changes list ordinary pages for almost every mechanic — and redirects for `redirect` fixing double or broken redirects, which has nothing to do on an article. That was once missing: every walk listed articles alone, so a run fixing double redirects on a wiki with thirteen of them was handed 212 articles, found none of them a redirect, and finished with 0 edits and no error. A task that mixes the two kinds — double redirects and a spelling pass in one run — is handed both. The other sources are not filtered: a category, a template or a list names its pages itself, and whoever named them meant them.

### Plan, preview, go

The task is created as soon as the dialog ends, and the queue takes over: it opens the wiki, puts the person and the bot through every check, lets each mechanic prepare itself — compiling six hundred rules, reading an interwiki map, a deletion log — and settles the page list. Nothing is written in that step. It is where a bad regular expression, a missing right or a wiki the bot has no status on stops the task, and where the person is told how many pages they are about to change and shown the first twenty.

Then the task waits. `/go <id>` runs it; `/go <id> dry` computes every diff and writes nothing, which is how a page list should be read before it is acted on. There is no cap on how many diffs come back — they arrive as a file. A dry run never writes, whatever else happens: the flag is read from the database before every page, so a preview asked for after the plan was made is still a preview. The mechanics that cannot be undone by an edit — renaming, protection, deletion, reverting — are marked in the catalogue and said out loud in the confirmation.

The page list is settled once, into the database. That is what makes a run countable before its first edit, interruptible by `/stop` at any page, and resumable after a restart from exactly where it stopped.

### Who may ask, and what the bot checks

**Bot administrators** are the ids in `config.ADMINS` and are not stored anywhere: no database mishap can hand out or take away control of the bot. They may do everything.

**Wiki administrators** are appointed with `/wikiadmin` (see below). The appointment is global and deliberately cheap to give, because it is not what grants anything — before every run the bot asks *that wiki* whether that person holds rollback, content moderator, discussions moderator, administrator, bureaucrat or bot there. Somebody with no standing on a wiki cannot borrow the bot's.

**And the bot checks itself.** Before a task starts it must hold one of three statuses on that wiki — bot, content moderator or administrator — or it refuses and says so: a hundred edits from an account with no standing is what a wiki blocks. Then the rights each mechanic needs are checked against what the wiki says the session holds, and a missing one is reported as the *group* that would grant it, because “available to the following group: content moderator” is something a person can act on and a bare right such as `editprotected` is not.

**A right can be missing for two reasons, and the answer says which.** The bot logs in with a BotPassword, and its session gets only the rights that are both the account's and allowed by the password's grants. When the account holds the right and the session does not, the missing thing is a grant, and the answer names it as Special:BotPasswords shows it — “Rollback changes to pages”. It used to name a group every time, and told a content moderator — a group that holds rollback — that rollback needed the rollbacker group.

### Wiki administrators

A Bot Admin appoints one with `/wikiadmin`, naming the person on the messenger and their account on Fandom. The Fandom account is not optional and not guessed: it is what the wiki is asked about before every run, and running the command again with another account is how it is corrected. The person is remembered by the numeric id of their messenger account, never by a name — a name can change hands, and an appointment that followed it would go to whoever picked it up.

**On Discord** the person is picked from the member list — `/wikiadmin user: @someone wiki_user: Their Fandom name` — and Discord hands the id over with them.

**On Telegram** the person is typed in: `/wikiadmin @someone Their Fandom name`. Telegram does not tell a bot whose an `@name` is — it resolves the `@name` of a public group or channel and answers “chat not found” for a person — so an `@name` the bot has not heard from is kept as an **invitation**. Nothing is granted yet. The first message or button press the bot receives from an account holding that `@name` turns the invitation into an appointment keyed by that account's id, before the message itself is answered — so a person told to send the bot `/tasks` gets the list, not a refusal. The bot tells them they have been appointed and what to try first, and tells the Bot Admin who appointed them that the invitation was taken. From then on the `@name` does not matter: the person may change it, and whoever takes it up afterwards gets nothing.

An invitation nobody claims lapses after seven days, because the longer it waits the likelier the `@name` is to have changed hands. `/wikiadmin` with no arguments lists the waiting invitations under the appointments, on both messengers, and `/remwikiadmin @someone` withdraws one. A numeric id is appointed at once, and so is a person with no `@name` picked from Telegram's own mention list, which carries the account itself. Replying to somebody's message is deliberately not a way to name them: a reply used to win over whatever was typed, which appointed the person replied to when the administrator had typed somebody else.

### Once, or on a schedule

The last question of the dialog. A repeating run stores the same three things a task does — the wiki, the mechanics, the parameters — plus when it is due, in one of three shapes: at given minutes of every hour, at a time every day, or at a time on named weekdays — numbered from 1 for Monday to 7 for Sunday, the way people count them. Each firing opens an ordinary task, so a scheduled run is watched, reported and stopped exactly like one asked for by hand.

The next moment is recomputed forward from *now* after every firing, so a bot that was down over its hour runs once when it comes back rather than once for every hour it missed. An answer the schedule cannot keep — «06:00» where minutes of the hour were asked for, «8» for a weekday — is asked again rather than stored.

**A repeating run set up by a wiki administrator waits for a bot administrator.** It works on somebody's wiki every hour or every night for as long as nobody stops it, so it is created switched off and a message goes to the Discord channels of `SERVICE_CHATS`, pinging the first Discord id of `config.ADMINS`, with two buttons. *Approve* starts it; *Reject* deletes it and tells the person privately, in their language — or in the chat they asked from, when a private message cannot reach them. Until then `/schedule on` cannot switch it on. The buttons keep working after a restart, and only the ids in `config.ADMINS` may press them. A bot administrator's own schedules never wait, and `SCHEDULE_APPROVAL = False` switches the step off for everybody. This is the one message in the log channels that pings anybody, because it is a question waiting for one person's answer.

**Some work is never repeated.** `revertbot` is not offered on a schedule, and the dialog does not ask “once or regularly” when it is in the task: undoing one person's edits every night is not something anybody means to ask for.

### What comes back

Up to three files, and only the ones a run has something for.

| File | What is in it |
|---|---|
| `task-<id>.diff.txt` | Every change, as a unified diff per page, with the summary that was used |
| `task-<id>.report.txt` | Whatever a reading mechanic collected — the list, the counts, the tree |
| `task-<id>.errors.txt` | The pages that would not be written, and why |

What a mechanic notes along the way — a broken redirect, a page left alone because it links one language twice — comes in the message the run ends with.

The files carry wiki content and nothing else. No traceback, no path on the host, no configuration: a failure is written as its type and message with anything path-shaped taken out, and the full traceback stays in the bot's own log. The files are a copy of what was already sent, and are swept after two weeks.

Every task also reports to the service chats — the Discord channel and the Telegram topic of `SERVICE_CHATS` — when it starts, every five hundred pages, and when it ends, naming who asked for it by their username and id in brackets. Never by a mention: a log that pings somebody every quarter of an hour is a log people mute.

### The queue

`scheduler.py` owns both the clock the jobs run by and the queue they wait in.

| Job | Priority | When | What it does |
|---|---|---|---|
| `tasks` | task | Every minute, and whenever there is more to do | Fires the schedules that are due and walks one chunk of one task |
| `news` | module | `PUBLISH_AT_MINUTES` — :00, :15, :30, :45 — and once at start-up | Catches up with the channel and rewrites the news templates and files on every wiki of `WIKIS` |
| `species` | module | Once a day at `SPECIES_AT` | Walks the articles of `SPECIES_WIKI` and standardises the names of Pokémon species |
| `sweep` | task | Once a day at 04:00 | Throws away the page lists and report files of runs that are long over |
| `backup` | task | Twice a day, at 04:30 and 16:30 | Sends an encrypted copy of the database to `BACKUP_CHATS` |
| `archive` | background | Once a day, at midnight in Kyiv | Commits the pages of `MYARCHIVE` that changed to its GitHub repository |

A module that is not set up has no row here at all: its job is not registered, and nothing about it appears in the queue or the presence line. **Background** is below everything: the archive waits until the queue is empty, a person's task included.

**One at a time, always.** Not because the logins would clash — each wiki has a session and a cookie file of its own, and the bot is signed in to all of them at once — but because Pywikibot is synchronous: every job goes through the same worker thread. A job that comes due while another is running waits its turn, and a job already waiting is not queued twice.

**The modules go first.** The news and the species walk run to a clock that somebody's readers depend on, so they are registered at module priority and jump the queue. Everything a person asks for through a command runs behind them.

**And a long run gives the worker back.** A walk of nine thousand articles could not be allowed to hold the quarter-hourly news pass for an hour, so it is not one job: the task queue walks a *chunk* — fifty pages, or a minute, or until something more important arrives — and then puts itself back in the queue. A walk of a whole wiki is a hundred short jobs with the news slipping in between them, and it survives a restart, because the position is a row in the database and not a variable.

**A task that has to wait is told so, and only then.** A run that the bot picks up at once says nothing about queues — being told you are first of one is noise. A run that lands behind something gets one line: which place it is in, and roughly how long until the bot reaches it, in whichever of hours, minutes and seconds are not zero (`2 h 15 min`, `8 s`). Both moments a task can be queued are covered: when `/run` creates it and when `/go` starts it while another run is still going.

The estimate is exactly as good as it claims to be. It is the pages still to do in front of you divided by the rate the running task is *actually* going at — its own elapsed time over its own pages checked, which already includes every quarter of an hour it stood aside for a news pass. A task merely waiting ahead of you counts as the few seconds its planning takes, because planning is all it will do before it stops and waits for somebody to type `/go`.

What each job reports differs on purpose. A task reports when it starts, every five hundred pages, and when it finishes. The news pass speaks only when it changed something or failed; four silent successes an hour are four messages nobody reads. The species walk reports however it ends, because a job that runs once a night and says nothing cannot be told from one that never ran.

### Presence

The line under the bot's name on Discord is the one place a person sees what it is doing without asking. Something running names the wiki where there is one to name — `Editing telepedia:ru` for a task, the same for the nightly species walk. The news pass has a line of its own, `Updating the TeleRadiopedia news`: it writes to every wiki of `WIKIS` at once, so there is no one wiki to point at, and the name of the group they form lives in the `presence_news` string of the six i18n files — which is what to change when the news go somewhere else. The sweep, the backup and the queue between two tasks name themselves (`Working: the nightly sweep`).

Nothing running, and the line says what is next and how long until it: `Next: the news, in 10 min.`, or `Next: a run on pokemon:ru, in 2 h 15 min.` when a repeating run of somebody's comes sooner than any of the bot's own jobs. The task queue is never what it names as next — it is due every minute and would be the answer for ever — and the countdown is rounded to whole minutes, so that Discord is not sent a new line every thirty seconds. The line is always in English: one line is shown to everybody who looks at the member list, whatever language each of them chose, so it cannot follow anybody's choice.

### No invented limits

There is no ceiling on how many pages a run may touch and no delay between edits (`WIKI_PUT_THROTTLE` is 0). An account carrying the bot flag is expected to edit at speed, the wiki throttles it on its own if it wants to, and a limit invented here would only make a walk of a whole wiki take three hours instead of one. The dialog's own “At most how many pages?” is there so a run can be tried on twenty pages before it is let loose on nine thousand.

### The news module

The module keeps the news block of one or several wikis' main pages in step with one Telegram channel. Four times an hour — at :00, :15, :30 and :45 — it writes the three latest posts into three templates and three files: the text of a post with its formatting and paragraphs, its date, its picture, a link back to the post under that picture, and — for a repost — where it was taken from. Nobody edits the main page by hand, and nothing is copied twice.

Two things are worth checking before anything else, because the module is quiet rather than loud when either is missing:

- **Administrator rights in the channel.** Telegram delivers the posts of a channel to a bot only if that bot administrates it; a bot that merely subscribes receives nothing. There is also no way to *ask* for the posts made earlier: the bot hears about a post as it happens or never. A channel that was already running when the bot arrived is filled in from its public web preview instead — see [Posts from before the bot arrived](#posts-from-before-the-bot-arrived).
- **The grants for the pictures.** Without *Edit existing pages* the templates fail, without *Upload new files* and *Upload, replace, and move files* the pictures do; the bot reports both to the service chats and tries again on the next pass. On a wiki where the three templates do not exist yet, the account also needs the right to create pages — the first pass makes them.

#### From a post to a news card

A post published in the followed channel arrives as a `channel_post` update and is written to `channel_posts` — its text, its date, its album id and the largest size of its picture. Nothing is published at that moment: the wikis are written to on a schedule, so a channel having a busy morning costs the same three edits as a quiet one.

A pass runs at every minute past the hour named in `PUBLISH_AT_MINUTES` and once more at start-up, so a restart is not a quarter of an hour of silence. The schedule is a clock, not a stopwatch: a bot started at twenty past still publishes at half past, and a pass that took two minutes does not push the next one two minutes late. Each pass reads the stored posts, folds them into news, and for each of the three slots uploads the picture and rewrites the template. The result is one card per template:

```
<div class="tp-news__item">
<div class="tp-news__img">[[File:Заглавная-Новость-1.jpg|link=https://t.me/example/512]]</div>
<div class="tp-news__body"><span class="tp-news__text">The text of the post, <b>formatting</b> and paragraphs kept, shortened.</span><span class="tp-news__tag">26 августа 2026</span><span class="tp-news__tag">Переслано из Радио и ТВ</span></div>
</div>
```

The link lives on the picture and points at the post the news came from. A channel with no public `@name` has no such link, and the card is written with `link=` — a picture that is not a link.

#### What becomes a news

Three rules, and they are all in `modules/teleradiopedia/news.py`:

- **An album is one news.** Telegram delivers a post with several pictures as several messages sharing a `media_group_id`; to a reader it is one post, so the bot folds them together, takes the text from whichever message carries it and the picture from the first one that has any.
- **Only posts with text count.** A picture with no words says nothing on a main page. A post without text is skipped and the next one down moves into its place.
- **The first picture wins, and a news without one shows none.** A post with several pictures shows the first of the gallery — the same one Telegram shows in the channel. A post with no picture is published as a card with no picture at all; see below.

#### Formatting

A post is rarely plain text, and what it is written with survives the trip: **bold**, *italics*, underline, strikethrough, `code` and links all come out as wikitext on the card. Bold becomes `<b>`, a link becomes wikitext's `[url text]` — an `<a>` tag would be stripped by MediaWiki — and the rest follow.

The **paragraphs** survive too. A line break in the post becomes `<br>` in the card, and a gap of any size between two paragraphs comes out as exactly one blank line — a channel that separates two thoughts is worth following, a channel that pressed Enter eight times is not.

What a news card has no use for keeps its text and loses its markup: spoilers, blockquotes, mentions and custom emoji. Nothing else is invented: the card shows the post, escaped so that a stray `<`, `|` or `[[` in somebody's post cannot break the page it lands in.

The two sources describe formatting differently — the Bot API sends entities with offsets counted in UTF-16 units, the web preview sends HTML — and both are read into one form before anything else happens (`richtext.py`), which is also the form the database keeps. A post therefore reads the same whichever door it came in through, and the cut below moves the formatting with the text instead of recomputing it.

#### Shortening the text

A post longer than `NEWS_TEXT_LIMIT` (600 characters) is cut where a reader would cut it. A sentence ending in the last part of the allowed window wins: the text stops there and an ellipsis takes the place of the full stop, so the card reads as a finished thought with more behind it. Failing that, the cut is made at the last whole word, and a comma or dash left dangling goes with it. The result, ellipsis included, is never longer than the limit.

#### Reposts

Most of what a news channel publishes is taken from somewhere else, and the card says so. A post forwarded into the channel gets one more tag after the date, in the same style as the date itself:

- from a channel — `Переслано из Радио и ТВ в Ростове-на-Дону и области`
- from a person — `Переслано от @someone`

The wording is `FORWARD_FROM_CHAT` and `FORWARD_FROM_USER` in the configuration, so it follows the wikis' language; setting either to an empty string turns that half off. The tag reuses the date's CSS class deliberately: a note under a news looks like a note under a news, and no stylesheet needs a new rule for it.

The two sources differ in what they can tell. Telegram names a person by their `@name` where they have one; the web preview only ever shows the name they display, and tells a channel from a person by whether that name is a link.

#### Pictures, and cards without one

The picture of a news is uploaded into that slot's file — `Заглавная-Новость-1.jpg` for the newest — replacing whatever it held. A post that carries a gallery gives up the first picture of it, the one Telegram shows in the channel.

A post with no picture of its own (a text-only post, or a video, which is not a picture) is published as a card with **no image block at all** — the `<div class="tp-news__img">` line is simply left out:

```
<div class="tp-news__item">
<div class="tp-news__body"><span class="tp-news__text">The text of the post, shortened.</span><span class="tp-news__tag">26 августа 2026</span></div>
</div>
```

The slot's own file is not touched while that lasts: it keeps the picture it held, out of sight rather than overwritten with a stand-in. As soon as a post with a picture takes that slot, the file is uploaded again and the image block comes back with it.

Telegram refusing to hand over a picture — the post is gone, the file is above the Bot API's 20 MB — is treated the same way, so that a card never shows the caption of one news above the picture of another.

**A refusal is not taken for an answer the first time.** Telegram's own CDN returns the occasional `HTTP 500` for a file that is there, and a card should not lose its picture over one bad second: the download is tried three times, three seconds apart, before the card goes up without one. And when even that fails the slot is recorded as holding no picture at all, which is the same thing it would say if the news had none — so the next pass, a quarter of an hour later, asks for that picture again, uploads it and puts the image block back into the card. Nothing has to remember that a download failed; a slot that holds no picture is already the whole of the memory needed.

#### More than one wiki

`config.WIKIS` lists every wiki the news go to; one entry or five, the mechanics are the same:

```python
WIKIS = (
    {"family": "hihraimtest", "lang": "ru"},
    {"family": "telepedia", "lang": "ru"},
)
```

The three news are the same everywhere — built once, from the same three posts, with the same text and the same link. What belongs to a wiki is where they land, what they are called there and what it already holds: its `templates` and `files`, the `css_prefix` its stylesheet knows the cards by (its own, when the entry names them; the shared `NEWS_TEMPLATES` / `NEWS_FILES` / `NEWS_CSS_PREFIX` otherwise), and its own row per slot in the database. Each wiki is written to on its own turn, so a wiki that is down, or that refuses an edit, costs its own news and nobody else's — the others are published, and the next pass retries the one that failed.

One account serves them all: the bot logs in once per wiki with the same BotPassword and keeps the sessions side by side. A picture is fetched from Telegram **once per pass**, however many wikis are missing it, and then uploaded only to those that are. A wiki that already holds it is left alone. If the download fails, the wikis that already have the picture keep showing it, and the ones that do not publish the card without an image block rather than pointing at a file holding an older news.

A wiki whose stylesheet calls the cards something else says so in its entry:

```python
{"family": "radiopedia", "lang": "ru", "css_prefix": "rp-news"}
```

and its three templates come out as `rp-news__item`, `rp-news__img`, `rp-news__body`, `rp-news__text` and `rp-news__tag` while every other wiki keeps `tp-news`.

Note what the bot does *not* do on a new wiki: it does not touch the main page and it does not add the CSS the cards are styled with — it has no right to edit the interface, deliberately. Both are yours to do; until they are done the cards sit on the wiki, correct and unstyled, showing nowhere.

#### What a pass skips

A pass that finds nothing to do leaves no trace on any wiki:

- **A file is uploaded only when it would change.** Every slot of every wiki remembers the `file_unique_id` of the picture it holds; a news whose picture is already up there is published without a byte moving. `/update force` is what overrides that.
- **A template is edited only when it would change.** The page is compared with what it should say before it is saved. This also means the bot quietly undoes a hand-made edit to one of the three templates at the next pass — they belong to it.
- **A slot is independent of the other two, and of the other wikis.** A file that will not upload fails its own slot on its own wiki; everything else goes through, and only what succeeded is recorded, so the next pass retries exactly what did not.
- **Fewer news than slots leaves the rest alone.** A channel with two posts fills two slots; the third keeps what it had rather than being blanked.

#### Posts from before the bot arrived

The Bot API has no history at all: a bot is told about a channel post as it happens and can never ask for an earlier one. What Telegram does serve is the channel's **public web preview** — the page `t.me/s/<name>` a browser sees with no account — and that is where the bot gets the older posts from.

The same page answers a second question — **what changed** — because the Bot API is no better on edits than on history: a post corrected while the bot was down produces no update it will ever see.

So the preview is read before every pass (`PREVIEW_SYNC`), and each time it is read the bot does two things: it stores the posts it does not have, and it refreshes the ones whose text, formatting or picture no longer match. The preview holds about twenty posts, which is plenty for three news; `PREVIEW_LIMIT` caps how many are considered. `/backfill` does the same on demand.

One rule keeps that from doing damage: **a post the bot heard from Telegram itself is not refreshed from the preview.** Its row carries the larger picture and the text Telegram handed over, while the preview sometimes shortens a long link — comparing the two would rewrite the templates over a difference nobody can see. Those posts are corrected by `edited_channel_post`, which arrives the moment somebody edits them. `/backfill all` is the way out of the rule when a post really was edited while the bot was away.

An album, finally, is a single block in the preview, so it arrives as one post showing the first picture of the gallery — which is what a news is anyway.

The limits are the preview's own: a channel with no public `@name` has no preview, a private channel serves none, its pictures are smaller than the ones the Bot API hands over, and the markup is undocumented and can change — which is why a failed read is reported and let go rather than stopping anything.

#### What the bot cannot see

- **Deletions.** Telegram does not tell bots when a channel post is deleted, and the preview stops showing it rather than saying it is gone. A post removed from the channel stays a news until three newer posts have pushed it out; `/update` after deleting it does not help, because the bot's copy is what it publishes from. Edits, unlike deletions, do reach the wikis: through `edited_channel_post` while the bot is running, and through the preview afterwards (see above).
- **Anything in a channel it does not follow.** One channel is followed at a time, the one in `SOURCE_CHANNEL`.

### The species module

Once a night the bot walks every article of `SPECIES_WIKI` and replaces outdated Russian names of Pokémon species with the standard ones — 270 pairs, taken from the wiki's own `[[Модуль:PokemonData/fromNumber]]` and kept in `modules/pokemon/data/fromnumber_name_rules.tsv`.

The replacement is careful in ways that matter on a wiki:

- **The case is carried over** word by word: `Вайплюм` → `Вайлплюм`, `вайплюм` → `вайлплюм`, `ВАЙПЛЮМ` → `ВАЙЛПЛЮМ`.
- **A name inside a longer word is caught too**, but only when what follows it is a grammatical ending or `-ит` (`Скизорит` → `Сизорит`). Anything else is a word of its own — `Глайгермен`, `Троупринт`, `Брианна` — and is left alone and listed in the report.
- **Four names change how they decline** (`Тентакруэль`, `Драгалдж`, `Силвалл`, `Фион`) and carry an explicit table of endings. A form the table does not know is *not* replaced: it goes into the report for a human, which is how the bot avoids inventing `Фионае`.
- **File names are never touched.** `[[Файл:…]]` targets, `|изображение=` values, gallery lines, categories, interwiki, URLs and `<nowiki>`/`<pre>` are hidden behind placeholders before the pass and put back afterwards. Captions *are* corrected.
- **The pass is idempotent**: running it again changes nothing.

It does not rename pages and does not touch redirects: a title that moves drags redirects, links and categories behind it, and that is a different job with a different cost of error. Nor does it start on a wiki where the account has no bot flag, unless `SPECIES_REQUIRE_BOT_FLAG` is turned off: hundreds of unflagged edits at once are a flood in Recent changes, and the service chats are told why the night was skipped.

### The archive module

Every midnight in Kyiv the bot reads a list of wiki pages — site stylesheets and scripts, Lua modules, the main pages — and commits every one that changed to a GitHub repository, so that a wiki's interface has a history outside the wiki and survives a vandal or a careless edit. It runs behind everything else and reads the pages anonymously through `api.php`: no login, so it never touches the sessions the other jobs use.

**Where a page goes.** `Pages/<language>/<wiki>/<title>` — `https://pokemon.fandom.com/ru/wiki/MediaWiki:Common.css` becomes `Pages/ru/pokemon/MediaWiki:Common.css`. A page of the Module namespace is filed under its canonical name, `Module:`, whatever the wiki calls the namespace, and a Lua module gets `.lua` unless its title already ends so: `Модуль:PokemonData/data` becomes `Module:PokemonData/data.lua`. A module's `/doc` page is wikitext and keeps its title as it is. A slash in a title is a directory. With `main_pages` (on by default) the main page of every wiki in the list is archived too, under the title the wiki itself gives it (`meta=siteinfo`, which is what `MediaWiki:Mainpage` sets).

**What a commit says.** One commit per changed page, with the message from `MYARCHIVE["messages"]`: `created` for a new file, `updated` when only the `owner` edited the page since the file's last commit, and `updated_by` — with `{editors}`, the accounts in the order they first edited — when somebody else did. The editors `MYARCHIVE["coauthors"]` links to a GitHub login are added as `Co-authored-by:`, so the commit shows on their profile too. A page equal to its file, or to its file with a final newline, is not committed; that is decided by comparing hashes, so an unchanged night costs one request to GitHub for the whole tree.

**What it needs, and what stays private.** The repository, the page list and the account links are `config.MYARCHIVE` in the untracked `config.py`; the token is `MYARCHIVE_GITHUB_TOKEN` in the untracked `src/.env`. Without both the module is off. To make the token: GitHub → *Settings* → *Developer settings* → *Personal access tokens* → *Fine-grained tokens* → *Generate new token*; *Resource owner* the owner of the repository, *Repository access* → *Only select repositories* and that one repository, *Permissions* → *Repository permissions* → *Contents: Read and write* (GitHub adds *Metadata: Read-only* by itself), and an expiry date you will remember to renew. The commits are authored by the account the token belongs to.

It reports to the service chats only when it committed something, could not reach a wiki or GitHub, or found a listed page missing — the last once per start of the bot, not every night.

### Localization

Every string the bot says is a key in the six files `i18n/en.json`, `es`, `pl`, `pt`, `ru` and `uk`, each entry carrying its text and its translation status. English is the reference: a key missing from a language falls back to it, and a key missing everywhere falls back to itself and to a line in the log. The files are read once at start-up, so an edit to them takes effect on the next restart.

**Each person chooses their language, and English is the default.** `/lang ru` on Telegram, `/lang code:` with a list to pick from on Discord, `/lang` alone to see which one is in use. The choice belongs to the account on that messenger and to nothing else — two people in one channel may read the bot in two languages — and choosing English deletes the stored choice, since English is what everybody gets without one. It used to be guessed: Telegram answered in the language of the person's app, Discord in `SERVICE_LANG`, so the same person read the bot in two languages and could choose neither.

**Everything a person is told follows their choice**, not only the replies to their commands: the dialog, the plan of a task, why it was refused, the notes it made along the way, how it ended, and the headings of the files it sends back. A refusal or a note is kept as a key rather than as text, because the same one is read twice — by the person, in their language, and by the service chats, in `SERVICE_LANG`.

**Two things cannot follow a person's choice**, because they are shown before the bot knows who is looking. The descriptions of the slash commands in Discord's command picker follow the language of the Discord app — English at base, the other five handed to Discord from the same i18n files. The presence line under the bot's name is English. The edit summaries on a wiki are the wiki's text, not the bot's messages, and stay as they are.

Any message that spells out a command spells it the way the messenger it goes to takes it. `/help` is built from one table that lists every command with the messengers it exists on, and a hint such as “See first what it would do, writing nothing” reads `/go 2 dry` on Telegram and `/go task_id: 2 dry: true` on Discord. It once did not, and a person on Discord, told to type something Discord's command picker cannot take, left `dry` unset and got a real run where they had asked for a preview.

### Service events and automatic backups

The chats in `SERVICE_CHATS` hear about the things a person would want to know: the bot starting and stopping, every task starting, progressing and ending, a news pass that changed the main pages or failed, a species walk however it ended, and a source channel that cannot be read. A news pass that found nothing to do says nothing — a report four times an hour is a report nobody reads.

The bot sends an encrypted copy of `src/fd.db` to the chats of `config.BACKUP_CHATS` twice a day, at 04:30 and 16:30 — half an hour behind the nightly sweep, so what leaves the machine is the swept database rather than one still carrying the page lists of runs that ended a month ago. `/backup` asks for the same file at any moment, and only the administrators in `config.ADMINS` may — the people appointed with `/wikiadmin` run wiki work and nothing else.

**The answer goes to the person who asked and to nobody else.** On Discord the reply is ephemeral and the command is allowed in a DM; on Telegram it works in a private chat only and says so in a group. Encryption is what makes the file safe to *store*, not safe to hand round: a channel or a group keeps it for as long as it exists, and a key can leak later than the file did.

**Encrypted because of where it goes.** A Telegram topic or a Discord channel keeps a file for as long as the chat exists and shows it to everybody who can read there, and `fd.db` holds who is appointed on which wiki and every task anybody has ever asked the bot to run. The snapshot is taken through SQLite's own online-backup API, so it is internally consistent even though the bot is writing while it is made, and it is encrypted before it leaves the process — an authenticated stream cipher built on BLAKE2, standard library only, no third-party crypto package. Whoever stores the file sees ciphertext they can neither read nor alter undetected. `BACKUP_KEY` is **this project's own** and belongs nowhere else; keep a copy off the server as well as on it, because a lost key makes every backup already taken unreadable for good.

**Without `BACKUP_KEY` there are no backups, not plaintext ones.** Building one raises rather than falling back, `/backup` says so to the person who asked, and the twice-daily job writes one line in the log and sends nothing. A deployment that has set `BACKUP_CHATS` but no key is the only case that complains; one that has set neither is simply a deployment that does not want backups, and says nothing at all.

**Restoring.** `python restore_backup.py fd.db.enc fd.db` from `src/`, with `BACKUP_KEY` in the environment or in `src/.env` — the same key the file was made with. A wrong key or an altered file fails loudly rather than producing a broken database. Stop the service before putting the result in place, for the reason [Running as a service](#running-as-a-service) gives.

### The wiki login

Pywikibot keeps its own directory, and the bot points it at `src/botconfig/`: the login cookie, the API cache and the throttle bookkeeping land there instead of in the operator's global Pywikibot installation, and no other project's account can reach this bot.

**On a wiki farm, each wiki needs a cookie jar of its own.** Pywikibot keeps one jar per process and names its file after the account, and `http.session.cookies` is that same object. Two wikis of one farm — `telepedia.fandom.com` and `radiopedia.fandom.com` — are served session cookies for `.fandom.com`, so they share it: logging in to the second replaces the first one's session, the first wiki starts answering as though a stranger were asking, and every edit there fails for a missing right while the same credentials work perfectly on the wiki that logged in last. The bot therefore gives each wiki a jar and a file of its own under `src/botconfig/cookies/`, and swaps them in before it says anything to that wiki. The sessions then live side by side, survive restarts, and no login can steal another's.

**A session does not last forever, and the bot checks.** Before each pass every wiki is asked who it thinks the bot is, which costs one request and answers the question that matters: a login session expires eventually, and when it does the library goes on believing it is signed in while the wiki treats every edit as a stranger's. Left alone that state outlives the process — it once cost a full day of passes, each failing the same way — so a session the wiki no longer recognises is thrown away and made again, cookies first (a stale one makes MediaWiki refuse the login outright). The log says `the session on telepedia:ru is no longer recognised — logging in again`, and then that it was restored.

**And when even that fails, the bot digs itself out.** It once did not: three days of dead news, two hundred and fifteen identical failures per wiki, and nothing but `systemctl restart fd_bot` would help. Emptying the cookie jar before the login did not survive to the request, because the library reloads the jar from disk inside `login()`; and `pywikibot.Site()` is a caching factory, so building the site "again" handed back the same object with the same stale login status, for the life of the process. Both are closed now: the clear is held until the login has gone out, and a wiki whose login fails has its cached Site, its jar and its cookie file thrown away before the second attempt — which is the state a freshly started process has, and that state was always known to work. A wiki that still refuses is then left alone for fifteen minutes, then thirty, then an hour, and tried again on its own. No pass of another wiki is affected, and no restart is needed. A wiki Pywikibot cannot address at all — a family that does not know the language — is a configuration error rather than a failed login, and is reported as one instead of being retried.

**The bot flag is the wiki's to give.** Every edit and every upload asks to be marked as a bot action, but MediaWiki honours that only for an account holding the `bot` right *on that wiki*, and the right takes two things at once: the account has to be in the local **bot group** (a bureaucrat adds it at `Special:UserRights`) and the BotPassword has to carry the **High-volume (bot) access** grant. Miss either and the bot still edits — its edits simply appear in Recent changes like anybody else's. The log line written at each login says which it is: `logged in to telepedia:ru as Example Bot (bot flag: yes)`.

The credentials go through Pywikibot's own password file, which the bot writes from `.env` at every start. The reason is the lifetime of the process: a login session expires eventually, and Pywikibot answers that by logging in again on its own — but only if it can find credentials. Handed nothing, it asks for a password on the console, and a bot that has been running unattended for a month would simply hang there. So `.env` stays the one place the secret is written by hand, and the generated `src/botconfig/user-password.cfg` is a runtime file, kept out of git like the cookies beside it.

That file is set to mode `600` on **every** start, and not only on the start that writes it. It is the wiki password in clear, it outlives the process, and a checkout, a deployment or a copy can each hand it back readable by every local user of the machine — which is exactly what once happened, a `664` from a checkout that stood until Pywikibot noticed it and said so in a warning.

**Pywikibot's own lines come through the bot's log.** The library keeps a logger of its own and, left alone, writes to the console through it — bare lines with no time and no level (`Logging in to telepedia:ru as ...`, `Page [[...]] saved`) in among the bot's own `2026-09-02 12:00:00,000 fd.publisher INFO ...`. In a journal that reads badly and cannot be filtered at all: a line with no level is invisible to `journalctl -p err` whatever it says. So `wiki/site.py` takes that logger over at import and lets its records travel up to the bot's own, where they arrive as `pywiki INFO Page [[...]] saved` like everything else. Anything the library says below `INFO` — its own verbose and debug chatter — is dropped rather than printed.

---

## Data collection and retention

The bot stores operational data in local SQLite (`src/fd.db`) to decide who may set it to work, to run the work it is asked for, and to run its modules. The full privacy policy lives in [PRIVACY.md](PRIVACY.md).

### What data is stored

- **Wiki administrators**
  - For each person appointed with `/wikiadmin`: the messenger, their numeric id there, the name they are shown under, their account name on Fandom, and who appointed them and when.
  - For a Telegram appointment made by `@name` that no account has claimed yet: the `@name`, the Fandom account, and who made it and when.
- **Tasks and schedules**
  - What was asked for, on which wiki, with which parameters, by whom (messenger, id, display name, Fandom account), when it ran and what it changed.
  - The page list of each run and what happened to each page.
  - For a repeating run, the same, plus when it is due and whether it still waits for approval.
- **Language choices**
  - For each person who chose a language other than English with `/lang`: the messenger, their numeric id there, the language, and when it was chosen.
- **The news module**
  - The posts of the followed channel: the text and its formatting, the timestamp, the message and album ids, the identifiers of the picture, the channel or person a repost came from, and whether the row came from Telegram or from the channel's web preview. A channel post carries no author: it is published under the channel's name, not a person's.
  - What each slot of each wiki holds: the message it came from and the identifier of the picture uploaded into it.
  - The bot's own bookkeeping: the id and `@name` the channel resolved to, when the last pass ran and what its error was.

Beside the database, a finished run leaves up to three files in `src/reports/` — wiki content and nothing else — and `src/botconfig/` holds the generated password file and one cookie file per wiki.

### Retention periods

- **Wiki administrators**: until `/remwikiadmin`.
- **Telegram invitations**: until the account holding the `@name` writes to the bot (the row then becomes an appointment keyed by the id), until withdrawn with `/remwikiadmin`, and never longer than **7 days**.
- **Task rows and schedules**: kept, as the record of who asked the bot to do what; a schedule until `/schedule del`.
- **Page lists of finished runs**: deleted after **30 days**.
- **Report files**: deleted after **14 days**.
- **Channel posts**: the newest **60** are kept; older rows are deleted as new ones arrive, since only the head of the channel can become a news.
- **Slot state and bookkeeping**: overwritten at every pass.
- **Language choices**: until the person chooses English, which deletes the row.

### Data usage boundaries

- The bot uses stored data only to decide who may ask it for work, to do that work and report on it, and to run its modules.
- Nothing is stored about anybody who is not appointed or invited, except the language they chose themselves: a message from anyone else is answered and forgotten.
- It does not implement analytics or tracking pipelines in this repository.
- Database backups are encrypted (authenticated BLAKE2 keystream + tag, standard library only) before leaving the process; the chats that keep them only ever hold ciphertext. The key lives in `BACKUP_KEY` and must be kept out of the repository.

---

## Acknowledgements

Fifteen of the nineteen mechanics are ports of scripts that ship with **[Pywikibot](https://github.com/wikimedia/pywikibot)** by the Pywikibot team and its contributors, licensed **MIT**. What was kept is each script's model — the options it offers, the order it does things in, and the decisions it refuses to make on a person's behalf — with its command line replaced by a dialog and its page list by this bot's own. Each module names the script it came from, its authors and its licence in its own docstring; the list is `replace`, `add_text`, `unlink`, `category`, `category_graph`, `interwiki`, `redirect` (which also folds in `fixing_redirects`), `image`, `delinker`, `movepages`, `protect`, `delete`, `revertbot`, `listpages` and `templatecount`.

The other four are not ports of anything third-party. `typos_ru`, `punct_ru` and `pravopys_uk`, and the masking layer under all three, come from the operator's own earlier wiki scripts; the typo lists they read are in the **AWB** format, which is a file format rather than code, and no AutoWikiBrowser source is used here. `cosmetic` is this bot's own as well, and deliberately so: Pywikibot has a `cosmetic_changes.py`, but it renames templates and rewrites links by rules that differ per project, which on somebody else's wiki is an opinion about their markup. This one touches whitespace and punctuation, which is the part nobody argues about.

Confederate Fandom is licensed under **Apache-2.0**.
