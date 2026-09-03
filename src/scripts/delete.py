"""Delete pages — the bot's shape of Pywikibot's delete.py.

    Pywikibot's delete.py is (C) Andre Engels, 2006, Pywikibot team,
    2006-2025, MIT licence. What is kept is the plain job: delete every page
    of a list, with one reason.

This is the mechanic that can lose work, and it is treated accordingly:

* it is marked destructive, so the confirmation says out loud that it cannot
  be undone by editing;
* a dry run lists exactly what would go and deletes nothing, which is how a
  page list should always be read before it is acted on;
* a page that is not there is a skip and not a failure — a list that was built
  an hour ago may name something somebody has already dealt with;
* the reason is the task's summary and nothing is invented for it. A deletion
  log entry with no reason is unhelpful, so the confirmation asks for one when
  the task has none.

Restoring a deleted page needs `undelete` and is a decision about somebody's
work, so it is not offered as a mechanic. `Special:Undelete` on the wiki is
where that belongs.
"""
import sys

from tasks import mechanic as mech
from tasks.params import FLAGS, Param

FLAG_TALK = "talk"


def prepare(ctx):
    """Nothing to build; the check is that there is a reason to record."""
    if not (ctx.summary or "").strip():
        raise ValueError("для удаления нужно указать причину — она попадёт "
                         "в журнал удалений")
    return None


def act(ctx, page):
    """Delete one page. -> (state, note)."""
    try:
        if not page.exists():
            return "skip", "страницы уже нет"
    except Exception as e:
        return "fail", "{}: {}".format(type(e).__name__, e)

    if ctx.dry_run:
        return "skip", "будет удалена"

    try:
        page.delete(reason=ctx.summary, prompt=False, mark=False)
    except Exception as e:
        return "fail", "{}: {}".format(type(e).__name__, e)

    if FLAG_TALK in set(ctx.params.get("delete_flags") or []):
        try:
            talk = page.toggleTalkPage()
            if talk is not None and talk.exists():
                talk.delete(reason=ctx.summary, prompt=False, mark=False)
        except Exception as e:
            return "done", "страница удалена, обсуждение — нет: {}".format(e)
    return "done", None


SPEC = mech.Mechanic(
    code="delete",
    kind=mech.ACTION,
    module=sys.modules[__name__],
    rights=("delete",),
    destructive=True,
    params=(
        Param("delete_flags", FLAGS, "param_delete_flags", options=(
            (FLAG_TALK, "flag_delete_talk"),
        )),
    ),
)
