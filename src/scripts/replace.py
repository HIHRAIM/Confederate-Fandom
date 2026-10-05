"""Replace text across pages — the bot's shape of Pywikibot's replace.py.

    Pywikibot's replace.py is (C) Pywikibot team, 2004-2025, MIT licence.
    What is kept here is its behaviour, not its code: the command line, the
    interactive questions and the fixes file belong to a script somebody runs
    at a terminal, and none of them survive the trip into a chat dialog.

Two ways to search, chosen by the flags: plain text, or a regular expression
with ``\\1`` back references in the replacement. Case can be ignored. And a
third flag protects the markup — with it the replacement runs over the masked
text (scripts/wikitools.py), so links, categories, file names, template names
and tables are out of reach and only the prose is touched. It is off by
default because a plain replacement often *is* meant for a link.

An empty replacement is how text is deleted; the dialog takes a lone dash for
it, since neither messenger will send an empty message.
"""
import re
import sys

from tasks import mechanic as mech
from utils import Explained
from tasks.params import BLANK, FLAGS, TEXT, Param

from scripts import wikitools as wt

FLAG_REGEX = "regex"
FLAG_NOCASE = "nocase"
FLAG_PROTECT = "protect"

def prepare(ctx):
    """Compile the pattern once for the whole run. -> the compiled pattern.

    A bad regular expression must stop the task here, before a single page is
    read, and not on page four hundred: the error the person gets is about
    what they typed, which is the only thing they can act on.
    """
    params = ctx.params
    flags = set(params.get("replace_flags") or [])
    find = params.get("find") or ""
    if not find:
        raise Explained("error_replace_no_find")
    pattern = find if FLAG_REGEX in flags else re.escape(find)
    options = re.IGNORECASE if FLAG_NOCASE in flags else 0
    engine = wt.engine() if FLAG_REGEX in flags else re
    try:
        return engine.compile(pattern, options)
    except Exception as e:
        raise Explained("error_bad_regex", pattern=find, error=str(e))

def apply(ctx, page, text):
    """One page's text with the replacement made. -> (text, change labels)."""
    params = ctx.params
    flags = set(params.get("replace_flags") or [])
    pattern = ctx.state.get(SPEC.code)
    replacement = params.get("replace") or ""
    if FLAG_REGEX not in flags:
        replacement = replacement.replace("\\", "\\\\")

    if FLAG_PROTECT in flags:
        spans = wt.protected_spans(text)
        masked, saved = wt.mask(text, spans)
        new, count = pattern.subn(replacement, masked)
        new = wt.unmask(new, saved)
    else:
        new, count = pattern.subn(replacement, text)

    if not count or new == text:
        return text, []
    return new, ["замена ×{}".format(count)]

def summary_part(ctx, labels):
    """What this mechanic contributes to the edit summary."""
    if not labels:
        return None
    find = ctx.params.get("find") or ""
    replacement = ctx.params.get("replace") or ""
    if replacement:
        return "замена «{}» на «{}»".format(find, replacement)
    return "удаление «{}»".format(find)

SPEC = mech.Mechanic(
    code="replace",
    kind=mech.TEXT,
    module=sys.modules[__name__],
    rights=("edit",),
    params=(
        Param("find", TEXT, "param_find"),
        Param("replace", TEXT, "param_replace", blank=BLANK),
        Param("replace_flags", FLAGS, "param_replace_flags", options=(
            (FLAG_REGEX, "flag_regex"),
            (FLAG_NOCASE, "flag_nocase"),
            (FLAG_PROTECT, "flag_protect"),
        )),
    ),
)
