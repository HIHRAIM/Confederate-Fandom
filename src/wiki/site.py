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

**A login that fails must not be permanent, and once it was.** Three things
made it so, and all three are answered below. `pywikibot.Site()` is a caching
factory rather than a constructor, so dropping this module's own `_session`
entry and building the site again handed back the very same object, stale
login status and all (`_drop_cached_site`). Emptying the cookie jar before
`action=login` did not survive to the request, because the library reloads the
jar from disk inside `login()` and this module's `load()` ignored the name it
was given (`_WikiCookieJar.suppress_load`). And nothing ever gave up on a wiki:
a bot that cannot log in tried again every quarter of an hour for three days,
earning `429`s that made the next attempt worse (`_blocked_until`).

Module state, one copy each: `_session` (the live Site per wiki), `_jars` (the
cookie jar per wiki) and `_blocked_until` (the wikis being left alone, and
until when).
"""
import logging
import os
import time
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

LOGIN_COOLDOWN = 900
"""How long a wiki that has just refused the bot is left alone, in seconds.

Fifteen minutes, which is one publishing pass: a wiki that refused once is
skipped for a turn and tried again on the next, so a passing failure costs one
pass and nothing more."""

LOGIN_COOLDOWN_MAX = 3600
"""The longest a wiki is left alone, however many times it has refused.

The wait doubles with each round that fails and stops here, at the hour Fandom
itself asks for in `Retry-After`. The doubling is the point: a wiki that is
briefly unhappy is back within a pass, and one that will not have the bot at
all is asked once an hour instead of ninety-six times a day — which is what
earned the `429`s that made every following login worse."""

RETRY_MAX = 120
"""The longest Pywikibot may wait between two attempts at one request.

Fandom answers an over-eager bot with `429` and a `Retry-After` of a whole
hour, and the library obeys it *inside* the request — on a bot with one
worker thread that stops every other job for an hour, including the ones for
other wikis. Capped here so that a rate limit costs a failed pass instead of
an idle bot. Best effort: it is the library's own setting, and a version that
renames it simply leaves the old behaviour."""

try:
    pywikibot.config.retry_max = RETRY_MAX
    pywikibot.config.max_retries = min(pywikibot.config.max_retries, 5)
except Exception as e:
    logger.warning("could not cap Pywikibot's retries: %s", e)

pywikibot.config.put_throttle = WIKI_PUT_THROTTLE
"""How long Pywikibot waits between two edits, in seconds.

Zero by default, and that is the operator's decision rather than an oversight:
an account carrying the bot flag on a Fandom wiki is expected to edit at
speed, the wiki throttles it on its own if it wants to, and a delay invented
here would only make a walk of nine thousand pages take three hours instead of
one. The value is in config.py for the wiki that asks for something else."""

_session = {}

_jars = {}

_blocked_until = {}
"""The wikis that would not let the bot in, and the monotonic time until which
they are left alone. Emptied for a wiki the moment it lets the bot in."""

_failures = {}
"""How many rounds of logging in have failed in a row, per wiki. What the
cooldown doubles on, and cleared by the first login that works."""

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
        self._suppressed = False

    def suppress_load(self, suppressed=True):
        """Stop `load()` reading the file, or let it read again.

        The one thing that made emptying the jar useless. `site.login()` calls
        `http.cookie_jar.load(self.username())` before it sends anything, and
        the override below reads the file whatever name it is handed — so the
        stale session cookie that had just been cleared was back in the jar,
        and travelled out with the very login meant to replace it. MediaWiki
        refuses `action=login` while a bot-password session is attached, and
        the login failed on a coin toss.

        Held for as long as the caller says rather than for one call: the
        library retries a login on its own, and a one-shot flag would be spent
        on the first attempt and let the second carry the cookie again.
        """
        self._suppressed = bool(suppressed)

    def load(self, user="", *args, **kwargs):
        """Read this wiki's cookies, ignoring the name Pywikibot suggests."""
        if self._suppressed:
            return
        try:
            cookiejar.LWPCookieJar.load(self, self.filename, ignore_discard=True)
        except (cookiejar.LoadError, OSError):
            pass

    def forget(self):
        """Empty the jar and take its file with it.

        The hard reset. A session cookie the wiki has forgotten is worse than
        no cookie at all, and a file holding one would be read back at the
        next start; the file is working data and is written again by the next
        successful login."""
        try:
            self.clear()
        except Exception:
            pass
        try:
            os.remove(self.filename)
        except OSError:
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

