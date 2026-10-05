"""Cosmetic changes alone — the wikifier, without any language rules.

The engine is `scripts/wikitools.py`, the same one the spelling mechanics use,
and the same protection applies: everything runs over the masked text, so
links, categories, file names, template names, tables, ``<pre>`` and
``<nowiki>`` are out of reach by construction.

What it does: spaces in headings (``==Раздел==`` -> ``== Раздел ==``), trailing
spaces, an indent that would turn a line into a code block, runs of blank
lines, a space before a punctuation mark, ``« - »`` -> ``« — »``, doubled
spaces inside a line, and blank lines at the end of the article.

It is a mechanic of its own as well as a flag on the spelling ones, because a
wiki whose language the bot has no rules for still wants its markup tidy — and
because the edit summary then says «косметические изменения» and nothing else,
which is the truth about that edit.

Pywikibot has a cosmetic_changes.py of its own ((C) Pywikibot team,
2006-2025, MIT licence). It is not what runs here: it renames templates and
rewrites links by rules that differ per project, and on a Fandom wiki that is
somebody else's opinion about their markup. This one only touches whitespace
and punctuation, which is the part nobody argues about.
"""
import sys

from tasks import mechanic as mech
from tasks.params import FLAGS, Param

from scripts import wikitools as wt

FLAG_LABELS = "labels"
FLAG_SKIP_REFS = "skip_refs"

def prepare(ctx):
    """Nothing to compile: the rules are the module's own."""
    return None

def apply(ctx, page, text):
    """One page's text, tidied. -> (text, change labels)."""
    flags = set(ctx.params.get("cosmetic_flags") or [])
    spans = wt.protected_spans(text, fix_labels=FLAG_LABELS in flags,
                               skip_refs=FLAG_SKIP_REFS in flags)
    masked, saved = wt.mask(text, spans)
    masked, changes = wt.apply_cosmetic(masked)
    new = wt.unmask(masked, saved)
    if new == text:
        return text, []
    return new, [name for name, _was, _now in changes]

def summary_part(ctx, labels):
    """What this mechanic contributes to the edit summary."""
    return "косметические изменения" if labels else None

SPEC = mech.Mechanic(
    code="cosmetic",
    kind=mech.TEXT,
    module=sys.modules[__name__],
    rights=("edit",),
    params=(
        Param("cosmetic_flags", FLAGS, "param_cosmetic_flags", options=(
            (FLAG_LABELS, "flag_fix_labels"),
            (FLAG_SKIP_REFS, "flag_skip_refs"),
        )),
    ),
)
