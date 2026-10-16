"""The interwiki table: find the pairs, let a person check them, then link them.

This is the second mode of the interwiki mechanic (scripts/interwiki.py),
chosen in its dialog. The first mode only spreads links that exist, and it
must: a link is never written from a title that happens to match. But most
articles of a young wiki have no link at all — 98% of glitchproductions:ru,
81% of pokemon:ru when this was written — and for them it can do nothing.
The table mode finds the candidates the first may not write, and puts them in
front of a person first. scripts/interwiki.py owns the SPEC and hands every
hook to this module when the task's `interwiki_mode` is "table".

**Two moments, and /go between them.**

1. *Planning* (`planned`, before anybody confirms anything): the bot reads
   the chosen pages and the chosen language versions, builds one row per
   article, and writes the table to ``User:<bot>/Interwiki/1``, ``/2``… —
   ROWS_PER_PAGE rows a page, so that the editor stays usable. The plan
   message names every page it wrote, and any higher-numbered page left over
   from an earlier, larger table, which this task does not read.
2. *The person edits the table* on the wiki: fixes a cell, clears one, adds a
   row, deletes a row they do not want touched.
3. */go* (`before_start`, in tasks/queue.py: start): the table is read back
   and checked — markup, rows, that every named article exists, that no
   article stands in two rows, that nothing on the wiki changed under it.
   Anything wrong is answered as a list and the task waits for the next /go.
   Only then is the page list settled, and the run edits the pages.

**What a cell means.** The column is the language; the cell is a link or
just a title. A filled cell is a link to set. A cell that showed an
*existing* link and was cleared is a link to take out, on both sides. A
deleted row is a row left alone. A row the bot wrote is known by its number,
which is how a cleared cell is told from one that was always empty.

**How the candidates are found**, in order of trust: the links the article
already has; a sister article that links back to it; the links of the
sister articles it is linked to; the same title; a redirect of that title on
the other wiki; the bot's dictionary; the same sound (scripts/translit.py);
and, below a similarity the person chose, a similar sound.

**The dictionary** is a page anybody can edit: ``User:<bot>/Dictionary``, a
table whose columns are languages and whose rows are one name or term in
each — «Список эпизодов» beside «List of episodes», «Сатоси» beside «Ash».
It is what finds the pairs no transliteration can, because their titles are
translated or the official names differ. A row matches a whole title, and
its terms are also put in place of the words of a title before the sound is
compared, so «и» beside «and» turns «Эш и Пикачу» into a title that meets
«Ash and Pikachu». The dictionary pages of the wiki and of every language
version compared are read and joined; the bot creates an empty one, with an
explanation, on the wiki of a table task that has none. Each cell is coloured by how
it was found. A candidate already linked to another article, or claimed by
two rows, is not written into either — it goes to the questions under the
table, worded for whoever reads them, with what to do.

**Where the links are set**: on this wiki only, or — when the person chose
it — on every wiki of the table: the run on this wiki creates one task for
each of the others when it finishes, already confirmed, and each passes the
usual checks on its own wiki (the bot's standing, the person's standing,
the rights) before it edits anything.

Reading is anonymous (wiki/anon.py): the check at /go happens beside the
worker, where Pywikibot must not be touched, and a language version on
another host needs no login. Writing the table and the links goes through
the bot's own session, like every other edit.
"""
import logging
import time

from scripts import interwiki as iw
from scripts import interwiki_table_page as tp
from scripts import translit
from utils import Explained

logger = logging.getLogger("fd.scripts.interwiki_table")

SUBPAGE = "Interwiki"

ROWS_PER_PAGE = 200

FUZZY_SECONDS = 90
"""How long the comparison of similar titles may take in one plan. Planning
holds the worker, and the news must not wait for it; what is left over is
reported, and a narrower page list or fewer languages finish in time."""

READ_SECONDS = 180
"""How long planning may spend reading the language versions. Each one is
read whole, and a wiki with thirty of them could hold the worker for many
minutes; the versions not reached in time are named under the table, and a
task with fewer languages reads them."""

MAX_PROBLEMS = 30

CODE = "interwiki"
"""The mechanic this mode belongs to: its code is the key of the run's state
and what the tasks for the other wikis are made with."""

MODE = "table"

SCOPE_THIS = "this"
SCOPE_ALL = "all"

FLAG_EMPTY = "empty_rows"

ALL_WORDS = {"*", "all", "все", "усі", "всі", "wszystkie", "todos", "todas"}

DICTIONARY = "Dictionary"
"""The bot's dictionary page: ``User:<bot>/Dictionary`` on every wiki."""

FOUND = ("back", "chain", "same", "redirect", "dictionary", "key", "similar")
"""Statuses of a cell the bot proposes, as opposed to a link that exists."""

GUESSED = ("same", "redirect", "dictionary", "key", "similar")
"""Statuses found by the title alone — the ones two rows may compete for."""

def _norm(title):
    """A title as MediaWiki compares it: spaces, and the first letter upper."""
    text = " ".join(str(title or "").replace("_", " ").split())
    return text[:1].upper() + text[1:] if text else ""

def _base_of(site):
    """The address of a Pywikibot site without /wiki/: https://host[/lang]."""
    return "https://{}{}".format(site.hostname(), site.scriptpath() or "")

