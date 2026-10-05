"""A Patreon sponsor's own Fandom wiki slots and daily work allowance."""
import asyncio

import discord
from discord import app_commands

import db
import sponsors
from config import SPONSOR_URL
from discord_bot.client import slash, tree
from utils import is_admin, lang_of, localized

@tree.command(name="sponsor-link", description="link Telegram to this subscription")
async def sponsor_link_cmd(interaction: discord.Interaction):
    """Issue a ten-minute pairing code only the Discord account can see."""
    lang = lang_of("discord", interaction.user.id)
    code = db.create_sponsor_link_code(interaction.user.id)
    await interaction.response.send_message(localized(
        "sponsor_link_code", lang, code=code), ephemeral=True)

@tree.command(name="sponsor-unlink", description="unlink Telegram from this subscription")
async def sponsor_unlink_cmd(interaction: discord.Interaction):
    """Revoke access from the paired Telegram account."""
    lang = lang_of("discord", interaction.user.id)
    changed = db.unlink_sponsor_account("discord", interaction.user.id)
    await interaction.response.send_message(localized(
        "sponsor_unlinked" if changed else "sponsor_link_missing", lang), ephemeral=True)

@tree.command(name="sponsor", description=slash("slash_sponsor"))
async def sponsor_cmd(interaction: discord.Interaction):
    """Show the role tier and account-wide wiki/task/page usage."""
    lang = lang_of("discord", interaction.user.id)
    tier = await sponsors.refresh_tier(interaction.user.id)
    limits = sponsors.limits(tier)
    tasks, pages = db.sponsor_usage(interaction.user.id)
    wikis = db.claimed_wikis(interaction.user.id)
    message = localized(
        "sponsor_status", lang,
        tier=(localized("sponsor_tier_community", lang) if tier == -1 else tier),
        wikis=len(wikis),
        wiki_limit=limits["wikis"], tasks=tasks, task_limit=limits["tasks"],
        pages=pages, page_limit=limits["pages"],
        names=", ".join(row["wiki"] for row in wikis) or "—",
        url=SPONSOR_URL)
    message += "\n" + localized("sponsor_community_usage", lang,
                                  communities=len(db.claimed_communities(interaction.user.id)),
                                  limit=limits["communities"])
    addendum = sponsors.status_addendum(interaction.user.id, lang)
    if addendum:
        message += "\n" + addendum
    wait = db.sponsor_slot_wait_days(interaction.user.id)
    if wait:
        message += "\n" + localized("sponsor_slot_wait", lang, days=wait)
    await interaction.response.send_message(message, ephemeral=True)

