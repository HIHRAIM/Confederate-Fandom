"""The conversation that builds a task, written once for both messengers.

Discord can block on `wait_for` inside a command and aiogram cannot, so the
two halves wait for an answer in very different ways. Everything *else* about
asking — which questions, in which order, what an answer means, what a wrong
answer is told — is the same, and it lives here. Each half provides a small
`Conversation` object with `ask` and `say`, and this module drives it.

The shape of the dialog, and why it is this short:

1. **which mechanics** — a numbered list, or the numbers and codes the person
   already put in the command (`/run 1 4 7`, `/run replace typos-ru`);
2. **which wiki** — a domain. Anything a person is likely to paste is
   accepted, including an article URL;
3. **where the pages come from** — one numbered list, and its argument;
4. **what each mechanic needs** — only what has no sensible default;
5. **the switches, all of them, in one message** — every optional flag of
   every chosen mechanic, numbered once through, answered with the numbers
   separated by spaces or with `0` for none. This is the step that keeps a
   task of four mechanics from being twenty questions;
6. **the edit summary** — or a dash, and the bot writes what it actually did;
7. **once or regularly**, and when.

Then the task is created and the queue takes over: it plans, says how many
pages it found, and waits for `/go`. The confirmation is deliberately not part
of this conversation — counting the pages of a whole wiki takes a minute, and
a dialog that hangs for a minute is a dialog somebody abandons.

Not this module's zone: sending and waiting (telegram_bot/dialogs.py,
discord_bot/dialogs.py) and what the questions say (i18n/).
"""
import logging

logger = logging.getLogger("fd.tasks.dialog")

from tasks import access, mechanic as mech_kinds, pagesets, registry
from tasks.params import CHOICE, FLAGS
from tasks.params import fill_defaults, parse_flags
from utils import localized

ONCE = "once"
HOURLY = "hourly"
DAILY = "daily"
WEEKLY = "weekly"

WHEN_OPTIONS = ((ONCE, "when_once"), (HOURLY, "when_hourly"),
                (DAILY, "when_daily"), (WEEKLY, "when_weekly"))

MAX_ATTEMPTS = 3


class Conversation:
    """What each messenger has to provide for the dialog to run.

    `ask` sends a question and waits for the person's next message, returning
    its text or None on a timeout. `say` sends without waiting. The rest is
    who is talking and where, which is what the task row stores so that a run
    finishing an hour later still knows where to answer.
    """

    def __init__(self, platform, user_id, display_name, chat_key, lang):
        """Remember who and where. The two halves subclass this for `ask`."""
        self.platform = platform
        self.user_id = user_id
        self.display_name = display_name
        self.chat_key = chat_key
        self.lang = lang

    async def ask(self, text):
        """Send a question, wait for the answer. -> the text, or None."""
        raise NotImplementedError

    async def say(self, text):
        """Send something that needs no answer."""
        raise NotImplementedError


def mechanics_list(lang):
    """The catalogue as a person reads it: a number, a code and a line."""
    lines = [localized("tasks_header", lang)]
    for number, mechanic in registry.numbered():
        lines.append("{}. {} — {}\n    `{}`{}".format(
            number,
            localized(mechanic.name_key, lang),
            localized(mechanic.desc_key, lang),
            mechanic.code,
            "  " + localized("tasks_destructive_mark", lang)
            if mechanic.destructive else ""))
    return "\n".join(lines)


def _numbered(lang, header, options):
    """A numbered list of (value, i18n key) pairs, as one message."""
    lines = [header]
    for index, (_value, key) in enumerate(options, 1):
        lines.append("{}. {}".format(index, localized(key, lang)))
    return "\n".join(lines)


async def _ask_choice(conv, header, options, error_key="dialog_bad_choice"):
    """Ask a numbered question until the answer is one of the numbers."""
    values = [value for value, _key in options]
    for _attempt in range(MAX_ATTEMPTS):
        answer = await conv.ask(_numbered(conv.lang, header, options))
        if answer is None:
            return None
        raw = answer.strip().rstrip(".")
        if raw.isdigit() and 1 <= int(raw) <= len(values):
            return values[int(raw) - 1]
        lowered = raw.lower()
        for value in values:
            if str(value).lower() == lowered:
                return value
        await conv.say(localized(error_key, conv.lang))
    return None