def _prefix(base):
    """The ``w:c:`` prefix of a wiki from its base address."""
    rest = base.split("://", 1)[-1]
    host, _, path = rest.partition("/")
    name = host.split(".")[0]
    path = path.strip("/")
    return "w:c:{}.{}".format(path, name) if path else "w:c:{}".format(name)

def _base_from_url(url):
    """The base address of a language version from its interwiki-map URL."""
    import re

    return re.sub(r"/wiki/.*$", "", str(url or "")).replace("http://", "https://")

def wanted_langs(answer, available):
    """The languages a person named. -> a sorted list. Raises Explained."""
    words = str(answer or "").replace(",", " ").lower().split()
    if not words or any(word in ALL_WORDS for word in words):
        return sorted(available)
    unknown = [word for word in words if word not in available]
    if unknown:
        raise Explained("error_iwtable_langs", langs=", ".join(unknown),
                        available=", ".join(sorted(available)) or "—")
    return sorted(dict.fromkeys(words))

def prepare(ctx):
    """Check the settings and the folding, and learn the language versions.

    A run that applies a checked table (`iw_child`, or `iw_plan` after /go)
    needs only the languages this wiki manages, to rebuild the block."""
    found = iw.language_map(ctx.site, ctx.lang)
    params = ctx.params
    state = {"managed": found["managed"], "plan": None}
    if params.get("iw_child") is not None:
        state["plan"] = params["iw_child"]
        return state
    if params.get("iw_plan") is not None:
        state["plan"] = (params["iw_plan"] or {}).get(ctx.lang) or {}
        return state
    failures = translit.self_test()
    if failures:
        raise ValueError("самопроверка транслитерации не прошла:\n" + "\n".join(failures[:5]))
    langs = wanted_langs(params.get("iw_langs"), set(found["urls"]))
    if not langs:
        raise Explained("note_interwiki_none")
    state.update(langs={lang: found["urls"][lang] for lang in langs},
                 base=_base_of(ctx.site))
    return state

class Reader:
    """What the analysis needs to know about one wiki, read once.

    `articles` {title: {'links', 'sort'}}, `redirects` {from: to}. The keys
    and the indexes are built lazily: the wiki of the task needs only its
    own pages."""

    def __init__(self, lang, base):
        """Remember where the wiki is; nothing is read yet."""
        from wiki.anon import AnonWiki

        self.lang = lang
        self.base = base
        self.prefix = _prefix(base)
        self.api = AnonWiki(base)
        self.articles = {}
        self.redirects = {}
        self.exact = {}
        self.keyed = {}
        self.han = 0

    def read_all(self):
        """Every article with its language links and sort key, and every
        redirect. The index by title and by sound is built here."""
        for page in self.api.all_pages(prop="langlinks|pageprops", lllimit="max",
                                       ppprop="defaultsort"):
            self.articles[page["title"]] = _page_info(page)
        self.redirects = self.api.redirects()
        for title, info in self.articles.items():
            self.exact.setdefault(title.casefold(), (title, None))
            for key in self._keys(title, info.get("sort")):
                self.keyed.setdefault(key, set()).add((title, None))
        for source, target in self.redirects.items():
            if target not in self.articles:
                continue
            self.exact.setdefault(source.casefold(), (target, source))
            for key in translit.keys(source, self.lang):
                self.keyed.setdefault(key, set()).add((target, source))

    def _keys(self, title, sort):
        """The keys of one article: of its title, or of its kana DEFAULTSORT
        when the title is in kanji."""
        if translit.has_han(title):
            if sort and translit.is_kana(sort):
                return translit.keys(title, self.lang, reading=sort)
            self.han += 1
            return set()
        return translit.keys(title, self.lang)

    def resolve(self, title):
        """An article title, a redirect's target, or None. -> (title, via)."""
        name = _norm(title)
        if name in self.articles:
            return name, None
        target = self.redirects.get(name)
        if target in self.articles:
            return target, name
        return None, None

def _page_info(page):
    """The parts of an API page the analysis keeps."""
    return {"links": {str(item.get("lang")).lower(): _norm(item.get("title"))
                      for item in page.get("langlinks") or []},
            "sort": (page.get("pageprops") or {}).get("defaultsort")}

