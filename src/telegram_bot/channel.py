"""The two handlers that collect the channel's posts.

This is the bot's only source of news: Telegram delivers a post of a channel
the bot administrates as a `channel_post` update, and there is no way to ask
for the posts made before that — a channel the bot is not an administrator of
sends nothing at all, and one it has just been added to starts at the next
post. What the bot has seen it keeps in channel_posts, and news.py builds the
three news out of that.

An edit arrives as `edited_channel_post` and overwrites the stored row, so a
correction made in the channel reaches the wiki at the next pass. A deletion
is not delivered to bots at all: a post removed from the channel stays a news
until three newer posts have pushed it out (see README: What the bot cannot
see).

The picture kept for a post is the largest size Telegram offers, since it is
uploaded to the wiki afterwards; `file_unique_id` is stored beside it because
it is the same for the same picture and is what lets the publisher skip an
upload it has already done.
"""
import logging

from aiogram.types import Message

import db
import richtext
from telegram_bot.client import is_source_chat, router

logger = logging.getLogger("fd.channel")

def _photo_of(message):
    """(file_id, file_unique_id) of the post's picture, or (None, None).

    The largest of the sizes Telegram lists is taken — the news card is a
    picture on a main page, not a thumbnail. A video, a document or a sticker
    is not a picture: those posts are published as a card with no image block
    at all (news.py: render_image)."""
    photo = getattr(message, "photo", None)
    if not photo:
        return None, None
    largest = max(photo, key=lambda size: (size.width or 0) * (size.height or 0))
    return largest.file_id, largest.file_unique_id

def _forward_of(message):
    """(kind, name) of the post this one was reposted from, or (None, None).

    Telegram describes a repost with one `forward_origin` of four shapes: a
    channel, some other chat, a person, or a person who has hidden their
    account. A card only has room for the two the reader cares about — where
    it came from (`chat`) or who it came from (`user`) — so the four are
    folded into those. A person is named by their @name when they have one,
    because that is what a reader can look up."""
    origin = getattr(message, "forward_origin", None)
    if origin is None:
        return None, None

    chat = getattr(origin, "chat", None) or getattr(origin, "sender_chat", None)
    if chat is not None:
        return "chat", (chat.title or (("@" + chat.username) if chat.username else None))

    user = getattr(origin, "sender_user", None)
    if user is not None:
        return "user", (("@" + user.username) if user.username else user.full_name)

    hidden = getattr(origin, "sender_user_name", None)
    if hidden:
        return "user", hidden
    return None, None

def _store(message):
    """Write one channel message into channel_posts, then drop the tail of the
    channel that can no longer become a news.

    The formatting travels with the text: a post carries its bold, italics and
    links as entities beside the message, and richtext.from_telegram turns
    them into the stored form (offsets in characters rather than in Telegram's
    UTF-16 units)."""
    file_id, unique_id = _photo_of(message)
    text = message.text or message.caption or ""
    entities = message.entities or message.caption_entities or []
    forward_type, forward_name = _forward_of(message)
    db.save_post(
        chat_id=message.chat.id,
        message_id=message.message_id,
        date=int(message.date.timestamp()),
        text=text,
        entities=richtext.from_telegram(text, entities),
        source="api",
        forward_type=forward_type,
        forward_name=forward_name,
        media_group_id=message.media_group_id,
        photo_file_id=file_id,
        photo_unique_id=unique_id,
    )
    db.cleanup_old_posts(message.chat.id)

@router.channel_post()
async def on_channel_post(message: Message):
    """Store a new post of the followed channel and ignore every other one.

    The handler takes no aiogram filter on purpose: which channel is the
    followed one is a question for is_source_chat, which knows about the
    resolved id, the configured @name and the numeric form alike."""
    if not is_source_chat(message.chat):
        return
    try:
        _store(message)
    except Exception as e:
        logger.warning("could not store channel post %s: %s", message.message_id, e)

@router.edited_channel_post()
async def on_edited_channel_post(message: Message):
    """Overwrite a stored post that was edited in the channel.

    An edited caption arrives without the photo repeated; db.save_post keeps
    the picture already stored in that case, so an edit never blanks a news
    card's image."""
    if not is_source_chat(message.chat):
        return
    try:
        _store(message)
    except Exception as e:
        logger.warning("could not store edited channel post %s: %s", message.message_id, e)
