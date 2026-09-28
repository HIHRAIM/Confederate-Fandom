"""Reading the posts a channel published before the bot could see them.

The Bot API has no history: a bot is told about a channel post as it happens
and can never ask for an earlier one, so a bot added to a channel with a
thousand posts starts at post one thousand and one. What Telegram does hand
out is the channel's public web preview — the page `t.me/s/<name>` it serves
to a browser with no account — and that is what this module reads.

The price of the only way in is that the markup is undocumented and can change
underfoot, which is why every parse failure raises `PreviewError` and is
reported rather than passing silently, and why nothing here is on the path of
an ordinary post: this is the backfill (backfill.py), not the collector.

It only fetches and parses. The post dicts it hands back are shaped the way
db.save_post takes them:

    {"message_id": int, "date": int, "text": str, "entities": list,
     "forward_type": "chat" | "user" | None, "forward_name": str | None,
     "photo_url": str | None}

Three things about that shape are worth knowing. An album is *one* block in
the preview, so it arrives as one post whose picture is the first of the
gallery — which is exactly what a news is. The picture is a URL rather than a
Telegram file_id, because the preview has no file ids; publisher.py tells the
two apart by the "http" in front and downloads accordingly. And the
formatting, which the preview writes as HTML, is read into the same entity
list the Bot API's posts are stored with (richtext.py), so that a post reads
the same whichever door it came through.
"""
import asyncio
import hashlib
import html as html_module
import logging
import re

import aiohttp

import richtext

logger = logging.getLogger("fd.preview")

PREVIEW_URL = "https://t.me/s/{channel}"

REQUEST_TIMEOUT = 30

REQUEST_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                   " (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru,en;q=0.9",
}

CHANNEL_NAME_RE = re.compile(r"^[A-Za-z0-9_]{4,32}$")

_BLOCK_RE = re.compile(r'<div class="tgme_widget_message[^"]*"[^>]*data-post="([^"/]+)/(\d+)"')
_PHOTO_RE = re.compile(r"tgme_widget_message_photo_wrap[^>]*background-image:url\('([^']+)'\)")
_TIME_RE = re.compile(r'<time[^>]+datetime="([^"]+)"')
_TEXT_RE = re.compile(r'<div class="tgme_widget_message_text[^"]*"[^>]*>')
_SERVICE_RE = re.compile(r'class="[^"]*\bservice_message\b')
_FORWARD_LINKED_RE = re.compile(
    r'<a class="tgme_widget_message_forwarded_from_name"[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
    re.DOTALL)
_FORWARD_PLAIN_RE = re.compile(
    r'<span class="tgme_widget_message_forwarded_from_name"[^>]*>(.*?)</span>', re.DOTALL)

class PreviewError(Exception):
    """The preview could not be read or could not be understood — a private
    channel, a name that is not a channel, a network that is out, or markup
    that has changed since this parser was written."""

def normalize_channel(raw):
    """Accept `name`, `@name`, `t.me/name` or a link to a post and return the
    bare channel name; None when it is not a public channel name.

    A numeric id is not a name: the preview is addressed by @name only, which
    is also why a channel without one cannot be backfilled this way."""
    text = (raw or "").strip()
    if not text:
        return None
    text = re.sub(r"^https?://", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^(www\.)?t(elegram)?\.me/", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^s/", "", text, flags=re.IGNORECASE)
    text = text.split("?", 1)[0].split("/", 1)[0]
    text = text.lstrip("@").strip()
    return text if CHANNEL_NAME_RE.match(text) else None

def picture_key(url):
    """A stable identifier for a picture that has no Telegram file_unique_id.

    The slots compare pictures by this key to decide whether an upload can be
    skipped, so it has to be the same for the same picture and different for a
    different one. The preview's file URLs are stable — the same page fetched
    twice names the same file — so their digest answers both."""
    return "web:" + hashlib.sha1((url or "").encode("utf-8")).hexdigest()[:24]

def _extract_div(html, start):
    """The inner HTML of the <div> whose opening tag ends at `start`.

    Counts nested <div>s instead of stopping at the first </div>: a post's text
    can contain them, and cutting there would drop the rest of the post."""
    depth = 1
    index = start
    while index < len(html):
        opening = html.find("<div", index)
        closing = html.find("</div", index)
        if closing < 0:
            return html[start:]
        if 0 <= opening < closing:
            depth += 1
            index = opening + 4
            continue
        depth -= 1
        if depth == 0:
            return html[start:closing]
        index = closing + 5
    return html[start:]

