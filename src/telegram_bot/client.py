"""The aiogram objects (bot, dispatcher, router), the polling entry point, and
the resolution of the source channel.

Named client.py rather than bot.py on purpose: the package re-exports the Bot
instance as ``telegram_bot.bot`` — that is how the rest of the codebase reaches
it — and a submodule of that same name would shadow the instance on the
package object.

The source channel is resolved once and remembered. config.SOURCE_CHANNEL may
be a @name or a numeric id, but an update carries only the numeric one, so the
bot asks Telegram what the configured channel is and keeps the answer both in
memory (`_source`, the module-level cache below) and in the database, where
/status reads it and where it survives a restart. The @name is kept for the
same trip: it is what the link under every news picture is built from.
"""
import logging

from aiogram import Bot, Dispatcher, Router

import db
from config import SOURCE_CHANNEL, TELEGRAM_TOKEN

logger = logging.getLogger("tprp.telegram")

bot = Bot(TELEGRAM_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

_source = {"chat_id": None, "username": None}

def source_chat_id():
    """The numeric id of the source channel, or None while it is unresolved.

    Answered from the in-memory cache, then from the database — a restart must
    not make the bot forget which channel its stored posts came from."""
    if _source["chat_id"] is None:
        stored = db.get_state("source_chat_id")
        if stored:
            _source["chat_id"] = int(stored)
            _source["username"] = db.get_state("source_username") or None
    return _source["chat_id"]

def source_username():
    """The @name of the source channel without the '@', or None for a channel
    that has none. The links of the news are built from it."""
    source_chat_id()
    return _source["username"]

async def resolve_source_channel():
    """Ask Telegram which channel config.SOURCE_CHANNEL names and remember it.

    Raises whatever aiogram raises when the channel cannot be read — a wrong
    name in config and a bot that was never added to the channel both look
    like that, and both are worth reporting to the service chats rather than
    swallowing (main.py does the reporting).

    A channel that turns out to be a different one than the database was
    filled from takes the old channel's posts with it: they can never become a
    news again, and keeping them would be holding on to somebody's posts for
    nothing."""
    previous = db.get_state("source_chat_id")
    chat = await bot.get_chat(SOURCE_CHANNEL)
    _source["chat_id"] = chat.id
    _source["username"] = chat.username or None
    db.set_state("source_chat_id", chat.id)
    db.set_state("source_username", chat.username or "")
    logger.info("source channel resolved: %s (@%s)", chat.id, chat.username or "-")
    if previous and int(previous) != chat.id:
        dropped = db.forget_other_channels(chat.id)
        logger.info("the source channel changed from %s — %s stored post(s) dropped",
                    previous, dropped)
    return chat

def is_source_chat(chat):
    """Whether an update came from the channel the bot is following.

    Falls back to matching config.SOURCE_CHANNEL itself while the channel is
    unresolved — the first posts must not be lost because the resolving call
    failed once at start-up."""
    if chat is None:
        return False
    known = source_chat_id()
    if known is not None:
        return chat.id == known
    configured = str(SOURCE_CHANNEL).strip()
    if configured.lstrip("-").isdigit():
        return chat.id == int(configured)
    return (chat.username or "").lower() == configured.lstrip("@").lower()

async def main():
    """Start long polling. Runs as one of the tasks main.py gathers."""
    await dp.start_polling(bot)