def analyse(own_lang, own, sisters, scope, threshold, include_empty, clock=time.monotonic,
            dictionary=()):
    """Build the rows of the table. -> {'rows', 'notes'}.

    `own` is the Reader of the task's wiki with `articles` holding the scope
    pages and `redirects` the whole wiki's; `sisters` {lang: Reader} are read
    in full. A row is {'cells' {lang: [title, status, via, pct]}, 'doubts'
    [(key, values)], 'seen' [[page lang, page, link lang, link]]}. Blocking
    and pure apart from the clock, so it can be tried on real wikis without
    writing anything."""
    langs = sorted(sisters)
    terms = _dictionary_maps(own_lang, langs, dictionary)
    back = {lang: {} for lang in langs}
    for lang, reader in sisters.items():
        for title, info in reader.articles.items():
            target = info["links"].get(own_lang)
            if not target:
                continue
            final, _via = own.resolve(target)
            back[lang].setdefault(final or target, []).append(title)

    rows = []
    for title in scope:
        info = own.articles.get(title)
        if info is None:
            continue
        rows.append(_row(own_lang, title, info, own, sisters, langs, back, terms))

    taken = {}
    for index, row in enumerate(rows):
        for lang, cell in row["cells"].items():
            if lang != own_lang and cell[1] != "broken":
                taken.setdefault((lang, cell[0]), []).append(index)
    for (lang, title), indexes in taken.items():
        if len(indexes) < 2:
            continue
        owners = [i for i in indexes if rows[i]["cells"][lang][1] not in GUESSED]
        guessed = [i for i in indexes if i not in owners]
        if owners:
            for index in guessed:
                del rows[index]["cells"][lang]
                rows[index]["doubts"].append(("taken", {"lang": lang, "candidate": title,
                                                        "other": rows[owners[0]]["title"]}))
            continue
        for index in guessed:
            del rows[index]["cells"][lang]
            rows[index]["doubts"].append(("contested", {"lang": lang, "candidate": title,
                                                        "indexes": indexes}))

    notes = []
    if threshold < 100:
        cut = _similar(own_lang, own, sisters, rows, threshold / 100.0, clock)
        if cut:
            notes.append(("iwnote_cut", {"seconds": FUZZY_SECONDS, "count": cut}))
    for lang in langs:
        if sisters[lang].han:
            notes.append(("iwnote_han", {"lang": lang, "count": sisters[lang].han}))

    kept = []
    for row in rows:
        new = any(cell[1] in FOUND or cell[1] == "broken" or cell[2]
                  for lang, cell in row["cells"].items() if lang != own_lang)
        missing = any(lang not in row["cells"] for lang in langs)
        if new or row["doubts"] or (include_empty and missing):
            kept.append(row)
    for number, row in enumerate(kept, 1):
        row["number"] = number
    numbers = {id(row): row.get("number") for row in kept}
    for row in kept:
        for _key, values in row["doubts"]:
            if "indexes" in values:
                values["rows"] = ", ".join(str(numbers.get(id(rows[i]))) for i in values.pop("indexes")
                                           if numbers.get(id(rows[i])))
    return {"rows": kept, "notes": notes}

def _dictionary_maps(own_lang, langs, dictionary):
    """The dictionary turned into what one wiki's rows need. -> {lang: (whole
    titles {casefolded own term: {terms}}, [(own term, term)] longest first)}."""
    maps = {}
    for lang in langs:
        whole, phrases = {}, []
        for entry in dictionary:
            mine, theirs = entry.get(own_lang), entry.get(lang)
            if not mine or not theirs:
                continue
            whole.setdefault(mine.casefold(), set()).add(theirs)
            phrases.append((mine, theirs))
        phrases.sort(key=lambda pair: -len(pair[0]))
        maps[lang] = (whole, phrases)
    return maps

def _translate(title, phrases):
    """A title with the dictionary's terms put in place of its words, or None
    when no term of it is in the dictionary. Whole words only, any case."""
    import re

    changed = title
    for mine, theirs in phrases:
        pattern = re.compile(r"(?<!\w){}(?!\w)".format(re.escape(mine)), re.IGNORECASE)
        changed = pattern.sub(lambda _m, theirs=theirs: theirs, changed)
    return changed if changed != title else None

def _row(own_lang, title, info, own, sisters, langs, back, terms=None):
    """One article's row: its links, then what can be found without guessing,
    then what the title suggests."""
    cells = {own_lang: [title, "linked", None, None]}
    doubts, seen = [], []
    for lang in langs:
        link = info["links"].get(lang)
        if not link:
            continue
        final, via = sisters[lang].resolve(link)
        if final is None:
            cells[lang] = [link, "broken", None, None]
            doubts.append(("broken", {"title": title, "lang": lang, "target": link}))
            continue
        cells[lang] = [final, "linked", via, None]
        if via:
            doubts.append(("redirect", {"lang": lang, "target": via, "final": final}))
        other = sisters[lang].articles[final]["links"].get(own_lang)
        if other:
            other_final = own.resolve(other)[0] or other
            if other_final != title:
                doubts.append(("mismatch", {"title": title, "lang": lang, "target": final,
                                            "back": other_final}))
                seen.append([lang, final, own_lang, other])

    for lang in langs:
        if lang in cells:
            continue
        sources = back[lang].get(title) or []
        if len(sources) == 1:
            cells[lang] = [sources[0], "back", None, None]
        elif len(sources) > 1:
            doubts.append(("back_many", {"title": title, "lang": lang,
                                         "options": _options(sources)}))

    done = set()
    while True:
        found = {}
        for lang, cell in list(cells.items()):
            if lang == own_lang or cell[1] == "broken" or lang in done:
                continue
            done.add(lang)
            for other_lang, other in sisters[lang].articles.get(cell[0], {}).get("links", {}).items():
                if other_lang not in sisters or other_lang in cells:
                    continue
                final, _via = sisters[other_lang].resolve(other)
                if final:
                    found.setdefault(other_lang, set()).add(final)
        if not found:
            break
        for lang, finals in found.items():
            if len(finals) == 1:
                cells[lang] = [finals.pop(), "chain", None, None]
            elif not any(key == "chain" and values["lang"] == lang for key, values in doubts):
                doubts.append(("chain", {"title": title, "lang": lang,
                                         "options": _options(finals)}))

    asked = {values["lang"] for _key, values in doubts if "lang" in values}
    own_keys = own._keys(title, info.get("sort"))
    for lang in langs:
        if lang in cells or lang in asked:
            continue
        reader = sisters[lang]
        exact = reader.exact.get(title.casefold())
        whole, phrases = (terms or {}).get(lang, ({}, []))
        translated = None if exact else _translate(title, phrases)
        listed = set()
        if not exact:
            listed = {(reader.resolve(term)[0], None)
                      for term in whole.get(title.casefold(), ())} - {(None, None)}
        if exact:
            candidates = {exact}
            status = "same" if exact[1] is None else "redirect"
            short = False
        elif listed:
            candidates = listed
            status = "dictionary"
            short = False
        elif translated and (reader.exact.get(translated.casefold())
                             or any(reader.keyed.get(k) for k in translit.keys(translated, lang))):
            hit = reader.exact.get(translated.casefold())
            candidates = {hit} if hit else set()
            if not hit:
                for key in translit.keys(translated, lang):
                    candidates |= reader.keyed.get(key, set())
            status = "dictionary"
            short = False
        else:
            candidates = set()
            for key in own_keys:
                candidates |= reader.keyed.get(key, set())
            status = "key"
            short = bool(candidates) and max((len(k) for k in own_keys), default=0) < translit.MIN_FUZZY
        targets = {target for target, _via in candidates}
        if not targets:
            continue
        if len(targets) > 1:
            doubts.append(("several", {"title": title, "lang": lang,
                                       "options": _options(targets)}))
            continue
        target = targets.pop()
        via = next((v for t, v in candidates if t == target and v), None)
        linked = reader.articles[target]["links"].get(own_lang)
        if linked and (own.resolve(linked)[0] or linked) != title:
            doubts.append(("taken", {"lang": lang, "candidate": target,
                                     "other": own.resolve(linked)[0] or linked}))
            continue
        cells[lang] = [target, status, via, None]
        if short:
            doubts.append(("short", {"title": title, "lang": lang, "candidate": target}))
    return {"cells": cells, "doubts": doubts, "seen": seen, "keys": own_keys,
            "title": title}

