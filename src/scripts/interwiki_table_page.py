"""The interwiki table as wikitext: written by the bot, read back after a person.

The table is a page people edit by hand, so reading it back is the part that
has to be forgiving and exact at once. Forgiving: a cell may hold a
``[[w:c:…|…]]`` link, a plain title, an ``[[en:…]]`` link or nothing, on its
own line or after ``||``, with or without attributes — the column says which
language it is, and that is all the bot needs. Exact: a row that lost a cell
would shift every title after it into the wrong language, so a row with the
wrong number of cells is an error, never a guess, and so is a link whose
brackets do not close.

**What the bot writes.** One table per page, a header row ``! № !! ru !! en``
and then one row per article, one cell per line::

    |-
    | 12
    | [[w:c:ru.pokemon:Пикачу|Пикачу]]
    | style="background:…" title="…" | [[w:c:pokemon:Pikachu|Pikachu]]

The first cell is the row's number. It is how the bot knows a row it wrote
from one somebody added, and so what a cleared cell means: a cell that held
an existing link and is now empty is a link to remove. A row without a
number is a new row. The colour of a cell is what the bot found it by; the
reader never has to keep it.

A comment at the top, ``<!-- interwiki-table task=12 part=1/3 -->``, ties the
page to its task. A later task overwrites the same pages, and the comment is
how the earlier one notices.
"""
import re
import urllib.parse

MARK = "<!-- interwiki-table task={task} part={part}/{parts} -->"

MARK_RE = re.compile(r"<!--\s*interwiki-table\s+task=(\d+)\s+part=(\d+)/(\d+)\s*-->")

NUMBER_HEADERS = {"№", "#", "no", "no.", "n", "nr", "nº"}

STYLES = {
    "linked": None,
    "back": "background:rgba(0,150,255,.18)",
    "chain": "background:rgba(0,150,255,.18)",
    "same": "background:rgba(255,200,0,.3)",
    "redirect": "background:rgba(255,200,0,.3)",
    "key": "background:rgba(255,200,0,.3)",
    "dictionary": "background:rgba(0,170,90,.22)",
    "similar": "background:rgba(255,130,0,.3)",
    "broken": "background:rgba(255,0,0,.22)",
}
"""The colour of a cell by how the bot found its title. Translucent, so the
same colour reads on a light theme and a dark one."""

class TableError(Exception):
    """One thing wrong with a table a person edited: an i18n key and its values."""

    def __init__(self, key, **values):
        """Keep the key; the words are chosen when the list is sent."""
        super().__init__(key)
        self.key = key
        self.values = values

def link(prefix, title, label=None):
    """A ``[[w:c:…]]`` link to one article of one language version.

    `prefix` is ``w:c:pokemon`` for a wiki at the root of its host and
    ``w:c:ru.pokemon`` for one under a language path, which is Fandom's own
    rule. Spaces become underscores in the target; a doubled apostrophe in
    the label is escaped, or it would turn the rest of the cell italic."""
    target = str(title).replace(" ", "_")
    text = str(label if label is not None else title).replace("''", "'&#39;")
    return "[[{}:{}|{}]]".format(prefix, target, text)

def render(task, part, parts, columns, rows, prefixes, before=(), after=()):
    """One page of the table. -> wikitext.

    `columns` are language codes, the wiki's own first; `rows` are
    (number, {lang: (title, status, tooltip)}); `prefixes` maps a language to
    its ``w:c:`` prefix; `before` and `after` are the lines of prose around
    the table, already worded in the reader's language."""
    lines = [MARK.format(task=task, part=part, parts=parts)]
    lines += list(before)
    lines.append('{| class="wikitable sortable"')
    lines.append("! № !! " + " !! ".join(columns))
    for number, cells in rows:
        lines.append("|-")
        lines.append("| {}".format(number if number is not None else "").rstrip())
        for lang in columns:
            title, status, tooltip = cells.get(lang) or (None, None, None)
            if not title:
                lines.append("|")
                continue
            attrs = []
            style = STYLES.get(status)
            if style:
                attrs.append('style="{}"'.format(style))
            if tooltip:
                attrs.append('title="{}"'.format(str(tooltip).replace('"', "&quot;")))
            content = link(prefixes[lang], title)
            lines.append("| {} | {}".format(" ".join(attrs), content) if attrs
                         else "| " + content)
    lines.append("|}")
    lines += list(after)
    return "\n".join(lines) + "\n"

def mark_of(text):
    """The (task, part, parts) a page says it belongs to, or None."""
    match = MARK_RE.search(text or "")
    if not match:
        return None
    return tuple(int(group) for group in match.groups())

def _split_outside(text, separator):
    """`text` split on `separator` wherever it is not inside [[ ]] or {{ }}."""
    parts, depth_link, depth_tpl, start, i = [], 0, 0, 0, 0
    while i < len(text):
        if text.startswith("[[", i):
            depth_link += 1
            i += 2
            continue
        if text.startswith("]]", i) and depth_link:
            depth_link -= 1
            i += 2
            continue
        if text.startswith("{{", i):
            depth_tpl += 1
            i += 2
            continue
        if text.startswith("}}", i) and depth_tpl:
            depth_tpl -= 1
            i += 2
            continue
        if not depth_link and not depth_tpl and text.startswith(separator, i):
            parts.append(text[start:i])
            i += len(separator)
            start = i
            continue
        i += 1
    parts.append(text[start:])
    return parts

