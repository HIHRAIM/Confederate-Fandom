"""The mechanics: one module per script the bot was asked to carry over.

Each module is named after the Pywikibot script (or the operator's own bot)
it came from, keeps that script's copyright line in its docstring, and
declares itself with a `SPEC` that tasks/registry.py collects. Beside them:

* `wikitools.py` — the layer they share: masking what may not be touched,
  the cosmetics, the AWB `<Typo/>` format, applying rules until they
  converge, and building an edit summary out of what actually happened;
* `typos_ru.py`, `punct_ru.py`, `pravopys_uk.py` — the language rules, each
  carrying its own self-tests, which the task runner runs before the first
  edit of a pass;
* `data/` — the rule lists those three read.

This is a real package and not a namespace one on purpose. `scripts` is a
name Pywikibot also uses for its own script directory; an `__init__.py` here
makes ours an ordinary package that cannot be merged with anything else that
happens to be on the path.

Nothing is imported here. A mechanic is imported by tasks/registry.py when
the catalogue is built, and importing them all from this file would mean a
broken one took the whole package down with it.
"""
