"""Typos and cosmetics for Russian-language wikis.

Ported from the operator's own `ru-bot/scripts/fix_typos_ru.py` (2025). Its
comments are kept as docstrings here, because this folder's clean_code.py
deletes every `#` comment.

Two groups of rules:

* **Typos** — `scripts/data/typos_ru.xml`, a list in the AWB format
  ``<Typo word="…" find="…" replace="…" />`` (607 rules). ``$1`` is turned
  into ``\\1``.

  The patterns are compiled by the ``regex`` module rather than the built-in
  ``re``: the AWB lists contain variable-length lookbehind (``(?<![вВ]ы|К)``)
  which .NET accepts and ``re`` does not. On ``re``, 7 of the 607 rules would
  not compile at all.

* **Cosmetics** — shared with the Ukrainian module through
  `scripts/wikitools.py`: spaces in headings, trailing spaces, indentation,
  blank lines, a space before a punctuation mark, ``« - »`` -> ``« — »``.

Unlike AWB: **foreign fragments are protected by sentence.** In the AWB list
19 rules are wrapped in a window ``(?<=(?:[^іїєґІЇЄҐuk]{30}))`` so as not to
"correct" Ukrainian and Belarusian text inside a Russian article (``Він
учасник змагань`` must not become ``Він участник``). The window is blind: it
forbids the rule from firing in the first 30 characters of the article, which
is exactly the lead. Here the windows are stripped (`strip_awb_guards`) and
their work is done by `skip_foreign`: the sentence carrying і ї є ґ ў is
protected. Russian text is corrected everywhere, the lead included, and the
foreign insertion is left untouched.

What is NOT touched — see `scripts/wikitools.py`: links whole (and with them
categories, files and interwikis), template and parameter names, bibliography
(``название=``, ``автор=``), ``<nowiki>``/``<pre>``/``<math>``/``<gallery>``,
HTML tags and attributes, table markup, ``{{{параметр}}}``, quoted text and
italics.

Idempotent: a second run over a corrected article makes no edit.
"""
from __future__ import annotations

import os
import re
import sys

from tasks import mechanic as mech
from tasks.params import FLAGS, Param

from scripts import punct_ru
from scripts import wikitools as wt

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
TYPOS_PATH = os.path.join(DATA_DIR, "typos_ru.xml")

SUMMARY_PARTS = [
    ("", "правописание"),
    ("пунктуация", "пунктуация"),
    ("косметика", "косметические изменения"),
]
"""The edit summary is assembled from what actually happened: whichever of the
three kinds of change really occurred are the ones listed. The order here is
the order in the summary. A rule belongs to a category by the prefix of its
name; the empty prefix is "everything else", that is, the typos from
typos_ru.xml."""

SUMMARY_LANG = "правописание"
SUMMARY_PUNCT = "пунктуация"
SUMMARY_COSMETIC = "косметические изменения"

DEFAULT_SKIP_TITLES = [
    r"^Widget:",
    r"^MediaWiki:",
    r"^Модуль:",
    r"^Module:",
    r"/skill\d*data$",
    r"/[a-z]*data$",
    r"\.(?:js|css|json)$",
]
"""Pages that are not prose: widget code and data pages. The nbsp rule turns
``&nbsp;`` into an ordinary space there, and in JS or HTML that can change the
layout. Found on gfl:ru (Widget:PNCStats, Zion/skilldata)."""

try:
    import regex
except ImportError:
    regex = None

_AWB_GUARD_BEHIND = re.compile(r"\(\?<=\(\?:\[\^[^\]]+\]\{\d+\}(?:\\b)?\)\)")
_AWB_GUARD_AHEAD = re.compile(r"\(\?=\(\?:\[\^[^\]]+\]\{\d+\}\)\)")
"""AWB's guard window: ``(?<=(?:[^іїєґІЇЄҐuk]{30})) … (?=(?:[^…]{30}))``."""

REPLACE_FIXES = {
    ("nbsp", "&nbsp;"): "\u00a0",
}
"""Corrections to the list itself. The key is (word, find), the value is what
the ``replace`` field should have been. They live here rather than in
data/typos_ru.xml so that the file stays exactly what the wiki gave us and can
be updated from it.

In the list ``&nbsp;`` is replaced by an ORDINARY space U+0020, which loses
the non-breaking: «10&nbsp;000» would become a breakable «10 000». U+00A0 was
evidently lost when the list was copied — the usual trouble with moving text
through tools that normalise spaces. A real non-breaking space is put back."""

