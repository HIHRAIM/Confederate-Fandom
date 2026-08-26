"""Telegram's formatting, carried over into wikitext.

A post is rarely plain text: it has bold, italics, links, sometimes code. The
two sources the bot reads describe that differently — the Bot API hands over
plain text plus a list of entities with offsets, the channel's public web
preview hands over HTML — and the wiki wants a third thing again. This module
is where the three meet.

Everything here works on one shape, deliberately the dumbest one that cannot
go wrong: a **list of (character, formats)** pairs, one entry per character of
the text, where `formats` is a tuple of tokens like ``("bold",)`` or
``("link", "https://…")``. Offsets, which is where formatting code usually
breaks, exist only at the doors — `from_telegram` converts them once (and from
UTF-16 units, which is what Telegram counts in) and `from_preview_html` never
sees any. Cutting, collapsing whitespace and joining runs are then plain list
operations that cannot put a tag in the wrong place.

What is not carried over is what a news card has no use for: spoilers,
blockquotes, mentions, custom emoji. Their text stays, their markup does not.
"""
import json
import re
from html.parser import HTMLParser

BOLD = ("bold",)
ITALIC = ("italic",)
UNDERLINE = ("underline",)
STRIKETHROUGH = ("strikethrough",)
CODE = ("code",)

TAGS = {
    BOLD: ("<b>", "</b>"),
    ITALIC: ("<i>", "</i>"),
    UNDERLINE: ("<u>", "</u>"),
    STRIKETHROUGH: ("<s>", "</s>"),
    CODE: ("<code>", "</code>"),
}

NESTING = ("link", "bold", "italic", "underline", "strikethrough", "code")

ENTITY_TOKENS = {
    "bold": BOLD,
    "italic": ITALIC,
    "underline": UNDERLINE,
    "strikethrough": STRIKETHROUGH,
    "code": CODE,
    "pre": CODE,
}

HTML_TOKENS = {
    "b": BOLD, "strong": BOLD,
    "i": ITALIC, "em": ITALIC,
    "u": UNDERLINE, "ins": UNDERLINE,
    "s": STRIKETHROUGH, "strike": STRIKETHROUGH, "del": STRIKETHROUGH,
    "code": CODE, "pre": CODE,
}

LINK_RE = re.compile(r"^https?://", re.IGNORECASE)

WIKI_ESCAPES = {
    "&": "&amp;", "<": "&lt;", ">": "&gt;",
    "[": "&#91;", "]": "&#93;",
    "{": "&#123;", "}": "&#125;",
    "|": "&#124;",
}

LINE_BREAK = "<br>"

def escape(text):
    """Make a run of text safe to drop into the middle of a wiki page.

    A line break becomes `<br>` rather than a literal newline: the card is
    one line of wikitext, and a real newline in the middle of it would either
    be swallowed or, worse, start a paragraph of its own inside the div.

    The text is written by whoever writes the channel and lands inside HTML
    inside wikitext, where both layers can be broken by a stray character: a
    '<' would open a tag, a '|' would end a template parameter, '[[' would
    start a link. Everything that means something to either layer is replaced
    by its HTML entity, which renders as the character itself and parses as
    nothing. The tags this module adds are written afterwards, around the
    escaped text, so they survive."""
    out = []
    for char in text or "":
        if char == "\n":
            out.append(LINE_BREAK)
        else:
            out.append(WIKI_ESCAPES.get(char, char))
    return "".join(out).replace("''", "&#39;&#39;")

def _rank(token):
    """Where a token sits in the nesting order — link outermost, code
    innermost — so that the same set of formats always produces the same
    tags in the same order."""
    try:
        return NESTING.index(token[0])
    except ValueError:
        return len(NESTING)

def _link_token(url):
    """``("link", url)`` for a usable http(s) address, or None.

    Anything else — a `tg://` mention, a relative address, an empty href — is
    dropped rather than written out: a news card is read by people who are not
    in Telegram."""
    url = (url or "").strip()
    return ("link", url) if LINK_RE.match(url) else None

