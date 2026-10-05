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

On Telegram an appointment is made by @name, like on Discord it is made by
picking the person, and the Bot API has no way to turn that @name into an id.
So an @name the bot has no id for waits in `wiki_admin_invites` until its
holder first writes to the bot (telegram_bot/people.py), and only then
becomes a row here. Nothing is stored about anybody else who writes.
"""
import time

from db import conn, cur, _db_lock

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

INVITE_DAYS = 7
"""How long an appointment by @name waits for its person to write to the bot.

A week is enough to tell somebody «напиши боту» and short enough that an
@name given up in the meantime is unlikely to have found a new owner."""

def _invite_key(username):
    """An @name as the invitations table keys it: no '@', lower case."""
    return str(username or "").strip().lstrip("@").lower()

def _drop_lapsed_invites():
    """Forget the invitations nobody claimed in time."""
    cutoff = int(time.time()) - INVITE_DAYS * 86400
    cur.execute("DELETE FROM wiki_admin_invites WHERE added_at < ?", (cutoff,))
    conn.commit()

def add_wiki_admin_invite(username, wiki_user, added_by=None):
    """Appoint an @name whose id the bot does not know yet.

    Written again rather than refused, like `add_wiki_admin`: repeating the
    command is how the Fandom account of a waiting invitation is corrected,
    and it starts the week again."""
    cur.execute(
        """
        INSERT INTO wiki_admin_invites (username, wiki_user, added_by, added_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(username) DO UPDATE SET
            wiki_user=excluded.wiki_user,
            added_by=excluded.added_by,
            added_at=excluded.added_at
        """,
        (_invite_key(username), str(wiki_user).strip(), added_by,
         int(time.time())),
    )
    conn.commit()

def claim_wiki_admin_invite(username, user_id, display_name):
    """Atomically exchange this account's invitation for an ID appointment.

    The old two-step path deleted and committed the invitation before writing
    the appointment. If the second write failed, the invitation was lost and
    the person remained unconfirmed. A failed write now rolls both changes
    back, so the next message can retry safely.
    """
    key = _invite_key(username)
    if not key:
        return None
    with _db_lock:
        row = cur.execute("SELECT * FROM wiki_admin_invites WHERE username=?",
                          (key,)).fetchone()
        if row is None:
            return None
        expired = int(row["added_at"] or 0) < int(time.time()) - INVITE_DAYS * 86400
        try:
            if not expired:
                cur.execute(
                    "INSERT INTO wiki_admins"
                    " (platform,user_id,wiki_user,display_name,added_by,added_at)"
                    " VALUES ('telegram',?,?,?,?,?)"
                    " ON CONFLICT(platform,user_id) DO UPDATE SET"
                    " wiki_user=excluded.wiki_user,"
                    " display_name=excluded.display_name,"
                    " added_by=excluded.added_by",
                    (int(user_id), row["wiki_user"], display_name,
                     row["added_by"], int(time.time())),
                )
            cur.execute("DELETE FROM wiki_admin_invites WHERE username=?", (key,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        return None if expired else row

def list_wiki_admin_invites():
    """Every invitation still waiting, oldest first."""
    _drop_lapsed_invites()
    return cur.execute(
        "SELECT * FROM wiki_admin_invites ORDER BY added_at, username"
    ).fetchall()

def remove_wiki_admin_invite(username):
    """Withdraw a waiting invitation. -> whether there was one."""
    key = _invite_key(username)
    had = cur.execute("SELECT 1 FROM wiki_admin_invites WHERE username=?",
                      (key,)).fetchone() is not None
    cur.execute("DELETE FROM wiki_admin_invites WHERE username=?", (key,))
    conn.commit()
    return had

def wiki_admins_named(platform, display_name):
    """The appointed people currently shown under this name on a platform.

    For taking an appointment away by @name: the bot keeps each person's
    @name up to date as they use it (`touch_display_name`), and that stored
    name is the only way back from an @name to an id the bot has without
    asking the person to write."""
    return cur.execute(
        "SELECT * FROM wiki_admins WHERE platform=? AND lower(display_name)=?",
        (str(platform), str(display_name or "").strip().lower()),
    ).fetchall()
