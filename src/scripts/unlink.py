"""Unlink a page — the bot's shape of Pywikibot's unlink.py.

    Pywikibot's unlink.py is (C) Pywikibot team, 2007-2025, MIT licence. What
    is kept here is what it does: take the links to one page out of every page
    that has them, and leave the words behind.

``[[Цель]]`` becomes ``Цель``, ``[[Цель|подпись]]`` becomes ``подпись``, and
``[[Цель]]ы`` becomes ``Целы`` — the trailing letters MediaWiki draws inside
the link belong to the word, so they stay attached to it.

What is deliberately not touched:

* ``[[:Цель]]`` — the leading colon makes it an ordinary link in the text
  (that is how a category or a file is linked to rather than used), and a
  person who wrote one meant it;
* ``[[Файл:Цель.jpg]]`` and ``[[Категория:Цель]]`` — those are not links to
  the page, they are a picture and a categorisation. Removing a file with
  this mechanic would blank an illustration, which is what `image` is for.

The page set is normally the pages that link to the target — the `backlinks`
source of the dialog answers exactly that question.
"""
import re
import sys

from tasks import mechanic as mech
from utils import Explained
from tasks.params import FLAGS, TEXT, Param

FLAG_KEEP_BOLD = "keep_bold"

def _normalise(title):
    """A page title as MediaWiki compares them: spaces, first letter capital."""
    text = str(title or "").strip().replace("_", " ")
    text = re.sub(r"\s+", " ", text).lstrip(":")
    return text[:1].upper() + text[1:] if text else text

def prepare(ctx):
    """Build the pattern that matches links to the target. -> the pattern.

    The title is matched with its first letter in either case, because
    MediaWiki treats ``[[цель]]`` and ``[[Цель]]`` as the same page, and with
    underscores accepted for spaces for the same reason.
    """
    title = _normalise(ctx.params.get("unlink_title"))
    if not title:
        raise Explained("error_unlink_no_title")
    head = title[0]
    body = re.escape(title[1:]).replace(r"\ ", r"[ _]")
    pattern = "[{}{}]{}".format(head.upper(), head.lower(), body)
    return re.compile(
        r"\[\[\s*(?P<target>" + pattern + r")\s*"
        r"(?:\|(?P<label>[^\]\|]*))?\]\](?P<tail>[a-zа-яёіїєґ]*)",
        re.UNICODE)

def apply(ctx, page, text):
    """One page's text with the links to the target taken out."""
    pattern = ctx.state.get(SPEC.code)
    flags = set(ctx.params.get("unlink_flags") or [])
    count = [0]

    def _replace(match):
        """One link -> the words it was showing."""
        label = match.group("label")
        shown = label if label is not None else match.group("target")
        shown = shown.strip() + (match.group("tail") or "")
        count[0] += 1
        return "'''{}'''".format(shown) if FLAG_KEEP_BOLD in flags else shown

    new = pattern.sub(_replace, text)
    if not count[0] or new == text:
        return text, []
    return new, ["снята ссылка ×{}".format(count[0])]

def summary_part(ctx, labels):
    """What this mechanic contributes to the edit summary."""
    if not labels:
        return None
    return "убраны ссылки на «{}»".format(
        _normalise(ctx.params.get("unlink_title")))

SPEC = mech.Mechanic(
    code="unlink",
    kind=mech.TEXT,
    module=sys.modules[__name__],
    rights=("edit",),
    params=(
        Param("unlink_title", TEXT, "param_unlink_title"),
        Param("unlink_flags", FLAGS, "param_unlink_flags", options=(
            (FLAG_KEEP_BOLD, "flag_unlink_bold"),
        )),
    ),
)
