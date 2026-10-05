"""Punctuation and typography for Russian text.

Ported from the operator's own `ru-bot/scripts/punct_ru.py` (2025). Its
comments are kept as docstrings here, because this folder's clean_code.py
deletes every `#` comment.

The rules are split into three levels by how much they risk. The level is the
mechanic's `level` parameter (``safe`` / ``typo`` / ``commas``), ``safe`` by
default.

**safe — the mechanics of spaces around marks.** No meaning is read at all
here: «слово,другое» -> «слово, другое». The only way to be wrong is on an
exception (numbers, initials, abbreviations, domains), and every one of them
is closed by an explicit test.

**typo — typography.** Ellipses and doubled marks. It changes how the text
looks, not what it says. Turning straight quotes into «ёлочки» is NOT part of
it — that lives behind its own `quotes` flag, because with an odd number of
quotation marks the pair is assembled wrongly (see QUOTE_RULES).

**commas — placing commas.** Only where a comma is required regardless of how
the sentence parses: before «но» and «зато» in mid-sentence. Everything else
was rejected deliberately.

What was tried and dropped, so that it is not invented again:

* «запятая перед *который*» — 180 false positives across 30 featured articles
  of ru.wikipedia. The comma goes before the *start* of the clause, and
  «который» is often not the first word: «пауза, в ходе которой», «план,
  согласно которому»;
* «что», «как», «когда» and parenthetical words — the comma depends on the
  syntax rather than on the word. «Я не знаю что делать» needs none.

The measure of quality here is not the module's own tests but a run over the
featured articles of ru.wikipedia: those have been proofread by people, so any
edit proposed there is almost certainly false.

All the rules are applied to the MASKED text (scripts/wikitools.py), so links,
templates, tables, <pre>, <nowiki>, quoted titles and foreign insertions are
out of their reach by construction.

Every rule carries tests in SELF_TEST — positive ones and negative ones (what
must NOT fire). The task runner runs them before the first edit of a pass.
"""
from __future__ import annotations

import sys

try:
    import regex as re
except ImportError:
    import re

from tasks import mechanic as mech
from tasks.params import FLAGS, Param

from scripts import wikitools as wt

RU_LOWER = "а-яё"
RU_UPPER = "А-ЯЁ"
RU = RU_LOWER + RU_UPPER

ABBREV = (
    "т", "тт", "г", "гг", "в", "вв", "стр", "с", "рис", "табл", "им", "ул",
    "пр", "пл", "д", "кв", "обл", "р", "оз", "гор", "им", "см", "мм", "км",
    "кг", "мл", "руб", "коп", "тыс", "млн", "млрд", "трлн", "экз", "изд",
    "сокр", "букв", "перен", "напр", "прим", "ср", "мн", "ед", "муж", "жен",
    "англ", "нем", "фр", "лат", "греч", "исп", "ит", "яп", "кит", "рус",
)
"""Accepted abbreviations with a full stop. A space is wanted after them but
no capital follows, so the "full stop + capital" rule never touches them.
Listed here are the ones inside which a full stop is NOT the end of a
sentence."""

NO_SPACE_AFTER_COMMA = re.compile(
    rf"(?<=[{RU_LOWER}])([,;])(?=[{RU}])")
"""No space after a comma or a semicolon before a letter.

``(?<!\\d)`` / ``(?!\\d)`` are unnecessary because a lower-case letter is
required on the left, which already excludes «1,5». A colon needs care of its
own («12:30», «Файл:Имя») and is too loaded in wiki markup, so only the comma
and the semicolon are taken. The letter on the left must be LOWER case: two
capitals around the mark are almost always code or a pair of abbreviations
rather than prose — «БАЭС,УТП» in a table of sources. Found on the featured
articles of ru.wikipedia."""

NO_SPACE_AFTER_DOT = re.compile(
    rf"(?<=[{RU_LOWER}])\.(?=[{RU_UPPER}])")
"""No space after a full stop before a CAPITAL: «конец.Начало». A lower-case
letter is required on the left (or initials «А.С.» would match) and a capital
on the right (or domains and abbreviations would)."""

NO_SPACE_AFTER_BANG = re.compile(
    rf"(?<=[{RU_LOWER}])([!?])(?=[{RU_UPPER}])")
