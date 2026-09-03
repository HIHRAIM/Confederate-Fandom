"""The layer every text-rewriting script shares: protection, cosmetics, rules.

Nothing here knows any particular language. The language rules live in the
scripts themselves (`scripts/typos_ru.py`, `scripts/punct_ru.py`,
`scripts/pravopys_uk.py`); what they have in common is here:

* **protection** — masking what may not be touched: links (and with them
  categories, files and interwikis), template names and parameter names,
  service and bibliographic values, ``<nowiki>``/``<pre>``/``<math>``/
  ``<gallery>``, HTML tags and attributes, table markup, magic words,
  ``{{{parameter}}}`` substitutions, quoted text and italics;
* **cosmetics** — spaces in headings, trailing spaces, indentation, blank
  lines, a space before a punctuation mark, ``« - »`` -> ``« — »``;
* **rules** — the AWB ``<Typo/>`` format, applying rules until they converge,
  and building the edit summary out of what actually happened.

Replacements always run over the *masked* text, so the protected pieces are
out of the rules' reach by construction rather than by agreement.

Ported from the operator's own bots (`ru-bot`, `uk-bot`, `common/wikitools.py`,
2025), where it was proven on five Ukrainian Fandom wikis — 849 edits, no
errors. The comments of the original are kept as docstrings here, because this
folder's clean_code.py deletes every `#` comment.

Not this module's zone: which pages are walked and what is saved
(tasks/runner.py), and the language rules themselves.
"""
from __future__ import annotations

import difflib
import os
import re
import sys

try:
    import regex as _regex
except ImportError:
    _regex = None

OPAQUE_TAGS = ("nowiki", "pre", "syntaxhighlight", "source", "code", "math",
               "chem", "ce", "timeline", "score", "graph", "mapframe",
               "maplink", "templatedata", "gallery", "imagemap", "hiero",
               "categorytree", "inputbox")

OPAQUE_RE = re.compile(
    r"<(" + "|".join(OPAQUE_TAGS) + r")\b[^>]*>.*?</\1\s*>", re.S | re.I)

COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
HTML_TAG_RE = re.compile(r"</?[A-Za-z][A-Za-z0-9]*(?:\s[^<>]*)?/?>")
EXT_LINK_RE = re.compile(r"\[(?:https?:)?//[^\]]*\]", re.I)
BARE_URL_RE = re.compile(r"(?:https?://|ftp://|//|www\.)[^\s\|\]\}<>]+", re.I)
MAGIC_RE = re.compile(r"__[A-ZА-ЯЄІЇҐ]+__")
TRIPLE_RE = re.compile(r"\{\{\{[^{}]*\}\}\}")
TABLE_LINE_RE = re.compile(r"^(?:\{\||\|\}|\|-|\{\{\{).*$", re.M)
ATTR_RE = re.compile(
    r"\b(?:style|class|id|width|height|align|valign|colspan|rowspan|bgcolor|"
    r"border|cellpadding|cellspacing|scope|group|name|ref|face|size)\s*=\s*"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s\|\}<>]+)", re.I)
FILENAME_RE = re.compile(
    r"\.(?:jpe?g|png|gif|svg|webp|ogg|ogv|oga|mp3|mp4|wav|webm|pdf|djvu|"
    r"tiff?|xcf|flac|mid|opus)\s*$", re.I)

LINKISH_KEYS = {
    "зображення", "изображение", "image", "img", "файл", "file", "картинка",
    "фото", "photo", "логотип", "logo", "обкладинка", "cover", "мапа", "map",
    "карта", "посилання", "ссылка", "link", "url", "сайт", "website",
    "сторінка", "страница", "page", "wikidata", "вікідані", "id",
    "ім'я файлу", "имя файла", "filename", "media", "медіа", "звук", "sound",
    "відео", "video", "клас", "class", "стиль", "style", "колір", "color",
    "ширина", "width", "висота", "height", "шаблон", "template",
}

