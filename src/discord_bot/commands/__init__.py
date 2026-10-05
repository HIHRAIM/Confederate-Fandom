"""The command modules, imported for their side effect.

A @tree.command decorator registers when its module is imported, so a module
nobody imports registers nothing and the bot silently loses those commands.
Append new command modules here.

The tree is synced once when the gateway comes up (discord_bot/client.py:
on_ready), so a command added here appears in Discord after a restart and not
before.
"""
from discord_bot.commands import tasks
from discord_bot.commands import admins
from discord_bot.commands import sponsors
