"""Shared helpers with no half of their own: the localization runtime, the
admin check and the service-chat reporter.

The localization runtime is the bulk of it. The six i18n/<lang>.json files are
read once at import into two shapes — `_LOCALE` (per key, per language, what
`localized` reads) and `_LOCALE_STATUS` (translation status per key) — so a
lookup at reply time is a dict access. A consequence worth knowing: edits to
the JSON files take effect on restart, not immediately.

Paths are resolved through `__file__`, so this module must stay directly in
src/: one directory deeper and i18n/ is no longer found and every reply falls
back to its own key.

Not this module's zone: anything that sends (telegram_bot/), the database
(db/), the wiki (wiki/) or the shape of a news (news.py).
"""
import json
import logging
import os

from config import ADMINS, PUBLISH_AT_MINUTES, SERVICE_CHATS, SERVICE_LANG

try:
    from config import BACKUP_CHATS
except ImportError:
    BACKUP_CHATS = {}
"""Where the encrypted database backups go, in the shape SERVICE_CHATS uses.

Optional, and read the way wiki/site.py reads WIKI_PUT_THROTTLE: a deployment
whose config.py predates backups keeps starting, it simply makes none. Kept
apart from SERVICE_CHATS deliberately rather than defaulting to it — a
backup is the whole database, and the chat that reads status lines is rarely
the chat that should hold one."""

logger = logging.getLogger("fd.utils")

SUPPORTED_LANGS = {"ru", "uk", "pl", "en", "es", "pt"}
DEFAULT_LANG = "en"

_I18N_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "i18n")

def _load_i18n():
    """Build the runtime localization structures from the i18n/<lang>.json
    files.

    Returns (locale, status):
      locale[key][lang] = text
      status[key][lang] = 'verified' | 'unverified' | 'untranslated'
    """
    locale, status = {}, {}
    if not os.path.isdir(_I18N_DIR):
        logger.warning("i18n directory %s is missing — replies fall back to their keys", _I18N_DIR)
        return locale, status
    for fname in sorted(os.listdir(_I18N_DIR)):
        if not fname.endswith(".json"):
            continue
        lang = fname[:-5]
        with open(os.path.join(_I18N_DIR, fname), encoding="utf-8") as f:
            entries = json.load(f)
        for key, entry in entries.items():
            locale.setdefault(key, {})[lang] = entry["text"]
            status.setdefault(key, {})[lang] = entry.get("status", "unverified")
    return locale, status

_LOCALE, _LOCALE_STATUS = _load_i18n()

def localized(key, lang, **kwargs):
    """The text of a reply in one language, with its placeholders filled.

    Falls back to the reference language and finally to the key itself, so a
    key the i18n files do not have yet still produces something to send and a
    line in the log rather than an exception in the middle of a reply."""
    table = _LOCALE.get(key)
    if table is None:
        logger.warning("Missing localization key %r — i18n files are older than the code?", key)
        table = {}
    template = table.get(lang) or table.get(DEFAULT_LANG) or key
    try:
        return template.format(**kwargs)
    except Exception:
        return template

PAGE_CHARS = 1800
"""How much text one page of a long answer carries, in characters.

Well under what either messenger accepts — Discord takes 4096 in an embed
description, Telegram 4096 in a message — because the limit that matters is
not what the API allows but how much a person reads before the buttons
scroll off the screen. One number for both halves, so the same list pages
the same way wherever it is read."""

