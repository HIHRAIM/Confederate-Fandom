"""Interlanguage links on a Fandom farm — Pywikibot's interwiki.py, rebuilt.

    Pywikibot's interwiki.py is (C) Rob W. W. Hooft, 2003, Daniel Herding,
    2004, Ashley Van Haeften, 2005-2007, xqt, 2007-2025 and the Pywikibot
    team, 2003-2025, MIT licence. Almost none of it survives the move, and the
    reason is worth writing down: that script solves the Wikipedia problem —
    hundreds of projects, a global graph, autonomous conflict resolution — for
    a world that has since moved to Wikidata. Fandom has no Wikidata and no
    global graph. A Fandom wiki has a handful of sister wikis, named in its own
    interwiki table, and the whole job is to keep the links between them in
    step.

**Which wikis are linked.** Not guessed and not configured: read from the
wiki's own ``meta=siteinfo&siprop=interwikimap``, keeping the entries marked as
languages that point back into the same host family. So the bot works out that
``telepedia.fandom.com/ru`` has ``uk`` beside it, and nobody has to keep a list
in a config file.

**What gets added.** The rule the operator asked for: a link that stands on one
of two linked wikis and not on the other. So the bot reads the interwiki links
of every page this one already points at, and brings back what those pages know
and this one does not. A link is never invented from a title that happens to
match — two wikis of the same farm can easily have an article of the same name
about different things, and a wrong interlanguage link is worse than none. Every
candidate is checked to exist before it is written.

**Where they go and in what order.** The block is moved to the very end of the
page, after the categories, and sorted by language code — which is the order
Fandom's own language list follows and the order the operator's earlier script
used (``en``, ``ru``, ``uk``).

**What is not touched.** ``[[:uk:Назва]]`` with a leading colon is an ordinary
link in the running text, not an interlanguage link, and it stays exactly where
it is.

One run touches one wiki. Running the same task on the sister wiki closes the
other half of the loop, and the report says so.
"""
import logging
import re
import sys

from tasks import mechanic as mech
from tasks.params import FLAGS, Param

logger = logging.getLogger("fd.scripts.interwiki")

FLAG_SORT_ONLY = "sort_only"
FLAG_NO_PROPAGATE = "no_propagate"

_IW_LINE_RE = re.compile(
    r"^[ \t]*\[\[[ \t]*(?P<lang>[a-z][a-z0-9-]{1,11})[ \t]*:[ \t]*"
    r"(?P<title>[^\]\|]+?)[ \t]*\]\][ \t]*$", re.M)
"""One interlanguage link on a line of its own. The leading colon form is not
matched at all — ``[[:uk:…]]`` is a link in the text and belongs to the
author."""


def _host_family(url):
    """The Fandom host family a URL belongs to. -> 'telepedia' or None.

    ``https://telepedia.fandom.com/uk/wiki/$1`` -> ``telepedia``. Anything
    that is not a Fandom-shaped host gives None and is left out: a link to
    Wikipedia is a real interwiki prefix, but it is not a sister wiki and the
    bot has no business writing one.
    """
    m = re.match(r"https?://([a-z0-9-]+)\.(fandom\.com|wikia\.org)/", str(url or ""), re.I)
    return m.group(1).lower() if m else None


def prepare(ctx):
    """Work out the sister wikis, and open nothing yet. -> the state mapping.

    The sites are opened lazily: a wiki nothing links to costs no login, and a
    run over a category where every page is already complete may never open a
    second wiki at all.
    """
    from wiki import families

    try:
        data = ctx.site.siteinfo["interwikimap"]
    except Exception as e:
        raise ValueError("не удалось прочитать таблицу интервики: {}".format(e))

    own_host = _host_family(ctx.site.base_url(""))
    if not own_host:
        try:
            own_host = families.family_name(ctx.site.hostname())
        except Exception:
            own_host = None

    langs = {}
    for entry in data:
        prefix = str(entry.get("prefix") or "").lower()
        if not prefix or prefix == ctx.lang:
            continue
        if "language" not in entry and not entry.get("language"):
            continue
        host = _host_family(entry.get("url"))
        if not host or (own_host and host != own_host):
            continue
        langs[prefix] = {"family": families.family_name(host),
                         "lang": prefix, "url": entry.get("url")}

    if not langs:
        ctx.note("на этой вики не объявлено ни одной языковой версии — "
                 "интервики ставить некуда")
    else:
        ctx.note("языковые версии: " + ", ".join(sorted(langs)))
    return {"langs": langs, "sites": {}, "exists": {}, "links": {}}


