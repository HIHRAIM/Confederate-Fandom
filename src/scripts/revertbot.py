"""Undo one account's edits — the bot's shape of Pywikibot's revertbot.py.

    Pywikibot's revertbot.py is (C) Bryan Tong Minh, 2008, xqt, 2018-2025 and
    the Pywikibot team, 2008-2025, MIT licence. Its job is kept: take back the
    consecutive edits one account made at the top of a page's history.

Only the *top* of the history, and only *consecutive* edits by that account.
That is not a simplification, it is the safe half of the job: an edit that
somebody has since built on cannot be undone without deciding what to keep of
their work, and a bot has no way to make that decision. A page where the last
edit is not the named account's is reported as a skip, so a person sees which
pages need looking at by hand.

Rollback is offered as a flag because it is the right tool where the account
has it: one request, one log entry, no diff to compute — but it takes the
whole top run of edits by the last editor and nothing else, so it is a
different operation and not an optimisation of the same one.

The page list normally comes from that account's contributions; the dialog's
`titles` source takes a list pasted from Special:Contributions.
"""
import sys

from tasks import mechanic as mech
from tasks.params import FLAGS, TEXT, Param

FLAG_ROLLBACK = "rollback"

HISTORY_DEPTH = 50


def prepare(ctx):
    """Check the account and, for rollback, the right to use it."""
    user = (ctx.params.get("revert_user") or "").strip()
    if not user:
        raise ValueError("не указано, чьи правки отменять")
    if FLAG_ROLLBACK in set(ctx.params.get("revert_flags") or []):
        from wiki import rights

        if not rights.has_right(ctx.site, "rollback"):
            from utils import localized, service_lang
            raise ValueError(localized("mechanic_need_rollback_group",
                                       service_lang()))
    return user.lstrip("@")


def act(ctx, page):
    """Undo the named account's run of edits at the top of one page."""
    user = ctx.state.get(SPEC.code)
    flags = set(ctx.params.get("revert_flags") or [])

    try:
        revisions = list(page.revisions(total=HISTORY_DEPTH, content=True))
    except Exception as e:
        return "fail", "{}: {}".format(type(e).__name__, e)
    if not revisions:
        return "skip", "истории нет"
    if revisions[0].user != user:
        return "skip", "последняя правка не от «{}»".format(user)

    keep = None
    reverted = 0
    for revision in revisions:
        if revision.user == user:
            reverted += 1
            continue
        keep = revision
        break

    if keep is None:
        return "skip", "все правки в истории от этого участника"

    if revisions[0].text == keep.text:
        """The bot's own restoration remains authored by the same bot.

        A repeat therefore still finds its edits at the top, but saving the
        same earlier text again would be a no-op counted as another revert.
        """
        return "skip", None

    if ctx.dry_run:
        return "skip", "будет откачено правок: {}".format(reverted)

    if FLAG_ROLLBACK in flags:
        try:
            ctx.site.rollbackpage(page, user=user, summary=ctx.summary or "")
        except Exception as e:
            return "fail", "{}: {}".format(type(e).__name__, e)
        return "done", "откат ({} правок)".format(reverted)

    try:
        page.text = keep.text
        page.save(summary=ctx.summary or "отмена правок",
                  bot=True, minor=False, apply_cosmetic_changes=False)
    except Exception as e:
        return "fail", "{}: {}".format(type(e).__name__, e)
    return "done", "отменено правок: {}".format(reverted)


SPEC = mech.Mechanic(
    code="revertbot",
    kind=mech.ACTION,
    module=sys.modules[__name__],
    rights=("edit",),
    destructive=True,
    params=(
        Param("revert_user", TEXT, "param_revert_user"),
        Param("revert_flags", FLAGS, "param_revert_flags", options=(
            (FLAG_ROLLBACK, "flag_rollback"),
        )),
    ),
)
