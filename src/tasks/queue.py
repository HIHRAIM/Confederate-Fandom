"""The job that drives the tasks: one chunk at a time, and never in the way.

This is the coroutine the scheduler knows as `tasks`. It runs at priority
TASK_PRIORITY, which is behind the modules, and each time it is given the
worker it does as much as it may:

* a schedule whose moment has come becomes a task;
* a task waiting to be planned is planned, and the person is shown what it
  will do;
* a task that has been confirmed gets its pages walked, chunk after chunk;
* a task whose pages are done is closed and reported.

It stops the moment something more important is due (`scheduler.waiting_ahead`)
and the clock hands it the worker again a minute later. That is what makes a
walk of nine thousand articles live beside a news pass that runs every quarter
of an hour: the walk goes at full speed and steps aside, rather than either
finishing first or being cut into minute-sized pieces.

Everything that touches Pywikibot goes through `asyncio.to_thread` — one
worker thread, always the same one, because the library is synchronous and
because the cookie jar it shares is not safe to have two threads in.

Not this module's zone: what a task does (tasks/runner.py), who may ask for
one (tasks/access.py) and how it is asked for (the commands).
"""
import asyncio
import logging

logger = logging.getLogger("fd.tasks.queue")

JOB = "tasks"

DEFAULT_PAGE_SECONDS = 1.0
"""How long one page is taken to cost before any real rate has been seen.

Used only for a task that is running but has not finished a chunk yet, so it
has no measured rate of its own. A read and usually a write against a Fandom
wiki with no throttle of ours in the way — near enough for a number the
message itself calls approximate."""

PLAN_SECONDS = 20.0
"""How long a task waiting *ahead* in the queue is taken to cost.

Such a task has not been planned yet, so nothing knows how many pages it will
touch — but it does not need to be known, because planning is all it will do
before it stops at 'confirm' and waits for a person to type /go. What it costs
the queue is one page count, not a walk."""


def _fire_schedules():
    """Turn every schedule whose moment has come into a task. -> their ids.

    A scheduled run needs no confirmation — it was confirmed once, when the
    schedule was made — so it is opened straight into the state a confirmed
    task waits in, and the plan will move it on by itself.
    """
    import db

    made = []
    for row in db.due_schedules():
        requester = {"platform": row["created_by_platform"],
                     "id": row["created_by_id"],
                     "name": row["created_by_name"],
                     "wiki_user": row["created_by_wiki_user"]}
        params = db.schedule_params(row)
        try:
            task_id = db.create_task(
                wiki=row["wiki"],
                mechanics=db.schedule_mechanics(row),
                params=params,
                requester=requester,
                dry_run=bool(params.get("dry_run")),
                schedule_id=row["id"],
                reply_chat=row["reply_chat"])
        except Exception:
            logger.exception("could not open a task for schedule %s", row["id"])
            continue
        db.mark_fired(row)
        made.append(task_id)
        logger.info("schedule %s fired as task %s", row["id"], task_id)
    return made


def _next_task():
    """The task to work on now, or None. Running ones before pending ones.

    A task already under way is finished before a new one is started: half a
    walk of a wiki is the worst state to leave anything in, and a person
    watching one run does not want a second one interleaved with it.
    """
    import db

    row = db.running_task()
    if row is not None:
        return row
    for row in db.active_tasks():
        if row["state"] == "pending":
            return row
    return None


def _seconds_ahead(ahead):
    """How long the tasks in front of one task will take. -> seconds.

    Each running task is asked its own rate rather than a shared one: elapsed
    time divided by pages checked. That measurement is better than it looks,
    because the elapsed time already contains every quarter-hour the task
    stood aside for a news pass — so what comes out is the rate the queue
    really moves at, not the rate the wiki answers at.

    A task that has not checked a page yet has no rate and falls back to
    DEFAULT_PAGE_SECONDS; one that is merely waiting costs PLAN_SECONDS.
    """
    import time

    import db

    now = int(time.time())
    seconds = 0.0
    for row in ahead:
        if row["state"] != "running":
            seconds += PLAN_SECONDS
            continue
        remaining = max(0, db.count_pages(row["id"]) - int(row["checked"] or 0))
        done = int(row["checked"] or 0)
        started = row["started_at"]
        if done > 0 and started:
            per_page = max(0.05, (now - int(started)) / float(done))
        else:
            per_page = DEFAULT_PAGE_SECONDS
        seconds += remaining * per_page
    return int(seconds)


