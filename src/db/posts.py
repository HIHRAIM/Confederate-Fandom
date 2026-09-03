"""The posts collected from the source channel.

Written by telegram_bot/channel.py as the updates arrive, read by news.py
when it builds the three news. Nothing here knows what a news is — it stores
messages and hands them back newest first.
"""
import json
import time

import richtext
from db import conn, cur

POST_KEEP = 60

def save_post(chat_id, message_id, date, text, entities=None, source="api",
              forward_type=None, forward_name=None,
              media_group_id=None, photo_file_id=None, photo_unique_id=None):
    """Store one channel message, replacing what was stored for it before.

    An edit arrives as the whole message again, so a plain replace is the
    edit path too — with one exception: Telegram sends an edited caption
    without repeating the photo, so an update that carries no photo keeps the
    one already stored rather than blanking it.

    `entities` is the formatting as a list of dicts (richtext.py); it is
    stored as JSON, and None means plain text. `source` says who is speaking:
    'api' for the bot's own ear, 'preview' for the channel's public web
    preview. Writing a row marks it edited from the second time on, which is
    what `edited_at` is for."""
    row = get_post(chat_id, message_id)
    if row is not None and not photo_file_id:
        photo_file_id = row["photo_file_id"]
        photo_unique_id = row["photo_unique_id"]
    cur.execute(
        """
        INSERT INTO channel_posts
            (chat_id, message_id, date, text, entities, source,
             forward_type, forward_name, media_group_id,
             photo_file_id, photo_unique_id, edited_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(chat_id, message_id) DO UPDATE SET
            date=excluded.date,
            text=excluded.text,
            entities=excluded.entities,
            source=excluded.source,
            forward_type=excluded.forward_type,
            forward_name=excluded.forward_name,
            media_group_id=excluded.media_group_id,
            photo_file_id=excluded.photo_file_id,
            photo_unique_id=excluded.photo_unique_id,
            edited_at=excluded.edited_at
        """,
        (int(chat_id), int(message_id), int(date), text or "",
         json.dumps(entities, ensure_ascii=False) if entities else None,
         source or "api",
         forward_type or None, forward_name or None,
         str(media_group_id) if media_group_id else None,
         photo_file_id, photo_unique_id,
         int(time.time()) if row is not None else None),
    )
    conn.commit()

def set_post_forward(chat_id, message_id, forward_type, forward_name):
    """Fill in where a stored post was reposted from, and nothing else.

    A narrow update on purpose. Posts stored before the bot knew about
    reposts — or by an older build of it — carry nothing in these two columns,
    and the automatic sync is forbidden from rewriting a row that came from
    Telegram (backfill.py). Filling an empty field is not rewriting: it adds
    what was missing and leaves the text, the formatting and the picture as
    the Bot API gave them."""
    cur.execute(
        """
        UPDATE channel_posts SET forward_type=?, forward_name=?
        WHERE chat_id=? AND message_id=?
        """,
        (forward_type or None, forward_name or None, int(chat_id), int(message_id)),
    )
    conn.commit()

def post_entities(row):
    """The stored formatting of one post row, as the list richtext.py takes.

    A row written before the column existed, or one that never had any
    formatting, comes back as an empty list rather than as None — a caller
    should not have to ask which."""
    if row is None:
        return []
    try:
        raw = row["entities"]
    except (IndexError, KeyError):
        return []
    return richtext.entities_from_json(raw)

def get_post(chat_id, message_id):
    """One stored message, or None."""
    return cur.execute(
        "SELECT * FROM channel_posts WHERE chat_id=? AND message_id=?",
        (int(chat_id), int(message_id)),
    ).fetchone()

def get_recent_posts(chat_id, limit=POST_KEEP):
    """The newest stored messages of the channel, newest first.

    The order is the one the news are picked in: by the Telegram timestamp,
    and by message number within the same second — an album is published in
    one breath and its parts share a timestamp, so the number is what keeps
    its first picture first."""
    return cur.execute(
        """
        SELECT * FROM channel_posts
        WHERE chat_id=?
        ORDER BY date DESC, message_id DESC
        LIMIT ?
        """,
        (int(chat_id), int(limit)),
    ).fetchall()

def count_posts(chat_id):
    """How many messages of this channel are stored — /status reads it."""
    row = cur.execute(
        "SELECT COUNT(*) AS n FROM channel_posts WHERE chat_id=?", (int(chat_id),)
    ).fetchone()
    return row["n"] if row else 0

def cleanup_old_posts(chat_id, keep=POST_KEEP):
    """Drop everything but the newest `keep` messages of the channel.

    The bot only ever looks at the head of the channel, so the tail is dead
    weight — and the text of posts nobody will publish again is data the bot
    has no reason to hold on to (see PRIVACY.md)."""
    cur.execute(
        """
        DELETE FROM channel_posts
        WHERE chat_id=? AND message_id NOT IN (
            SELECT message_id FROM channel_posts
            WHERE chat_id=?
            ORDER BY date DESC, message_id DESC
            LIMIT ?
        )
        """,
        (int(chat_id), int(chat_id), int(keep)),
    )
    conn.commit()

def forget_other_channels(chat_id):
    """Drop the posts of every channel except this one; returns how many went.

    Called when config.SOURCE_CHANNEL turns out to name a different channel
    than the one the database was filled from. The old channel's posts can
    never become a news again — collect_news only ever reads the followed
    channel — so keeping them would be holding on to the text of somebody's
    posts for no reason at all (see PRIVACY.md)."""
    cursor = cur.execute("DELETE FROM channel_posts WHERE chat_id<>?", (int(chat_id),))
    conn.commit()
    return cursor.rowcount
