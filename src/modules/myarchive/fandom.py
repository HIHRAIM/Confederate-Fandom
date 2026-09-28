"""Reading pages for the archive: anonymously, through a wiki's api.php.

Three questions, and each is one or a few requests per wiki, however many
pages are archived there: what the wiki calls its main page and its
namespaces (`info`), what the pages say now (`pages`, fifty titles a request),
and who edited one page since a moment (`editors_since`) — asked only of the
pages that changed.
"""
import logging
import re
import urllib.parse

import requests

logger = logging.getLogger("fd.modules.myarchive.fandom")

USER_AGENT = "Confederate Fandom archive (fd_bot)"

TIMEOUT = 30

BATCH = 50

MODULE_NS = 828

_URL_RE = re.compile(
    r"^https?://(?P<host>[^/\s]+)/(?:(?P<lang>[a-z][a-z0-9-]*)/)?wiki/(?P<title>[^?#]+)",
    re.I)


def parse_url(url):
    """A page address -> (host, language path or None, title). Raises
    ValueError for anything that is not ``https://host[/lang]/wiki/Title``."""
    match = _URL_RE.match(str(url or "").strip())
    if not match:
        raise ValueError("not a wiki page address: {}".format(url))
    title = urllib.parse.unquote(match.group("title")).replace("_", " ").strip()
    return (match.group("host").lower(),
            (match.group("lang") or "").lower() or None, title)


class Wiki:
    """One wiki of the farm, read without logging in."""

    def __init__(self, host, lang_path):
        """Remember where its api.php is; nothing is asked yet."""
        self.host = host
        self.lang_path = lang_path
        self.api = "https://{}{}/api.php".format(
            host, "/" + lang_path if lang_path else "")
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self._info = None

    @property
    def subdomain(self):
        """The wiki's own part of the host: ``pokemon`` of pokemon.fandom.com."""
        return self.host.split(".")[0]

    def _query(self, **params):
        """One action=query request. -> the decoded answer. Raises on an error."""
        params.update(action="query", format="json", formatversion="2")
        response = self.session.get(self.api, params=params, timeout=TIMEOUT)
        response.raise_for_status()
        data = response.json()
        if "error" in data:
            raise RuntimeError("{}: {}".format(
                data["error"].get("code"), data["error"].get("info")))
        return data

    def info(self):
        """The content language, the main page and the namespace names."""
        if self._info is None:
            data = self._query(meta="siteinfo", siprop="general|namespaces")
            general = data["query"]["general"]
            self._info = {
                "lang": general.get("lang") or self.lang_path or "en",
                "mainpage": general.get("mainpage"),
                "namespaces": {int(key): value.get("name", "")
                               for key, value in data["query"]["namespaces"].items()},
            }
        return self._info

    def pages(self, titles):
        """The current text of pages. -> {asked title: page} where a page is
        {'title', 'ns', 'missing', 'content', 'model', 'timestamp', 'revid'}."""
        out = {}
        titles = list(dict.fromkeys(titles))
        for start in range(0, len(titles), BATCH):
            batch = titles[start:start + BATCH]
            data = self._query(prop="revisions", titles="|".join(batch),
                               rvprop="ids|timestamp|user|content|contentmodel",
                               rvslots="main")
            query = data.get("query", {})
            aliases = {item["from"]: item["to"]
                       for item in query.get("normalized", [])}
            found = {page["title"]: page for page in query.get("pages", [])}
            for asked in batch:
                page = found.get(aliases.get(asked, asked))
                if page is None or page.get("missing") or page.get("invalid"):
                    out[asked] = {"title": asked, "missing": True}
                    continue
                revision = (page.get("revisions") or [{}])[0]
                slot = (revision.get("slots") or {}).get("main", {})
                out[asked] = {
                    "title": page["title"], "ns": page.get("ns", 0),
                    "missing": False, "content": slot.get("content", ""),
                    "model": slot.get("contentmodel", ""),
                    "timestamp": revision.get("timestamp"),
                    "revid": revision.get("revid"),
                }
        return out

    def editors_since(self, title, since=None, limit_requests=10):
        """Who edited one page after `since` (ISO time), oldest first, each
        once. Every editor of the page when `since` is None — asked page by
        page, and cut after `limit_requests` requests of five hundred
        revisions, which is a history no archive needs to name in full."""
        names = []
        params = {"prop": "revisions", "titles": title, "rvprop": "user",
                  "rvlimit": "max"}
        if since:
            params["rvend"] = since
        for _request in range(limit_requests):
            data = self._query(**params)
            for page in data.get("query", {}).get("pages", []):
                for revision in page.get("revisions", []):
                    user = revision.get("user")
                    if user and not revision.get("userhidden"):
                        names.append(user)
            more = data.get("continue")
            if not more:
                break
            params.update(more)
        return list(dict.fromkeys(reversed(names)))