def queue_place(task_id):
    """Where a task stands in the queue. -> {"position", "eta"} or None.

    None is the answer that matters most: it means the bot is about to work on
    this task and nobody needs to be told anything. A queue notice is worth
    sending only when there is a wait, and "you are first of one" is noise.

    Who counts as being ahead follows `_next_task` exactly, because a queue
    position that disagreed with the thing doing the queueing would be worse
    than none. A running task is finished before any other is begun, so it is
    ahead of everything; among running tasks the lower id goes first. A task
    in 'confirm' is ahead of nobody — it is waiting for a person, not for the
    worker, and it may never be confirmed at all.
    """
    import db

    row = db.get_task(task_id)
    if row is None:
        return None
    active = db.active_tasks()
    running = [other for other in active if other["state"] == "running"]
    if row["state"] == "running":
        ahead = [other for other in running if other["id"] < row["id"]]
    elif row["state"] == "pending":
        ahead = running + [other for other in active
                           if other["state"] == "pending" and other["id"] < row["id"]]
    else:
        return None
    if not ahead:
        return None
    return {"position": len(ahead) + 1, "eta": _seconds_ahead(ahead)}


def queue_notice(task_id, lang):
    """The line to send a person whose task has to wait, or None.

    Called at the two moments a task enters the queue — when /run creates it
    and when /go starts it — and silent at both when there is nothing in front
    of it, which is the ordinary case.
    """
    from utils import format_duration, localized

    place = queue_place(task_id)
    if place is None:
        return None
    if place["eta"] > 0:
        return localized("queue_place_eta", lang, id=task_id,
                         position=place["position"],
                         eta=format_duration(place["eta"], lang))
    return localized("queue_place", lang, id=task_id, position=place["position"])


def go_hint(chat_key, task_id, lang):
    """How to start this task, spelled the way its messenger spells it.

    Discord and Telegram take the same command with different syntax: `/go 2
    dry` there, `/go task_id: 2 dry: true` here. The plan message is built
    once and sent to whichever chat asked for it, so it cannot carry either
    spelling as a constant — and when it carried Telegram's, a person on
    Discord followed it, left the `dry` option untouched because the message
    never mentioned it, and got a real run where they had asked for a preview.

    The chat key already knows the platform (`'<platform>:<chat>[:<thread>]'`),
    which is why nothing has to be passed down from the command.
    """
    from tasks import notify
    from utils import localized

    target = notify.parse_chat(chat_key)
    platform = target[0] if target else ""
    key = "task_go_discord" if platform == "discord" else "task_go_telegram"
    return localized(key, lang, id=task_id)


def reader_lang(row):
    """The language of the person who asked for a task (utils.lang_of).

    What the person is sent is written in it; what the service chats are sent
    is written in config.SERVICE_LANG, and so is the error kept on the row,
    which is the operator's record. The two used to be one text in the
    service language, sent to both.
    """
    from utils import lang_of

    return lang_of(row["requested_by_platform"], row["requested_by_id"])


