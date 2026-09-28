"""Template for src/config.py — this deployment's administrators and modules.

Copy it to src/config.py and fill in the values; the real file is deliberately
untracked (it names particular people, chats and wikis), so this template is
the documentation of what the bot expects to find there.

The wiki work people ask for through /run needs only the first part: the
accounts, the administrators, the chats. The three modules below it — the
news, the species names and the page archive — ship switched off, and a
module that is off registers no job and is not mentioned anywhere; turn on
only what this deployment is for.

Secrets are never written here: the Telegram token and the wiki bot password
come from src/.env through env_loader (see .env.example).
"""
import os

from env_loader import load_env
load_env()

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
DISCORD_TOKEN = os.environ["DISCORD_BOT_TOKEN"]

# The wiki account. WIKI_BOT_PASSWORD_SUFFIX is the name of the BotPassword
# (Special:BotPasswords), not the account name: the login name the bot sends is
# "<WIKI_USERNAME>@<WIKI_BOT_PASSWORD_SUFFIX>". The BotPassword needs the
# "Edit existing pages" and "Upload new files / Upload, replace and move files"
# grants for the news, "High-volume (bot) access" for the bot flag, and — for
# the mechanics that delete, move or protect — the matching grants beside them.
WIKI_USERNAME = os.environ["WIKI_USERNAME"]
WIKI_BOT_PASSWORD_SUFFIX = os.environ["WIKI_BOT_PASSWORD_SUFFIX"]
WIKI_BOT_PASSWORD = os.environ["WIKI_BOT_PASSWORD"]

# How long Pywikibot waits between two edits, in seconds. Zero, and that is a
# decision rather than an oversight: an account carrying the bot flag on a
# Fandom wiki is expected to edit at speed, the wiki throttles it on its own if
# it wants to, and a delay invented here would only make a walk of nine
# thousand pages take three hours instead of one.
WIKI_PUT_THROTTLE = 0

# The bot's own administrators, by their numeric id on each messenger. They
# may use every command. Hard-coded here rather than stored, so that no
# database mishap can hand out or take away control of the bot.
#
# The other kind of person who may set the bot to work is a "wiki
# administrator", appointed at runtime with /wikiadmin and stored in the
# database (db/admins.py). That appointment grants nothing on its own: before
# every run the bot asks the wiki itself whether that person holds rights
# there.
#
# Lists rather than sets, because the order is used: the first Discord id is
# the one pinged when a repeating run waits for approval (SCHEDULE_APPROVAL).
ADMINS = {
    "telegram": [ADMINISTRATOR_ID, ADMINISTRATOR_ID],
    "discord": [ADMINISTRATOR_ID, ADMINISTRATOR_ID],
}

# Where the bot reports: a failed wiki edit, a failed upload, a start and a
# stop, a nightly walk, and every task — that it began, how far it has got and
# how it ended, naming who asked for it. Every report goes to both messengers.
# Telegram keys are '<chat_id>:<thread_id>' — thread 0 is the plain group;
# Discord keys are numeric channel ids. Empty sets leave the log file as the
# only record.
SERVICE_CHATS = {
    "telegram": {
        "CHAT_ID",  # Example: -1000000000000:00000
    },
    "discord": {
        CHANNEL_ID,
    },
}

# Where the encrypted database backup goes: twice a day on its own, and on
# /backup when an administrator asks. Same shape as SERVICE_CHATS, and
# deliberately a separate setting rather than a default to it — the file is the
# whole database (who is appointed on which wiki, every task ever asked for),
# and the chat that reads status lines is rarely the chat that should keep one.
# It is encrypted before it leaves the process, with BACKUP_KEY from .env;
# without that key nothing is sent and nothing is written in clear. Leave the
# sets empty to make no automatic backups at all.
BACKUP_CHATS = {
    "telegram": set(),
    "discord": set(),
}

# The language service messages are written in — one of the six the i18n files
# cover: en, es, pl, pt, ru, uk. Replies to a command follow the language of
# the person who sent it instead.
SERVICE_LANG = "ru"

