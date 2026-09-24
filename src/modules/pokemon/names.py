"""Правила замены устаревших русских названий покемонов и движок замены.

Портировано из pokemon-bot/scripts/poke_name_rules.py без изменений в логике;
пояснения, которые там жили в `#`-комментариях, собраны здесь и в ключах
"note" отдельных правил, потому что clean_code.py комментарии удаляет.

Три требования и как они выполнены:

1. **Регистр сохраняется.** Совпадение ищется без учёта регистра, а регистр
   исходного текста переносится на замену пословно: «Вайплюм» → «Вайлплюм»,
   «вайплюм» → «вайлплюм», «ВАЙПЛЮМ» → «ВАЙЛПЛЮМ».
2. **Название ловится и как корень другого слова.** Ищется ОСНОВА, а всё, что
   идёт за ней кириллицей, сохраняется: «вайплюмский» → «вайлплюмский»,
   «Хаундуминит» → «Хандуминит». Склонения перечислять не нужно.
3. **Имена файлов не трогаются.** Перед заменой они — вместе со ссылками
   [[Файл:…]], URL, интервики, <nowiki>/<pre> — прячутся за плейсхолдеры
   (`protect`), а после возвращаются на место (`unprotect`).

Поля правила в WORD_FIXES: `old` — как в статьях сейчас (именительный падеж),
`new` — как должно быть, `stem`/`nstem` — основа для поиска и для замены (по
умолчанию равны old/new), `suffix` — явная таблица окончаний, включающая
строгий режим, `block` — регулярка по хвосту: совпало, значит вхождение
пропускается. `note` ничего не делает, это перенесённое пояснение.

Особые случаи, каждый со своей причиной:

* **Тентакруэль → Тентакрул** и **Криогональ → Криогонал** — мягкая основа
  становится твёрдой, поэтому окончания заданы таблицей: «Тентакруэлем» →
  «Тентакрулом», «Тентакруэлей» → «Тентакрулов». У Криогонали заблокирован
  хвост «-ьн»: «Криогональный человек» — прилагательное, оно и от новой
  основы образуется так же.
* **Драгалдж → Драгалджи** — склоняемое становится несклоняемым, все падежи
  сходятся в одну форму. Пустой суффикс у новой основы делает правило
  идемпотентным: «Драгалджи» снова даёт «Драгалджи», а не «Драгалджии».
* **Бриан → Брионн** с блокировкой хвоста «^н»: «леди Брианна» — тренер, а не
  Brionne.
* **Десидьюай → Десиджуай** ищется по основе без «й», иначе не поймать
  «Десидьюая».

Словосочетания (PHRASE_FIXES) меняют род — «Железная Корона» → «Железный
Вождь», — поэтому основу переносить нельзя и у каждого задана полная падежная
таблица: Gouging Fire (муж. «Огонь» → ср. «Пламя»), Raging Bolt (муж. «Болт» →
жен. «Молния»), Iron Crown (жен. «Корона» → муж. одуш. «Вождь»). Регистр
восстанавливается пословно, так что «Яростный болт» в тексте статьи даст
«Яростная молния». Длинные формы проверяются раньше коротких — иначе
«Яростный Болт» съел бы начало «Яростные Болты».

PROTECT_RES перечисляет то, что править нельзя: <nowiki>/<pre>/<code>
целиком, URL, цель ссылки на файл ([[Файл:… и [[:Файл:… до | или ]]),
Special:FilePath, интервики ([[en:…]], [[uk:…]], [[wikipedia:ru:…]]) и голое
имя файла с расширением — оно встречается в галереях и в значениях параметров
шаблонов.
"""

from __future__ import annotations

import re

CYR = "а-яёА-ЯЁ"
CYR_RE = re.compile(f"[{CYR}]")