async def _plan(row):
    """Plan one task and tell the person what it will do."""
    import db
    from tasks import access, notify, registry, report, runner
    from utils import localized, service_lang

    task_id = row["id"]
    lang = reader_lang(row)
    service = service_lang()
    try:
        plan = await asyncio.to_thread(runner.plan, task_id)
    except access.Refusal as refusal:
        if db.get_task(task_id)["state"] == "stopped":
            runner.forget(task_id)
            return
        db.set_task_state(task_id, "failed", error=refusal.text(service))
        runner.forget(task_id)
        await notify.send(row["reply_chat"], refusal.text(lang))
        await notify.announce(localized("task_refused", service, id=task_id,
                                        wiki=row["wiki"],
                                        reason=refusal.text(service)))
        return
    except Exception as e:
        logger.exception("task %s could not be planned", task_id)
        if db.get_task(task_id)["state"] == "stopped":
            runner.forget(task_id)
            return
        db.set_task_state(task_id, "failed", error=report.safe_error(e, service))
        runner.forget(task_id)
        await notify.send(row["reply_chat"], localized(
            "task_plan_failed", lang, id=task_id,
            error=report.safe_error(e, lang)))
        await notify.announce(localized(
            "task_plan_failed", service, id=task_id,
            error=report.safe_error(e, service)))
        return

    fresh = db.get_task(task_id)
    if not plan or fresh is None or fresh["state"] != "confirm":
        runner.forget(task_id)
        return

    if row["schedule_id"]:
        await start(task_id, announce_only=True)
        return

    mechanics, _unknown = registry.find_all(db.task_mechanics(row))
    names = ", ".join(localized(m.name_key, lang) for m in mechanics)
    sample = "\n".join("• " + title for title in plan["sample"])
    more = plan["pages"] - len(plan["sample"])
    await notify.send(row["reply_chat"], localized(
        "task_planned", lang,
        id=task_id, wiki=plan["wiki"], mechanics=names,
        pages=plan["pages"],
        sample=sample + (("\n" + localized("task_sample_more", lang, count=more))
                         if more > 0 else ""),
        warning=localized("task_destructive", lang) if plan["destructive"] else "",
        notes="\n".join(runner.render_notes(plan["notes"], lang)),
        how=go_hint(row["reply_chat"], task_id, lang),
    ))


async def _chunk(row):
    """Walk one chunk of a running task, and close it when it is done."""
    import db
    from tasks import notify, runner
    from utils import localized, service_lang

    task_id = row["id"]
    lang = reader_lang(row)
    service = service_lang()
    try:
        more = await asyncio.to_thread(runner.run_chunk, task_id)
    except Exception as e:
        logger.exception("task %s failed while running", task_id)
        await _failed(row, e, lang, service)
        return False

    fresh = db.get_task(task_id)
    if fresh is None or fresh["state"] != "running":
        runner.forget(task_id)
        return False

    if more:
        fresh = db.get_task(task_id)
        total = db.count_pages(task_id)
        if total and fresh["checked"] and fresh["checked"] % 500 == 0:
            await notify.announce(localized(
                "task_progress", service, id=task_id, wiki=row["wiki"],
                checked=fresh["checked"], total=total, edited=fresh["edited"]))
        return True

    try:
        result = await asyncio.to_thread(runner.finish, task_id)
    except Exception as e:
        logger.exception("task %s failed to finish", task_id)
        await _failed(row, e, lang, service)
        return False

    if not result:
        runner.forget(task_id)
        return False
    key = "task_done_dry" if result.get("dry_run") else "task_done"

    def done(language):
        """The closing message, in one language."""
        return localized(key, language, id=task_id, wiki=result.get("wiki"),
                         checked=result.get("checked", 0),
                         edited=result.get("edited", 0),
                         failed=result.get("failed", 0),
                         notes="\n".join(runner.render_notes(
                             result.get("notes"), language)))

    await notify.send(row["reply_chat"], done(lang))
    await notify.send_files(row["reply_chat"], result.get("files"), lang=lang)
    await notify.announce(done(service))
    return False


async def _failed(row, error, lang, service):
    """A task that broke while running: the row, the person, the service log."""
    import db
    from tasks import notify, report, runner
    from utils import localized

    task_id = row["id"]
    db.set_task_state(task_id, "failed", error=report.safe_error(error, service))
    runner.forget(task_id)
    await notify.send(row["reply_chat"], localized(
        "task_failed", lang, id=task_id, wiki=row["wiki"],
        error=report.safe_error(error, lang)))
    await notify.announce(localized(
        "task_failed", service, id=task_id, wiki=row["wiki"],
        error=report.safe_error(error, service)))


