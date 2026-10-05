"""What the bot's Discord presence says, and the loop that keeps it saying it.

Discord shows one line under the bot's name, and it is the only place a person
can see what the bot is doing without asking it anything. So it answers the
two questions somebody actually has: **what is it working on right now**, and
when the answer is "nothing" — **what happens next, and when**.

Which of the two it is follows the scheduler rather than a guess. A job is
running, and the line names the wiki being edited wherever there is one to
name: a task carries its own, the species walk has one in config, a news pass
has all of them at once and so says what it is doing instead. Nothing is
running, and the line names the soonest thing on the clock — the bot's own
jobs and the repeating runs people set up with `/schedule`, whichever comes
first.

One job is deliberately never offered as "next". The task queue is registered
at every minute of the hour, so it is always the soonest thing there is; left
in, the line would say "next: the task queue, in under a minute" for ever and
never mention the news pass or tonight's walk. It is the queue's driver rather
than a piece of work, and when it is actually *running* something it is named
by the task, not by itself.

The countdown is rounded to whole minutes above a minute, and that is not
cosmetic: the loop sends a new presence only when the text has changed, and a
text carrying seconds would change on every tick for ever, against a Discord
rate limit that exists precisely for that.

The line goes out as a **custom** activity rather than a "watching" or a
"playing" one. Those two put a verb of Discord's own in front of whatever they
are given — "Watching …" — and the line here is already a whole sentence
with a verb of its own. A status that is a noun phrase can afford the prefix;
this one cannot.

**The line is English**, the bot's default language. One line is shown to
everybody who looks at the member list, whatever language each of them chose
with /lang, so it cannot follow anybody's choice; it used to follow
config.SERVICE_LANG, which put the operator's language in front of every
server the bot was in.

Not this module's zone: the connection (`client.py`), and what the jobs are
(`scheduler.py`, `modules/`, `tasks/`).
"""
import asyncio
import logging

import discord

logger = logging.getLogger("fd.discord.status")

INTERVAL = 30
"""How often the line is worked out again, in seconds.

It is *sent* only when it has changed, so this is how quickly the bot notices
it has started working, not how often it talks to Discord."""

NAME_LIMIT = 128
"""How long Discord lets the line be."""

QUEUE_JOB = "tasks"
"""The job that drives the task queue, and the one never offered as "next".

Registered at every minute of the hour (tasks/queue.py: register), so it is
always the nearest thing due and would crowd out everything worth showing."""

def _wait(seconds):
    """A countdown rounded so that it does not change every second.

    Under a minute it stays seconds, because "in a minute" is a lie when it is
    four seconds away. Above, it is whole minutes, which is what keeps the
    presence from being rewritten on every tick of the loop.
    """
    seconds = max(0, int(seconds))
    return seconds - seconds % 60 if seconds >= 60 else seconds

def _running_text(job, lang):
    """The line for the job under way, or None when none is.

    A task names the wiki it is editing, because that is the thing a person
    watching wants to know and the row already holds it. The species walk
    names its wiki from config for the same reason.

    The news pass has a line to itself. It writes to every wiki of
    config.WIKIS at once, so there is no one wiki to point at, and the group
    those wikis form has a name of its own that no key here could work out
    — so the name lives in the `presence_news` string, in the six i18n files,
    which is where every other thing the bot calls something by name lives
    too. A deployment that publishes to a different set of wikis changes it
    there and nowhere else.

    Everything left — the sweep, the backup, and the task queue between two
    tasks — names itself.
    """
    from modules.pokemon import setting
    from utils import job_label, localized, wiki_key

    SPECIES_WIKI = setting("SPECIES_WIKI")

    if not job:
        return None
    if job == QUEUE_JOB:
        import db

        row = db.running_task()
        if row is not None:
            return localized("presence_editing", lang, wiki=row["wiki"])
    if job == "news":
        return localized("presence_news", lang)
    if job == "species":
        return localized("presence_editing", lang, wiki=wiki_key(SPECIES_WIKI))
    return localized("presence_busy", lang, job=job_label(job, lang))

def _next_text(lang):
    """The line for what happens next, or None when nothing is on the clock.

    Both kinds of "next" are weighed against each other in seconds and the
    nearer one wins: the bot's own scheduled jobs, and the repeating runs
    somebody set up. They are different things to a person only in what the
    line then says — one names a job, the other names a wiki.
    """
    import time
    from datetime import datetime

    import db
    import scheduler
    from utils import format_duration, job_label, localized

    now = datetime.now()
    best = None
    for name in scheduler.job_names():
        if name == QUEUE_JOB:
            continue
        moment = scheduler.next_due(name, now)
        if moment is None:
            continue
        seconds = (moment - now).total_seconds()
        if best is None or seconds < best[0]:
            best = (seconds, "presence_next", {"job": job_label(name, lang)})

    row = db.next_schedule()
    if row is not None and row["next_run"]:
        seconds = int(row["next_run"]) - int(time.time())
        if best is None or seconds < best[0]:
            best = (seconds, "presence_next_run", {"wiki": row["wiki"]})

    if best is None:
        return None
    seconds, key, values = best
    return localized(key, lang, when=format_duration(_wait(seconds), lang),
                     **values)

def text(lang):
    """The whole line, in one language. Never raises.

    A status that cannot be worked out must not take the loop down with it:
    the bot would then go on working with a line saying whatever it said an
    hour ago, which is worse than saying nothing in particular.
    """
    import scheduler
    from utils import localized

    try:
        line = (_running_text(scheduler.running(), lang)
                or _next_text(lang)
                or localized("presence_idle", lang))
    except Exception:
        logger.exception("could not work out what the status should say")
        line = localized("presence_idle", lang)
    return str(line)[:NAME_LIMIT]

async def loop():
    """Keep the presence in step with what the bot is doing.

    Started by `client.main` and cancelled with it. Sends only when the line
    has changed — most ticks change nothing, and Discord counts presence
    updates. A send that fails forgets what was shown, so the next tick tries
    again rather than believing a line that never arrived.
    """
    from discord_bot.client import client
    from utils import DEFAULT_LANG

    await client.wait_until_ready()
    shown = None
    while not client.is_closed():
        line = text(DEFAULT_LANG)
        if line != shown:
            try:
                await client.change_presence(
                    activity=discord.CustomActivity(name=line))
                shown = line
            except Exception as e:
                logger.info("could not set the Discord status: %s", e)
                shown = None
        await asyncio.sleep(INTERVAL)
