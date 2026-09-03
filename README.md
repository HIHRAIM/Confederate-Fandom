# Confederate Fandom

Confederate Fandom keeps the news block of a wiki's main page in step with a Telegram channel. It watches one channel, and four times an hour — at :00, :15, :30 and :45 — it writes the three latest posts into three templates and three files: the text of a post with its formatting and paragraphs, its date, its picture, a link back to the post under that picture, and — for a repost — where it was taken from. Nobody edits the main page by hand, and nothing is copied twice.

It can keep several wikis in step at once — the same three news, one account, each wiki written to on its own (see [More than one wiki](#more-than-one-wiki)).

It also has a second job on a wiki of its own: once a night it walks the articles and brings the names of Pokémon species to the standard ones (see [The species job](#the-species-job)).

And it does what it is asked. Nineteen kinds of work over any Fandom wiki — replace text, fix the spelling, tidy the markup, complete the interlanguage links, move, protect, delete, count, list — set going by a command in Discord or Telegram, once or on a schedule (see [Wiki work](#wiki-work)). Nothing runs beside anything else: everything goes through one queue, and what that buys is explained in [Jobs and the queue](#jobs-and-the-queue).

It is written with [aiogram](https://github.com/aiogram/aiogram) on the Telegram side and [Pywikibot](https://github.com/wikimedia/pywikibot) on the wiki side, and it runs as one process with an SQLite file beside it.

## Requirements

- Python **3.11**
- A Telegram bot token — and the bot must be an **administrator of the channel** it follows
- A Discord bot token, with the **Message Content Intent** switched on in the Developer Portal — the dialogs are answered with ordinary messages, and without that intent every answer arrives empty. The bot needs permission to write in the channels it is used in, and the application needs `applications.commands` when it is invited, or the slash commands do not appear
- A wiki account with a **BotPassword**, allowed to edit pages and to upload files on every wiki you publish to
- SQLite (uses local `src/fd.db`, no external database)
- Python packages:
  - `aiogram`
  - `discord.py`
  - `pywikibot`
  - `regex` — the spelling rules come from AWB lists that use variable-length lookbehind, which the built-in `re` will not compile. Without it seven of the 607 Russian rules are lost and the bot says so once at start-up

## What the bot needs

Two things are worth checking before anything else, because the bot is quiet rather than loud when either is missing.

- **Administrator rights in the channel.** Telegram delivers the posts of a channel to a bot only if that bot administrates it; a bot that merely subscribes receives nothing. There is also no way to *ask* for the posts made earlier: the bot hears about a post as it happens or never. A channel that was already running when the bot arrived is filled in from its public web preview instead — see [Posts from before the bot arrived](#posts-from-before-the-bot-arrived).
- **A wiki account with the two grants.** On `Special:BotPasswords`, the BotPassword needs *Edit existing pages* and *Upload new files / Upload, replace and move files*. Without the first the templates fail, without the second the pictures do; the bot reports both to the service chats and tries again on the next pass. On a wiki where the three templates do not exist yet, the account also needs the right to create pages — the first pass makes them. For the edits to be *marked* as bot edits, add the account to that wiki's bot group as well; see [The wiki login](#the-wiki-login).

## Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/HIHRAIM/Confederate Fandom
   cd Confederate Fandom
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

4. **Fill in the secrets.** Copy `src/.env.example` to `src/.env`:
   - `TELEGRAM_BOT_TOKEN` — the token from [@BotFather](https://t.me/BotFather).
   - `DISCORD_BOT_TOKEN` — the token from the Discord developer portal.
   - `WIKI_USERNAME` — the wiki account, without any suffix (`Example Bot`).
   - `WIKI_BOT_PASSWORD_SUFFIX` — the *name* of the BotPassword from `Special:BotPasswords` (`ExampleBot`), not the account name. The bot logs in as `<WIKI_USERNAME>@<WIKI_BOT_PASSWORD_SUFFIX>`.
   - `WIKI_BOT_PASSWORD` — the password that page generated.

   Environment variables that are already set take precedence over the file. `src/.env` must never be committed; neither must `src/botconfig/user-password.cfg`, which the bot writes from these values for Pywikibot to read (see [The wiki login](#the-wiki-login)).

5. **Fill in the configuration.** Copy `src/config.example.py` to `src/config.py` and edit:
   - `ADMINS["telegram"]` and `ADMINS["discord"]` — the numeric user IDs of the bot's own administrators, on each messenger. They are not stored in the database on purpose: no mishap there can hand out or take away control of the bot. Everybody else who is to run wiki work is appointed at runtime with `/wikiadmin`.
   - `SERVICE_CHATS["telegram"]` and `SERVICE_CHATS["discord"]` — where the bot reports what it did and what failed: Telegram chats as `"<chat_id>:<thread_id>"` (thread `0` is the plain group), Discord channels as numeric ids. Every report goes to both. Empty sets leave the log file as the only record.
   - `SERVICE_LANG` — the language those reports are written in.
   - `SOURCE_CHANNEL` — the channel to follow, as `@name` or as the numeric id.
   - `WIKIS` — every wiki the news go to, each as a Pywikibot family and language code; a wiki that keeps its news under other titles may carry its own `templates` and `files` tuples, and one whose stylesheet names the card's classes differently its own `css_prefix`.
   - `NEWS_TEMPLATES` / `NEWS_FILES` — the template pages and the file names, newest news first. Both tuples must be the same length, and that length is how many news the bot keeps.
   - `NEWS_CSS_PREFIX` — the stem of the card's CSS classes (`tp-news` gives `tp-news__item`, `tp-news__img`, `tp-news__body`, `tp-news__text` and `tp-news__tag`), for every wiki that does not name its own.
   - `NEWS_DATE_FORMAT` / `NEWS_MONTHS` — how the date is written (`26 августа 2026`) and the month names it is written with, which is a question of language rather than of the server's installed locales.
   - `FORWARD_FROM_CHAT` / `FORWARD_FROM_USER` — what a card says about a repost; `{name}` is the channel or the person it came from. Empty means say nothing.
   - `PUBLISH_AT_MINUTES`, `NEWS_TEXT_LIMIT`, `NEWS_TIMEZONE` — the minutes past the hour the wikis are written at, how long a news text may be, and the time zone its date is written in.
   - `PREVIEW_SYNC` / `PREVIEW_LIMIT` — whether to read the channel's public preview before every pass (which is how older posts and missed edits are picked up), and how many of its posts to consider.
   - `EDIT_SUMMARY` / `UPLOAD_SUMMARY` — the edit summaries, in the wikis' own language; `{link}` is the post the news came from.
   - `SPECIES_WIKI` / `SPECIES_AT` / `SPECIES_SUMMARY` / `SPECIES_LIMIT` — the wiki the species job walks, the time of day it runs at, the summary its edits carry, and a page cap for trying it out. `SPECIES_WIKI = None` switches the job off.
   - `WIKI_PUT_THROTTLE` — seconds Pywikibot waits between two edits. `0`, and deliberately so: an account with the bot flag is expected to edit at speed and the wiki throttles it on its own. Raise it for a wiki that asks.

6. **Set up the Discord application.** In the Developer Portal, on the *Bot* page, switch on the **Message Content Intent**: the dialogs are answered with ordinary messages, and without it every answer arrives empty. Invite the application with both `bot` and `applications.commands`, or the slash commands never appear. The tree is synced once when the gateway comes up, so a new command shows after a restart.

7. **Add a family file per wiki.** Pywikibot needs one Python file for each wiki in `WIKIS`, at `src/botconfig/families/<family>_family.py`, mapping the language code to the host and the script path. Only the wikis in `WIKIS` and `SPECIES_WIKI` need one written by hand — a wiki named in a task is looked up once and its file generated (`wiki/families.py`). The ones shipped with the project are the example to copy:

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

8. **Run the bot** — from `src/`, because the database, `.env` and Pywikibot's own directory are opened by relative path:
   ```bash
   cd src && python main.py
   ```

## Project structure

The code lives in `src/`. [ARCHITECTURE.md](ARCHITECTURE.md) describes how the pieces work together and carries a feature → file table.

| Path | What lives there |
|---|---|
| `main.py` | The entry point: the two messengers, the modules and the task queue |
| `scheduler.py` | The clock and the queue: what runs when, who goes first, and never two at once |
| `modules/` | The standing work: `telepedia/` for the news, `pokemon/` for the species names |
| `scripts/` | The nineteen mechanics, each named after the script it came from, plus the shared masking and cosmetics layer |
| `tasks/` | The task engine: the catalogue, the dialog, the page sources, the checks, the runner, the reports |
| `richtext.py` | Telegram's formatting — bold, italics, links — carried over into wikitext |
| `utils.py` | Localization runtime, the admin check, the service-chat reporter |
| `config.py` | This deployment's channel, wikis and pages (untracked) |
| `env_loader.py` | Reads `src/.env` into the environment |
| `i18n/` | The six localization files |
| `botconfig/` | Pywikibot's directory: its config, its family files, and one cookie file per wiki |
| `reports/` | The diffs and lists a run sends back, swept after two weeks (untracked) |
| `telegram_bot/` | The Telegram half: client, the channel collector, the commands, the dialogs |
| `discord_bot/` | The Discord half: client, the slash commands, the dialogs, the log channels |
| `wiki/` | The wiki half: the login, the generated families, the rights, the page and file writing |
| `db/` | The SQLite connection, the schema, and one module per domain |

## Commands

The same commands on both messengers — slash commands on Discord, ordinary commands on Telegram. Replies come in the language of the person who asked, when it is one of the six the project speaks.

**Wiki work.** For the administrators in `config.ADMINS`, and for the wiki administrators they appoint.

| Command | What it does |
|---|---|
| `/tasks` | The catalogue of mechanics, numbered |
| `/run [numbers or codes]` | Sets up a run, in a dialog. `/run 1 4` and `/run replace typos-ru` skip the first question |
| `/go <id>` | Confirms a prepared task and starts it |
| `/go <id> dry` | The same, but writes nothing: the diffs are computed and sent as a file, the wiki is untouched |
| `/jobs` | What is running, what is queued, and how the last few tasks ended |
| `/stop <id>` | Stops a task. What it has already written stays written |
| `/schedule` | The repeating runs; `/schedule on|off|del <id>` changes one |

**The news.** For the administrators in `config.ADMINS` only.

| Command | What it does |
|---|---|
| `/help` | What the bot does and which commands it takes |
| `/status` | The channel, the wikis, how many posts are stored, when the last pass ran and what it left behind, and what each of the three slots holds |
| `/update` | Runs a pass now instead of waiting for the next one |
| `/update force` | The same, but ignores which picture each slot already holds, so all three files are uploaded again to every wiki — the answer to a file that was changed or deleted on a wiki behind the bot's back |
| `/backfill` | Reads the channel's public web preview now: recovers the posts published before the bot was added and picks up their edits |
| `/backfill all` | The same, but also refreshes the posts the bot heard from Telegram itself — for a post edited while the bot was down |

**Access.** For the administrators in `config.ADMINS` only.

| Command | What it does |
|---|---|
| `/wikiadmin` | Who is appointed a wiki administrator |
| `/wikiadmin <who> <Fandom account>` | Appoints one. On Telegram *who* is a reply, an `@name` or a numeric id; on Discord it is a user |
| `/remwikiadmin <who>` | Takes the appointment away |

## Jobs and the queue

`scheduler.py` owns both the clock the jobs run by and the queue they wait in.

| Job | Priority | When | What it does |
|---|---|---|---|
| `news` | module | `PUBLISH_AT_MINUTES` — :00, :15, :30, :45 — and once at start-up | Catches up with the channel and rewrites the three templates and three files on every wiki of `WIKIS` |
| `species` | module | Once a day at `SPECIES_AT` | Walks the articles of `SPECIES_WIKI` and standardises the names of Pokémon species |
| `tasks` | task | Every minute, and whenever there is more to do | Fires the schedules that are due and walks one chunk of one task |
| `sweep` | task | Once a day at 04:00 | Throws away the page lists and report files of runs that are long over |

**One at a time, always.** Not because the logins would clash — each wiki has a session and a cookie file of its own, and the bot is signed in to all of them at once — but because Pywikibot is synchronous: every job goes through the same worker thread. A job that comes due while another is running waits its turn, and a job already waiting is not queued twice, so a long night cannot leave four news passes stacked behind it — only one.

**The modules go first.** The news and the species walk are what somebody's readers actually see, so they are registered at module priority and jump the queue. Everything a person asks for through a command runs behind them.

**And a long run gives the worker back.** A walk of nine thousand articles could not be allowed to hold the quarter-hourly news pass for an hour, so it is not one job: the task queue walks a *chunk* — fifty pages, or a minute, or until something more important arrives — and then puts itself back in the queue. A walk of a whole wiki is a hundred short jobs with the news slipping in between them, and it survives a restart, because the position is a row in the database and not a variable.

What each job reports differs on purpose. The news pass speaks only when it changed something or failed; four silent successes an hour are four messages nobody reads. The species walk reports however it ends, because a job that runs once a night and says nothing cannot be told from one that never ran. A task reports when it starts, every five hundred pages, and when it finishes.

## The species job

Once a night the bot walks every article of `SPECIES_WIKI` and replaces outdated Russian names of Pokémon species with the standard ones — 270 pairs, taken from the wiki's own `[[Модуль:PokemonData/fromNumber]]` and kept in `species/data/fromnumber_name_rules.tsv`.

The replacement is careful in ways that matter on a wiki:

- **The case is carried over** word by word: `Вайплюм` → `Вайлплюм`, `вайплюм` → `вайлплюм`, `ВАЙПЛЮМ` → `ВАЙЛПЛЮМ`.
- **A name inside a longer word is caught too**, but only when what follows it is a grammatical ending or `-ит` (`Скизорит` → `Сизорит`). Anything else is a word of its own — `Глайгермен`, `Троупринт`, `Брианна` — and is left alone and listed in the report.
- **Four names change how they decline** (`Тентакруэль`, `Драгалдж`, `Силвалл`, `Фион`) and carry an explicit table of endings. A form the table does not know is *not* replaced: it goes into the report for a human, which is how the bot avoids inventing `Фионае`.
- **File names are never touched.** `[[Файл:…]]` targets, `|изображение=` values, gallery lines, categories, interwiki, URLs and `<nowiki>`/`<pre>` are hidden behind placeholders before the pass and put back afterwards. Captions *are* corrected.
- **The pass is idempotent**: running it again changes nothing.

It does not rename pages and does not touch redirects: a title that moves drags redirects, links and categories behind it, and that is a different job with a different cost of error.

## Wiki work

Nineteen mechanics, each a Pywikibot script (or one of the operator's own) with its command line replaced by a dialog. `/tasks` prints them numbered; `/run` sets one going.

| Code | What it does | Rights it needs |
|---|---|---|
| `replace` | Find and replace text or a regular expression | edit |
| `addtext` | Add a block of text at the top, at the bottom or before the categories | edit |
| `unlink` | Take the links to one page out and leave the words | edit |
| `typos-ru` | Russian: 607 typo rules, punctuation and cosmetics | edit |
| `punct-ru` | Russian punctuation alone, at one of three levels of risk | edit |
| `pravopys-uk` | Ukrainian orthography of 2019, plus the typo list | edit |
| `cosmetic` | The wikifier alone: whitespace, headings, blank lines, dashes | edit |
| `category` | Add, remove or move a category | edit |
| `interwiki` | Complete the interlanguage links, move them to the end, sort them | edit |
| `redirect` | Fix double redirects, point links straight at the target, find the broken ones | edit |
| `image` | Swap a file for another, or take it out of everywhere it is shown | edit |
| `delinker` | Take deleted files out of the articles that still show them | edit |
| `movepages` | Rename by a prefix, a suffix or a regular expression | move |
| `protect` | Set or lift protection on editing, moving, re-uploading | protect |
| `delete` | Delete a list of pages | delete |
| `revertbot` | Undo one account's run of edits at the top of a page's history | edit |
| `listpages` | Write the page list to a file | — |
| `templatecount` | How many pages use the templates, and which | — |
| `category-graph` | The tree of subcategories, as text or as a `.dot` file | — |

**They compose.** Everything that rewrites wikitext runs over the same page in one pass and saves once: `replace` + `typos-ru` + `cosmetic` is one line in the history, with a summary built from what all three actually did. `/run replace typos-ru cosmetic` is how that is asked for.

**Any Fandom wiki, by domain.** The dialog asks for the wiki and takes anything a person is likely to paste — `telepedia.fandom.com/ru`, a link to an article, or the `family:lang` shorthand the bot prints. A wiki the bot has never seen is looked up once (`meta=siteinfo`) and a Pywikibot family file is generated for it; from then on it costs nothing.

### The dialog

Short on purpose. Which mechanics, which wiki, where the pages come from, what each mechanic must be told — and then **every optional switch of every chosen mechanic in one numbered message**, answered with the numbers you want separated by spaces, or `0` for none. Four mechanics with five switches each is one question, not twenty.

Then the task is created and the queue takes over: it plans, says how many pages it found and shows the first twenty, and waits. `/go <id>` runs it; `/go <id> dry` computes every diff and writes nothing, which is how a page list should be read before it is acted on. There is no cap on how many diffs come back — they arrive as a file.

### Who may ask, and what the bot checks

**Bot administrators** are the ids in `config.ADMINS` and are not stored anywhere: no database mishap can hand out or take away control of the bot. They may do everything.

**Wiki administrators** are appointed with `/wikiadmin`, by their account on the messenger and their account on Fandom. The appointment is global and deliberately cheap to give, because it is not what grants anything — before every run the bot asks *that wiki* whether that person holds rollback, content moderator, discussions moderator, administrator, bureaucrat or bot there. Somebody with no standing on a wiki cannot borrow the bot's.

**And the bot checks itself.** Before a task starts it must hold one of three statuses on that wiki — bot, content moderator or administrator — or it refuses and says so: a hundred edits from an account with no standing is what a wiki blocks. Then the rights each mechanic needs are checked against what the wiki says the session holds, and a missing one is reported as the *group* that would grant it, because «нужен статус модератора контента» is something a person can act on and «нужно право editprotected» is not.

### Once, or on a schedule

The last question of the dialog. A repeating run stores the same three things a task does — the wiki, the mechanics, the parameters — plus when it is due, in one of three shapes: at given minutes of every hour, at a time every day, or at a time on named weekdays. Each firing opens an ordinary task, so a scheduled run is watched, reported and stopped exactly like one asked for by hand.

The next moment is recomputed forward from *now* after every firing, so a bot that was down over its hour runs once when it comes back rather than once for every hour it missed.

### What comes back

Up to three files, and only the ones a run has something for.

| File | What is in it |
|---|---|
| `task-<id>.diff.txt` | Every change, as a unified diff per page, with the summary that was used |
| `task-<id>.report.txt` | Whatever a reading mechanic collected — the list, the counts, the tree |
| `task-<id>.errors.txt` | The pages that would not be written, and why |

They carry wiki content and nothing else. No traceback, no path on the host, no configuration: a failure is written as its type and message with anything path-shaped taken out, and the full traceback stays in the bot's own log. The files are a copy of what was already sent, and are swept after two weeks.

Every task also reports to the service chats — the Discord channel and the Telegram topic of `SERVICE_CHATS` — when it starts, every five hundred pages, and when it ends, naming who asked for it by their username and id in brackets. Never by a mention: a log that pings somebody every quarter of an hour is a log people mute.

### No invented limits

There is no ceiling on how many pages a run may touch and no delay between edits (`WIKI_PUT_THROTTLE` is 0). An account carrying the bot flag is expected to edit at speed, the wiki throttles it on its own if it wants to, and a limit invented here would only make a walk of a whole wiki take three hours instead of one. The dialog's own «сколько страниц взять максимум» is there so a run can be tried on twenty pages before it is let loose on nine thousand.

## How the news card is built

### From a post to a news card

A post published in the followed channel arrives as a `channel_post` update and is written to `channel_posts` — its text, its date, its album id and the largest size of its picture. Nothing is published at that moment: the wikis are written to on a schedule, so a channel having a busy morning costs the same three edits as a quiet one.

A pass runs at every minute past the hour named in `PUBLISH_AT_MINUTES` — `:00`, `:15`, `:30`, `:45` — and once more at start-up, so a restart is not a quarter of an hour of silence. The schedule is a clock, not a stopwatch: a bot started at twenty past still publishes at half past, and a pass that took two minutes does not push the next one two minutes late. Each pass reads the stored posts, folds them into news, and for each of the three slots uploads the picture and rewrites the template. The result is one card per template:

```
<div class="tp-news__item">
<div class="tp-news__img">[[File:Заглавная-Новость-1.jpg|link=https://t.me/example/512]]</div>
<div class="tp-news__body"><span class="tp-news__text">The text of the post, <b>formatting</b> and paragraphs kept, shortened.</span><span class="tp-news__tag">26 августа 2026</span><span class="tp-news__tag">Переслано из Радио и ТВ</span></div>
</div>
```

The link lives on the picture and points at the post the news came from. A channel with no public `@name` has no such link, and the card is written with `link=` — a picture that is not a link.

### What becomes a news

Three rules, and they are all in `news.py`:

- **An album is one news.** Telegram delivers a post with several pictures as several messages sharing a `media_group_id`; to a reader it is one post, so the bot folds them together, takes the text from whichever message carries it and the picture from the first one that has any.
- **Only posts with text count.** A picture with no words says nothing on a main page. A post without text is skipped and the next one down moves into its place.
- **The first picture wins, and a news without one shows none.** A post with several pictures shows the first of the gallery — the same one Telegram shows in the channel. A post with no picture is published as a card with no picture at all; see below.

### Formatting

A post is rarely plain text, and what it is written with survives the trip: **bold**, *italics*, underline, strikethrough, `code` and links all come out as wikitext on the card. Bold becomes `<b>`, a link becomes wikitext's `[url text]` — an `<a>` tag would be stripped by MediaWiki — and the rest follow.

The **paragraphs** survive too. A line break in the post becomes `<br>` in the card, and a gap of any size between two paragraphs comes out as exactly one blank line — a channel that separates two thoughts is worth following, a channel that pressed Enter eight times is not.

What a news card has no use for keeps its text and loses its markup: spoilers, blockquotes, mentions and custom emoji. Nothing else is invented: the card shows the post, escaped so that a stray `<`, `|` or `[[` in somebody's post cannot break the page it lands in.

The two sources describe formatting differently — the Bot API sends entities with offsets counted in UTF-16 units, the web preview sends HTML — and both are read into one form before anything else happens (`richtext.py`), which is also the form the database keeps. A post therefore reads the same whichever door it came in through, and the cut below moves the formatting with the text instead of recomputing it.

### Shortening the text

A post longer than `NEWS_TEXT_LIMIT` (600 characters) is cut where a reader would cut it. A sentence ending in the last part of the allowed window wins: the text stops there and an ellipsis takes the place of the full stop, so the card reads as a finished thought with more behind it. Failing that, the cut is made at the last whole word, and a comma or dash left dangling goes with it. The result, ellipsis included, is never longer than the limit.

### Reposts

Most of what a news channel publishes is taken from somewhere else, and the card says so. A post forwarded into the channel gets one more tag after the date, in the same style as the date itself:

- from a channel — `Переслано из Радио и ТВ в Ростове-на-Дову и области`
- from a person — `Переслано от @someone`

The wording is `FORWARD_FROM_CHAT` and `FORWARD_FROM_USER` in the configuration, so it follows the wikis' language; setting either to an empty string turns that half off. The tag reuses the date's CSS class deliberately: a note under a news looks like a note under a news, and no stylesheet needs a new rule for it.

The two sources differ in what they can tell. Telegram names a person by their `@name` where they have one; the web preview only ever shows the name they display, and tells a channel from a person by whether that name is a link.

### Pictures, and cards without one

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

### More than one wiki

`config.WIKIS` lists every wiki the news go to; one entry or five, the mechanics are the same:

```python
WIKIS = (
    {"family": "hihraimtest", "lang": "ru"},
    {"family": "telepedia", "lang": "ru"},
)
```

The three news are the same everywhere — built once, from the same three posts, with the same text and the same link. What belongs to a wiki is where they land, what they are called there and what it already holds: its `templates` and `files`, the `css_prefix` its stylesheet knows the cards by (its own, when the entry names them; the shared `NEWS_TEMPLATES` / `NEWS_FILES` / `NEWS_CSS_PREFIX` otherwise), and its own row per slot in the database. Each wiki is written to on its own turn, so a wiki that is down, or that refuses an edit, costs its own news and nobody else's — the others are published, and the next pass retries the one that failed.

One account serves them all: the bot logs in once per wiki with the same BotPassword and keeps the sessions side by side. What it needs on each is the same pair of grants, plus the right to create pages on a wiki where the three templates do not exist yet — the first pass makes them.

A picture is fetched from Telegram **once per pass**, however many wikis are missing it, and then uploaded only to those that are. A wiki that already holds it is left alone. If the download fails, the wikis that already have the picture keep showing it, and the ones that do not publish the card without an image block rather than pointing at a file holding an older news.

A wiki whose stylesheet calls the cards something else says so in its entry:

```python
{"family": "radiopedia", "lang": "ru", "css_prefix": "rp-news"}
```

and its three templates come out as `rp-news__item`, `rp-news__img`, `rp-news__body`, `rp-news__text` and `rp-news__tag` while every other wiki keeps `tp-news`.

Note what the bot does *not* do on a new wiki: it does not touch the main page and it does not add the CSS the cards are styled with — it has no right to edit the interface, deliberately. Both are yours to do; until they are done the cards sit on the wiki, correct and unstyled, showing nowhere.

### What a pass skips

A pass that finds nothing to do leaves no trace on any wiki:

- **A file is uploaded only when it would change.** Every slot of every wiki remembers the `file_unique_id` of the picture it holds; a news whose picture is already up there is published without a byte moving. `/update force` is what overrides that.
- **A template is edited only when it would change.** The page is compared with what it should say before it is saved. This also means the bot quietly undoes a hand-made edit to one of the three templates at the next pass — they belong to it.
- **A slot is independent of the other two, and of the other wikis.** A file that will not upload fails its own slot on its own wiki; everything else goes through, and only what succeeded is recorded, so the next pass retries exactly what did not.
- **Fewer news than slots leaves the rest alone.** A channel with two posts fills two slots; the third keeps what it had rather than being blanked.

### Posts from before the bot arrived

The Bot API has no history at all: a bot is told about a channel post as it happens and can never ask for an earlier one. What Telegram does serve is the channel's **public web preview** — the page `t.me/s/<name>` a browser sees with no account — and that is where the bot gets the older posts from.

The same page answers a second question — **what changed** — because the Bot API is no better on edits than on history: a post corrected while the bot was down produces no update it will ever see.

So the preview is read before every pass (`PREVIEW_SYNC`), and each time it is read the bot does two things: it stores the posts it does not have, and it refreshes the ones whose text, formatting or picture no longer match. The preview holds about twenty posts, which is plenty for three news; `PREVIEW_LIMIT` caps how many are considered. `/backfill` does the same on demand.

One rule keeps that from doing damage: **a post the bot heard from Telegram itself is not refreshed from the preview.** Its row carries the larger picture and the text Telegram handed over, while the preview sometimes shortens a long link — comparing the two would rewrite the templates over a difference nobody can see. Those posts are corrected by `edited_channel_post`, which arrives the moment somebody edits them. `/backfill all` is the way out of the rule when a post really was edited while the bot was away.

An album, finally, is a single block in the preview, so it arrives as one post showing the first picture of the gallery — which is what a news is anyway.

The limits are the preview's own: a channel with no public `@name` has no preview, a private channel serves none, its pictures are smaller than the ones the Bot API hands over, and the markup is undocumented and can change — which is why a failed read is reported and let go rather than stopping anything.

### What the bot cannot see

- **Deletions.** Telegram does not tell bots when a channel post is deleted, and the preview stops showing it rather than saying it is gone. A post removed from the channel stays a news until three newer posts have pushed it out; `/update` after deleting it does not help, because the bot's copy is what it publishes from. Edits, unlike deletions, do reach the wikis: through `edited_channel_post` while the bot is running, and through the preview afterwards (see above).
- **Anything in a channel it does not follow.** One channel is followed at a time, the one in `SOURCE_CHANNEL`.

### Localization

Every string the bot says is a key in the six files `i18n/en.json`, `es`, `pl`, `pt`, `ru` and `uk`, each entry carrying its text and its translation status. English is the reference: a key missing from a language falls back to it, and a key missing everywhere falls back to itself and to a line in the log. Replies follow the language of the person who typed the command; the service chats follow `SERVICE_LANG`. The files are read once at start-up, so an edit to them takes effect on the next restart.

### Service events

The chats in `SERVICE_CHATS` hear about the things a person would want to know: the bot starting and stopping, a pass that changed the main page, a pass that failed, and a source channel that cannot be read. A pass that found nothing to do says nothing — a report four times an hour is a report nobody reads.

### The wiki login

Pywikibot keeps its own directory, and the bot points it at `src/botconfig/`: the login cookie, the API cache and the throttle bookkeeping land there instead of in the operator's global Pywikibot installation, and no other project's account can reach this bot.

**On a wiki farm, each wiki needs a cookie jar of its own.** Pywikibot keeps one jar per process and names its file after the account, and `http.session.cookies` is that same object. Two wikis of one farm — `telepedia.fandom.com` and `radiopedia.fandom.com` — are served session cookies for `.fandom.com`, so they share it: logging in to the second replaces the first one's session, the first wiki starts answering as though a stranger were asking, and every edit there fails for a missing right while the same credentials work perfectly on the wiki that logged in last. The bot therefore gives each wiki a jar and a file of its own under `src/botconfig/cookies/`, and swaps them in before it says anything to that wiki. The sessions then live side by side, survive restarts, and no login can steal another's.

**A session does not last forever, and the bot checks.** Before each pass every wiki is asked who it thinks the bot is, which costs one request and answers the question that matters: a login session expires eventually, and when it does the library goes on believing it is signed in while the wiki treats every edit as a stranger's. Left alone that state outlives the process — it once cost a full day of passes, each failing the same way — so a session the wiki no longer recognises is thrown away and made again, cookies first (a stale one makes MediaWiki refuse the login outright). The log says `the session on telepedia:ru is no longer recognised — logging in again`, and then that it was restored.

**The bot flag is the wiki's to give.** Every edit and every upload asks to be marked as a bot action, but MediaWiki honours that only for an account holding the `bot` right *on that wiki*, and the right takes two things at once: the account has to be in the local **bot group** (a bureaucrat adds it at `Special:UserRights`) and the BotPassword has to carry the **High-volume editing** grant. Miss either and the bot still publishes — its edits simply appear in Recent changes like anybody else's. The log line written at each login says which it is: `logged in to telepedia:ru as Example Bot (bot flag: yes)`.

The credentials go through Pywikibot's own password file, which the bot writes from `.env` at every start. The reason is the lifetime of the process: a login session expires eventually, and Pywikibot answers that by logging in again on its own — but only if it can find credentials. Handed nothing, it asks for a password on the console, and a bot that has been running unattended for a month would simply hang there. So `.env` stays the one place the secret is written by hand, and the generated `src/botconfig/user-password.cfg` is a runtime file, kept out of git like the cookie beside it.

That file is set to mode `600` on **every** start, and not only on the start that writes it. It is the wiki password in clear, it outlives the process, and a checkout, a deployment or a copy can each hand it back readable by every local user of the machine — which is exactly what once happened, a `664` from a checkout that stood until Pywikibot noticed it and said so in a warning.

**Pywikibot's own lines come through the bot's log.** The library keeps a logger of its own and, left alone, writes to the console through it — bare lines with no time and no level (`Logging in to telepedia:ru as ...`, `Page [[...]] saved`) in among the bot's own `2026-09-02 12:00:00,000 fd.publisher INFO ...`. In a journal that reads badly and cannot be filtered at all: a line with no level is invisible to `journalctl -p err` whatever it says. So `wiki/site.py` takes that logger over at import and lets its records travel up to the bot's own, where they arrive as `pywiki INFO Page [[...]] saved` like everything else. Anything the library says below `INFO` — its own verbose and debug chatter — is dropped rather than printed.

## Deploying an update

Two things about the file layout are worth respecting when a running instance is updated.

**Stop the service before you swap files.** `src/fd.db` is open by the running process. Replacing it underneath leaves the process writing through its old handle into a file nobody will read again — and the write-ahead log (`fd.db-wal`) beside it belongs to the file that was there when it was written. Never delete a `-wal` file to "clean up": it holds the newest posts and slots, and SQLite folds it back in on the next open. `systemctl stop fd-bot`, copy, `systemctl start fd-bot`.

**Give the process a moment to close.** A stop signal reaches the bot mid-sleep between passes; it answers by ending both of its tasks and closing its sessions, which takes a moment rather than the thirty seconds a service manager waits before killing it outright. A killed process is not a disaster — nothing is written mid-edit — but it leaves the database's log to be replayed at the next start, which is exactly the state worth not being in when the files are also being swapped.

## Data collection and retention

The bot stores what it needs to publish and nothing else. In `src/fd.db`:

- **The posts of the followed channel** — the text and its formatting, the timestamp, the message and album ids, the identifiers of the picture, and whether the row came from Telegram or from the channel's web preview. Channels are published under the channel's name, not a person's: a channel post carries no author. The newest 60 posts are kept and the rest are deleted as new ones arrive, since only the head of the channel can become a news.
- **What each slot holds** — the message a slot came from and the identifier of the picture uploaded into it, which is what lets a pass skip an upload.
- **The bot's own bookkeeping** — the id and `@name` the channel resolved to, when the last pass ran and what its error was.
- **The wiki administrators** — for each person appointed with `/wikiadmin`: which messenger, their numeric id there, the name they are shown under, their account name on Fandom, and who appointed them and when. This is the only place the bot stores anything about a person, and it stores it because every one of those five things is needed to answer «может ли этот человек запустить эту работу на этой вики». `/remwikiadmin` deletes the row.
- **The tasks and the schedules** — what was asked for, on which wiki, by whom (the same platform, id, display name and Fandom account), when it ran and what it did. The page list of a finished run is deleted after thirty days; the row itself is kept, because it is the record of who asked the bot to do what.

No reader of the channel is recorded at all, and no user of a wiki except the administrators the owner appoints. Note that the point of the bot is publication: the text and the picture of a post reach a public wiki, under a link back to the post. [PRIVACY.md](PRIVACY.md) is the longer version of this section.