async def start(task_id, announce_only=False):
    """Move a confirmed task into the running state and get it going.

    `announce_only` is for a scheduled run, which nobody confirmed by hand:
    it is announced and started in one step.

    Only the prepared 'confirm' state may start. A stop arriving after a
    caller's earlier check must not be overwritten by this transition.
    """
    import db
    import scheduler
    from tasks import access, notify
    from utils import localized, service_lang

    row = db.get_task(task_id)
    if row is None:
        return False
    if not db.set_task_state(task_id, "running", expected_state="confirm"):
        return False
    lang = reader_lang(row)
    requester = {"platform": row["requested_by_platform"],
                 "id": row["requested_by_id"],
                 "name": row["requested_by_name"],
                 "wiki_user": row["requested_by_wiki_user"]}

    def started(language):
        """The line saying the task has begun, in one language."""
        return localized(
            "task_started", language, id=task_id, wiki=row["wiki"],
            mechanics=", ".join(db.task_mechanics(row)),
            pages=db.count_pages(task_id),
            who=access.describe(requester, language),
            how=localized("task_by_schedule", language, id=row["schedule_id"])
            if row["schedule_id"] else "")

    await notify.announce(started(service_lang()))
    if not announce_only:
        await notify.send(row["reply_chat"], started(lang))
        notice = queue_notice(task_id, lang)
        if notice:
            await notify.send(row["reply_chat"], notice)
    scheduler.enqueue(JOB, reason="task {} started".format(task_id))
    return True


async def stop(task_id):
    """Stop a task where it stands. -> whether there was one to stop.

    The pages already done stay done — an edit cannot be taken back by
    stopping — and the row keeps its counters, so a stopped task is a record
    of what it managed rather than a hole.
    """
    import db
    from tasks import notify, runner
    from utils import localized, service_lang

    row = db.get_task(task_id)
    if row is None or row["state"] not in ("pending", "confirm", "running"):
        return False
    db.set_task_state(task_id, "stopped")
    if not runner.is_busy(task_id):
        runner.forget(task_id)
    await notify.announce(localized(
        "task_stopped", service_lang(), id=task_id, wiki=row["wiki"],
        checked=row["checked"], edited=row["edited"]))
    return True


async def tick():
    """One turn of the task queue. Registered with the scheduler as `tasks`.

    Fires what is due, then works through the tasks chunk by chunk until there
    is nothing left or something more important is waiting for the worker.

    The loop is inside the job rather than around it, and that is not an
    optimisation. `scheduler.enqueue` refuses a job that is already running,
    which this one is for as long as it lasts — so a job that tried to put
    itself back in the queue would be refused and the whole task queue would
    advance one chunk a minute, which for nine thousand pages is three hours
    of doing almost nothing. Looping here, a run goes at full speed and stops
    only when it is asked to: `scheduler.waiting_ahead` says a module job is
    due, the loop returns, the news pass goes through, and the clock queues
    this job again at the next minute.
    """
    import scheduler

    made = await asyncio.to_thread(_fire_schedules)
    for task_id in made:
        logger.info("task %s opened by a schedule", task_id)

    while True:
        row = await asyncio.to_thread(_next_task)
        if row is None:
            return

        if row["state"] == "pending":
            await _plan(row)
        elif row["state"] == "running":
            await _chunk(row)
        else:
            return

        if scheduler.waiting_ahead(scheduler.TASK_PRIORITY):
            logger.info("the task queue steps aside: something is due")
            return


def register():
    """Put the task queue on the schedule: every minute, behind the modules."""
    import scheduler

    scheduler.register(JOB, tick, minutes=tuple(range(60)),
                       priority=scheduler.TASK_PRIORITY)
