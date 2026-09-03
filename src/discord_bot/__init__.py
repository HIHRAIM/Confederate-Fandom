"""The Discord half of the bot, as a package.

Import order is registration order: the client and its command tree first, then
the command modules, whose @tree.command decorators fire on import. A module
nobody imports registers nothing and the bot silently loses those commands.

Two jobs now, where there used to be one. The service reports still go to the
channels of config.SERVICE_CHATS — that is what `send_log` and `send_files`
are for — and the same commands the Telegram half answers are here as slash
commands, with the dialogs held in the channel they were started in
(discord_bot/dialogs.py).

The re-exports are the package's public API: `client` for anything that needs
the connection itself, `main` for the task main.py waits on, `send_log` and
`send_files` for tasks/notify.py.
"""
from discord_bot.client import client, main, send_files, send_log, tree
from discord_bot import commands
