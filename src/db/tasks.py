"""One run of the script mechanics: the row, its page list and its counters.

A task is a row in `tasks` plus the pages it is to walk in `task_pages`. The
pages are settled before the first edit and never re-derived, and that one
decision is what makes everything else work:

* the run can be **interrupted between chunks** and give the worker back to
  the news pass, then carry on at `tasks.cursor` (answer to the fifteen-minute
  schedule: a walk of nine thousand articles must not hold the main pages
  hostage);
* it **survives a restart** — the queue picks the task up at the next page
  rather than at the first;
* the person who asked can be told **how many pages** are involved before
  anything is written, which is what the confirmation is for.

State moves pending -> running -> done | failed | stopped. 'pending' is also
where a task waits to be confirmed, so a task nobody confirms simply never
runs and can be deleted.

Not this module's zone: what a mechanic does to a page (scripts/, tasks/), and
when a repeating task comes due (db/schedules.py).
"""
import json
import time

from db import _db_lock, conn, cur

STATES = ("pending", "running", "done", "failed", "stopped")

PAGE_STATES = ("todo", "done", "skip", "fail")


def create_task(wiki, mechanics, params, requester, dry_run=False,
                schedule_id=None, reply_chat=None):
    """Open a task in the 'pending' state. -> its id.

    `mechanics` is the list of codes to run over each page, in order;
    `params` is everything the dialog collected; `requester` is the mapping
    tasks/access.py builds — platform, id, display name and Fandom account.
    """
    now = int(time.time())
    row = cur.execute(
        """
        INSERT INTO tasks
            (wiki, mechanics, params, state, dry_run,
             requested_by_platform, requested_by_id, requested_by_name,
             requested_by_wiki_user, reply_chat, schedule_id, created_at)
        VALUES (?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (str(wiki), json.dumps(list(mechanics), ensure_ascii=False),
         json.dumps(dict(params or {}), ensure_ascii=False),
         1 if dry_run else 0,
         (requester or {}).get("platform"), (requester or {}).get("id"),
         (requester or {}).get("name"), (requester or {}).get("wiki_user"),
         reply_chat, schedule_id, now),
    )
    conn.commit()
    return row.lastrowid


def get_task(task_id):
    """One task's row, or None."""
    return cur.execute("SELECT * FROM tasks WHERE id=?", (int(task_id),)).fetchone()


def task_mechanics(row):
    """The mechanic codes of one task, as a list."""
    try:
        return json.loads(row["mechanics"])
    except (TypeError, ValueError):
        return []


def task_params(row):
    """The parameters of one task, as a dict."""
    try:
        return json.loads(row["params"] or "{}")
    except (TypeError, ValueError):
        return {}


def task_report(row):
    """The counters of one task, as a dict; empty while it is still running."""
    try:
        return json.loads(row["report"] or "{}")
    except (TypeError, ValueError):
        return {}


def set_task_state(task_id, state, error=None, *, expected_state=None):
    """Move a task to another state, stamping the time where it matters.

    Not `set_state`, and the name is load-bearing. db/slots.py has a
    `set_state(key, value)` of its own — the bot's own bookkeeping, which is
    what stores the resolved channel and the time of the last pass — and both
    are re-exported flat from db/__init__.py. Two functions of the same name
    there means the later import silently wins, and every caller of the other
    one starts failing on its first argument. That is exactly what happened:
    `db.set_state("last_pass_ts", …)` reached this function and died on
    `int("last_pass_ts")`, so a news pass that had already written its slots
    reported itself as a failure every fifteen minutes.
    With expected_state, the transition succeeds only from that state. This
    keeps a worker finishing a slow plan from reviving a task stopped by the
    messenger thread. The check and update share the database lock.
    """
    with _db_lock:
        if expected_state is not None:
            row = get_task(task_id)
            if row is None or row["state"] != expected_state:
                return False
        now = int(time.time())
        if state == "running":
            cur.execute("UPDATE tasks SET state=?, started_at=COALESCE(started_at, ?) "
                        "WHERE id=?", (state, now, int(task_id)))
        elif state in ("done", "failed", "stopped"):
            cur.execute("UPDATE tasks SET state=?, finished_at=?, error=? WHERE id=?",
                        (state, now, error, int(task_id)))
        else:
            cur.execute("UPDATE tasks SET state=? WHERE id=?", (state, int(task_id)))
        conn.commit()
        return True


def set_dry_run(task_id, dry_run=True):
    """Make a task a preview run, or stop being one.

    Set between the plan and the start, which is where `/go <id> dry` sits:
    the page list is already settled, and all that changes is whether the
    edits are written or only counted.
    """
    cur.execute("UPDATE tasks SET dry_run=? WHERE id=?",
                (1 if dry_run else 0, int(task_id)))
    conn.commit()


def set_report(task_id, report):
    """Store the counters a finished (or paused) run has reached."""
    cur.execute("UPDATE tasks SET report=? WHERE id=?",
                (json.dumps(dict(report or {}), ensure_ascii=False), int(task_id)))
    conn.commit()


def bump(task_id, checked=0, edited=0, failed=0, cursor=None):
    """Add to a running task's counters and move its cursor.

    Written after every chunk rather than after every page: the numbers are
    for a person reading a progress line, and a commit per page over nine
    thousand pages is a cost with nothing to show for it."""
    if cursor is None:
        cur.execute("UPDATE tasks SET checked=checked+?, edited=edited+?, "
                    "failed=failed+? WHERE id=?",
                    (int(checked), int(edited), int(failed), int(task_id)))
    else:
        cur.execute("UPDATE tasks SET checked=checked+?, edited=edited+?, "
                    "failed=failed+?, cursor=? WHERE id=?",
                    (int(checked), int(edited), int(failed), int(cursor),
                     int(task_id)))
    conn.commit()


def set_pages(task_id, titles):
    """Settle the page list of a task. -> how many pages there are.

    Called once, before the first edit. Re-setting the list clears whatever
    was there, so a task that is re-planned does not inherit half an old
    walk."""
    cur.execute("DELETE FROM task_pages WHERE task_id=?", (int(task_id),))
    rows = [(int(task_id), seq, str(title))
            for seq, title in enumerate(titles, 1)]
    cur.executemany(
        "INSERT INTO task_pages (task_id, seq, title, state) VALUES (?, ?, ?, 'todo')",
        rows)
    conn.commit()
    return len(rows)


def count_pages(task_id, state=None):
    """How many pages a task holds, in total or in one state."""
    if state:
        row = cur.execute(
            "SELECT COUNT(*) AS n FROM task_pages WHERE task_id=? AND state=?",
            (int(task_id), str(state))).fetchone()
    else:
        row = cur.execute("SELECT COUNT(*) AS n FROM task_pages WHERE task_id=?",
                          (int(task_id),)).fetchone()
    return row["n"] if row else 0


def next_pages(task_id, after, limit):
    """The next chunk of pages still to do, in order. -> list of rows."""
    return cur.execute(
        "SELECT * FROM task_pages WHERE task_id=? AND seq>? AND state='todo' "
        "ORDER BY seq LIMIT ?",
        (int(task_id), int(after), int(limit))).fetchall()


def page_titles(task_id, limit=None):
    """The titles of a task's pages, in order — what the preview prints."""
    sql = "SELECT title FROM task_pages WHERE task_id=? ORDER BY seq"
    params = [int(task_id)]
    if limit:
        sql += " LIMIT ?"
        params.append(int(limit))
    return [row["title"] for row in cur.execute(sql, tuple(params)).fetchall()]


def mark_page(task_id, seq, state, note=None):
    """Record what happened to one page."""
    cur.execute("UPDATE task_pages SET state=?, note=? WHERE task_id=? AND seq=?",
                (str(state), note, int(task_id), int(seq)))


def record_task_page(task_id, seq, state, note=None, report=None):
    """Commit one completed page, counters and restart data together.

    A chunk can be interrupted after any wiki request. Deferring its SQL
    commit until the end would repeat earlier edits after a process restart.
    The shared connection lock also prevents a messenger commit from splitting
    this transaction. A completed page is never counted twice.
    """
    with _db_lock:
        try:
            changed = cur.execute(
                "UPDATE task_pages SET state=?, note=? "
                "WHERE task_id=? AND seq=? AND state='todo'",
                (str(state), note, int(task_id), int(seq))).rowcount
            if changed:
                cur.execute(
                    "UPDATE tasks SET checked=checked+1, edited=edited+?, "
                    "failed=failed+?, cursor=?, report=? WHERE id=?",
                    (int(state == "done"), int(state == "fail"), int(seq),
                     json.dumps(dict(report or {}), ensure_ascii=False),
                     int(task_id)))
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def failed_pages(task_id, limit=200):
    """The pages that would not be written, with the reason — for the report."""
    return cur.execute(
        "SELECT title, note FROM task_pages WHERE task_id=? AND state='fail' "
        "ORDER BY seq LIMIT ?", (int(task_id), int(limit))).fetchall()


def active_tasks():
    """Every task that is running or waiting, oldest first.

    'confirm' is in the list because a task waiting for somebody to type /go
    is very much active from a person's point of view — leaving it out of
    /jobs would make a forgotten task invisible.
    """
    return cur.execute(
        "SELECT * FROM tasks WHERE state IN ('pending', 'confirm', 'running') "
        "ORDER BY id").fetchall()


def recent_tasks(limit=10):
    """The last few tasks, newest first — what /jobs prints under the queue."""
    return cur.execute("SELECT * FROM tasks ORDER BY id DESC LIMIT ?",
                       (int(limit),)).fetchall()


def running_task():
    """The task the worker is on, or None."""
    return cur.execute(
        "SELECT * FROM tasks WHERE state='running' ORDER BY id LIMIT 1").fetchone()


def cleanup_tasks(keep_days=30):
    """Forget the page lists of tasks that finished long ago.

    The rows in `tasks` are kept — they are the record of who asked the bot to
    do what — but a finished walk of nine thousand pages has no reason to keep
    nine thousand rows of 'done' beside it."""
    cutoff = int(time.time()) - int(keep_days) * 86400
    cur.execute(
        "DELETE FROM task_pages WHERE task_id IN "
        "(SELECT id FROM tasks WHERE finished_at IS NOT NULL AND finished_at < ?)",
        (cutoff,))
    conn.commit()