def paginate(lines, budget=PAGE_CHARS):
    """Group lines into pages of roughly equal size. -> list of strings.

    Two rules, and the second is the reason this is not four lines of greedy
    filling. A page never exceeds `budget`, and no line is ever split: an
    entry cut in half across a button press is worse than a short page.

    Greedy filling obeys both and still looks wrong — nineteen mechanics come
    out as one page of 1790 characters and one of 211, which reads as a bug
    rather than as a second page. So the number of pages is worked out first,
    from the total length, and the lines are then dealt out evenly between
    that many. When an even deal happens to overflow a page — lines differ in
    length, and the long ones can land together — one more page is added and
    the deal is made again. It terminates: by the time there is a page per
    line, every page is one line, and every line was cut to fit the budget on
    the way in.

    Shared by both messengers on purpose. The same list should page the same
    way wherever it is read, and a person who is told "page 2 of 3" on Discord
    should not find four pages of it on Telegram.
    """
    lines = [line if len(line) <= budget else line[:budget - 1] + "…"
             for line in lines]
    if not lines:
        return [""]
    total = sum(len(line) + 1 for line in lines) - 1
    count = max(1, -(-total // budget))
    while True:
        per = -(-len(lines) // count)
        groups = [lines[index:index + per]
                  for index in range(0, len(lines), per)]
        if all(sum(len(line) + 1 for line in group) - 1 <= budget
               for group in groups):
            return ["\n".join(group) for group in groups]
        count += 1


def has_translation(key):
    """Whether the six files carry this key at all, asked without complaining.

    `localized` warns when a key is missing, and rightly: a reply falling back
    to its own key is a bug somebody must see. But a caller that *offers* a
    key and means to fall back — a command spelled differently on one
    messenger, a job with no friendly name — is not that bug, and it would
    otherwise write a warning per line per call. This is the question to ask
    first."""
    return key in _LOCALE


def job_label(name, lang):
    """A scheduler job's name as a person reads it: 'news' -> 'the news'.

    The names in the schedule are identifiers — `news`, `species`, `tasks`,
    `sweep`, `backup` — and they are the right thing for a log line and the
    wrong thing for the Discord presence or for /jobs. A job with no key of
    its own falls back to its identifier, so a job added without touching the
    six files still shows something true rather than a missing-key line.
    """
    if not name:
        return "—"
    key = "job_" + str(name)
    return localized(key, lang) if has_translation(key) else str(name)


def format_duration(seconds, lang):
    """A rough length of time as a person reads it: "2 ч 15 мин", "8 с".

    Hours, minutes and seconds, and only the ones that are not zero — a wait
    of two hours and three seconds reads "2 ч 3 с", never "2 ч 0 мин 3 с".
    Anything under a second is rounded up to one rather than shown as nothing,
    because the number is an estimate and "in 0" reads as a broken message.

    The three units are i18n keys and short forms on purpose ("ч", "min"). A
    long form would need the plural rules of six languages — one hour, two
    hours, five hours, and the different answer Polish and Ukrainian give —
    for a number nobody is going to hold the bot to anyway.
    """
    total = max(1, int(round(float(seconds or 0))))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    parts = []
    for value, key in ((hours, "unit_hours"), (minutes, "unit_minutes"),
                       (secs, "unit_seconds")):
        if value:
            parts.append("{} {}".format(value, localized(key, lang)))
    return " ".join(parts)

def user_lang(user):
    """The language to answer one Telegram user in: the language of their
    client when the bot speaks it, the reference language otherwise."""
    code = (getattr(user, "language_code", None) or "").split("-", 1)[0].lower()
    return code if code in SUPPORTED_LANGS else DEFAULT_LANG

def service_lang():
    """The language the service chats are written in (config.SERVICE_LANG),
    or the reference language when that is not one of the six."""
    return SERVICE_LANG if SERVICE_LANG in SUPPORTED_LANGS else DEFAULT_LANG

def is_admin(platform, user_id=None):
    """Whether somebody is an administrator of the bot itself.

    Hard-coded in config.ADMINS rather than stored, so it survives any
    database mishap: the people who own the bot cannot be locked out of it by
    a corrupt row. Wiki administrators are the other kind and *are* stored
    (db/admins.py) — they may run the script mechanics and nothing else.

    Called as `is_admin('discord', 123)`. The one-argument form is the older
    Telegram-only spelling and still works, because that is what the four
    original commands were written against.
    """
    if user_id is None:
        platform, user_id = "telegram", platform
    try:
        return int(user_id) in ADMINS.get(str(platform), set())
    except (TypeError, ValueError):
        return False


def admin_ids(platform):
    """Every bot administrator on one platform, as a sorted list."""
    return sorted(ADMINS.get(str(platform), set()))


def _chat_keys(mapping, what):
    """One configured mapping of chats as '<platform>:<chat>[:<thread>]'.

    The shared half of `service_chat_keys` and `backup_chat_keys`: both settings
    have the same shape, and a second copy of this loop would be a second place
    for a Telegram thread id to be spelled differently."""
    keys = []
    for chat_key in (mapping or {}).get("telegram", set()):
        chat_id, thread = _parse_service_chat_key(chat_key)
        if chat_id is None:
            logger.warning("%s chat key %r is not '<chat_id>:<thread_id>'",
                           what, chat_key)
            continue
        keys.append("telegram:{}:{}".format(chat_id, thread or 0))
    for channel_id in (mapping or {}).get("discord", set()):
        keys.append("discord:{}".format(channel_id))
    return keys

def service_chat_keys():
    """Every service chat as '<platform>:<chat>[:<thread>]'.

    One spelling of a chat for the whole bot: tasks/notify.py answers a person
    in the same form the task row stores, and the service chats have to look
    the same or the reporting would need two code paths.
    """
    return _chat_keys(SERVICE_CHATS, "service")

def backup_chat_keys():
    """Every backup chat, in the same spelling — so the same sender can be used.

    Empty is the ordinary state of a deployment that has not set BACKUP_CHATS,
    and the periodic job reads it as "make no backups" rather than as a
    failure to report twice a day."""
    return _chat_keys(BACKUP_CHATS, "backup")

def publish_marks():
    """The minutes past the hour a publishing pass runs at, sorted and
    deduplicated.

    Read from config.PUBLISH_AT_MINUTES; anything outside 0–59 is folded into
    it, and an empty setting falls back to the top of the hour rather than
    leaving the loop with nothing to wait for. Lives here because two modules
    need the same answer — main.py to sleep until the next one, /status to
    print the schedule — and neither may import the other."""
    marks = sorted({int(minute) % 60 for minute in PUBLISH_AT_MINUTES})
    return marks or [0]

def publish_schedule():
    """The schedule as /status prints it: ':00, :15, :30, :45'."""
    return ", ".join(":{:02d}".format(minute) for minute in publish_marks())

def wiki_key(wiki):
    """The name one wiki of config.WIKIS is known by: '<family>:<lang>'.

    It is both the key of its rows in wiki_slots and what /status prints, so
    it is built here rather than in either of them — two spellings of the same
    wiki would give it two sets of slots and lose track of what it holds."""
    return "{}:{}".format(wiki["family"], wiki["lang"])

def _parse_service_chat_key(chat_key):
    """'<chat_id>:<thread_id>' → (chat_id, thread_id); a bare id means the
    plain group. Returns (None, None) for anything unparseable, which is what
    a typo in config looks like."""
    try:
        text = str(chat_key).strip()
        if ":" in text:
            chat_id, thread = text.split(":", 1)
            return int(chat_id), int(thread or 0)
        return int(text), 0
    except (TypeError, ValueError):
        return None, None

async def send_service_event(event_key, **kwargs):
    """Report an operational event to the service chats, on both messengers.

    Every send is guarded — the service chats are where failures are reported,
    so a failure there must stay a log line and never take down the loop that
    was reporting.

    Lives here rather than in main.py so that the Telegram half can report
    without importing the entry module, which under `python main.py` would
    load a second copy of it and rerun everything at its top level."""
    from telegram_bot import bot
    from discord_bot import send_log

    text = localized(event_key, service_lang(), **kwargs)
    logger.info("service event %s: %s", event_key, text)
    for chat_key in SERVICE_CHATS.get("telegram", set()):
        chat_id, thread = _parse_service_chat_key(chat_key)
        if chat_id is None:
            logger.warning("service chat key %r is not '<chat_id>:<thread_id>'", chat_key)
            continue
        try:
            await bot.send_message(chat_id, text, message_thread_id=thread or None)
        except Exception as e:
            logger.warning("send_service_event failed for %s: %s", chat_key, e)
    for channel_id in SERVICE_CHATS.get("discord", set()):
        await send_log(channel_id, text)
