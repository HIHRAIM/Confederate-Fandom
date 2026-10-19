"""Phonetic keys of titles, so that one name written in two scripts can be found.

The interwiki table (scripts/interwiki_table.py) looks for the article of
another language version that has the same name, and the same name is
rarely the same string: «Сибуя», «Шибуя», «Сібуя», Shibuya, シブヤ and
しぶや are one place. Translating between every pair of writing systems
would be nine systems and seventy-two directions; instead every title is
turned into a **key** — a rough Latin skeleton of how it sounds — and keys
are compared.

**How a key is made.** A title is cut into runs of one script. Cyrillic is
spelt out letter by letter by the rules of the wiki's language (Russian,
Ukrainian, Belarusian, Bulgarian, Serbian); hiragana and katakana are
romanised by Hepburn; Hangul syllables by the Revised Romanization; Latin
text is read by the spelling rules of a language — the wiki's own, English,
and Japanese romaji, because names on Fandom are mostly English or Japanese
whatever the wiki. Each reading gives one variant, so a title has a small
set of keys, and two titles match when any two of their keys do.

Then every variant is folded the same way, and the folding is what makes
the Japanese systems agree. Polivanov's Russian spelling is Kunrei-shiki in
Cyrillic (си, ти, цу, дзи), Kovalenko's Ukrainian one is the same with і,
and Hepburn writes shi, chi, tsu, ji: so ``sh`` before i and ``ch`` before i
fold to ``s`` and ``t``, ``ts`` to ``t``, ``dz``/``dzh``/``zh``/``j`` to one
``j``, and before a, u, o the soft consonants keep their ``i`` (``сю`` and
``shu`` both give ``siu``). Doubled letters collapse, ``y`` is ``i``, ``w``
is ``v``. The rules are deliberately coarse — they find candidates for a
person to check, and the interwiki table never writes a link nobody has
looked at.

**What it cannot read.** Kanji and hanzi need a dictionary, and the readings
dictionaries that fit the bot's licence weigh tens of megabytes, which the
operator declined for one mechanic. A Japanese title in kanji therefore has
no key of its own; the table uses the page's DEFAULTSORT when it is written
in kana, which is how Japanese wikis usually sort their articles.

`self_test` is run by the mechanic before it reads anything, the way the
spelling mechanics test their rules: a fold that stopped bringing «Сибуя»
and Shibuya together would otherwise only show as an emptier table.
"""
import difflib
import re
import unicodedata

MIN_FUZZY = 6
"""Shortest key compared by similarity rather than only for equality. Two
five-letter keys that differ in one letter are already 90% alike — Kevin and
Kelvin — so a short key counts only when it is equal, and an equal short key
is itself reported for a person to check (scripts/interwiki_table.py):
«Эш» and «Ешь» fold to the same two letters."""

_CYR_RU = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "io",
    "ж": "zh", "з": "z", "и": "i", "й": "i", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ы": "i", "ь": "", "э": "e", "ю": "iu", "я": "ia",
}
_CYR_UK = dict(_CYR_RU, **{"г": "h", "ґ": "g", "є": "ie", "і": "i", "ї": "ii",
                           "'": "", "’": "", "ʼ": ""})
_CYR_BE = dict(_CYR_RU, **{"г": "h", "і": "i", "ў": "u", "'": "", "’": ""})
_CYR_BG = dict(_CYR_RU, **{"ъ": "a", "щ": "sht"})
_CYR_SR = dict(_CYR_RU, **{"ђ": "dj", "ј": "i", "љ": "li", "њ": "ni", "ћ": "ch",
                           "џ": "dzh"})

CYRILLIC_READINGS = {
    "ru": (_CYR_RU,),
    "uk": (_CYR_UK, dict(_CYR_UK, г="g")),
    "be": (_CYR_BE, dict(_CYR_BE, г="g")),
    "bg": (_CYR_BG,),
    "sr": (_CYR_SR,),
}
"""How the Cyrillic of each language is spelt out. Ukrainian and Belarusian
have two readings of «г»: their own h, which is what a Ukrainian name in
Latin letters carries (Hryhorii), and g, which is how the same name is
written in Russian (Григорий) — the two wikis are compared both ways. Any
other language's Cyrillic is read as Russian and as Ukrainian."""

