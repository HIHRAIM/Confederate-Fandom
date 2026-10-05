"""The queue of jobs, the clock that fills it, and who goes first.

The bot has more than one thing to do — keep the news of two wikis in step
every quarter of an hour, walk a third wiki once a night, and run whatever
somebody has asked of it through the commands — and it must never do two of
them at the same time. Not because the sessions would clash: each wiki has its
own cookie jar and its own login (wiki/site.py), so being signed in to several
wikis at once is fine. The reason is simpler and harder: Pywikibot is
synchronous, the bot runs it in one worker thread, and a job that walks nine
thousand pages takes hours. Two jobs sharing that thread would either serialize
in an undefined order or trip over each other's edits.

So there is one worker and one queue. What is new here is that the queue is
**ordered by priority**, and that is what makes the two kinds of work live
together:

* the **modules** — the news pass and the species walk — are what the bot
  exists for and run to a schedule somebody else depends on. They have
  priority 0 and go to the front.
* the **task queue** is priority 10. It runs one *chunk* of one task and
  returns, then puts itself back in the queue. So a walk of nine thousand
  articles is not one job holding the worker for an hour; it is a hundred
  short jobs, and a news pass that comes due slips in between two of them.

A job already waiting is not queued twice — a night's walk that is somehow
still going when the next quarter of an hour arrives does not collect four
news passes behind it, only one.

Registering a job is `register(name, run, minutes=…)` for the ones that happen
at given minutes past the hour, or `daily_at="20:00"` for once a day — or
`daily_at=("04:30", "16:30")` for a job that wants a period the other shape
cannot say, such as every twelve hours. `run` is a coroutine and gets no
arguments; whatever it wants to report, it reports itself.
"""
import asyncio
import logging
from datetime import datetime, timedelta

logger = logging.getLogger("fd.scheduler")

MODULE_PRIORITY = 0

TASK_PRIORITY = 10

BACKGROUND_PRIORITY = 20
"""Work nobody is waiting for, such as the nightly archive of wiki pages: it
goes after everything else in the queue, a person's task included, and the
task queue does not step aside for it (`waiting_ahead` looks only at what is
more important than the asker)."""

_jobs = {}

_queue = []

_state = {"running": None, "started_at": None}

_wakeup = asyncio.Event()

def _daily_times(daily_at):
    """`daily_at` as a tuple of "HH:MM" strings: one time, or several.

    A bare string is one time and stays one — that is what every caller
    written before this passed, and what most of them still pass. A list or a
    tuple is several times a day, which is the only way to say a period the
    other shape cannot: `minutes` repeats every hour, `daily_at` once a day,
    and a backup that wants to happen every twelve hours falls between them.
    """
    if not daily_at:
        return ()
    if isinstance(daily_at, str):
        return (daily_at,)
    return tuple(str(item) for item in daily_at if item)

def register(name, run, minutes=None, daily_at=None, priority=MODULE_PRIORITY,
             tz=None):
    """Add one job to the schedule.

    `minutes` is a list of minutes past the hour; `daily_at` is "HH:MM", or
    several of them, in the server's own time — or in `tz`, an IANA zone
    name, for a job whose hour belongs to somebody else's clock (midnight in
    Kyiv is not midnight on a server in Frankfurt). A job with neither runs
    only when something asks for it by name. `priority` decides who waits for
    whom: lower goes first.
    """
    _jobs[name] = {"run": run, "minutes": tuple(minutes or ()),
                   "daily_at": _daily_times(daily_at), "priority": int(priority),
                   "tz": tz}

def _zone(name):
    """An IANA zone, or None when the name is unknown (logged once per ask).

    Europe/Kyiv is tried as Europe/Kiev too: the spelling changed in 2022, and
    an older zone database knows only the old one."""
    from zoneinfo import ZoneInfo

    for candidate in (name, {"Europe/Kyiv": "Europe/Kiev"}.get(name)):
        if not candidate:
            continue
        try:
            return ZoneInfo(candidate)
        except Exception:
            continue
    logger.warning("unknown time zone %r — using the server's own time", name)
    return None

