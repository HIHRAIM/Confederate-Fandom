"""The archive module: chosen wiki pages, committed to a GitHub repository.

Once a night — at midnight in Kyiv unless config says otherwise — the bot
reads a list of pages on the Fandom farm (site stylesheets and scripts,
modules, the main pages) and commits every one that changed into a
repository, one file per page, so that a wiki's interface has a history
outside the wiki and survives a vandal or a careless edit.

| Module | Responsibility |
|---|---|
| `fandom.py` | reading the pages and who edited them, anonymously, through api.php |
| `github.py` | the few calls to GitHub's REST API the pass needs |
| `archive.py` | one pass: where each page goes, whether it changed, what the commit says |

**Nothing here is in the repository of the bot.** Which pages, which
repository, whose Fandom account is whose GitHub account — config.MYARCHIVE,
in the untracked config.py — and the token, MYARCHIVE_GITHUB_TOKEN in the
untracked src/.env. Without both the module is off (`enabled`): it registers
no job and nobody running the bot hears of it.

**It waits behind everything** (scheduler.BACKGROUND_PRIORITY): nobody is
waiting for it, so a person's task and the news go first, and the archive
runs when the queue is empty.

It reads with plain HTTP rather than through Pywikibot: the pages are public,
no login is needed, and a job that never touches the library cannot disturb
the sessions and cookie jars of the jobs that do.
"""
import asyncio
import logging
import os

logger = logging.getLogger("fd.modules.myarchive")

CODE = "myarchive"

JOB = "archive"

DEFAULT_AT = "00:00"

DEFAULT_TZ = "Europe/Kyiv"

TOKEN_VARIABLE = "MYARCHIVE_GITHUB_TOKEN"

_reported_missing = set()
"""The pages already reported as missing since the process started: a page
that does not exist is said once, not every night until config is fixed."""


def settings():
    """(config.MYARCHIVE as a dict, the token or ""). Never raises."""
    import config

    cfg = getattr(config, "MYARCHIVE", None)
    if not isinstance(cfg, dict):
        cfg = {}
    return cfg, os.environ.get(TOKEN_VARIABLE, "").strip()


def enabled():
    """Whether this deployment keeps an archive: a repository, pages, a token."""
    cfg, token = settings()
    return bool(token and cfg.get("repo") and cfg.get("pages"))


async def job():
    """One archive pass, in a worker thread, reported only when it matters.

    Silent when nothing changed, like the news: a line every night saying
    "nothing" is a line nobody reads. A pass that committed something, could
    not find a page or failed says so in the service chats.
    """
    from modules.myarchive import archive
    from utils import send_service_event

    cfg, token = settings()
    try:
        result = await asyncio.to_thread(archive.run_pass, cfg, token)
    except Exception as e:
        logger.exception("the archive pass failed")
        try:
            await send_service_event("service_archive_failed", error=e)
        except Exception:
            pass
        return
    missing = [page for page in result["missing"]
               if page not in _reported_missing]
    _reported_missing.update(result["missing"])
    if result["created"] or result["updated"] or missing or result["errors"]:
        await send_service_event(
            "service_archive_done", repo=cfg.get("repo"),
            created=result["created"], updated=result["updated"],
            missing=", ".join(missing) or "—",
            errors="; ".join(result["errors"]) or "—")


def jobs():
    """The jobs of this module, for main.py to register. -> a list of dicts."""
    import scheduler

    if not enabled():
        return []
    cfg, _token = settings()
    return [{"name": JOB, "run": job, "daily_at": cfg.get("at") or DEFAULT_AT,
             "tz": cfg.get("timezone") or DEFAULT_TZ,
             "priority": scheduler.BACKGROUND_PRIORITY, "at_start": False}]