_LATIN_RULES = {
    "en": (("tch", "ch"), ("ch", "ch"), ("sh", "sh"), ("ph", "f"), ("ck", "k"),
           ("qu", "kv"), ("x", "ks"), ("c(?=[eiy])", "s"), ("c", "k"),
           ("th", "t"), ("wh", "v"), ("ee", "i"), ("oo", "u"),
           ("(?<=[aeiouy])h(?![aeiouy])", "")),
    "ja": (("ou", "o"), ("oo", "o"), ("uu", "u"), ("n'", "n"),
           ("m(?=[bp])", "n")),
    "fr": (("eaux", "o"), ("eau", "o"), ("aux", "o"), ("au", "o"), ("ou", "u"),
           ("oi", "ua"), ("ai", "e"), ("ei", "e"), ("eu", "e"), ("tch", "ch"),
           ("ch", "sh"), ("qu", "k"), ("gu(?=[eiy])", "g"), ("g(?=[eiy])", "zh"),
           ("j", "zh"), ("gn", "ni"), ("ç", "s"), ("c(?=[eiy])", "s"),
           ("c", "k"), ("ph", "f"), ("th", "t"), ("h", "")),
    "de": (("tsch", "ch"), ("dsch", "dzh"), ("sch", "sh"), ("ch", "h"),
           ("ck", "k"), ("ph", "f"), ("th", "t"), ("qu", "kv"), ("ß", "ss"),
           ("ei", "ai"), ("ie", "i"), ("eu", "oi"), ("äu", "oi"), ("ä", "e"),
           ("ö", "e"), ("ü", "iu"), ("w", "v"), ("z", "ts"), ("j", "i")),
    "es": (("ch", "ch"), ("ll", "i"), ("ñ", "ni"), ("qu(?=[ei])", "k"),
           ("gu(?=[ei])", "g"), ("g(?=[ei])", "h"), ("j", "h"),
           ("c(?=[ei])", "s"), ("c", "k"), ("z", "s"), ("h", "")),
    "pl": (("szcz", "shch"), ("sz", "sh"), ("cz", "ch"), ("rz", "zh"),
           ("dż", "dzh"), ("dź", "dzh"), ("ch", "h"), ("ż", "zh"), ("ź", "zh"),
           ("ś", "sh"), ("ć", "ch"), ("w", "v"), ("c", "ts"), ("j", "i"),
           ("ł", "l"), ("ó", "u"), ("ą", "on"), ("ę", "en"), ("ń", "n")),
    "pt": (("tch", "ch"), ("nh", "ni"), ("lh", "li"), ("ch", "sh"), ("x", "sh"),
           ("ç", "s"), ("qu(?=[ei])", "k"), ("gu(?=[ei])", "g"),
           ("c(?=[eiy])", "s"), ("c", "k"), ("g(?=[eiy])", "zh"), ("j", "zh"),
           ("ão", "aun"), ("õe", "oin")),
    "it": (("sc(?=[ei])", "sh"), ("ch", "k"), ("c(?=[ei])", "ch"), ("c", "k"),
           ("gli", "li"), ("gn", "ni"), ("gh", "g"), ("g(?=[ei])", "dzh"),
           ("qu", "kv"), ("z", "ts"), ("h", "")),
    "sr": (("dž", "dzh"), ("lj", "li"), ("nj", "ni"), ("č", "ch"), ("ć", "ch"),
           ("đ", "dj"), ("š", "sh"), ("ž", "zh"), ("c", "ts"), ("j", "i")),
}
"""How Latin letters are read in each language, as (pattern, sound) pairs.

Each set is applied in **one pass** — at a given position the first pattern
that matches wins and its output is never read again — so «ch» read as
«sh» in French cannot then be caught by a rule for «sh». The order inside a
set is therefore longest and most specific first. The Ukrainian national
transliteration (zh, kh, ts, ch, shch, y for и, h for г) needs no set of
its own: the English reading and the folding already land where the
Ukrainian Cyrillic does."""

