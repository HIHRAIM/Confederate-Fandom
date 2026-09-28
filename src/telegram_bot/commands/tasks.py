"""The task commands on Telegram: the catalogue, the runs and the schedules.

Six commands, and the shape of them is the same on both messengers because
everything they do lives in tasks/ — this module only takes the words apart
and hands them over.

| Command | What it does |
|---|---|
| `/tasks` | the numbered catalogue of mechanics |
| `/run [номера или коды]` | build a task, in a dialog |
| `/go <id> [dry]` | confirm a planned task and set it going |
| `/jobs` | what is running, what is waiting, what has just finished |
| `/stop <id>` | stop a task where it stands |
| `/schedule […]` | the repeating runs: list, off, on, delete |

Who may use them: a bot administrator (config.ADMINS) or a wiki administrator
the owner appointed (db/admins.py). The check is `access.caller`, and it is
the only one made here — whether the *bot* may work on the wiki somebody
chose, and whether that person has standing there, is decided when the task is
planned, because both need the wiki open and neither belongs in a command.
"""
import logging

from aiogram.filters import Command
from aiogram.types import Message

import db
from tasks import access, dialog, queue as task_queue
from telegram_bot import pages
from telegram_bot.client import router
from telegram_bot.dialogs import TelegramConversation
from utils import localized, user_lang

logger = logging.getLogger("fd.telegram.tasks")


def _caller(message):
    """Who is asking, or None when they may not ask. -> the requester mapping."""
    user = message.from_user
    if user is None:
        return None
    name = ("@" + user.username) if user.username else user.full_name
    return access.caller("telegram", user.id, name)


async def _deny(message, lang):
    """The answer everyone who may not use these commands gets."""
    await message.answer(localized("not_admin", lang))


def _positive_id(text):
    """Read a task or schedule id that SQLite can represent, or None.

    A Telegram argument is untrusted text. isdigit also accepts superscript
    digits that int rejects, and a very large integer cannot be bound by
    SQLite even when Python can parse it. Reject both as command usage errors
    before any database lookup.
    """
    if not text or len(text) > 19 or not text.isascii() or not text.isdecimal():
        return None
    value = int(text)
    return value if 0 < value <= 9223372036854775807 else None


@router.message(Command("tasks"))
async def tasks_cmd(message: Message):
    """The catalogue: what the bot can be told to do, numbered.

    A paged HTML message rather than a wall of text: one line per mechanic,
    the name in bold, the code in monospace after it
    (telegram_bot/pages.py)."""
    lang = user_lang(message.from_user)
    if _caller(message) is None:
        await _deny(message, lang)
        return
    await pages.send(message, "tasks", lang)


@router.message(Command("run"))
async def run_cmd(message: Message):
    """Build a task, in a dialog. `/run 1 4` skips the first question."""
    lang = user_lang(message.from_user)
    if _caller(message) is None:
        await _deny(message, lang)
        return
    tokens = (message.text or "").split()[1:]
    conversation = TelegramConversation(message)
    try:
        await dialog.build(conversation, tokens)
    except Exception as e:
        logger.exception("the /run dialog failed")
        await message.answer(localized("dialog_failed", lang, error=e))


@router.message(Command("go"))
async def go_cmd(message: Message):
    """Confirm a planned task and set it going. `dry` runs it without writing.

    Reject unknown flags before looking up the task. A misspelled preview
    flag must never silently become a live run just because it is not exactly
    the token `dry`.
    """
    lang = user_lang(message.from_user)
    if _caller(message) is None:
        await _deny(message, lang)
        return

    parts = (message.text or "").split()[1:]
    task_id = _positive_id(parts[0]) if parts else None
    flags = [part.lower() for part in parts[1:]]
    if task_id is None or flags not in ([], ["dry"]):
        await message.answer(localized("go_usage", lang))
        return
    row = db.get_task(task_id)
    if row is None:
        await message.answer(localized("task_unknown", lang, id=task_id))
        return
    if row["state"] != "confirm":
        await message.answer(localized("task_not_waiting", lang, id=task_id,
                                       state=row["state"]))
        return

    if flags == ["dry"]:
        db.set_dry_run(task_id)
    await task_queue.start(task_id)


@router.message(Command("jobs"))
async def jobs_cmd(message: Message):
    """What the bot is doing, what is queued, and how the last runs ended."""
    lang = user_lang(message.from_user)
    if _caller(message) is None:
        await _deny(message, lang)
        return

    await pages.send(message, "jobs", lang)


@router.message(Command("stop"))
async def stop_cmd(message: Message):
    """Stop a task. What it has already written stays written."""
    lang = user_lang(message.from_user)
    if _caller(message) is None:
        await _deny(message, lang)
        return
    parts = (message.text or "").split()[1:]
    task_id = _positive_id(parts[0]) if parts else None
    if task_id is None:
        await message.answer(localized("stop_usage", lang))
        return
    if await task_queue.stop(task_id):
        await message.answer(localized("stop_done", lang, id=task_id))
    else:
        await message.answer(localized("task_unknown", lang, id=task_id))


@router.message(Command("schedule"))
async def schedule_cmd(message: Message):
    """The repeating runs. `/schedule off|on|del <id>` changes one."""
    lang = user_lang(message.from_user)
    if _caller(message) is None:
        await _deny(message, lang)
        return

    parts = (message.text or "").split()[1:]
    if parts and parts[0].lower() in ("off", "on", "del", "delete"):
        schedule_id = _positive_id(parts[1]) if len(parts) >= 2 else None
        if schedule_id is None:
            await message.answer(localized("schedule_usage_telegram", lang))
            return
        action = parts[0].lower()
        row = db.get_schedule(schedule_id)
        if action in ("del", "delete"):
            ok = db.delete_schedule(schedule_id)
            key = "schedule_deleted" if ok else "schedule_unknown"
        elif row is not None and db.is_pending(row):
            key = "schedule_awaiting"
        else:
            ok = db.set_enabled(schedule_id, action == "on")
            key = ("schedule_on" if action == "on" else "schedule_off") \
                if ok else "schedule_unknown"
        await message.answer(localized(key, lang, id=schedule_id))
        return

    if not db.list_schedules():
        await message.answer(localized("schedule_empty", lang))
        return
    await pages.send(message, "sched", lang)
