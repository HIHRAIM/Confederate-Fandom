"""Appointing wiki administrators on Discord, and the bot's own /help.

Only a bot administrator may appoint: control of the bot lives in
config.ADMINS and nothing stored can hand it out.

    /wikiadmin user:<@кто> wiki_user:<ник на Fandom>
    /wikiadmin                     — кто назначен
    /remwikiadmin user:<@кто>

The Fandom name is not optional and not guessed. It is what the bot checks on
the wiki before every run that person asks for (wiki/rights.py:
is_wiki_staff), so an appointment without it would be an appointment that
cannot be used. Running the command again with a different name is how a name
is corrected.

Discord names people with a real user object rather than a string, so there is
none of Telegram's guessing between a reply, an @name and an id.
"""
import logging

import discord
from discord import app_commands

import db
from discord_bot.client import tree
from utils import is_admin, localized, service_lang

logger = logging.getLogger("fd.discord.admins")

MESSAGE_LIMIT = 1900


@tree.command(name="wikiadmin", description="назначить администратора вики")
@app_commands.describe(user="кому выдать доступ",
                       wiki_user="его ник на Fandom")
async def wikiadmin_cmd(interaction: discord.Interaction,
                        user: discord.User = None, wiki_user: str = ""):
    """Appoint somebody, or list who is appointed."""
    lang = service_lang()
    if not is_admin("discord", interaction.user.id):
        await interaction.response.send_message(localized("not_admin", lang),
                                                ephemeral=True)
        return

    if user is None:
        rows = db.list_wiki_admins()
        if not rows:
            await interaction.response.send_message(
                localized("wikiadmin_empty", lang))
            return
        lines = [localized("wikiadmin_header", lang)]
        for row in rows:
            lines.append(localized(
                "wikiadmin_line", lang, platform=row["platform"],
                name=row["display_name"] or row["user_id"],
                user_id=row["user_id"], wiki_user=row["wiki_user"]))
        await interaction.response.send_message("\n".join(lines)[:MESSAGE_LIMIT])
        return

    if not wiki_user.strip():
        await interaction.response.send_message(
            localized("wikiadmin_no_wiki_user", lang), ephemeral=True)
        return

    name = getattr(user, "name", None) or str(user)
    existed = db.get_wiki_admin("discord", user.id) is not None
    db.add_wiki_admin("discord", user.id, wiki_user.strip(), name,
                      added_by=str(interaction.user.id))
    await interaction.response.send_message(localized(
        "wikiadmin_updated" if existed else "wikiadmin_added", lang,
        name=name, user_id=user.id, wiki_user=wiki_user.strip()))


@tree.command(name="remwikiadmin", description="снять администратора вики")
@app_commands.describe(user="у кого забрать доступ")
async def remwikiadmin_cmd(interaction: discord.Interaction, user: discord.User):
    """Take an appointment away."""
    lang = service_lang()
    if not is_admin("discord", interaction.user.id):
        await interaction.response.send_message(localized("not_admin", lang),
                                                ephemeral=True)
        return
    if db.remove_wiki_admin("discord", user.id):
        await interaction.response.send_message(
            localized("wikiadmin_removed", lang, user_id=user.id))
    else:
        await interaction.response.send_message(
            localized("wikiadmin_not_found", lang, user_id=user.id))


@tree.command(name="help", description="что бот умеет")
async def help_cmd(interaction: discord.Interaction):
    """What the bot does and which commands it takes."""
    lang = service_lang()
    await interaction.response.send_message(
        localized("help", lang)[:MESSAGE_LIMIT], ephemeral=True)


@tree.command(name="status", description="состояние новостей и очереди")
async def status_cmd(interaction: discord.Interaction):
    """The same answer /status gives on Telegram: slots, schedule, queue."""
    import scheduler
    from tasks import access

    lang = service_lang()
    if access.caller("discord", interaction.user.id,
                     getattr(interaction.user, "name", None)) is None:
        await interaction.response.send_message(localized("not_admin", lang),
                                                ephemeral=True)
        return

    from config import SOURCE_CHANNEL, WIKIS
    from utils import publish_schedule, wiki_key

    await interaction.response.send_message(localized(
        "status_short", lang,
        channel=str(SOURCE_CHANNEL),
        wiki=", ".join(wiki_key(entry) for entry in WIKIS) or "—",
        schedule=publish_schedule(),
        running=scheduler.running() or "—",
        waiting=", ".join(scheduler.waiting()) or "—",
        error=db.get_state("last_error") or "—")[:MESSAGE_LIMIT])
