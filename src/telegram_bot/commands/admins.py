"""Appointing wiki administrators on Telegram, and the database backup.

Four commands live here. Appointment and backup commands require a bot
administrator; the person holding an invitation can use /claimwikiadmin.

    /wikiadmin                          — who is appointed, and who is invited
    /wikiadmin <@ник или ID> <ник на Fandom>
    /claimwikiadmin                     — confirm an invitation in a private chat
    /remwikiadmin <@ник или ID>
    /backup                             — the database, encrypted

The same shape as on Discord: the person, then their Fandom account, typed
into the command. The Fandom name is not optional and not guessed. It is what
the bot checks on the wiki before every run that person asks for
(wiki/rights.py: is_wiki_staff), so an appointment without it would be an
appointment that cannot be used. Re-running the command with a different name
is how a name is corrected.

What the bot remembers is the numeric id, never the @name, so that an @name
given up and taken by somebody else does not take the appointment with it.
Telegram does not tell a bot whose an @name is, so an @name first becomes an
invitation and becomes an appointment when its holder writes to the bot
(telegram_bot/people.py). A numeric id, or a person picked from Telegram's own
list, is appointed at once.
"""
import logging
import time

from aiogram.filters import Command
from aiogram.types import Message

import db
from telegram_bot import people
from telegram_bot.client import router
from utils import is_admin, localized, user_lang

logger = logging.getLogger("fd.telegram.admins")

@router.message(Command("wikiadmin"))
async def wikiadmin_cmd(message: Message):
    """Appoint somebody, or list who is appointed."""
    from tasks import lists

    lang = user_lang(message.from_user)
    if not is_admin("telegram", message.from_user.id if message.from_user else 0):
        await message.answer(localized("not_admin", lang))
        return

    if len((message.text or "").split()) < 2:
        title, lines = lists.wiki_admins(lang)
        if not lines:
            await message.answer(localized("wikiadmin_empty", lang))
            return
        await message.answer("\n".join([title] + lines))
        return

    user_id, display, username, wiki_user = await people.resolve(message)
    if user_id is None and username is None:
        await message.answer(localized("wikiadmin_no_user", lang))
        return
    if not wiki_user:
        await message.answer(localized("wikiadmin_no_wiki_user", lang))
        return

    added_by = str(message.from_user.id)
    if user_id is None:
        db.add_wiki_admin_invite(username, wiki_user, added_by=added_by)
        await message.answer(localized(
            "wikiadmin_invited", lang, username=username, wiki_user=wiki_user,
            until=lists.invite_until(time.time())))
        return

    existed = db.get_wiki_admin("telegram", user_id) is not None
    db.add_wiki_admin("telegram", user_id, wiki_user, display, added_by=added_by)
    await message.answer(localized(
        "wikiadmin_updated" if existed else "wikiadmin_added", lang,
        name=display or user_id, user_id=user_id, wiki_user=wiki_user))

@router.message(Command("claimwikiadmin"))
async def claimwikiadmin_cmd(message: Message):
    """Show the sender whether their invitation became an ID appointment.

    The outer middleware tries to claim before this handler. A direct retry
    also covers a missed middleware pass; when there is no match, the sender
    receives their numeric ID so a Bot Admin can appoint them explicitly.
    """
    user = message.from_user
    if user is None:
        return
    lang = user_lang(user)
    if message.chat.type != "private":
        await message.answer(localized("wikiadmin_claim_private", lang))
        return
    if user.username and db.get_wiki_admin("telegram", user.id) is None:
        await people.claim_invitation(user)
    appointment = db.get_wiki_admin("telegram", user.id)
    if appointment is not None:
        await message.answer(localized("wikiadmin_claim_confirmed", lang,
                                       wiki_user=appointment["wiki_user"],
                                       user_id=user.id))
    elif user.username:
        await message.answer(localized("wikiadmin_claim_missing", lang,
                                       username=user.username, user_id=user.id))
    else:
        await message.answer(localized("wikiadmin_claim_no_username", lang,
                                       user_id=user.id))

@router.message(Command("remwikiadmin"))
async def remwikiadmin_cmd(message: Message):
    """Take an appointment away, or withdraw an invitation.

    An @name is looked for first among the invitations, then among the names
    the appointed people were last seen under. The list shows every id, so a
    person whose @name has changed is still one command away."""
    lang = user_lang(message.from_user)
    if not is_admin("telegram", message.from_user.id if message.from_user else 0):
        await message.answer(localized("not_admin", lang))
        return

    user_id, _display, username, _rest = await people.resolve(message)
    if user_id is None and username is not None:
        if db.remove_wiki_admin_invite(username):
            await message.answer(localized("wikiadmin_invite_removed", lang,
                                           username=username))
            return
        named = db.wiki_admins_named("telegram", "@" + username)
        if len(named) == 1:
            user_id = named[0]["user_id"]
    if user_id is None:
        await message.answer(localized("wikiadmin_no_user", lang))
        return
    if db.remove_wiki_admin("telegram", user_id):
        await message.answer(localized("wikiadmin_removed", lang, user_id=user_id))
    else:
        await message.answer(localized("wikiadmin_not_found", lang, user_id=user_id))

@router.message(Command("backup"))
async def backup_cmd(message: Message):
    """Send an encrypted snapshot of the database to whoever asked.

    The same file, and the same format, the twice-daily job sends to
    config.BACKUP_CHATS; this is the on-demand half of it, for the moment
    before somebody edits something they are not sure about.

    **Private chats only.** The file is the whole database, and a group keeps
    it for as long as the group exists — an administrators' group included.
    Encryption is what makes the file safe to store, not safe to hand round,
    so the one place it is sent is the chat between the bot and the person who
    asked. Without BACKUP_KEY the bot says so and sends nothing: a plaintext
    database is never the fallback.
    """
    lang = user_lang(message.from_user)
    if not is_admin("telegram", message.from_user.id if message.from_user else 0):
        await message.answer(localized("not_admin", lang))
        return
    if message.chat.type != "private":
        await message.answer(localized("backup_private_only", lang))
        return

    import asyncio

    from aiogram.types import BufferedInputFile

    import backup_crypto
    from tasks import report

    if not backup_crypto.available():
        await message.answer(localized("backup_no_key", lang))
        return
    try:
        data = await asyncio.to_thread(backup_crypto.build_backup)
    except Exception as e:
        logger.exception("the backup could not be built")
        await message.answer(localized("backup_failed", lang,
                                       error=report.safe_error(e)))
        return
    await message.answer_document(
        BufferedInputFile(data, filename=backup_crypto.backup_filename()))