CITATION_KEYS = {
    "назва", "название", "title", "заголовок", "підзаголовок", "subtitle",
    "trans-title", "оригінал", "original", "стаття", "статья", "article",
    "частина", "part", "розділ", "chapter", "книга", "book", "журнал",
    "journal", "газета", "newspaper", "видання", "edition", "work",
    "видавництво", "publisher", "publication", "серія", "series",
    "автор", "author", "автори", "authors", "редактор", "editor",
    "last", "first", "прізвище", "ім'я", "перекладач", "translator",
    "цитата", "quote", "том", "volume", "випуск", "issue",
}

PROTECTED_KEYS = LINKISH_KEYS | CITATION_KEYS
"""Parameter names whose value is not prose.

LINKISH_KEYS hold a file, a page or a URL. CITATION_KEYS hold a *quotation* —
the name of a source, an author, a publishing house — and "correcting" a
mistake there breaks the reference: ``{{УЗЕ|стаття=Ню Йорк}}`` is spelt
exactly the way that 1930s edition spelt it.
"""

ITALIC_RE = re.compile(r"'{2,5}[^'\n]+?'{2,5}")
"""Italics ``''…''`` most often mark the title of a work, a foreign word or an
obsolete form quoted as an example — precisely what must not be "corrected"
(``''Ню Йорк''`` inside the article «Нью-Йорк»). Switched on by skip_italics."""

QUOTED_RE = re.compile(
    r"«[^»\n]{1,120}»"
    r"|“[^”\n]{1,120}”"
    r"|\"[^\"\n]{1,120}\"")
"""Quoted text is as a rule a proper name (a programme, a channel, a band) or
a verbatim quotation, and neither may be touched: «Прес-клуб» is the name of a
show, not a misspelling of «пресклуб». The length cap and the ban on newlines
keep an unpaired quotation mark from eating half the article."""

OPAQUE_TEMPLATES = {
    "defaultsort", "displaytitle", "сортування", "сортировка",
    "нп", "не перекладено", "не переведено", "ill", "iw",
    "interlanguage link", "lang", "мова", "язык",
    "translit", "транслітерація", "транслитерация",
}

NON_PROSE_NS = re.compile(
    r"^\s*:?\s*(?:файл|file|image|зображення|изображение|категорія|категория|"
    r"category|媒体|media|媒體|шаблон|template|довідка|справка|help|"
    r"спеціальна|специальная|special|[a-z][a-z-]{1,11})\s*:",
    re.I)

FOREIGN_LETTERS = "іїєґўІЇЄҐЎ"
"""Letters the Russian alphabet does not have but its neighbours do: Ukrainian
і, ї, є, ґ and Belarusian і, ў. A word carrying one marks the fragment as not
being written in Russian."""

_FOREIGN_WORD_RE = re.compile(rf"[^\W\d_]*[{FOREIGN_LETTERS}][^\W\d_]*")

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+|\n+|(?=\|)|(?<=\|)")
"""Sentence boundaries: a full stop, a line break and list markup all end a
fragment."""


def foreign_spans(text: str) -> list[tuple[int, int]]:
    """Sentences that are not written in Russian (Ukrainian, Belarusian).

    This replaces AWB's trick, where the same thing was done with a window
    ``(?<=[^іїєґ]{30})`` around every word. The window is blind: it stopped a
    rule from firing in the first 30 characters of the article — that is,
    exactly in the lead, the most-read part of it. Here the boundary runs by
    sentence, so Russian text is corrected everywhere and a Ukrainian
    quotation inside it is left alone.
    """
    spans: list[tuple[int, int]] = []
    pos = 0
    for chunk in _SENTENCE_SPLIT_RE.split(text):
        if not chunk:
            continue
        start = text.find(chunk, pos)
        if start < 0:
            continue
        pos = start + len(chunk)
        if _FOREIGN_WORD_RE.search(chunk):
            spans.append((start, pos))
    return spans


