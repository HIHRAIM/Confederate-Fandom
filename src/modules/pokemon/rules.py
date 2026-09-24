"""Правила из выгрузки [[Модуль:PokemonData/fromNumber]] и точки входа замены.

Портировано из pokemon-bot/scripts/fromnumber_rules.py без изменений в логике.
Читает data/fromnumber_name_rules.tsv (270 пар: old, new, ndex, en, first,
last, revs) и строит из них правила поверх движка из names.py.

Публичное: `fix_text(text)` возвращает (новый текст, [(было, стало)],
[непонятные формы]); `fix_title(title)`; `find_derived(text)` — слова, которые
правило намеренно не тронуло; `load_pairs`, `build_rules`.

Что разрешено дописывать к названию. Менять название внутри более длинного
слова можно только если к нему прибавлено падежное окончание или «-ит»
(мегакамень: «Скизорит» → «Сизорит»). Всё остальное — самостоятельные слова:
«Глайгермен» (супергерой из аниме), «глайгердевушка», «Троупринт»,
«Снизлер», «Брианна» — их правило не трогает, а `find_derived` показывает в
отчёте. Условие «хвост не является разрешённым окончанием» записано так,
чтобы годиться для поля `block`, которое ищется по хвосту: пустой хвост под
него не подходит, а значит именительный падеж не блокируется никогда.

Ручные оговорки (EXTRA) — случаи, где старое название попадает в постороннее
слово или где склонение меняется:

* «Снизлер» (Sneasler, #903) и «Троупринт» (покемон фанатской игры Pokémon
  Uranium) — действующие названия, их трогать нельзя.
* **Силвалл → Силвалли** — склоняемое становится несклоняемым, как
  «Драгалдж» → «Драгалджи»: все падежи сходятся в «Силвалли». Без таблицы
  вышло бы «Силвалла» → «Силваллиа».
* **Фион → Фиона** — мужской род становится женским, окончания меняются;
  прямой перенос дал бы «Фионе» → «Фионае». Именно так в статьях и появились
  «Фионае» и «Фионаы» — эта таблица их не трогает, они попадают в список
  непонятных форм для ручной правки.

Заголовки со словом Pixelmon не переименовываются (это мод Minecraft со
своими названиями), поэтому и ссылки на них защищены. Защита разметки здесь
шире, чем в names.py: к ней добавлены категории (переименовывать их не
входит в задачу), японская транслитерация |jtranslit=/|jname=/|tmname=,
значение параметра — имя файла с пробелами (|изображение = Вайплюм
Валенсия.png) и строка «имя файла с пробелами | подпись» вне тега <gallery>.

Замена идемпотентна: повторный прогон по всему ns0 ничего не меняет. PREFILTER
строится по ОСНОВАМ правил, а не по названиям из TSV — у «Тентакруэль» основа
«Тентакруэл», иначе страница с одним «Тентакруэлем» не нашлась бы. Новое
название, начинающееся со старого, правилом не трогается.
"""

from __future__ import annotations

import os
import re

from modules.pokemon.names import PHRASE_FIXES, WORD_FIXES, PhraseRule, Rule

TSV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "data", "fromnumber_name_rules.tsv")

EXTRA: dict[str, dict] = {
    "Снизл": {"block": r"^ер"},
    "Троу": {"block": r"^принт"},
    "Силвалл": {"stem": "Силвалл", "nstem": "Силвалли",
                "suffix": {"": "", "а": "", "у": "", "ом": "", "е": "",
                           "и": "", "ы": "", "ов": "", "ам": "", "ами": "",
                           "ах": ""}},
    "Фион": {"stem": "Фион", "nstem": "Фион",
             "suffix": {"": "а", "а": "а", "ы": "ы", "у": "у", "е": "е",
                        "ой": "ой", "ом": "ой", "ов": "", "ам": "ам",
                        "ами": "ами", "ах": "ах"}},
}

PIXELMON_RE = re.compile(r"Pixelmon", re.I)

CASE_ENDINGS = ("", "а", "я", "у", "ю", "ом", "ем", "ём", "е", "и", "ы", "ь",
                "ей", "ов", "ев", "ам", "ям", "ами", "ями", "ах", "ях", "ой")
STONE = "ит"                                   # мегакамень: …ит, …ита, …итом
ALLOWED_TAILS = frozenset(CASE_ENDINGS) | {STONE + e for e in CASE_ENDINGS}

