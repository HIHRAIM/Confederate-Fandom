"""Fandom work budgets derived from the shared Patreon Discord roles."""
import logging
import math
import time

import db
import config

logger = logging.getLogger("fd.sponsors")

TIER1_WIKIS = 2
TIER1_COMMUNITIES = 2
TIER1_TASKS_DAY = 2
TIER1_PAGES_DAY = 30
TIER2_MULTIPLIER = 3
TIER3_MULTIPLIER = 5

def limits(tier):
    """One subscription's wiki, task and page allowance."""
    factor = (0 if tier == 0 else TIER3_MULTIPLIER if tier == 3
              else TIER2_MULTIPLIER if tier == 2 else 1)
    return {"wikis": TIER1_WIKIS * factor,
            "communities": TIER1_COMMUNITIES * factor,
            "tasks": TIER1_TASKS_DAY * factor,
            "pages": TIER1_PAGES_DAY * factor}

def status_addendum(discord_id, lang):
    """Explain free-role activation and retention in subscription status."""
    from utils import localized
    row = db.cur.execute(
        "SELECT tier,grace_tier,grace_since,community_role_since"
        " FROM sponsor_tiers WHERE discord_id=?", (str(discord_id),),
    ).fetchone()
    if not row:
        return ""
    effective = db.sponsor_tier(discord_id)
    if row["tier"] == -1 and effective == 0 and row["community_role_since"]:
        days = max(1, math.ceil((7 * 86400 -
                                 (time.time() - row["community_role_since"])) / 86400))
        return localized("sponsor_community_pending", lang, days=days)
    grace = db.sponsor_grace_days(discord_id)
    if row["tier"] == 0 and grace:
        key = ("sponsor_community_grace" if row["grace_tier"] == -1
               else "sponsor_grace_active")
        return localized(key, lang, days=grace)
    if row["tier"] == 0 and effective == 0 and (
            db.claimed_wikis(discord_id) or db.claimed_communities(discord_id)):
        return localized("sponsor_retention_warning", lang)
    return ""

def canonical_id(platform, user_id):
    """One quota identity for Discord and its linked Telegram account."""
    if platform == "discord":
        return str(user_id)
    if platform == "telegram":
        return db.linked_discord_id(user_id)
    return None

async def live_tier(discord_id):
    """0/1/2 from live roles, or None when Discord is unavailable."""
    from discord_bot.client import client
    guild = client.get_guild(int(config.PATREON_GUILD_ID))
    if guild is None:
        return None
    try:
        member = guild.get_member(int(discord_id)) or await guild.fetch_member(int(discord_id))
    except Exception as error:
        if "404" in str(error) or "Unknown Member" in str(error):
            return 0
        logger.info("Patreon role lookup failed for %s: %s", discord_id, error)
        return None
    role_ids = {role.id for role in member.roles}
    community = bool(role_ids.intersection(map(int, config.COMMUNITY_SPONSOR_ROLE_IDS)))
    db.observe_community_role(discord_id, community)
    return max((int(tier) for tier, role_id in config.PATREON_TIER_ROLES.items()
                if int(role_id) in role_ids), default=(-1 if community else 0))

async def refresh_tier(discord_id):
    """Update cache only after a successful live role read."""
    tier = await live_tier(discord_id)
    if tier is not None:
        db.save_sponsor_tier(discord_id, tier)
    return db.sponsor_tier(discord_id)

async def reconcile():
    """Hourly repair for role changes while the process was offline."""
    from discord_bot.client import client
    guild = client.get_guild(int(config.PATREON_GUILD_ID))
    discovered = set()
    if guild:
        for role_id in list(config.COMMUNITY_SPONSOR_ROLE_IDS) + list(config.PATREON_TIER_ROLES.values()):
            role = guild.get_role(int(role_id))
            if role:
                discovered.update(str(member.id) for member in role.members)
    if guild is None:
        return
    for discord_id in db.known_sponsor_ids() | discovered:
        await refresh_tier(discord_id)
    await cleanup_due_wikis()
    await cleanup_due_communities()