def _sister_site(ctx, lang):
    """The logged-in Site of one sister wiki, opened once. -> Site or None.

    Every failure is swallowed into None on purpose: a sister wiki the account
    has no access to, or one that is down, must cost that language and not the
    run. The cookie jar is put back on the way out — each wiki of the farm has
    its own, and leaving somebody else's selected is how a session gets lost
    (wiki/site.py).
    """
    import wiki

    state = ctx.state.get(SPEC.code)
    if lang in state["sites"]:
        return state["sites"][lang]
    entry = state["langs"].get(lang)
    site = None
    if entry:
        try:
            site = wiki.get_site(entry["family"], entry["lang"])
        except Exception as e:
            logger.warning("cannot reach the %s wiki: %s", lang, e)
            ctx.note("языковая версия «{}» недоступна: {}".format(lang, e))
        finally:
            wiki.use_cookies(ctx.wiki)
    state["sites"][lang] = site
    return site


def _exists(ctx, lang, title):
    """Whether one page exists on one sister wiki, asked once per title."""
    import wiki
    import pywikibot

    state = ctx.state.get(SPEC.code)
    key = (lang, title)
    if key in state["exists"]:
        return state["exists"][key]
    site = _sister_site(ctx, lang)
    found = False
    if site is not None:
        try:
            found = pywikibot.Page(site, title).exists()
        except Exception as e:
            logger.warning("cannot check %s:%s: %s", lang, title, e)
        finally:
            wiki.use_cookies(ctx.wiki)
    state["exists"][key] = found
    return found


def _links_of(ctx, lang, title):
    """The interlanguage links of one page on one sister wiki. -> {lang: title}.

    This is the propagation the operator asked for: a link that stands on the
    Ukrainian article and not on the Russian one is found here and brought
    back.
    """
    import wiki
    import pywikibot

    state = ctx.state.get(SPEC.code)
    key = (lang, title)
    if key in state["links"]:
        return state["links"][key]
    site = _sister_site(ctx, lang)
    found = {}
    if site is not None:
        try:
            text = pywikibot.Page(site, title).text
            for match in _IW_LINE_RE.finditer(text):
                found[match.group("lang").lower()] = match.group("title").strip()
        except Exception as e:
            logger.warning("cannot read %s:%s: %s", lang, title, e)
        finally:
            wiki.use_cookies(ctx.wiki)
    state["links"][key] = found
    return found


def _strip(text):
    """Take the interwiki block out. -> (text without it, {lang: title})."""
    found = {}
    for match in _IW_LINE_RE.finditer(text):
        found[match.group("lang").lower()] = match.group("title").strip()
    return _IW_LINE_RE.sub("", text), found


def apply(ctx, page, text):
    """One page's interlanguage links completed and sorted."""
    state = ctx.state.get(SPEC.code) or {}
    known_langs = state.get("langs") or {}
    if not known_langs:
        return text, []

    flags = set(ctx.params.get("interwiki_flags") or [])
    body, present = _strip(text)
    links = {lang: title for lang, title in present.items()
             if lang in known_langs}

    added = []
    if FLAG_SORT_ONLY not in flags and FLAG_NO_PROPAGATE not in flags:
        for lang, title in list(links.items()):
            for other_lang, other_title in _links_of(ctx, lang, title).items():
                if other_lang == ctx.lang or other_lang in links:
                    continue
                if other_lang not in known_langs:
                    continue
                if _exists(ctx, other_lang, other_title):
                    links[other_lang] = other_title
                    added.append(other_lang)

    if not links:
        return text, []

    block = "\n".join("[[{}:{}]]".format(lang, links[lang])
                      for lang in sorted(links))
    new = body.rstrip("\n") + "\n\n" + block + "\n"
    if new == text:
        return text, []

    labels = []
    if added:
        labels.append("добавлены интервики: " + ", ".join(sorted(set(added))))
    if not labels:
        labels.append("интервики упорядочены")
    return new, labels


def summary_part(ctx, labels):
    """What this mechanic contributes to the edit summary."""
    if not labels:
        return None
    if any(label.startswith("добавлены") for label in labels):
        return "интервики-ссылки"
    return "интервики-ссылки упорядочены"


SPEC = mech.Mechanic(
    code="interwiki",
    kind=mech.TEXT,
    module=sys.modules[__name__],
    rights=("edit",),
    params=(
        Param("interwiki_flags", FLAGS, "param_interwiki_flags", options=(
            (FLAG_SORT_ONLY, "flag_iw_sort_only"),
            (FLAG_NO_PROPAGATE, "flag_iw_no_propagate"),
        )),
    ),
)