def _options(titles):
    """A short list of titles for a question: «A», «B», «C» and N more."""
    titles = sorted(titles)
    shown = ", ".join("«{}»".format(t) for t in titles[:5])
    return shown + (" (+{})".format(len(titles) - 5) if len(titles) > 5 else "")

BIG_WIKI = 5000

def _similar(own_lang, own, sisters, rows, threshold, clock):
    """Fill the cells still empty with similar-sounding titles, within
    FUZZY_SECONDS. -> how many rows were left uncompared.

    Candidates are compared only within the block of keys that begin the
    same way and are of a near length. The block is the first letter on an
    ordinary wiki, and the first two on one with more than BIG_WIKI candidate
    titles: by the first letter alone, pokemon:ru against the English wiki
    took 85 seconds, by two 12. Two letters miss a pair like «Кэйтлин» and
    Caitlin (ke, ka), which is why a small wiki keeps the wider block."""
    import difflib

    started = clock()
    used = {(lang, cell[0]) for row in rows for lang, cell in row["cells"].items()}
    blocks, width = {}, {}
    for lang, reader in sisters.items():
        index = {}
        width[lang] = 2 if len(reader.articles) > BIG_WIKI else 1
        for key, entries in reader.keyed.items():
            if len(key) < translit.MIN_FUZZY:
                continue
            for target, _via in entries:
                if (lang, target) in used:
                    continue
                if reader.articles[target]["links"].get(own_lang):
                    continue
                index.setdefault(key[:width[lang]], []).append((key, target))
        blocks[lang] = index

    for position, row in enumerate(rows):
        if clock() - started > FUZZY_SECONDS:
            return len(rows) - position
        keys = [key for key in row["keys"] if len(key) >= translit.MIN_FUZZY]
        if not keys:
            continue
        asked = {values.get("lang") for _key, values in row["doubts"]}
        for lang in sisters:
            if lang in row["cells"] or lang in asked:
                continue
            scores = {}
            for key in keys:
                for other, target in blocks[lang].get(key[:width[lang]], ()):
                    if abs(len(other) - len(key)) > max(2, len(key) * 0.3):
                        continue
                    matcher = difflib.SequenceMatcher(None, key, other, autojunk=False)
                    if matcher.real_quick_ratio() < threshold or matcher.quick_ratio() < threshold:
                        continue
                    ratio = matcher.ratio()
                    if ratio >= threshold and ratio > scores.get(target, 0):
                        scores[target] = ratio
            if not scores:
                continue
            ranked = sorted(scores.items(), key=lambda item: -item[1])
            if len(ranked) > 1 and ranked[0][1] - ranked[1][1] < 0.02:
                row["doubts"].append(("several", {"title": row["title"], "lang": lang,
                                                  "options": _options(t for t, _r in ranked[:5])}))
                continue
            target, ratio = ranked[0]
            row["cells"][lang] = [target, "similar", None, int(round(ratio * 100))]
            used.add((lang, target))
            for block in blocks[lang].values():
                block[:] = [(k, t) for k, t in block if t != target]
    return 0