async def cleanup_due_communities():
    """Leave expired communities only after a fresh Patreon role read.

    A successful takeover replaces the claim, so it cannot appear here.
    Discord channel IDs are collected before leave to scope job deletion.
    """
    import discord
    from discord_bot.client import client
    from telegram_bot.client import bot as tg_bot

    checked = {}
    for claim in db.due_sponsor_communities():
        owner = str(claim["discord_id"])
        if owner not in checked:
            checked[owner] = await live_tier(owner)
            if checked[owner] is not None:
                db.save_sponsor_tier(owner, checked[owner])
        if checked[owner] is None or db.sponsor_tier(owner) != 0:
            continue
        platform = claim["platform"]
        community_id = str(claim["community_id"])
        current = db.community_claim(platform, community_id)
        if not current or str(current["discord_id"]) != owner:
            continue
        channels = ()
        try:
            if platform == "discord":
                guild = client.get_guild(int(community_id))
                if guild is None:
                    try:
                        guild = await client.fetch_guild(int(community_id))
                    except discord.NotFound:
                        guild = None
                    except discord.HTTPException as error:
                        logger.warning("expired sponsor guild lookup failed (%s): %s",
                                       community_id, error)
                        continue
                if guild is not None:
                    channels = tuple(channel.id for channel in guild.channels)
                    channels += tuple(thread.id for thread in guild.threads)
                    await guild.leave()
            elif platform == "telegram":
                if not await tg_bot.leave_chat(int(community_id)):
                    continue
            else:
                continue
        except Exception as error:
            logger.warning("expired sponsor community leave failed (%s:%s): %s",
                           platform, community_id, error)
            continue
        if db.purge_sponsor_community(platform, community_id, owner, channels):
            logger.info("expired sponsor community removed (%s:%s)",
                        platform, community_id)

async def cleanup_due_wikis():
    """Purge expired sponsor wiki work after grace plus another thirty days.

    The operator's configured news wikis are retained: their sponsor claim
    is released but the administrator's tasks and news state stay. Each owner
    gets a fresh role read before a destructive database operation.
    """
    operator_wikis = {
        f"{entry['family']}:{entry['lang']}"
        for entry in getattr(config, "WIKIS", ())
        if isinstance(entry, dict) and entry.get("family") and entry.get("lang")
    }
    checked = {}
    for claim in db.due_sponsor_wikis():
        owner = str(claim["discord_id"])
        if owner not in checked:
            checked[owner] = await live_tier(owner)
            if checked[owner] is not None:
                db.save_sponsor_tier(owner, checked[owner])
        if checked[owner] is None or db.sponsor_tier(owner) != 0:
            continue
        key = claim["wiki"]
        if key in operator_wikis:
            db.release_wiki(key, owner)
            continue
        if db.purge_sponsor_wiki(key, owner):
            logger.info("expired sponsor wiki removed (%s)", key)

def can_use_wiki(discord_id, wiki):
    """A sponsor may run only on a wiki they themselves claimed."""
    row = db.wiki_claim(wiki)
    return bool(row and row["discord_id"] == str(discord_id)
                and db.sponsor_tier(discord_id) != 0)

def can_use_community(discord_id, platform, community_id):
    """Sponsors work only in their own assigned guilds and groups."""
    row = db.community_claim(platform, community_id)
    return bool(row and row["discord_id"] == str(discord_id)
                and db.sponsor_tier(discord_id) != 0)

def spend_task(discord_id):
    """Reserve one planned run, including a schedule firing."""
    tier = db.sponsor_tier(discord_id)
    return tier != 0 and db.spend_sponsor_unit(discord_id, "tasks", limits(tier)["tasks"])

def reserve_pages(discord_id, pages):
    """Reserve the planned page count before a task may start."""
    tier = db.sponsor_tier(discord_id)
    return tier != 0 and db.spend_sponsor_unit(
        discord_id, "pages", limits(tier)["pages"], pages)