WORD_FIXES: list[dict] = [
    {"old": "Вайплюм", "new": "Вайлплюм"},
    {"note": "мягкая основа -> твёрдая: окончания меняются",
     "old": "Тентакруэль", "new": "Тентакрул",
     "stem": "Тентакруэл", "nstem": "Тентакрул",
     "suffix": {"": "", "ь": "", "я": "а", "ю": "у", "ем": "ом", "ём": "ом",
                "е": "е", "и": "ы", "ей": "ов", "ям": "ам", "ями": "ами",
                "ях": "ах", "ь-": "-"}},
    {"old": "Электривайр", "new": "Элективайр"},
    {"old": "Конкельдар", "new": "Конкельдурр"},
    {"old": "Флетчлиндер", "new": "Флетчиндер"},
    {"old": "Фурфу", "new": "Фурфру"},
    {"note": "склоняемое -> несклоняемое: все падежи сходятся в одну форму",
     "old": "Драгалдж", "new": "Драгалджи",
     "stem": "Драгалдж", "nstem": "Драгалджи",
     "suffix": {"": "", "а": "", "у": "", "ем": "", "ом": "", "е": "",
                "и": "", "ей": "", "ами": "", "ах": ""}},
    {"note": "«леди Брианна» — тренер, не Brionne", "old": "Бриан", "new": "Брионн", "block": r"^н"},
    {"old": "Полчегейст", "new": "Полчагейст"},
    {"old": "Архалудон", "new": "Архалюдон"},
    {"old": "Гидрэпл", "new": "Гидраппл"},
    {"old": "Найнтейлз", "new": "Найнтэйлс"},
    {"old": "Блэйзикен", "new": "Блейзикен"},
    {"old": "Хаундум", "new": "Хандум"},
    {"old": "Форетресс", "new": "Форретресс"},
    {"old": "Мэнтайн", "new": "Мантайн"},
    {"note": "мягкая основа -> твёрдая; «Криогональный человек» не трогаем",
     "old": "Криогональ", "new": "Криогонал",
     "stem": "Криогонал", "nstem": "Криогонал",
     "suffix": {"": "", "ь": "", "а": "а", "у": "у", "ом": "ом", "е": "е",
                "ы": "ы", "ов": "ов", "ам": "ам", "ах": "ах", "ами": "ами"},
     "block": r"^ьн"},
    {"old": "Ксюркитри", "new": "Заркитри"},
    {"old": "Спритзи", "new": "Спритци"},
    {"old": "Стонжорнер", "new": "Стонджорнер"},
    {"note": "основа без «й», иначе не поймать «Десидьюая»",
     "old": "Десидьюай", "new": "Десиджуай",
     "stem": "Десидьюа", "nstem": "Десиджуа"},
    {"old": "Клавитзер", "new": "Кловитцер"},
    {"old": "Тартонейтор", "new": "Тартонэйтор"},
    {"old": "Мадсбрэй", "new": "Мадбрей",
     "stem": "Мадсбрэ", "nstem": "Мадбре"},
    {"old": "Минчино", "new": "Минччино"},
    {"old": "Скидду", "new": "Скиддо"},
    {"old": "Глэйли", "new": "Глейли"},
    {"old": "Вейлмер", "new": "Вэйлмер"},
    {"old": "Хандаур", "new": "Хандор"},
]

PHRASE_FIXES: dict[str, dict[str, str]] = {
    "Выжигающий Огонь": {
        "Выжигающий Огонь": "Пронзающее Пламя",
        "Выжигающего Огня": "Пронзающего Пламени",
        "Выжигающему Огню": "Пронзающему Пламени",
        "Выжигающим Огнём": "Пронзающим Пламенем",
        "Выжигающим Огнем": "Пронзающим Пламенем",
        "Выжигающем Огне": "Пронзающем Пламени",
    },
    "Яростный Болт": {
        "Яростный Болт": "Яростная Молния",
        "Яростного Болта": "Яростной Молнии",
        "Яростному Болту": "Яростной Молнии",
        "Яростным Болтом": "Яростной Молнией",
        "Яростном Болте": "Яростной Молнии",
        "Яростные Болты": "Яростные Молнии",
        "Яростных Болтов": "Яростных Молний",
    },
    "Железная Корона": {
        "Железная Корона": "Железный Вождь",
        "Железной Короны": "Железного Вождя",
        "Железной Короне": "Железному Вождю",
        "Железную Корону": "Железного Вождя",
        "Железной Короной": "Железным Вождём",
        "Железные Короны": "Железные Вожди",
    },
}

_MEDIA_EXT = (r"png|jpe?g|gif|svg|webp|ogg|oga|ogv|webm|mp3|mp4|wav|pdf"
              r"|tif|tiff|bmp")

PROTECT_RES = [
    re.compile(r"<(nowiki|pre|syntaxhighlight|source|code)\b[^>]*>.*?</\1\s*>",
               re.S | re.I),
    re.compile(r"<(nowiki|pre)\s*/>", re.I),
    re.compile(r"(?:https?:)?//[^\s\]|<>{}\"']+", re.I),
    re.compile(r"\[\[\s*:?\s*(?:Файл|File|Изображение|Image|Медиа|Media)\s*:"
               r"[^\]|]*", re.I),
    re.compile(r"\[\[\s*:?\s*(?:Special|Служебная)\s*:[^\]|]*", re.I),
    re.compile(r"\[\[\s*(?::)?\s*[a-z][a-z-]{1,11}\s*:[^\]]*\]\]", re.I),
    re.compile(r"[^\s|=\[\]{}<>\n]+\.(?:" + _MEDIA_EXT + r")\b", re.I),
]

_PLACEHOLDER = "\x00{}\x00"
_PLACEHOLDER_RE = re.compile(r"\x00(\d+)\x00")

