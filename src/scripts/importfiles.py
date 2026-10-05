"""Import current file binaries from a public MediaWiki wiki into a Fandom wiki.

The source can be a wiki page URL or its api.php URL. The source is read
anonymously through the standard MediaWiki API. The destination is the task's
already authenticated Fandom wiki; its normal rights and sponsor checks run
before the plan. Existing destination files are skipped unless the user chooses
the overwrite option in the dialog and confirms the task plan.

The dialog asks for file names, files used by one or more pages, one or more
source categories, or a bounded walk of allimages, and explicitly asks whether
to copy the source file-page
wikitext. Without that option, the new page records a source link. Only files
directly in the chosen categories are included; subcategories are not walked.
Only the current file and optionally the current description are moved;
revision history is not reconstructed. A plan lists titles before uploads.

Every source URL, API redirect and binary URL must use HTTPS and resolve only
to public addresses. Responses and downloads have size caps, so a malformed
wiki or a huge file cannot occupy the bot's worker without bound.
"""
import hashlib
import ipaddress
import json
import os
import re
import socket
import sys
import tempfile
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

import requests

from tasks import mechanic as mech
from tasks.params import BLANK, CHOICE, INT, LONGTEXT, TEXT, Param, strip_fences
from utils import Explained, localized

MAX_API_BYTES = 8 * 1024 * 1024
MAX_FILE_BYTES = 80 * 1024 * 1024
MAX_FILES = 500
USER_AGENT = "Confederate Fandom file import (https://github.com/HIHRAIM/Confederate-Fandom)"
FILE_PREFIX = re.compile(r"^(?:File|Image|Файл|Изображение|Зображення)\s*:\s*", re.I)
CATEGORY_PREFIX = re.compile(r"^(?:Category|Категория|Категорія|Categoría|Kategoria|Categoria)\s*:\s*", re.I)

def _public_https(url):
    """Reject local, private, credentialed and non-HTTPS source URLs."""
    parsed = urlsplit(str(url or "").strip())
    if (parsed.scheme.lower() != "https" or not parsed.hostname or
            parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise ValueError("a public HTTPS URL is required")
    host = parsed.hostname
    if "." not in host:
        raise ValueError("a public host is required")
    addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global
                            for item in addresses):
        raise ValueError("the host must resolve only to public addresses")
    return urlunsplit(("https", parsed.netloc, parsed.path or "/", parsed.query, ""))

def _candidates(wiki_url):
    """Try the common API locations, including Fandom's language prefix."""
    safe = _public_https(wiki_url)
    parsed = urlsplit(safe)
    origin = f"https://{parsed.netloc}"
    path = parsed.path.rstrip("/")
    if path.endswith("/api.php"):
        return [origin + path]
    prefix = path.split("/wiki/", 1)[0] if "/wiki/" in path else ""
    if prefix == "/wiki":
        prefix = ""
    possibilities = [origin + prefix + "/api.php", origin + prefix + "/w/api.php",
                     origin + "/w/api.php", origin + "/api.php"]
    return list(dict.fromkeys(possibilities))

def _get(session, url, params=None, *, stream=False):
    """Follow at most three validated HTTPS redirects."""
    current = _public_https(url)
    for _ in range(4):
        response = session.get(current, params=params, timeout=(10, 45),
                               stream=True, allow_redirects=False)
        if response.status_code in (301, 302, 303, 307, 308):
            location = response.headers.get("Location")
            response.close()
            if not location:
                raise ValueError("redirect without a location")
            current = _public_https(urljoin(current, location))
            continue
        response.raise_for_status()
        return response
    raise ValueError("too many redirects")

