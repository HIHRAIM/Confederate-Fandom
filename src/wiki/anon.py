"""Reading a Fandom wiki without logging in: plain HTTP to its api.php.

Pywikibot is the way the bot works on a wiki, and it stays the way for
everything that edits. This module is for two kinds of reading where it is
the wrong tool:

* **reading beside the worker.** The interwiki table is checked when a person
  sends /go, in the command's own moment, while the worker may be in the
  middle of somebody else's walk. Pywikibot keeps its cookie jar in a
  process-global, and two threads on two wikis unseat each other's sessions
  (wiki/site.py) — so nothing outside the worker may touch it. A request
  without a session has nothing to unseat.
* **a wiki the bot has no session on** — a language version on another host,
  which needs no family file and no login to be read.

Anonymous reading is not better in general, and that is why the rest of the
bot does not use it: a logged-in bot account may ask for ten times as much
in one request (5 000 list entries, 500 titles), a wiki can hide pages from
readers, and an address that asks too often is throttled by its IP. Every
answer that asks to slow down is obeyed here (`Retry-After`), a few times,
before it is reported.

Blocking; called from a worker thread, never from the loop.
"""
import logging
import re
import time

import requests

logger = logging.getLogger("fd.wiki.anon")

USER_AGENT = "Confederate Fandom (fd_bot)"

TIMEOUT = 30

BATCH = 50
"""Titles in one request: the limit for a reader without the bot right."""

RETRIES = 3

MAX_WAIT = 30

class AnonWiki:
    """One wiki, read through its api.php without a session."""

    def __init__(self, base):
        """`base` is the wiki's address without /wiki/: https://host[/lang]."""
        self.base = str(base).rstrip("/")
        self.api = self.base + "/api.php"
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT

    @classmethod
    def from_article_url(cls, url):
        """From an interwiki-map address, ``https://host/ja/wiki/$1``."""
        base = re.sub(r"/wiki/.*$", "", str(url or "").strip())
        return cls(base.replace("http://", "https://"))

    def request(self, **params):
        """One GET to api.php. -> the decoded answer. Raises on an API error.

        A 429 or a 5xx is retried after the wait the server names (at most
        MAX_WAIT seconds), RETRIES times, and then raised: the caller decides
        what a wiki that will not answer costs."""
        params.setdefault("format", "json")
        params.setdefault("formatversion", "2")
        for attempt in range(RETRIES + 1):
            response = self.session.get(self.api, params=params, timeout=TIMEOUT)
            if response.status_code in (429, 500, 502, 503, 504) and attempt < RETRIES:
                try:
                    wait = int(response.headers.get("Retry-After") or 0)
                except ValueError:
                    wait = 0
                time.sleep(min(MAX_WAIT, max(wait, 2 ** attempt)))
                continue
            response.raise_for_status()
            data = response.json()
            if "error" in data:
                raise RuntimeError("{}: {}".format(data["error"].get("code"),
                                                   data["error"].get("info")))
            return data
        raise RuntimeError("{} did not answer".format(self.api))

    def query(self, **params):
        """Every answer of one action=query, following `continue`. -> yields the
        `query` part of each answer."""
        params["action"] = "query"
        params.setdefault("continue", "")
        while True:
            data = self.request(**params)
            yield data.get("query") or {}
            more = data.get("continue")
            if not more:
                return
            params.update(more)

    def siteinfo(self):
        """The general part, the namespaces and the interwiki map."""
        data = self.request(action="query", meta="siteinfo",
                            siprop="general|namespaces|interwikimap")
        return data.get("query") or {}

    def pages(self, titles, **props):
        """Pages by title, BATCH at a time, redirects followed. -> yields
        (asked title, page mapping or None, the redirect target or None).

        `props` are the query parameters for what to read about each page
        (prop=..., lllimit=...). A page split across continuations is merged:
        a long list of language links comes back over several answers."""
        titles = list(dict.fromkeys(str(t) for t in titles if str(t).strip()))
        for start in range(0, len(titles), BATCH):
            batch = titles[start:start + BATCH]
            merged = {}
            aliases = {}
            redirects = {}
            for query in self.query(titles="|".join(batch), redirects=1, **props):
                for item in query.get("normalized", []):
                    aliases[item["from"]] = item["to"]
                for item in query.get("redirects", []):
                    redirects[item["from"]] = item["to"]
                for page in query.get("pages", []):
                    known = merged.setdefault(page["title"], dict(page))
                    for key, value in page.items():
                        if isinstance(value, list) and key in known and known[key] is not value:
                            known[key] = known[key] + [v for v in value if v not in known[key]]
                        else:
                            known.setdefault(key, value)
            for asked in batch:
                name = aliases.get(asked, asked)
                target = redirects.get(name)
                page = merged.get(target or name)
                if page is not None and (page.get("missing") or page.get("invalid")):
                    page = None
                yield asked, page, target

    def redirects(self, namespace=0):
        """Every redirect of a namespace and where it points. -> {from: to}.

        Two lists rather than one generator: allpages as a generator cannot
        resolve redirects, so the redirect pages are listed by id and
        `allredirects` gives each id's target."""
        ids = {}
        for query in self.query(list="allpages", apnamespace=namespace,
                                apfilterredir="redirects", aplimit="max"):
            for page in query.get("allpages", []):
                ids[page["pageid"]] = page["title"]
        out = {}
        for query in self.query(list="allredirects", arnamespace=namespace,
                                arprop="ids|title", arlimit="max"):
            for item in query.get("allredirects", []):
                source = ids.get(item.get("fromid"))
                if source:
                    out[source] = item["title"]
        return out

    def all_pages(self, namespace=0, **props):
        """Every article (no redirects) of a namespace with the properties
        asked for. -> yields page mappings, merged across continuations."""
        params = dict(generator="allpages", gapnamespace=namespace,
                      gaplimit="max", gapfilterredir="nonredirects", **props)
        seen = {}
        for query in self.query(**params):
            for page in query.get("pages", []):
                known = seen.get(page["title"])
                if known is None:
                    seen[page["title"]] = dict(page)
                    continue
                for key, value in page.items():
                    if isinstance(value, list):
                        known[key] = known.get(key, []) + [v for v in value
                                                           if v not in known.get(key, [])]
                    else:
                        known.setdefault(key, value)
        for page in seen.values():
            yield page

    def text(self, title):
        """The current wikitext of one page and its recent editors. -> (text or
        None when there is no such page, [(user, timestamp), …] newest first)."""
        data = self.request(action="query", prop="revisions", titles=title,
                            rvprop="content|user|timestamp", rvslots="main",
                            rvlimit=1)
        pages = (data.get("query") or {}).get("pages") or [{}]
        page = pages[0]
        if page.get("missing") or page.get("invalid"):
            return None, []
        revision = (page.get("revisions") or [{}])[0]
        content = ((revision.get("slots") or {}).get("main") or {}).get("content")
        return content, [(revision.get("user"), revision.get("timestamp"))]

    def editors_since(self, title, since):
        """Who edited one page after `since` (ISO time), newest first."""
        data = self.request(action="query", prop="revisions", titles=title,
                            rvprop="user|timestamp", rvlimit=50, rvend=since)
        pages = (data.get("query") or {}).get("pages") or [{}]
        return [(rev.get("user"), rev.get("timestamp"))
                for rev in pages[0].get("revisions") or []]