def protect(text: str) -> tuple[str, list[str]]:
    """Прячет защищённые куски за плейсхолдеры ``\\x00N\\x00``."""
    saved: list[str] = []

    def stash(m: re.Match) -> str:
        saved.append(m.group(0))
        return _PLACEHOLDER.format(len(saved) - 1)

    for rx in PROTECT_RES:
        text = rx.sub(stash, text)
    return text, saved

def unprotect(text: str, saved: list[str]) -> str:
    """Restore outer masks before the earlier masks that they may contain."""
    for index in range(len(saved) - 1, -1, -1):
        text = text.replace(_PLACEHOLDER.format(index), saved[index])
    return text

def apply_case(src: str, dst: str) -> str:
    """Регистр ``src`` -> строка ``dst`` (для одного слова)."""
    letters = [c for c in src if c.isalpha()]
    if not letters:
        return dst
    if len(letters) > 1 and all(c.isupper() for c in letters):
        return dst.upper()
    if all(c.islower() for c in letters):
        return dst.lower()
    if letters[0].isupper():
        return dst[:1].upper() + dst[1:]
    return dst[:1].lower() + dst[1:]

def apply_case_words(src: str, dst: str) -> str:
    """То же, но пословно: «Яростный болт» -> «Яростная молния»."""
    s_words, d_words = src.split(), dst.split()
    if len(s_words) != len(d_words):
        return apply_case(src, dst)
    return " ".join(apply_case(s, d) for s, d in zip(s_words, d_words))

class Rule:
    """Одно правило замены."""

    def __init__(self, spec: dict):
        self.old = spec["old"]
        self.new = spec["new"]
        self.stem = spec.get("stem", self.old)
        self.nstem = spec.get("nstem", self.new)
        self.suffix: dict[str, str] | None = spec.get("suffix")
        self.block = re.compile(spec["block"]) if spec.get("block") else None
        self.rx = re.compile(
            f"(?<![{CYR}a-zA-Z])({re.escape(self.stem)})([{CYR}]*)",
            re.IGNORECASE)

    def apply(self, text: str) -> tuple[str, list[tuple[str, str]],
                                        list[str]]:
        """-> (текст, [(было, стало)], [непонятные формы])."""
        changes: list[tuple[str, str]] = []
        unknown: list[str] = []

        def repl(m: re.Match) -> str:
            stem_src, tail = m.group(1), m.group(2)
            whole = stem_src + tail
            if self.block and self.block.search(tail.lower()):
                return whole
            if self.suffix is not None:
                new_tail = self.suffix.get(tail.lower())
                if new_tail is None:
                    unknown.append(whole)
                    return whole
                if tail[:1].isupper() or whole.isupper():
                    new_tail = new_tail.upper()
            else:
                new_tail = tail
            out = apply_case(stem_src, self.nstem) + new_tail
            if out != whole:
                changes.append((whole, out))
            return out

        return self.rx.sub(repl, text), changes, unknown

class PhraseRule:
    """Замена словосочетания по падежной таблице."""

    def __init__(self, old: str, table: dict[str, str]):
        self.old = old
        self.new = table[old]
        self.table = {k.lower(): v for k, v in table.items()}
        alts = sorted(table, key=len, reverse=True)
        self.rx = re.compile(
            f"(?<![{CYR}a-zA-Z])(" + "|".join(re.escape(a) for a in alts)
            + f")(?![{CYR}])", re.IGNORECASE)

    def apply(self, text: str) -> tuple[str, list[tuple[str, str]],
                                        list[str]]:
        changes: list[tuple[str, str]] = []

        def repl(m: re.Match) -> str:
            src = m.group(1)
            dst = self.table[src.lower()]
            out = apply_case_words(src, dst)
            if out != src:
                changes.append((src, out))
            return out

        return self.rx.sub(repl, text), changes, []

def build_rules() -> list:
    """Словосочетания идут первыми: они длиннее и конкретнее."""
    rules: list = [PhraseRule(old, tbl) for old, tbl in PHRASE_FIXES.items()]
    rules += [Rule(spec) for spec in WORD_FIXES]
    return rules

RULES = build_rules()

def fix_text(text: str, rules: list | None = None,
             guard_files: bool = True) -> tuple[str, list, list]:
    """Заменяет названия в вики-тексте.

    -> (новый текст, [(было, стало)], [непонятные формы])
    """
    rules = rules if rules is not None else RULES
    saved: list[str] = []
    if guard_files:
        text, saved = protect(text)
    changes: list[tuple[str, str]] = []
    unknown: list[str] = []
    for rule in rules:
        text, ch, unk = rule.apply(text)
        changes += ch
        unknown += unk
    if guard_files:
        text = unprotect(text, saved)
    return text, changes, unknown

def fix_title(title: str, rules: list | None = None) -> str:
    """Заголовок страницы: защита файлов не нужна, склонения сохраняются."""
    new, _, _ = fix_text(title, rules, guard_files=False)
    return new