def _query(session, api, **params):
    """Read a bounded JSON result from the source MediaWiki API."""
    params.update(action="query", format="json", formatversion="2")
    response = _get(session, api, params)
    try:
        raw = bytearray()
        for part in response.iter_content(65536):
            raw.extend(part)
            if len(raw) > MAX_API_BYTES:
                raise ValueError("API response is too large")
        data = json.loads(raw)
    finally:
        response.close()
    if not isinstance(data, dict) or "error" in data or "query" not in data:
        raise ValueError("the source did not return a usable MediaWiki API response")
    result = data["query"]
    result["_continue"] = data.get("continue", {})
    return result

def _discover(session, wiki_url):
    """Find and validate the first working MediaWiki API endpoint."""
    last = None
    for api in _candidates(wiki_url):
        try:
            info = _query(session, api, meta="siteinfo", siprop="general")
            if info.get("general", {}).get("generator", "").startswith("MediaWiki"):
                return api
        except (requests.RequestException, ValueError, OSError) as error:
            last = error
    raise ValueError("no public MediaWiki API was found") from last

def _name(title):
    """A bare file name, without common file namespace aliases."""
    value = FILE_PREFIX.sub("", str(title or "").strip().replace("_", " "))
    return value.strip()

def _listed_names(raw):
    names = []
    for line in strip_fences(raw).splitlines():
        name = _name(line)
        if name and not name.startswith("#"):
            names.append(name)
    return list(dict.fromkeys(names))

def _listed_categories(raw):
    """Accept one or several bare category titles or localized prefixes."""
    names = []
    for line in strip_fences(raw).splitlines():
        name = CATEGORY_PREFIX.sub("", line.strip().replace("_", " ")).strip()
        if name and not name.startswith("#"):
            names.append(name)
    return list(dict.fromkeys(names))

def _listed_pages(raw):
    """Read page titles without stripping their namespace prefixes."""
    return list(dict.fromkeys(line.strip().replace("_", " ")
                              for line in strip_fences(raw).splitlines()
                              if line.strip() and not line.lstrip().startswith("#")))

def _catalog_names(state, params, key, wanted, already=()):
    """Walk an API listing with continuation and a strict plan-size cap."""
    names = []
    known = set(already)
    for _ in range(30):
        if len(names) >= wanted:
            break
        params["ailimit" if key == "allimages" else "cmlimit"] = wanted - len(names)
        result = _query(state["session"], state["api"], **params)
        items = result.get(key, [])
        for item in items:
            name = _name(item.get("name") or item.get("title"))
            if name and name not in known:
                names.append(name)
                known.add(name)
        continuation = result.get("_continue", {})
        if not continuation:
            break
        params.pop("aifrom", None)
        params.update(continuation)
    else:
        if len(names) < wanted:
            raise ValueError("the source listing required too many API pages")
    return names

def _used_file_names(state, title, wanted, already=()):
    """Read MediaWiki's image list for a source page, including templates."""
    params = {"prop": "images", "titles": title, "redirects": 1}
    names = []
    known = set(already)
    for _ in range(30):
        if len(names) >= wanted:
            break
        params["imlimit"] = wanted - len(names)
        result = _query(state["session"], state["api"], **params)
        for page in result.get("pages") or []:
            for image in page.get("images") or []:
                name = _name(image.get("title"))
                if name and name not in known:
                    names.append(name)
                    known.add(name)
        continuation = result.get("_continue", {})
        if not continuation:
            break
        params.update(continuation)
    else:
        if len(names) < wanted:
            raise ValueError("the page image list required too many API pages")
    return names

def prepare(ctx):
    """Validate the source and prevent combining uploads with other mechanics."""
    if len(ctx.mechanics) != 1:
        raise Explained("error_file_import_alone")
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    try:
        api = _discover(session, ctx.params.get("file_source"))
    except (ValueError, requests.RequestException, OSError) as error:
        session.close()
        raise Explained("error_file_import_source", reason=str(error)) from error
    return {"session": session, "api": api}