# Whether a repeating run set up by a wiki administrator waits for a bot
# administrator's yes before it starts. On, it is created switched off and a
# message with two buttons goes to the Discord channels of SERVICE_CHATS,
# pinging the first Discord id of ADMINS; yes starts it, no deletes it and
# tells the person privately. A bot administrator's own schedules never wait.
# False lets wiki administrators set up repeating runs on their own.
SCHEDULE_APPROVAL = True

# ---------------------------------------------------------------------------
# The news module (modules/teleradiopedia): the newest posts of a Telegram
# channel as news cards on the main pages of one or several wikis. Off while
# SOURCE_CHANNEL is None or WIKIS is empty.

# SOURCE_CHANNEL — the channel whose posts become the news. '@name' or the
# numeric id; the bot must be an administrator of it, otherwise Telegram
# delivers no channel_post updates and the bot collects nothing (see README:
# What the bot needs). The public link of a post is built from the channel's
# @name, so a channel without one gets news with no link on the image.
SOURCE_CHANNEL = None  # Example: "@CHANNEL_NAME"

# WIKIS — every wiki the news are published to, as Pywikibot families and
# language codes. All of them get the same three news; each is written to on
# its own, so one wiki being down or refusing an edit does not stop the others.
# Each family file lives in src/botconfig/families/<family>_family.py — that is
# what maps the code to the host and the script path (see README: Setup) — and
# the wiki account needs its edit and upload rights on every wiki listed here.
# A wiki that keeps its news under different titles may carry its own
# 'templates' and 'files' tuples; one whose stylesheet names the card's classes
# differently may carry its own 'css_prefix'. Without them the values below are
# used.
WIKIS = (
    # {"family": "FAMILY_NAME", "lang": "ru"},
    # {"family": "OTHER_FAMILY", "lang": "ru",
    #  "css_prefix": "other-news",
    #  "templates": ("Template:Main/News-1", "Template:Main/News-2", "Template:Main/News-3"),
    #  "files": ("Main-News-1.jpg", "Main-News-2.jpg", "Main-News-3.jpg")},
)

# The three template pages and the three files every wiki uses unless it says
# otherwise, newest news first. Both tuples must be the same length; that
# length is how many news the bot keeps. Template titles carry their namespace,
# file names do not.
NEWS_TEMPLATES = (
    "Шаблон:Заглавная/Новость-1",
    "Шаблон:Заглавная/Новость-2",
    "Шаблон:Заглавная/Новость-3",
)
NEWS_FILES = (
    "Заглавная-Новость-1.jpg",
    "Заглавная-Новость-2.jpg",
    "Заглавная-Новость-3.jpg",
)

# The minutes past the hour at which the news are rebuilt: 00, 15, 30 and 45
# means four passes an hour, on the clock — the pass at the top of the next
# hour is the '00' of that hour, not a fifth entry here. The posts themselves
# arrive as they are published; this is only when the wikis are written to.
# A pass also runs once at start-up, so a restart does not wait for the mark.
PUBLISH_AT_MINUTES = (0, 15, 30, 45)

# The Bot API hands out no history and no edit the bot was not listening for,
# so a bot added to an established channel sees nothing until the next post,
# and a post corrected while the bot was down stays wrong on the wikis.
# PREVIEW_SYNC answers both by reading the channel's public web preview
# (t.me/s/<name>) before every pass: posts that are missing are added, and
# posts the preview itself gave us are refreshed when their text, formatting
# or picture has changed. A post the bot heard from Telegram is never
# overwritten this way — `/backfill all` is the manual door to that.
# PREVIEW_LIMIT caps how many of the preview's posts are considered; it shows
# about twenty. Both are useless for a channel with no public @name, which has
# no preview to read.
PREVIEW_SYNC = True
PREVIEW_LIMIT = 20

# NEWS_CSS_PREFIX — the stem of the CSS classes a news card is built from:
# '<prefix>__item', '__img', '__body', '__text' and '__tag', the last of which
# carries both the date and the repost line. The wiki's own stylesheet is what
# gives them a look, and the bot cannot edit it — a wiki that has no such rules
# yet shows the cards unstyled until someone adds them.
NEWS_CSS_PREFIX = "tp-news"

