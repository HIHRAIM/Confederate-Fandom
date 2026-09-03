"""The wiki administrators the bot's owner has appointed.

Two kinds of person may set the bot to work. The **bot administrators** are
hard-coded in config.ADMINS and are not stored anywhere — that is deliberate,
so that no database mishap can take away or hand out control of the bot. The
**wiki administrators** are rows here: a person on Discord or Telegram, and
the name of their account on Fandom.

The appointment is global and the standing is not. A row says only that this
person may ask the bot to work; whether they may ask it on *this* wiki is
decided on that wiki, every time, by wiki/rights.py: is_wiki_staff. So a row
is cheap to give and cannot be used to borrow rights the person does not have
where they are trying to use them.

A person is recognised by (platform, user_id) — the numeric id on Discord or
on Telegram — because that is the only thing about an account that does not
change. display_name is kept for the log line and is refreshed on the way
past; it is never what identifies anybody.
"""
import time

from db import conn, cur

PLATFORMS = ("discord", "telegram")


def add_wiki_admin(platform, user_id, wiki_user, display_name=None, added_by=None):
    """Appoint one person, or update the Fandom account of one already there.

    Re-appointing is how the Fandom name is corrected, so the row is written
    rather than refused; the caller is the one that reports which of the two
    happened."""
    cur.execute(
        """
        INSERT INTO wiki_admins
            (platform, user_id, wiki_user, display_name, added_by, added_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(platform, user_id) DO UPDATE SET
            wiki_user=excluded.wiki_user,
            display_name=COALESCE(excluded.display_name, wiki_admins.display_name),
            added_by=excluded.added_by
        """,
        (str(platform), int(user_id), str(wiki_user).strip(),
         display_name, added_by, int(time.time())),
    )
    conn.commit()


def remove_wiki_admin(platform, user_id):
    """Take the appointment away. -> whether there was one."""
    row = get_wiki_admin(platform, user_id)
    cur.execute("DELETE FROM wiki_admins WHERE platform=? AND user_id=?",
                (str(platform), int(user_id)))
    conn.commit()
    return row is not None


def get_wiki_admin(platform, user_id):
    """The row of one person, or None when they were never appointed."""
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return None
    return cur.execute(
        "SELECT * FROM wiki_admins WHERE platform=? AND user_id=?",
        (str(platform), uid),
    ).fetchone()


def list_wiki_admins(platform=None):
    """Everyone appointed, oldest first — the order /wikiadmin prints them in."""
    if platform:
        return cur.execute(
            "SELECT * FROM wiki_admins WHERE platform=? ORDER BY added_at, user_id",
            (str(platform),),
        ).fetchall()
    return cur.execute(
        "SELECT * FROM wiki_admins ORDER BY platform, added_at, user_id"
    ).fetchall()


def touch_display_name(platform, user_id, display_name):
    """Keep the stored display name in step with the messenger's.

    Called on the way past when somebody uses a command. Nothing depends on
    it — it exists so the service log can name a person the way their
    teammates would, next to the id that actually identifies them."""
    if not display_name:
        return
    cur.execute(
        "UPDATE wiki_admins SET display_name=? WHERE platform=? AND user_id=?",
        (str(display_name), str(platform), int(user_id)),
    )
    conn.commit()