def pages(ctx):
    """Plan up to 500 source file titles before any upload is possible."""
    state = ctx.state[SPEC.code]
    scope = ctx.params.get("file_scope")
    if scope == "list":
        names = _listed_names(ctx.params.get("file_names"))
    else:
        wanted = int(ctx.params.get("file_limit") or 0)
        if not 1 <= wanted <= MAX_FILES:
            raise Explained("error_file_import_count", limit=MAX_FILES)
        try:
            names = []
            if scope == "all":
                params = {"list": "allimages"}
                start = (ctx.params.get("file_start") or "").strip()
                if start:
                    params["aifrom"] = _name(start)
                names = _catalog_names(state, params, "allimages", wanted)
            elif scope in ("page", "pages"):
                page_text = (ctx.params.get("file_page") if scope == "page"
                             else ctx.params.get("file_pages"))
                for title in _listed_pages(page_text):
                    if len(names) >= wanted:
                        break
                    names.extend(_used_file_names(state, title, wanted - len(names), names))
            else:
                category_text = (ctx.params.get("file_category") if scope == "category"
                                 else ctx.params.get("file_categories"))
                for category in _listed_categories(category_text):
                    if len(names) >= wanted:
                        break
                    names.extend(_catalog_names(state, {
                        "list": "categorymembers", "cmtitle": "Category:" + category,
                        "cmtype": "file", "cmprop": "title",
                    }, "categorymembers", wanted - len(names), names))
        except (requests.RequestException, ValueError, OSError) as error:
            raise Explained("error_file_import_source", reason=str(error)) from error
    if not names:
        return []
    if len(names) > MAX_FILES:
        raise Explained("error_file_import_count", limit=MAX_FILES)
    if ctx.params.get("file_existing") == "overwrite":
        ctx.note("note_file_import_overwrite")
    return ["File:" + name for name in dict.fromkeys(names) if name]

def _source_file(state, name):
    """Read the current binary URL and optional current description wikitext."""
    result = _query(
        state["session"], state["api"], titles="File:" + name,
        redirects="1", prop="imageinfo|revisions|info",
        iiprop="url|size|sha1|mime", rvprop="content", rvslots="main",
        inprop="url",
    )
    found = (result.get("pages") or [])
    if not found or "imageinfo" not in found[0]:
        return None
    page = found[0]
    info = page["imageinfo"][0]
    revisions = page.get("revisions") or []
    revision = revisions[0] if revisions else {}
    description = ((revision.get("slots") or {}).get("main") or {}).get(
        "content", revision.get("content", "")) or ""
    return {"url": _public_https(info["url"]), "size": int(info.get("size") or 0),
            "sha1": info.get("sha1", ""), "text": description,
            "page_url": _public_https(page.get("fullurl") or state["api"])}

def _download(session, info):
    """Stream into a temporary file, reject huge and mismatched downloads."""
    if info["size"] > MAX_FILE_BYTES:
        raise ValueError("source file is larger than 80 MiB")
    response = _get(session, info["url"], stream=True)
    temp = tempfile.NamedTemporaryFile(prefix="fd-import-", delete=False)
    digest = hashlib.sha1()
    size = 0
    try:
        for part in response.iter_content(262144):
            size += len(part)
            if size > MAX_FILE_BYTES:
                raise ValueError("source file is larger than 80 MiB")
            temp.write(part)
            digest.update(part)
        temp.close()
        expected = str(info.get("sha1") or "").lower()
        if re.fullmatch(r"[0-9a-f]{40}", expected) and digest.hexdigest() != expected:
            raise ValueError("download does not match the source SHA-1")
        if not size:
            raise ValueError("source file is empty")
        return temp.name
    except Exception:
        temp.close()
        os.unlink(temp.name)
        raise
    finally:
        response.close()

def _target_file_hash(site, title):
    """Return the current binary hash, including files without a page."""
    result = site.simple_request(action="query", titles=title, prop="imageinfo",
                                 iiprop="sha1", formatversion=2).submit()
    pages = result.get("query", {}).get("pages", [])
    info = pages[0].get("imageinfo") if pages else None
    return (info[0].get("sha1") or "") if info else None