def read_dictionaries(apis, bot):
    """The bot's dictionary pages of these wikis, joined. -> (rows [{lang:
    term}], notes for the table, the languages whose page was found).

    A page that cannot be read as a table, and the rows with a broken cell,
    are left out and reported under the table; the rest of the dictionary
    still counts."""
    rows, notes, found = [], [], []
    name = "User:{}/{}".format(bot, DICTIONARY)
    for lang, api in apis:
        try:
            text, _latest = api.text(name)
        except Exception as e:
            logger.warning("cannot read the dictionary of %s: %s", lang, e)
            continue
        if text is None:
            continue
        found.append(lang)
        try:
            parsed = tp.parse(text, None, numbered=False)
        except tp.TableError:
            notes.append(("iwnote_dict_unreadable", {"lang": lang}))
            continue
        broken = 0
        for row in parsed["rows"]:
            if row["errors"]:
                broken += 1
                continue
            entry = {code: term for code, term in row["cells"].items() if term}
            if len(entry) >= 2:
                rows.append(entry)
        if broken:
            notes.append(("iwnote_dict_errors", {"lang": lang, "count": broken}))
    return rows, notes, found

def _create_dictionary(ctx, bot, columns):
    """An empty dictionary, with what it is for, on the wiki of the task.
    -> its title, or None when it could not be written. The words are in the
    wiki's language when the bot speaks it, English otherwise: the page is
    for the wiki's editors, not for the person who asked."""
    import pywikibot
    from utils import LANG_NAMES, localized

    lang = ctx.lang if ctx.lang in LANG_NAMES else "en"
    text = "\n".join([
        localized("iwdict_intro", lang),
        "",
        '{| class="wikitable sortable"',
        "! " + " !! ".join(columns),
        "<!-- " + localized("iwdict_example", lang) + " -->",
        "|}",
        "",
    ])
    try:
        page = pywikibot.Page(ctx.site, "User:{}/{}".format(bot, DICTIONARY))
        if page.exists():
            return None
        page.text = text
        page.save(summary="словарь для таблиц интервики", bot=True, minor=False,
                  apply_cosmetic_changes=False)
        return page.title()
    except Exception as e:
        logger.warning("cannot create the dictionary: %s", e)
        return None

WHOLE_WIKI = 500
"""From how many pages the task's own wiki is read whole rather than by
title: a list of articles brings 500 a request, a lookup by title only 50."""

def read_own(own, titles):
    """Read the pages of the task into `own`, and the wiki's redirects."""
    wanted = {_norm(title) for title in titles}
    if len(wanted) > WHOLE_WIKI:
        for page in own.api.all_pages(prop="langlinks|pageprops", lllimit="max",
                                      ppprop="defaultsort"):
            if page["title"] in wanted:
                own.articles[page["title"]] = _page_info(page)
    rest = [title for title in titles if _norm(title) not in own.articles]
    for _asked, page, _target in own.api.pages(rest, prop="langlinks|pageprops",
                                               lllimit="max", ppprop="defaultsort"):
        if page is not None:
            own.articles[page["title"]] = _page_info(page)
    own.redirects = own.api.redirects()

def planned(ctx, titles):
    """Build the table from the settled page list and write it to the wiki."""
    import db
    import pywikibot
    import wiki

    state = ctx.state.get(CODE) or {}
    if state.get("plan") is not None:
        return
    own = Reader(ctx.lang, state["base"])
    read_own(own, titles)
    sisters, unreachable, skipped = {}, [], []
    started = time.monotonic()
    for lang, url in state["langs"].items():
        if time.monotonic() - started > READ_SECONDS:
            skipped.append(lang)
            continue
        reader = Reader(lang, _base_from_url(url))
        try:
            reader.read_all()
        except Exception as e:
            logger.warning("cannot read the %s version: %s", lang, e)
            unreachable.append((lang, str(e)))
            continue
        sisters[lang] = reader

    bot = ctx.site.username() or ""
    dictionary, dict_notes, dict_found = read_dictionaries(
        [(ctx.lang, own.api)] + [(lang, reader.api) for lang, reader in sisters.items()], bot)
    flags = set(ctx.params.get("interwiki_table_flags") or [])
    result = analyse(ctx.lang, own, sisters, [_norm(t) for t in titles],
                     int(ctx.params.get("iw_threshold") or 100), FLAG_EMPTY in flags,
                     dictionary=dictionary)
    notes = result["notes"] + dict_notes + [("iwnote_unreachable", {"lang": lang, "error": error})
                                            for lang, error in unreachable]
    if skipped:
        notes.append(("iwnote_skipped", {"langs": ", ".join(skipped), "seconds": READ_SECONDS}))
    rows = result["rows"]
    columns = [ctx.lang] + sorted(sisters)
    prefixes = {lang: reader.prefix for lang, reader in sisters.items()}
    prefixes[ctx.lang] = own.prefix

    wiki.use_cookies(ctx.wiki)
    chunks = [rows[i:i + ROWS_PER_PAGE] for i in range(0, len(rows), ROWS_PER_PAGE)]
    names = ["User:{}/{}/{}".format(bot, SUBPAGE, k) for k in range(1, len(chunks) + 1)]
    written = []
    written_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    for part, chunk in enumerate(chunks, 1):
        text = _page_text(ctx, part, names, columns, chunk, prefixes,
                          notes if part == 1 else [])
        page = pywikibot.Page(ctx.site, names[part - 1])
        page.text = text
        page.save(summary="таблица интервики для задачи №{}".format(ctx.task_id),
                  bot=True, minor=False, apply_cosmetic_changes=False)
        written.append(page.title())

    stale = []
    try:
        for page in ctx.site.allpages(prefix="{}/{}/".format(bot, SUBPAGE), namespace=2):
            tail = page.title().rsplit("/", 1)[-1]
            if tail.isdigit() and int(tail) > len(chunks):
                stale.append(page.title())
    except Exception as e:
        logger.warning("cannot list the older table pages: %s", e)

    wikis = {lang: {"base": reader.base, "prefix": reader.prefix}
             for lang, reader in sisters.items()}
    wikis[ctx.lang] = {"base": own.base, "prefix": own.prefix}
    for lang, url in state["langs"].items():
        wikis.setdefault(lang, {"base": _base_from_url(url), "prefix": _prefix(_base_from_url(url))})
        wikis[lang]["url"] = url
    stored = dict(ctx.params)
    stored.update(
        iw_pages=written, iw_own=ctx.lang, iw_wikis=wikis, iw_bot=bot,
        iw_written_at=written_at,
        iw_written={str(row["number"]): {lang: [cell[0], cell[1], cell[2]]
                                         for lang, cell in row["cells"].items()}
                    for row in rows},
        iw_seen={str(row["number"]): row["seen"] for row in rows if row["seen"]},
    )
    db.set_task_params(ctx.task_id, stored)
    ctx.params.update(stored)

    doubts = sum(len(row["doubts"]) for row in rows)
    if written:
        ctx.note("note_iwtable_written", pages=", ".join(written), rows=len(rows),
                 doubts=doubts)
    else:
        ctx.note("note_iwtable_nothing")
    if stale:
        ctx.note("note_iwtable_stale", pages=", ".join(stale))
    if dictionary:
        ctx.note("note_iwdict_used", rows=len(dictionary), wikis=", ".join(dict_found))
    if ctx.lang not in dict_found:
        created = _create_dictionary(ctx, bot, columns)
        if created:
            ctx.note("note_iwdict_created", page=created)

