"""Pair Telegram with a Discord subscription and show its shared budget."""
from aiogram.filters import Command
from aiogram.types import Message

import db
import sponsors
from config import SPONSOR_URL
from telegram_bot.client import router
from utils import is_admin, localized, user_lang

@router.message(Command("sponsor_link"))
async def sponsor_link_cmd(message: Message):
    """Consume the code issued to the Discord account in a private chat."""
    lang = user_lang(message.from_user)
    if message.chat.type != "private" or message.from_user is None:
        await message.answer(localized("sponsor_link_private", lang))
        return
    parts = (message.text or "").split()
    if len(parts) != 2:
        await message.answer(localized("sponsor_link_usage", lang))
        return
    owner = db.consume_sponsor_link_code(message.from_user.id, parts[1])
    await message.answer(localized(
        "sponsor_linked" if owner else "sponsor_link_invalid", lang))

@router.message(Command("sponsor_unlink"))
async def sponsor_unlink_cmd(message: Message):
    """Revoke this Telegram account's link without Discord access."""
    lang = user_lang(message.from_user)
    changed = bool(message.from_user and db.unlink_sponsor_account(
        "telegram", message.from_user.id))
    await message.answer(localized(
        "sponsor_unlinked" if changed else "sponsor_link_missing", lang))

@router.message(Command("sponsor"))
async def sponsor_cmd(message: Message):
    """Show the same wiki and task budget as the linked Discord account."""
    lang = user_lang(message.from_user)
    owner = sponsors.canonical_id("telegram", message.from_user.id) if message.from_user else None
    if not owner:
        await message.answer(localized("sponsor_link_missing", lang))
        return
    tier = await sponsors.refresh_tier(owner)
    caps = sponsors.limits(tier)
    tasks, pages = db.sponsor_usage(owner)
    wikis = db.claimed_wikis(owner)
    status = localized(
        "sponsor_status", lang,
        tier=(localized("sponsor_tier_community", lang) if tier == -1 else tier),
        wikis=len(wikis),
        wiki_limit=caps["wikis"], tasks=tasks, task_limit=caps["tasks"],
        pages=pages, page_limit=caps["pages"],
        names=", ".join(row["wiki"] for row in wikis) or "—", url=SPONSOR_URL)
    status += "\n" + localized("sponsor_community_usage", lang,
                                 communities=len(db.claimed_communities(owner)),
                                 limit=caps["communities"])
    addendum = sponsors.status_addendum(owner, lang)
    if addendum:
        status += "\n" + addendum
    wait = db.sponsor_slot_wait_days(owner)
    if wait:
        status += "\n" + localized("sponsor_slot_wait", lang, days=wait)
    await message.answer(status)

@router.message(Command("sponsor_community"))
async def sponsor_community_cmd(message: Message):
    """Claim this group for the linked Discord subscription."""
    lang = user_lang(message.from_user)
    if message.chat.type not in ("group", "supergroup") or message.from_user is None:
        await message.answer(localized("sponsor_community_here", lang))
        return
    admin = is_admin("telegram", message.from_user.id)
    if not admin:
        from telegram_bot.client import bot
        try:
            member = await bot.get_chat_member(message.chat.id, message.from_user.id)
            status = str(member.status).lower().split(".")[-1]
        except Exception:
            status = ""
        if status not in ("administrator", "creator"):
            await message.answer(localized("sponsor_community_manage", lang))
            return
    owner_id = sponsors.canonical_id("telegram", message.from_user.id)
    if not owner_id and not admin:
        await message.answer(localized("sponsor_link_missing", lang))
        return
    tier = await sponsors.refresh_tier(owner_id) if owner_id else 0
    if tier == 0 and not admin:
        await message.answer(localized("sponsor_not_active", lang, url=SPONSOR_URL))
        return
    owner = f"admin:telegram:{message.from_user.id}" if admin else owner_id
    row = db.community_claim("telegram", message.chat.id)
    if row and row["discord_id"] == owner:
        await message.answer(localized("sponsor_community_claimed", lang))
        return
    takeover = None
    if row:
        old = str(row["discord_id"])
        if old.startswith("admin:") or db.sponsor_tier(old) != 0:
            await message.answer(localized("sponsor_community_taken", lang))
            return
        takeover = old
    if not admin and len(db.claimed_communities(owner)) >= sponsors.limits(tier)["communities"]:
        await message.answer(localized("sponsor_community_limit", lang))
        return
    wait = db.sponsor_slot_wait_days(owner) if not admin else 0
    if wait:
        await message.answer(localized("sponsor_slot_wait", lang, days=wait))
        return
    if not db.claim_community("telegram", message.chat.id, owner,
                              takeover_from=takeover):
        await message.answer(localized("sponsor_community_taken", lang))
        return
    await message.answer(localized("sponsor_community_claimed", lang))

@router.message(Command("sponsor_uncommunity"))
async def sponsor_uncommunity_cmd(message: Message):
    """Release this group without touching its other wiki work."""
    lang = user_lang(message.from_user)
    if message.chat.type not in ("group", "supergroup") or message.from_user is None:
        await message.answer(localized("sponsor_community_here", lang))
        return
    admin = is_admin("telegram", message.from_user.id)
    owner = (f"admin:telegram:{message.from_user.id}" if admin else
             sponsors.canonical_id("telegram", message.from_user.id))
    changed = bool(owner and db.release_community("telegram", message.chat.id, owner))
    await message.answer(localized(
        "sponsor_community_released" if changed else "sponsor_community_not_owned", lang))
