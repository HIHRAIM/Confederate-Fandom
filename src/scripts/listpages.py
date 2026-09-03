"""List pages into a file — the bot's shape of Pywikibot's listpages.py.

    Pywikibot's listpages.py is (C) Pywikibot team, 2008-2025, MIT licence. It
    prints a page list in a chosen format; here the list goes into the file the
    task sends back, because a chat window is not where four thousand titles
    belong.

It changes nothing and needs no rights beyond reading, which makes it the
sensible first move on any wiki: run the page source you are about to act on
through this, read the list, then run the mechanic that writes.

The extra columns cost a read of each page, so they are flags rather than the
default: a bare list of titles is one request per fifty pages, and a list with
sizes and timestamps is one per page.
"""
import sys

from tasks import mechanic as mech
from tasks.params import FLAGS, Param

FLAG_SIZE = "size"
FLAG_TIMESTAMP = "timestamp"
FLAG_CATEGORIES = "categories"
FLAG_REDIRECTS = "redirects"


def prepare(ctx):
    """Nothing to build; the report is collected page by page."""
    return None


def collect(ctx, page):
    """One line of the report for one page."""
    flags = set(ctx.params.get("list_flags") or [])
    parts = [page.title()]
    if not flags:
        return parts

    try:
        if FLAG_REDIRECTS in flags and page.isRedirectPage():
            try:
                parts.append("-> " + page.getRedirectTarget().title())
            except Exception:
                parts.append("-> ?")
        if FLAG_SIZE in flags:
            parts.append("{} б".format(len(page.text)))
        if FLAG_TIMESTAMP in flags:
            parts.append(str(page.latest_revision.timestamp))
        if FLAG_CATEGORIES in flags:
            names = [category.title(with_ns=False) for category in page.categories()]
            parts.append("; ".join(names) if names else "без категорий")
    except Exception as e:
        parts.append("не удалось прочитать: {}".format(type(e).__name__))
    return ["\t".join(parts)]


SPEC = mech.Mechanic(
    code="listpages",
    kind=mech.REPORT,
    module=sys.modules[__name__],
    rights=(),
    params=(
        Param("list_flags", FLAGS, "param_list_flags", options=(
            (FLAG_SIZE, "flag_list_size"),
            (FLAG_TIMESTAMP, "flag_list_timestamp"),
            (FLAG_CATEGORIES, "flag_list_categories"),
            (FLAG_REDIRECTS, "flag_list_redirects"),
        )),
    ),
)
