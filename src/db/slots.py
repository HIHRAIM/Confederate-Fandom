"""What the news slots hold on each wiki, and the bot's own bookkeeping.

A slot row is written only after that wiki accepted the change, so a failed
pass leaves the previous state in place and the next pass tries again. Every
wiki of config.WIKIS keeps its own row per slot: the same news can be up to
date on one wiki while another is still refusing the edit, and each has its own
answer to "does this slot already hold this picture?".

Slots are addressed by the wiki key `'<family>:<lang>'` — utils.wiki_key builds
it, and it is the only form these functions accept.
"""
import time

from db import conn, cur

def get_slot(wiki, slot):
    """The stored state of one slot on one wiki, or None when that wiki has
    never published it."""
    return cur.execute(
        "SELECT * FROM wiki_slots WHERE wiki=? AND slot=?", (str(wiki), int(slot))
    ).fetchone()

def get_slots(wiki):
    """Every stored slot of one wiki, slot 1 first — /status prints them in
    this order."""
    return cur.execute(
        "SELECT * FROM wiki_slots WHERE wiki=? ORDER BY slot", (str(wiki),)
    ).fetchall()

def set_slot(wiki, slot, chat_id, message_id, image_key):
    """Record what a slot now holds on one wiki. `image_key` is the
    photo_unique_id of the uploaded picture, or '' when the news had none and
    the card was published without an image block."""
    cur.execute(
        """
        INSERT INTO wiki_slots (wiki, slot, chat_id, message_id, image_key, published_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(wiki, slot) DO UPDATE SET
            chat_id=excluded.chat_id,
            message_id=excluded.message_id,
            image_key=excluded.image_key,
            published_at=excluded.published_at
        """,
        (str(wiki), int(slot), int(chat_id), int(message_id), image_key or "", int(time.time())),
    )
    conn.commit()

def get_state(key, default=None):
    """One bookkeeping value, or `default`."""
    row = cur.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default

def set_state(key, value):
    """Store one bookkeeping value; None is stored as the empty string."""
    cur.execute(
        """
        INSERT INTO state (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """,
        (key, "" if value is None else str(value)),
    )
    conn.commit()
