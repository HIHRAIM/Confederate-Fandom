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


def prepare(ctx):
    """A cache of what each title resolves to, shared by every page of the run.

    A run over a category asks about the same handful of redirects again and
    again; without the cache that is one request per link per page.
    """
    return {"resolved": {}, "exists": {}}


def _final_target(ctx, title):
    """Follow a redirect chain to its end. -> (title, exists, hops).

    A chain longer than CHAIN_LIMIT, or one that comes back to where it
    started, stops and reports the last title it reached: a loop is a thing
    for a person to look at, not for a bot to keep walking.
    """
    import pywikibot

    cache = ctx.state.get(SPEC.code)["resolved"]
    if title in cache:
        return cache[title]

    seen = []
    current = title
    hops = 0
    exists = True
    while hops < CHAIN_LIMIT:
        if current in seen:
            break
        seen.append(current)
        page = pywikibot.Page(ctx.site, current)
        try:
            if not page.exists():
                exists = False
                break
            if not page.isRedirectPage():
                break
            current = page.getRedirectTarget().title(with_section=False)
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
            first = page.getRedirectTarget().title(with_section=False)
        except Exception:
            return text, []
        final, exists, hops = _final_target(ctx, first)
        if mode == BROKEN:
            if not exists:
                ctx.note("битое перенаправление: {} -> {}".format(
                    page.title(), first))
            return text, []
        if hops == 0 or final == first or not exists:
            return text, []
        new = re.sub(r"\[\[[^\]]+\]\]", "[[{}]]".format(final), text, count=1)
        if new == text:
            return text, []
        return new, ["двойное перенаправление"]

    count = [0]

    def _fix(match):
        """One link, pointed at the end of its chain."""
        target = match.group(1).strip()
        section = match.group(2) or ""
        label = match.group(4)
        if not target or target.startswith((":", "#")) or ":" in target.split("|")[0][:12]:
            return match.group(0)
        final, exists, hops = _final_target(ctx, target)
        if hops == 0 or not exists or final == target:
            return match.group(0)
        count[0] += 1
        shown = label if label is not None else target
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