def annotate(text, entities):
    """Turn text and entities into the (character, formats) pairs everything
    else here works on."""
    text = text or ""
    marks = [[] for _ in text]
    for entity in entities or []:
        token = _entity_token(entity)
        if token is None:
            continue
        start = max(0, int(entity.get("offset", 0)))
        end = min(len(text), start + int(entity.get("length", 0)))
        for index in range(start, end):
            marks[index].append(token)
    return [(char, tuple(sorted(set(tokens), key=_rank)))
            for char, tokens in zip(text, marks)]

def _entity_token(entity):
    """The format one stored entity stands for, or None when the card has no
    use for it."""
    kind = entity.get("type")
    if kind == "text_link":
        return _link_token(entity.get("url"))
    return ENTITY_TOKENS.get(kind)

def entities_from_json(raw):
    """The entity list a stored JSON string holds, or an empty list.

    Anything unreadable comes back empty rather than raising: a post whose
    formatting cannot be understood is still a post, and publishing it plain
    beats not publishing it at all."""
    if not raw:
        return []
    if isinstance(raw, list):
        return raw
    try:
        loaded = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return loaded if isinstance(loaded, list) else []

def plain(chars):
    """The text of annotated characters, with the formatting dropped."""
    return "".join(char for char, _ in chars)

MAX_BLANK_LINES = 1

def normalize(chars):
    """Tidy whitespace without flattening the post.

    The paragraphs a post was written with are worth keeping — a channel that
    puts a blank line between two thoughts means it — so line breaks survive,
    while everything else about the whitespace is tidied: runs of spaces and
    tabs become one space, spaces around a line break go, and a gap of any
    size between paragraphs comes out as at most one blank line
    (MAX_BLANK_LINES). The ends are trimmed.

    A space keeps the formatting of the whitespace it stands for, which is
    what holds a formatted phrase together: strip it, and a bold sentence
    comes out as one `<b>…</b>` per word, and a link whose text has a space in
    it comes out as two links. A line break carries none: it is punctuation of
    the layout, not of the sentence."""
    out = []
    for char, formats in chars:
        if char == "\n":
            while out and out[-1][0] == " ":
                out.pop()
            if _trailing_breaks(out) > MAX_BLANK_LINES:
                continue
            out.append(("\n", ()))
        elif char.isspace():
            if out and out[-1][0] in (" ", "\n"):
                continue
            out.append((" ", formats))
        else:
            out.append((char, formats))
    while out and out[0][0] in (" ", "\n"):
        out.pop(0)
    while out and out[-1][0] in (" ", "\n"):
        out.pop()
    return out

def _trailing_breaks(chars):
    """How many line breaks the text ends on — one is a new line, two are a
    blank line between paragraphs, and more is what gets cut down."""
    count = 0
    for char, _formats in reversed(chars):
        if char != "\n":
            break
        count += 1
    return count

def runs(chars):
    """The characters grouped into the longest runs that share a format set.

    Adjacent characters with the same formats become one run, which is what
    keeps a bold sentence one `<b>…</b>` rather than one per letter."""
    grouped = []
    for char, formats in chars:
        if grouped and grouped[-1][0] == formats:
            grouped[-1][1].append(char)
        else:
            grouped.append((formats, [char]))
    return [(formats, "".join(chunk)) for formats, chunk in grouped]

def render(chars):
    """The wikitext of annotated characters: escaped text wearing its tags.

    A link becomes wikitext's external-link form `[url text]` rather than an
    `<a>` tag, which MediaWiki would strip; everything else is an HTML tag the
    wiki accepts. Tags are opened outermost first (link, then bold, italics,
    underline, strikethrough, code), so the nesting is always well formed."""
    out = []
    for formats, text in runs(chars):
        rendered = escape(text)
        for token in reversed(formats):
            if token[0] == "link":
                if not rendered.strip():
                    continue
                rendered = "[{} {}]".format(token[1], rendered)
            else:
                open_tag, close_tag = TAGS.get(token, ("", ""))
                rendered = open_tag + rendered + close_tag
        out.append(rendered)
    return "".join(out)

