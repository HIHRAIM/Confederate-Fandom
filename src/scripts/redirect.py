"""Redirects — the bot's shape of Pywikibot's redirect.py and fixing_redirects.py.

    Pywikibot's redirect.py is (C) Daniel Herding, 2004, Purodha Blissenbach,
    2004, xqt, 2009-2025 and the Pywikibot team, 2004-2025; fixing_redirects.py
    is (C) Frederic Bavay, 2004, Cosoleto, 2004 and the Pywikibot team,
    2004-2025. Both MIT. The command-line script walks the wiki's own redirect
    tables; here the page list comes from the dialog like every other
    mechanic's, which is the one real difference.

Three things it can do, and they are three different jobs:

* **двойные** — a redirect that points at another redirect. MediaWiki does not
  follow the second hop, so the reader lands on a redirect page and has to
  click again. Fixed by pointing the first one straight at the end of the
  chain.
* **ссылки** — links in an ordinary article that point at a redirect. Nothing
  is broken, but the link costs a hop; this rewrites them to the target while
  keeping what the reader sees, so ``[[Псевдоним]]`` becomes
  ``[[Настоящее имя|Псевдоним]]`` and not ``[[Настоящее имя]]``.
* **битые** — a redirect whose target does not exist. Nothing is edited: what
  to do with one is a decision for a person, so they are collected into the
  task's report and left alone.

A chain is followed at most CHAIN_LIMIT hops. Redirects can be circular, and a
bot that follows one for ever is a bot nobody can stop.

**The first two modes walk redirects, and say so** (`redirects` below). The
page sources that enumerate a wiki list ordinary pages unless the mechanics
of the task ask for something else, and this one used not to ask: on
glitchproductions:ru, with thirteen double redirects on
Служебная:Двойные_перенаправления, a run over all pages was handed the 212
articles, looked at each, found none of them a redirect and finished with
0 edits and no error. The third mode reads articles and asks for those.
"""
import re
import sys

from tasks import mechanic as mech
from tasks.params import CHOICE, Param

DOUBLE = "double"
LINKS = "links"
BROKEN = "broken"

CHAIN_LIMIT = 10

_LINK_RE = re.compile(r"\[\[([^\[\]\|#]+)(#[^\[\]\|]*)?(\|([^\[\]]*))?\]\]")

def redirects(params):
    """Which pages the chosen mode works on: redirects for «двойные» and
    «битые», ordinary pages for «ссылки» (see `Mechanic.redirects`)."""
    return (params.get("redirect_mode") or DOUBLE) != LINKS

def _redirect_link(ctx, title):
    """The link a redirect page carries, pointing at `title`.

    A redirect to a category or a file needs the leading colon: without it
    ``[[Категория:…]]`` is read as putting the page into that category, and
    ``[[Файл:…]]`` as showing the picture.
    """
    import pywikibot

    try:
        namespace = pywikibot.Page(ctx.site, title).namespace()
    except Exception:
        namespace = 0
    return "[[{}{}]]".format(":" if namespace in (6, 14) else "", title)

def prepare(ctx):
    """A cache of what each title resolves to, shared by every page of the run.

    A run over a category asks about the same handful of redirects again and
    again; without the cache that is one request per link per page.
    """
    return {"resolved": {}, "exists": {}}

def _final_target(ctx, title):
    """Follow a redirect chain to its end. -> (title, exists, hops).

    A cycle, unreadable target or chain longer than CHAIN_LIMIT returns
    ``exists=None``: no safe destination was proved. Rewriting toward the
    last intermediate redirect would preserve the fault or create a loop.
    A section inherited from an earlier hop takes precedence over later
    ones, just as an explicit section on the original link does.
    """
    import pywikibot

    cache = ctx.state.get(SPEC.code)["resolved"]
    if title in cache:
        return cache[title]

    seen = []
    current = title
    hops = 0
    exists = None
    while hops < CHAIN_LIMIT:
        base, separator, section = current.partition("#")
        if base in seen:
            break
        seen.append(base)
        page = pywikibot.Page(ctx.site, base)
        try:
            if not page.exists():
                exists = False
                break
            if not page.isRedirectPage():
                exists = True
                break
            current = page.getRedirectTarget().title()
            if separator:
                current = current.split("#", 1)[0] + "#" + section
            hops += 1
        except Exception:
            break
    result = (current, exists, hops)
    cache[title] = result
    return result

def apply(ctx, page, text):
    """One page's redirects put right. -> (text, change labels)."""
    mode = ctx.params.get("redirect_mode") or DOUBLE

    if mode in (DOUBLE, BROKEN):
        try:
            if not page.isRedirectPage():
                return text, []
            first = page.getRedirectTarget().title()
        except Exception:
            return text, []
        final, exists, hops = _final_target(ctx, first)
        if mode == BROKEN:
            if exists is False:
                ctx.note("note_redirect_broken", title=page.title(),
                         target=first)
            return text, []
        if hops == 0 or final == first or not exists:
            return text, []
        link = _redirect_link(ctx, final)
        new = re.sub(r"\[\[[^\]]+\]\]", lambda _match: link, text, count=1)
        if new == text:
            return text, []
        return new, ["двойное перенаправление"]

    try:
        if page.isRedirectPage():
            return text, []
    except Exception:
        return text, []

    count = [0]

    def _fix(match):
        """One link, pointed at the end of its chain."""
        target = match.group(1).strip()
        section = match.group(2) or ""
        label = match.group(4)
        if not target or target.startswith((":", "#")):
            return match.group(0)
        if ":" in target:
            """Local user and project links are ordinary navigational links.

            A colon alone does not identify an interwiki or an embedding.
            Resolve the local namespace so those links can be shortened,
            while preserving file/category inclusions and foreign links.
            """
            import pywikibot
            try:
                linked = pywikibot.Page(ctx.site, target)
                if linked.site != ctx.site or linked.namespace() in (6, 14):
                    return match.group(0)
            except Exception:
                return match.group(0)
        final, exists, hops = _final_target(ctx, target)
        if hops == 0 or not exists or final == target:
            return match.group(0)
        count[0] += 1
        shown = label if label is not None else target
        if section:
            final = final.split("#", 1)[0]
        return "[[{}{}|{}]]".format(final, section, shown)

    new = _LINK_RE.sub(_fix, text)
    if not count[0] or new == text:
        return text, []
    return new, ["ссылка на перенаправление ×{}".format(count[0])]

def summary_part(ctx, labels):
    """What this mechanic contributes to the edit summary."""
    if not labels:
        return None
    mode = ctx.params.get("redirect_mode") or DOUBLE
    if mode == DOUBLE:
        return "исправление двойного перенаправления"
    return "ссылки на перенаправления заменены на прямые"

SPEC = mech.Mechanic(
    code="redirect",
    kind=mech.TEXT,
    module=sys.modules[__name__],
    rights=("edit",),
    params=(
        Param("redirect_mode", CHOICE, "param_redirect_mode", options=(
            (DOUBLE, "redirect_mode_double"),
            (LINKS, "redirect_mode_links"),
            (BROKEN, "redirect_mode_broken"),
        )),
    ),
)