def iter_balanced(text: str, op: str, cl: str) -> list[tuple[int, int]]:
    """Every ``op…cl`` pair, nested ones included, as (start, end)."""
    stack: list[int] = []
    spans: list[tuple[int, int]] = []
    i, n = 0, len(text)
    while i < n:
        if text.startswith(op, i):
            stack.append(i)
            i += len(op)
        elif text.startswith(cl, i):
            if stack:
                spans.append((stack.pop(), i + len(cl)))
            i += len(cl)
        else:
            i += 1
    spans.sort()
    return spans


def split_top_level(s: str) -> list[tuple[int, int]]:
    """The bounds of the parts separated by a top-level ``|``.

    Nested ``{{…}}``, ``[[…]]``, ``[…]`` and HTML tags are skipped, or
    ``{{Шаблон|а={{Інший|б}}}}`` would fall apart on somebody else's pipe.
    """
    parts: list[tuple[int, int]] = []
    depth_t = depth_l = depth_b = 0
    start = 0
    i, n = 0, len(s)
    while i < n:
        if s.startswith("{{", i):
            depth_t += 1
            i += 2
        elif s.startswith("}}", i):
            depth_t = max(0, depth_t - 1)
            i += 2
        elif s.startswith("[[", i):
            depth_l += 1
            i += 2
        elif s.startswith("]]", i):
            depth_l = max(0, depth_l - 1)
            i += 2
        elif s[i] == "[":
            depth_b += 1
            i += 1
        elif s[i] == "]":
            depth_b = max(0, depth_b - 1)
            i += 1
        elif s[i] == "|" and not (depth_t or depth_l or depth_b):
            parts.append((start, i))
            start = i + 1
            i += 1
        else:
            i += 1
    parts.append((start, n))
    return parts


def _template_spans(text: str, template_values: str) -> list[tuple[int, int]]:
    """The protected pieces of a template: its name, its parameter names and
    its service values.

    The name itself (``{{Ім'я``), every ``|`` and every ``ключ=`` is always
    protected; a positional parameter is protected unless template_values is
    'all', because a positional value is usually a page title; a named value
    is protected when its key is in PROTECTED_KEYS or when it looks like a
    file name.
    """
    spans: list[tuple[int, int]] = []
    for start, end in iter_balanced(text, "{{", "}}"):
        inner = text[start + 2:end - 2]
        base = start + 2
        parts = split_top_level(inner)
        name_raw = inner[parts[0][0]:parts[0][1]]
        name = re.sub(r"\s+", " ", name_raw.strip().replace("_", " ")).lstrip(":")
        spans.append((start, base + parts[0][1]))
        if name.split("|")[0].strip().lower() in OPAQUE_TEMPLATES:
            spans.append((start, end))
            continue
        for p_start, p_end in parts[1:]:
            spans.append((base + p_start - 1, base + p_start))
            seg = inner[p_start:p_end]
            eq = _top_level_eq(seg)
            if eq is None:
                if template_values != "all":
                    spans.append((base + p_start, base + p_end))
                continue
            spans.append((base + p_start, base + p_start + eq + 1))
            key = seg[:eq].strip().lower()
            value = seg[eq + 1:]
            if (template_values == "none" or key in PROTECTED_KEYS
                    or FILENAME_RE.search(value)):
                spans.append((base + p_start + eq + 1, base + p_end))
        spans.append((end - 2, end))
    return spans


def _top_level_eq(seg: str) -> int | None:
    """The position of the top-level ``=`` in one part of a template, or None.

    ``|опис={{Шаблон|а=б}}`` returns the position of the first ``=``, not the
    one inside the nested template.
    """
    depth = 0
    i, n = 0, len(seg)
    while i < n:
        if seg.startswith("{{", i) or seg.startswith("[[", i):
            depth += 1
            i += 2
        elif seg.startswith("}}", i) or seg.startswith("]]", i):
            depth = max(0, depth - 1)
            i += 2
        elif seg[i] == "=" and not depth:
            return i
        else:
            i += 1
    return None