def _words(values):
    """The values of a message as the i18n texts name them. A language code
    is `{code}` there, never `{lang}`: `localized` takes the reader's
    language under that name, and a value called `lang` collides with it."""
    return {("code" if name == "lang" else name): value for name, value in values.items()}

def _page_text(ctx, part, names, columns, rows, prefixes, notes):
    """One page of the table with its prose, in the reader's language."""
    from utils import localized

    lang = ctx.reader
    parts = ", ".join("[[{}|{}]]".format(name, k) for k, name in enumerate(names, 1))
    before = [
        localized("iwtable_intro", lang, id=ctx.task_id, wiki=ctx.wiki, part=part,
                  parts=len(names)),
        "",
        localized("iwtable_howto", lang),
        "",
        localized("iwtable_legend", lang),
        "",
        localized("iwtable_go", lang, id=ctx.task_id),
        "",
        localized("iwtable_parts", lang, parts=parts),
        "",
    ]
    table_rows = []
    for row in rows:
        cells = {}
        for cell_lang, (title, status, via, pct) in row["cells"].items():
            tooltip = None
            if status in FOUND or status == "broken":
                tooltip = localized("iwcell_" + status, lang, via=via or "", pct=pct or "",
                                    code=cell_lang)
            elif via:
                tooltip = localized("iwcell_via", lang, via=via)
            cells[cell_lang] = (title, status, tooltip)
        table_rows.append((row["number"], cells))
    after = []
    bullets = []
    for key, values in notes:
        bullets.append("* " + localized(key, lang, **_words(values)))
    for row in rows:
        for key, values in row["doubts"]:
            bullets.append("* " + localized("iwdoubt_" + key, lang, row=row["number"],
                                            **_words({k: v for k, v in values.items()
                                                      if k != "row"})))
    if bullets:
        after = ["", "== {} ==".format(localized("iwtable_doubts", lang)), ""] + bullets
    return tp.render(ctx.task_id, part, len(names), columns, table_rows, prefixes,
                     before=before, after=after)

