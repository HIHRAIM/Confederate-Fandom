"""Appointing wiki administrators on Telegram.

Two commands, and only a bot administrator may use them: control of the bot
lives in config.ADMINS and nothing stored can hand it out.

    /wikiadmin                       — who is appointed
    /wikiadmin <@ник или ID> <ник на Fandom>
    /remwikiadmin <@ник или ID>

The Fandom name is not optional and not guessed. It is what the bot checks on
the wiki before every run that person asks for (wiki/rights.py:
is_wiki_staff), so an appointment without it would be an appointment that
cannot be used. Re-running the command with a different name is how a name is
corrected.

Somebody can be named three ways — by replying to their message, by their
@name, or by their numeric id — because a person who has never written in this
chat has no message to reply to, and a person with no @name has only an id.
"""
import logging

from aiogram.filters import Command
from aiogram.types import Message

import db
from telegram_bot.client import bot, router
from utils import is_admin, localized, user_lang

logger = logging.getLogger("fd.telegram.admins")


async def _resolve(message, token):
    """Who a person meant. -> (numeric id, display name) or (None, None).

    A reply wins over anything typed, because replying is the unambiguous way
    to point at somebody.
    """
    if message.reply_to_message and message.reply_to_message.from_user:
        user = message.reply_to_message.from_user
        return user.id, ("@" + user.username) if user.username else user.full_name
    for entity in (message.entities or []):
        if entity.type == "text_mention" and entity.user:
            user = entity.user
            return user.id, ("@" + user.username) if user.username else user.full_name

    raw = (token or "").strip()
    if raw.isdigit():
        return int(raw), None
    if raw.startswith("@"):
        try:
            chat = await bot.get_chat(raw)
            return chat.id, raw
        except Exception as e:
            logger.info("could not resolve %s: %s", raw, e)
    return None, None


@router.message(Command("wikiadmin"))
async def wikiadmin_cmd(message: Message):
    """Appoint somebody, or list who is appointed."""
    lang = user_lang(message.from_user)
    if not is_admin("telegram", message.from_user.id if message.from_user else 0):
        await message.answer(localized("not_admin", lang))
        return

    parts = (message.text or "").split()[1:]
    if not parts:
        rows = db.list_wiki_admins()
        if not rows:
            await message.answer(localized("wikiadmin_empty", lang))
            return
        lines = [localized("wikiadmin_header", lang)]
        for row in rows:
            lines.append(localized(
                "wikiadmin_line", lang, platform=row["platform"],
                name=row["display_name"] or row["user_id"],
                user_id=row["user_id"], wiki_user=row["wiki_user"]))
        await message.answer("\n".join(lines))
        return

    user_id, display = await _resolve(message, parts[0])
    wiki_user = " ".join(parts[1:]).strip() if len(parts) > 1 else ""
    if message.reply_to_message and not wiki_user:
        wiki_user = " ".join(parts).strip()
    if user_id is None:
        await message.answer(localized("wikiadmin_no_user", lang))
        return
    if not wiki_user:
        await message.answer(localized("wikiadmin_no_wiki_user", lang))
        return

    existed = db.get_wiki_admin("telegram", user_id) is not None
    db.add_wiki_admin("telegram", user_id, wiki_user, display,
                      added_by=str(message.from_user.id))
    await message.answer(localized(
        "wikiadmin_updated" if existed else "wikiadmin_added", lang,
        name=display or user_id, user_id=user_id, wiki_user=wiki_user))


@router.message(Command("remwikiadmin"))
async def remwikiadmin_cmd(message: Message):
    """Take an appointment away."""
    lang = user_lang(message.from_user)
    if not is_admin("telegram", message.from_user.id if message.from_user else 0):
        await message.answer(localized("not_admin", lang))
        return

    parts = (message.text or "").split()[1:]
    user_id, _display = await _resolve(message, parts[0] if parts else "")
    if user_id is None:
        await message.answer(localized("wikiadmin_no_user", lang))
        return
    if db.remove_wiki_admin("telegram", user_id):
        await message.answer(localized("wikiadmin_removed", lang, user_id=user_id))
    else:
        await message.answer(localized("wikiadmin_not_found", lang, user_id=user_id))
