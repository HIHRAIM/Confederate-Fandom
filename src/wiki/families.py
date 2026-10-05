"""Turning a domain somebody typed into a wiki Pywikibot can talk to.

Pywikibot addresses a wiki by a *family* and a *language code*, and a family
is a Python file that maps the code to a host and a script path. Four of them
were written by hand when the bot served four wikis. Now a task may name any
wiki of the Fandom farm, so the files are generated here instead, once per
family, into the same src/botconfig/families/ directory the hand-written ones
live in — a generated file and a hand-written one are the same thing to
Pywikibot, and a family that already exists is never overwritten.

What one request to the wiki buys us, and why it is made: on Fandom the wiki
in the *root* of a host may be in any language (``telepedia.fandom.com`` is
English, another host's root is Russian), and every other language sits under
a path of its own — ``/ru``, ``/uk``. A family file has to know which code is
the root one, and the only honest source for that is the wiki: ``action=query&
meta=siteinfo`` answers with its content language and its script path. The
answer is baked into the generated file, so the request happens once per
family and never again.

The request is deliberately made with plain `requests` rather than through
Pywikibot: it happens *before* the wiki has a family at all, and it must not
touch the cookie jar wiki/site.py swaps per wiki.

Not this module's zone: logging in (wiki/site.py) and what may be done once
logged in (wiki/rights.py).
"""
import hashlib
import logging
import os
import re
import sys

import requests

from utils import Explained

logger = logging.getLogger("fd.wiki.families")

FAMILIES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "botconfig", "families")

PROBE_TIMEOUT = 20

USER_AGENT = "Confederate Fandom (fd_bot; pywikibot)"

_URL_RE = re.compile(
    r"^(?:https?://)?(?P<host>[a-z0-9][a-z0-9.-]*\.[a-z]{2,})"
    r"(?P<path>/[^\s?#]*)?$", re.I)

_KNOWN_HOSTS = ("fandom.com", "wikia.org", "gamepedia.com", "wiki.gg")

_TEMPLATE = '''"""Generated from {host} by wiki/families.py.

{note}
"""
from pywikibot import family

class Family(family.Family):

    """One wiki of the Fandom farm, addressed by its language code."""

    name = {name!r}
    langs = {langs!r}

    def scriptpath(self, code):
        """Where api.php lives for one language of this wiki."""
        return {paths!r}[code]

    def protocol(self, code):
        """Fandom is https only."""
        return 'https'
'''

def family_name(host):
    """The preferred legacy Pywikibot family name of one host.

    Everything but the letters and digits of the first label is dropped, so
    ``hihraim-test.fandom.com`` becomes ``hihraimtest`` — which is exactly
    what the hand-written family of that wiki is called. This spelling is
    retained for stored tasks, but is not a unique host identifier:
    ``owarinoseraph`` and ``owari-no-seraph`` collide. ``ensure_family`` checks
    the host before reusing it and chooses a separate key when necessary.
    """
    label = str(host).strip().lower().split("/")[0].split(".")[0]
    cleaned = re.sub(r"[^a-z0-9]", "", label)
    if not cleaned:
        raise Explained("error_wiki_bad_domain", host=str(host))
    if cleaned[0].isdigit():
        cleaned = "w" + cleaned
    return cleaned

def parse_target(text):
    """What wiki a person meant. -> {'host', 'path', 'family', 'lang'}.

    Everything a person is likely to paste is accepted: a bare domain, a
    domain with a language path, a full article URL, and the shorthand
    ``telepedia:ru`` the bot itself prints. The language is taken from the
    path when there is one; ``lang`` is None when the target is the root of a
    host, and `ensure_family` then asks the wiki what language that is.
    """
    text = str(text or "").strip()
    if not text:
        raise Explained("error_wiki_empty")

    if ":" in text and "/" not in text and "." not in text:
        family, _, lang = text.partition(":")
        return {"host": None, "path": None,
                "family": family_name(family), "lang": lang or None}

    for cut in ("?", "#"):
        if cut in text:
            text = text.split(cut, 1)[0]

    m = _URL_RE.match(text)
    if not m:
        raise Explained("error_wiki_bad_address", text=text)
    host = m.group("host").lower()
    path = (m.group("path") or "").rstrip("/")

    for marker in ("/wiki/", "/index.php", "/api.php", "/f/", "/Special:"):
        cut = path.find(marker)
        if cut >= 0:
            path = path[:cut]
            break

    lang = None
    if path:
        first = path.strip("/").split("/")[0]
        if re.fullmatch(r"[a-z]{2,3}(?:-[a-z0-9-]+)?", first, re.I):
            lang = first.lower()
            path = "/" + lang
        else:
            path = ""
    return {"host": host, "path": path, "family": family_name(host),
            "lang": lang}