def from_telegram(text, entities):
    """The stored entity list for a message the bot received itself.

    Telegram counts offsets in UTF-16 code units, Python in characters, and
    the two part company at the first emoji — which a news channel uses in
    every other post. The conversion happens here, once, so that nothing
    downstream has to know that UTF-16 was ever involved."""
    text = text or ""
    if not entities:
        return []

    units = text.encode("utf-16-le")
    index_of = {}
    position = 0
    for character_index, char in enumerate(text):
        index_of[position] = character_index
        position += len(char.encode("utf-16-le")) // 2
    index_of[position] = len(text)

    def to_character(offset):
        """The character index for a UTF-16 offset, clamped into the text."""
        if offset in index_of:
            return index_of[offset]
        return len(units) // 2 if offset > len(units) // 2 else len(text)

    stored = []
    for entity in entities:
        kind = getattr(entity, "type", None) or ""
        start = to_character(int(getattr(entity, "offset", 0)))
        end = to_character(int(getattr(entity, "offset", 0)) + int(getattr(entity, "length", 0)))
        item = {"type": kind, "offset": start, "length": max(0, end - start)}
        url = getattr(entity, "url", None)
        if url:
            item["url"] = url
        if _entity_token(item) is not None:
            stored.append(item)
    return stored

class _PreviewParser(HTMLParser):
    """The message-text fragment of the web preview, read into annotated
    characters.

    A parser rather than a regular expression because the fragment nests —
    a bold word inside a link inside a line — and because tags there are not
    always closed in the order they were opened."""

    def __init__(self):
        """Start with an empty stack of open formats and no text."""
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.chars = []

    def _formats(self):
        """The formats every character gets right now."""
        return tuple(sorted(set(self.stack), key=_rank))

    def handle_starttag(self, tag, attrs):
        """Open a format, a link, or nothing at all."""
        if tag == "br":
            self.chars.append(("\n", ()))
            return
        if tag == "a":
            token = _link_token(dict(attrs).get("href"))
            self.stack.append(token if token else ("ignored",))
            return
        self.stack.append(HTML_TOKENS.get(tag, ("ignored",)))

    def handle_startendtag(self, tag, attrs):
        """`<br>` is the only self-closing tag the preview uses."""
        if tag == "br":
            self.chars.append(("\n", ()))

    def handle_endtag(self, tag):
        """Close the most recently opened format, whatever it was."""
        if tag == "br":
            return
        if self.stack:
            self.stack.pop()

    def handle_data(self, data):
        """Text under whatever formats are open."""
        formats = tuple(token for token in self._formats() if token[0] != "ignored")
        for char in data:
            self.chars.append((char, formats))

def from_preview_html(fragment):
    """The annotated characters of one post as the web preview marked it up."""
    parser = _PreviewParser()
    parser.feed(fragment or "")
    parser.close()
    return parser.chars

def to_entities(chars):
    """Annotated characters back into a stored entity list.

    The preview arrives as markup and the database keeps entities, so this is
    the way back: one entity per run of characters sharing a token."""
    entities = []
    open_at = {}
    for index, (_char, formats) in enumerate(chars):
        formats = set(formats)
        for token in list(open_at):
            if token not in formats:
                entities.append(_entity(token, open_at.pop(token), index))
        for token in formats:
            open_at.setdefault(token, index)
    for token, start in open_at.items():
        entities.append(_entity(token, start, len(chars)))
    entities.sort(key=lambda item: (item["offset"], item["length"]))
    return entities

def _entity(token, start, end):
    """One stored entity for a token that ran from `start` to `end`."""
    if token[0] == "link":
        return {"type": "text_link", "offset": start, "length": end - start, "url": token[1]}
    for kind, mapped in ENTITY_TOKENS.items():
        if mapped == token and kind != "pre":
            return {"type": kind, "offset": start, "length": end - start}
    return {"type": token[0], "offset": start, "length": end - start}
