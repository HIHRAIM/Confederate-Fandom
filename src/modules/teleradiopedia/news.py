"""What a news is: which posts become one, and what wikitext they turn into.

This module is the whole of the bot's editorial logic and it touches nothing
outside itself — no Telegram, no wiki, no database. It is handed the rows
db.get_recent_posts returned and hands back at most len(config.NEWS_TEMPLATES)
news, newest first, each already carrying the text, the date, the link and the
picture its slot needs.

Five rules decide what a news is:

* **An album is one news.** Telegram delivers a post with several pictures as
  several messages sharing a media_group_id; to a reader it is one post, so
  the messages of one album are folded into a single news that takes the text
  from whichever of them carries it and the picture from the first one that
  has any.
* **Only posts with text count.** A picture with no words says nothing on a
  main page, so a post without text is skipped and the next one down moves up
  into its place.
* **The post keeps its formatting and its paragraphs.** Bold, italics and
  links survive the trip into wikitext (richtext.py), and so do the line
  breaks, tidied down to at most one blank line between paragraphs; what a
  card has no use for — spoilers, blockquotes, mentions — loses its markup and
  keeps its text.
* **A repost says where it came from.** A post forwarded into the channel is
  published with a line naming the channel or the person it was taken from,
  after the date (`render_forward`).
* **The first picture wins, and a news without one shows none.** A post with
  several pictures shows the first — the same one Telegram shows in the
  channel. A post with no picture (or with a video instead) is published as a
  card with no picture at all: the whole image block is left out, and the
  slot's file on the wiki is neither overwritten nor shown. The next post
  that does bring a picture puts the block back and the file with it.
"""
import logging
import re
from datetime import datetime, timezone

import richtext
from modules.teleradiopedia.settings import (
    FORWARD_FROM_CHAT,
    FORWARD_FROM_USER,
    NEWS_CSS_PREFIX,
    NEWS_DATE_FORMAT,
    NEWS_MONTHS,
    NEWS_TEXT_LIMIT,
    NEWS_TIMEZONE,
)

logger = logging.getLogger("fd.news")

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

ELLIPSIS = "…"

SENTENCE_END_RE = re.compile(r"[.!?…][\"'»”)\]]?(?=\s|$)")

SENTENCE_CUT_FLOOR = 0.6

TRAILING_JUNK = " \t\n\u00a0,;:—–-‐.!?…"

def news_timezone():
    """The time zone the dates are written in (config.NEWS_TIMEZONE), or UTC
    when the system has no such zone — a wrong hour is a smaller problem than
    a bot that will not start. The tzdata dependency supplies IANA zones on
    Windows, where zoneinfo otherwise falls back to UTC even for valid names.
    """
    if ZoneInfo is None:
        return timezone.utc
    try:
        return ZoneInfo(NEWS_TIMEZONE)
    except Exception as e:
        logger.warning("unknown time zone %r (%s) — dates are written in UTC", NEWS_TIMEZONE, e)
        return timezone.utc

def format_date(ts):
    """A Telegram timestamp as the card writes it — '26 августа 2026'.

    Built from config.NEWS_DATE_FORMAT and config.NEWS_MONTHS rather than from
    strftime: month names in the form a date needs after a number are a
    question of language, and a server's installed locales are not something
    a bot should depend on."""
    moment = datetime.fromtimestamp(int(ts), timezone.utc).astimezone(news_timezone())
    month = NEWS_MONTHS[moment.month - 1] if len(NEWS_MONTHS) >= 12 else str(moment.month)
    return NEWS_DATE_FORMAT.format(day=moment.day, month=month, year=moment.year)

def normalize_text(raw):
    """One line of readable text out of a post.

    This is the plain-text path — what /status prints and what a log line
    reads — so here paragraph breaks really do become spaces. The cards go
    through richtext.normalize instead, which keeps them."""
    return re.sub(r"\s+", " ", raw or "").strip()