_LATIN_ALIASES = {"pt-br": "pt", "pt-pt": "pt", "sr-el": "sr", "sr-latn": "sr"}

def _compile(rules):
    """One alternation over a rule set, and the outputs by group number."""
    pattern = re.compile("|".join("({})".format(p) for p, _out in rules))
    return pattern, [out for _p, out in rules]

_LATIN = {lang: _compile(rules) for lang, rules in _LATIN_RULES.items()}

_FOLD = tuple((re.compile(p), out) for p, out in (
    (r"shch", "sh"), (r"tsch", "ch"), (r"sch", "sh"), (r"tch", "ch"),
    (r"dzh", "j"), (r"dz", "j"), (r"zh", "j"),
    (r"kh", "h"), (r"gh", "g"), (r"ph", "f"), (r"th", "t"), (r"ck", "k"),
    (r"x", "ks"), (r"q", "k"), (r"w", "v"), (r"y", "i"),
    (r"sh(?=[aou])", "si"), (r"sh", "s"),
    (r"ch(?=[aou])", "ti"), (r"ch", "t"),
    (r"j(?=[aou])", "ji"),
    (r"ts", "t"), (r"tz", "t"), (r"c", "k"),
    (r"\bie", "e"), (r"m(?=[bp])", "n"),
))
"""The folding every variant goes through, in order — see the module
docstring for why each step is there."""

_SPECIAL = {"ß": "ss", "æ": "ae", "œ": "oe", "ø": "o", "đ": "d", "ł": "l",
            "ı": "i", "þ": "t", "ð": "d"}

_HIRAGANA = {
    "あ": "a", "い": "i", "う": "u", "え": "e", "お": "o",
    "か": "ka", "き": "ki", "く": "ku", "け": "ke", "こ": "ko",
    "が": "ga", "ぎ": "gi", "ぐ": "gu", "げ": "ge", "ご": "go",
    "さ": "sa", "し": "shi", "す": "su", "せ": "se", "そ": "so",
    "ざ": "za", "じ": "ji", "ず": "zu", "ぜ": "ze", "ぞ": "zo",
    "た": "ta", "ち": "chi", "つ": "tsu", "て": "te", "と": "to",
    "だ": "da", "ぢ": "ji", "づ": "zu", "で": "de", "ど": "do",
    "な": "na", "に": "ni", "ぬ": "nu", "ね": "ne", "の": "no",
    "は": "ha", "ひ": "hi", "ふ": "fu", "へ": "he", "ほ": "ho",
    "ば": "ba", "び": "bi", "ぶ": "bu", "べ": "be", "ぼ": "bo",
    "ぱ": "pa", "ぴ": "pi", "ぷ": "pu", "ぺ": "pe", "ぽ": "po",
    "ま": "ma", "み": "mi", "む": "mu", "め": "me", "も": "mo",
    "や": "ya", "ゆ": "yu", "よ": "yo",
    "ら": "ra", "り": "ri", "る": "ru", "れ": "re", "ろ": "ro",
    "わ": "wa", "ゐ": "i", "ゑ": "e", "を": "o", "ん": "n", "ゔ": "vu",
    "ぁ": "a", "ぃ": "i", "ぅ": "u", "ぇ": "e", "ぉ": "o",
    "ゃ": "ya", "ゅ": "yu", "ょ": "yo", "ゎ": "wa", "ゕ": "ka", "ゖ": "ke",
}

