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

The pages are the account's own contributions (`pages`): every page where its
edit is still the latest, in every namespace. The dialog asks no page source,
and no "once or regularly" either — undoing one person's work is not a thing
to repeat on a schedule.
"""
import sys

from tasks import mechanic as mech
from utils import Explained, localized
from tasks.params import FLAGS, TEXT, Param

FLAG_ROLLBACK = "rollback"

HISTORY_DEPTH = 50


def prepare(ctx):
    """Check the account, and whether rollback can be used when it is asked.

    Rollback is a way of undoing, not a condition for it: when the session
    cannot roll back, the run goes on by ordinary edits and says why
    (`wiki/rights.py: explain_missing` — the group, or the BotPassword grant,
    that would have allowed it). It used to refuse the whole task, naming the
    rollbacker group, on a wiki where the bot was a content moderator — a
    group that holds rollback already; what the session lacked was the grant.
    """
    user = (ctx.params.get("revert_user") or "").strip().lstrip("@")
    if not user:
        raise Explained("error_revert_no_user")
    rollback = FLAG_ROLLBACK in set(ctx.params.get("revert_flags") or [])
    if rollback:
        from wiki import rights

        if not rights.has_right(ctx.site, "rollback"):
            rollback = False
            reason = rights.explain_missing(ctx.site, ["rollback"])
            ctx.note("note_revert_no_rollback",
                     reason=reason.text(ctx.reader) if reason else "")
    return {"user": user, "rollback": rollback}


def pages(ctx):
    """Every page where the account's edit is still the latest one.

    That is the account's whole contribution that can be undone: a page
    somebody else has edited since is left to a person, because reverting it
    would throw their work away with the account's — which is also what
    Pywikibot's revertbot does. Every namespace, newest first. The keyword is
    `top` from Pywikibot 11.6 on and `top_only` before it; both are tried,
    since requirements.txt allows either.
    """
    user = (ctx.params.get("revert_user") or "").strip().lstrip("@")
    try:
        contributions = ctx.site.usercontribs(user=user, top=True)
    except TypeError:
        contributions = ctx.site.usercontribs(user=user, top_only=True)
    titles = []
    for contribution in contributions:
        title = contribution.get("title")
        if title and title not in titles:
            titles.append(title)
    return titles


def act(ctx, page):
    """Undo the named account's run of edits at the top of one page."""
    state = ctx.state.get(SPEC.code) or {}
    user = state.get("user")

    try:
        revisions = list(page.revisions(total=HISTORY_DEPTH, content=True))
    except Exception as e:
        return "fail", "{}: {}".format(type(e).__name__, e)
    if not revisions:
        return "skip", localized("page_revert_no_history", ctx.reader)
    if revisions[0].user != user:
        return "skip", localized("page_revert_not_last", ctx.reader, user=user)

    keep = None
    reverted = 0
    for revision in revisions:
        if revision.user == user:
            reverted += 1
            continue
        keep = revision
        break

    if keep is None:
        return "skip", localized("page_revert_all_theirs", ctx.reader)

    if revisions[0].text == keep.text:
        """The bot's own restoration remains authored by the same bot.

        A repeat therefore still finds its edits at the top, but saving the
        same earlier text again would be a no-op counted as another revert.
        """
        return "skip", None

    if ctx.dry_run:
        return "skip", localized("page_revert_will", ctx.reader, count=reverted)

    if state.get("rollback"):
        try:
            ctx.site.rollbackpage(page, user=user, summary=ctx.summary or "")
        except Exception as e:
            return "fail", "{}: {}".format(type(e).__name__, e)
        return "done", localized("page_revert_rolled_back", ctx.reader,
                                 count=reverted)

    try:
        page.text = keep.text
        page.save(summary=ctx.summary or "отмена правок",
                  bot=True, minor=False, apply_cosmetic_changes=False)
    except Exception as e:
        return "fail", "{}: {}".format(type(e).__name__, e)
    return "done", localized("page_revert_done", ctx.reader, count=reverted)


SPEC = mech.Mechanic(
    code="revertbot",
    kind=mech.ACTION,
    module=sys.modules[__name__],
    rights=("edit",),
    destructive=True,
    own_pages=True,
    schedulable=False,
    params=(
        Param("revert_user", TEXT, "param_revert_user"),
        Param("revert_flags", FLAGS, "param_revert_flags", options=(
            (FLAG_ROLLBACK, "flag_rollback"),
        )),
    ),
)
