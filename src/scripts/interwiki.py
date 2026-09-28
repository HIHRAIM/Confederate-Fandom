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
wiki's own ``meta=siteinfo&siprop=interwikimap``. Every entry marked as a
language is one this mechanic *manages* — its lines are kept, sorted and put
at the end — but only the ones on the same host are *opened*, because only
those share the bot's login and can be read and checked. On tadc.fandom.com
the Japanese version lives on theamazingdigitalcircus.fandom.com: its link is
a real language link, the reader sees it in the menu, and it is kept exactly
as written; it is simply never used to find more.

That distinction is written down because it was once missing. The block used
to be rebuilt from the same-host languages alone, so a ``[[ja:…]]`` line was
taken out with the others and never put back — two pages of tadc:ru lost
their link to the Japanese wiki in one run. A line with a prefix that is not a
language at all (``[[wikipedia:…]]``) is not this mechanic's business and is
left where it stands.

**What gets added.** The rule the operator asked for: a link that stands on one
of two linked wikis and not on the other. So the bot reads the interwiki links
of every page this one already points at, and brings back what those pages know
and this one does not — an article with a link to the Ukrainian version gets
the English one from *that* page, without anybody having found it. This is the
whole of what `flag_iw_sort_only` switches off.

**All of it in one pass.** A link brought back is walked in its turn, so `ru`
takes `en` from `uk` and then `pl` from `en` without waiting for the next run.
This used to stop after one hop, which bounded nothing worth bounding: the
next run started from the enlarged set and reached the same place anyway — in
two edits to the same article instead of one, and a page history is a thing
people read. The walk cannot run away: a language enters the queue only when
it is new to this page, and the languages are the handful the wiki's own
interwiki table declares, so the queue is shorter than that table and each
sister page is read once and remembered.

It settles. Once there is nothing left to bring back the pass finds the block
already correct and writes nothing at all, so a scheduled run does not churn.

What keeps a wrong link out is not the hop limit but the three checks. A link
is never invented from a title that happens to match — two wikis of the same
farm can easily have an article of the same name about different things, and a
wrong interlanguage link is worse than none. Only the languages the wiki's own
interwiki table declares are considered. Every candidate is checked to exist
before it is written, and a language the page already carries is left as its
author wrote it. The corollary is worth knowing: a wrong link on one wiki of
the farm will spread to the others over a few runs, exactly as a right one
does.

**Where they go and in what order.** The block is moved to the very end of the
page, after the categories, and sorted by language code — the order the
operator's earlier script used (``en``, ``ru``, ``uk``). It is also the order
Fandom shows, and that was checked rather than assumed: the main page of
tadc:ru carries its links as en, es, id, ja, pl, uk, zh, pt-br, and the
language menu on the rendered page reads en, es, id, ja, pl, pt-br, uk, zh.
Fandom sorts the menu by code itself, whatever the source says, so sorting
the source changes nothing a reader sees — it makes the source read the way
the menu already does. The one change a reader *can* see is a link added.

**No edit for whitespace.** A page whose links are already complete, already
in order and already last is left alone even if the blank lines around the
block differ, and a link taken out of the middle of the text goes with its
line break, so it leaves no gap. Both were missing once: a run over tadc:ru
made 221 edits that added nothing, 151 of them leaving a triple line break
where a link had been.

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
from tasks import report
from utils import Explained
from tasks.params import FLAGS, Param
from scripts import wikitools as wt

logger = logging.getLogger("fd.scripts.interwiki")

FLAG_SORT_ONLY = "sort_only"
"""Add nothing: only move the block to the end of the page and sort it.

The one thing this mechanic can usefully be told, because adding links is the
only thing it does that somebody might not want done.

There was a second flag beside it, `no_propagate`, offered as «не собирать
ссылки с соседних языковых версий». It named the implementation rather than
the result, and it gated the very same condition as this one — two options in
the dialog, one behaviour, and a person having to guess which was which. The
plainer of the two stayed. Nothing stored used the other, so nothing had to be
migrated; do not bring it back."""

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
        raise Explained("error_interwiki_map", error=str(e))

    own_host = _host_family(ctx.site.base_url(""))
    if not own_host:
        try:
            own_host = families.family_name(ctx.site.hostname())
        except Exception:
            own_host = None

    langs = {}
    managed = set()
    for entry in data:
        prefix = str(entry.get("prefix") or "").lower()
        if not prefix or prefix == ctx.lang:
            continue
        if "language" not in entry and not entry.get("language"):
            continue
        managed.add(prefix)
        host = _host_family(entry.get("url"))
        if not host or (own_host and host != own_host):
            continue
        langs[prefix] = {"family": families.family_name(host),
                         "lang": prefix, "url": entry.get("url")}

    if not managed:
        ctx.note("note_interwiki_none")
    else:
        ctx.note("note_interwiki_langs", langs=", ".join(sorted(managed)))
        elsewhere = sorted(managed - set(langs))
        if elsewhere:
            ctx.note("note_interwiki_elsewhere", langs=", ".join(elsewhere))
    return {"langs": langs, "managed": managed, "sites": {}, "exists": {},
            "links": {}}


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
            from wiki import families

            family, code = families.ensure_family(entry["url"])
            entry["family"], entry["lang"] = family, code
            site = wiki.get_site(family, code)
        except Exception as e:
            logger.warning("cannot reach the %s wiki: %s", lang, e)
            ctx.note("note_interwiki_unreachable", lang=lang,
                     error=report.safe_error(e, ctx.reader))
        finally:
            wiki.use_cookies(ctx.wiki)
    state["sites"][lang] = site
    return site


