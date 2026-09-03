"""The Telegram half of the bot, as a package.

Importing it builds the aiogram objects and registers every handler: the
import order below runs the @router.* decorators of each module. Client first,
then the domain module that collects the channel's posts, then the commands,
and **catchall last**.

That last one is not a matter of taste. aiogram dispatches in registration
order and telegram_bot/catchall.py is a ``@router.message()`` with no filter
at all — the handler that feeds the dialogs. Registered any earlier it
silently swallows every command below it and the bot answers nothing.

The re-exports are the package's public API: `bot` is the aiogram Bot every
other module reaches for as ``telegram_bot.bot``, and `main` is the polling
task main.py gathers.
"""
from telegram_bot.client import (
    bot,
    dp,
    is_source_chat,
    main,
    resolve_source_channel,
    router,
    source_chat_id,
    source_username,
)
from telegram_bot.files import download_photo
from telegram_bot import channel
from telegram_bot import commands
from telegram_bot import catchall
