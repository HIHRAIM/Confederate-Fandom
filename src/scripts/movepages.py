"""Rename pages by a rule — the bot's shape of Pywikibot's movepages.py.

    Pywikibot's movepages.py is (C) Leonardo Gregianin, 2006, Andreas J.
    Schwab, 2007, xqt, 2009-2025 and the Pywikibot team, 2006-2025, MIT
    licence. Its options are kept: add or strip a prefix or a suffix, or
    rewrite the title with a regular expression, and choose what happens to
    the redirect, the talk page and the subpages.

A move is not an edit and cannot be undone by editing, so this mechanic is
marked destructive and the confirmation says so. Two things are refused
outright rather than attempted:

* a rule that would leave the title unchanged — moving a page onto itself is
  an error on every wiki, and a rule that does it to every page is a rule
  somebody mistyped;
* a target that already exists — overwriting it would mean deleting somebody
  else's page, which is a decision for a person.

Not leaving a redirect behind needs `suppressredirect`, which the bot group
does not carry on Fandom; the flag is checked before the first page rather
than failing on each one.
"""
import re
import sys

from tasks import mechanic as mech
from tasks.params import CHOICE, FLAGS, TEXT, Param

PREFIX_ADD = "prefix_add"
PREFIX_REMOVE = "prefix_remove"
SUFFIX_ADD = "suffix_add"
SUFFIX_REMOVE = "suffix_remove"
REGEX = "regex"

FLAG_NO_REDIRECT = "no_redirect"
FLAG_MOVE_TALK = "move_talk"
FLAG_MOVE_SUBPAGES = "move_subpages"


def prepare(ctx):
    """Check the rule and the rights before the first page is moved."""
    mode = ctx.params.get("move_mode") or PREFIX_ADD
    argument = (ctx.params.get("move_argument") or "").strip()
    if not argument:
        raise ValueError("не указано, что добавлять, убирать или искать в названии")

    flags = set(ctx.params.get("move_flags") or [])
    if FLAG_NO_REDIRECT in flags:
        from wiki import rights

        if not rights.has_right(ctx.site, "suppressredirect"):
            raise ValueError(
                "чтобы переименовывать без перенаправления, нужно право "
                "suppressredirect — его даёт статус администратора")

    pattern = None
    if mode == REGEX:
        try:
            pattern = re.compile(argument)
        except re.error as e:
            raise ValueError("не удалось разобрать выражение «{}»: {}".format(
                argument, e))
    return {"mode": mode, "argument": argument, "pattern": pattern,
            "to": ctx.params.get("move_to") or ""}


def _new_title(state, title):
    """The title a page should have under this rule, or None to leave it."""
    mode, argument = state["mode"], state["argument"]
    if mode == PREFIX_ADD:
        return argument + title
    if mode == PREFIX_REMOVE:
        return title[len(argument):] if title.startswith(argument) else None
    if mode == SUFFIX_ADD:
        return title + argument
    if mode == SUFFIX_REMOVE:
        return title[:-len(argument)] if title.endswith(argument) else None
    if mode == REGEX:
        new = state["pattern"].sub(state["to"], title)
        return new if new != title else None
    return None


def act(ctx, page):
    """Move one page. -> (state, note)."""
    import pywikibot

    state = ctx.state.get(SPEC.code) or {}
    flags = set(ctx.params.get("move_flags") or [])
    title = page.title()
    target = _new_title(state, title)

    if not target or target == title:
        return "skip", None
    if not target.strip():
        return "fail", "новое название оказалось пустым"

    if pywikibot.Page(ctx.site, target).exists():
        return "fail", "страница «{}» уже существует".format(target)

    if ctx.dry_run:
        return "skip", "будет переименована в «{}»".format(target)

    try:
        page.move(target, reason=ctx.summary,
                  noredirect=FLAG_NO_REDIRECT in flags,
                  movetalk=FLAG_MOVE_TALK in flags,
                  movesubpages=FLAG_MOVE_SUBPAGES in flags)
    except Exception as e:
        return "fail", "{}: {}".format(type(e).__name__, e)
    return "done", "-> «{}»".format(target)


SPEC = mech.Mechanic(
    code="movepages",
    kind=mech.ACTION,
    module=sys.modules[__name__],
    rights=("move",),
    destructive=True,
    params=(
        Param("move_mode", CHOICE, "param_move_mode", options=(
            (PREFIX_ADD, "move_mode_prefix_add"),
            (PREFIX_REMOVE, "move_mode_prefix_remove"),
            (SUFFIX_ADD, "move_mode_suffix_add"),
            (SUFFIX_REMOVE, "move_mode_suffix_remove"),
            (REGEX, "move_mode_regex"),
        )),
        Param("move_argument", TEXT, "param_move_argument"),
        Param("move_to", TEXT, "param_move_to",
              depends=("move_mode", REGEX)),
        Param("move_flags", FLAGS, "param_move_flags", options=(
            (FLAG_NO_REDIRECT, "flag_no_redirect"),
            (FLAG_MOVE_TALK, "flag_move_talk"),
            (FLAG_MOVE_SUBPAGES, "flag_move_subpages"),
        )),
    ),
)