_HIRAGANA_PAIRS = {
    "きゃ": "kya", "きゅ": "kyu", "きょ": "kyo", "ぎゃ": "gya", "ぎゅ": "gyu",
    "ぎょ": "gyo", "しゃ": "sha", "しゅ": "shu", "しょ": "sho", "しぇ": "she",
    "じゃ": "ja", "じゅ": "ju", "じょ": "jo", "じぇ": "je", "ちゃ": "cha",
    "ちゅ": "chu", "ちょ": "cho", "ちぇ": "che", "ぢゃ": "ja", "ぢゅ": "ju",
    "ぢょ": "jo", "にゃ": "nya", "にゅ": "nyu", "にょ": "nyo", "ひゃ": "hya",
    "ひゅ": "hyu", "ひょ": "hyo", "びゃ": "bya", "びゅ": "byu", "びょ": "byo",
    "ぴゃ": "pya", "ぴゅ": "pyu", "ぴょ": "pyo", "みゃ": "mya", "みゅ": "myu",
    "みょ": "myo", "りゃ": "rya", "りゅ": "ryu", "りょ": "ryo",
    "ふぁ": "fa", "ふぃ": "fi", "ふぇ": "fe", "ふぉ": "fo", "ふゅ": "fyu",
    "てぃ": "ti", "でぃ": "di", "とぅ": "tu", "どぅ": "du", "でゅ": "dyu",
    "うぃ": "wi", "うぇ": "we", "うぉ": "wo", "いぇ": "ye",
    "つぁ": "tsa", "つぃ": "tsi", "つぇ": "tse", "つぉ": "tso",
    "ゔぁ": "va", "ゔぃ": "vi", "ゔぇ": "ve", "ゔぉ": "vo",
    "くぁ": "kwa", "ぐぁ": "gwa",
}
"""Two-kana sounds, including the katakana-only ones of loanwords (ファ,
ティ, ウィ…), written here in hiragana: katakana is shifted to hiragana
before reading, so one table serves both."""

_RR_INITIAL = ("g", "kk", "n", "d", "tt", "r", "m", "b", "pp", "s", "ss", "",
               "j", "jj", "ch", "k", "t", "p", "h")
_RR_MEDIAL = ("a", "ae", "ya", "yae", "eo", "e", "yeo", "ye", "o", "wa", "wae",
              "oe", "yo", "u", "wo", "we", "wi", "yu", "eu", "ui", "i")
_RR_FINAL = ("", "k", "k", "k", "n", "n", "n", "t", "l", "k", "m", "l", "l",
             "l", "p", "l", "m", "p", "p", "t", "t", "ng", "t", "t", "k", "t",
             "p", "t")

def _is_kana(char):
    """Hiragana, katakana or the long-vowel mark."""
    return "ぁ" <= char <= "ヿ" and char not in "・"

def _is_han(char):
    """A CJK ideograph — kanji or hanzi, which cannot be read here."""
    code = ord(char)
    return (0x4E00 <= code <= 0x9FFF or 0x3400 <= code <= 0x4DBF
            or 0xF900 <= code <= 0xFAFF or 0x20000 <= code <= 0x2FA1F)

def has_han(text):
    """Whether a title holds characters this module cannot read."""
    return any(_is_han(char) for char in str(text or ""))

def is_kana(text):
    """Whether a text is kana alone, apart from spaces and punctuation — what a
    usable DEFAULTSORT reading looks like."""
    letters = [char for char in str(text or "") if char.isalpha()]
    return bool(letters) and all(_is_kana(char) for char in letters)

def kana_to_latin(text):
    """Kana -> Hepburn romaji. ッ and ー are dropped: the folding collapses the
    doubled consonant and the long vowel they stand for anyway."""
    plain = "".join(chr(ord(char) - 0x60) if "ァ" <= char <= "ヶ" else char
                    for char in text)
    plain = plain.replace("ヴ", "ゔ")
    out = []
    i = 0
    while i < len(plain):
        pair = plain[i:i + 2]
        if pair in _HIRAGANA_PAIRS:
            out.append(_HIRAGANA_PAIRS[pair])
            i += 2
            continue
        char = plain[i]
        if char in ("っ", "ー", "ー"):
            i += 1
            continue
        out.append(_HIRAGANA.get(char, " "))
        i += 1
    return "".join(out)