def _drop_cached_site(family, lang):
    """Take one wiki out of Pywikibot's own Site cache. -> how many went.

    `pywikibot.Site()` is a caching factory and not a constructor: it keeps
    every Site it has built in `pywikibot._sites`, keyed by code, family, user
    and interface, and hands the same object back for the life of the process.

    That is what made a failed login permanent. This module would drop its own
    `_session` entry, take what it thought was the cold path, and be given
    back the very same object — with its stale `_loginstatus`, its cached
    login token and its cached userinfo — so `site.login()` failed exactly as
    it had failed the time before, four times an hour for three days.
    Clearing our own dictionary was clearing the wrong one.

    Matched on the site's own attributes rather than by rebuilding the cache
    key: the key's shape is the library's business and has changed between
    versions, while a Site has always known its code and its family.
    """
    cache = getattr(pywikibot, "_sites", None)
    if not isinstance(cache, dict):
        return 0
    gone = 0
    for cache_key, cached in list(cache.items()):
        family_name = getattr(getattr(cached, "family", None), "name", None)
        if getattr(cached, "code", None) == lang and family_name == family:
            cache.pop(cache_key, None)
            gone += 1
    return gone


def _forget_login(site):
    """Make one Site object forget that it ever logged in.

    The belt to `_drop_cached_site`'s braces, for whatever still holds a
    reference to the old object. Each of the three is wrapped on its own: they
    are the library's private furniture, and a version that renames one should
    cost the reset that piece and not the whole of it.
    """
    try:
        del site.userinfo
    except Exception:
        pass
    try:
        site.tokens.clear()
    except Exception:
        pass
    try:
        site._loginstatus = pywikibot.login.LoginStatus.NOT_LOGGED_IN
    except Exception:
        pass


def _hard_reset(family, lang, key):
    """Throw away everything this process remembers about one wiki.

    The session, Pywikibot's cached Site, the cookie jar and the cookie file.
    What is left afterwards is what a freshly started process has, which is
    the state that was known to recover — restarting the unit was the only
    cure for three days, and this is that restart for one wiki.
    """
    _session.pop(key, None)
    gone = _drop_cached_site(family, lang)
    jar = _jars.pop(key, None)
    if jar is not None:
        jar.forget()
    logger.warning("the wiki layer for %s was reset (%s cached site(s) dropped)",
                   key, gone)
    _use_cookies(key)


class WikiUnknown(ValueError):
    """Pywikibot has no way to address this wiki: no such family, or no such
    language in it.

    Kept apart from a failed login on purpose. A login can fail for a while
    and come back, which is what the reset and the parking are for; a family
    file without the language fails the same way every time, and treating it
    as a login wasted two resets per wiki and then reported «could not log in»
    about wikis the bot had never tried to log in to. That is how a run over
    tadc:ru found every sister wiki «unreachable»: the family had been
    generated for ``ru`` alone, and nothing had taught it the others.
    """


def _unknown_site(error):
    """Whether an exception from `pywikibot.Site()` means "no such wiki"."""
    name = type(error).__name__
    return (name in ("UnknownSiteError", "UnknownFamilyError")
            or "does not exist in family" in str(error))


def _login_from_scratch(family, lang, key):
    """Build the Site and sign in. -> the Site, or None when it would not.

    Returns None for anything a reset might cure, so the caller can decide
    between trying again and giving up. Raises `WikiUnknown` for the one
    thing no reset cures: a family that cannot name this wiki at all.
    """
    _write_password_file()
    pywikibot.config.register_families_folder(FAMILIES_DIR)
    pywikibot.config.usernames[family][lang] = WIKI_USERNAME
    pywikibot.config.password_file = PASSWORD_FILE

    try:
        site = pywikibot.Site(lang, family)
    except Exception as e:
        if _unknown_site(e):
            raise WikiUnknown(
                "Pywikibot cannot address {}: {}".format(key, e)) from e
        logger.warning("could not open %s: %s", key, e)
        return None
    try:
        site.login()
    except Exception as e:
        logger.warning("could not log in to %s: %s", key, e)
        return None
    _jars[key].save()
    logger.info("logged in to %s as %s (bot flag: %s)", site, site.username(),
                "yes" if has_bot_right(site) else "no — edits will not be marked")
    return site


