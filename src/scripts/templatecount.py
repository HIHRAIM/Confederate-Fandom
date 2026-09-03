"""How often templates are used — Pywikibot's templatecount.py, as a mechanic.

    Pywikibot's templatecount.py is (C) Pywikibot team, 2006-2025, MIT
    licence. It counts and it lists, and both are kept.

This one is standalone: it has no page list, because the pages it is
interested in are exactly the ones that use the templates, and the wiki
already knows which those are. So the dialog never asks where to take pages
from — it asks which templates, and the answer comes back as a count and, if
asked, the list behind it.

Several templates at once, separated by commas: a template and its redirects
are different pages to MediaWiki, and the honest number for «сколько статей
пользуются этим шаблоном» is the sum over all of its names.
"""
import sys

from tasks import mechanic as mech
from tasks.params import FLAGS, TEXT, Param

FLAG_LIST = "list"
FLAG_REDIRECTS = "with_redirects"


def prepare(ctx):
    """Check that there is something to count."""
    names = _names(ctx)
    if not names:
        raise ValueError("не указан ни один шаблон")
    return names


def _names(ctx):
    """The template names of this run, without their namespace prefix."""
    raw = str(ctx.params.get("templates") or "")
    out = []
    for part in raw.replace("|", ",").split(","):
        name = part.strip().lstrip(":")
        for prefix in ("шаблон:", "шаблон :", "template:", "шаблон:"):
            if name.lower().startswith(prefix):
                name = name[len(prefix):].strip()
        if name and name not in out:
            out.append(name)
    return out


def finish(ctx):
    """Ask the wiki and build the report. -> the lines of the file."""
    import pywikibot

    flags = set(ctx.params.get("template_flags") or [])
    lines = []
    total = 0
    for name in ctx.state.get(SPEC.code) or []:
        page = pywikibot.Page(ctx.site, "Template:" + name)
        try:
            if not page.exists():
                lines.append("{}\tшаблона нет".format(name))
                continue
            users = list(page.getReferences(only_template_inclusion=True))
        except Exception as e:
            lines.append("{}\tне удалось посчитать: {}".format(
                name, type(e).__name__))
            continue

        if FLAG_REDIRECTS in flags:
            try:
                for redirect in page.redirects():
                    users += list(redirect.getReferences(
                        only_template_inclusion=True))
            except Exception:
                pass

        titles = sorted({user.title() for user in users})
        total += len(titles)
        lines.append("{}\t{}".format(name, len(titles)))
        if FLAG_LIST in flags:
            lines += ["\t" + title for title in titles]

    ctx.note("всего страниц с этими шаблонами: {}".format(total))
    return lines


SPEC = mech.Mechanic(
    code="templatecount",
    kind=mech.REPORT,
    module=sys.modules[__name__],
    rights=(),
    standalone=True,
    params=(
        Param("templates", TEXT, "param_templates"),
        Param("template_flags", FLAGS, "param_template_flags", options=(
            (FLAG_LIST, "flag_template_list"),
            (FLAG_REDIRECTS, "flag_template_redirects"),
        )),
    ),
)