def _probe(host, path):
    """Ask one wiki what it is. -> siteinfo's `general` block.

    Made without logging in and without Pywikibot: at this point the wiki has
    no family yet, and the shared cookie jar must not be touched.
    """
    url = "https://{}{}/api.php".format(host, path or "")
    params = {"action": "query", "meta": "siteinfo", "siprop": "general",
              "format": "json", "formatversion": "2"}
    response = requests.get(url, params=params, timeout=PROBE_TIMEOUT,
                            headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    data = response.json()
    general = (data.get("query") or {}).get("general")
    if not general:
        raise Explained("error_wiki_not_mediawiki", url=url)
    return general

def _family_path(family):
    """Where the file of one family lives."""
    return os.path.join(FAMILIES_DIR, "{}_family.py".format(family))

def _read_family(family):
    """Read a family's actual hosts and paths through Pywikibot.

    The question is put to Pywikibot rather than to the text of the file,
    because a family may compute its languages instead of listing them — the
    hand-written pokemon family builds its `langs` with a comprehension and
    derives the script path in code, and no amount of reading the source would
    recover that. Loading the family gives the same answer for a file this
    module generated and for one a person wrote.

    Returns None when there is no such family, which is what tells
    `ensure_family` it has to ask the wiki.
    """
    if not os.path.exists(_family_path(family)):
        return None
    import wiki.site
    import pywikibot

    pywikibot.config.register_families_folder(FAMILIES_DIR)
    try:
        loaded = pywikibot.family.Family.load(family)
    except Exception as e:
        logger.warning("family %s exists but will not load: %s", family, e)
        return None
    paths, hosts = {}, {}
    try:
        for code in loaded.langs:
            hosts[code] = str(loaded.hostname(code)).lower()
            paths[code] = loaded.scriptpath(code)
    except Exception as e:
        logger.warning("family %s has unreadable host or path: %s", family, e)
        return None
    return {"paths": paths, "hosts": hosts}

def _read_langs(family):
    """The known language paths, for the stored ``family:language`` spelling."""
    known = _read_family(family)
    return known["paths"] if known is not None else None

def _generated_for(family, host):
    """Only this module's generated files may be extended in place.

    A handwritten family may have computed paths and other overrides that
    the generic template cannot preserve. Its absence of our exact generator
    heading is enough to keep it untouched, even when loading it failed.
    """
    try:
        with open(_family_path(family), encoding="utf-8") as source:
            heading = source.readline().strip()
    except OSError:
        return False
    return heading == '\"\"\"Generated from {} by wiki/families.py.'.format(host)

def _family_conflict(host):
    """Explain a protected family-file conflict without exposing local paths."""
    return Explained("family_file_conflict", host=host)

def _family_for_host(preferred, host, lang):
    """Choose a family that cannot silently redirect this host to another.

    Existing short keys and handwritten aliases keep their meaning. A host
    whose short key is occupied, or whose handwritten family cannot describe
    the requested language, receives a stable key derived from the full host.
    Every candidate is checked too: even a pre-existing digest-named file is
    never trusted merely because its filename looks right.
    """
    digest = hashlib.sha256(host.encode("utf-8")).hexdigest()
    candidates = (preferred, preferred + "x" + digest[:12],
                  preferred + "x" + digest)
    for candidate in candidates:
        known = _read_family(candidate)
        if known is not None:
            if lang and known["hosts"].get(lang) == host:
                return candidate, known["paths"]
            if (_generated_for(candidate, host)
                    and set(known["hosts"].values()) == {host}):
                return candidate, known["paths"]
        elif not os.path.exists(_family_path(candidate)):
            return candidate, {}
    raise _family_conflict(host)

def _forget(family):
    """Make Pywikibot read the family file again after it was rewritten.

    Both caches have to go: the module Python imported, and the Family object
    Pywikibot keeps beside it. Without this a language added to an existing
    family would be invisible until the bot restarted.
    """
    module = "{}_family".format(family)
    sys.modules.pop(module, None)
    try:
        from pywikibot.family import Family
        Family._families.pop(family, None)
    except Exception as e:
        logger.debug("could not drop the cached family %s: %s", family, e)

def _write(family, host, langs):
    """Write a new family or extend this generator's file for the same host.

    The ownership check also lives at the write boundary, so a future caller
    cannot accidentally bypass the selection rules in ``ensure_family``.
    ``langs`` is {code: script path}.
    """
    if os.path.exists(_family_path(family)):
        known = _read_family(family)
        if (known is None or not _generated_for(family, host)
                or set(known["hosts"].values()) != {host}):
            raise _family_conflict(host)
    os.makedirs(FAMILIES_DIR, exist_ok=True)
    note = ("The root of the host answers as '{root}'. Other languages live "
            "under a path of their own.").format(
        root=next((c for c, p in sorted(langs.items()) if not p), "?"))
    source = _TEMPLATE.format(
        host=host, note=note, name=family,
        langs={code: host for code in sorted(langs)},
        paths={code: langs[code] for code in sorted(langs)})
    with open(_family_path(family), "w", encoding="utf-8") as f:
        f.write(source)
    _forget(family)
    logger.info("family %s now covers %s", family, ", ".join(sorted(langs)))

def ensure_family(target):
    """Make sure Pywikibot can address the wiki `target` names.

    Takes what `parse_target` returns (or the text itself) and gives back
    ``(family, lang)`` — the pair every other module addresses a wiki by, and
    the two halves of the ``family:lang`` key its rows are stored under.

    A family file that covers both the language and its host is reused.
    Handwritten files are never rewritten: a missing language gets a separate
    generated family. Colliding legacy names also get separate generated
    families instead of replacing the host of already configured languages.
    """
    if not isinstance(target, dict):
        target = parse_target(target)
    family = target["family"]
    lang = target["lang"]
    host = target["host"]

    if host is None:
        known = _read_langs(family)
        if known is not None and lang and lang in known:
            return family, lang
        if known is None:
            raise Explained("error_wiki_unknown_family", family=family)
        if lang is None:
            raise Explained("error_wiki_no_lang", family=family)
        raise Explained("error_wiki_no_section", family=family, lang=lang,
                        langs=", ".join(sorted(known)))

    host = str(host).lower()
    if lang:
        selected, known = _family_for_host(family, host, lang)
        if lang in known:
            return selected, lang

    general = _probe(host, target["path"])
    root_lang = None
    script = (general.get("scriptpath") or "").rstrip("/")
    if not script:
        root_lang = general.get("lang") or "en"
    found = lang or general.get("lang") or "en"

    canonical_host = str(general.get("servername") or host).lower()
    preferred = family if canonical_host == host else family_name(canonical_host)
    family, known = _family_for_host(preferred, canonical_host, found)
    if found in known:
        return family, found

    langs = dict(known or {})
    if root_lang and root_lang not in langs:
        langs[root_lang] = ""
    langs[found] = script if lang else (script or "")
    if not lang and root_lang:
        langs[root_lang] = ""
        found = root_lang
    _write(family, canonical_host, langs)
    return family, found

def known_families():
    """Every family the bot can address without asking a wiki anything."""
    if not os.path.isdir(FAMILIES_DIR):
        return []
    return sorted(name[:-10] for name in os.listdir(FAMILIES_DIR)
                  if name.endswith("_family.py"))
