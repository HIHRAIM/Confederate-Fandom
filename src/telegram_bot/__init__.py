"""The Telegram half of the bot, as a package.

Importing it builds the aiogram objects and registers every handler: the
import order below runs the @router.* decorators of each module. Client first,
then the domain module that collects the channel's posts, then the commands,
and **catchall last**.

That last one is not a matter of taste. aiogram dispatches in registration
order and telegram_bot/catchall.py is a ``@router.message()`` with no filter
at all — the handler that feeds the dialogs. Registered any earlier it
silently swallows every command below it and the bot answers nothing.

`people` registers no handler. It puts an outer middleware in front of all of
them, on messages and on button presses: the check that turns an invitation
made by @name into an appointment keyed by the id, before the handler that
answers the person's first message decides whether they may ask.

`pages` comes before the commands because the commands reach for it, and
because it registers the one ``@router.callback_query`` in this half — the
arrows under a paged answer. Callback queries are dispatched on a chain of
their own, so it is in no danger from the catchall below; it is placed here to
be found where every other registration is.

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
from telegram_bot import people
from telegram_bot import channel
from telegram_bot import pages
from telegram_bot import commands
from telegram_bot import catchall