FIND_FIXES = {
    ("и т. д., и т. п.", r"\b([иИ])\s*т\.?\s*([дп])\."):
        r"\b([иИ])[ \t]*т\.?[ \t]*([дп])\.",
    ("т. е., т. к., т. н.", r"\b([тТ])\.\s*([екн])\."):
        r"\b([тТ])\.[ \t]*([екн])\.",
}
"""Corrections to the ``find`` field. The key is (word, the original find).

``\\s`` in these rules also matches a NON-BREAKING space while the replacement
puts an ordinary one back. A correctly typed «и&nbsp;т.&nbsp;п.» therefore
degraded into «и т. п.» and lost the non-breaking — and an abbreviation is
exactly what must not be broken across a line. ``\\s`` becomes ``[ \\t]`` so
the rule normalises only the variants written with ordinary spaces («и т.п.»
-> «и т. п.») and leaves the already-correct ones alone."""


Options = wt.Options
"""The flags of one pass live in wikitools: both language modules and the
task runner pass the same object around."""


def strip_awb_guards(pattern: str) -> tuple[str, bool]:
    """Remove AWB's guard window. -> (pattern, whether there was one).

    The window is replaced by the per-sentence protection (`skip_foreign`),
    which is both more precise and does not silence the rule at the start of
    the article.
    """
    new = _AWB_GUARD_BEHIND.sub("", pattern)
    new = _AWB_GUARD_AHEAD.sub("", new)
    return new, new != pattern


def load_ru_typos(path: str = None, strip_guards: bool = True,
                  warn: bool = True) -> tuple[list, dict]:
    """Read the AWB list. -> (rules, statistics)."""
    path = path or TYPOS_PATH
    engine = regex or re
    text = open(path, encoding="utf-8").read()
    rules = []
    stats = {"всего": 0, "снято окон": 0, "не скомпилировалось": 0,
             "исправлено правил": 0}
    for m in wt._TYPO_RE.finditer(text):
        attrs = {k: wt.unescape(v) for k, v in wt._ATTR_RE.findall(m.group(1))}
        find, repl = attrs.get("find"), attrs.get("replace")
        if find is None or repl is None:
            continue
        stats["всего"] += 1
        name = attrs.get("word", find)
        fixed = REPLACE_FIXES.get((name, find))
        if fixed is not None and fixed != repl:
            repl = fixed
            stats["исправлено правил"] += 1
        fixed_find = FIND_FIXES.get((name, find))
        if fixed_find is not None and fixed_find != find:
            find = fixed_find
            stats["исправлено правил"] += 1
        if strip_guards:
            find, had = strip_awb_guards(find)
            if had:
                stats["снято окон"] += 1
        repl = wt._DOLLAR_RE.sub(r"\\\1", repl)
        try:
            rules.append(wt.Rule(f"опечатка: {name}", find, repl, engine=engine))
        except Exception as exc:
            stats["не скомпилировалось"] += 1
            if warn:
                line = text.count("\n", 0, m.start()) + 1
                print(f"  ! typos_ru.xml:{line} «{name}»: {exc}", file=sys.stderr)
    return rules, stats


def punct_rules(level, quotes: bool = False):
    """The punctuation rules as ordinary wt.Rule, so that masking applies."""
    if not level or level == "off":
        return []
    return [wt.Rule(name, rx.pattern, repl, engine=regex or re)
            for name, rx, repl in punct_ru.build_rules(level, quotes)]


def build_rules(typos: bool = True, punct_level: str = "safe",
                quotes: bool = False, strip_guards: bool = True):
    """The whole rule set of one pass: the typo list plus the punctuation.

    Both live in the same list on purpose. wikitools.apply_rules runs it until
    it converges, and punctuation and typos affect each other: a typo rule can
    put a comma where the punctuation rule then wants a space. Handing them
    over separately would make the pass depend on which ran first.
    """
    rules = []
    if typos:
        rules, _stats = load_ru_typos(strip_guards=strip_guards, warn=False)
    rules += punct_rules(punct_level, quotes)
    return rules


