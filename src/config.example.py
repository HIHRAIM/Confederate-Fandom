"""Template for src/config.py — this deployment's channel, wiki and pages.

Copy it to src/config.py and fill in the values; the real file is deliberately
untracked (it names one particular channel and one particular wiki), so this
template is the documentation of what the bot expects to find there.

Secrets are never written here: the Telegram token and the wiki bot password
come from src/.env through env_loader (see .env.example).
"""
import os

from env_loader import load_env
load_env()

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

# The wiki account. WIKI_BOT_PASSWORD_SUFFIX is the name of the BotPassword
# (Special:BotPasswords), not the account name: the login name the bot sends is
# "<WIKI_USERNAME>@<WIKI_BOT_PASSWORD_SUFFIX>". The BotPassword needs the
# "Edit existing pages" and "Upload new files / Upload, replace and move files"
# grants; nothing else.
WIKI_USERNAME = os.environ["WIKI_USERNAME"]
WIKI_BOT_PASSWORD_SUFFIX = os.environ["WIKI_BOT_PASSWORD_SUFFIX"]
WIKI_BOT_PASSWORD = os.environ["WIKI_BOT_PASSWORD"]

# Telegram user IDs allowed to use /status and /update. Everyone else is
# answered with the "not an admin" reply.
ADMINS = {
    "telegram": {ADMINISTRATOR_ID, ADMINISTRATOR_ID},
}

# Chats the bot reports to: a failed wiki edit, a failed upload, a start and a
# stop. '<chat_id>:<thread_id>' — thread 0 is the plain group. An empty set
# leaves the log file as the only record.
SERVICE_CHATS = {
    "telegram": {
        "CHAT_ID",  # Example: -1000000000000:00000
    },
}

# The language service messages are written in — one of the six the i18n files
# cover: en, es, pl, pt, ru, uk. Replies to a command follow the language of
# the person who sent it instead.
SERVICE_LANG = "ru"

# SOURCE_CHANNEL — the channel whose posts become the news. '@name' or the
# numeric id; the bot must be an administrator of it, otherwise Telegram
# delivers no channel_post updates and the bot collects nothing (see README:
# What the bot needs). The public link of a post is built from the channel's
# @name, so a channel without one gets news with no link on the image.
SOURCE_CHANNEL = "@CHANNEL_NAME"

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
    {"family": "FAMILY_NAME", "lang": "ru"},
    {"family": "OTHER_FAMILY", "lang": "ru",
     "css_prefix": "other-news",
     "templates": ("Template:Main/News-1", "Template:Main/News-2", "Template:Main/News-3"),
     "files": ("Main-News-1.jpg", "Main-News-2.jpg", "Main-News-3.jpg")},
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
# '<prefix>__item', '__img', '__body', '__text', '__date'. The wiki's own
# stylesheet is what gives them a look, and the bot cannot edit it — a wiki
# that has no such rules yet shows the cards unstyled until someone adds them.
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
