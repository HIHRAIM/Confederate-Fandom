"""How the Telegram half holds a conversation.

This is where the two halves differ most. Discord can block on
`bot.wait_for(...)` inside a command; aiogram has no such facility, so
`wait_for_message` parks a future in `_pending_inputs` keyed by
``(chat_id, user_id)``, and it is telegram_bot/catchall.py — a
``@router.message()`` with no filter at all — that receives the answer and
resolves the future.

That is why the catchall must be registered **last**: aiogram dispatches in
registration order, and a handler with no filter registered before the
commands would swallow every one of them.

`_pending_inputs` must exist exactly once, declared here and imported by name
everywhere else. Two modules each declaring "their own" copy is the classic
split bug — the catchall writes one dict, the waiting dialog reads the other,
and the dialog hangs until it times out.

A dialog that never gets its answer simply times out after DIALOG_TIMEOUT and
the task is never created, which is the right outcome: a half-answered task is
worse than none.
"""
import asyncio
import logging

from tasks.dialog import Conversation
from tasks.notify import chat_key
from utils import user_lang

logger = logging.getLogger("fd.telegram.dialogs")

DIALOG_TIMEOUT = 15 * 60

_pending_inputs = {}


async def wait_for_message(chat_id, user_id, timeout=DIALOG_TIMEOUT):
    """Wait for one person's next message in one chat. -> the text, or None.

    A second dialog with the same person in the same chat cancels the first:
    somebody who starts over with a fresh command means it, and two futures on
    one key would leave the older dialog waiting for a message that will be
    handed to the newer one.
    """
    key = (chat_id, user_id)
    old = _pending_inputs.pop(key, None)
    if old and not old.done():
        old.cancel()
    future = asyncio.get_running_loop().create_future()
    _pending_inputs[key] = future
    try:
        return await asyncio.wait_for(future, timeout)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        return None
    finally:
        if _pending_inputs.get(key) is future:
            _pending_inputs.pop(key, None)


def deliver(chat_id, user_id, text):
    """Hand one message to whoever is waiting for it. -> whether anyone was.

    Called by the catchall for every message that is not a command. A False
    here means nobody was in a dialog and the message is somebody talking in
    the chat, which is none of the bot's business.
    """
    future = _pending_inputs.get((chat_id, user_id))
    if future is None or future.done():
        return False
    future.set_result(text)
    return True


class TelegramConversation(Conversation):
    """The dialog driver for Telegram: send, then park a future.

    Built from the message that started the dialog, so the answers go back to
    the same chat and the same topic, and the task remembers that chat for the
    report it will send when the run finishes an hour later.
    """

    def __init__(self, message):
        """Take who and where from the message that started it."""
        user = message.from_user
        super().__init__(
            platform="telegram",
            user_id=user.id if user else 0,
            display_name=(user.username and "@" + user.username)
            or (user.full_name if user else None),
            chat_key=chat_key("telegram", message.chat.id,
                              message.message_thread_id),
            lang=user_lang(user))
        self.message = message

    async def say(self, text):
        """Send something that needs no answer."""
        await self.message.answer(str(text))

    async def ask(self, text):
        """Send a question and wait for this person's next message here."""
        await self.message.answer(str(text))
        return await wait_for_message(self.message.chat.id, self.user_id)
