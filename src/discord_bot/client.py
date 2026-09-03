"""The Discord half: the client, the command tree, and the log channels.

It began as a client that only wrote service reports, with `Intents.none()` and
nothing to listen to. It now carries the same commands as the Telegram half,
and that costs one privileged intent: **message content**. The dialogs are
answered with ordinary messages — a numbered list and «1 3 4» — and without
that intent every answer arrives empty. It has to be switched on in the
Developer Portal; there is no way round it short of rebuilding every dialog on
buttons, which would make the two halves behave differently for no gain.

The commands are slash commands, registered on a `CommandTree` and synced once
when the gateway comes up. `guilds` and `guild_messages` are the other two
intents: the first so the client knows of channels without a request per
report, the second so a dialog's answers are delivered at all.

Sending waits for the client to be ready, because a message sent before the
gateway handshake is a message lost. The wait is bounded: a Discord that is
down must cost the report, not the pass that was trying to write it.
"""
import asyncio
import logging
import os

import discord
from discord import app_commands

from config import DISCORD_TOKEN

logger = logging.getLogger("fd.discord")

READY_TIMEOUT = 30

MESSAGE_LIMIT = 1900

intents = discord.Intents.none()
intents.guilds = True
intents.guild_messages = True
intents.message_content = True
intents.dm_messages = True

client = discord.Client(intents=intents)

tree = app_commands.CommandTree(client)


@client.event
async def on_ready():
    """Sync the command tree once the gateway is up, then say so.

    Syncing here rather than in a setup hook because it must happen after the
    application id is known, and because a sync that fails should leave a bot
    that still reports to its log channels rather than one that does not
    start.
    """
    try:
        synced = await tree.sync()
        logger.info("connected to Discord as %s, %s commands synced",
                    client.user, len(synced))
    except Exception as e:
        logger.warning("connected to Discord as %s, but the commands would "
                       "not sync: %s", client.user, e)


@tree.error
async def on_command_error(interaction, error):
    """Answer a command that raised, and put the reason in the log.

    What the person sees is deliberately short: the details belong in the log,
    and an interaction that is never answered leaves «приложение не отвечает»
    on their screen for ever.
    """
    logger.exception("a Discord command failed: %s", error)
    try:
        if interaction.response.is_done():
            await interaction.followup.send("Команда не отработала — "
                                            "подробности в служебном канале.")
        else:
            await interaction.response.send_message(
                "Команда не отработала — подробности в служебном канале.",
                ephemeral=True)
    except Exception:
        pass


async def _channel(channel_id):
    """One channel, from the cache or from Discord. -> the channel or None."""
    try:
        await asyncio.wait_for(client.wait_until_ready(), timeout=READY_TIMEOUT)
    except asyncio.TimeoutError:
        logger.warning("Discord is not ready — nothing sent to %s", channel_id)
        return None
    try:
        return client.get_channel(int(channel_id)) or \
            await client.fetch_channel(int(channel_id))
    except Exception as e:
        logger.warning("could not reach the Discord channel %s: %s", channel_id, e)
        return None


async def send_log(channel_id, text):
    """Write one report into one channel. Never raises.

    A failure here is reported to the log and forgotten: the channels are
    where the bot complains, so a complaint that cannot be delivered must not
    become a second failure on top of the first.
    """
    channel = await _channel(channel_id)
    if channel is None:
        return
    try:
        await channel.send(str(text)[:MESSAGE_LIMIT])
    except Exception as e:
        logger.warning("could not write to the Discord channel %s: %s", channel_id, e)


async def send_files(channel_id, paths, caption=None):
    """Send a task's files into one channel. Never raises.

    Discord takes ten attachments per message and caps each at the server's
    upload limit; a file that is too large is skipped with a line saying so,
    because a run whose report will not fit still made its edits and the
    person needs to hear that much.
    """
    channel = await _channel(channel_id)
    if channel is None:
        return
    real = [path for path in (paths or []) if path and os.path.exists(path)]
    if not real:
        return
    attachments = []
    skipped = []
    for path in real[:10]:
        try:
            attachments.append(discord.File(path))
        except Exception as e:
            skipped.append("{}: {}".format(os.path.basename(path), e))
    try:
        if attachments:
            await channel.send(content=(str(caption)[:MESSAGE_LIMIT]
                                        if caption else None),
                               files=attachments)
        if skipped:
            await channel.send("Не удалось приложить: " + "; ".join(skipped))
    except Exception as e:
        logger.warning("could not send files to the Discord channel %s: %s",
                       channel_id, e)


async def main():
    """Start the client. Runs as one of the tasks main.py waits on."""
    await client.start(DISCORD_TOKEN)
