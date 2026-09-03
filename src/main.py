"""Entry point: the two messengers, the modules, and the task queue.

Run it from this directory — the database, the .env file and Pywikibot's own
directory are all opened by relative path: ``python main.py``.

There is very little here on purpose. The standing work belongs to the modules
(modules/telepedia for the news, modules/pokemon for the species names); what
somebody asks the bot to do through a command belongs to the task engine
(tasks/); the clock and the one worker thread belong to scheduler.py. What is
left here is starting all of it and stopping it properly.

Three kinds of job end up on the schedule, and the order between them is the
whole design:

* the **modules**, at MODULE_PRIORITY — the news four times an hour, the
  species walk once a night. They are what somebody's readers see, so they go
  first when anything is due.
* the **task queue**, at TASK_PRIORITY — one chunk of one task per turn, then
  back in the queue. A walk of nine thousand articles is a hundred short jobs,
  and a news pass slips in between two of them.
* the **nightly sweep**, which throws away the page lists and report files of
  runs that are long over.

Import order at the top matters: `db.init()` runs before the Telegram package
is imported further, so the schema exists before anything queries it.
"""
import asyncio
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("fd.main")

import db
import modules
import scheduler
from discord_bot import client as dc_client, main as dc_main
from tasks import queue as task_queue
from telegram_bot import bot, main as tg_main
from utils import send_service_event

db.init()

SWEEP_AT = "04:00"


async def sweep_job():
    """Throw away what a finished run no longer needs.

    The rows in `tasks` stay — they are the record of who asked the bot to do
    what — but a finished walk of nine thousand pages has no reason to keep
    nine thousand rows of 'done' beside it, and the diff files were already
    sent to whoever asked for them.
    """
    from tasks import report

    try:
        db.cleanup_tasks()
        removed = report.cleanup()
        logger.info("nightly sweep done, %s report files removed", removed)
    except Exception:
        logger.exception("the nightly sweep failed")


def register_jobs():
    """Put the modules, the task queue and the sweep on the schedule.

    The module jobs marked `at_start` are queued straight away, so a restart
    is not a quarter of an hour of stale news; the nightly ones wait for their
    hour.
    """
    at_start = modules.register(scheduler)
    task_queue.register()
    scheduler.register("sweep", sweep_job, daily_at=SWEEP_AT,
                       priority=scheduler.TASK_PRIORITY)
    for name in at_start:
        scheduler.enqueue(name, reason="start-up")


async def main():
    """Start the two messengers and the scheduler, then wait for whichever of
    them ends first and take the others down with it.

    Waiting for *both* is what a `gather` would do, and it is wrong here.
    aiogram installs its own SIGINT/SIGTERM handler and answers the signal by
    stopping the polling neatly — at which point the scheduler is still asleep
    until the next quarter of an hour, holding the process open. A service
    manager waiting for it to exit runs out of patience and sends SIGKILL, and
    an orderly stop becomes a killing every time. Ending on the first task to
    finish, and cancelling the rest, is what makes the bot close when it is
    asked to.

    The service chats are told once the bot has had five seconds to connect,
    and told again on the way out however it ends.
    """
    register_jobs()
    tasks = [
        asyncio.create_task(tg_main(), name="telegram"),
        asyncio.create_task(dc_main(), name="discord"),
        asyncio.create_task(scheduler.run(), name="scheduler"),
    ]

    await asyncio.sleep(5)
    await send_service_event("service_started")

    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            if task.cancelled():
                continue
            error = task.exception()
            if error:
                logger.error("the %s task stopped: %s", task.get_name(), error)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
    finally:
        try:
            await send_service_event("service_stopped")
        except Exception:
            logger.warning("could not report the shutdown to the service chats")
        finally:
            for close in (bot.session.close(), dc_client.close()):
                try:
                    await close
                except Exception:
                    pass


if __name__ == "__main__":
    asyncio.run(main())
