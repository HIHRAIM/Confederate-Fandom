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

logger = logging.getLogger("tprp.utils")

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

def user_lang(user):
    """The language to answer one Telegram user in: the language of their
    client when the bot speaks it, the reference language otherwise."""
    code = (getattr(user, "language_code", None) or "").split("-", 1)[0].lower()
    return code if code in SUPPORTED_LANGS else DEFAULT_LANG

def service_lang():
    """The language the service chats are written in (config.SERVICE_LANG),
    or the reference language when that is not one of the six."""
    return SERVICE_LANG if SERVICE_LANG in SUPPORTED_LANGS else DEFAULT_LANG

def is_admin(user_id):
    """Whether the user may use /status and /update — hard-coded in
    config.ADMINS rather than stored, so it survives any database mishap."""
    try:
        return int(user_id) in ADMINS.get("telegram", set())
    except (TypeError, ValueError):
        return False

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
    """Report an operational event to the service chats.

    Every send is guarded — the service chats are where failures are reported,
    so a failure there must stay a log line and never take down the loop that
    was reporting.

    Lives here rather than in main.py so that the Telegram half can report
    without importing the entry module, which under `python main.py` would
    load a second copy of it and rerun everything at its top level."""
    from telegram_bot import bot

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
