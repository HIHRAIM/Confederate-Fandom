"""The connection to the wikis: where Pywikibot keeps its files, and how the
bot logs in.

One session per wiki of config.WIKIS, under one account. The same news go to
all of them, so the sessions are kept side by side in `_session` and reused
across passes.

PYWIKIBOT_DIR is pointed at src/botconfig/ *before* pywikibot is imported —
the library reads it at import time and never again. That directory is where
its login cookie, its API cache and its throttle bookkeeping land, which keeps
this bot out of the operator's global Pywikibot installation and keeps another
project's account out of this bot.

Logging in goes through Pywikibot's own password file rather than a login call
of our own, and the file is written here from the values in .env at every
start. The reason is the lifetime of the process: a session expires eventually,
and Pywikibot answers that by logging in again on its own — but only if it can
find credentials. Handed nothing, it asks for a password on the console, and a
bot that has been running unattended for a month would simply hang there. So
.env stays the one place the secret is written by hand, and this module keeps
Pywikibot's copy of it in step.

The family file (src/botconfig/families/<family>_family.py) is what maps each
wiki's family name to a host and a script path; register_families_folder adds
the folder to Pywikibot's own, so no wiki has to be added to the library.
"""
import logging
import os

CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "botconfig")
FAMILIES_DIR = os.path.join(CONFIG_DIR, "families")
PASSWORD_FILE = "user-password.cfg"

os.environ.setdefault("PYWIKIBOT_DIR", CONFIG_DIR)

import pywikibot

from config import WIKI_BOT_PASSWORD, WIKI_BOT_PASSWORD_SUFFIX, WIKI_USERNAME

logger = logging.getLogger("tprp.wiki")

_session = {}

def _write_password_file():
    """Put the credentials from .env where Pywikibot looks for them.

    The file holds one line in Pywikibot's own format and is rewritten only
    when it does not already say that, so a run that changes nothing does not
    touch it. It is a secret on disk, like the login cookie beside it: kept
    out of git by .git/info/exclude and made unreadable to other users where
    the platform can do that."""
    path = os.path.join(CONFIG_DIR, PASSWORD_FILE)
    line = "({!r}, BotPassword({!r}, {!r}))\n".format(
        WIKI_USERNAME, WIKI_BOT_PASSWORD_SUFFIX, WIKI_BOT_PASSWORD)
    try:
        if os.path.exists(path) and open(path, encoding="utf-8").read() == line:
            return path
    except OSError:
        pass
    with open(path, "w", encoding="utf-8") as f:
        f.write(line)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path

def get_site(family, lang):
    """The logged-in Site of one wiki, built once and kept.

    One session per wiki of config.WIKIS, held in `_session` — logging in
    costs a request and a cookie, and a pass that writes to three wikis should
    pay for it once each and not once per page.

    Blocking: every Pywikibot call is, which is why the publishing pass runs
    in a worker thread (publisher.py). Only one pass runs at a time, so this
    is reached from one thread at a time as well."""
    key = "{}:{}".format(family, lang)
    if key in _session:
        return _session[key]

    _write_password_file()
    pywikibot.config.register_families_folder(FAMILIES_DIR)
    pywikibot.config.usernames[family][lang] = WIKI_USERNAME
    pywikibot.config.password_file = PASSWORD_FILE

    site = pywikibot.Site(lang, family)
    site.login()
    logger.info("logged in to %s as %s (bot flag: %s)", site, site.username(),
                "yes" if has_bot_right(site) else "no — edits will not be marked")
    _session[key] = site
    return site

def has_bot_right(site):
    """Whether this account may mark its edits as bot edits on this wiki.

    Worth a line in the log at every login, because the answer is invisible
    from the code's side: the bot asks for the flag on every edit and the wiki
    grants it only to an account in the local bot group whose BotPassword
    carries the "High-volume editing" grant. Missing either, the edits are
    written all the same and simply appear in Recent changes."""
    try:
        return "bot" in site.userinfo.get("rights", [])
    except Exception:
        return False