TAIL_BLOCK = ("^(?!(?:"
              + "|".join(sorted((t for t in ALLOWED_TAILS if t),
                                key=len, reverse=True))
              + ")$).")

MEDIA_EXT = (r"png|jpe?g|gif|svg|webp|ogg|oga|ogv|webm|mp3|mp4|wav|pdf"
             r"|tif|tiff|bmp")

GALLERY_RE = re.compile(r"(<gallery[^>]*>)(.*?)(</gallery\s*>)", re.S | re.I)

PROTECT_RES = [
    re.compile(r"<(nowiki|pre|syntaxhighlight|source|code)\b[^>]*>.*?</\1\s*>",
               re.S | re.I),
    re.compile(r"<(nowiki|pre)\s*/>", re.I),
    re.compile(r"(?:https?:)?//[^\s\]|<>{}\"']+", re.I),
    re.compile(r"\[\[\s*:?\s*[^\]|]*Pixelmon[^\]|]*", re.I),
    re.compile(r"\[\[\s*:?\s*(?:Файл|File|Изображение|Image|Медиа|Media)\s*:"
               r"[^\]|]*", re.I),
    re.compile(r"\[\[\s*:?\s*(?:Категория|Category)\s*:[^\]|]*", re.I),
    re.compile(r"\[\[\s*:?\s*(?:Special|Служебная)\s*:[^\]|]*", re.I),
    re.compile(r"\[\[\s*(?::)?\s*[a-z][a-z-]{1,11}\s*:[^\]]*\]\]", re.I),
    re.compile(r"\|\s*(?:jtranslit|jname|jname2|tmname|romaji|translit)\s*="
               r"[^|\n}]*", re.I),
    re.compile(r"[=|][^=|\[\]{}<>\n]*?\.(?:" + MEDIA_EXT + r")\b", re.I),
    re.compile(r"^[^=|\[\]{}<>\n]*?\.(?:" + MEDIA_EXT + r")(?=\s*\|)",
               re.I | re.M),
    re.compile(r"[^\s|=\[\]{}<>\n]+\.(?:" + MEDIA_EXT + r")\b", re.I),
]

_PLACEHOLDER = "\x00{}\x00"
_PLACEHOLDER_RE = re.compile(r"\x00(\d+)\x00")

def protect(text: str) -> tuple[str, list[str]]:
    """Прячет защищённые куски за плейсхолдеры ``\\x00N\\x00``."""
    saved: list[str] = []

    def stash(s: str) -> str:
        saved.append(s)
        return _PLACEHOLDER.format(len(saved) - 1)

    def gallery(m: re.Match) -> str:
        """В галерее имя файла — всё до первой «|», тега «Файл:» может не быть."""
        lines = []
        for line in m.group(2).split("\n"):
            name, sep, rest = line.partition("|")
            lines.append(stash(name) + sep + rest if name.strip() else line)
        return m.group(1) + "\n".join(lines) + m.group(3)

    text = GALLERY_RE.sub(gallery, text)
    for rx in PROTECT_RES:
        text = rx.sub(lambda m: stash(m.group(0)), text)
    return text, saved

def unprotect(text: str, saved: list[str]) -> str:
    """Restore enclosing masks first, including a gallery inside nowiki."""
    for index in range(len(saved) - 1, -1, -1):
        text = text.replace(_PLACEHOLDER.format(index), saved[index])
    return text

