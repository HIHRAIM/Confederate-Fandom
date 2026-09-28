"""Getting a task's answers back to the person, and to the service log.

Two destinations, and a task writes to both:

* **the person who asked** — wherever they asked from. The chat is stored on
  the task row as ``'<platform>:<chat>[:<thread>]'`` so that a run which
  finishes an hour later, or after a restart, still knows where to answer.
* **the service log** — the Discord channel and the Telegram topic of
  config.SERVICE_CHATS. Every task says there that it started, how it is
  going and how it ended, naming who asked for it by their username and id in
  brackets, never by a mention: a log that pings somebody every quarter of an
  hour is a log people mute.

Everything sent from here is guarded. The service log is where failures are
reported, so a failure to report must stay a line in the bot's own log and
never take down the run that was reporting.

Not this module's zone: what the messages say (i18n/, the commands) and what
may go into a file (tasks/report.py: safe_error).
"""
import logging
import os

logger = logging.getLogger("fd.tasks.notify")

MESSAGE_LIMIT = 3500


def parse_chat(key):
    """'<platform>:<chat>[:<thread>]' -> (platform, chat, thread) or None."""
    parts = str(key or "").split(":")
    if len(parts) < 2 or not parts[0]:
        return None
    platform = parts[0]
    chat = parts[1]
    thread = parts[2] if len(parts) > 2 else None
    try:
        chat = int(chat)
    except ValueError:
        return None
    try:
        thread = int(thread) if thread else None
    except ValueError:
        thread = None
    return platform, chat, thread


def chat_key(platform, chat_id, thread=None):
    """The stored form of one chat, as `parse_chat` reads it back."""
    if thread:
        return "{}:{}:{}".format(platform, chat_id, thread)
    return "{}:{}".format(platform, chat_id)


async def send(key, text):
    """One message to the chat a task was asked from. Never raises."""
    target = parse_chat(key)
    if target is None:
        return
    platform, chat, thread = target
    body = str(text)[:MESSAGE_LIMIT]
    try:
        if platform == "telegram":
            from telegram_bot import bot

            await bot.send_message(chat, body, message_thread_id=thread or None)
        elif platform == "discord":
            from discord_bot import send_log

            await send_log(chat, body)
    except Exception as e:
        logger.warning("could not answer %s: %s", key, e)


async def send_files(key, paths, caption=None, lang=None):
    """The files a task produced, to the chat it was asked from.

    A file that is not there is skipped rather than reported: a task that
    changed nothing leaves no diff, and saying so twice helps nobody. `lang`
    is the reader's, for the line Discord adds about a file too large to
    attach.
    """
    target = parse_chat(key)
    if target is None:
        return
    platform, chat, thread = target
    real = [path for path in (paths or []) if path and os.path.exists(path)]
    if not real:
        return
    try:
        if platform == "telegram":
            from aiogram.types import FSInputFile

            from telegram_bot import bot

            for index, path in enumerate(real):
                await bot.send_document(
                    chat, FSInputFile(path),
                    caption=caption if index == 0 else None,
                    message_thread_id=thread or None)
        elif platform == "discord":
            from discord_bot import send_files as discord_files

            await discord_files(chat, real, caption, lang)
    except Exception as e:
        logger.warning("could not send the files of a task to %s: %s", key, e)


async def to_person(platform, user_id, text, fallback=None):
    """A private message to one person; `fallback` is a chat key to use when
    the messenger will not deliver it (a Telegram user who never opened a
    chat with the bot, a Discord user who closed their DMs). Never raises.
    -> whether it reached them one way or the other."""
    try:
        if platform == "telegram":
            from telegram_bot import bot

            await bot.send_message(int(user_id), str(text)[:MESSAGE_LIMIT])
            return True
        if platform == "discord":
            from discord_bot.client import client

            user = client.get_user(int(user_id)) or await client.fetch_user(int(user_id))
            await user.send(str(text)[:MESSAGE_LIMIT])
            return True
    except Exception as e:
        logger.info("no private message to %s:%s: %s", platform, user_id, e)
    if fallback:
        await send(fallback, text)
        return True
    return False


async def request_approval(schedule_id):
    """Ask a bot administrator whether a repeating run may start.
    -> whether the question reached a channel. The asking is Discord's
    (discord_bot/approvals.py): that is where the buttons are."""
    from discord_bot import approvals

    return await approvals.request(schedule_id)


async def announce(text, files=None):
    """One line into every service chat, on both messengers.

    This is where a task says it began, how far it has got and how it ended.
    """
    from utils import service_chat_keys

    for key in service_chat_keys():
        await send(key, text)
        if files:
            await send_files(key, files)