def _link_spans(text: str, fix_labels: bool) -> list[tuple[int, int]]:
    """Wiki links. Whole by default, label included.

    With fix_labels the label of ``[[Ціль|підпис]]`` is left to the rules and
    only ``[[Ціль|`` and ``]]`` are kept, except for links into a namespace
    NON_PROSE_NS names, which are never prose.
    """
    spans: list[tuple[int, int]] = []
    for start, end in iter_balanced(text, "[[", "]]"):
        inner = text[start + 2:end - 2]
        if not fix_labels or NON_PROSE_NS.match(inner):
            spans.append((start, end))
            continue
        parts = split_top_level(inner)
        if len(parts) == 1:
            spans.append((start, end))
            continue
        spans.append((start, start + 2 + parts[0][1] + 1))
        spans.append((end - 2, end))
    return spans


def protected_spans(text: str, fix_labels: bool = False,
                    template_values: str = "named",
                    skip_refs: bool = False,
                    skip_italics: bool = False,
                    skip_quotes: bool = False,
                    skip_foreign: bool = False) -> list[tuple[int, int]]:
    """Every stretch of the text no rule may touch, merged and sorted."""
    spans: list[tuple[int, int]] = []
    for rx in (COMMENT_RE, OPAQUE_RE, EXT_LINK_RE, BARE_URL_RE, MAGIC_RE,
               TRIPLE_RE, TABLE_LINE_RE, ATTR_RE, HTML_TAG_RE):
        spans += [(m.start(), m.end()) for m in rx.finditer(text)]
    if skip_refs:
        spans += [(m.start(), m.end()) for m in
                  re.finditer(r"<ref\b[^>]*>.*?</ref\s*>", text, re.S | re.I)]
    if skip_italics:
        spans += [(m.start(), m.end()) for m in ITALIC_RE.finditer(text)]
    if skip_quotes:
        spans += [(m.start(), m.end()) for m in QUOTED_RE.finditer(text)]
    if skip_foreign:
        spans += foreign_spans(text)
    spans += _link_spans(text, fix_labels)
    spans += _template_spans(text, template_values)
    return merge_spans(spans)