def _forward_of(block):
    """(kind, name) of the post a block was reposted from, or (None, None).

    The preview says "Forwarded from" and then a name, and the one thing that
    tells a channel from a person is whether that name is a link: a channel's
    post can be linked to, a person's cannot. It is a weaker answer than the
    Bot API's — a person is named as they choose to appear, with no @name —
    but it is the only one a page meant for browsers carries."""
    match = _FORWARD_LINKED_RE.search(block)
    if match:
        name = richtext.plain(richtext.from_preview_html(match.group(2))).strip()
        if name:
            return "chat", name
    match = _FORWARD_PLAIN_RE.search(block)
    if match:
        name = richtext.plain(richtext.from_preview_html(match.group(1))).strip()
        if name:
            return "user", name
    return None, None

def _post_date(block):
    """The Telegram timestamp of one block as a unix time, or None."""
    match = _TIME_RE.search(block)
    if not match:
        return None
    stamp = match.group(1).replace("Z", "+00:00")
    try:
        from datetime import datetime
        return int(datetime.fromisoformat(stamp).timestamp())
    except ValueError:
        return None

def parse_preview(html):
    """The posts of a channel's public preview, oldest first.

    Service messages ("Channel created" and the like) are dropped, and so are
    blocks with no timestamp, since a news without a date cannot be published.
    Raises `PreviewError` when the page carries no post this parser
    recognizes — which is what a private channel, a preview that is switched
    off and a changed layout all look like."""
    if not html:
        raise PreviewError("empty response")

    bounds = list(_BLOCK_RE.finditer(html))
    if not bounds:
        raise PreviewError("no posts in the preview (private channel, or the preview is off)")

    posts = []
    for index, match in enumerate(bounds):
        end = bounds[index + 1].start() if index + 1 < len(bounds) else len(html)
        block = html[match.start():end]
        if _SERVICE_RE.search(block):
            continue

        date = _post_date(block)
        if date is None:
            continue

        text_match = _TEXT_RE.search(block)
        chars = (richtext.normalize(richtext.from_preview_html(
            _extract_div(block, text_match.end()))) if text_match else [])
        photos = _PHOTO_RE.findall(block)
        forward_type, forward_name = _forward_of(block)
        posts.append({
            "message_id": int(match.group(2)),
            "date": date,
            "text": richtext.plain(chars),
            "entities": richtext.to_entities(chars),
            "forward_type": forward_type,
            "forward_name": forward_name,
            "photo_url": html_module.unescape(photos[0]) if photos else None,
        })

    posts.sort(key=lambda post: (post["date"], post["message_id"]))
    return posts

async def fetch_posts(channel, session=None):
    """The posts of a public channel, read from its web preview, oldest first.

    Raises `PreviewError` when the channel cannot be read."""
    name = normalize_channel(channel)
    if not name:
        raise PreviewError("{!r} is not a public channel name".format(channel))

    owns_session = session is None
    session = session or aiohttp.ClientSession()
    try:
        async with session.get(
            PREVIEW_URL.format(channel=name), headers=REQUEST_HEADERS,
            timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
        ) as response:
            if response.status != 200:
                raise PreviewError("HTTP {}".format(response.status))
            return parse_preview(await response.text())
    except PreviewError:
        raise
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        raise PreviewError("{}: {}".format(type(e).__name__, e))
    finally:
        if owns_session:
            await session.close()

async def fetch_picture(url, session=None):
    """The bytes of one preview picture, or None when they cannot be had.

    A picture that will not download is not worth failing a pass over: the
    card is published without one instead (publisher.py), and the next pass
    tries again."""
    owns_session = session is None
    session = session or aiohttp.ClientSession()
    try:
        async with session.get(
            url, headers=REQUEST_HEADERS,
            timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
        ) as response:
            if response.status != 200:
                logger.warning("could not download %s: HTTP %s", url, response.status)
                return None
            return await response.read()
    except Exception as e:
        logger.warning("could not download %s: %s", url, e)
        return None
    finally:
        if owns_session:
            await session.close()
