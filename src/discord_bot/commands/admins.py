"""Appointing wiki administrators on Discord, /help, /status, /lang and /backup.

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

`/backup` sits here rather than beside the wiki commands because it is the
same kind of thing as the two above: something only the people named in
config.ADMINS may do. `/lang` is the one command here anybody may use: it
changes nothing but the language the bot answers that person in.
"""
import logging

import discord
from discord import app_commands

import db
from discord_bot.client import slash, tree
from utils import LANG_NAMES, is_admin, lang_answer, lang_of, localized

logger = logging.getLogger("fd.discord.admins")

MESSAGE_LIMIT = 1900


@tree.command(name="wikiadmin", description=slash("slash_wikiadmin"))
@app_commands.describe(user=slash("slash_wikiadmin_user"),
                       wiki_user=slash("slash_wikiadmin_wiki_user"))
async def wikiadmin_cmd(interaction: discord.Interaction,
                        user: discord.User = None, wiki_user: str = ""):
    """Appoint somebody, or list who is appointed."""
    lang = lang_of("discord", interaction.user.id)
    if not is_admin("discord", interaction.user.id):
        await interaction.response.send_message(localized("not_admin", lang),
                                                ephemeral=True)
        return

    if user is None:
        from tasks import lists

        title, lines = lists.wiki_admins(lang)
        if not lines:
            await interaction.response.send_message(
                localized("wikiadmin_empty", lang))
            return
        await interaction.response.send_message(
            "\n".join([title] + lines)[:MESSAGE_LIMIT])
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


@tree.command(name="remwikiadmin", description=slash("slash_remwikiadmin"))
@app_commands.describe(user=slash("slash_remwikiadmin_user"))
async def remwikiadmin_cmd(interaction: discord.Interaction, user: discord.User):
    """Take an appointment away."""
    lang = lang_of("discord", interaction.user.id)
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


@tree.command(name="help", description=slash("slash_help"))
async def help_cmd(interaction: discord.Interaction):
    """What the bot does and which commands it takes.

    Paginated like the other long answers, and ephemeral as it always was: a
    command list belongs to whoever asked for it, not to the channel."""
    from discord_bot import pages
    from tasks import lists

    lang = lang_of("discord", interaction.user.id)
    title, lines = lists.help_text(lang, pages.MARKUP, lists.DISCORD)
    await pages.send(interaction, title, lines, lang, ephemeral=True)


@tree.command(name="status", description=slash("slash_status"))
async def status_cmd(interaction: discord.Interaction):
    """The same answer /status gives on Telegram: slots, schedule, queue."""
    import scheduler
    from tasks import access

    lang = lang_of("discord", interaction.user.id)
    if access.caller("discord", interaction.user.id,
                     getattr(interaction.user, "name", None)) is None:
        await interaction.response.send_message(localized("not_admin", lang),
                                                ephemeral=True)
        return

    from modules.teleradiopedia import settings as news_settings
    from modules.teleradiopedia.settings import SOURCE_CHANNEL, WIKIS
    from utils import publish_schedule, queue_status, wiki_key

    if not news_settings.enabled():
        await interaction.response.send_message(queue_status(lang))
        return

    await interaction.response.send_message(localized(
        "status_short", lang,
        channel=str(SOURCE_CHANNEL),
        wiki=", ".join(wiki_key(entry) for entry in WIKIS) or "—",
        schedule=publish_schedule(),
        running=scheduler.running() or "—",
        waiting=", ".join(scheduler.waiting()) or "—",
        error=db.get_state("last_error") or "—")[:MESSAGE_LIMIT])


@tree.command(name="backup", description=slash("slash_backup"))
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@app_commands.allowed_installs(guilds=True, users=True)
async def backup_cmd(interaction: discord.Interaction):
    """Send an encrypted snapshot of the database to whoever asked.

    The same file the twice-daily job sends to config.BACKUP_CHATS, on demand,
    and for the people in config.ADMINS only.

    **The answer is ephemeral, and the command works in a DM.** The file is the
    whole database; encrypted, yes, but a channel keeps it for as long as the
    channel exists and hands it to everyone who can read there, and a key is a
    thing that can leak later. Asking in a direct message is the way to have it
    reach nobody else at all, which is why the command is allowed there.

    Without BACKUP_KEY the bot says so and sends nothing. A plaintext copy of
    the database is never what happens instead.
    """
    lang = lang_of("discord", interaction.user.id)
    if not is_admin("discord", interaction.user.id):
        await interaction.response.send_message(localized("not_admin", lang),
                                                ephemeral=True)
        return

    import asyncio
    import io

    import backup_crypto
    from tasks import report

    if not backup_crypto.available():
        await interaction.response.send_message(localized("backup_no_key", lang),
                                                ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    try:
        data = await asyncio.to_thread(backup_crypto.build_backup)
    except Exception as e:
        logger.exception("the backup could not be built")
        await interaction.followup.send(
            localized("backup_failed", lang, error=report.safe_error(e)),
            ephemeral=True)
        return
    await interaction.followup.send(
        file=discord.File(io.BytesIO(data),
                          filename=backup_crypto.backup_filename()),
        ephemeral=True)


@tree.command(name="lang", description=slash("slash_lang"))
@app_commands.describe(code=slash("slash_lang_code"))
@app_commands.choices(code=[
    app_commands.Choice(name=name, value=code)
    for code, name in sorted(LANG_NAMES.items())])
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@app_commands.allowed_installs(guilds=True, users=True)
async def lang_cmd(interaction: discord.Interaction,
                   code: app_commands.Choice[str] = None):
    """The language the bot answers this person in, on this messenger.

    Personal rather than per server, unlike the /lang of the other bots of
    the family: a task's answers go to whoever asked for it, and two people
    in one channel may read different languages. Open to everybody, and
    ephemeral. Without a choice it says which language is in use.
    """
    await interaction.response.send_message(
        lang_answer("discord", interaction.user.id,
                    code.value if code else None, "/lang code: ru"),
        ephemeral=True)
