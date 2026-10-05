"""Sponsor wiki ownership and atomic daily task/page budgets."""
from datetime import datetime, timezone
import secrets
import time

from db import _db_lock, conn, cur

GRACE_SECONDS = 30 * 86400
COMMUNITY_WAIT_SECONDS = 7 * 86400
COMMUNITY_GRACE_SECONDS = 86400

def _rank(tier):
    """A community role ranks below a paid role and above no role."""
    return 0 if tier == -1 else -1 if tier == 0 else tier

def _community_ready(row, now):
    return bool(row["community_role_since"] is not None and
                now - int(row["community_role_since"]) >= COMMUNITY_WAIT_SECONDS)

def observe_community_role(discord_id, present):
    """Start the seven-day clock on first observation, resetting on removal."""
    owner = str(discord_id)
    now = int(time.time())
    row = cur.execute("SELECT community_role_present FROM sponsor_tiers WHERE discord_id=?",
                      (owner,)).fetchone()
    if row is None and not present:
        return
    if row is None:
        cur.execute("INSERT INTO sponsor_tiers"
                    " (discord_id,tier,checked_at,community_role_since,community_role_present)"
                    " VALUES (?,0,?,?,1)", (owner, now, now))
    elif present and not row["community_role_present"]:
        cur.execute("UPDATE sponsor_tiers SET community_role_since=?,community_role_present=1"
                    " WHERE discord_id=?", (now, owner))
    elif not present and row["community_role_present"]:
        cur.execute("UPDATE sponsor_tiers SET community_role_present=0 WHERE discord_id=?",
                    (owner,))
    conn.commit()

def paid_sponsor_tier(discord_id):
    """Tier on the most recent successful Patreon role check."""
    row = cur.execute("SELECT tier FROM sponsor_tiers WHERE discord_id=?",
                      (str(discord_id),)).fetchone()
    return int(row[0]) if row else 0

def sponsor_tier(discord_id):
    """Effective tier after role maturity and the applicable grace period."""
    row = cur.execute("SELECT tier,grace_since,grace_tier,community_role_since,"
                      " community_role_present FROM sponsor_tiers WHERE discord_id=?",
                      (str(discord_id),)).fetchone()
    if row is None:
        return 0
    now = time.time()
    tier = int(row["tier"])
    former = int(row["grace_tier"] or 0)
    window = COMMUNITY_GRACE_SECONDS if former == -1 else GRACE_SECONDS
    if (row["grace_since"] is not None and former
            and _rank(former) > _rank(tier)
            and now - int(row["grace_since"]) < window):
        return former
    if tier == -1:
        return -1 if _community_ready(row, now) else 0
    return tier