"""No space after «!» or «?» before a capital letter."""

SPACE_INSIDE_PAREN_OPEN = re.compile(r"\([ \t]+(?=\S)")
SPACE_INSIDE_PAREN_CLOSE = re.compile(r"(?<=\S)[ \t]+\)")
"""A space inside brackets: «( текст )» -> «(текст)»."""

ALT_ENDING = r"[{}]{{1,3}}".format(RU_LOWER)
ALT_ENDING_RE = re.compile(rf"(?<=[{RU_LOWER}])\(({ALT_ENDING})\)")
"""An alternative ending in brackets is written with a hyphen: «Готов(а)» ->
«Готов(-а)», «уважаемый(ая)» -> «уважаемый(-ая)», «студент(ка)» ->
«студент(-ка)». This is NOT a parenthetical clause, and a space before the
bracket would be wrong here. They are told apart by length: an ending is one
to three lower-case letters right against the word, and anything longer is
already an explanation («слово(пояснение)»)."""

NO_SPACE_BEFORE_PAREN = re.compile(
    rf"(?<=[{RU_LOWER}])\((?!{ALT_ENDING}\))(?=[{RU}])")
"""No space before an opening bracket: «слово(текст)» -> «слово (текст)».

A LOWER-case letter is required on the left: a capital means an abbreviation
where the bracket is part of the name and no space belongs — «ВКП(б)»,
«РСДРП(б)», «НИИ(ВА)». Found on the featured articles of ru.wikipedia. The
lookahead excludes alternative endings, which the rule above handles and where
a space would be a mistake."""

SAFE_RULES = [
    ("пунктуация: альтернативное окончание", ALT_ENDING_RE, r"(-\1)"),
    ("пунктуация: пробел после запятой", NO_SPACE_AFTER_COMMA, r"\1 "),
    ("пунктуация: пробел после точки", NO_SPACE_AFTER_DOT, ". "),
    ("пунктуация: пробел после !?", NO_SPACE_AFTER_BANG, r"\1 "),
    ("пунктуация: пробел внутри скобок", SPACE_INSIDE_PAREN_OPEN, "("),
    ("пунктуация: пробел внутри скобок", SPACE_INSIDE_PAREN_CLOSE, ")"),
    ("пунктуация: пробел перед скобкой", NO_SPACE_BEFORE_PAREN, " ("),
]
"""The bracket rules come first: «Готов(а)» must become «Готов(-а)» and not
«Готов (а)»."""

STRAIGHT_QUOTES = re.compile(r'"([^"\n]{1,200})"')
"""Straight quotes -> «ёлочки». The contents carry no line breaks and no
nested quotes and are capped at 200 characters, so that an unpaired quotation
mark cannot eat half the article."""

DOUBLE_COMMA = re.compile(r",{2,}")
DOUBLE_SEMICOLON = re.compile(r";{2,}")
"""Doubled commas and semicolons — a slip of the keyboard."""

MANY_DOTS = re.compile(r"\.{4,}")
"""Four or more full stops -> an ellipsis of three. Exactly three is left."""

SPACE_BEFORE_ELLIPSIS = re.compile(rf"(?<=[{RU}])[ \t]+\.\.\.")
"""A space BEFORE an ellipsis at the end of a word: «слово ...» -> «слово...»"""

QUOTE_RULES = [
    ("пунктуация: кавычки-ёлочки", STRAIGHT_QUOTES, r"«\1»"),
]
"""Quotes are behind a flag of their own rather than in the `typo` level.

The pattern pairs neighbouring quotation marks, and where the text holds an
odd number of them the pair is assembled wrongly. A real case (tadc:ru): the
closing quote of one phrase joined the opening quote of the next and produced
«, но было принято решение…» — a « standing before a comma. Doing it properly
needs the parity of the whole text to be read, not a character-wise match, so
the rule is off by default."""

TYPO_RULES = [
    ("пунктуация: дубль запятой", DOUBLE_COMMA, ","),
    ("пунктуация: дубль точки с запятой", DOUBLE_SEMICOLON, ";"),
    ("пунктуация: многоточие", MANY_DOTS, "..."),
    ("пунктуация: пробел перед многоточием", SPACE_BEFORE_ELLIPSIS, "..."),
]