def before_start(row, lang):
    """Read the table back and check it, at /go. -> None (nothing to check),
    {'problems': text} or {'titles', 'params', 'warnings'}.

    Runs beside the worker, so it reads anonymously and never touches
    Pywikibot. Every problem is collected before anything is answered: one
    message listing them all is worth more than a /go per mistake."""
    import db
    from utils import localized
    from wiki.anon import AnonWiki

    params = db.task_params(row)
    if params.get("iw_child") is not None or "iw_own" not in params:
        return None
    own = params["iw_own"]
    wikis = params.get("iw_wikis") or {}
    pages = params.get("iw_pages") or []
    problems = []

    def problem(key, **values):
        """Remember one problem, worded for the reader. A row is named by its
        number, and by its line in the source only when it has none — a new
        row, or one whose cells could not be counted."""
        if "line" in values:
            number = values.pop("row", None)
            line = values.pop("line")
            values["where"] = (localized("iwwhere_row", lang, row=number) if number
                               else localized("iwwhere_line", lang, line=line))
        problems.append(localized(key, lang, **_words(values)))

    if not pages:
        problem("iwerr_nothing_written")
        return {"problems": _problem_text(row, lang, problems)}

    readers = {code: AnonWiki(info["base"]) for code, info in wikis.items()}
    table_rows = []
    editors = set()
    for name in pages:
        try:
            text, _latest = readers[own].text(name)
        except Exception as e:
            problem("iwerr_wiki_unreachable", lang=own, error=str(e)[:200])
            continue
        if text is None:
            problem("iwerr_page_missing", page=name)
            continue
        mark = tp.mark_of(text)
        if mark is None:
            problem("iwerr_no_mark", page=name)
            continue
        if mark[0] != row["id"]:
            problem("iwerr_other_task", page=name, other=mark[0])
            continue
        try:
            parsed = tp.parse(text, set(wikis))
        except tp.TableError as e:
            problem("iwerr_" + e.key, page=name, **e.values)
            continue
        for entry in parsed["rows"]:
            entry["page"] = name
            for error in entry["errors"]:
                problem("iwerr_" + error.key, page=name, row=entry["number"],
                        **error.values)
            if not entry["errors"]:
                table_rows.append(entry)
        try:
            for user, _when in readers[own].editors_since(name, params.get("iw_written_at")):
                if user and user not in (params.get("iw_bot"), row["requested_by_wiki_user"]):
                    editors.add(user)
        except Exception as e:
            logger.warning("cannot read the history of %s: %s", name, e)

    numbers = {}
    for entry in table_rows:
        if entry["number"] is not None:
            numbers.setdefault(entry["number"], []).append(entry["page"])
    for number, where in numbers.items():
        if len(where) > 1:
            problem("iwerr_number_twice", row=number, pages=", ".join(sorted(set(where))))

    written = params.get("iw_written") or {}
    seen = params.get("iw_seen") or {}
    wanted = {code: set() for code in wikis}
    for entry in table_rows:
        for code, title in entry["cells"].items():
            if title:
                wanted[code].add(title)
        for code, cell in (written.get(str(entry["number"])) or {}).items():
            if cell[1] in ("linked", "broken") and cell[0]:
                wanted.setdefault(code, set()).add(cell[0])
            if cell[2]:
                wanted.setdefault(code, set()).add(cell[2])

    pages_of = {code: {} for code in wikis}
    unreachable = set()
    for code, titles in wanted.items():
        if not titles or code not in readers:
            continue
        try:
            for asked, page, _target in readers[code].pages(sorted(titles), prop="langlinks",
                                                            lllimit="max"):
                if page is not None:
                    pages_of[code][_norm(asked)] = (page["title"], _page_info(page)["links"])
        except Exception as e:
            unreachable.add(code)
            problem("iwerr_wiki_unreachable", lang=code, error=str(e)[:200])

    final_rows = []
    where = {}
    for entry in table_rows:
        cells = {}
        for code, title in entry["cells"].items():
            if not title:
                continue
            found = pages_of[code].get(_norm(title))
            if found is None and code in unreachable:
                continue
            if found is None:
                problem("iwerr_missing_title", page=entry["page"], line=entry["line"],
                        row=entry["number"], lang=code, title=title)
                continue
            cells[code] = found[0]
            where.setdefault((code, found[0]), []).append(entry["number"] or entry["line"])
        final_rows.append((entry, cells))
    for (code, title), places in where.items():
        if len(places) > 1:
            problem("iwerr_title_twice", lang=code, title=title,
                    rows=", ".join(str(p) for p in places))
    if problems:
        return {"problems": _problem_text(row, lang, problems)}

    scope = params.get("iw_scope") or SCOPE_THIS
    edited = set(wikis) if scope == SCOPE_ALL else {own}
    plan = {code: {} for code in wikis}

    def instruction(code, title):
        """The instruction for one page, made on first use."""
        return plan[code].setdefault(title, {"set": {}, "drop": {}})

    for entry, cells in final_rows:
        before = written.get(str(entry["number"])) or {} if entry["number"] else {}
        allowed = {}
        for code, cell in before.items():
            for name in (cell[0], cell[2]):
                if name:
                    allowed.setdefault(code, set()).add(_norm(name))
        for page_code, page_title, link_code, link_title in seen.get(str(entry["number"])) or []:
            allowed.setdefault(("page", page_code, _norm(page_title), link_code), set()).add(
                _norm(link_title))
        for code, title in cells.items():
            for other, other_title in cells.items():
                if other != code:
                    instruction(code, title)["set"][other] = other_title
        for code, cell in before.items():
            if cell[1] not in ("linked", "broken") or cells.get(code) == cell[0]:
                continue
            old = cell[2] or cell[0]
            for member_code, member in cells.items():
                if member_code != code:
                    instruction(member_code, member)["drop"][code] = old
            old_page = pages_of.get(code, {}).get(_norm(cell[0]))
            if cell[1] == "linked" and old_page:
                for member_code, old_member in before.items():
                    if member_code != code and old_member[1] == "linked":
                        instruction(code, old_page[0])["drop"][member_code] = old_member[0]
        for code, title in cells.items():
            if code not in edited:
                continue
            current_links = pages_of[code].get(_norm(title), (None, {}))[1]
            for other, other_title in instruction(code, title)["set"].items():
                current = current_links.get(other)
                if not current or _norm(current) == _norm(other_title):
                    continue
                ok = (_norm(current) in allowed.get(other, set())
                      or _norm(current) in allowed.get(("page", code, _norm(title), other), set())
                      or _norm(current) == _norm(instruction(code, title)["drop"].get(other)))
                if not ok:
                    problem("iwerr_conflict", page=entry["page"], line=entry["line"],
                            row=entry["number"], lang=code, title=title, other=other,
                            current=current,
                            wanted=other_title)
    if problems:
        return {"problems": _problem_text(row, lang, problems)}

    for code, pages_plan in plan.items():
        for title in list(pages_plan):
            current_links = pages_of[code].get(_norm(title), (None, {}))[1]
            wanted = pages_plan[title]
            wanted["set"] = {other: target for other, target in wanted["set"].items()
                             if _norm(current_links.get(other)) != _norm(target)}
            wanted["drop"] = {other: old for other, old in wanted["drop"].items()
                              if other in wanted["set"]
                              or _norm(current_links.get(other)) == _norm(old)}
            if not wanted["set"] and not wanted["drop"]:
                del pages_plan[title]
    plan = {code: pages for code, pages in plan.items() if pages and code in edited}
    if not plan:
        problem("iwerr_empty")
        return {"problems": _problem_text(row, lang, problems)}
    stored = dict(params)
    stored["iw_plan"] = plan
    warnings = None
    if editors:
        warnings = localized("iwwarn_editors", lang, id=row["id"],
                             users=", ".join(sorted(editors)))
    return {"titles": sorted(plan.get(own, {})), "params": stored, "warnings": warnings}

