"""Take deleted files out of the pages that still use them — Pywikibot's delinker.

    Pywikibot's delinker.py is (C) xqt, 2023-2025 and the Pywikibot team,
    MIT licence. It watches the deletion log and removes what was deleted from
    wherever it is still shown. That is exactly what is kept.

Why it exists at all: deleting a file does not touch the articles that showed
it. They keep the markup, and a reader gets a red link where a picture was.
Somebody has to go round after the deletion, and on a wiki with an active file
namespace that is a daily job — which is why this one is worth putting on a
schedule.

Two ways to say which deletions to act on:

* a **one-off** run takes the last `delinker_days` days of the log;
* a **repeating** run takes everything since it last ran, which is stored with
  the schedule. A bot that was down for a day therefore catches up rather than
  either missing the deletions or redoing a week of them.

The page list is normally `recent` or a category; the mechanic itself does not
choose which pages to look at, so a run over the whole wiki is a run over the
whole wiki and takes as long as that.

The removal is `image.remove_usages`, the same code the `image` mechanic uses:
a file taken out by one and left by the other would be the worst of both.
"""
import logging
import sys
from datetime import timedelta

from tasks import mechanic as mech
from utils import Explained
from tasks.params import INT, Param

from scripts import image

logger = logging.getLogger("fd.scripts.delinker")

DEFAULT_DAYS = 7

LOG_LIMIT = 500

def prepare(ctx):
    """Read the deletion log. -> the set of file names to take out.

    Filter the API to the file namespace before applying LOG_LIMIT, otherwise
    unrelated article deletions can consume the entire window and hide a
    file that still needs delinking. Only current file deletions count: the log also contains
    restores and revision hiding, and a filename may have been reuploaded
    since its deletion. None of those may remove a working illustration.
    A deleted article is a red link somebody may
    want to keep as a request for that article, and removing those links is
    a different decision that nobody asked this mechanic to make.
    """
    import pywikibot

    days = int(ctx.params.get("delinker_days") or DEFAULT_DAYS)
    since = ctx.params.get("delinker_since")
    if since:
        start = pywikibot.Timestamp.fromtimestamp(int(since))
    else:
        start = pywikibot.Timestamp.nowutc() - timedelta(days=days)

    names = []
    try:
        for entry in ctx.site.logevents(logtype="delete", namespace=6, end=start,
                                        total=LOG_LIMIT):
            try:
                if entry.action() != "delete":
                    continue
                page = entry.page()
                title = page.title()
            except Exception:
                continue
            if ":" not in title:
                continue
            namespace, _, rest = title.partition(":")
            if not rest:
                continue
            try:
                if page.namespace() != 6 or page.exists():
                    continue
            except Exception:
                continue
            name = image.normalise(title)
            if name and name not in names:
                names.append(name)
    except Exception as e:
        raise Explained("error_delinker_log", error=str(e))

    if not names:
        ctx.note("note_delinker_none")
    else:
        ctx.note("note_delinker_count", count=len(names))
    return names

def apply(ctx, page, text):
    """One page with every deleted file taken out. -> (text, change labels)."""
    names = ctx.state.get(SPEC.code) or []
    labels = []
    for name in names:
        text, count = image.remove_usages(text, name)
        if count:
            labels.append("убран удалённый файл «{}»".format(name))
    return text, labels

def summary_part(ctx, labels):
    """What this mechanic contributes to the edit summary."""
    if not labels:
        return None
    if len(labels) == 1:
        return labels[0]
    return "убраны удалённые файлы ({})".format(len(labels))

SPEC = mech.Mechanic(
    code="delinker",
    kind=mech.TEXT,
    module=sys.modules[__name__],
    rights=("edit",),
    params=(
        Param("delinker_days", INT, "param_delinker_days",
              default=DEFAULT_DAYS, minimum=1, maximum=365),
    ),
)