@tree.command(name="sponsor-wiki", description=slash("slash_sponsor_wiki"))
@app_commands.describe(wiki="Fandom wiki URL", wiki_user="Your Fandom account name")
async def sponsor_wiki_cmd(interaction: discord.Interaction, wiki: str, wiki_user: str):
    """Claim one wiki after proving staff status on that wiki itself."""
    lang = lang_of("discord", interaction.user.id)
    tier = await sponsors.refresh_tier(interaction.user.id)
    from utils import is_admin
    admin = is_admin("discord", interaction.user.id)
    if tier == 0 and not admin:
        await interaction.response.send_message(localized("sponsor_not_active", lang,
                                                         url=SPONSOR_URL), ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    try:
        import wiki as wiki_module
        from wiki import families, rights
        target = families.parse_target(wiki)
        family, code = await asyncio.to_thread(families.ensure_family, target)
        key = f"{family}:{code}"
        site = await asyncio.to_thread(wiki_module.get_site, family, code)
        staff, _ = (await asyncio.to_thread(rights.is_wiki_staff, site, wiki_user.strip())
                    if not admin else (True, ()))
    except Exception:
        await interaction.followup.send(localized("sponsor_wiki_invalid", lang), ephemeral=True)
        return
    if not staff:
        await interaction.followup.send(localized("sponsor_wiki_staff", lang), ephemeral=True)
        return
    if not admin:
        try:
            from wiki.identity import handle_matches, profile_discord_handle
            handle = await profile_discord_handle(wiki_user.strip())
        except Exception:
            await interaction.followup.send(localized("sponsor_wiki_identity_unavailable", lang), ephemeral=True)
            return
        if not handle_matches(handle, interaction.user.name):
            await interaction.followup.send(localized("sponsor_wiki_identity", lang), ephemeral=True)
            return
    row = db.wiki_claim(key)
    takeover_from = None
    if row and str(row["discord_id"]) != str(interaction.user.id):
        if is_admin("discord", row["discord_id"]) or db.sponsor_tier(row["discord_id"]) != 0:
            await interaction.followup.send(localized("sponsor_wiki_taken", lang), ephemeral=True)
            return
        takeover_from = row["discord_id"]
    if (not admin and (not row or takeover_from is not None)
            and len(db.claimed_wikis(interaction.user.id)) >= sponsors.limits(tier)["wikis"]):
        await interaction.followup.send(localized("sponsor_wiki_limit", lang), ephemeral=True)
        return
    wait = (db.sponsor_slot_wait_days(interaction.user.id)
            if not admin and (row is None or takeover_from is not None) else 0)
    if wait:
        await interaction.followup.send(localized("sponsor_slot_wait", lang, days=wait),
                                        ephemeral=True)
        return
    if not db.claim_wiki(key, interaction.user.id, wiki_user.strip(),
                         takeover_from=takeover_from, bypass_cooldown=admin):
        await interaction.followup.send(localized("sponsor_wiki_taken", lang), ephemeral=True)
        return
    await interaction.followup.send(localized("sponsor_wiki_claimed", lang, wiki=key), ephemeral=True)

@tree.command(name="sponsor-unwiki", description=slash("slash_sponsor_unwiki"))
@app_commands.describe(wiki="Claimed wiki key, for example family:en")
async def sponsor_unwiki_cmd(interaction: discord.Interaction, wiki: str):
    """Release only this sponsor's own wiki slot."""
    lang = lang_of("discord", interaction.user.id)
    if not db.release_wiki(wiki.strip(), interaction.user.id):
        await interaction.response.send_message(localized("sponsor_wiki_not_owned", lang), ephemeral=True)
        return
    await interaction.response.send_message(localized("sponsor_wiki_released", lang), ephemeral=True)

@tree.command(name="sponsor-community", description=slash("slash_sponsor_community"))
async def sponsor_community_cmd(interaction: discord.Interaction):
    """Assign this guild to a sponsor or the bot's operator."""
    lang = lang_of("discord", interaction.user.id)
    if interaction.guild is None:
        await interaction.response.send_message(localized("sponsor_community_here", lang),
                                                ephemeral=True)
        return
    admin = is_admin("discord", interaction.user.id)
    if not admin and not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message(localized("sponsor_community_manage", lang),
                                                ephemeral=True)
        return
    tier = await sponsors.refresh_tier(interaction.user.id)
    if tier == 0 and not admin:
        await interaction.response.send_message(localized("sponsor_not_active", lang,
                                                         url=SPONSOR_URL), ephemeral=True)
        return
    owner = f"admin:{interaction.user.id}" if admin else str(interaction.user.id)
    row = db.community_claim("discord", interaction.guild_id)
    if row and row["discord_id"] == owner:
        await interaction.response.send_message(localized("sponsor_community_claimed", lang),
                                                ephemeral=True)
        return
    takeover = None
    if row:
        old = str(row["discord_id"])
        if old.startswith("admin:") or db.sponsor_tier(old) != 0:
            await interaction.response.send_message(localized("sponsor_community_taken", lang),
                                                    ephemeral=True)
            return
        takeover = old
    if not admin and len(db.claimed_communities(owner)) >= sponsors.limits(tier)["communities"]:
        await interaction.response.send_message(localized("sponsor_community_limit", lang),
                                                ephemeral=True)
        return
    wait = db.sponsor_slot_wait_days(owner) if not admin else 0
    if wait:
        await interaction.response.send_message(localized("sponsor_slot_wait", lang,
                                                          days=wait), ephemeral=True)
        return
    if not db.claim_community("discord", interaction.guild_id, owner,
                              takeover_from=takeover):
        await interaction.response.send_message(localized("sponsor_community_taken", lang),
                                                ephemeral=True)
        return
    await interaction.response.send_message(localized("sponsor_community_claimed", lang),
                                            ephemeral=True)

@tree.command(name="sponsor-uncommunity", description=slash("slash_sponsor_uncommunity"))
async def sponsor_uncommunity_cmd(interaction: discord.Interaction):
    """Release only the current caller's community assignment."""
    lang = lang_of("discord", interaction.user.id)
    if interaction.guild is None:
        await interaction.response.send_message(localized("sponsor_community_here", lang),
                                                ephemeral=True)
        return
    admin = is_admin("discord", interaction.user.id)
    owner = f"admin:{interaction.user.id}" if admin else str(interaction.user.id)
    changed = db.release_community("discord", interaction.guild_id, owner)
    await interaction.response.send_message(localized(
        "sponsor_community_released" if changed else "sponsor_community_not_owned", lang),
        ephemeral=True)
