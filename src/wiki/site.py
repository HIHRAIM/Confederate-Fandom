"""The connection to the wikis: where Pywikibot keeps its files, and how the
bot logs in.

One session per wiki of config.WIKIS, under one account. The same news go to
all of them, so the sessions are kept side by side in `_session` and reused
across passes — but never trusted blindly: a session that the wiki has
forgotten is detected before the pass writes anything, and renewed
(`is_signed_in`, `_sign_in_again`).

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

The library also talks, and it is made to talk through this bot's logging
rather than past it (`_route_library_logging`), so that one journal reads as
one journal.
"""
import logging
import os
from http import cookiejar

CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "botconfig")
FAMILIES_DIR = os.path.join(CONFIG_DIR, "families")
COOKIE_DIR = os.path.join(CONFIG_DIR, "cookies")
PASSWORD_FILE = "user-password.cfg"

os.environ.setdefault("PYWIKIBOT_DIR", CONFIG_DIR)

import pywikibot
from pywikibot.comms import http

from config import WIKI_BOT_PASSWORD, WIKI_BOT_PASSWORD_SUFFIX, WIKI_USERNAME

try:
    from config import WIKI_PUT_THROTTLE
except ImportError:
    WIKI_PUT_THROTTLE = 0

logger = logging.getLogger("fd.wiki")


def _route_library_logging():
    """Send Pywikibot's own lines through this bot's logging, not past it.

    The library keeps a logger of its own, `pywiki`, and the first time
    anything is written through it, it installs terminal handlers on that
    logger and stops it propagating. Its lines then arrive on the console bare
    — no time, no level, no name — in among this bot's own ones:

        2026-09-02 12:00:00,000 fd.publisher INFO pass done over 2 wiki(s)
        Logging in to telepedia:ru as Example Bot@Example
        Page [[telepedia:ru:Template:Main/News-1]] saved

    In a journal that reads badly and, worse, cannot be filtered: a line with
    no level is invisible to `journalctl -p err` whatever it says.

    So the handlers are installed here, at import, and taken straight off
    again. The records then travel up to the root logger main.py configured,
    and the library's lines look like everybody else's. The order is the
    point: asking the library to set itself up *now* is what makes its own
    attempt later — it does it lazily, on the first line it writes — a
    no-op, so nothing puts the terminal handlers back afterwards.

    The level is pinned at INFO because the library talks below it. Its own
    VERBOSE and STDOUT levels sit under INFO but above the threshold it gives
    that logger, so they would pass it and reach a root handler that does not
    filter by level. Pinned here, what survives is what a person wants to
    read: the logins, the saves, the warnings and the errors.

    Best effort, all of it. This is the library's own furniture, and a version
    that rearranges it should cost the bot its tidy log and nothing else.
    """
    try:
        from pywikibot import bot as pywikibot_bot

        pywikibot_bot.init_handlers()
    except Exception as e:
        logger.warning("could not take over Pywikibot's logging: %s: %s",
                       type(e).__name__, e)
    library = logging.getLogger("pywiki")
    library.handlers = []
    library.propagate = True
    library.setLevel(logging.INFO)


_route_library_logging()

pywikibot.config.put_throttle = WIKI_PUT_THROTTLE
"""How long Pywikibot waits between two edits, in seconds.

Zero by default, and that is the operator's decision rather than an oversight:
an account carrying the bot flag on a Fandom wiki is expected to edit at
speed, the wiki throttles it on its own if it wants to, and a delay invented
here would only make a walk of nine thousand pages take three hours instead of
one. The value is in config.py for the wiki that asks for something else."""

_session = {}

_jars = {}

class _WikiCookieJar(http.PywikibotCookieJar):
    """A cookie jar that belongs to one wiki and stays on its own file.

    Pywikibot keeps **one** jar per process and one file per account:
    `PywikibotCookieJar.load()` builds the name from the user and nothing
    else, and `http.session.cookies` is that same object. On a wiki farm this
    is a trap. Fandom's session cookies are issued for `.fandom.com`, so two
    wikis of the farm share them: logging in to the second one replaces the
    first one's session in the jar, the first wiki starts answering as if a
    stranger were asking, and every edit there fails with a missing right —
    while the same credentials work perfectly on the wiki that logged in last.

    So each wiki gets a jar of its own, and this class is what keeps it that
    way: the file is fixed at construction, and the `load()` Pywikibot calls
    during its own login cannot drag the shared file's cookies back in.
    """

    def __init__(self, filename):
        """Bind the jar to one file, for good."""
        super().__init__()
        self.filename = filename

    def load(self, user="", *args, **kwargs):
        """Read this wiki's cookies, ignoring the name Pywikibot suggests."""
        try:
            cookiejar.LWPCookieJar.load(self, self.filename, ignore_discard=True)
        except (cookiejar.LoadError, OSError):
            pass

    def save(self, *args, **kwargs):
        """Write this wiki's cookies, readable by nobody else."""
        try:
            cookiejar.LWPCookieJar.save(self, self.filename, ignore_discard=True)
            os.chmod(self.filename, 0o600)
        except OSError as e:
            logger.warning("could not store the cookies in %s: %s", self.filename, e)