COMMA_BEFORE_NO = re.compile(
    rf"(?<=[{RU_LOWER}])(?<!\b[нН]о)(?<!\b[аА])[ \t]+(но|зато)[ \t]+"
    rf"(?=[{RU_LOWER}])")
"""Before «но» and «зато» in mid-sentence a comma is always required.

A letter on the left (so this is not the start of a sentence), a space and a
lower-case letter on the right, and nothing done where the comma already
stands. «но» can be part of a word, hence ``\\b`` on both sides. «но зато» is
a compound conjunction that takes no comma between its parts, so before
«зато» the pattern looks for «но» or «а» on the left. Found on the featured
articles («…пользы, но зато оставил немало загадок»).

REJECTED: a comma before «который». The rule looked obvious, but a check over
30 featured articles of ru.wikipedia — text proofread by people — gave 180
false positives. The comma goes before the START of the subordinate clause
and «который» is often not the first word:

    пауза, в ходе которой стороны…      (the comma goes before «в ходе»)
    план, согласно которому силами…     (before «согласно»)
    союзников, разведка которых не…     (before «разведка»)

Working out where the clause starts needs a syntactic parse, not a regular
expression. The rule was removed on purpose — do not restore it without
dependency parsing."""

COMMA_RULES = [
    ("пунктуация: запятая перед «но»", COMMA_BEFORE_NO, r", \1 "),
]

def build_rules(level: str = "safe", quotes: bool = False):
    """-> the list of (name, compiled pattern, replacement).

    ``quotes`` switches on turning straight quotes into «ёлочки», separately
    from the level, because it is the one rule that can pair them wrongly.
    """
    rules = list(SAFE_RULES)
    if level in ("typo", "commas"):
        rules += TYPO_RULES
    if level == "commas":
        rules += COMMA_RULES
    if quotes:
        rules += QUOTE_RULES
    return rules

SELF_TEST = [
    ("safe", "Слово,другое", "Слово, другое", "пробел после запятой"),
    ("safe", "Раз;два", "Раз; два", "пробел после точки с запятой"),
    ("safe", "конец.Начало", "конец. Начало", "пробел после точки"),
    ("safe", "Что?Ответ", "Что? Ответ", "пробел после вопросительного"),
    ("safe", "текст( в скобках )", "текст (в скобках)", "пробелы в скобках"),
    ("safe", "слово(пояснение)", "слово (пояснение)", "пробел перед скобкой"),
    ("safe", "Готов(а) к бою", "Готов(-а) к бою", "альтернативное окончание"),
    ("safe", "Готов(-а) к бою", "Готов(-а) к бою", "уже с дефисом"),
    ("safe", "уважаемый(ая) читатель", "уважаемый(-ая) читатель",
     "окончание из двух букв"),
    ("safe", "студент(ка) вуза", "студент(-ка) вуза", "окончание -ка"),
    ("safe", "сделал(и) работу", "сделал(-и) работу", "окончание из буквы"),
    ("safe", "работал(ому) человеку", "работал(-ому) человеку",
     "окончание из трёх букв"),
    ("safe", "Цена 1,5 рубля", "Цена 1,5 рубля", "десятичная дробь"),
    ("safe", "Версия 2,0 и 3,5", "Версия 2,0 и 3,5", "дроби подряд"),
    ("safe", "А.С. Пушкин", "А.С. Пушкин", "инициалы"),
    ("safe", "сайт example.Ru", "сайт example.Ru", "домен не трогаем"),
    ("safe", "H(2)O формула", "H(2)O формула", "латиница и цифры в скобках"),
    ("safe", "ЦК ВКП(б) решил", "ЦК ВКП(б) решил",
     "аббревиатура со скобкой — часть названия"),
    ("safe", "доцент НИИ(ВА) РФ", "доцент НИИ(ВА) РФ", "аббревиатура 2"),
    ("safe", "т.д. и т.п.", "т.д. и т.п.", "сокращения"),
    ("safe", "БАЭС,УТП 1989", "БАЭС,УТП 1989",
     "две аббревиатуры — код, а не текст"),
    ("safe", "Москва,Санкт-Петербург", "Москва, Санкт-Петербург",
     "обычный текст с заглавной справа правим"),

    ("typo", "Слово,, другое", "Слово, другое", "дубль запятой"),
    ("typo", "Текст.... конец", "Текст... конец", "четыре точки"),
    ("typo", "Текст... конец", "Текст... конец", "три точки не трогаем"),
    ("typo", "слово ...", "слово...", "пробел перед многоточием"),

    ("commas", "Он пришёл но ушёл", "Он пришёл, но ушёл", "перед «но»"),
    ("commas", "Было трудно зато интересно", "Было трудно, зато интересно",
     "перед «зато»"),
    ("commas", "Он пришёл, но ушёл", "Он пришёл, но ушёл",
     "запятая уже есть"),
    ("commas", "Но он ушёл", "Но он ушёл", "«Но» в начале предложения"),
    ("commas", "Ноутбук новый", "Ноутбук новый", "«но» внутри слова"),
    ("commas", "пользы, но зато оставил", "пользы, но зато оставил",
     "«но зато» — составной союз, запятой внутри нет"),
    ("commas", "трудно а зато интересно", "трудно а зато интересно",
     "«а зато» тоже не разрываем"),
    ("commas", "освещения. Но зато западнее", "освещения. Но зато западнее",
     "«Но зато» с заглавной — тоже составной союз"),
]

