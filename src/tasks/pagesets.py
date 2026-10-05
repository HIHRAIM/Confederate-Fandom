"""Where the pages of a task come from.

Every mechanic works over a list of pages, and the list is settled before the
first edit — see db/tasks.py for why that one decision is what makes a long
run interruptible, resumable and reportable. This module is the half that
produces it: one question to the person ("откуда брать страницы?"), one
argument, and a list of titles.

The sources are the ones the Pywikibot scripts offered between them, minus the
ones that only make sense at a command line. Each is a thin call to the
library; nothing here parses wikitext or decides anything about a page.

Two rules the whole module keeps:

* **it never edits and never logs in** — it is given a Site that is already
  signed in, and it only reads;
* **it returns titles, not Page objects** — the titles are what goes into
  task_pages, and a run that resumes after a restart has no Page objects left
  to inherit.

Blocking, like everything that touches Pywikibot: called from the worker
thread (tasks/runner.py), never from the loop.
"""
import logging
from datetime import timedelta

logger = logging.getLogger("fd.tasks.pagesets")

ALL = "all"
CATEGORY = "category"
TEMPLATE = "template"
SEARCH = "search"
LINKS = "links"
BACKLINKS = "backlinks"
FILEUSE = "fileuse"
PREFIX = "prefix"
TITLES = "titles"
NEWPAGES = "new"
RECENT = "recent"
PAIRS = "pairs"

SOURCES = (
    (ALL, "pageset_all", False),
    (CATEGORY, "pageset_category", True),
    (TEMPLATE, "pageset_template", True),
    (SEARCH, "pageset_search", True),
    (BACKLINKS, "pageset_backlinks", True),
    (LINKS, "pageset_links", True),
    (FILEUSE, "pageset_fileuse", True),
    (PREFIX, "pageset_prefix", True),
    (TITLES, "pageset_titles", True),
    (NEWPAGES, "pageset_new", False),
    (RECENT, "pageset_recent", False),
    (PAIRS, "pageset_pairs", True),
)
"""(code, the i18n key of its line, whether it needs an argument). The order
is the order the numbered list is printed in, so it may not be shuffled
without changing what «3» means to somebody halfway through a dialog."""

SOURCE_CODES = tuple(code for code, _key, _arg in SOURCES)

NEEDS_ARGUMENT = {code for code, _key, needs in SOURCES if needs}

NAMED = {TITLES, PAIRS}
"""The sources that name their pages outright. The namespace question is not
asked for them, because the answer would change nothing: `collect` takes the
titles as they were sent. Asking it anyway was one more question that made a
person wonder what they had got wrong."""

DEFAULT_NAMESPACE = 0

EVERY_NAMESPACE = {"*", "all", "все", "усі", "всі", "wszystkie", "todos", "todas"}
"""The answers that mean every namespace of the wiki, in each of the six
languages; the question names the one for the reader's language."""

RECENT_DAYS = 7

def needs_argument(source):
    """Whether this source has to be told what to look at."""
    return source in NEEDS_ARGUMENT

def takes_namespaces(source):
    """Whether the namespaces a person names narrow this source at all."""
    return source not in NAMED

def _namespaces(params, site=None):
    """The namespaces a task is confined to, as a list of numbers.

    A task that names none works in the main namespace: every mechanic here
    was written for articles, and a bot let loose over Template: and
    MediaWiki: by accident is a bad afternoon. Every namespace is a choice of
    its own (EVERY_NAMESPACE): all the wiki has, the virtual ones — Special:
    and Media:, which hold no pages — left out.
    """
    raw = params.get("namespaces")
    if raw in (None, "", []):
        return [DEFAULT_NAMESPACE]
    if isinstance(raw, str) and raw.strip().lower() in EVERY_NAMESPACE:
        if site is None:
            return [DEFAULT_NAMESPACE]
        return sorted(int(ns) for ns in site.namespaces if int(ns) >= 0)
    if isinstance(raw, (list, tuple)):
        values = raw
    else:
        values = str(raw).replace(",", " ").split()
    out = []
    for value in values:
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if number not in out:
            out.append(number)
    return out or [DEFAULT_NAMESPACE]

def _titles(pages, limit):
    """Page objects -> their titles, deduplicated, capped by `limit`.

    The cap is the person's own (`limit` in the task parameters) and is 0 by
    default: the operator asked for no ceiling of the bot's invention, since
    an account with the bot flag has no reason to be throttled. It exists so
    that a run can be tried on twenty pages before it is let loose on nine
    thousand.
    """
    seen = set()
    out = []
    for page in pages:
        try:
            title = page if isinstance(page, str) else page.title()
        except Exception as e:
            logger.warning("skipping a page whose title could not be read: %s", e)
            continue
        if title in seen:
            continue
        seen.add(title)
        out.append(title)
        if limit and len(out) >= limit:
            break
    return out

