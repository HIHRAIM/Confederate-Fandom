"""Rename pages by a rule — the bot's shape of Pywikibot's movepages.py.

    Pywikibot's movepages.py is (C) Leonardo Gregianin, 2006, Andreas J.
    Schwab, 2007, xqt, 2009-2025 and the Pywikibot team, 2006-2025, MIT
    licence. Its options are kept: add or strip a prefix or a suffix, or
    rewrite the title with a regular expression, and choose what happens to
    the redirect, the talk page and the subpages.

One mode is this bot's own: **a list of pairs**. A rule is the right shape for
a hundred pages named alike and the wrong shape for nine pages named nothing
alike, and the second is what people actually ask for. So `list` takes a
pasted block of ``старое_название новое_название``, one rename per line, and
the pages of the run are the left-hand column — which is why the mode goes
with the `pairs` page source and refuses to run with any other: both halves
are read out of the same block, and taking pages from somewhere else would
mean moving pages the list never named.

Spaces in a title are written as underscores there, the way MediaWiki writes
them in a URL. That is not a whim either: Discord's own markdown turns text
between underscores into italics and eats them, so a person pasting a list
into Discord wraps it in a code fence — which `tasks/params.py: parse_pairs`
strips.

A move is not an edit and cannot be undone by editing, so this mechanic is
marked destructive and the confirmation says so. Two things are refused
outright rather than attempted:

* a rule that would leave the title unchanged — moving a page onto itself is
  an error on every wiki, and a rule that does it to every page is a rule
  somebody mistyped;
* a target that already exists — overwriting it would mean deleting somebody
  else's page, which is a decision for a person.

Not leaving a redirect behind needs `suppressredirect`; the session's actual
rights are checked before the first page rather than inferred from its group.
"""
import re
import sys

from tasks import mechanic as mech
from utils import Explained, localized
from tasks.params import BLANK, CHOICE, FLAGS, TEXT, Param

PREFIX_ADD = "prefix_add"
PREFIX_REMOVE = "prefix_remove"
SUFFIX_ADD = "suffix_add"
SUFFIX_REMOVE = "suffix_remove"
REGEX = "regex"
LIST = "list"

RULE_MODES = (PREFIX_ADD, PREFIX_REMOVE, SUFFIX_ADD, SUFFIX_REMOVE, REGEX)
"""The modes that work by a rule, and so have something to be told.

`list` is the one that does not: it is handed the whole answer at once, in the
page source, and asking it for a prefix as well would be asking a question
with no answer."""

FLAG_NO_REDIRECT = "no_redirect"
FLAG_MOVE_TALK = "move_talk"
FLAG_MOVE_SUBPAGES = "move_subpages"


def _pair_map(pairs):
    """The renames by title, under every spelling the wiki might answer with.

    A wiki capitalises the first letter of a title, so «список серий» and
    «Список серий» are one page to it and two strings here. The pages come
    back from Pywikibot in the wiki's spelling, so the capitalised form is
    kept as a key too and a line written in lower case still finds its page.
    """
    table = {}
    for old, new in pairs:
        table[old] = new
        if old[:1].islower():
            table[old[:1].upper() + old[1:]] = new
    return table


def prepare(ctx):
    """Check the rule and the rights before the first page is moved."""
    mode = ctx.params.get("move_mode") or PREFIX_ADD

    flags = set(ctx.params.get("move_flags") or [])
    if FLAG_NO_REDIRECT in flags:
        from wiki import rights

        if not rights.has_right(ctx.site, "suppressredirect"):
            raise rights.explain_missing(ctx.site, ["suppressredirect"])

    if mode == LIST:
        from tasks import pagesets
        from tasks.params import parse_pairs

        if (ctx.params.get("source") or "") != pagesets.PAIRS:
            raise Explained("error_move_list_source",
                            source=lambda lang: localized(
                                "pageset_" + pagesets.PAIRS, lang))
        pairs = parse_pairs(ctx.params.get("argument"))
        if not pairs:
            raise Explained("error_move_no_pairs")
        return {"mode": mode, "pairs": _pair_map(pairs), "argument": "",
                "pattern": None, "to": ""}

    argument = (ctx.params.get("move_argument") or "").strip()
    if not argument:
        raise Explained("error_move_no_argument")

    pattern = None
    if mode == REGEX:
        try:
            pattern = re.compile(argument)
        except re.error as e:
            raise Explained("error_bad_regex", pattern=argument, error=str(e))
    return {"mode": mode, "argument": argument, "pattern": pattern,
            "pairs": {}, "to": ctx.params.get("move_to") or ""}


def _new_title(state, title):
    """The title under this rule, or None when it already satisfies it.

    Adding an affix skips titles that already carry it, so selecting the
    moved pages for another run does not duplicate the prefix or suffix.
    """
    mode, argument = state["mode"], state["argument"]
    if mode == PREFIX_ADD:
        return None if title.startswith(argument) else argument + title
    if mode == PREFIX_REMOVE:
        return title[len(argument):] if title.startswith(argument) else None
    if mode == SUFFIX_ADD:
        return None if title.endswith(argument) else title + argument
    if mode == SUFFIX_REMOVE:
        return title[:-len(argument)] if title.endswith(argument) else None
    if mode == REGEX:
        new = state["pattern"].sub(state["to"], title)
        return new if new != title else None
    if mode == LIST:
        return state["pairs"].get(title)
    return None


def act(ctx, page):
    """Move one page. -> (state, note)."""
    import pywikibot

    state = ctx.state.get(SPEC.code) or {}
    flags = set(ctx.params.get("move_flags") or [])
    title = page.title()
    if not page.exists():
        return "skip", None
    target = _new_title(state, title)

    if not target or target == title:
        return "skip", None
    if not target.strip():
        return "fail", localized("page_move_empty", ctx.reader)

    if pywikibot.Page(ctx.site, target).exists():
        return "fail", localized("page_move_exists", ctx.reader, title=target)

    if ctx.dry_run:
        return "skip", localized("page_move_will", ctx.reader, title=target)

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
            (LIST, "move_mode_list"),
        )),
        Param("move_argument", TEXT, "param_move_argument",
              depends=("move_mode", RULE_MODES)),
        Param("move_to", TEXT, "param_move_to", blank=BLANK,
              depends=("move_mode", REGEX)),
        Param("move_flags", FLAGS, "param_move_flags", options=(
            (FLAG_NO_REDIRECT, "flag_no_redirect"),
            (FLAG_MOVE_TALK, "flag_move_talk"),
            (FLAG_MOVE_SUBPAGES, "flag_move_subpages"),
        )),
    ),
)
