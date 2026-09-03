"""The task commands on Discord: the catalogue, the runs and the schedules.

The same six commands the Telegram half has, as slash commands. Everything
they do lives in tasks/; this module takes the arguments apart and hands them
over, so the two messengers cannot drift apart on what a command means.

| Command | What it does |
|---|---|
| `/tasks` | the numbered catalogue of mechanics |
| `/run [что]` | build a task, in a dialog in this channel |
| `/go <id> [dry]` | confirm a planned task and set it going |
| `/jobs` | what is running, what is waiting, what has just finished |
| `/stop <id>` | stop a task where it stands |
| `/schedule [действие] [id]` | the repeating runs: list, off, on, delete |

A slash command has three seconds to answer, and a dialog takes minutes, so
`/run` answers the interaction at once and then talks in the channel
(discord_bot/dialogs.py).
"""
import logging

import discord
from discord import app_commands

import db
import scheduler
from discord_bot.client import tree
from discord_bot.dialogs import DiscordConversation
from tasks import access, dialog, queue as task_queue
from utils import localized, service_lang

logger = logging.getLogger("fd.discord.tasks")

RECENT_TASKS = 5

MESSAGE_LIMIT = 1900


def _caller(interaction):
    """Who is asking, or None when they may not ask."""
    user = interaction.user
    return access.caller("discord", user.id,
                         getattr(user, "name", None) or str(user))


async def _deny(interaction, lang):
    """The answer everyone who may not use these commands gets."""
    await interaction.response.send_message(localized("not_admin", lang),
                                            ephemeral=True)


async def _reply(interaction, text, ephemeral=False):
    """Answer an interaction with something that may be long."""
    body = str(text)
    await interaction.response.send_message(body[:MESSAGE_LIMIT],
                                            ephemeral=ephemeral)
    body = body[MESSAGE_LIMIT:]
    while body:
        await interaction.followup.send(body[:MESSAGE_LIMIT], ephemeral=ephemeral)
        body = body[MESSAGE_LIMIT:]


@tree.command(name="tasks", description="что бот умеет делать по вики")
async def tasks_cmd(interaction: discord.Interaction):
    """The catalogue: what the bot can be told to do, numbered."""
    lang = service_lang()
    if _caller(interaction) is None:
        await _deny(interaction, lang)
        return
    await _reply(interaction, dialog.mechanics_list(lang))


@tree.command(name="run", description="запустить работу по вики")
@app_commands.describe(what="номера или кодовые названия механик через пробел")
async def run_cmd(interaction: discord.Interaction, what: str = ""):
    """Build a task, in a dialog. `/run 1 4` skips the first question."""
    lang = service_lang()
    if _caller(interaction) is None:
        await _deny(interaction, lang)
        return
    await interaction.response.send_message(localized("dialog_opened", lang))
    conversation = DiscordConversation(interaction, lang)
    try:
        await dialog.build(conversation, (what or "").replace(",", " ").split())
    except Exception as e:
        logger.exception("the /run dialog failed")
        await conversation.say(localized("dialog_failed", lang, error=e))


@tree.command(name="go", description="подтвердить и запустить задачу")
@app_commands.describe(task_id="номер задачи", dry="только предпросмотр, без правок")
async def go_cmd(interaction: discord.Interaction, task_id: int, dry: bool = False):
    """Confirm a planned task and set it going."""
    lang = service_lang()
    if _caller(interaction) is None:
        await _deny(interaction, lang)
        return

    row = db.get_task(task_id)
    if row is None:
        await _reply(interaction, localized("task_unknown", lang, id=task_id))
        return
    if row["state"] != "confirm":
        await _reply(interaction, localized("task_not_waiting", lang, id=task_id,
                                            state=row["state"]))
        return
    if dry:
        db.set_dry_run(task_id)
    await interaction.response.send_message(
        localized("task_confirmed", lang, id=task_id))
    await task_queue.start(task_id)


@tree.command(name="jobs", description="что бот делает прямо сейчас")
async def jobs_cmd(interaction: discord.Interaction):
    """What the bot is doing, what is queued, and how the last runs ended."""
    lang = service_lang()
    if _caller(interaction) is None:
        await _deny(interaction, lang)
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
    await _reply(interaction, "\n".join(lines))


@tree.command(name="stop", description="остановить задачу")
@app_commands.describe(task_id="номер задачи")
async def stop_cmd(interaction: discord.Interaction, task_id: int):
    """Stop a task. What it has already written stays written."""
    lang = service_lang()
    if _caller(interaction) is None:
        await _deny(interaction, lang)
        return
    if await task_queue.stop(task_id):
        await _reply(interaction, localized("stop_done", lang, id=task_id))
    else:
        await _reply(interaction, localized("task_unknown", lang, id=task_id))


@tree.command(name="schedule", description="регулярные запуски")
@app_commands.describe(action="list, on, off или del", schedule_id="номер расписания")
async def schedule_cmd(interaction: discord.Interaction, action: str = "list",
                       schedule_id: int = 0):
    """The repeating runs, and switching one on or off."""
    lang = service_lang()
    if _caller(interaction) is None:
        await _deny(interaction, lang)
        return

    action = (action or "list").lower()
    if action in ("on", "off", "del", "delete"):
        if not schedule_id:
            await _reply(interaction, localized("schedule_usage", lang))
            return
        if action in ("del", "delete"):
            ok = db.delete_schedule(schedule_id)
            key = "schedule_deleted" if ok else "schedule_unknown"
        else:
            ok = db.set_enabled(schedule_id, action == "on")
            key = ("schedule_on" if action == "on" else "schedule_off") \
                if ok else "schedule_unknown"
        await _reply(interaction, localized(key, lang, id=schedule_id))
        return

    rows = db.list_schedules()
    if not rows:
        await _reply(interaction, localized("schedule_empty", lang))
        return
    lines = [localized("schedule_header", lang)]
    for row in rows:
        lines.append(localized(
            "schedule_line", lang, id=row["id"], wiki=row["wiki"],
            mechanics=", ".join(db.schedule_mechanics(row)),
            when=dialog.describe_schedule(row, lang),
            state=localized("schedule_state_on" if row["enabled"]
                            else "schedule_state_off", lang)))
    await _reply(interaction, "\n".join(lines))