def _cooldown_for(key):
    """How long to leave one wiki alone after a round of failed logins.

    Doubles with each round and stops at LOGIN_COOLDOWN_MAX. Counted per wiki,
    because one wiki of the farm refusing the bot says nothing about the
    others, and reset by the first login that works — a bot that recovers
    must not carry yesterday's failures into today's waiting.
    """
    _failures[key] = _failures.get(key, 0) + 1
    return min(LOGIN_COOLDOWN * (2 ** (_failures[key] - 1)), LOGIN_COOLDOWN_MAX)


def get_site(family, lang):
    """The logged-in Site of one wiki, built once and kept.

    One session per wiki of config.WIKIS, held in `_session` — logging in
    costs a request and a cookie, and a pass that writes to three wikis should
    pay for it once each and not once per page.

    Four ways in, in the order they are tried. The session that is already
    there and still works. The session the wiki has forgotten, renewed in
    place (`_sign_in_again`). A wiki whose renewal failed, reset to the state
    a restarted process would have and logged into from nothing. And, when
    even that fails twice, no way in at all for `LOGIN_COOLDOWN`: the wiki is
    parked, this raises at once, and the pass fails for that wiki alone
    instead of the bot spending the next three days proving it cannot log in.

    Blocking: every Pywikibot call is, which is why the publishing pass runs
    in a worker thread (publisher.py). Only one pass runs at a time, so this
    is reached from one thread at a time as well."""
    key = "{}:{}".format(family, lang)
    _use_cookies(key)

    until = _blocked_until.get(key)
    if until is not None:
        left = until - time.monotonic()
        if left > 0:
            raise RuntimeError(
                "{} would not let the bot in; leaving it alone for another "
                "{} s".format(key, int(left)))
        _blocked_until.pop(key, None)

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
        logger.warning("%s: the session could not be renewed — starting the "
                       "wiki layer over", key)
        _hard_reset(family, lang, key)

    site = _login_from_scratch(family, lang, key)
    if site is None:
        logger.warning("%s: the login failed — resetting and trying once more", key)
        _hard_reset(family, lang, key)
        site = _login_from_scratch(family, lang, key)
    if site is None:
        wait = _cooldown_for(key)
        _blocked_until[key] = time.monotonic() + wait
        raise RuntimeError(
            "could not log in to {}; leaving it alone for {} s".format(key, wait))

    _blocked_until.pop(key, None)
    _failures.pop(key, None)
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
    jar = http.cookie_jar
    try:
        jar.suppress_load()
        jar.clear()
    except Exception as e:
        logger.warning("could not clear the login cookies: %s", e)
    _forget_login(site)
    try:
        _write_password_file()
        site.login()
        jar.save()
        return True
    except Exception as e:
        logger.warning("logging in to %s again failed: %s", site, e)
        return False
    finally:
        try:
            jar.suppress_load(False)
        except Exception:
            pass

def forget_sessions():
    """Start the wiki layer over, for every wiki. -> how many were reset.

    Everything this process remembers goes: the sessions, Pywikibot's own
    cached Sites, the cookie jars and their files. It used to clear only
    `_session`, which is precisely the dictionary that does *not* matter —
    the library handed the same Site straight back, and the function was
    useless in the one situation it exists for.

    Nothing calls it on the ordinary path. It is the manual form of what
    `get_site` now does by itself.
    """
    keys = sorted(set(_session) | set(_jars) | set(_blocked_until))
    for key in keys:
        family, _, lang = key.partition(":")
        if family and lang:
            _hard_reset(family, lang, key)
    _blocked_until.clear()
    _failures.clear()
    return len(keys)

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