def load_pairs(path: str = TSV_PATH) -> list[tuple[str, str]]:
    """Читает пары замен из TSV. -> [(старое, новое)].

    Отсутствующий файл — это ошибка, а не повод завершить процесс: в
    оригинальном скрипте здесь стоял ``sys.exit``, который внутри бота увёл
    бы за собой весь процесс. Бросаем исключение, его ловит задача.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(
            "нет списка замен {} — он должен лежать рядом с модулем".format(path))
    pairs = []
    with open(path, encoding="utf-8") as fh:
        next(fh)                                    # заголовок
        for line in fh:
            if line.strip():
                old, new = line.rstrip("\n").split("\t")[:2]
                pairs.append((old, new))
    return pairs

def build_rules(pairs: list[tuple[str, str]] | None = None) -> list:
    """Пары -> правила. Словосочетания идут первыми, дальше — длинные основы."""
    pairs = load_pairs() if pairs is None else pairs
    manual = {spec["old"]: spec for spec in WORD_FIXES}

    phrases: list = []
    words: list = []
    for old, new in pairs:
        if " " in old:
            table = next((t for t in PHRASE_FIXES.values()
                          if t.get(old) == new), None)
            phrases.append(PhraseRule(old, table or {old: new}))
            continue

        spec = {"old": old, "new": new}
        base = manual.get(old)
        if base and base["new"] == new:
            spec.update({k: v for k, v in base.items()
                         if k in ("stem", "nstem", "suffix", "block")})
        spec.update(EXTRA.get(old, {}))
        if "suffix" not in spec:
            blocks = [TAIL_BLOCK]
            if spec.get("block"):
                blocks.append(spec["block"])
            if len(new) > len(old) and new.lower().startswith(old.lower()):
                blocks.append("^" + re.escape(new[len(old):].lower()))
            spec["block"] = "|".join(f"(?:{b})" for b in blocks)
        words.append(Rule(spec))

    words.sort(key=lambda r: len(r.stem), reverse=True)
    return phrases + words

def build_prefilter(rules: list | None = None):
    """Одна регулярка «встречается ли тут хоть одно старое название».

    Правил под три сотни, а задевают они меньше 5 % страниц. Один общий поиск
    отсекает остальные страницы сразу, вместо 270 проходов по тексту.

    Искать надо именно ОСНОВЫ правил, а не названия из TSV: у «Тентакруэль»
    основа «Тентакруэл», и страница, где стоит только «Тентакруэлем», по
    самому названию не нашлась бы.
    """
    rules = RULES if rules is None else rules
    alts: set[str] = set()
    for rule in rules:
        table = getattr(rule, "table", None)
        alts.update(table if table else [rule.stem])
    return re.compile("(?<![а-яёА-ЯЁa-zA-Z])(?:"
                      + "|".join(re.escape(a)
                                 for a in sorted(alts, key=len, reverse=True))
                      + ")", re.IGNORECASE)

RULES = build_rules()
PREFILTER = build_prefilter(RULES)

_DERIVED_NEW = {r.stem.lower(): r.nstem for r in RULES
                if getattr(r, "suffix", None) is None and hasattr(r, "stem")}
DERIVED_RE = re.compile(
    "(?<![а-яёА-ЯЁa-zA-Z])("
    + "|".join(re.escape(s) for s in sorted(_DERIVED_NEW, key=len,
                                            reverse=True))
    + ")([а-яёА-ЯЁ]+)", re.IGNORECASE)

def find_derived(text: str) -> list[str]:
    """Производные слова, которые правила намеренно оставили как есть.

    «Глайгермен» от Глайгера, «Троупринт» от Троу. Имена файлов и прочее
    защищённое сюда не попадают. Уже правильные формы — тоже: «Джамплафф»
    начинается с устаревшего «Джамплаф», но это не производное слово, а то,
    что мы и хотим видеть.
    """
    text, _ = protect(text)
    out = []
    for m in DERIVED_RE.finditer(text):
        word, stem, tail = m.group(0), m.group(1), m.group(2)
        if tail.lower() in ALLOWED_TAILS:
            continue
        new = _DERIVED_NEW[stem.lower()].lower()
        if (word.lower().startswith(new)
                and word.lower()[len(new):] in ALLOWED_TAILS):
            continue
        out.append(word)
    return out

def fix_text(text: str, rules: list | None = None,
             guard: bool = True) -> tuple[str, list, list]:
    """Заменяет названия в вики-тексте.

    -> (новый текст, [(было, стало)], [непонятные падежные формы])
    """
    if rules is None and not PREFILTER.search(text):
        return text, [], []
    rules = RULES if rules is None else rules
    saved: list[str] = []
    if guard:
        text, saved = protect(text)
    changes: list[tuple[str, str]] = []
    unknown: list[str] = []
    for rule in rules:
        text, ch, unk = rule.apply(text)
        changes += ch
        unknown += unk
    if guard:
        text = unprotect(text, saved)
    return text, changes, unknown

def fix_title(title: str, rules: list | None = None) -> str:
    """Новый заголовок страницы (в заголовке защищать нечего)."""
    return fix_text(title, rules, guard=False)[0]