def sponsor_grace_days(discord_id):
    """Whole days of continued operation after the paid role vanished."""
    row = cur.execute("SELECT tier,grace_since,grace_tier FROM sponsor_tiers WHERE discord_id=?",
                      (str(discord_id),)).fetchone()
    if not row or row["grace_since"] is None or not row["grace_tier"]:
        return 0
    window = COMMUNITY_GRACE_SECONDS if row["grace_tier"] == -1 else GRACE_SECONDS
    left = window - (time.time() - int(row["grace_since"]))
    return max(0, int((left + 86399) // 86400))

def save_sponsor_tier(discord_id, tier):
    """Update a tier after a successful Discord role read."""
    now = int(time.time())
    old = cur.execute("SELECT tier,grace_since,grace_tier FROM sponsor_tiers WHERE discord_id=?",
                      (str(discord_id),)).fetchone()
    previous = sponsor_tier(discord_id)
    if _rank(tier) < _rank(previous):
        grace_since, grace_tier = now, previous
    elif old and old["grace_since"] and _rank(old["grace_tier"] or 0) > _rank(tier):
        grace_since, grace_tier = old["grace_since"], old["grace_tier"]
    else:
        grace_since, grace_tier = None, None
    cur.execute(
        "INSERT INTO sponsor_tiers"
        " (discord_id,tier,checked_at,grace_since,grace_tier) VALUES (?,?,?,?,?)"
        " ON CONFLICT(discord_id) DO UPDATE SET tier=excluded.tier,"
        " checked_at=excluded.checked_at,grace_since=excluded.grace_since,"
        " grace_tier=excluded.grace_tier",
        (str(discord_id), int(tier), now, grace_since, grace_tier)
    )
    conn.commit()

def known_sponsor_ids():
    """Accounts with a role or a preserved wiki claim."""
    return {row[0] for row in cur.execute(
        "SELECT discord_id FROM sponsor_tiers UNION SELECT discord_id FROM sponsor_wikis"
        " UNION SELECT discord_id FROM sponsor_communities"
        " WHERE discord_id NOT LIKE 'admin:%'"
    ).fetchall()}

def community_claim(platform, community_id):
    """Exact owner of a Discord guild or Telegram group, if assigned."""
    return cur.execute(
        "SELECT * FROM sponsor_communities WHERE platform=? AND community_id=?",
        (str(platform), str(community_id)),
    ).fetchone()

def claimed_communities(discord_id):
    """Active and retained community slots held by one subscription."""
    return cur.execute(
        "SELECT * FROM sponsor_communities WHERE discord_id=?"
        " ORDER BY claimed_at,platform,community_id", (str(discord_id),),
    ).fetchall()

def claim_community(platform, community_id, discord_id, takeover_from=None):
    """Assign one community only when empty or owned by the expected account."""
    owner = str(discord_id)
    with _db_lock:
        current = community_claim(platform, community_id)
        if (not owner.startswith("admin:") and
                (current is None or str(current["discord_id"]) != owner) and
                sponsor_slot_wait_days(owner)):
            return False
        if takeover_from is None:
            changed = cur.execute(
                "INSERT INTO sponsor_communities"
                " (platform,community_id,discord_id,claimed_at) VALUES (?,?,?,?)"
                " ON CONFLICT(platform,community_id) DO NOTHING",
                (str(platform), str(community_id), owner, int(time.time())),
            )
        else:
            changed = cur.execute(
                "UPDATE sponsor_communities SET discord_id=?,claimed_at=?"
                " WHERE platform=? AND community_id=? AND discord_id=?",
                (owner, int(time.time()), str(platform), str(community_id),
                 str(takeover_from)),
            )
        conn.commit()
        return bool(changed.rowcount)

def release_community(platform, community_id, discord_id):
    """Release only the exact owner's assignment."""
    changed = cur.execute(
        "DELETE FROM sponsor_communities WHERE platform=? AND community_id=?"
        " AND discord_id=?", (str(platform), str(community_id), str(discord_id)),
    )
    if changed.rowcount and not str(discord_id).startswith("admin:"):
        cur.execute("UPDATE sponsor_tiers SET slot_changed_at=? WHERE discord_id=?",
                    (int(time.time()), str(discord_id)))
    conn.commit()
    return bool(changed.rowcount)

def due_sponsor_communities(now=None):
    """Assignments beyond the role grace and thirty more days."""
    instant = int(now if now is not None else time.time())
    return cur.execute(
        "SELECT sc.* FROM sponsor_communities sc JOIN sponsor_tiers st"
        " ON st.discord_id=sc.discord_id WHERE st.tier=0"
        " AND st.grace_since IS NOT NULL AND st.grace_tier IS NOT NULL"
        " AND st.grace_since + CASE WHEN st.grace_tier=-1 THEN 86400"
        " ELSE 2592000 END + 2592000<=?", (instant,),
    ).fetchall()

def purge_sponsor_community(platform, community_id, discord_id, channel_ids=()):
    """Erase only jobs addressed to this departed community, then its claim.

    Discord task destinations are channels rather than guilds, so the caller
    supplies channel IDs captured before leaving. Unknown destinations are
    retained; guessing their guild from a numeric ID could delete other work.
    """
    if not any(row["platform"] == str(platform)
               and row["community_id"] == str(community_id)
               and row["discord_id"] == str(discord_id)
               for row in due_sponsor_communities()):
        return False
    destinations = ([str(community_id)] if platform == "telegram"
                    else [str(value) for value in channel_ids])
    with _db_lock:
        cur.execute(
            "DELETE FROM task_pages WHERE task_id IN"
            " (SELECT id FROM tasks WHERE community_platform=? AND community_id=?)",
            (str(platform), str(community_id)),
        )
        for table in ("schedules", "tasks"):
            cur.execute(
                f"DELETE FROM {table} WHERE community_platform=? AND community_id=?",
                (str(platform), str(community_id)),
            )
        for destination in destinations:
            prefix = f"{platform}:{destination}"
            for table in ("schedules", "tasks"):
                if table == "tasks":
                    cur.execute(
                        "DELETE FROM task_pages WHERE task_id IN"
                        " (SELECT id FROM tasks WHERE reply_chat=? OR reply_chat LIKE ?)",
                        (prefix, prefix + ":%"),
                    )
                cur.execute(
                    f"DELETE FROM {table} WHERE reply_chat=? OR reply_chat LIKE ?",
                    (prefix, prefix + ":%"),
                )
        cur.execute(
            "DELETE FROM sponsor_communities WHERE platform=? AND community_id=?"
            " AND discord_id=?", (str(platform), str(community_id), str(discord_id)),
        )
        conn.commit()
    return True

def claimed_wikis(discord_id):
    """Wiki slots held by one Discord account."""
    return cur.execute("SELECT * FROM sponsor_wikis WHERE discord_id=? ORDER BY claimed_at,wiki",
                       (str(discord_id),)).fetchall()

def wiki_claim(wiki):
    """Owner and Fandom account for a wiki, if claimed."""
    return cur.execute("SELECT * FROM sponsor_wikis WHERE wiki=?", (str(wiki),)).fetchone()

def claim_wiki(wiki, discord_id, wiki_user, takeover_from=None,
               bypass_cooldown=False):
    """Never displace another sponsor's wiki claim."""
    current = wiki_claim(wiki)
    if (not bypass_cooldown and
            (current is None or str(current["discord_id"]) != str(discord_id)) and
            sponsor_slot_wait_days(discord_id)):
        return False
    if takeover_from is None:
        cur.execute(
            "INSERT INTO sponsor_wikis (wiki,discord_id,wiki_user,claimed_at)"
            " VALUES (?,?,?,?) ON CONFLICT(wiki) DO UPDATE SET"
            " wiki_user=excluded.wiki_user WHERE discord_id=excluded.discord_id",
            (str(wiki), str(discord_id), str(wiki_user), int(time.time()))
        )
    else:
        cur.execute(
            "UPDATE sponsor_wikis SET discord_id=?,wiki_user=?,claimed_at=?"
            " WHERE wiki=? AND discord_id=?",
            (str(discord_id), str(wiki_user), int(time.time()),
             str(wiki), str(takeover_from)),
        )
    conn.commit()
    row = wiki_claim(wiki)
    return bool(row and row["discord_id"] == str(discord_id))

def due_sponsor_wikis(now=None):
    """Claims whose paid or community-role grace plus retention has ended."""
    instant = int(now if now is not None else time.time())
    return cur.execute(
        "SELECT sw.* FROM sponsor_wikis sw JOIN sponsor_tiers st"
        " ON st.discord_id=sw.discord_id WHERE st.tier=0"
        " AND st.grace_since IS NOT NULL AND st.grace_tier IS NOT NULL"
        " AND st.grace_since + CASE WHEN st.grace_tier=-1 THEN 86400"
        " ELSE 2592000 END + 2592000 <=?",
        (instant,),
    ).fetchall()

def purge_sponsor_wiki(wiki, discord_id):
    """Remove a lapsed wiki's claim, scheduled jobs and task history.

    Rechecks ownership and deadline in one scheduler job before deleting.
    Published wiki edits and shared channel posts are outside this database
    and are not touched. The wiki itself is never a chat to leave.
    """
    owner = str(discord_id)
    key = str(wiki)
    if not any(row["wiki"] == key and row["discord_id"] == owner
               for row in due_sponsor_wikis()):
        return False
    ids = "SELECT id FROM tasks WHERE wiki=?"
    cur.execute(f"DELETE FROM task_pages WHERE task_id IN ({ids})", (key,))
    cur.execute("DELETE FROM tasks WHERE wiki=?", (key,))
    cur.execute("DELETE FROM schedules WHERE wiki=?", (key,))
    cur.execute("DELETE FROM wiki_slots WHERE wiki=?", (key,))
    cur.execute("DELETE FROM sponsor_wikis WHERE wiki=? AND discord_id=?",
                (key, owner))
    conn.commit()
    return True

def release_wiki(wiki, discord_id):
    """Release only the caller's claim; existing tasks remain recorded."""
    changed = cur.execute("DELETE FROM sponsor_wikis WHERE wiki=? AND discord_id=?",
                          (str(wiki), str(discord_id)))
    if changed.rowcount:
        cur.execute("UPDATE sponsor_tiers SET slot_changed_at=? WHERE discord_id=?",
                    (int(time.time()), str(discord_id)))
    conn.commit()
    return bool(changed.rowcount)

def sponsor_slot_wait_days(discord_id, cooldown_days=30):
    """Days until a released wiki or community slot may be used again."""
    row = cur.execute("SELECT slot_changed_at FROM sponsor_tiers WHERE discord_id=?",
                      (str(discord_id),)).fetchone()
    if not row or row[0] is None:
        return 0
    remaining = int(row[0]) + cooldown_days * 86400 - time.time()
    return max(0, int((remaining + 86399) // 86400))

def sponsor_usage(discord_id):
    """Today UTC's task and page totals."""
    day = datetime.now(timezone.utc).date().isoformat()
    row = cur.execute("SELECT tasks,pages FROM sponsor_usage WHERE discord_id=? AND day=?",
                      (str(discord_id), day)).fetchone()
    return (int(row[0]), int(row[1])) if row else (0, 0)

def spend_sponsor_unit(discord_id, column, limit, amount=1):
    """Reserve a task or planned pages atomically before work begins."""
    if column not in {"tasks", "pages"}:
        raise ValueError(column)
    if amount < 0 or amount > int(limit):
        return False
    day = datetime.now(timezone.utc).date().isoformat()
    with _db_lock:
        changed = cur.execute(
            f"INSERT INTO sponsor_usage (discord_id,day,{column}) VALUES (?,?,?)"
            f" ON CONFLICT(discord_id,day) DO UPDATE SET {column}={column}+excluded.{column}"
            f" WHERE {column}+excluded.{column} <= ?",
            (str(discord_id), day, int(amount), int(limit))
        )
        conn.commit()
        return bool(changed.rowcount)

def linked_discord_id(telegram_id):
    """Discord subscription shared by this explicitly linked Telegram user."""
    row = cur.execute("SELECT discord_id FROM sponsor_account_links WHERE telegram_id=?",
                      (str(telegram_id),)).fetchone()
    return str(row[0]) if row else None

def linked_telegram_id(discord_id):
    """Telegram account paired with this Discord identity, if any."""
    row = cur.execute("SELECT telegram_id FROM sponsor_account_links WHERE discord_id=?",
                      (str(discord_id),)).fetchone()
    return str(row[0]) if row else None

def create_sponsor_link_code(discord_id):
    """One short-lived code, issued only to the authenticated Discord user."""
    code = secrets.token_urlsafe(16)
    with _db_lock:
        cur.execute("DELETE FROM sponsor_link_codes WHERE expires_at<=?", (int(time.time()),))
        cur.execute("DELETE FROM sponsor_link_codes WHERE discord_id=?", (str(discord_id),))
        cur.execute("INSERT INTO sponsor_link_codes (discord_id,code,expires_at)"
                    " VALUES (?,?,?)", (str(discord_id), code, int(time.time()) + 600))
        conn.commit()
    return code

def consume_sponsor_link_code(telegram_id, code):
    """Pair accounts exactly once; return the Discord ID on success."""
    with _db_lock:
        row = cur.execute("SELECT discord_id FROM sponsor_link_codes"
                          " WHERE code=? AND expires_at>?", (str(code), int(time.time()))).fetchone()
        if row is None:
            return None
        discord_id = str(row[0])
        cur.execute("DELETE FROM sponsor_account_links"
                    " WHERE discord_id=? OR telegram_id=?", (discord_id, str(telegram_id)))
        cur.execute("INSERT INTO sponsor_account_links"
                    " (discord_id,telegram_id,linked_at) VALUES (?,?,?)",
                    (discord_id, str(telegram_id), int(time.time())))
        cur.execute("DELETE FROM sponsor_link_codes WHERE discord_id=?", (discord_id,))
        conn.commit()
    return discord_id

def unlink_sponsor_account(platform, user_id):
    """Either linked account may revoke the pairing immediately."""
    column = "discord_id" if platform == "discord" else "telegram_id"
    with _db_lock:
        changed = cur.execute(f"DELETE FROM sponsor_account_links WHERE {column}=?",
                              (str(user_id),))
        conn.commit()
        return bool(changed.rowcount)