def process(text: str, rules, opts) -> tuple[str, list]:
    """One page's text through the rules, with the protection the flags ask for."""
    return wt.process_text(
        text, rules,
        fix_labels=opts.fix_link_labels,
        template_values=opts.template_values,
        skip_refs=opts.skip_refs,
        skip_italics=opts.skip_italics,
        cosmetic=opts.cosmetic,
        skip_quotes=opts.skip_quotes,
        skip_foreign=opts.skip_foreign)

SELF_TEST = [
    # --- опечатки из typos_ru.xml (все проверены на реальном списке) ---
    ("Абанент не отвечает.", "Абонент не отвечает.", "опечатка: абонент"),
    ("Это абракодабра.", "Это абракадабра.", "опечатка: абракадабра"),
    ("Он учасник соревнований.", "Он участник соревнований.",
     "опечатка: участник"),
    ("Наш раён большой.", "Наш район большой.", "опечатка: район"),
    ("Подписан дакумент.", "Подписан документ.", "опечатка: документ"),
    ("Большое колличество людей.", "Большое количество людей.",
     "опечатка: количество"),
    ("Он придти не смог.", "Он прийти не смог.", "опечатка: прийти"),

    # --- защита: то же, что у uk-bot ---
    ("[[Категория:Абанент]]", "[[Категория:Абанент]]", "категория"),
    ("[[Файл:Учасник.jpg|мини|Учасник]]", "[[Файл:Учасник.jpg|мини|Учасник]]",
     "файл"),
    ("[[Учасник]] — это учасник.", "[[Учасник]] — это участник.",
     "цель ссылки не трогаем, текст правим"),
    ("{{Карточка|название=Учасник|описание=учасник}}",
     "{{Карточка|название=Учасник|описание=участник}}",
     "библиографию бережём, прозу правим"),
    ("<nowiki>учасник</nowiki>", "<nowiki>учасник</nowiki>", "nowiki"),
    ("<!-- учасник -->", "<!-- учасник -->", "комментарий"),
    ("Ссылка [https://ex.com/учасник учасник тут].",
     "Ссылка [https://ex.com/учасник учасник тут].", "внешняя ссылка"),

    # --- иноязычные вставки (то, ради чего AWB городил окно {30}) ---
    ("Він учасник змагань.", "Він учасник змагань.",
     "украинское предложение не трогаем"),
    ("Ён удзельнік спаборніцтваў.", "Ён удзельнік спаборніцтваў.",
     "белорусское предложение не трогаем"),
    ("Он учасник. Він учасник змагань.",
     "Он участник. Він учасник змагань.",
     "русское правим, украинское рядом — нет"),
]

# Главное отличие от AWB: правило срабатывает и в первых 30 символах.
SELF_TEST_LEAD = [
    ("Учасник соревнований прибыл.", "Участник соревнований прибыл.",
     "срабатывает в самом начале статьи (AWB — нет)"),
    ("Раён был основан в 1900 году.", "Район был основан в 1900 году.",
     "преамбула правится"),
    ("Дакумент подписан вчера.", "Документ подписан вчера.",
     "преамбула: документ"),
]

SELF_TEST_COSMETIC = [
    ("==Раздел==", "== Раздел ==", "заголовок"),
    ("Слово , другое .", "Слово, другое.", "пробел перед знаком"),
    ("Иван - директор", "Иван — директор", "дефис -> тире"),
    ("а\n\n\n\n\nб\n", "а\n\nб\n", "пустые строки"),
    # Реальный случай с gfl:ru — калибр, а не конец предложения.
    ("A .223 competition cartridge", "A .223 competition cartridge",
     "точка перед цифрой: калибр не трогаем"),
    (".30-64 Rounds и .300BLK", ".30-64 Rounds и .300BLK",
     "калибры в начале строки"),
    ("Итого , 5 штук .", "Итого, 5 штук.",
     "запятая перед пробелом и цифрой — правим"),
    ("Число 3 . 14 тут", "Число 3. 14 тут",
     "точка с пробелом после — обычная пунктуация"),

    # --- двойные пробелы ---
    ("Слово  другое", "Слово другое", "двойной пробел -> одиночный"),
    ("Раз   два    три", "Раз два три", "три и четыре пробела"),
    ("Иван  -  директор", "Иван — директор",
     "двойные пробелы вокруг тире схлопываются"),
    ("<pre>\nа  б\n</pre>", "<pre>\nа  б\n</pre>",
     "внутри <pre> пробелы значимы — не трогаем"),
    ("<nowiki>а  б</nowiki>", "<nowiki>а  б</nowiki>",
     "внутри nowiki не трогаем"),
    ("[[Файл:А.jpg|мини|Подпись  тут]]", "[[Файл:А.jpg|мини|Подпись  тут]]",
     "внутри ссылки не трогаем"),
    ("{| class=\"wikitable\"\n|-\n| а  б\n|}",
     "{| class=\"wikitable\"\n|-\n| а б\n|}",
     "в ячейке таблицы схлопываем"),
    ("  Отступ  внутри\n", "Отступ внутри\n",
     "отступ снимается, внутренний двойной схлопывается"),
]

