"""The catalogue of mechanics: what the bot can be told to do.

One mechanic is one of the scripts, wrapped so that the bot can offer it in a
numbered list, ask for what it needs and run it over a page list. The wrapper
is thin on purpose — everything a mechanic actually *does* lives in its module
under scripts/, named after the script it came from. What a mechanic *is* is
declared in tasks/mechanic.py, which this module only collects.

The order of MECHANICS is the order of the numbered list a person sees, so it
may not be shuffled: somebody halfway through a dialog is holding a number
that has to keep meaning the same thing. New mechanics go at the end.

Not this module's zone: running them (tasks/runner.py), asking for their
parameters (tasks/params.py and the two messengers) and who is allowed
(tasks/access.py).
"""
import logging

from tasks.mechanic import ACTION, KINDS, REPORT, TEXT, Mechanic

logger = logging.getLogger("fd.tasks.registry")


def _load():
    """Import every mechanic module and read its SPEC.

    A module that will not import is a bug in that module and must not take
    the whole catalogue down with it: the bot is left able to do everything
    else, and the failure is in the log where somebody will find it.
    """
    names = (
        "replace", "add_text", "unlink", "typos_ru", "punct_ru",
        "pravopys_uk", "cosmetic", "category", "interwiki", "redirect",
        "image", "delinker", "movepages", "protect", "delete", "revertbot",
        "listpages", "templatecount", "category_graph",
    )
    catalogue = []
    for name in names:
        try:
            module = __import__("scripts." + name, fromlist=["SPEC"])
        except Exception:
            logger.exception("mechanic %s will not import and is not offered", name)
            continue
        spec = getattr(module, "SPEC", None)
        if spec is None:
            logger.error("module scripts.%s has no SPEC and is not offered", name)
            continue
        catalogue.append(spec)
    return tuple(catalogue)


MECHANICS = _load()

BY_CODE = {mechanic.code: mechanic for mechanic in MECHANICS}


def numbered():
    """The catalogue as (number, mechanic) pairs, 1-based."""
    return list(enumerate(MECHANICS, 1))


def find(token):
    """One mechanic by its number or by its code. -> the Mechanic or None.

    Both are accepted everywhere on purpose: a person may answer the list with
    «4», or skip the list entirely with `/run replace`.
    """
    key = str(token or "").strip().lower().rstrip(".")
    if not key:
        return None
    if key.isdigit():
        index = int(key)
        if 1 <= index <= len(MECHANICS):
            return MECHANICS[index - 1]
        return None
    return BY_CODE.get(key)


def find_all(tokens):
    """Several mechanics at once. -> (found, the tokens nothing matched).

    Order is the caller's, because it is the order they will run over each
    page, and «замена, потом опечатки» is not the same edit as the reverse.
    """
    found, unknown = [], []
    for token in tokens:
        mechanic = find(token)
        if mechanic is None:
            unknown.append(str(token))
        elif mechanic not in found:
            found.append(mechanic)
    return found, unknown


def rights_for(mechanics):
    """Every right a set of mechanics needs between them, in a stable order."""
    needed = []
    for mechanic in mechanics:
        for right in mechanic.rights:
            if right not in needed:
                needed.append(right)
    return needed


def of_kind(mechanics, kind):
    """The mechanics of one kind, in the order the caller gave them."""
    return [mechanic for mechanic in mechanics if mechanic.kind == kind]


def needs_pages(mechanics):
    """Whether this set of mechanics has to be given a page list at all."""
    return any(not mechanic.standalone for mechanic in mechanics)


def needs_source(mechanics):
    """Whether the dialog must ask where the pages come from: some mechanic
    walks pages and does not find them itself (`Mechanic.own_pages`)."""
    return any(not mechanic.standalone and not mechanic.own_pages
               for mechanic in mechanics)


def schedulable(mechanics):
    """Whether this set of mechanics may repeat on a schedule at all."""
    return all(mechanic.schedulable for mechanic in mechanics)


def redirects_wanted(mechanics, params):
    """Whether the page list should hold redirects. -> True, False or None.

    True when every mechanic that walks pages works on redirects alone, False
    when every one works on ordinary pages, None — both — when they differ:
    a task that fixes double redirects and tidies articles in one run needs
    the two kinds. Each mechanic of such a run is then handed both, exactly as
    it always was by a category or a list of titles; the redirect mechanic
    passes over whatever is not its own (see `Mechanic.redirects`).
    """
    wanted = {mechanic.redirects(params) for mechanic in mechanics
              if not mechanic.standalone}
    if len(wanted) == 1:
        return wanted.pop()
    return None


def is_destructive(mechanics):
    """Whether any of them does something an edit cannot undo."""
    return any(mechanic.destructive for mechanic in mechanics)


def all_params(mechanics):
    """Every parameter a set of mechanics needs, without asking twice.

    Two mechanics may want the same thing — a summary, a namespace — and the
    dialog must ask for it once. Parameters are matched by name, and the first
    mechanic that declares one owns it.
    """
    seen = set()
    ordered = []
    for mechanic in mechanics:
        for param in mechanic.params:
            if param.name in seen:
                continue
            seen.add(param.name)
            ordered.append(param)
    return ordered
