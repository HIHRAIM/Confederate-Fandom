"""Bringing articles to the Ukrainian orthography of 2019, plus common typos.

Ported from the operator's own `uk-bot/scripts/fix_pravopys.py` (2025). Its
comments are kept as docstrings here, because this folder's clean_code.py
deletes every `#` comment. The masking layer the original carried its own copy
of now lives once, in `scripts/wikitools.py`; only the Ukrainian rules are
here.

Two groups of rules:

* **Правопис-2019** — `scripts/data/pravopys2019.json`. ONLY those norms are
  included where the orthography gives a single spelling:

  - § 126: the sound sequence [je] -> ``є`` (проект -> проєкт, фойє -> фоє);
  - § 35, п. 4 (підп. 2—4) and п. 7: foreign components (веб-, прес-, екс-,
    віце-, міні-, напів- …) are written SOLID: веб-сайт -> вебсайт. The hyphen
    is kept before a proper name, an abbreviation, Latin script and digits —
    ``екс-Югославія``, ``веб-API``, ``топ-10`` (the notes to § 35);
  - § 36, п. 1, підп. 7: ``пів`` meaning "half" is written SEPARATELY
    (пів-Києва -> пів Києва); the lexicalised півострів/південь stay solid.

  Variant norms are NOT automated: § 123 (ефір/етер, кафедра/катедра), § 2
  п. 2 (ірій/ирій), авдиторія/аудиторія, Ґете/Гете. There the orthography
  allows both spellings and the bot has no right to choose for the author.

* **Typos** — `scripts/data/typos.txt` in the ``<Typo word find replace />``
  format (the Ukrainian Wikipedia's list). ``$1`` is turned into ``\\1``.

What the script does NOT touch (masked before the replacements and put back
as it was) is listed in `scripts/wikitools.py`: whole ``[[…]]`` links and with
them categories, files and interwikis; external links and bare URLs; template
names and parameter names; the values of positional parameters (usually page
titles); values that look like file names and ``зображення=``/``file=``
parameters; ``<nowiki>``, ``<pre>``, ``<syntaxhighlight>``, ``<math>``,
``<gallery>``, ``<timeline>``, ``<score>``, HTML comments; HTML tags and
layout attributes (``style=``, ``class=``, ``colspan=`` …); table markup lines
(``{|``, ``|-``) and magic words (``__TOC__``).

Idempotent: a second run over a corrected article makes no edit.
"""
from __future__ import annotations

import json
import os
import re
import sys

from tasks import mechanic as mech
from tasks.params import FLAGS, Param

from scripts import wikitools as wt

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
RULES_PATH = os.path.join(DATA_DIR, "pravopys2019.json")
TYPOS_PATH = os.path.join(DATA_DIR, "typos.txt")

SUMMARY_LANG = "правопис"
SUMMARY_COSMETIC = "косметичні зміни"
SUMMARY_BOTH = "правопис та косметичні зміни"

SUMMARY_PARTS = [
    ("", SUMMARY_LANG),
    ("косметика", SUMMARY_COSMETIC),
]
SUMMARY_CONJ = "та"
"""The edit summary is assembled from what the edit actually contains: only
cosmetics -> «косметичні зміни», only orthography or typos -> «правопис», both
-> «правопис та косметичні зміни»."""

UA_LOWER = "а-щьюяєіїґ’'ʼ"
UA_UPPER = "А-ЩЬЮЯЄІЇҐ"
UA_LETTER = UA_LOWER + UA_UPPER