def _use_cookies(key):
    """Make one wiki's cookies the ones every request from now on carries.

    Called before anything is asked of that wiki. Both names have to be
    swapped: `http.session.cookies` is what the requests actually travel with,
    and `http.cookie_jar` is what Pywikibot's own login and cookie-saving
    reach for."""
    jar = _jars.get(key)
    if jar is None:
        try:
            os.makedirs(COOKIE_DIR, exist_ok=True)
        except OSError as e:
            logger.warning("could not make the cookie directory %s: %s", COOKIE_DIR, e)
        jar = _WikiCookieJar(os.path.join(COOKIE_DIR, key.replace(":", "-") + ".lwp"))
        jar.load()
        _jars[key] = jar
    http.cookie_jar = jar
    http.session.cookies = jar
    return jar

def use_cookies(key):
    """Make one wiki's cookies the current ones, without asking it anything.

    The cheap half of `get_site`, and the one anything that has just talked to
    another wiki must call on the way back. Pywikibot keeps one jar per
    process, so a mechanic that reads a sister wiki (scripts/interwiki.py)
    leaves that wiki's cookies selected; the next edit on the task's own wiki
    would then go out with somebody else's session attached. Costs nothing —
    no request, no login — so calling it too often is free and calling it too
    seldom is a lost session.
    """
    return _use_cookies(str(key))


def _write_password_file():
    """Put the credentials from .env where Pywikibot looks for them.

    The file holds one line in Pywikibot's own format and is rewritten only
    when it does not already say that, so a run that changes nothing does not
    touch it. It is a secret on disk, like the login cookie beside it: kept
    out of git by .git/info/exclude and made unreadable to other users where
    the platform can do that.

    The mode is set on **every** start, and not only on the start that writes
    the line. Skipping it when the contents already matched is how a checkout
    once left the wiki password at 664 — readable by every local user of the
    machine — until Pywikibot noticed on its own and said so in a warning. The
    file this function is handed is not always the file it wrote last time: it
    outlives the process, and a restart, a deployment or a copy can each hand
    it back with somebody else's idea of who may read it."""
    path = os.path.join(CONFIG_DIR, PASSWORD_FILE)
    line = "({!r}, BotPassword({!r}, {!r}))\n".format(
        WIKI_USERNAME, WIKI_BOT_PASSWORD_SUFFIX, WIKI_BOT_PASSWORD)
    try:
        current = open(path, encoding="utf-8").read() if os.path.exists(path) else None
    except OSError:
        current = None
    if current != line:
        with open(path, "w", encoding="utf-8") as f:
            f.write(line)
    try:
        os.chmod(path, 0o600)
    except OSError as e:
        logger.warning("could not restrict the credentials file to this user: %s", e)
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
    _use_cookies(key)
    site = _session.get(key)
    if site is not None:
        if is_signed_in(site):
            return site
        logger.warning("the session on %s is no longer recognised — logging in again", key)
        _session.pop(key, None)
        if _sign_in_again(site) and is_signed_in(site):
            _session[key] = site
            logger.info("the session on %s was restored", key)
            return site
        raise RuntimeError("the session on {} expired and could not be renewed".format(key))

    _write_password_file()
    pywikibot.config.register_families_folder(FAMILIES_DIR)
    pywikibot.config.usernames[family][lang] = WIKI_USERNAME
    pywikibot.config.password_file = PASSWORD_FILE

    site = pywikibot.Site(lang, family)
    site.login()
    _jars[key].save()
    logger.info("logged in to %s as %s (bot flag: %s)", site, site.username(),
                "yes" if has_bot_right(site) else "no — edits will not be marked")
    _session[key] = site
    return site

def is_signed_in(site):
    """Whether the wiki still recognises this session as the bot's account.

    Asked once per wiki per pass, and the answer costs one request. It is
    worth it: a login session expires eventually, and when it does the Site
    object goes on believing it is signed in — its cached userinfo says so —
    while the wiki answers every edit as if a stranger had made it. Left to
    itself the bot then fails every pass in the same way for as long as the
    process lives, which is exactly what happened for a day. So the cache is
    dropped and the question put to the wiki itself, and the name has to come
    back the bot's own: 'not anonymous' is not enough, because a lapsed
    session reads as an IP address with rights of its own."""
    try:
        del site.userinfo
    except Exception:
        pass
    try:
        info = site.userinfo
    except Exception as e:
        logger.warning("could not ask %s who it thinks we are: %s", site, e)
        return False
    return "anon" not in info and info.get("name") == WIKI_USERNAME

def _sign_in_again(site):
    """Log in from scratch on a session the wiki has forgotten.

    The cookies go first, and that is the whole trick. MediaWiki refuses
    `action=login` while a bot-password session is attached to the request —
    "Cannot log in when using BotPasswordSessionProvider sessions" — so a
    stale cookie in the jar keeps the bot out of its own account: the retry
    Pywikibot makes on its own hits that wall and gives up, leaving the site
    with no username at all. Anonymous, the request is accepted and the login
    goes through, which is why a restarted process recovers and a running one
    did not."""
    try:
        http.cookie_jar.clear()
    except Exception as e:
        logger.warning("could not clear the login cookies: %s", e)
    try:
        del site.userinfo
    except Exception:
        pass
    try:
        site._loginstatus = pywikibot.login.LoginStatus.NOT_LOGGED_IN
    except Exception:
        pass
    try:
        _write_password_file()
        site.login()
        http.cookie_jar.save()
        return True
    except Exception as e:
        logger.warning("logging in to %s again failed: %s", site, e)
        return False

def forget_sessions():
    """Drop every stored session, so the next pass logs in from scratch.

    The cookies are kept: they are per wiki and still good. Nothing calls this
    on the ordinary path; it is here for the case where a wiki has to be given
    up on entirely and started again."""
    _session.clear()

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
