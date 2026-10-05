"""Swap or remove a file wherever it is used — Pywikibot's image.py, adapted.

    Pywikibot's image.py is (C) Pywikibot team, 2013-2025, MIT licence. It
    replaces one image with another across the pages that use it, and removing
    it is the same job with an empty target — that is kept here exactly.

A file is used in more shapes than a link, and all four are handled:

* ``[[Файл:Имя.jpg|thumb|подпись]]`` — the whole construct, in any of the
  namespace spellings a Fandom wiki may carry;
* ``|изображение=Имя.jpg`` — a parameter of an infobox, which is how most
  articles actually show a picture;
* a bare line inside ``<gallery>``;
* ``{{#invoke:}}`` and other places the name appears as plain text, which is
  the fallback: the name is replaced wherever it stands as a whole word.

With an empty target the usage is removed rather than emptied — an infobox
parameter left as ``|изображение=`` renders as a broken slot on many themes,
so the parameter goes with it, and a ``[[Файл:…]]`` construct is taken out
along with the line break that followed it.

The removal half is also what `delinker` uses, which is why it lives here as a
function rather than inside `apply`.
"""
import re
import sys

from tasks import mechanic as mech
from utils import Explained
from tasks.params import BLANK, TEXT, Param

FILE_PREFIX = r"(?:[Фф]айл|[Ff]ile|[Ии]зображение|[Зз]ображення|[Ii]mage|[Мм]едиа|[Mm]edia)"

IMAGE_PARAM = (r"(?:изображение|изображения|image|img|файл|file|фото|photo|"
               r"логотип|logo|обложка|обкладинка|cover|картинка|зображення)")

def normalise(name):
    """A file name without its namespace, with spaces, first letter capital."""
    text = str(name or "").strip().lstrip(":")
    text = re.sub(r"^" + FILE_PREFIX + r"\s*:\s*", "", text, flags=re.I)
    text = re.sub(r"\s+", " ", text.replace("_", " ")).strip()
    return text[:1].upper() + text[1:] if text else text

def name_pattern(name):
    """A pattern matching one file name however it is spelt in wikitext."""
    head = name[0]
    body = re.escape(name[1:]).replace(r"\ ", r"[ _]")
    return r"(?:" + re.escape(head.upper()) + "|" + re.escape(head.lower()) + r")" + body

def usage_patterns(name):
    """The three shaped patterns that find one file's usages. -> a tuple.

    Returned together because both `apply` and `delinker` want the same three,
    and a fourth spelling invented in one of them would be a file removed on
    one wiki and left on another.
    """
    core = name_pattern(name)
    construct = re.compile(
        r"\[\[\s*" + FILE_PREFIX + r"\s*:\s*" + core + r"\s*(?:\|(?:[^\[\]]|\[\[[^\]]*\]\])*)?\]\]\n?",
        re.UNICODE)
    parameter = re.compile(
        r"[ \t]*\|\s*(?i:" + IMAGE_PARAM + r")\s*=\s*(?:" + FILE_PREFIX + r"\s*:\s*)?"
        + core + r"(?=[ \t]*(?:\||\}\}|\r?$))[ \t]*\n?",
        re.UNICODE | re.M)
    bare = re.compile(
        r"(?<![\w/.-])(?P<prefix>" + FILE_PREFIX + r"\s*:\s*)?" + core + r"(?![\w/.-])",
        re.UNICODE)
    return construct, parameter, bare

def remove_usages(text, name):
    """Take every usage of one file out of a page. -> (text, how many).

    Gallery captions belong to the image's whole line. Removing only the
    filename would leave a caption interpreted as another missing image.
    Parameter matches require a complete value, so ``Old.jpg.png`` cannot
    be mistaken for ``Old.jpg`` and damage the surrounding template.
    """
    construct, parameter, bare = usage_patterns(name)
    total = 0
    text, count = construct.subn("", text)
    total += count
    text, count = parameter.subn("", text)
    total += count
    gallery_line = re.compile(
        r"^[ \t]*(?:" + FILE_PREFIX + r"[ \t]*:[ \t]*)?"
        + name_pattern(name) + r"[ \t]*(?:\|[^\n]*)?(?:\n|$)", re.M)

    def _gallery(match):
        """Drop the matching image and its caption inside one gallery."""
        nonlocal total
        body, count = gallery_line.subn("", match.group(2))
        total += count
        return match.group(1) + body + match.group(3)

    text = re.sub(r"(<gallery\b[^>]*>)(.*?)(</gallery\s*>)", _gallery,
                  text, flags=re.I | re.S)
    lines = []
    changed = 0
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped and bare.fullmatch(stripped):
            changed += 1
            continue
        lines.append(line)
    if changed:
        text = "\n".join(lines)
        total += changed
    return text, total

def replace_usages(text, name, target):
    """Replace the filename while retaining its namespace spelling.

    ``[[File:Old.jpg]]`` must stay a file inclusion; dropping ``File:``
    silently turns the image into an ordinary article link.
    """
    _construct, _parameter, bare = usage_patterns(name)
    return bare.subn(lambda m: (m.group("prefix") or "") + target, text)

def prepare(ctx):
    """Check the arguments before a single page is read."""
    name = normalise(ctx.params.get("image_from"))
    if not name:
        raise Explained("error_image_no_file")
    return {"name": name, "to": normalise(ctx.params.get("image_to"))}

def apply(ctx, page, text):
    """One page with the file swapped or taken out. -> (text, change labels)."""
    state = ctx.state.get(SPEC.code) or {}
    name, target = state["name"], state["to"]
    if target:
        new, count = replace_usages(text, name, target)
        label = "файл заменён ×{}"
    else:
        new, count = remove_usages(text, name)
        label = "файл убран ×{}"
    if not count or new == text:
        return text, []
    return new, [label.format(count)]

def summary_part(ctx, labels):
    """What this mechanic contributes to the edit summary."""
    if not labels:
        return None
    state = ctx.state.get(SPEC.code) or {}
    if state.get("to"):
        return "файл «{}» заменён на «{}»".format(state["name"], state["to"])
    return "убран файл «{}»".format(state.get("name"))

SPEC = mech.Mechanic(
    code="image",
    kind=mech.TEXT,
    module=sys.modules[__name__],
    rights=("edit",),
    params=(
        Param("image_from", TEXT, "param_image_from"),
        Param("image_to", TEXT, "param_image_to",
              blank=BLANK + ("-", "—", "–")),
    ),
)
