"""How the Discord half holds a conversation.

The mirror of telegram_bot/dialogs.py, and much shorter, because discord.py
can block on `wait_for` inside a command: there is no future to park and no
catchall to feed it. The waiting is done where the question was asked.

A slash command has three seconds to answer or Discord calls it failed, so the
dialog begins by answering the interaction and then talks in the channel like
an ordinary conversation. The answers are read with `wait_for('message')`
filtered to the same person in the same channel — which is why the message
content intent has to be on (discord_bot/client.py).

The timeout is the same as Telegram's, and for the same reason: a dialog that
never gets its answer must let go rather than sit on a task row for ever.
"""
import logging

from tasks.dialog import Conversation, MAX_LIST_BYTES, decode_list_document
from tasks.notify import chat_key
from utils import lang_of

logger = logging.getLogger("fd.discord.dialogs")

DIALOG_TIMEOUT = 15 * 60

MESSAGE_LIMIT = 1900

class DiscordConversation(Conversation):
    """The dialog driver for Discord: send in the channel, wait for a reply.

    Built from the interaction that started it, so the answers go back to the
    same channel and the task remembers it for the report it will send when
    the run finishes an hour later.
    """

    def __init__(self, interaction, lang=None):
        """Take who and where from the interaction that started it."""
        user = interaction.user
        super().__init__(
            platform="discord",
            user_id=user.id,
            display_name=getattr(user, "name", None) or str(user),
            chat_key=chat_key("discord", interaction.channel_id),
            lang=lang or lang_of("discord", user.id))
        self.interaction = interaction
        self.channel = interaction.channel
        self.community_id = interaction.guild_id

    async def say(self, text):
        """Send something that needs no answer, in chunks Discord accepts."""
        body = str(text)
        while body:
            await self.channel.send(body[:MESSAGE_LIMIT])
            body = body[MESSAGE_LIMIT:]

    async def _reply(self, text):
        """Wait for a matching message, retaining its attachments if present."""
        from discord_bot.client import client

        await self.say(text)

        def _mine(message):
            """Only this person, only this channel, only what is not a command."""
            return (message.author.id == self.user_id
                    and message.channel.id == self.channel.id
                    and not message.content.startswith("/"))

        try:
            return await client.wait_for("message", check=_mine,
                                         timeout=DIALOG_TIMEOUT)
        except Exception:
            return None

    async def ask(self, text):
        """Send a question and wait for this person's next text message."""
        message = await self._reply(text)
        return message.content if message is not None else None

    async def ask_text_or_file(self, text):
        """Accept a pasted list or one bounded UTF-8 .txt attachment."""
        message = await self._reply(text)
        if message is None:
            return None
        if not message.attachments:
            return message.content
        if len(message.attachments) != 1:
            raise ValueError("exactly one text file is required")
        attachment = message.attachments[0]
        if attachment.size > MAX_LIST_BYTES:
            raise ValueError("text file is too large")
        try:
            contents = await attachment.read()
        except Exception as error:
            raise ValueError("could not read the text attachment") from error
        return decode_list_document(attachment.filename, contents)