def collect(site, params, redirects=False):
    """The page list of one task. -> a list of titles, in the order to walk.

    `params` carries `source`, `argument`, `namespaces`, `limit` and, for the
    category source, `recurse`.

    `redirects` is what the task's mechanics can work on
    (tasks/registry.py: redirects_wanted): False for ordinary pages, True for
    redirects, None for both. Pywikibot spells the same three values the same
    way, so it is handed on as it is — but only to the sources that enumerate
    the wiki. Those used to be called with ``filterredir=False`` whatever the
    task, which in Pywikibot means *no redirects*, not *no filter*; that is
    how a run of the redirect mechanic over all pages was given 212 articles
    and none of the wiki's 320 redirects. The sources that name their pages —
    a category, a template, a list — are left alone.
    """
    import pywikibot

    from utils import Explained

    source = params.get("source") or ALL
    argument = (params.get("argument") or "").strip()
    limit = int(params.get("limit") or 0)
    namespaces = _namespaces(params, site)

    if source in NEEDS_ARGUMENT and not argument and source != TITLES:
        raise Explained("error_source_needs_argument")

    if source == ALL:
        pages = []
        for namespace in namespaces:
            pages = _chain(pages, site.allpages(namespace=namespace,
                                                filterredir=redirects))
        return _titles(pages, limit)

    if source == PREFIX:
        pages = []
        for namespace in namespaces:
            pages = _chain(pages, site.allpages(prefix=argument,
                                                namespace=namespace,
                                                filterredir=redirects))
        return _titles(pages, limit)

    if source == CATEGORY:
        recurse = int(params.get("recurse") or 0)
        category = pywikibot.Category(site, argument)
        return _titles(category.articles(recurse=recurse,
                                         namespaces=namespaces), limit)

    if source == TEMPLATE:
        page = pywikibot.Page(site, argument)
        if page.namespace() == 0 and not argument.lower().startswith(("шаблон:", "template:")):
            page = pywikibot.Page(site, "Template:" + argument)
        return _titles(page.getReferences(only_template_inclusion=True,
                                          namespaces=namespaces), limit)

    if source == BACKLINKS:
        page = pywikibot.Page(site, argument)
        return _titles(page.backlinks(namespaces=namespaces,
                                      follow_redirects=False), limit)

    if source == LINKS:
        page = pywikibot.Page(site, argument)
        return _titles(page.linkedPages(namespaces=namespaces), limit)

    if source == FILEUSE:
        name = argument
        if ":" not in name:
            name = "File:" + name
        return _titles(pywikibot.FilePage(site, name).using_pages(
            namespaces=namespaces), limit)

    if source == SEARCH:
        return _titles(site.search(argument, namespaces=namespaces), limit)

    if source == TITLES:
        wanted = [line.strip() for line in
                  str(argument).replace("|", "\n").split("\n")]
        return _titles((title for title in wanted if title), limit)

    if source == PAIRS:
        from tasks.params import parse_pairs

        return _titles((old for old, _new in parse_pairs(argument)), limit)

    if source == NEWPAGES:
        total = limit or 200
        pages = (entry[0] if isinstance(entry, tuple) else entry
                 for entry in site.newpages(total=total, namespaces=namespaces,
                                            redirect=redirects))
        return _titles(pages, limit)

    if source == RECENT:
        total = limit or 500
        days = int(params.get("days") or RECENT_DAYS)
        seen = []
        for change in site.recentchanges(total=total, namespaces=namespaces,
                                         changetype="edit|new",
                                         redirect=redirects,
                                         end=_days_ago(days)):
            title = change.get("title")
            if title and title not in seen:
                seen.append(title)
                if limit and len(seen) >= limit:
                    break
        return seen

    raise Explained("error_unknown_source", source=source)

def _chain(first, second):
    """Two generators, one after the other, without loading either."""
    def _walk():
        """Yield everything of the first, then everything of the second."""
        for item in first:
            yield item
        for item in second:
            yield item
    return _walk()

def _days_ago(days):
    """A Pywikibot timestamp `days` days back, for recentchanges' `end`."""
    import pywikibot

    return pywikibot.Timestamp.nowutc() - timedelta(days=days)