_VOICELESS = {"g": "k", "d": "t", "b": "p", "j": "ch"}
"""The word-initial consonants as McCune–Reischauer and the Russian (Kontsevich)
spelling hear them: 박 is Bak in the Revised Romanization and Pak, «Пак» in
both of the others."""

def hangul_to_latin(text, voiceless=False):
    """Hangul syllables -> the Revised Romanization, letter by letter, without
    the sound changes between syllables. `voiceless` writes the first
    consonant of each word as McCune–Reischauer does."""
    out = []
    first = True
    for char in text:
        code = ord(char) - 0xAC00
        if 0 <= code < 11172:
            initial = _RR_INITIAL[code // 588]
            if voiceless and first:
                initial = _VOICELESS.get(initial, initial)
            out.append(initial + _RR_MEDIAL[(code % 588) // 28]
                       + _RR_FINAL[code % 28])
            first = False
        else:
            out.append(" ")
            first = True
    return "".join(out)

def _script(char):
    """The script run a character belongs to."""
    if "Ѐ" <= char <= "ӿ" or char in "'’ʼ":
        return "cyr"
    if _is_kana(char):
        return "kana"
    if "가" <= char <= "힣":
        return "hangul"
    if _is_han(char):
        return "han"
    if char.isalpha():
        return "latin"
    if char.isdigit():
        return "digit"
    return "other"

def _runs(text):
    """The text cut into (script, run) pairs."""
    runs = []
    for char in text:
        kind = _script(char)
        if runs and runs[-1][0] == kind:
            runs[-1][1] += char
        else:
            runs.append([kind, char])
    return runs

def _read_latin(run, reading):
    """One Latin run by one language's spelling rules."""
    compiled = _LATIN.get(reading)
    if compiled is None:
        return run
    pattern, outputs = compiled

    def sound(match):
        """The sound of the first rule that matched here."""
        return outputs[match.lastindex - 1]

    return pattern.sub(sound, run)

def _fold(text):
    """The common folding of every variant -> the key itself."""
    text = "".join(_SPECIAL.get(char, char) for char in text)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    for pattern, out in _FOLD:
        text = pattern.sub(out, text)
    text = re.sub(r"[^a-z0-9]", "", text)
    return re.sub(r"(.)\1+", r"\1", text)

def _clean(title):
    """The title as it is read: compatibility forms folded, case folded, the
    disambiguation in brackets dropped (``Ash (anime)`` is about Ash)."""
    text = unicodedata.normalize("NFKC", str(title or ""))
    text = re.sub(r"\s*[(（][^)）]*[)）]", " ", text)
    return text.casefold().strip()

def keys(title, lang, reading=None):
    """Every key of one title on a wiki in `lang`. -> a set, empty when the
    title cannot be read (kanji, hanzi, or nothing but punctuation).

    `reading` is extra kana to read instead of the title — a Japanese page's
    DEFAULTSORT."""
    text = _clean(reading if reading else title)
    if not text or has_han(text):
        return set()
    lang = str(lang or "").lower()
    lang = _LATIN_ALIASES.get(lang, lang)
    latin_readings = ["en", "ja"]
    if lang in _LATIN and lang not in latin_readings:
        latin_readings.insert(0, lang)
    cyrillic = CYRILLIC_READINGS.get(lang) or (_CYR_RU, _CYR_UK)

    runs = _runs(text)
    if not any(kind in ("cyr", "kana", "hangul", "latin") for kind, _run in runs):
        return set()
    has_latin = any(kind == "latin" for kind, _run in runs)
    has_cyr = any(kind == "cyr" for kind, _run in runs)
    has_hangul = any(kind == "hangul" for kind, _run in runs)
    variants = set()
    for latin in (latin_readings if has_latin else [None]):
        for table in (cyrillic if has_cyr else (None,)):
            for voiceless in ((False, True) if has_hangul else (False,)):
                parts = []
                for kind, run in runs:
                    if kind == "cyr":
                        parts.append("".join(table.get(char, "") for char in run))
                    elif kind == "kana":
                        parts.append(_read_latin(kana_to_latin(run), "ja"))
                    elif kind == "hangul":
                        parts.append(hangul_to_latin(run, voiceless))
                    elif kind == "latin":
                        parts.append(_read_latin(run, latin))
                    elif kind == "digit":
                        parts.append(run)
                    else:
                        parts.append(" ")
                key = _fold("".join(parts))
                if key:
                    variants.add(key)
    return variants

def similarity(first, second):
    """How alike two sets of keys are, 0..1: the best pair. Equal keys are 1.0;
    keys shorter than MIN_FUZZY count only when equal."""
    best = 0.0
    for a in first:
        for b in second:
            if a == b:
                return 1.0
            if min(len(a), len(b)) < MIN_FUZZY:
                continue
            ratio = difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()
            if ratio > best:
                best = ratio
    return best

_SAME = (
    (("Сибуя", "ru"), ("Шибуя", "ru"), ("Shibuya", "en"), ("シブヤ", "ja"),
     ("しぶや", "ja"), ("Сібуя", "uk")),
    (("Цубаса", "ru"), ("Tsubasa", "en"), ("ツバサ", "ja"), ("Цубаса", "uk")),
    (("Тихиро", "ru"), ("Chihiro", "en"), ("チヒロ", "ja"), ("Тіхіро", "uk")),
    (("Дзюн", "ru"), ("Jun", "en"), ("ジュン", "ja")),
    (("Сюити", "ru"), ("Shuichi", "en"), ("シュウイチ", "ja"), ("Сюїті", "uk")),
    (("Пикачу", "ru"), ("Pikachu", "en"), ("Pikachu", "fr"), ("ピカチュウ", "ja")),
    (("Токио", "ru"), ("Tōkyō", "en"), ("Tokyo", "de"), ("トウキョウ", "ja")),
    (("Кевин Теммер", "ru"), ("Kevin Temmer", "en")),
    (("Чайковский", "ru"), ("Tchaïkovski", "fr"), ("Tschaikowski", "de"),
     ("Czajkowski", "pl"), ("Tchaikovsky", "en")),
    (("Григорій", "uk"), ("Hryhorii", "en"), ("Григорий", "ru")),
    (("Житомир", "uk"), ("Zhytomyr", "en"), ("Житомир", "ru")),
    (("Джон", "ru"), ("John", "en")),
    (("Мария", "ru"), ("Mariya", "en"), ("Maria", "es")),
    (("Ёсида", "ru"), ("Yoshida", "en"), ("ヨシダ", "ja")),
    (("Хосе", "ru"), ("José", "es")),
    (("Пак", "ru"), ("박", "ko")),
)
"""Groups whose members must share a key. Each line is a name the folding was
built for, written the ways the wikis write it."""

_DIFFERENT = (
    (("Список эпизодов", "ru"), ("List of episodes", "en")),
    (("Кевин", "ru"), ("Kelvin", "en")),
    (("Персонажи", "ru"), ("Characters", "en")),
)
"""Pairs that must stay below 90% — a translated title is not a transliterated
one, and a short name is not a long one."""

def self_test():
    """Check the folding against the names it was built for. -> failures."""
    failures = []
    for group in _SAME:
        first = keys(*group[0])
        for other in group[1:]:
            if not first & keys(*other):
                failures.append("{} ≠ {}: {} / {}".format(
                    group[0][0], other[0], sorted(first), sorted(keys(*other))))
    for one, two in _DIFFERENT:
        if similarity(keys(*one), keys(*two)) >= 0.9:
            failures.append("{} ≈ {}".format(one[0], two[0]))
    if keys("碇シンジ", "ja"):
        failures.append("kanji gave a key")
    if not is_kana("いかり しんじ") or is_kana("碇シンジ"):
        failures.append("is_kana")
    return failures