# В списке `&nbsp;` менялся на обычный пробел — неразрывность терялась.
# REPLACE_FIXES возвращает настоящий U+00A0.
SELF_TEST_NBSP = [
    ("Всего 10&nbsp;000 штук.", "Всего 10 000 штук.",
     "&nbsp; -> неразрывный пробел, а не обычный"),
    # Правильно набранные сокращения не трогаем: там неразрывный
    # пробел, и менять его на обычный — деградация.
    ("яблоки и т. п. тут", "яблоки и т. п. тут",
     "«и т. п.» с неразрывными — не трогаем"),
    ("верно, т. е. так", "верно, т. е. так",
     "«т. е.» с неразрывным — не трогаем"),
    # А слипшиеся — нормализуем.
    ("яблоки и т.п. тут", "яблоки и т. п. тут",
     "«и т.п.» -> «и т. п.»"),
    ("верно, т.е. так", "верно, т. е. так", "«т.е.» -> «т. е.»"),
]

# Пунктуация внутри бота: важно, что маскировка защищает разметку.
SELF_TEST_PUNCT = [
    ("Слово,другое тут", "Слово, другое тут", "пробел после запятой"),
    ("[[Файл:А,Б.jpg|мини|Подпись]]", "[[Файл:А,Б.jpg|мини|Подпись]]",
     "имя файла с запятой не трогаем"),
    ("{{Карточка|название=А,Б}}", "{{Карточка|название=А,Б}}",
     "библиографический параметр не трогаем"),
    ("<nowiki>слово,другое</nowiki>", "<nowiki>слово,другое</nowiki>",
     "nowiki"),
    ("Цена 1,5 рубля", "Цена 1,5 рубля", "дробь"),
]

# Все сочетания трёх видов правок.
SUMMARY_TEST = [
    ("==Раздел==", SUMMARY_COSMETIC, "только косметика"),
    ("Он учасник.", SUMMARY_LANG, "только опечатка"),
    ("Слово,другое", SUMMARY_PUNCT, "только пунктуация"),
    ("==Учасник==", f"{SUMMARY_LANG} и {SUMMARY_COSMETIC}",
     "правописание + косметика"),
    ("Он учасник,тут", f"{SUMMARY_LANG} и {SUMMARY_PUNCT}",
     "правописание + пунктуация"),
    ("==Раздел==\nСлово,другое", f"{SUMMARY_PUNCT} и {SUMMARY_COSMETIC}",
     "пунктуация + косметика"),
    ("==Учасник==\nОн учасник,тут",
     f"{SUMMARY_LANG}, {SUMMARY_PUNCT} и {SUMMARY_COSMETIC}",
     "все три вида"),
]


