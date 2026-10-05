"""The task engine, as a package: what the bot can be told to do and how.

The pieces, in the order a task meets them:

| Module | Responsibility |
|---|---|
| `mechanic.py` | what a mechanic *is* — the class the scripts declare themselves with |
| `registry.py` | the catalogue: which mechanics exist, in which order, by number or by code |
| `params.py` | what a mechanic has to be told, and how one typed answer becomes a value |
| `pagesets.py` | where the pages come from |
| `access.py` | who may ask, and what the bot is allowed to do on that wiki |
| `runner.py` | the plan, the chunks, the edits |
| `report.py` | the files that go back, and what may go into them |
| `notify.py` | getting the answers to the person and to the service log |
| `queue.py` | the scheduler job that drives all of it |

The re-exports below are the package's public face — what the commands and
main.py reach for. Import order matters in one place only: `registry` imports
every mechanic, and every mechanic imports `mechanic`, which imports nothing.
That is why the class lives in a module of its own.
"""
from tasks.mechanic import ACTION, REPORT, TEXT, Mechanic
from tasks.params import Param, asked_params, fill_defaults, parse_flags
_REGISTRY_EXPORTS = (
    "MECHANICS", "all_params", "find", "find_all", "is_destructive",
    "needs_pages", "numbered", "of_kind", "rights_for",
)

def __getattr__(name):
    """Load the catalogue only when it is requested, after a script's SPEC.

    Importing a script first enters this package to obtain Mechanic. Eagerly
    loading the catalogue at that point sees the half-initialized script,
    drops it and shifts every later number. Lazy public re-exports retain the
    same API while allowing either documented import order.
    """
    if name in _REGISTRY_EXPORTS:
        from tasks import registry
        return getattr(registry, name)
    raise AttributeError(name)
