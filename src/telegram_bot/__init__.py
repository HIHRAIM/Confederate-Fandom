"""The Telegram half of the bot, as a package.

Importing it builds the aiogram objects and registers every handler: the
import order below runs the @router.* decorators of each module. Client first,
then the domain module that collects the channel's posts, then the commands —
aiogram dispatches in registration order, and although these cannot collide
(a channel post and a private command are different update types), keeping the
ladder in dependency order means it reads the way it dispatches.

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
