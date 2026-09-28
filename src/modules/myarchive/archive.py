"""One archive pass: every configured page, compared, and committed if changed.

**Where a page goes**: ``Pages/<language>/<wiki>/<title>`` —
``Pages/ru/pokemon/MediaWiki:Common.css`` for pokemon.fandom.com/ru. A page of
the Module namespace is filed under its canonical name, ``Module:``, whatever
the wiki calls the namespace, and a Lua module gets ``.lua`` unless its title
already ends so — which is how the repository already names them
(``Module:PokemonData/fromNumber/pixelmon.lua``). A module's documentation is
wikitext and keeps its title as it is. A slash in a title is a directory.

**Whether it changed** is asked of the hashes, not of the files: the tree of
the branch gives each file's blob hash, the page's text is hashed here the way
git does, and a page equal to its file — or to its file with a final newline,
which a file committed by hand usually has — costs nothing more. Only a page
that differs is read back and committed.

**What the commit says** (config.MYARCHIVE["messages"]): a new file, an update
made by the owner alone, or an update after other people's edits, naming them.
Who edited is asked of the wiki: every revision since the file's last commit.
The editors config.MYARCHIVE["coauthors"] knows are added as co-authors, so
the commit shows on their GitHub profile too.

Blocking; called from a worker thread by the module's job.
"""
import hashlib
import logging

from modules.myarchive import fandom
from modules.myarchive.github import GitHub

logger = logging.getLogger("fd.modules.myarchive.archive")

ROOT = "Pages"

MESSAGES = {
    "created": "save file",
    "updated": "update",
    "updated_by": "update after edits by {editors}",
}
"""The commit messages when config.MYARCHIVE names none. The repository is
the operator's, so its language is theirs to choose there."""


def repo_path(lang, subdomain, page, namespaces):
    """Where one page lives in the repository."""
    title = page["title"]
    if page.get("ns") == fandom.MODULE_NS:
        local = namespaces.get(fandom.MODULE_NS) or "Module"
        if title.startswith(local + ":"):
            title = "Module:" + title[len(local) + 1:]
        if page.get("model") == "Scribunto" and not title.lower().endswith(".lua"):
            title += ".lua"
    return "/".join((ROOT, lang, subdomain, title))


def blob_sha(data):
    """The hash git gives a file with these bytes."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def _same(stored, data):
    """Equal but for line endings and trailing blank lines."""
    def norm(raw):
        return raw.replace(b"\r\n", b"\n").rstrip()
    return stored is not None and norm(stored) == norm(data)


def _message(editors, owner, messages):
    """The first line of an update's commit message."""
    others = [name for name in editors if name != owner]
    if not others:
        return messages["updated"]
    return messages["updated_by"].format(editors=", ".join(editors))


def _trailers(github, editors, coauthors, me):
    """The Co-authored-by lines for the editors config links to GitHub."""
    lines = []
    for name in editors:
        login = coauthors.get(name)
        if not login or login == me:
            continue
        address = github.noreply(login)
        line = "Co-authored-by: {} <{}>".format(login, address)
        if address and line not in lines:
            lines.append(line)
    return lines


def _group(urls):
    """The configured addresses by wiki, in the order given. -> ({(host,
    lang): [titles]}, [addresses that are not page addresses])."""
    wikis, bad = {}, []
    for url in urls:
        try:
            host, lang, title = fandom.parse_url(url)
        except ValueError:
            bad.append(str(url))
            continue
        titles = wikis.setdefault((host, lang), [])
        if title not in titles:
            titles.append(title)
    return wikis, bad


def run_pass(cfg, token):
    """Archive every configured page once. -> a mapping of counters and lists."""
    messages = dict(MESSAGES)
    messages.update(cfg.get("messages") or {})
    owner = cfg.get("owner")
    coauthors = dict(cfg.get("coauthors") or {})
    github = GitHub(token, cfg["repo"], cfg.get("branch"))
    me = github.login()
    tree = github.tree()

    result = {"created": 0, "updated": 0, "unchanged": 0, "missing": [],
              "errors": []}
    wikis, bad = _group(cfg.get("pages") or [])
    result["errors"] += ["not a page address: {}".format(url) for url in bad]

    for (host, lang_path), titles in wikis.items():
        wiki = fandom.Wiki(host, lang_path)
        try:
            info = wiki.info()
            if cfg.get("main_pages", True) and info["mainpage"] \
                    and info["mainpage"] not in titles:
                titles = titles + [info["mainpage"]]
            pages = wiki.pages(titles)
        except Exception as e:
            logger.warning("could not read %s: %s", wiki.api, e)
            result["errors"].append("{}: {}".format(host, e))
            continue

        for asked in titles:
            page = pages.get(asked) or {"missing": True}
            label = "{}/{}: {}".format(host, lang_path or "", asked)
            if page.get("missing"):
                result["missing"].append(label)
                continue
            path = repo_path(info["lang"], wiki.subdomain, page,
                             info["namespaces"])
            data = page["content"].encode("utf-8")
            stored_sha = tree.get(path)
            try:
                if stored_sha in (blob_sha(data), blob_sha(data + b"\n")):
                    result["unchanged"] += 1
                    continue
                if stored_sha and _same(github.read(path), data):
                    result["unchanged"] += 1
                    continue
                if stored_sha:
                    since = github.last_commit_date(path)
                    editors = wiki.editors_since(page["title"], since)
                    first = _message(editors, owner, messages)
                else:
                    editors = wiki.editors_since(page["title"])
                    first = messages["created"]
                trailers = _trailers(github, editors, coauthors, me)
                message = first + ("\n\n" + "\n".join(trailers) if trailers else "")
                github.put(path, data, message, sha=stored_sha)
            except Exception as e:
                logger.warning("could not archive %s: %s", label, e)
                result["errors"].append("{}: {}".format(label, e))
                continue
            result["updated" if stored_sha else "created"] += 1
            logger.info("archived %s -> %s (%s)", label, path, first)
    return result
