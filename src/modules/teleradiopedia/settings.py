"""The news module's settings: read from config.py, each with a default.

A deployment that publishes no news has no reason to carry twenty lines of
news configuration, and a config.py without them must still start. So nothing
reads these names from config directly: they are read here once, with a
default for every one, and the rest of the bot imports them from this module.

**The module is on only when it has somewhere to take news from and somewhere
to put them** (`enabled`): a channel to follow, at least one wiki, and as many
files as templates. Anything less and it registers no job, resolves no
channel, collects no post and stays out of /help — somebody running the bot
for wiki work alone never hears of it. The defaults are therefore "off", and
config.example.py ships with the module switched off.
"""
import config

def _get(name, default):
    """One setting, or its default when config.py does not name it."""
    value = getattr(config, name, default)
    return default if value is None and default is not None else value

SOURCE_CHANNEL = _get("SOURCE_CHANNEL", None)
WIKIS = tuple(_get("WIKIS", ()) or ())
NEWS_TEMPLATES = tuple(_get("NEWS_TEMPLATES", ()) or ())
NEWS_FILES = tuple(_get("NEWS_FILES", ()) or ())
PUBLISH_AT_MINUTES = tuple(_get("PUBLISH_AT_MINUTES", (0, 15, 30, 45)) or ())
PREVIEW_SYNC = bool(_get("PREVIEW_SYNC", True))
PREVIEW_LIMIT = int(_get("PREVIEW_LIMIT", 20))
NEWS_CSS_PREFIX = str(_get("NEWS_CSS_PREFIX", "tp-news"))
NEWS_TEXT_LIMIT = int(_get("NEWS_TEXT_LIMIT", 600))
NEWS_TIMEZONE = str(_get("NEWS_TIMEZONE", "UTC"))
NEWS_DATE_FORMAT = str(_get("NEWS_DATE_FORMAT", "{day} {month} {year}"))
NEWS_MONTHS = tuple(_get("NEWS_MONTHS", (
    "January", "February", "March", "April", "May", "June", "July",
    "August", "September", "October", "November", "December")) or ())
FORWARD_FROM_CHAT = str(_get("FORWARD_FROM_CHAT", "") or "")
FORWARD_FROM_USER = str(_get("FORWARD_FROM_USER", "") or "")
EDIT_SUMMARY = str(_get("EDIT_SUMMARY", "{link}"))
UPLOAD_SUMMARY = str(_get("UPLOAD_SUMMARY", "{link}"))

def enabled():
    """Whether this deployment publishes news at all."""
    return (bool(SOURCE_CHANNEL) and bool(WIKIS) and bool(NEWS_TEMPLATES)
            and len(NEWS_TEMPLATES) == len(NEWS_FILES))