def self_test(rules=None):
    """Run every rule's own tests. -> the list of failures, empty when sound.

    The original printed this to the console and the wrapper script refused to
    start on a failure. Here the task runner calls it before the first edit of
    a pass: a rule that has stopped doing what it was written to do costs a
    refusal rather than a wiki full of bad edits.

    Each case is checked twice — the second pass must change nothing, or the
    bot would edit the same page for ever.
    """
    if rules is None:
        rules = build_rules()
    failures = []
    plain = Options()
    cosm = Options(cosmetic=True)

    def _check(cases, label, opts):
        """One table of (source, wanted, why) through the rules."""
        for src, want, why in cases:
            got, _ = process(src, rules, opts)
            again, _ = process(got, rules, opts)
            if got != want:
                failures.append("%s [%s]: вход %r, надо %r, вышло %r"
                                % (label, why, src, want, got))
            elif again != got:
                failures.append("%s [%s]: неидемпотентно, %r -> %r"
                                % (label, why, got, again))

    _check(SELF_TEST + SELF_TEST_LEAD, "опечатки", plain)
    _check(SELF_TEST_NBSP, "неразрывный пробел", plain)
    _check(SELF_TEST_COSMETIC, "косметика", cosm)

    punct = rules + punct_rules("commas")
    for src, want, why in SELF_TEST_PUNCT:
        got, _ = wt.process_text(src, punct, skip_italics=True,
                                 skip_quotes=True, skip_foreign=True)
        again, _ = wt.process_text(got, punct, skip_italics=True,
                                   skip_quotes=True, skip_foreign=True)
        if got != want:
            failures.append("пунктуация [%s]: вход %r, надо %r, вышло %r"
                            % (why, src, want, got))
        elif again != got:
            failures.append("пунктуация [%s]: неидемпотентно, %r -> %r"
                            % (why, got, again))

    for src, want, why in SUMMARY_TEST:
        _text, changes = process(src, rules, cosm)
        got = wt.make_summary(changes, SUMMARY_PARTS)
        if got != want:
            failures.append("описание [%s]: надо «%s», вышло «%s»"
                            % (why, want, got))

    return failures + punct_ru.self_test()


def prepare(ctx):
    """Compile the rule set of this run, and check it before the first edit.

    The self-test runs here on purpose. A rule list is data, and data that has
    been edited can be wrong in ways nothing else notices until a few hundred
    articles carry the mistake; the original refused to start on a failure and
    so does this. Six hundred rules compile in well under a second, so the
    check costs nothing worth saving.
    """
    flags = set(ctx.params.get("typos_ru_flags") or [])
    level = "safe"
    if FLAG_PUNCT_OFF in flags:
        level = "off"
    elif FLAG_PUNCT_COMMAS in flags:
        level = "commas"
    elif FLAG_PUNCT_TYPO in flags:
        level = "typo"
    rules = build_rules(punct_level=level, quotes=FLAG_QUOTES in flags)
    failures = self_test(rules)
    if failures:
        raise ValueError("самопроверка правил не прошла:\n" + "\n".join(failures[:5]))
    return {"rules": rules,
            "opts": Options(cosmetic=FLAG_COSMETIC in flags,
                            fix_labels=FLAG_LABELS in flags,
                            skip_refs=FLAG_SKIP_REFS in flags)}


def apply(ctx, page, text):
    """One page's text corrected. -> (text, the names of what was changed)."""
    state = ctx.state.get(SPEC.code) or {}
    new, changes = process(text, state["rules"], state["opts"])
    if new == text:
        return text, []
    return new, [name for name, _was, _now in changes]


def summary_part(ctx, labels):
    """The summary this run earned: exactly the kinds of change it made."""
    if not labels:
        return None
    return wt.make_summary([(name, "", "") for name in labels], SUMMARY_PARTS)


FLAG_COSMETIC = "cosmetic"
FLAG_PUNCT_OFF = "punct_off"
FLAG_PUNCT_TYPO = "punct_typo"
FLAG_PUNCT_COMMAS = "punct_commas"
FLAG_QUOTES = "quotes"
FLAG_LABELS = "labels"
FLAG_SKIP_REFS = "skip_refs"

SPEC = mech.Mechanic(
    code="typos-ru",
    kind=mech.TEXT,
    module=sys.modules[__name__],
    rights=("edit",),
    params=(
        Param("typos_ru_flags", FLAGS, "param_typos_ru_flags", options=(
            (FLAG_COSMETIC, "flag_cosmetic"),
            (FLAG_PUNCT_TYPO, "flag_punct_typo"),
            (FLAG_PUNCT_COMMAS, "flag_punct_commas"),
            (FLAG_QUOTES, "flag_quotes"),
            (FLAG_PUNCT_OFF, "flag_punct_off"),
            (FLAG_LABELS, "flag_fix_labels"),
            (FLAG_SKIP_REFS, "flag_skip_refs"),
        )),
    ),
)
