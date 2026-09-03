"""Protect and unprotect pages — the bot's shape of Pywikibot's protect.py.

    Pywikibot's protect.py is (C) Pywikibot team, 2008-2025, MIT licence. Its
    model is kept whole: a set of actions (edit, move, upload), a level for
    them, and an expiry.

The levels are the three a Fandom wiki actually has: everybody, autoconfirmed
accounts, administrators. «Everybody» is how a page is *un*protected — that is
MediaWiki's own model, not a shortcut, and it is why there is no separate
unprotect mechanic.

`upload` is offered because on a file page "editing" it and "replacing" it are
different rights, and protecting only the description page while leaving the
file replaceable is the mistake that protection is usually meant to prevent.

The reason written into the protection log is the task's summary; a task with
no summary protects with none, which is what the operator asked for when the
bot's own pages were protected.
"""
import sys

from tasks import mechanic as mech
from tasks.params import CHOICE, FLAGS, TEXT, Param

ALL = "all"
AUTOCONFIRMED = "autoconfirmed"
SYSOP = "sysop"

WHAT_EDIT = "edit"
WHAT_MOVE = "move"
WHAT_UPLOAD = "upload"

DEFAULT_EXPIRY = "infinite"


def prepare(ctx):
    """Build the protection mapping once. -> {action: level}."""
    level = ctx.params.get("protect_level") or SYSOP
    what = list(ctx.params.get("protect_what") or [])
    if not what:
        what = [WHAT_EDIT, WHAT_MOVE]
    return {action: level for action in what}


def act(ctx, page):
    """Protect (or unprotect) one page. -> (state, note)."""
    protections = ctx.state.get(SPEC.code) or {}
    expiry = (ctx.params.get("protect_expiry") or DEFAULT_EXPIRY).strip()

    if ctx.dry_run:
        return "skip", "будет: " + ", ".join(
            "{}={}".format(action, level)
            for action, level in sorted(protections.items()))

    try:
        page.protect(protections=protections, reason=ctx.summary or "",
                     expiry=expiry or DEFAULT_EXPIRY)
    except Exception as e:
        return "fail", "{}: {}".format(type(e).__name__, e)
    return "done", ", ".join("{}={}".format(action, level)
                             for action, level in sorted(protections.items()))


SPEC = mech.Mechanic(
    code="protect",
    kind=mech.ACTION,
    module=sys.modules[__name__],
    rights=("protect",),
    destructive=True,
    params=(
        Param("protect_level", CHOICE, "param_protect_level", options=(
            (SYSOP, "protect_level_sysop"),
            (AUTOCONFIRMED, "protect_level_autoconfirmed"),
            (ALL, "protect_level_all"),
        )),
        Param("protect_what", FLAGS, "param_protect_what", options=(
            (WHAT_EDIT, "protect_what_edit"),
            (WHAT_MOVE, "protect_what_move"),
            (WHAT_UPLOAD, "protect_what_upload"),
        )),
        Param("protect_expiry", TEXT, "param_protect_expiry",
              default=DEFAULT_EXPIRY),
    ),
)
