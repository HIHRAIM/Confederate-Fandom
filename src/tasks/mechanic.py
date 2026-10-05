"""What a mechanic is, declared where nothing else has to be imported first.

This module exists to break a cycle rather than to hold much. Every mechanic
under scripts/ has to declare itself with `Mechanic`, and the catalogue
(tasks/registry.py) has to import every mechanic to build the list — so if the
class lived in the catalogue, importing a mechanic first would find the
catalogue half-built and its SPEC missing. Here nothing is imported at all,
so both orders work.

The three kinds decide how a task runs, and the difference is not cosmetic:

* **TEXT** — it rewrites wikitext. Several of them compose: the runner reads a
  page once, hands the text to each in turn, and saves once with a summary
  built from all of them. That is what makes «замена + опечатки + пунктуация +
  косметика» one edit per page instead of four.
* **ACTION** — it does something to the page itself: delete, protect, move,
  revert. These run after the text ones, one page at a time, and each says
  what happened to that page.
* **REPORT** — it changes nothing. It collects lines, and the task ends with a
  file.
"""

TEXT = "text"
ACTION = "action"
REPORT = "report"

KINDS = (TEXT, ACTION, REPORT)

class Mechanic:
    """One thing the bot can be told to do, declared rather than described.

    `code` is what a person may type instead of a number, and what is stored
    in a task row — it never changes. `rights` are the MediaWiki rights the
    session must hold before the run may start; a missing one is reported as
    the group that would grant it, or as the BotPassword grant that withholds
    it (wiki/rights.py: explain_missing).

    The callables are looked up on the module, not passed in, so that a
    mechanic's module reads as the script it was ported from and not as a
    registration form: `prepare`, and then `apply` / `act` / `collect`
    according to the kind.
    """

    __slots__ = ("code", "kind", "module", "rights", "params", "destructive",
                 "standalone", "own_pages", "schedulable")

    def __init__(self, code, kind, module, rights=(), params=(),
                 destructive=False, standalone=False, own_pages=False,
                 schedulable=True):
        """Declare one mechanic. Nothing here reads a wiki.

        `standalone` means the mechanic asks the wiki its own question and
        needs no page list at all — counting how often a template is used, or
        drawing a category tree. A task made only of standalone mechanics
        skips the page-source dialog entirely.

        `destructive` marks the ones that cannot be undone by editing: delete,
        move, protect, revert. It is what makes the confirmation say so out
        loud.

        `own_pages` means the mechanic knows its pages itself and the dialog
        does not ask where they come from: undoing an account's work walks
        that account's contributions, not a category somebody has to guess.
        The module provides `pages(ctx)`.

        `schedulable` False keeps the mechanic out of repeating runs, and the
        dialog does not ask "once or regularly" at all: undoing one person's
        edits every night is not a thing anybody means to ask for.
        """
        if kind not in KINDS:
            raise ValueError("unknown mechanic kind: {}".format(kind))
        self.code = code
        self.kind = kind
        self.module = module
        self.rights = tuple(rights)
        self.params = tuple(params)
        self.destructive = destructive
        self.standalone = standalone
        self.own_pages = own_pages
        self.schedulable = schedulable

    def __repr__(self):
        """The code, which is how a mechanic is named everywhere else."""
        return "<Mechanic {}>".format(self.code)

    @property
    def name_key(self):
        """The i18n key of this mechanic's name."""
        return "mech_{}".format(self.code.replace("-", "_"))

    @property
    def desc_key(self):
        """The i18n key of the line under its name in the list."""
        return "mech_{}_desc".format(self.code.replace("-", "_"))

    def prepare(self, ctx):
        """Whatever the mechanic has to do once before the first page.

        Compiling six hundred rules, reading a deletion log, loading a list of
        interwikis: it happens here, once per run, and whatever it returns is
        kept in the context under the mechanic's code. Raising here stops the
        task before anything is written, which is where a bad regular
        expression or a missing argument belongs.
        """
        hook = getattr(self.module, "prepare", None)
        return hook(ctx) if hook else None

    def apply(self, ctx, page, text):
        """TEXT: rewrite one page's text. -> (new text, list of change labels)."""
        return self.module.apply(ctx, page, text)

    def act(self, ctx, page):
        """ACTION: do something to one page. -> (state, note)."""
        return self.module.act(ctx, page)

    def collect(self, ctx, page):
        """REPORT: read one page. -> lines for the report file, or None."""
        hook = getattr(self.module, "collect", None)
        return hook(ctx, page) if hook else None

    def finish(self, ctx):
        """Whatever the mechanic has to say once the last page is done.

        This is also where a standalone mechanic does all of its work: it has
        no page list to walk, so it asks the wiki its question here and
        returns the lines of the report.
        """
        hook = getattr(self.module, "finish", None)
        return hook(ctx) if hook else None

    def pages(self, ctx):
        """The titles an `own_pages` mechanic works on, found by itself."""
        hook = getattr(self.module, "pages", None)
        return list(hook(ctx)) if hook else []

    def redirects(self, params):
        """Which pages this mechanic can do anything with, for these settings.

        -> False: ordinary pages only, which is every mechanic that does not
        say otherwise; True: redirects only; None: both.

        Asked before the page list is built, and it decides what the sources
        that enumerate a wiki (all pages, a prefix, new pages, recent changes)
        list at all. They used to list ordinary pages whatever the task, so
        the redirect mechanic, told to fix double redirects on a wiki that had
        thirteen, was handed 212 articles and not one redirect, and finished
        with 0 edits and no error. A source that names its pages itself — a
        category, a list of titles — is not filtered: whoever named them meant
        them.
        """
        hook = getattr(self.module, "redirects", None)
        return hook(params) if hook else False

    def summary_part(self, ctx, labels):
        """This mechanic's contribution to the edit summary.

        A mechanic that builds its own — the spelling ones say exactly what
        they corrected — provides `summary_part`; the rest are named by their
        own wording in the i18n files.
        """
        hook = getattr(self.module, "summary_part", None)
        if hook:
            return hook(ctx, labels)
        return None
