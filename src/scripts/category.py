"""Add, remove or move a category — the bot's shape of Pywikibot's category.py.

    Pywikibot's category.py is (C) Rob W. W. Hooft, 2004, Daniel Herding,
    2004, Wikipedian, 2004-2008, leogregianin, 2004-2008, Cyde, 2006-2010,
    Anreas J Schwab, 2007, xqt, 2009-2025 and the Pywikibot team, 2008-2025,
    MIT licence. That script does a dozen things (listify, tidy, tree, clean);
    what is kept here are the three a person asks a bot for over a page list.

The category is written in the wiki's own namespace name — `Категория:` on a
Russian wiki, `Категорія:` on a Ukrainian one, `Category:` on an English one —
because that is what its authors will see in the diff. Both spellings are
recognised when reading, so a page categorised in English on a Russian wiki is
still found.

A category is added at the end of the article, after the prose and before the
interlanguage links, which is where MediaWiki's own convention puts it. A
category that is already there is not added twice.
"""
import re
import sys

from tasks import mechanic as mech
from utils import Explained
from tasks.params import CHOICE, TEXT, Param

ADD = "add"
REMOVE = "remove"
MOVE = "move"

_ANY_CATEGORY_PREFIX = r"(?:[Кк]атегория|[Кк]атегорія|[Cc]ategory|[Кк]атэгорыя)"

_INTERWIKI_TAIL_RE = re.compile(
    r"(?:^\s*\[\[\s*[a-z][a-z-]{1,11}\s*:[^\]]*\]\]\s*$)", re.M)

def _clean(name):
    """A category name without its namespace prefix and without decoration."""
    text = str(name or "").strip().lstrip(":")
    text = re.sub(r"^" + _ANY_CATEGORY_PREFIX + r"\s*:\s*", "", text)
    return re.sub(r"\s+", " ", text.replace("_", " ")).strip()

def prepare(ctx):
    """Work out the wiki's own word for "category" and check the arguments.

    -> {'prefix', 'name', 'to', 'pattern'} — everything `apply` needs without
    asking the wiki again for every page.
    """
    action = ctx.params.get("category_action") or ADD
    name = _clean(ctx.params.get("category_name"))
    target = _clean(ctx.params.get("category_to"))
    if not name:
        raise Explained("error_category_no_name")
    if action == MOVE and not target:
        raise Explained("error_category_no_target")

    try:
        prefix = ctx.site.namespace(14)
    except Exception:
        prefix = "Category"

    def _pattern(title):
        """A pattern matching one category link however it is spelt."""
        head = title[0]
        body = re.escape(title[1:]).replace(r"\ ", r"[ _]")
        return re.compile(
            r"\[\[\s*" + _ANY_CATEGORY_PREFIX + r"\s*:\s*"
            r"(?:" + re.escape(head.upper()) + "|" + re.escape(head.lower()) + r")" + body +
            r"\s*(\|[^\]]*)?\]\]\n?", re.UNICODE)

    return {"prefix": prefix, "name": name, "to": target,
            "pattern": _pattern(name),
            "target_pattern": _pattern(target) if target else None}

def _insert(text, line):
    """Put one category line where categories belong: after the prose."""
    match = None
    for found in _INTERWIKI_TAIL_RE.finditer(text):
        if match is None or found.start() < match.start():
            match = found
    if match is None:
        return text.rstrip("\n") + "\n" + line + "\n"
    return text[:match.start()].rstrip("\n") + "\n" + line + "\n\n" + \
        text[match.start():].lstrip("\n")

def apply(ctx, page, text):
    """One page with its categories changed. -> (text, change labels)."""
    state = ctx.state.get(SPEC.code) or {}
    action = ctx.params.get("category_action") or ADD
    prefix, name, target = state["prefix"], state["name"], state["to"]
    pattern = state["pattern"]

    if action == REMOVE:
        new, count = pattern.subn("", text)
        if not count:
            return text, []
        return new.rstrip("\n") + "\n", ["убрана категория ×{}".format(count)]

    if action == MOVE:
        """Keep the old sort key unless the target already has its own.

        Matching the destination by its normalized pattern also recognizes
        English namespace aliases and lowercase initials, preventing a
        second categorization of the same page.
        """
        if name[:1].upper() + name[1:] == target[:1].upper() + target[1:]:
            return text, []
        target_exists = bool(state["target_pattern"].search(text))

        def _move(match):
            """Replace one category in place, retaining its explicit key."""
            nonlocal target_exists
            if target_exists:
                return ""
            target_exists = True
            tail = "\n" if match.group(0).endswith("\n") else ""
            return "[[{}:{}{}]]{}".format(prefix, target,
                                          match.group(1) or "", tail)

        new, count = pattern.subn(_move, text)
        if not count or new == text:
            return text, []
        return new, ["категория заменена"]

    if pattern.search(text):
        return text, []
    return _insert(text, "[[{}:{}]]".format(prefix, name)), ["добавлена категория"]

def summary_part(ctx, labels):
    """What this mechanic contributes to the edit summary."""
    if not labels:
        return None
    state = ctx.state.get(SPEC.code) or {}
    action = ctx.params.get("category_action") or ADD
    if action == REMOVE:
        return "убрана категория «{}»".format(state.get("name"))
    if action == MOVE:
        return "категория «{}» заменена на «{}»".format(
            state.get("name"), state.get("to"))
    return "добавлена категория «{}»".format(state.get("name"))

SPEC = mech.Mechanic(
    code="category",
    kind=mech.TEXT,
    module=sys.modules[__name__],
    rights=("edit",),
    params=(
        Param("category_action", CHOICE, "param_category_action", options=(
            (ADD, "category_action_add"),
            (REMOVE, "category_action_remove"),
            (MOVE, "category_action_move"),
        )),
        Param("category_name", TEXT, "param_category_name"),
        Param("category_to", TEXT, "param_category_to",
              depends=("category_action", MOVE)),
    ),
)