def load_data(path: str = None) -> dict:
    """The editable rule lists of правопис-2019, as they are on disk."""
    with open(path or RULES_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def build_pravopys_rules(data: dict, extra_components: bool = False,
                         piv_solid: bool = False) -> list:
    """The rules of правопис-2019 built out of the lists.

    § 126 gives two shapes: a substring replaced anywhere, and a whole word.
    § 35 strips the hyphen only when a lower-case Cyrillic letter follows, so
    that a proper name, an abbreviation, Latin script or a digit keeps it, and
    only when the component is not repeated — § 35, п. 6, підп. 1 keeps the
    hyphen in repetitions (писав-писав, білий-білий). Without that test the
    nickname «Поп-Поп» in an oblique case — «Поп-попа», «поп-попу» — would be
    glued into «Поппопа». A real case on theloudhouse.

    § 36 is three rules in order: пів before a proper name is always separate,
    the lexicalised words are solid, and everything else hyphenated becomes
    separate. `piv_solid` adds the optional fourth — півгодини -> пів години.
    """
    rules = []

    je = data["je_words"]
    for src, dst in je["substring"].items():
        if src != dst:
            rules.append(wt.Rule(f"§126 {src}->{dst}", re.escape(src), dst))
    for src, dst in je["word"].items():
        if src != dst:
            rules.append(wt.Rule(f"§126 {src}->{dst}",
                                 rf"(?<![{UA_LETTER}]){re.escape(src)}\b", dst))

    comp = data["components_solid"]
    keep = {w.lower() for w in data["components_keep_hyphen"]["list"]}
    names = ("p2_inshomovni", "p3_kilkisnyi_vyiav", "p4_anty_vice_eks",
             "p7_napiv")
    parts: list[str] = []
    for key in names:
        parts += comp[key]
    if extra_components:
        parts += comp["extra_ta_in"]["list"]
    for part in sorted(set(parts) - keep, key=len, reverse=True):
        head, tail = part[0], re.escape(part[1:])
        cls = f"[{head.upper()}{head}]"
        rules.append(wt.Rule(
            f"§35 {part}-",
            rf"(?<![{UA_LETTER}])({cls}{tail})-(?=[{UA_LOWER}])"
            rf"(?!{cls}{tail})",
            r"\1"))

    piv = data["piv"]
    solid = sorted(piv["solid_words"]["list"], key=len, reverse=True)
    rules.append(wt.Rule("§36 пів-Власна -> пів Власна",
                         rf"(?<![{UA_LETTER}])([Пп]ів)-(?=[{UA_UPPER}])",
                         r"\1 "))
    rules.append(wt.Rule("§36 пів-острів -> півострів",
                         rf"(?<![{UA_LETTER}])([Пп]ів)-({'|'.join(solid)})"
                         rf"(?![{UA_LOWER}])",
                         r"\1\2"))
    rules.append(wt.Rule("§36 пів-слово -> пів слово",
                         rf"(?<![{UA_LETTER}])([Пп]ів)-(?=[{UA_LOWER}])",
                         r"\1 "))
    if piv_solid:
        for word in sorted(piv["split_solid"]["list"], key=len, reverse=True):
            rules.append(wt.Rule(f"§36 пів{word} -> пів {word}",
                                 rf"(?<![{UA_LETTER}])([Пп]ів){word}\b",
                                 rf"\1 {word}"))
    return rules


def build_rules(pravopys: bool = True, typos: bool = True,
                extra_components: bool = False, piv_solid: bool = False):
    """The whole rule set of one pass: правопис-2019 plus the typo list."""
    rules = []
    if pravopys:
        rules += build_pravopys_rules(load_data(), extra_components, piv_solid)
    if typos:
        rules += wt.load_typos(TYPOS_PATH, warn=False)
    return rules


def make_summary(changes) -> str:
    """The edit summary in Ukrainian, from what the edit actually contains."""
    return wt.make_summary(changes, SUMMARY_PARTS, conj=SUMMARY_CONJ)

SELF_TEST = [
    # (что подаём, что должно получиться, пояснение)
    ("Це проект нової редакції.", "Це проєкт нової редакції.", "§126"),
    ("Спроектували проекцію.", "Спроєктували проєкцію.", "§126 всередині"),
    ("Зайшов у фойє.", "Зайшов у фоє.", "§126 фоє"),
    ("Новий веб-сайт і прес-конференція.",
     "Новий вебсайт і пресконференція.", "§35 разом"),
    ("екс-міністр і віце-прем'єр", "ексміністр і віцепрем'єр", "§35 екс/віце"),
    ("екс-Югославія, веб-API, топ-10",
     "екс-Югославія, веб-API, топ-10", "§35 винятки: дефіс лишається"),
    ("напів-автомат", "напівавтомат", "§35 п.7"),
    ("Проїхав пів-Києва.", "Проїхав пів Києва.", "§36 власна назва"),
    ("З'їв пів-яблука.", "З'їв пів яблука.", "§36 окремо"),
    ("Це пів-острів.", "Це півострів.", "§36 лексикалізоване"),
    ("Це масштабна организація.", "Це масштабна організація.", "typos.txt"),
    ("Наступний слідуючий крок.", "Наступний наступний крок.", "typos.txt"),
    # --- защита ---
    ("[[Категорія:Проект Х]]", "[[Категорія:Проект Х]]", "категорія"),
    ("[[Файл:Веб-сайт проект.jpg|міні|Це проект]]",
     "[[Файл:Веб-сайт проект.jpg|міні|Це проект]]", "файл"),
    ("[[Проект Аполлон]] — це проект.",
     "[[Проект Аполлон]] — це проєкт.", "ціль посилання"),
    ("[[Проект|цей проект]] діє.", "[[Проект|цей проект]] діє.",
     "посилання цілком (за замовчуванням)"),
    ("{{Проект-стаб|тип=проект}}", "{{Проект-стаб|тип=проєкт}}",
     "ім'я шаблону лишається, значення правиться"),
    ("{{Картка|зображення=Веб-сайт проект.jpg|опис=веб-сайт}}",
     "{{Картка|зображення=Веб-сайт проект.jpg|опис=вебсайт}}",
     "linkish-параметр"),
    ("{{Головна|Проект Аполлон}}", "{{Головна|Проект Аполлон}}",
     "позиційний параметр"),
    ("Див. [https://example.com/проект Проект тут].",
     "Див. [https://example.com/проект Проект тут].", "зовнішнє посилання"),
    ("URL https://ex.com/веб-сайт кінець.",
     "URL https://ex.com/веб-сайт кінець.", "голий URL"),
    ("<nowiki>проект веб-сайт</nowiki>", "<nowiki>проект веб-сайт</nowiki>",
     "nowiki"),
    ("<!-- проект веб-сайт -->", "<!-- проект веб-сайт -->", "коментар"),
    ("<gallery>Проект.jpg|веб-сайт</gallery>",
     "<gallery>Проект.jpg|веб-сайт</gallery>", "gallery"),
    ('<div class="веб-сайт">проект</div>',
     '<div class="веб-сайт">проєкт</div>', "атрибут тега"),
    ('{| class="wikitable"\n|-\n| проект\n|}',
     '{| class="wikitable"\n|-\n| проєкт\n|}', "таблиця"),
    # Реальний випадок зі статті «Нью-Йорк»: назва джерела — цитата,
    # її не можна «виправляти», інакше посилання перестане відповідати
    # виданню, на яке посилаються.
    ("{{УЗЕ|том=2|сторінки=888|стаття=Ню Йорк}}",
     "{{УЗЕ|том=2|сторінки=888|стаття=Ню Йорк}}", "назва джерела"),
    ("{{Cite book|title=Проект веб-сайт|author=Ню Йорк}}",
     "{{Cite book|title=Проект веб-сайт|author=Ню Йорк}}", "бібліографія"),
    ("{{ТС_Буд|частина=Проект|сторінки =162}}",
     "{{ТС_Буд|частина=Проект|сторінки =162}}", "частина джерела"),
]

# Перевіряються окремо: результат залежить від прапорця.
SELF_TEST_FLAGS = [
    ("Застаріла назва — ''Ню Йорк''.", "Застаріла назва — ''Ню Йорк''.",
     "курсив із --skip-italics", {"skip_italics": True}),
    ("[[Проект|цей проект]] діє.", "[[Проект|цей проєкт]] діє.",
     "підпис із --fix-link-labels", {"fix_labels": True}),
    ("{{цитата|Це проект}}", "{{цитата|Це проєкт}}",
     "позиційний із --template-values all", {"template_values": "all"}),
    ("Підстановка {{{параметр|проект}}} у шаблоні.",
     "Підстановка {{{параметр|проект}}} у шаблоні.",
     "{{{параметр}}} навіть із --template-values all",
     {"template_values": "all"}),

    # --- косметика ---
    ("==Заголовок==", "== Заголовок ==", "косметика: заголовок",
     {"cosmetic": True}),
    ("===Підрозділ===", "=== Підрозділ ===", "косметика: рівень 3",
     {"cosmetic": True}),
    ("==  Вже з пробілами  ==", "== Вже з пробілами ==",
     "косметика: зайві пробіли в заголовку", {"cosmetic": True}),
    ("Текст   \nІнший\t\n", "Текст\nІнший\n",
     "косметика: пробіли в кінці рядка", {"cosmetic": True}),
    ("а\n\n\n\n\nб\n", "а\n\nб\n", "косметика: порожні рядки",
     {"cosmetic": True}),
    ("Слово , інше . Кінець !", "Слово, інше. Кінець!",
     "косметика: пробіл перед розділовим знаком", {"cosmetic": True}),
    ("Це - тире.", "Це — тире.", "косметика: дефіс -> тире",
     {"cosmetic": True}),
    ("  Одиночний відступ.\n", "Одиночний відступ.\n",
     "косметика: відступ знято", {"cosmetic": True}),
    (" код рядок 1\n код рядок 2\n", " код рядок 1\n код рядок 2\n",
     "косметика: блок з відступом — НЕ чіпаємо", {"cosmetic": True}),
    ("<pre>\n  відступ\n  ще\n</pre>\n", "<pre>\n  відступ\n  ще\n</pre>\n",
     "косметика: <pre> недоторканий", {"cosmetic": True}),
    ("Рядок\nа , б\n", "Рядок\nа, б\n",
     "косметика: кома не склеює рядки", {"cosmetic": True}),
    ("[[Файл:А.jpg|thumb|Підпис , з комою]]",
     "[[Файл:А.jpg|thumb|Підпис , з комою]]",
     "косметика: всередині посилання не чіпаємо", {"cosmetic": True}),
    ("{| class=\"wikitable\"\n|-\n| а - б\n|}",
     "{| class=\"wikitable\"\n|-\n| а — б\n|}",
     "косметика: тире в комірці таблиці", {"cosmetic": True}),
    ("Слово  інше", "Слово інше", "косметика: подвійний пробіл",
     {"cosmetic": True}),
    ("<pre>\nа  б\n</pre>", "<pre>\nа  б\n</pre>",
     "косметика: пробіли в <pre> значимі", {"cosmetic": True}),

    # --- назви в лапках (реальні випадки з telepedia) ---
    ("Ток-шоу «Прес-клуб» виходило щотижня.",
     "Ток-шоу «Прес-клуб» виходило щотижня.",
     "«Прес-клуб» — назва передачі", {"skip_quotes": True}),
    ("Рубрики «Поп-музика», «Інді-музика», «Хард-рок».",
     "Рубрики «Поп-музика», «Інді-музика», «Хард-рок».",
     "назви рубрик у лапках", {"skip_quotes": True}),
    ("Гурт \"Кібер-партизани\" зламав ефір.",
     "Гурт \"Кібер-партизани\" зламав ефір.",
     "назва гурту в прямих лапках", {"skip_quotes": True}),
    ("Це міні-серіал, а не «міні-серіал».",
     "Це мінісеріал, а не «міні-серіал».",
     "поза лапками правимо, в лапках — ні", {"skip_quotes": True}),
]

# Удвоение основы — § 35, п. 6, підп. 1: дефис сохраняется.
# Реальные случаи с theloudhouse (кличка діда Поп-Поп).
SELF_TEST += [
    ("Поп-Поп прийшов.", "Поп-Поп прийшов.", "§35 повтор: Поп-Поп"),
    ("Відмовити Поп-попа від нападу.", "Відмовити Поп-попа від нападу.",
     "§35 повтор у непрямому відмінку"),
    ("Кілт належав поп-попу.", "Кілт належав поп-попу.",
     "§35 повтор з малої літери"),
    ("Команда Поп-поп прибула.", "Команда Поп-поп прибула.",
     "§35 повтор: Поп-поп"),
    # ...но обычные составные части по-прежнему склеиваются
    ("Слухає поп-музику.", "Слухає попмузику.", "§35 поп- працює як раніше"),
    ("Це поп-гурт.", "Це попгурт.", "§35 поп-гурт -> попгурт"),
]


# (текст, ожидаемое описание правки) — описание собирается по факту правок.
SUMMARY_TEST = [
    ("==Розділ==", SUMMARY_COSMETIC, "лише косметика"),
    ("Слово , інше", SUMMARY_COSMETIC, "лише косметика (пунктуація)"),
    ("Це проект.", SUMMARY_LANG, "лише правопис"),
    ("Масштабна организація.", SUMMARY_LANG, "лише опечатка"),
    ("==Проект==", SUMMARY_BOTH, "заголовок + правопис"),
    ("Це проект , ага.", SUMMARY_BOTH, "правопис + пунктуація"),
]


def self_test(rules=None):
    """Run every rule's own tests. -> the list of failures, empty when sound.

    The original printed this to the console and the wrapper script refused to
    start on a failure. Here the task runner calls it before the first edit of
    a pass.

    Each case is checked twice — the second pass must change nothing, or the
    bot would edit the same page for ever. SELF_TEST_FLAGS carries a fourth
    element: the flags that case depends on.
    """
    if rules is None:
        rules = build_rules()
    failures = []

    for case in SELF_TEST + SELF_TEST_FLAGS:
        src, want, why = case[0], case[1], case[2]
        kwargs = case[3] if len(case) > 3 else {}
        got, _ = wt.process_text(src, rules, **kwargs)
        again, _ = wt.process_text(got, rules, **kwargs)
        if got != want:
            failures.append("правопис [%s]: вхід %r, треба %r, маємо %r"
                            % (why, src, want, got))
        elif again != got:
            failures.append("правопис [%s]: неідемпотентно, %r -> %r"
                            % (why, got, again))

    for src, want, why in SUMMARY_TEST:
        _text, changes = wt.process_text(src, rules, skip_italics=True,
                                         skip_quotes=True, cosmetic=True)
        got = make_summary(changes)
        if got != want:
            failures.append("опис [%s]: треба «%s», маємо «%s»"
                            % (why, want, got))

    return failures


FLAG_COSMETIC = "cosmetic"
FLAG_NO_TYPOS = "no_typos"
FLAG_EXTRA = "extra_components"
FLAG_PIV_SOLID = "piv_solid"
FLAG_LABELS = "labels"
FLAG_SKIP_REFS = "skip_refs"


def prepare(ctx):
    """Build the Ukrainian rule set, and check it before the first edit."""
    flags = set(ctx.params.get("pravopys_uk_flags") or [])
    rules = build_rules(typos=FLAG_NO_TYPOS not in flags,
                        extra_components=FLAG_EXTRA in flags,
                        piv_solid=FLAG_PIV_SOLID in flags)
    failures = self_test(rules)
    if failures:
        raise ValueError("самоперевірка правил не пройшла:\n" + "\n".join(failures[:5]))
    return {"rules": rules,
            "opts": wt.Options(cosmetic=FLAG_COSMETIC in flags,
                               fix_labels=FLAG_LABELS in flags,
                               skip_refs=FLAG_SKIP_REFS in flags)}


def apply(ctx, page, text):
    """One page's text brought to правопис-2019. -> (text, change names)."""
    state = ctx.state.get(SPEC.code) or {}
    new, changes = wt.process_text(text, state["rules"], **state["opts"].kwargs())
    if new == text:
        return text, []
    return new, [name for name, _was, _now in changes]


def summary_part(ctx, labels):
    """The summary this run earned, in Ukrainian and by what it did."""
    if not labels:
        return None
    return make_summary([(name, "", "") for name in labels])


SPEC = mech.Mechanic(
    code="pravopys-uk",
    kind=mech.TEXT,
    module=sys.modules[__name__],
    rights=("edit",),
    params=(
        Param("pravopys_uk_flags", FLAGS, "param_pravopys_uk_flags", options=(
            (FLAG_COSMETIC, "flag_cosmetic"),
            (FLAG_NO_TYPOS, "flag_no_typos"),
            (FLAG_EXTRA, "flag_extra_components"),
            (FLAG_PIV_SOLID, "flag_piv_solid"),
            (FLAG_LABELS, "flag_fix_labels"),
            (FLAG_SKIP_REFS, "flag_skip_refs"),
        )),
    ),
)