def _content(cell):
    """A cell without its attributes: what follows the first lone ``|``."""
    pieces = _split_outside(cell, "|")
    if len(pieces) > 1 and "=" in pieces[0] and "[[" not in pieces[0]:
        return "|".join(pieces[1:]).strip()
    return cell.strip()

def cell_title(content, languages=()):
    """The article a cell names, or None for an empty cell. Raises
    TableError("brackets") for a link that does not close.

    The column decides the language, so only the title is taken from a link:
    ``[[w:c:ru.x:Пикачу|…]]``, ``[[ru:Пикачу]]``, ``[[Пикачу]]`` and a bare
    ``Пикачу`` all name «Пикачу»."""
    text = re.sub(r"<!--.*?-->", "", content or "", flags=re.S).strip()
    text = re.sub(r"</?(?:span|small|b|i|s|u)\b[^>]*>", "", text).strip()
    if not text:
        return None
    if text.count("[[") != text.count("]]"):
        raise TableError("brackets", text=text[:80])
    match = re.search(r"\[\[([^\]]*)\]\]", text)
    if match:
        target = match.group(1).split("|", 1)[0].strip()
        wc = re.match(r"(?i)^:?w:c:[^:]+:(.*)$", target)
        if wc:
            target = wc.group(1)
        else:
            head, sep, rest = target.lstrip(":").partition(":")
            if sep and head.lower() in languages:
                target = rest
    else:
        target = text
    target = urllib.parse.unquote(target.replace("_", " ")).strip()
    target = re.sub(r"\s+", " ", target)
    if not target:
        return None
    return target[0].upper() + target[1:] if target[0].islower() else target

def parse(text, languages, numbered=True):
    """One page of the table. -> {'columns', 'rows'}, or raises TableError for
    the first thing that makes the page unreadable as a whole.

    A row is {'number' (int or None), 'cells' {lang: title or None},
    'line' (its first line, for the messages), 'errors' [TableError]} — the
    errors of one row are collected rather than raised, so that one message
    can list everything wrong with the table at once.

    `numbered` False reads a table whose first column is not a row number —
    the bot's dictionary, where a number would mean nothing; a № column is
    still recognised and skipped if somebody adds one. `languages` None
    accepts any column: a dictionary may hold languages a task does not
    compare."""
    lines = (text or "").split("\n")
    start = next((i for i, line in enumerate(lines) if line.strip().startswith("{|")), None)
    if start is None:
        raise TableError("no_table")
    end = next((i for i in range(start + 1, len(lines))
                if lines[i].strip().startswith("|}")), None)
    if end is None:
        raise TableError("no_table")

    columns = None
    rows = []
    current = None
    for index in range(start + 1, end):
        raw = lines[index]
        line = raw.strip()
        if line.startswith("|+"):
            continue
        if line.startswith("|-"):
            current = {"line": index + 1, "raw": []}
            rows.append(current)
            continue
        if line.startswith("!") and columns is None:
            headers = [_content(cell).strip().lower()
                       for cell in re.split(r"!!|\|\|", line[1:])]
            columns = headers
            current = None
            continue
        if line.startswith("|"):
            if current is None:
                current = {"line": index + 1, "raw": []}
                rows.append(current)
            current["raw"] += _split_outside(line[1:], "||")
            continue
        if current is not None and current["raw"]:
            current["raw"][-1] += "\n" + raw

    if not columns:
        raise TableError("no_header")
    has_number = columns[0] in NUMBER_HEADERS
    if numbered and not has_number:
        columns = ["№"] + columns
        has_number = True
    langs = columns[1:] if has_number else columns
    seen = set()
    for lang in langs:
        if languages is not None and lang not in languages:
            raise TableError("header", column=lang, langs=", ".join(sorted(languages)))
        if lang in seen:
            raise TableError("header_twice", lang=lang)
        seen.add(lang)

    out = []
    for row in rows:
        if not row["raw"]:
            continue
        errors = []
        cells = [_content(cell) for cell in row["raw"]]
        raw_number = re.sub(r"<[^>]*>", "", cells[0]).strip() if has_number else ""
        if len(cells) != len(columns):
            errors.append(TableError("cells", line=row["line"], found=len(cells),
                                     expected=len(columns)))
            out.append({"number": int(raw_number) if raw_number.isdigit() else None,
                        "cells": {}, "line": row["line"], "errors": errors})
            continue
        number = None
        if raw_number:
            if raw_number.isdigit():
                number = int(raw_number)
            else:
                errors.append(TableError("number", line=row["line"], value=raw_number[:20]))
        titles = {}
        for lang, cell in zip(langs, cells[1:] if has_number else cells):
            try:
                titles[lang] = cell_title(cell, languages or ())
            except TableError as e:
                e.values.update(line=row["line"], lang=lang)
                errors.append(e)
                titles[lang] = None
        out.append({"number": number, "cells": titles, "line": row["line"],
                    "errors": errors})
    return {"columns": langs, "rows": out}
