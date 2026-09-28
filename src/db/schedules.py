"""Tasks that repeat: by the hour, by the day, or on named days of the week.

A schedule is a task that has not happened yet. It stores the same three
things a task does — which wiki, which mechanics, which parameters — plus when
it is due, and every time it fires it opens an ordinary task row and puts it in
the queue. That means a repeating run is watched, reported and stopped exactly
like one somebody asked for by hand.

`next_run` is stored rather than computed on the fly, and it is recomputed
*forward from now* after every firing. A bot that was down over its hour
therefore runs once when it comes back, not once for every hour it missed —
which for a walk of a whole wiki is the difference between a catch-up and a
flood.

Three shapes, and they cover what a person is likely to want:

* `hourly` — at the given minutes of every hour ('0,30');
* `daily` — at hour:minute every day;
* `weekly` — at hour:minute on the listed weekdays, 0 = Monday.
"""
import json
import time
from datetime import datetime, timedelta

from db import conn, cur

KINDS = ("hourly", "daily", "weekly")


def _parse_ints(text):
    """'0,15,30' -> [0, 15, 30]; anything unparseable is dropped."""
    out = []
    for part in str(text or "").replace(" ", "").split(","):
        if part.isdigit():
            out.append(int(part))
    return sorted(set(out))


def next_due(kind, minutes=None, hour=None, minute=None, weekdays=None, now=None):
    """When a schedule of this shape is next due. -> a unix timestamp.

    Always strictly in the future, so that recomputing right after a firing
    cannot hand back the moment that has just passed.
    """
    now = now or datetime.now()
    now = now.replace(second=0, microsecond=0) + timedelta(minutes=1)

    if kind == "hourly":
        marks = _parse_ints(minutes) or [0]
        for mark in marks:
            moment = now.replace(minute=mark % 60)
            if moment >= now:
                return int(moment.timestamp())
        return int((now + timedelta(hours=1)).replace(minute=marks[0] % 60).timestamp())

    target_hour = int(hour or 0) % 24
    target_minute = int(minute or 0) % 60

    if kind == "daily":
        moment = now.replace(hour=target_hour, minute=target_minute)
        if moment < now:
            moment += timedelta(days=1)
        return int(moment.timestamp())

    days = _parse_ints(weekdays)
    days = [d % 7 for d in days] or [0]
    for ahead in range(0, 8):
        moment = (now + timedelta(days=ahead)).replace(
            hour=target_hour, minute=target_minute)
        if moment >= now and moment.weekday() in days:
            return int(moment.timestamp())
    return int((now + timedelta(days=7)).timestamp())


PENDING = "pending"
"""The approval state of a schedule no bot administrator has said yes to."""


