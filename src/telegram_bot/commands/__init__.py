"""The command modules, imported for their side effect.

A @router.message decorator registers when its module is imported, so a module
nobody imports registers nothing and the bot silently loses those commands.
Append new command modules here.
"""
from telegram_bot.commands import user
