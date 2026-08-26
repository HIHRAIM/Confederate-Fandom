"""The three commands the bot answers: /help, /status and /update.

All three are for the bot's administrators (config.ADMINS) — the bot has
nothing to say to anyone else, and /update writes to the wiki. Replies are
plain text in the language of the person who asked (utils.user_lang), which is
why nothing here formats with HTML: a post's text can contain anything, and
plain text cannot be broken by it.

The publishing pass itself lives in publisher.py and is imported at the call
site: publisher reaches back into this half to download a picture, and the two
would otherwise import each other at module level.
"""
import logging

from aiogram.filters import Command
from aiogram.types import Message

import db
import news
from config import NEWS_TEMPLATES, SOURCE_CHANNEL, WIKIS
from telegram_bot.client import router, source_chat_id, source_username
from utils import is_admin, localized, publish_schedule, user_lang, wiki_key

logger = logging.getLogger("tprp.commands")

STATUS_PREVIEW_LIMIT = 80

def _primary_wiki():
    """The wiki /status reads the slots from: the first of config.WIKIS.

    Every wiki carries the same three news, so one of them is enough to say
    what is published; a wiki that has fallen behind the others shows up in
    the error line instead."""
    return WIKIS[0] if WIKIS else None

def _deny(message, lang):
    """The reply everyone who is not an administrator gets."""
    return message.answer(localized("not_admin", lang))

def _channel_name():
    """The source channel as /status prints it: the @name it resolved to and
    its numeric id, or the configured value while it is unresolved."""
    chat_id = source_chat_id()
    if chat_id is None:
        return str(SOURCE_CHANNEL)
    username = source_username()
    return "@{} ({})".format(username, chat_id) if username else str(chat_id)

def _last_pass(lang):
    """When the last pass ran, as a local timestamp, or the 'never yet' text."""
    stored = db.get_state("last_pass_ts")
    if not stored:
        return localized("status_never", lang)
    from datetime import datetime, timezone
    moment = datetime.fromtimestamp(int(stored), timezone.utc).astimezone(news.news_timezone())
    return moment.strftime("%d.%m.%Y %H:%M")

def _slot_lines(lang):
    """One line per news slot, in slot order, as /status prints them.

    The line is built from the post the slot came from when it is still
    stored; a post that has already fallen off the end of channel_posts leaves
    the date of the publishing pass and no preview, which is enough to tell
    that the slot is filled and how old it is."""
    primary = _primary_wiki()
    if primary is None:
        return ""
    key = wiki_key(primary)
    titles = primary.get("templates") or NEWS_TEMPLATES
    lines = []
    for slot in range(1, len(titles) + 1):
        row = db.get_slot(key, slot)
        if row is None or not row["message_id"]:
            lines.append(localized("status_slot_empty", lang, slot=slot))
            continue
        post = db.get_post(row["chat_id"], row["message_id"])
        date = news.format_date(post["date"] if post else row["published_at"])
        preview = (news.shorten(post["text"], STATUS_PREVIEW_LIMIT).replace("\n", " ")
                   if post else "")
        link = news.post_link(source_username(), row["message_id"]) or "—"
        lines.append(localized("status_slot", lang, slot=slot, date=date, link=link, text=preview))
    return "\n".join(lines)

@router.message(Command("help"))
async def help_cmd(message: Message):
    """What the bot does and which three commands it takes."""
    lang = user_lang(message.from_user)
    if not is_admin(message.from_user.id if message.from_user else 0):
        await _deny(message, lang)
        return
    await message.answer(localized("help", lang))

@router.message(Command("status"))
async def status_cmd(message: Message):
    """What the three slots hold, where they come from and when they were
    last rebuilt."""
    lang = user_lang(message.from_user)
    if not is_admin(message.from_user.id if message.from_user else 0):
        await _deny(message, lang)
        return

    chat_id = source_chat_id()
    error = db.get_state("last_error") or ""
    await message.answer(localized(
        "status", lang,
        channel=_channel_name(),
        wiki=", ".join(wiki_key(w) for w in WIKIS) or "—",
        posts=db.count_posts(chat_id) if chat_id is not None else 0,
        schedule=publish_schedule(),
        last_pass=_last_pass(lang),
        error=localized("status_error", lang, error=error) if error else "",
        slots=_slot_lines(lang),
    ))

@router.message(Command("update"))
async def update_cmd(message: Message):
    """Run a publishing pass now instead of waiting for the next one.

    ``/update force`` additionally forgets which picture each slot holds, so
    all three files are uploaded again — the answer to a file that was changed
    or deleted on the wiki behind the bot's back."""
    lang = user_lang(message.from_user)
    if not is_admin(message.from_user.id if message.from_user else 0):
        await _deny(message, lang)
        return

    import publisher

    if publisher.is_running():
        await message.answer(localized("update_busy", lang))
        return

    force = "force" in (message.text or "").lower()
    await message.answer(localized("update_started", lang))
    try:
        result = await publisher.run_pass(force=force)
    except Exception as e:
        logger.exception("manual pass failed")
        await message.answer(localized("update_failed", lang, error=e))
        return

    if result["have"] == 0:
        await message.answer(localized("update_no_news", lang))
        return
    if result["templates"] or result["files"]:
        await message.answer(localized(
            "update_done", lang, templates=result["templates"], files=result["files"]))
    else:
        await message.answer(localized("update_unchanged", lang))
    if result["have"] < result["count"]:
        await message.answer(localized(
            "update_partial", lang, have=result["have"], count=result["count"]))

@router.message(Command("backfill"))
async def backfill_cmd(message: Message):
    """Read the channel's public web preview now: add the posts the bot was
    not there for, and refresh the ones it took from the preview before.

    ``/backfill all`` additionally refreshes the posts the bot heard from
    Telegram itself — the answer to a post that was edited while the bot was
    down. It is not the default because the preview's copy of a post is the
    poorer one: its pictures are smaller and it sometimes shortens a long link,
    and rewriting good rows with it would churn the templates for nothing.

    The channel needs a public @name: the preview is addressed by name."""
    lang = user_lang(message.from_user)
    if not is_admin(message.from_user.id if message.from_user else 0):
        await _deny(message, lang)
        return

    chat_id = source_chat_id()
    username = source_username()
    if chat_id is None or not username:
        await message.answer(localized("backfill_no_channel", lang))
        return

    from backfill import sync

    refresh_all = "all" in (message.text or "").lower().split()
    await message.answer(localized("backfill_started", lang))
    try:
        seen, added, updated = await sync(chat_id, username, refresh_all=refresh_all)
    except Exception as e:
        logger.warning("manual preview sync failed: %s", e)
        await message.answer(localized("backfill_failed", lang, error=e))
        return
    await message.answer(localized(
        "backfill_done", lang, seen=seen, added=added, updated=updated))