async def _ask_param(conv, param, values):
    """Ask for one parameter until the answer parses. -> the value or None."""
    if param.kind == CHOICE:
        return await _ask_choice(conv, localized(param.label, conv.lang),
                                 param.options)
    for _attempt in range(MAX_ATTEMPTS):
        answer = await conv.ask(localized(param.label, conv.lang))
        if answer is None:
            return None
        try:
            return param.parse(answer)
        except ValueError:
            await conv.say(localized("dialog_bad_value", conv.lang))
    return None


async def _ask_flags(conv, mechanics):
    """Every switch of every chosen mechanic, in one numbered message.

    The one place the dialog would otherwise grow without limit: four
    mechanics with five switches each is twenty yes-or-no questions, and
    nobody answers twenty questions. Here they are one list, and the person
    writes the numbers they want — or `0`, which is what most runs want.

    -> {parameter name: [values]}, or None on a timeout.
    """
    entries = []
    for mechanic in mechanics:
        for param in mechanic.params:
            if param.kind != FLAGS:
                continue
            for value, key in param.options:
                entries.append((param.name, value, key,
                                localized(mechanic.name_key, conv.lang)))
    if not entries:
        return {}

    lines = [localized("dialog_flags", conv.lang)]
    last_owner = None
    for index, (_name, _value, key, owner) in enumerate(entries, 1):
        if owner != last_owner:
            lines.append("— {}".format(owner))
            last_owner = owner
        lines.append("{}. {}".format(index, localized(key, conv.lang)))
    lines.append(localized("dialog_flags_hint", conv.lang))

    for _attempt in range(MAX_ATTEMPTS):
        answer = await conv.ask("\n".join(lines))
        if answer is None:
            return None
        try:
            chosen = parse_flags(answer, list(range(1, len(entries) + 1)))
        except ValueError:
            await conv.say(localized("dialog_bad_flags", conv.lang))
            continue
        result = {}
        for number in chosen:
            name, value, _key, _owner = entries[number - 1]
            result.setdefault(name, []).append(value)
        for name, _value, _key, _owner in entries:
            result.setdefault(name, [])
        return result
    return None


async def _ask_pageset(conv):
    """Where the pages come from: the source and its argument."""
    options = tuple((code, key) for code, key, _needs in pagesets.SOURCES)
    source = await _ask_choice(conv, localized("dialog_source", conv.lang), options)
    if source is None:
        return None
    params = {"source": source}
    if pagesets.needs_argument(source):
        for _attempt in range(MAX_ATTEMPTS):
            answer = await conv.ask(localized(
                "dialog_source_argument_" + source, conv.lang))
            if answer is None:
                return None
            if answer.strip():
                params["argument"] = answer.strip()
                break
            await conv.say(localized("dialog_bad_value", conv.lang))
        else:
            return None

    namespaces = await conv.ask(localized("dialog_namespaces", conv.lang))
    if namespaces is None:
        return None
    if namespaces.strip() and namespaces.strip() not in ("-", "0"):
        params["namespaces"] = namespaces.strip()
    else:
        params["namespaces"] = "0"

    limit = await conv.ask(localized("dialog_limit", conv.lang))
    if limit is None:
        return None
    raw = limit.strip().rstrip(".")
    params["limit"] = int(raw) if raw.isdigit() else 0
    return params


async def _ask_when(conv):
    """Once, or on a schedule — and if on a schedule, when exactly.

    -> a mapping the caller hands to db.create_schedule, or {'kind': 'once'}.
    """
    kind = await _ask_choice(conv, localized("dialog_when", conv.lang),
                             WHEN_OPTIONS)
    if kind is None:
        return None
    if kind == ONCE:
        return {"kind": ONCE}

    if kind == HOURLY:
        answer = await conv.ask(localized("dialog_when_minutes", conv.lang))
        if answer is None:
            return None
        return {"kind": HOURLY, "minutes": answer.strip() or "0"}

    answer = await conv.ask(localized("dialog_when_time", conv.lang))
    if answer is None:
        return None
    hour, _, minute = answer.strip().partition(":")
    try:
        hour = int(hour)
        minute = int(minute or 0)
    except ValueError:
        await conv.say(localized("dialog_bad_time", conv.lang))
        return None

    if kind == DAILY:
        return {"kind": DAILY, "hour": hour, "minute": minute}

    days = await conv.ask(localized("dialog_when_weekdays", conv.lang))
    if days is None:
        return None
    return {"kind": WEEKLY, "hour": hour, "minute": minute,
            "weekdays": days.strip() or "0"}