def merge_spans(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Sort the spans and fuse the ones that touch or overlap."""
    if not spans:
        return []
    spans = sorted(s for s in spans if s[0] < s[1])
    out = [spans[0]]
    for start, end in spans[1:]:
        if start <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out


_M_OPEN, _M_CLOSE = "", ""
_M_DIGITS = {str(d): chr(0xE100 + d) for d in range(10)}
"""The markers are characters from the private use area: wikitext never
contains them, and they are neither letters nor digits, so ``\\b`` and ``\\w``
behave around them exactly as they do around a punctuation mark."""


def mask(text: str, spans: list[tuple[int, int]]) -> tuple[str, list[str]]:
    """Replace the protected pieces with markers. -> (text, what was saved)."""
    out: list[str] = []
    saved: list[str] = []
    pos = 0
    for start, end in spans:
        out.append(text[pos:start])
        token = "".join(_M_DIGITS[d] for d in str(len(saved)))
        out.append(_M_OPEN + token + _M_CLOSE)
        saved.append(text[start:end])
        pos = end
    out.append(text[pos:])
    return "".join(out), saved


_UNMASK_RE = re.compile(_M_OPEN + r"([-]+)" + _M_CLOSE)
_M_BACK = {v: k for k, v in _M_DIGITS.items()}


def unmask(text: str, saved: list[str]) -> str:
    """Put the protected pieces back where their markers stand."""

    def _restore(m: re.Match) -> str:
        idx = int("".join(_M_BACK[c] for c in m.group(1)) or "-1")
        return saved[idx]

    return _UNMASK_RE.sub(_restore, text)


class Rule:
    """One replacement rule.

    ``engine`` is a module with a ``compile()``: ``re`` by default, or
    ``regex``. The second one is needed for the AWB lists: they contain
    variable-length lookbehind (``(?<![вВ]ы|К)``), which ``re`` will not
    compile and .NET and ``regex`` will.
    """

    __slots__ = ("name", "rx", "repl")

    def __init__(self, name: str, pattern: str, repl: str,
                 flags: int = 0, engine=None) -> None:
        """Compile the pattern with whichever engine the caller chose."""
        self.name = name
        self.rx = (engine or re).compile(pattern, flags)
        self.repl = repl


_XML_UNESCAPE = (("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'),
                 ("&apos;", "'"), ("&amp;", "&"))
_ATTR_RE = re.compile(r"(\w+)\s*=\s*\"([^\"]*)\"")
_DOLLAR_RE = re.compile(r"\$(\d)")


def unescape(value: str) -> str:
    """XML entities back to characters. ``&amp;`` last, or «&amp;lt;» breaks."""
    for src, dst in _XML_UNESCAPE:
        value = value.replace(src, dst)
    return value


_TYPO_RE = re.compile(r"<Typo\b([^>]*?)/>")


def load_typos(path: str, warn: bool = True, engine=None,
               prefix: str = "опечатка") -> list[Rule]:
    """Read a list of ``<Typo word="…" find="…" replace="…" />``.

    Entries are searched for across the whole file rather than line by line:
    in the AWB lists several ``<Typo/>`` often sit on one line, and trailing
    ``<!-- … -->`` breaks a "line starts with <Typo" test.
    """
    rules: list[Rule] = []
    text = open(path, encoding="utf-8").read()
    for m in _TYPO_RE.finditer(text):
        attrs = {k: unescape(v) for k, v in _ATTR_RE.findall(m.group(1))}
        find, repl = attrs.get("find"), attrs.get("replace")
        if find is None or repl is None:
            continue
        name = attrs.get("word", find)
        repl = _DOLLAR_RE.sub(r"\\\1", repl)
        try:
            rules.append(Rule(f"{prefix}: {name}", find, repl, engine=engine))
        except Exception as exc:
            if warn:
                line = text.count("\n", 0, m.start()) + 1
                print(f"  ! {os.path.basename(path)}:{line} «{name}»: {exc}",
                      file=sys.stderr)
    return rules


HEADING_RE = re.compile(r"^(={2,6})[ \t]*(\S.*?)[ \t]*\1[ \t]*$", re.M)
"""``==Заголовок==`` -> ``== Заголовок ==``, the level kept by the back
reference."""

TRAILING_WS_RE = re.compile(r"[ \t]+$", re.M)
BLANK_LINES_RE = re.compile(r"\n[ \t]*(?:\n[ \t]*)+\n")

SPACE_BEFORE_PUNCT_RE = re.compile(r"(?<=\S)[ \t]+([,.;!?])(?!\d)")
"""A space before a punctuation mark. ``[ \\t]`` and not ``\\s``: with ``\\s``
the pattern would swallow the line break and glue two lines together. The
negative lookahead for a digit is required — a full stop followed straight by
a digit is not the end of a sentence but a decimal fraction or a calibre. A
real case on gfl:ru: «A .223 competition cartridge» became «A.223». The same
goes for «.30-64 Rounds» and «.300BLK»."""

DASH_RE = re.compile(r"(?<=\S)[ \t]+-[ \t]+(?=\S)")
"""« - » -> « — », with spaces required on both sides and a single hyphen."""

MULTI_SPACE_RE = re.compile(r"(?<=\S) {2,}(?=\S)")
"""Two or more spaces in a row -> one, *inside* a line only: the indent at the
start is strip_leading_spaces's business (it has its own logic for code
blocks) and the tail is TRAILING_WS_RE's. Tabs are left alone — in table
markup they are sometimes meaningful."""

_ONLY_TOKEN_RE = re.compile(r"^[ \t]*[-]+[ \t]*$")
"""A line that is nothing but a marker for a protected piece: it may be a
``<pre>`` or a ``<gallery>``, and its indent must not be touched."""


def strip_leading_spaces(text: str) -> tuple[str, int]:
    """Remove the indent at the start of lines.

    In wiki markup a line beginning with a space is displayed as a
    preformatted block. So the indent is removed from *single* lines only: two
    or more indented lines in a row are most likely a deliberate block of code
    or ASCII art, and are left alone.
    """
    lines = text.split("\n")
    indented = [bool(re.match(r"[ \t]+\S", ln)) for ln in lines]
    n = 0
    for i, is_ind in enumerate(indented):
        if not is_ind or _ONLY_TOKEN_RE.match(lines[i]):
            continue
        prev = indented[i - 1] if i else False
        nxt = indented[i + 1] if i + 1 < len(indented) else False
        if prev or nxt:
            continue
        lines[i] = lines[i].lstrip(" \t")
        n += 1
    return "\n".join(lines), n


def apply_cosmetic(text: str) -> tuple[str, list[tuple[str, str, str]]]:
    """The cosmetic edits. -> (text, the list of changes).

    Every operation runs over the *masked* text, so the contents of links,
    templates, ``<pre>``, ``<nowiki>`` and tables are out of their reach by
    construction. Trailing blank lines are collapsed but a final line break is
    never added: a page without one would otherwise be edited for nothing,
    since MediaWiki strips trailing whitespace when it saves anyway.
    """
    changes: list[tuple[str, str, str]] = []

    def _run(label: str, rx: re.Pattern, repl) -> None:
        """Apply one cosmetic pattern, remembering the first thing it changed."""
        nonlocal text
        first: list[tuple[str, str]] = []

        def _sub(m: re.Match) -> str:
            new = m.expand(repl) if isinstance(repl, str) else repl(m)
            if new != m.group(0) and not first:
                first.append((m.group(0), new))
            return new

        new_text, n = rx.subn(_sub, text)
        if new_text != text:
            was, now = first[0] if first else ("", "")
            changes.append((f"косметика: {label} ×{n}", was, now))
            text = new_text

    _run("заголовки", HEADING_RE, r"\1 \2 \1")
    _run("пробелы в конце строки", TRAILING_WS_RE, "")
    text2, n_ind = strip_leading_spaces(text)
    if n_ind:
        changes.append((f"косметика: отступы в начале строки ×{n_ind}", "", ""))
        text = text2
    _run("пустые строки", BLANK_LINES_RE, "\n\n")
    _run("пробел перед знаком препинания", SPACE_BEFORE_PUNCT_RE, r"\1")
    _run("дефис -> тире", DASH_RE, " — ")
    _run("двойные пробелы", MULTI_SPACE_RE, " ")

    tail = "\n" if text.endswith("\n") else ""
    stripped = text.rstrip() + tail
    if stripped != text:
        changes.append(("косметика: пустые строки в конце статьи", "", ""))
        text = stripped
    return text, changes


def is_cosmetic(change_name: str) -> bool:
    """A cosmetic change, or a language one (spelling, a typo)?"""
    return change_name.startswith("косметика")


def join_ru(items: list[str], conj: str = "и") -> str:
    """«а» / «а и б» / «а, б и в» — a list with a conjunction before the last."""
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} {conj} {items[-1]}"


def make_summary(changes: list[tuple[str, str, str]],
                 parts: list[tuple[str, str]], conj: str = "и") -> str:
    """The edit summary, built out of what the edit actually contains.

    ``parts`` is a list of ``(rule-name prefix, label)`` in the order the
    labels should appear in the summary. A rule belongs to the first category
    whose prefix matched; the prefix ``""`` is "everything else".

    This is what makes the summary assemble itself from what really happened:
    «правописание», «пунктуация и косметические изменения», «правописание,
    пунктуация и косметические изменения».
    """
    present: list[str] = []
    for prefix, label in parts:
        for name, _was, _now in changes:
            owner = next((p for p, _ in parts if p and name.startswith(p)), "")
            if owner == prefix:
                present.append(label)
                break
    return join_ru(present, conj)


def apply_rules(text: str, rules: list[Rule],
                max_passes: int = 4) -> tuple[str, list[tuple[str, str, str]]]:
    """Run the rules until they converge. -> (text, the list of replacements)."""
    changes: list[tuple[str, str, str]] = []
    for _ in range(max_passes):
        before = text
        for rule in rules:
            def _sub(m, rule: Rule = rule) -> str:
                """One replacement, recorded by the rule that made it.

                A broken back reference is the rule's own problem and never
                the page's: the engine is chosen by the bot, not by this
                module, so an expansion that raises leaves the text as it was.
                """
                try:
                    new = m.expand(rule.repl)
                except Exception:
                    return m.group(0)
                if new == m.group(0):
                    return m.group(0)
                changes.append((rule.name, m.group(0), new))
                return new
            text = rule.rx.sub(_sub, text)
        if text == before:
            break
    return text, changes


class Options:
    """The flags one text-rewriting pass runs with.

    The defaults are the operator's recommended run: italics, quoted text and
    foreign sentences protected, link labels and positional template values
    left alone. Cosmetics are off unless the caller asks, because they are a
    separate mechanic of the bot's and appear in the summary on their own.
    """

    def __init__(self, **kw):
        """Everything the pass may be told, with the safe answer by default."""
        self.fix_link_labels = kw.get("fix_labels", False)
        self.template_values = kw.get("template_values", "named")
        self.skip_refs = kw.get("skip_refs", False)
        self.skip_italics = kw.get("skip_italics", True)
        self.skip_quotes = kw.get("skip_quotes", True)
        self.skip_foreign = kw.get("skip_foreign", True)
        self.cosmetic = kw.get("cosmetic", False)

    def kwargs(self):
        """The same flags under the names process_text takes them by."""
        return {"fix_labels": self.fix_link_labels,
                "template_values": self.template_values,
                "skip_refs": self.skip_refs,
                "skip_italics": self.skip_italics,
                "skip_quotes": self.skip_quotes,
                "skip_foreign": self.skip_foreign,
                "cosmetic": self.cosmetic}


def process_text(text: str, rules: list[Rule], fix_labels: bool = False,
                 template_values: str = "named", skip_refs: bool = False,
                 skip_italics: bool = False, cosmetic: bool = False,
                 skip_quotes: bool = False,
                 skip_foreign: bool = False) -> tuple[str, list]:
    """Mask, apply the rules (and the cosmetics), unmask. The whole pass.

    Cosmetics and rules affect each other, so with `cosmetic` the two are run
    until they converge rather than once. A real case (tadc:ru): the text held
    «съеденным ,пока», the cosmetics removed the space *before* the comma
    giving «съеденным,пока», and the rule for a space *after* a comma no
    longer fired — it had run earlier. The page was fixed only on the bot's
    second run, which is to say it was not idempotent.
    """
    spans = protected_spans(text, fix_labels, template_values, skip_refs,
                            skip_italics, skip_quotes, skip_foreign)
    masked, saved = mask(text, spans)
    masked, changes = apply_rules(masked, rules)
    if cosmetic:
        for _ in range(4):
            masked, cosm = apply_cosmetic(masked)
            changes += cosm
            masked, more = apply_rules(masked, rules)
            changes += more
            if not more:
                break
    return unmask(masked, saved), changes


def diff_text(title: str, old: str, new: str, context: int = 1) -> str:
    """The unified diff of one page, as text.

    The original printed this to the console; here it goes into the file the
    bot sends to the person who asked for the run (tasks/report.py), so it
    returns a string instead.
    """
    return "\n".join(difflib.unified_diff(
        old.splitlines(), new.splitlines(),
        fromfile=f"{title} (было)", tofile=f"{title} (стало)",
        lineterm="", n=context))


def engine():
    """The regex engine the AWB lists need, or ``re`` when it is not installed.

    ``regex`` accepts the variable-length lookbehind those lists contain;
    without it seven of the 607 Russian rules do not compile at all, and the
    caller is told so once rather than per rule.
    """
    return _regex or re