def create_schedule(wiki, mechanics, params, kind, requester, minutes=None,
                    hour=None, minute=None, weekdays=None, reply_chat=None,
                    pending=False):
    """Add a repeating run. -> its id.

    `pending` makes it wait for a bot administrator (discord_bot/approvals.py):
    written disabled and marked PENDING, so it fires nothing until
    `approve_schedule`, and `set_enabled` will not switch it on either.
    """
    now = int(time.time())
    row = cur.execute(
        """
        INSERT INTO schedules
            (wiki, mechanics, params, kind, minutes, hour, minute, weekdays,
             enabled, created_by_platform, created_by_id, created_by_name,
             created_by_wiki_user, reply_chat, created_at, next_run, approval)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (str(wiki), json.dumps(list(mechanics), ensure_ascii=False),
         json.dumps(dict(params or {}), ensure_ascii=False),
         str(kind), minutes, hour, minute, weekdays, 0 if pending else 1,
         (requester or {}).get("platform"), (requester or {}).get("id"),
         (requester or {}).get("name"), (requester or {}).get("wiki_user"),
         reply_chat, now,
         next_due(kind, minutes, hour, minute, weekdays),
         PENDING if pending else None),
    )
    conn.commit()
    return row.lastrowid


def is_pending(row):
    """Whether a schedule still waits for a bot administrator's decision."""
    try:
        return row["approval"] == PENDING
    except (IndexError, KeyError, TypeError):
        return False


def approve_schedule(schedule_id):
    """Let a pending schedule run. -> its row, or None when it was not pending.

    The next moment is worked out from now, as when a schedule is switched
    back on: an approval that took a day does not owe a day of runs.
    """
    row = get_schedule(schedule_id)
    if row is None or not is_pending(row):
        return None
    cur.execute(
        "UPDATE schedules SET approval=NULL, enabled=1, next_run=? "
        "WHERE id=? AND approval=?",
        (next_due(row["kind"], row["minutes"], row["hour"], row["minute"],
                  row["weekdays"]), int(schedule_id), PENDING))
    conn.commit()
    return get_schedule(schedule_id)


def reject_schedule(schedule_id):
    """Throw a pending schedule away. -> the row it was, or None."""
    row = get_schedule(schedule_id)
    if row is None or not is_pending(row):
        return None
    cur.execute("DELETE FROM schedules WHERE id=? AND approval=?",
                (int(schedule_id), PENDING))
    conn.commit()
    return row


def get_schedule(schedule_id):
    """One schedule's row, or None."""
    return cur.execute("SELECT * FROM schedules WHERE id=?",
                       (int(schedule_id),)).fetchone()


def list_schedules(enabled_only=False):
    """Every repeating run, oldest first."""
    if enabled_only:
        return cur.execute(
            "SELECT * FROM schedules WHERE enabled=1 ORDER BY id").fetchall()
    return cur.execute("SELECT * FROM schedules ORDER BY id").fetchall()


def due_schedules(now=None):
    """The schedules whose moment has come."""
    moment = int(now or time.time())
    return cur.execute(
        "SELECT * FROM schedules WHERE enabled=1 AND next_run IS NOT NULL "
        "AND next_run <= ? ORDER BY next_run", (moment,)).fetchall()


def next_schedule(now=None):
    """The enabled repeating run that comes due soonest, or None.

    `next_run` is stored on the row rather than worked out here, so this is
    one indexless but tiny query over a handful of rows — which is what makes
    it cheap enough for the Discord presence to ask twice a minute.
    """
    moment = int(now or time.time())
    return cur.execute(
        "SELECT * FROM schedules WHERE enabled=1 AND next_run IS NOT NULL "
        "AND next_run > ? ORDER BY next_run LIMIT 1", (moment,)).fetchone()


def mark_fired(row):
    """Record that a schedule has just fired and move it to its next moment."""
    cur.execute(
        "UPDATE schedules SET last_run=?, next_run=? WHERE id=?",
        (int(time.time()),
         next_due(row["kind"], row["minutes"], row["hour"], row["minute"],
                  row["weekdays"]),
         int(row["id"])))
    conn.commit()


def set_enabled(schedule_id, enabled):
    """Switch a repeating run on or off without losing it. -> whether it exists.

    A schedule waiting for approval is left as it is, and reported as not
    switched: switching it on would be the way round the approval. The
    commands say why before they get here."""
    row = get_schedule(schedule_id)
    if row is None or is_pending(row):
        return False
    if enabled:
        cur.execute(
            "UPDATE schedules SET enabled=1, next_run=? WHERE id=?",
            (next_due(row["kind"], row["minutes"], row["hour"], row["minute"],
                      row["weekdays"]), int(schedule_id)))
    else:
        cur.execute("UPDATE schedules SET enabled=0 WHERE id=?", (int(schedule_id),))
    conn.commit()
    return True


def delete_schedule(schedule_id):
    """Remove a repeating run. -> whether there was one."""
    existed = get_schedule(schedule_id) is not None
    cur.execute("DELETE FROM schedules WHERE id=?", (int(schedule_id),))
    conn.commit()
    return existed


def schedule_mechanics(row):
    """The mechanic codes of one schedule, as a list."""
    try:
        return json.loads(row["mechanics"])
    except (TypeError, ValueError):
        return []


def schedule_params(row):
    """The parameters of one schedule, as a dict."""
    try:
        return json.loads(row["params"] or "{}")
    except (TypeError, ValueError):
        return {}