def enqueue(name, reason="asked for"):
    """Put a job in the queue unless it is already there or already running.

    Inserted by priority, so a news pass queued while a hundred task chunks
    are waiting still runs next. Returns whether it was added, which is what a
    command needs to answer 'it is already running' rather than promising a
    second pass.
    """
    if name not in _jobs:
        logger.warning("no such job: %s", name)
        return False
    if _state["running"] == name or name in _queue:
        logger.info("job %s is already %s — not queued again", name,
                    "running" if _state["running"] == name else "waiting")
        return False
    priority = _jobs[name]["priority"]
    position = len(_queue)
    for index, other in enumerate(_queue):
        if _jobs[other]["priority"] > priority:
            position = index
            break
    _queue.insert(position, name)
    _wakeup.set()
    logger.info("job %s queued (%s); waiting: %s", name, reason, len(_queue))
    return True

def waiting_ahead(priority):
    """Whether anything more important than `priority` is waiting its turn.

    This is what a long job asks between chunks. The task runner checks it
    after every chunk and hands the worker back when a module job is due, so
    the main pages are never an hour behind a walk of the whole wiki.
    """
    return any(_jobs[name]["priority"] < priority for name in _queue)

def running():
    """The job under way, or None."""
    return _state["running"]

def job_names():
    """Every registered job, by name.

    What the Discord presence walks to find the next thing due. The registry
    itself stays private: a caller that could reach into `_jobs` would be a
    caller that could change one."""
    return list(_jobs)

def waiting():
    """The jobs waiting their turn, in order."""
    return list(_queue)

def next_due(name, now=None):
    """When a job is next due, or None when it is not on the clock."""
    job = _jobs.get(name)
    if not job:
        return None
    now = now or datetime.now()
    zone = _zone(job["tz"]) if job.get("tz") else None
    if zone is not None and job["daily_at"]:
        local = now.astimezone(zone)
        candidates = []
        for moment in job["daily_at"]:
            hour, _, minute = str(moment).partition(":")
            try:
                target = local.replace(hour=int(hour), minute=int(minute or 0),
                                       second=0, microsecond=0)
            except ValueError:
                logger.warning("job %s has an unreadable time %r — ignoring it",
                               name, moment)
                continue
            if target <= local:
                target = target + timedelta(days=1)
            candidates.append(target.astimezone().replace(tzinfo=None))
        return min(candidates) if candidates else None
    if job["daily_at"]:
        candidates = []
        for moment in job["daily_at"]:
            hour, _, minute = str(moment).partition(":")
            try:
                target = now.replace(hour=int(hour), minute=int(minute or 0),
                                     second=0, microsecond=0)
            except ValueError:
                logger.warning("job %s has an unreadable time %r — ignoring it",
                               name, moment)
                continue
            candidates.append(target if target > now
                              else target + timedelta(days=1))
        return min(candidates) if candidates else None
    marks = sorted({int(m) % 60 for m in job["minutes"]})
    if not marks:
        return None
    for mark in marks:
        target = now.replace(minute=mark, second=0, microsecond=0)
        if target > now:
            return target
    return (now + timedelta(hours=1)).replace(minute=marks[0], second=0,
                                              microsecond=0)

async def clock():
    """Sleep until the next job is due, queue it, sleep again.

    One sleep for all the jobs, so that a schedule of four passes an hour, one
    a night and one every minute costs one timer rather than three loops
    racing each other.
    """
    while True:
        now = datetime.now()
        due = [(next_due(name, now), name) for name in _jobs]
        due = [(moment, name) for moment, name in due if moment]
        if not due:
            await asyncio.sleep(60)
            continue
        moment, name = min(due)
        await asyncio.sleep(max(1.0, (moment - datetime.now()).total_seconds()))
        for other, other_name in due:
            if other <= datetime.now():
                enqueue(other_name, reason="on the clock")

async def worker():
    """Run the queued jobs, one at a time, for as long as the bot lives.

    Every failure stays inside its job: the queue must survive a job that
    raises, or one bad night would take the news down with it.
    """
    while True:
        if not _queue:
            _wakeup.clear()
            await _wakeup.wait()
            continue
        name = _queue.pop(0)
        _state["running"] = name
        _state["started_at"] = datetime.now()
        started = _state["started_at"]
        logger.info("job %s started", name)
        try:
            await _jobs[name]["run"]()
        except asyncio.CancelledError:
            _state["running"] = None
            raise
        except Exception:
            logger.exception("job %s failed", name)
        finally:
            if _state["running"] == name:
                logger.info("job %s finished in %s s", name,
                            int((datetime.now() - started).total_seconds()))
                _state["running"] = None
                _state["started_at"] = None

async def run():
    """The scheduler as one task: the clock and the worker together."""
    await asyncio.gather(clock(), worker())
