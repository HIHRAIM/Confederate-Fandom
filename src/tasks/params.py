"""What a mechanic needs to be told, and how the bot asks for it.

A parameter is declared, not asked for by hand. Every mechanic lists what it
needs, and the two halves of the bot walk that list the same way — one dialog
for both messengers, one place to change how a question is put.

The kinds, and why there are only six:

* `TEXT` / `LONGTEXT` — a line, or something that may run to paragraphs.
* `INT` — a number, with bounds.
* `CHOICE` — one of a few. Printed as a numbered list; the answer is a number.
* `FLAGS` — several of a few, and this is the one that keeps the dialogs
  short. Everything optional about a mechanic is collected into a single
  message: the options are numbered, the person writes the numbers they want
  separated by spaces, and `0` means none of them. One question instead of
  eight yes-or-no ones.
* `PAGES` — where the pages come from. It has a sub-dialog of its own
  (tasks/pagesets.py), because the answer is itself a choice plus an argument.

A parameter with a default is never asked about on its own; it goes into the
FLAGS message when it is a switch, and is simply left at its default when it
is not. That is deliberate: a dialog a person has to answer eight times is a
dialog they stop using.

Not this module's zone: the catalogue of mechanics (tasks/registry.py) and the
sending itself (telegram_bot/, discord_bot/).
"""

TEXT = "text"
LONGTEXT = "longtext"
INT = "int"
CHOICE = "choice"
FLAGS = "flags"
PAGES = "pages"

KINDS = (TEXT, LONGTEXT, INT, CHOICE, FLAGS, PAGES)

EMPTY_ANSWERS = ("-", "—", "–")
"""What a person writes when the answer is "nothing". A replacement may
legitimately be the empty string — that is how a mechanic deletes rather than
replaces — and an empty message cannot be sent on either messenger, so a lone
dash stands for it. The prompts say so."""


class Param:
    """One thing a mechanic has to be told.

    `name` is the key it lands under in the task's parameters. `label` is the
    i18n key of the question. `options` is a tuple of (value, i18n key) for
    CHOICE and FLAGS. `default` makes the parameter optional; a FLAGS
    parameter is optional by definition and its default is the empty set.
    """

    __slots__ = ("name", "kind", "label", "options", "default", "minimum",
                 "maximum", "placeholder", "depends")

    def __init__(self, name, kind, label, options=(), default=None,
                 minimum=None, maximum=None, placeholder=None, depends=None):
        """Declare one parameter. Nothing here talks to anybody.

        `depends` is (the name of another parameter, the value or values that
        make this one relevant). It is what keeps the dialogs short: the
        category mechanic asks where to move a category to only when the
        person chose to move one, and never otherwise.
        """
        if kind not in KINDS:
            raise ValueError("unknown parameter kind: {}".format(kind))
        self.name = name
        self.kind = kind
        self.label = label
        self.options = tuple(options)
        self.default = default
        self.minimum = minimum
        self.maximum = maximum
        self.placeholder = placeholder
        self.depends = depends

    def wanted(self, values):
        """Whether this parameter is relevant given what has been answered.

        A parameter with no `depends` is always relevant. One with `depends`
        is relevant only when the parameter it names holds one of the values
        it names — asked at the moment that becomes true, and skipped for
        good otherwise.
        """
        if not self.depends:
            return True
        name, expected = self.depends
        if not isinstance(expected, (list, tuple, set)):
            expected = (expected,)
        return (values or {}).get(name) in expected

    @property
    def required(self):
        """Whether the dialog must have an answer before the task can run."""
        return self.default is None and self.kind != FLAGS

    def option_values(self):
        """The values of a CHOICE or FLAGS parameter, in the order shown."""
        return [value for value, _key in self.options]

    def parse(self, text):
        """One typed answer -> the stored value, or raise ValueError.

        The messengers hand over whatever the person wrote; everything that
        turns text into a value happens here, so that Discord and Telegram
        cannot drift apart on what «2 3» means.
        """
        raw = (text or "").strip()
        if self.kind in (TEXT, LONGTEXT):
            if raw in EMPTY_ANSWERS:
                return ""
            if not raw:
                raise ValueError("empty")
            return raw
        if self.kind == INT:
            try:
                value = int(raw.replace(" ", ""))
            except ValueError:
                raise ValueError("not a number")
            if self.minimum is not None and value < self.minimum:
                raise ValueError("too small")
            if self.maximum is not None and value > self.maximum:
                raise ValueError("too large")
            return value
        if self.kind == CHOICE:
            values = self.option_values()
            index = raw.rstrip(".")
            if index.isdigit() and 1 <= int(index) <= len(values):
                return values[int(index) - 1]
            lowered = raw.lower()
            for value in values:
                if str(value).lower() == lowered:
                    return value
            raise ValueError("not one of the options")
        if self.kind == FLAGS:
            return parse_flags(raw, self.option_values())
        raise ValueError("this kind is not parsed here")


def parse_flags(text, values):
    """«1 3 4» -> the values chosen; «0» or «-» -> none. Raises on nonsense.

    Commas are accepted beside spaces, because half the people who are told
    "separated by spaces" write commas anyway, and refusing them teaches
    nobody anything.
    """
    raw = (text or "").strip().lower()
    if raw in ("0", "-", "нет", "none", "no", "ні", "нема"):
        return []
    chosen = []
    for token in raw.replace(",", " ").split():
        token = token.rstrip(".")
        if not token.isdigit():
            raise ValueError("not a number: {}".format(token))
        index = int(token)
        if index == 0:
            continue
        if not 1 <= index <= len(values):
            raise ValueError("no such option: {}".format(index))
        value = values[index - 1]
        if value not in chosen:
            chosen.append(value)
    return chosen


def flag_params(params):
    """The switches of a mechanic — the ones that go into one FLAGS message."""
    return [p for p in params if p.kind == FLAGS]


def asked_params(params, values=None):
    """The parameters the dialog actually puts a question about.

    Everything required and relevant, plus the FLAGS message. A parameter that
    has a default and is not a switch is left alone: it exists so that a
    scheduled task can carry a value, not so that a person has to confirm it.

    `values` is what has been answered so far, which is what decides the
    parameters that depend on an earlier answer. It is re-read as the dialog
    goes, so a choice made in question two can add question three.
    """
    return [p for p in params
            if (p.required or p.kind == FLAGS) and p.wanted(values)]


def fill_defaults(params, values):
    """Put the defaults in for everything the dialog did not ask about."""
    filled = dict(values or {})
    for param in params:
        if param.name in filled:
            continue
        filled[param.name] = [] if param.kind == FLAGS else param.default
    return filled