def act(ctx, page):
    """Upload a verified binary with the chosen existing-file policy."""
    import pywikibot
    import wiki

    title = page.title()
    destination = pywikibot.FilePage(ctx.site, title)
    target_hash = _target_file_hash(ctx.site, title)
    existing = destination.exists() or target_hash is not None
    overwrite = ctx.params.get("file_existing") == "overwrite"
    if existing and not overwrite:
        return "skip", localized("file_import_existing", ctx.reader)
    state = ctx.state[SPEC.code]
    try:
        info = _source_file(state, _name(title))
        if info is None:
            return "fail", localized("file_import_missing", ctx.reader)
        description = (info["text"] if ctx.params.get("file_description") == "copy"
                       else "Source: [" + info["page_url"] + " " + info["page_url"] + "]")
        summary = ctx.summary or "Import file from " + info["page_url"]
        if target_hash and target_hash.lower() == str(info["sha1"]).lower():
            if not overwrite or destination.text == description:
                return "skip", localized("file_import_same", ctx.reader)
            if ctx.dry_run:
                return "done", localized("file_import_preview", ctx.reader)
            wiki.use_cookies(ctx.wiki)
            destination.text = description
            destination.save(summary=summary, bot=True, minor=False,
                             apply_cosmetic_changes=False)
            return "done", localized("file_import_description_done", ctx.reader)
        if ctx.dry_run:
            return "done", localized("file_import_preview", ctx.reader)
        path = _download(state["session"], info)
        try:
            wiki.use_cookies(ctx.wiki)
            uploaded = destination.upload(
                path, comment=summary, text=description,
                ignore_warnings=("exists", "page-exists") if existing else False,
                report_success=not existing, chunk_size=5 * 1024 * 1024)
        finally:
            os.unlink(path)
    except Exception as error:
        from tasks import report
        return "fail", report.safe_error(error, ctx.reader)
    return ("done", localized("file_import_done", ctx.reader)) if uploaded else (
        "fail", localized("file_import_failed", ctx.reader))

def finish(ctx):
    """Release the source HTTP connection after the last planned file."""
    state = ctx.state.get(SPEC.code) or {}
    session = state.get("session")
    if session is not None:
        session.close()
    return None

SPEC = mech.Mechanic(
    code="importfiles", kind=mech.ACTION, module=sys.modules[__name__],
    rights=("upload", "edit"), destructive=True, own_pages=True, schedulable=False,
    params=(
        Param("file_source", TEXT, "param_file_source"),
        Param("file_scope", CHOICE, "param_file_scope", options=(
            ("list", "file_scope_list"), ("page", "file_scope_page"),
            ("pages", "file_scope_pages"),
            ("category", "file_scope_category"),
            ("categories", "file_scope_categories"),
            ("all", "file_scope_all"))),
        Param("file_names", LONGTEXT, "param_file_names", depends=("file_scope", "list")),
        Param("file_page", TEXT, "param_file_page", depends=("file_scope", "page")),
        Param("file_pages", LONGTEXT, "param_file_pages",
              depends=("file_scope", "pages")),
        Param("file_category", TEXT, "param_file_category",
              depends=("file_scope", "category")),
        Param("file_categories", LONGTEXT, "param_file_categories",
              depends=("file_scope", "categories")),
        Param("file_start", TEXT, "param_file_start", blank=BLANK,
              depends=("file_scope", "all")),
        Param("file_limit", INT, "param_file_limit", minimum=1, maximum=MAX_FILES,
              depends=("file_scope", ("all", "page", "pages",
                                      "category", "categories"))),
        Param("file_description", CHOICE, "param_file_description", options=(
            ("copy", "file_description_copy"),
            ("source_link", "file_description_source_link"))),
        Param("file_existing", CHOICE, "param_file_existing", options=(
            ("skip", "file_existing_skip"),
            ("overwrite", "file_existing_overwrite"))),
    ),
)
