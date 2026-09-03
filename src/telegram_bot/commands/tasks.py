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
import scheduler
from tasks import access, dialog, queue as task_queue
from telegram_bot.client import router
from telegram_bot.dialogs import TelegramConversation
from utils import localized, user_lang

logger = logging.getLogger("fd.telegram.tasks")

RECENT_TASKS = 5


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


@router.message(Command("tasks"))
async def tasks_cmd(message: Message):
    """The catalogue: what the bot can be told to do, numbered."""
    lang = user_lang(message.from_user)
    if _caller(message) is None:
        await _deny(message, lang)
        return
    await message.answer(dialog.mechanics_list(lang))


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
    """Confirm a planned task and set it going. `dry` runs it without writing."""
    lang = user_lang(message.from_user)
    if _caller(message) is None:
        await _deny(message, lang)
        return

    parts = (message.text or "").split()[1:]
    if not parts or not parts[0].isdigit():
        await message.answer(localized("go_usage", lang))
        return
    task_id = int(parts[0])
    row = db.get_task(task_id)
    if row is None:
        await message.answer(localized("task_unknown", lang, id=task_id))
        return
    if row["state"] != "confirm":
        await message.answer(localized("task_not_waiting", lang, id=task_id,
                                       state=row["state"]))
        return

    if "dry" in [part.lower() for part in parts[1:]]:
        db.set_dry_run(task_id)
    await task_queue.start(task_id)


@router.message(Command("jobs"))
async def jobs_cmd(message: Message):
    """What the bot is doing, what is queued, and how the last runs ended."""
    lang = user_lang(message.from_user)
    if _caller(message) is None:
        await _deny(message, lang)
        return

    lines = [localized("jobs_header", lang,
                       running=scheduler.running() or "—",
                       waiting=", ".join(scheduler.waiting()) or "—")]
    active = db.active_tasks()
    if active:
        lines.append(localized("jobs_active", lang))
        for row in active:
            lines.append(localized(
                "jobs_task", lang, id=row["id"], wiki=row["wiki"],
                state=row["state"],
                mechanics=", ".join(db.task_mechanics(row)),
                checked=row["checked"], total=db.count_pages(row["id"]),
                edited=row["edited"], failed=row["failed"]))
    for row in db.recent_tasks(RECENT_TASKS):
        if row["state"] in ("pending", "confirm", "running"):
            continue
        lines.append(localized(
            "jobs_finished", lang, id=row["id"], wiki=row["wiki"],
            state=row["state"], edited=row["edited"], failed=row["failed"],
            error=row["error"] or ""))
    await message.answer("\n".join(lines))


@router.message(Command("stop"))
async def stop_cmd(message: Message):
    """Stop a task. What it has already written stays written."""
    lang = user_lang(message.from_user)
    if _caller(message) is None:
        await _deny(message, lang)
        return
    parts = (message.text or "").split()[1:]
    if not parts or not parts[0].isdigit():
        await message.answer(localized("stop_usage", lang))
        return
    if await task_queue.stop(int(parts[0])):
        await message.answer(localized("stop_done", lang, id=int(parts[0])))
    else:
        await message.answer(localized("task_unknown", lang, id=int(parts[0])))


@router.message(Command("schedule"))
async def schedule_cmd(message: Message):
    """The repeating runs. `/schedule off|on|del <id>` changes one."""
    lang = user_lang(message.from_user)
    if _caller(message) is None:
        await _deny(message, lang)
        return

    parts = (message.text or "").split()[1:]
    if parts and parts[0].lower() in ("off", "on", "del", "delete"):
        if len(parts) < 2 or not parts[1].isdigit():
            await message.answer(localized("schedule_usage", lang))
            return
        schedule_id = int(parts[1])
        action = parts[0].lower()
        if action in ("del", "delete"):
            ok = db.delete_schedule(schedule_id)
            key = "schedule_deleted" if ok else "schedule_unknown"
        else:
            ok = db.set_enabled(schedule_id, action == "on")
            key = ("schedule_on" if action == "on" else "schedule_off") \
                if ok else "schedule_unknown"
        await message.answer(localized(key, lang, id=schedule_id))
        return

    rows = db.list_schedules()
    if not rows:
        await message.answer(localized("schedule_empty", lang))
        return
    lines = [localized("schedule_header", lang)]
    for row in rows:
        lines.append(localized(
            "schedule_line", lang, id=row["id"], wiki=row["wiki"],
            mechanics=", ".join(db.schedule_mechanics(row)),
            when=dialog.describe_schedule(row, lang),
            state=localized("schedule_state_on" if row["enabled"]
                            else "schedule_state_off", lang)))
    await message.answer("\n".join(lines))