def _apply(text, rules):
    """Apply a list of (name, pattern, replacement) to raw text, for the tests."""
    for _name, rx, repl in rules:
        text = rx.sub(repl, text)
    return text

def self_test():
    """Run every rule's own tests. -> the list of failures, empty when sound.

    The original printed this to the console before a run and the wrapper
    script refused to start on a failure. Here the task runner calls it before
    the first edit of a pass, so a rule that has stopped doing what it was
    written to do costs a refusal rather than a wiki full of bad edits.

    Idempotency is checked as well: a rule whose second pass changes the text
    again would make the bot edit the same page for ever.
    """
    failures = []
    for level, src, want, why in SELF_TEST:
        got = _apply(src, build_rules(level))
        again = _apply(got, build_rules(level))
        if got != want:
            failures.append("пунктуация [%s: %s]: вход %r, надо %r, вышло %r"
                            % (level, why, src, want, got))
        elif again != got:
            failures.append("пунктуация [%s: %s]: неидемпотентно, %r -> %r"
                            % (level, why, got, again))
    return failures

FLAG_TYPO = "typo"
FLAG_COMMAS = "commas"
FLAG_QUOTES = "quotes"

def prepare(ctx):
    """The punctuation rules of this run, checked before the first edit.

    Punctuation alone, without the typo list: a wiki may want its spaces
    around commas tidied and its wording left exactly as its authors wrote it.
    """
    flags = set(ctx.params.get("punct_ru_flags") or [])
    level = "commas" if FLAG_COMMAS in flags else (
        "typo" if FLAG_TYPO in flags else "safe")
    failures = self_test()
    if failures:
        raise ValueError("самопроверка правил не прошла:\n" + "\n".join(failures[:5]))
    return [wt.Rule(name, rx.pattern, repl, engine=wt.engine())
            for name, rx, repl in build_rules(level, FLAG_QUOTES in flags)]

def apply(ctx, page, text):
    """One page's punctuation tidied. -> (text, the names of what changed).

    Runs over the masked text like every other rewriting mechanic, so a comma
    inside a file name or a template parameter is nobody's business here.
    """
    rules = ctx.state.get(SPEC.code) or []
    new, changes = wt.process_text(text, rules, skip_italics=True,
                                   skip_quotes=True, skip_foreign=True)
    if new == text:
        return text, []
    return new, [name for name, _was, _now in changes]

def summary_part(ctx, labels):
    """What this mechanic contributes to the edit summary."""
    return "пунктуация" if labels else None

SPEC = mech.Mechanic(
    code="punct-ru",
    kind=mech.TEXT,
    module=sys.modules[__name__],
    rights=("edit",),
    params=(
        Param("punct_ru_flags", FLAGS, "param_punct_ru_flags", options=(
            (FLAG_TYPO, "flag_punct_typo"),
            (FLAG_COMMAS, "flag_punct_commas"),
            (FLAG_QUOTES, "flag_quotes"),
        )),
    ),
)