async def build(conv, tokens=()):
    """The whole conversation. -> the new task's id, or None.

    `tokens` are whatever came with the command, so `/run replace typos-ru`
    skips the first question and `/run` asks it.
    """
    import db
    import scheduler
    from tasks import queue as task_queue

    requester = access.caller(conv.platform, conv.user_id, conv.display_name)
    if requester is None:
        await conv.say(localized("not_admin", conv.lang))
        return None

    mechanics, unknown = registry.find_all(tokens)
    if unknown:
        await conv.say(localized("run_unknown", conv.lang,
                                 what=", ".join(unknown)))
        return None
    if not mechanics:
        await conv.say(mechanics_list(conv.lang))
        answer = await conv.ask(localized("dialog_pick_mechanics", conv.lang))
        if answer is None:
            return None
        mechanics, unknown = registry.find_all(answer.replace(",", " ").split())
        if unknown or not mechanics:
            await conv.say(localized("run_unknown", conv.lang,
                                     what=", ".join(unknown) or "—"))
            return None

    target = None
    for _attempt in range(MAX_ATTEMPTS):
        answer = await conv.ask(localized("dialog_wiki", conv.lang))
        if answer is None:
            return None
        try:
            from wiki import families

            target = families.parse_target(answer)
            break
        except ValueError as e:
            await conv.say(str(e))
    if target is None:
        return None

    await conv.say(localized("dialog_wiki_checking", conv.lang))
    try:
        import asyncio

        from wiki import families

        family, lang = await asyncio.to_thread(families.ensure_family, target)
    except Exception as e:
        await conv.say(localized("dialog_wiki_failed", conv.lang, error=e))
        return None
    wiki_key = "{}:{}".format(family, lang)

    params = {}
    if registry.needs_pages(mechanics):
        pageset = await _ask_pageset(conv)
        if pageset is None:
            return None
        params.update(pageset)

    for param in registry.all_params(mechanics):
        if param.kind == FLAGS:
            continue
        if not (param.required and param.wanted(params)):
            continue
        value = await _ask_param(conv, param, params)
        if value is None:
            return None
        params[param.name] = value

    flags = await _ask_flags(conv, mechanics)
    if flags is None:
        return None
    params.update(flags)
    params = fill_defaults(registry.all_params(mechanics), params)

    writes = [m for m in mechanics if m.kind != mech_kinds.REPORT]
    if writes:
        summary = await conv.ask(localized("dialog_summary", conv.lang))
        if summary is None:
            return None
        params["summary"] = "" if summary.strip() in ("-", "—") else summary.strip()
    else:
        params["summary"] = ""

    when = await _ask_when(conv)
    if when is None:
        return None

    codes = [mechanic.code for mechanic in mechanics]
    if when["kind"] != ONCE:
        schedule_id = db.create_schedule(
            wiki=wiki_key, mechanics=codes, params=params,
            kind=when["kind"], requester=requester,
            minutes=when.get("minutes"), hour=when.get("hour"),
            minute=when.get("minute"), weekdays=when.get("weekdays"),
            reply_chat=conv.chat_key)
        await conv.say(localized("schedule_created", conv.lang, id=schedule_id,
                                 wiki=wiki_key,
                                 mechanics=", ".join(codes),
                                 when=describe_schedule(
                                     db.get_schedule(schedule_id), conv.lang)))
        return None

    task_id = db.create_task(wiki=wiki_key, mechanics=codes, params=params,
                             requester=requester, reply_chat=conv.chat_key)
    await conv.say(localized("task_created", conv.lang, id=task_id,
                             wiki=wiki_key, mechanics=", ".join(codes)))
    scheduler.enqueue(task_queue.JOB, reason="task {} created".format(task_id))
    return task_id


def describe_schedule(row, lang):
    """When a repeating run happens, as a person reads it."""
    if row is None:
        return "—"
    kind = row["kind"]
    if kind == HOURLY:
        return localized("schedule_hourly", lang, minutes=row["minutes"] or "0")
    when = "{:02d}:{:02d}".format(int(row["hour"] or 0), int(row["minute"] or 0))
    if kind == DAILY:
        return localized("schedule_daily", lang, time=when)
    names = localized("weekday_names", lang).split(",")
    days = [names[int(day) % 7].strip()
            for day in str(row["weekdays"] or "0").replace(" ", "").split(",")
            if day.isdigit()]
    return localized("schedule_weekly", lang, time=when, days=", ".join(days))
