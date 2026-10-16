"""Estimate worker time from measured page passes, excluding queue waits.

Until matching passes exist, allow ten seconds per page plus one for each
additional mechanic. Measurements include wiki reads, edits and throttling,
but exclude time yielded to module jobs. Estimates are advisory, not promises.
"""
import math
import statistics

import db

def estimate_seconds(row):
    """Estimate this settled page list using recent matching real passes."""
    codes = db.task_mechanics(row)
    samples = db.cur.execute(
        "SELECT work_seconds, timed_pages FROM tasks WHERE wiki=? AND mechanics=?"
        " AND dry_run=? AND id<>? AND timed_pages>=3 AND work_seconds>0"
        " ORDER BY id DESC LIMIT 20",
        (row["wiki"], row["mechanics"], row["dry_run"], row["id"]),
    ).fetchall()
    per_page = (statistics.median(float(s[0]) / int(s[1]) for s in samples)
                if samples else 10.0 + max(0, len(codes) - 1))
    return math.ceil(db.count_pages(row["id"]) * max(0.1, per_page))

def save_estimate(task_id):
    """Persist an estimate for the preview mode selected before admission."""
    seconds = estimate_seconds(db.get_task(task_id))
    db.cur.execute("UPDATE tasks SET estimated_seconds=? WHERE id=?", (seconds, task_id))
    db.conn.commit()
    return seconds