def cut_length(text, limit):
    """How many characters of a normalized text a card may keep, and whether
    anything was left behind.

    The cut is made where a reader would make it. A sentence that ends in the
    last part of the allowed window wins: the text stops there and an ellipsis
    takes the place of the full stop, so the card reads as a finished thought
    that has more behind it. Otherwise the cut is made at the last whole word,
    and any comma or dash left dangling at the end goes with it — a card must
    never end in the middle of a word or on a stray comma.

    Returns ``(kept, truncated)``. The length is what the caller slices, which
    is what lets the same decision apply to plain text and to text carrying
    formatting: the formatting is sliced with it, not recomputed."""
    if limit <= 0 or len(text) <= limit:
        return len(text), False
    if limit == 1:
        return 0, True

    window = text[:limit - 1]

    kept = None
    for match in SENTENCE_END_RE.finditer(window):
        if match.start() >= SENTENCE_CUT_FLOOR * (limit - 1):
            kept = match.start()
    if kept is None:
        """A paragraph break is a word boundary too; a whole word exactly
        filling the window must not be discarded for the preceding one."""
        if text[len(window)].isspace():
            kept = len(window)
        else:
            boundaries = [m.start() for m in re.finditer(r"\s", window)]
            kept = boundaries[-1] if boundaries else len(window)

    while kept > 0 and window[kept - 1] in TRAILING_JUNK:
        kept -= 1
    return (kept, True) if kept else (len(window.rstrip()), True)

def shorten(text, limit=None):
    """A post cut down to `limit` characters, ending in an ellipsis when
    anything was left behind. Plain text in, plain text out — /status reads a
    news this way; the cards go through `cut_chars`, which keeps the
    formatting."""
    limit = NEWS_TEXT_LIMIT if limit is None else limit
    text = normalize_text(text)
    kept, truncated = cut_length(text, limit)
    return text[:kept] + (ELLIPSIS if truncated else "")

def cut_chars(chars, limit=None):
    """The same cut, made on annotated characters (richtext.py).

    The ellipsis is appended unformatted: it is the bot's punctuation, not the
    channel's, and a bold ellipsis after a bold sentence would be a claim
    about the post that the post never made."""
    limit = NEWS_TEXT_LIMIT if limit is None else limit
    kept, truncated = cut_length(richtext.plain(chars), limit)
    chars = chars[:kept]
    return chars + [(ELLIPSIS, ())] if truncated else chars

def post_link(username, message_id):
    """The public link to one post, or None for a channel without a @name.

    A channel with no public name has no link a reader could follow, so the
    news is published with no link on its picture rather than with one that
    only members can open."""
    if not username:
        return None
    return "https://t.me/{}/{}".format(str(username).lstrip("@"), int(message_id))

def _group_posts(rows):
    """Fold the stored messages into posts, newest first.

    The messages of one album come back as one group; every other message is a
    group of itself. Inside a group the order is the order they were published
    in, which is what makes "the first picture" mean the same thing here as it
    does in the channel."""
    groups, order = {}, []
    for row in rows:
        key = ("album", row["media_group_id"]) if row["media_group_id"] else ("post", row["message_id"])
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(row)

    posts = []
    for key in order:
        members = sorted(groups[key], key=lambda r: r["message_id"])
        posts.append(members)
    posts.sort(key=lambda m: (m[0]["date"], m[0]["message_id"]), reverse=True)
    return posts

def _column(row, name):
    """One column of a stored row, or None when a database written before that
    column existed has no such thing. An old file must not cost a pass."""
    try:
        return row[name]
    except (IndexError, KeyError):
        return None

def _entities_of(row):
    """The formatting stored with one post row, as richtext.py takes it.

    Guarded because a row from a database written before the column existed
    has no `entities` at all — an old file must not cost the bot a pass."""
    try:
        raw = row["entities"]
    except (IndexError, KeyError):
        return []
    return richtext.entities_from_json(raw)