def _exists(ctx, lang, title):
    """Whether one page exists on one sister wiki, asked once per title.

    Opening the sister restores the caller's jar before it returns, so the
    sister's jar must be selected again for the actual page request. This
    is equally necessary when its Site came from the cache.
    """
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
            entry = state["langs"][lang]
            wiki.use_cookies("{}:{}".format(entry["family"], entry["lang"]))
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
            entry = state["langs"][lang]
            wiki.use_cookies("{}:{}".format(entry["family"], entry["lang"]))
            text, _saved = _mask_disabled(pywikibot.Page(site, title).text)
            for match in _IW_LINE_RE.finditer(text):
                found[match.group("lang").lower()] = match.group("title").strip()
        except Exception as e:
            logger.warning("cannot read %s:%s: %s", lang, title, e)
        finally:
            wiki.use_cookies(ctx.wiki)
    state["links"][key] = found
    return found


def _mask_disabled(text):
    """Keep commented and escaped examples out of the language graph.

    Moving a ``[[lang:Title]]`` line from inside nowiki or a comment into
    the final block would turn an intentionally disabled link into a real
    language link. The same protection is needed when reading sisters.
    """
    spans = [(match.start(), match.end())
             for pattern in (wt.COMMENT_RE, wt.OPAQUE_RE)
             for match in pattern.finditer(text)]
    return wt.mask(text, wt.merge_spans(spans))


def _strip(text, managed):
    """Take the managed language lines out. -> (rest, {lang: title}, clash).

    Only prefixes in `managed` are touched; any other ``[[prefix:…]]`` line
    stays where it is. A line is removed together with its line break, and the
    blank lines that stood *after* a removed block are absorbed into the ones
    before it — a block with a blank line on each side would otherwise leave
    the two side by side, which is the triple line break a run over tadc:ru
    left on 151 pages.

    `clash` is True when one language is linked twice with two different
    titles. The page is then left exactly as it is: which of the two is right
    is a question for a person, and rebuilding the block would silently keep
    one and drop the other.
    """
    text, saved = _mask_disabled(text)
    found, kept, clash = {}, [], False
    after_removal = False
    for line in text.split("\n"):
        match = _IW_LINE_RE.match(line)
        lang = match.group("lang").lower() if match else None
        if lang is None or lang not in managed:
            blank = not line.strip()
            if after_removal and blank and kept and not kept[-1].strip():
                continue
            kept.append(line)
            if not blank:
                after_removal = False
            continue
        after_removal = True
        title = match.group("title").strip()
        if lang in found and found[lang] != title:
            clash = True
        found.setdefault(lang, title)
    return wt.unmask("\n".join(kept), saved), found, clash


def _squash(text):
    """Text with the differences no reader sees taken out: trailing spaces,
    runs of blank lines, the ends. Two versions equal under this are the same
    page, and are not worth an edit."""
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def apply(ctx, page, text):
    """One page's interlanguage links completed and sorted."""
    state = ctx.state.get(SPEC.code) or {}
    known_langs = state.get("langs") or {}
    managed = state.get("managed") or set(known_langs)
    if not managed:
        return text, []

    flags = set(ctx.params.get("interwiki_flags") or [])
    body, present, clash = _strip(text, managed)
    if clash:
        ctx.note("note_interwiki_clash",
                 title=page.title() if page is not None else "?")
        return text, []
    links = dict(present)

    added = []
    if FLAG_SORT_ONLY not in flags:
        pending = [(lang, title) for lang, title in links.items()
                   if lang in known_langs]
        while pending:
            lang, title = pending.pop(0)
            for other_lang, other_title in _links_of(ctx, lang, title).items():
                if other_lang == ctx.lang or other_lang in links:
                    continue
                if other_lang not in known_langs:
                    continue
                if _exists(ctx, other_lang, other_title):
                    links[other_lang] = other_title
                    added.append(other_lang)
                    pending.append((other_lang, other_title))

    if not links:
        return text, []

    block = "\n".join("[[{}:{}]]".format(lang, links[lang])
                      for lang in sorted(links))
    new = body.rstrip() + "\n\n" + block
    if _squash(new) == _squash(text):
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
        )),
    ),
)