# How long the text of one news may be, in characters. Longer posts are cut at
# the last sentence that fits, or at the last whole word, and end with '…'
# (news.py: shorten).
NEWS_TEXT_LIMIT = 600

# The time zone the card's date is rendered in. Telegram timestamps are UTC;
# readers of the wiki are not.
NEWS_TIMEZONE = "Europe/Moscow"

# How that date is written. {day} is the day of the month without a leading
# zero, {month} is taken from NEWS_MONTHS (in whatever form the language needs
# after a number — Russian wants the genitive: "26 августа 2026"), {year} is
# the four digits. The names live here rather than in the system's locale,
# which a server may not have installed at all.
NEWS_DATE_FORMAT = "{day} {month} {year}"
NEWS_MONTHS = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)

# What a card says about a post that is a repost, written after the date in a
# tag of its own. {name} is the channel's title or the person's @name. Leave
# either empty to say nothing for that kind of repost.
FORWARD_FROM_CHAT = "Переслано из {name}"
FORWARD_FROM_USER = "Переслано от {name}"

# The edit summaries, in the wiki's own language. {link} is the post the news
# came from.
EDIT_SUMMARY = "Обновление новости с {link}"
UPLOAD_SUMMARY = "Изображение новости с {link}"

# ---------------------------------------------------------------------------
# The species module (modules/pokemon): walking one wiki's articles and
# bringing the names of Pokemon species to the standard ones. SPECIES_WIKI names the wiki
# the way WIKIS does — a Pywikibot family and a language code, with its family
# file beside the others. SPECIES_AT is the local time it runs at, once a day;
# a job that comes due while another is running waits its turn rather than
# starting beside it (scheduler.py). SPECIES_LIMIT stops the walk after that
# many pages and is meant for trying it out — 0 walks the whole namespace.
# Off while SPECIES_WIKI is None.
SPECIES_WIKI = None  # Example: {"family": "FAMILY_NAME", "lang": "ru"}
SPECIES_AT = "20:00"
SPECIES_SUMMARY = "стандартизация названий видов покемонов"
SPECIES_LIMIT = 0

# Whether the walk refuses to start when the account has no bot flag on that
# wiki. It is on by default because the walk is hundreds of edits at once:
# unflagged, they arrive in Recent changes as a flood. The flag needs both
# the local bot group and the "High-volume (bot) access" grant on the BotPassword.
SPECIES_REQUIRE_BOT_FLAG = True

# ---------------------------------------------------------------------------
# The archive module (modules/myarchive): chosen wiki pages committed to a
# GitHub repository once a night, one commit per changed page. Off while
# MYARCHIVE is None or MYARCHIVE_GITHUB_TOKEN is missing from src/.env.
#
#   repo       — "owner/name" of the repository.
#   branch     — optional; the repository's default branch otherwise.
#   at, timezone — when the pass runs; "00:00" in "Europe/Kyiv" by default.
#                It waits behind every other job, a person's task included.
#   pages      — full page addresses: https://<wiki>.fandom.com/<lang>/wiki/<Title>.
#   main_pages — also archive the main page of every wiki in `pages`
#                (True by default).
#   owner      — the Fandom account whose edits alone make a plain "updated".
#   coauthors  — Fandom account -> GitHub login, added as co-authors of a
#                commit that archives their edits.
#   messages   — the commit messages; {editors} is the list of accounts.
#
# A page goes to Pages/<lang>/<wiki>/<Title>; a Lua module to
# Pages/<lang>/<wiki>/Module:<Name>.lua.
MYARCHIVE = None
# MYARCHIVE = {
#     "repo": "OWNER/REPOSITORY",
#     "pages": [
#         "https://EXAMPLE.fandom.com/ru/wiki/MediaWiki:Common.css",
#         "https://EXAMPLE.fandom.com/ru/wiki/Модуль:EXAMPLE",
#     ],
#     "owner": "FANDOM_ACCOUNT",
#     "coauthors": {"FANDOM_ACCOUNT": "GITHUB_LOGIN"},
#     "messages": {
#         "created": "сохранён файл",
#         "updated": "обновление",
#         "updated_by": "обновление после правок {editors}",
#     },
# }
