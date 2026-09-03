"""The command modules, imported for their side effect.

A @router.message decorator registers when its module is imported, so a module
nobody imports registers nothing and the bot silently loses those commands.
Append new command modules here.

Order is registration order and registration order is dispatch order. It does
not matter between these three — they answer different commands — but it
matters that telegram_bot/catchall.py comes after all of them, which is the
package's job and not this one's.
"""
from telegram_bot.commands import user
from telegram_bot.commands import tasks
from telegram_bot.commands import admins
