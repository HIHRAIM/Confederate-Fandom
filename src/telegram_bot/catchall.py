"""The handler that feeds the dialogs, and it must be registered last.

One ``@router.message()`` with no filter at all. aiogram dispatches in
registration order, so this module is imported after every command module
(telegram_bot/__init__.py) — registered any earlier it would silently swallow
every command below it, and the bot would answer nothing.

All it does is hand the message to whoever is waiting for it
(telegram_bot/dialogs.py: deliver). A message nobody is waiting for is left
alone: people talk in the chats the bot sits in, and none of that is the
bot's business.

Commands are never delivered to a dialog. Somebody who types `/status` in the
middle of a dialog has changed their mind, and treating the command as an
answer would both lose the command and put nonsense into the task.
"""
import logging

from aiogram.types import Message

from telegram_bot.client import router
from telegram_bot.dialogs import deliver

logger = logging.getLogger("fd.telegram.catchall")


@router.message()
async def _dialog_catchall(message: Message):
    """Give one message to the dialog waiting for it, if there is one."""
    if message.from_user is None:
        return
    text = message.text or message.caption or ""
    if text.startswith("/"):
        return
    deliver(message.chat.id, message.from_user.id, text)