def collect_news(rows, username, count, limit=None):
    """The news to publish, newest first, at most `count` of them.

    `rows` are the stored messages of the channel in any order (db.get_recent_posts
    hands them over newest first); `username` is the channel's @name, which is
    what the links are built from.

    Each news carries its text twice over: `chars`, the annotated characters
    the card is rendered from, and `text`, the same thing without formatting,
    which is what /status prints and what a human reads in a log line."""
    news = []
    for members in _group_posts(rows):
        if len(news) >= count:
            break
        written = next((m for m in members if (m["text"] or "").strip()), None)
        if written is None:
            continue
        chars = cut_chars(
            richtext.normalize(
                richtext.annotate(written["text"], _entities_of(written))),
            limit)
        with_photo = next((m for m in members if m["photo_file_id"]), None)
        head = members[0]
        forward = next((m for m in members if _column(m, "forward_type")), head)
        news.append({
            "slot": len(news) + 1,
            "chat_id": head["chat_id"],
            "message_id": head["message_id"],
            "chars": chars,
            "text": richtext.plain(chars),
            "date": format_date(head["date"]),
            "forward_type": _column(forward, "forward_type"),
            "forward_name": _column(forward, "forward_name"),
            "link": post_link(username, head["message_id"]),
            "photo_file_id": with_photo["photo_file_id"] if with_photo else None,
            "photo_unique_id": with_photo["photo_unique_id"] if with_photo else None,
        })
    return news

def has_image(item):
    """Whether this news brought a picture at all. Whether the card *shows*
    one is a further question, and not this module's: a wiki shows the picture
    when its own file holds it, which publisher.py is what knows (it passes
    `file_name=None` for a card that must be published without one)."""
    return bool(item["photo_unique_id"])

def render_image(item, file_name, prefix=None):
    """The image block of a card, or the empty string when `file_name` is
    None — which is what hides the slot's file instead of showing a stale one.
    The link is carried by the picture alone; a news whose channel has no
    public name gets `link=`, which renders as a picture that is not a link."""
    if not file_name:
        return ""
    return '<div class="{prefix}__img">[[File:{file}|link={link}]]</div>\n'.format(
        prefix=prefix or NEWS_CSS_PREFIX, file=file_name, link=item["link"] or "")

def render_forward(item, prefix=None):
    """What the card says about a repost, or the empty string.

    A post that was reposted from somewhere gets a second tag of the same kind
    as the date, right after it: where it came from for a channel, who it came
    from for a person (config.FORWARD_FROM_CHAT / FORWARD_FROM_USER). Both
    wear the wikis' `__tag` class — the date is a tag under the news and so is
    this, and a stylesheet needs no new rule for either."""
    kind = item.get("forward_type")
    name = (item.get("forward_name") or "").strip()
    template = {"chat": FORWARD_FROM_CHAT, "user": FORWARD_FROM_USER}.get(kind)
    if not template or not name:
        return ""
    return '<span class="{prefix}__tag">{text}</span>'.format(
        prefix=prefix or NEWS_CSS_PREFIX,
        text=template.format(name=richtext.escape(name)))

def render_template(item, file_name, prefix=None):
    """The whole wikitext of one news template.

    The shape is the one the wiki's main page styles — a picture, then a body
    of text and date, and no heading of any kind — and it is rewritten in full
    on every pass rather than patched, so a template that was edited by hand
    comes back to what the channel says. `file_name` is None for a card that
    is published without a picture. The text comes out wearing the post's own
    formatting — bold, italics, links — which richtext.py is what carries over
    from Telegram, together with the escaping that keeps a post from breaking
    the page it lands in.

    `prefix` is the stem of the card's CSS classes and belongs to the wiki
    being written to, not to the news: the same three news are `tp-news__item`
    on one wiki and `rp-news__item` on another, because that is what each
    wiki's own stylesheet calls them."""
    prefix = prefix or NEWS_CSS_PREFIX
    return (
        '<div class="{prefix}__item">\n'
        "{image}"
        '<div class="{prefix}__body">'
        '<span class="{prefix}__text">{text}</span>'
        '<span class="{prefix}__tag">{date}</span>'
        "{forward}"
        "</div>\n"
        "</div>"
    ).format(
        prefix=prefix,
        image=render_image(item, file_name, prefix),
        text=richtext.render(item["chars"]),
        date=item["date"],
        forward=render_forward(item, prefix),
    )
