"""What a person has chosen for themselves: for now, the language.

The one setting that belongs to a person rather than to a chat or to the bot.
Replies used to follow the Telegram client's language on Telegram and
config.SERVICE_LANG on Discord, so the same person read the bot in two
languages and could choose neither. Now `/lang` sets it per account and
utils.lang_of reads it; English is the default and is not stored.

A person is recognised by (platform, user_id), the same as in db/admins.py:
the numeric id is the only thing about an account that does not change.
"""
import time

from db import conn, cur


def get_user_lang(platform, user_id):
    """The language one person chose, or None when they chose none."""
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return None
    row = cur.execute(
        "SELECT lang FROM user_langs WHERE platform=? AND user_id=?",
        (str(platform), uid),
    ).fetchone()
    return row["lang"] if row else None


def set_user_lang(platform, user_id, lang, default=None):
    """Remember one person's language; `default` removes the row instead.

    The caller passes the default language, so that choosing it leaves
    nothing behind: a row exists only where it changes something.
    """
    if lang == default:
        cur.execute("DELETE FROM user_langs WHERE platform=? AND user_id=?",
                    (str(platform), int(user_id)))
    else:
        cur.execute(
            """
            INSERT INTO user_langs (platform, user_id, lang, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(platform, user_id) DO UPDATE SET
                lang=excluded.lang, updated_at=excluded.updated_at
            """,
            (str(platform), int(user_id), str(lang), int(time.time())),
        )
    conn.commit()
