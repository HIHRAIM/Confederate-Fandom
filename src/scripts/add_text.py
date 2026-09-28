"""Add a block of text to pages — the bot's shape of Pywikibot's add_text.py.

    Pywikibot's add_text.py is (C) Filnik, 2007-2008 and the Pywikibot team,
    2007-2025, MIT licence. What is kept here is its behaviour: put a block at
    the top or at the bottom of a page, and do not put it there twice.

Three places, and the third is the one that matters on a wiki with categories:
`bottom` appends after everything, which drops the block *below* the category
block where nobody looks; `before_categories` puts it after the prose and
before the first category, interwiki or DEFAULTSORT, which is where a
maintenance notice or a navbox belongs.

By default a page that already contains the block is left alone, so a task can
be re-run over a category that has grown without doubling the block on
everything that was there the first time. The flag turns that off.
"""
import re
import sys

from tasks import mechanic as mech
from utils import Explained
from tasks.params import CHOICE, FLAGS, LONGTEXT, Param

TOP = "top"
BOTTOM = "bottom"
BEFORE_CATEGORIES = "before_categories"

FLAG_AGAIN = "again"
FLAG_NEWLINE = "newline"

_TAIL_RE = re.compile(
    r"(?:^\s*(?:\[\[\s*(?:[Кк]атегория|[Кк]атегорія|[Cc]ategory)\s*:[^\]]*\]\]"
    r"|\[\[\s*[a-z][a-z-]{1,11}\s*:[^\]]*\]\]"
    r"|\{\{\s*(?:DEFAULTSORT|СОРТИРОВКА|ПОРЯДОК_СОРТИРОВКИ|СОРТУВАННЯ)[^}]*\}\})"
    r"\s*$)", re.M)
"""The tail of an article: categories, interlanguage links and the sort key.
`before_categories` inserts in front of the first of them."""


def prepare(ctx):
    """Nothing to compile; the check is that there is something to add."""
    if not (ctx.params.get("add_text") or "").strip():
        raise Explained("error_addtext_no_text")
    return None


def _tail_start(text):
    """Where the category block begins, or the length of the text."""
    first = None
    for match in _TAIL_RE.finditer(text):
        if first is None or match.start() < first:
            first = match.start()
    return len(text) if first is None else first


def apply(ctx, page, text):
    """One page's text with the block added. -> (text, change labels)."""
    block = (ctx.params.get("add_text") or "").strip("\n")
    flags = set(ctx.params.get("add_flags") or [])
    where = ctx.params.get("add_where") or BEFORE_CATEGORIES

    if FLAG_AGAIN not in flags and block.strip() and block.strip() in text:
        return text, []

    separator = "\n\n" if FLAG_NEWLINE in flags else "\n"

    if where == TOP:
        new = block + separator + text.lstrip("\n")
    elif where == BOTTOM:
        new = text.rstrip("\n") + separator + block + "\n"
    else:
        cut = _tail_start(text)
        head = text[:cut].rstrip("\n")
        tail = text[cut:].lstrip("\n")
        new = head + separator + block + ("\n\n" + tail if tail else "\n")

    if new == text:
        return text, []
    return new, ["добавлен текст"]


def summary_part(ctx, labels):
    """What this mechanic contributes to the edit summary."""
    return "добавление текста" if labels else None


SPEC = mech.Mechanic(
    code="addtext",
    kind=mech.TEXT,
    module=sys.modules[__name__],
    rights=("edit",),
    params=(
        Param("add_text", LONGTEXT, "param_add_text"),
        Param("add_where", CHOICE, "param_add_where", options=(
            (BEFORE_CATEGORIES, "add_where_before_categories"),
            (TOP, "add_where_top"),
            (BOTTOM, "add_where_bottom"),
        )),
        Param("add_flags", FLAGS, "param_add_flags", options=(
            (FLAG_AGAIN, "flag_add_again"),
            (FLAG_NEWLINE, "flag_add_newline"),
        )),
    ),
)
