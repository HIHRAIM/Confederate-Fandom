"""The modules: the standing work the bot was built for.

A module is one wiki's worth of ongoing work, with its own files and its own
jobs, and it is the shape this bot's two long-standing jobs now have:

| Module | Wikis | What it does |
|---|---|---|
| `teleradiopedia` | Телепедия, Радиопедия | keeps three news cards on the main pages in step with a Telegram channel, four times an hour |
| `pokemon` | Покемон Вики | standardises the Russian names of species once a night |
| `myarchive` | any | commits chosen wiki pages to a GitHub repository once a night |

The difference between a module and a mechanic (scripts/) is who asks for it.
A mechanic runs when somebody types a command; a module runs to a schedule
that somebody's readers depend on, which is why module jobs are registered at
MODULE_PRIORITY and go ahead of the task queue when both are due
(scheduler.py). A walk of nine thousand articles never makes the main page an
hour late.

Adding a module: a package here with a `jobs()` returning
``{'name', 'run', 'minutes' | 'daily_at', 'at_start'}`` — and, when it needs
them, `'tz'` for a daily hour on another zone's clock and `'priority'` for
work that should wait behind everything else — and one line in MODULES.
Nothing else knows the list.

**A module that is not configured is not there.** Its `jobs()` returns
nothing, so it registers no job, costs no request and does not appear in the
Discord presence; a person who runs the bot for wiki work alone never hears
of the news, the species or the archive. Each module decides for itself what
"configured" means, and its settings are read with defaults, so a config.py
that does not name them still starts.
"""
import logging

logger = logging.getLogger("fd.modules")

from modules import myarchive, pokemon, teleradiopedia

MODULES = (teleradiopedia, pokemon, myarchive)


def register(scheduler):
    """Put every module's jobs on the schedule. -> the ones to run at start-up.

    Registered at MODULE_PRIORITY, which is what puts them ahead of the task
    queue. The names come back so main.py can queue the ones that should not
    wait for their first mark — a restart must not cost a quarter of an hour
    of stale news.
    """
    at_start = []
    for module in MODULES:
        for job in module.jobs():
            scheduler.register(job["name"], job["run"],
                               minutes=job.get("minutes"),
                               daily_at=job.get("daily_at"),
                               priority=job.get("priority",
                                                scheduler.MODULE_PRIORITY),
                               tz=job.get("tz"))
            logger.info("module %s registered the job %s", module.CODE, job["name"])
            if job.get("at_start"):
                at_start.append(job["name"])
    return at_start