def _problem_text(row, lang, problems):
    """The answer to a /go whose table is not right."""
    from utils import localized

    lines = [localized("iwerr_title", lang, id=row["id"])]
    lines += ["• " + line for line in problems[:MAX_PROBLEMS]]
    if len(problems) > MAX_PROBLEMS:
        lines.append(localized("iwerr_more", lang, count=len(problems) - MAX_PROBLEMS))
    return "\n".join(lines)

def apply(ctx, page, text):
    """One page's language links as the checked table has them."""
    state = ctx.state.get(CODE) or {}
    plan = state.get("plan") or {}
    title = page.title() if page is not None else ""
    wanted = plan.get(title) or plan.get(_norm(title))
    managed = set(state.get("managed") or ())
    if not wanted:
        return text, []
    managed |= set(wanted["set"]) | set(wanted["drop"])

    masked, _saved = iw._mask_disabled(text)
    everything = {}
    for match in iw._IW_LINE_RE.finditer(masked):
        code = match.group("lang").lower()
        if code in managed:
            everything.setdefault(code, set()).add(match.group("title").strip())
    clashing = {code for code, titles in everything.items() if len(titles) > 1}
    if clashing - set(wanted["set"]):
        ctx.note("note_interwiki_clash", title=title)
        return text, []

    body, present, _clash = iw._strip(text, managed)
    links = dict(present)
    for code, old in wanted["drop"].items():
        if _norm(links.get(code)) == _norm(old):
            del links[code]
    for code, target in wanted["set"].items():
        current = links.get(code)
        if (current and _norm(current) != _norm(target) and code not in clashing
                and _norm(current) != _norm(wanted["drop"].get(code))):
            ctx.note("note_iwtable_changed", title=title, code=code, now=current,
                     table=target)
            continue
        links[code] = target
    new = body.rstrip()
    if links:
        new += "\n\n" + "\n".join("[[{}:{}]]".format(code, links[code])
                                  for code in sorted(links))
    if iw._squash(new) == iw._squash(text):
        return text, []
    return new, ["table"]

def summary_part(ctx, labels):
    """What this mechanic contributes to the edit summary."""
    return "интервики-ссылки по таблице" if labels else None

def finish(ctx):
    """On the wiki of the table, when the person chose every wiki: one task
    for each other wiki, confirmed with this one and started by the queue as
    soon as its own checks pass. -> report lines."""
    import db
    from utils import localized
    from wiki import families

    params = ctx.params
    if params.get("iw_child") is not None or (params.get("iw_scope") or SCOPE_THIS) != SCOPE_ALL:
        return None
    plan = params.get("iw_plan") or {}
    row = db.get_task(ctx.task_id)
    if row is None:
        return None
    requester = {"platform": row["requested_by_platform"], "id": row["requested_by_id"],
                 "name": row["requested_by_name"], "wiki_user": row["requested_by_wiki_user"]}
    made = []
    for code, pages in sorted(plan.items()):
        if code == ctx.lang or not pages:
            continue
        url = (params.get("iw_wikis") or {}).get(code, {}).get("url")
        try:
            family, lang = families.ensure_family(url)
        except Exception as e:
            ctx.note("note_iwtable_child_failed", code=code, error=str(e)[:200])
            continue
        child = {"source": "titles", "argument": "\n".join(sorted(pages)),
                 "namespaces": "0", "limit": 0, "summary": params.get("summary"),
                 "interwiki_mode": MODE, "iw_child": pages, "after_task": ctx.task_id}
        task_id = db.create_task("{}:{}".format(family, lang), [CODE], child, requester,
                                 dry_run=ctx.dry_run, reply_chat=row["reply_chat"],
                                 community_platform=row["community_platform"],
                                 community_id=row["community_id"])
        made.append("№{} ({}:{})".format(task_id, family, lang))
    if not made:
        return None
    ctx.note("note_iwtable_children", tasks=", ".join(made))
    return [localized("note_iwtable_children", ctx.reader, tasks=", ".join(made))]
