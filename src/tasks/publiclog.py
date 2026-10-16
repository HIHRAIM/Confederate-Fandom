"""The public log: a line on the wiki for every task the bot starts there.

A wiki's editors see the bot's edits in their recent changes, but not who
set it going or whom to tell when a run goes wrong. So every task that may
edit adds one line to ``User:<bot>/Archive <n>`` on the wiki it runs on:

    * 14:05, 8 October 2026 (UTC): Task <code>replace</code> was started by user Somebody

and the first line of the page says where to report harmful edits — a message
wall and the Discord and Telegram links of config.PUBLIC_LOG. Without that
setting the log is off, like any module that is not configured.

**Which tasks.** Those that can edit: a dry run writes nothing at all, and a
task of report mechanics alone only reads, so neither leaves a line. The line
is written when the task starts running, before its first page, and only
once — a flag in the task's parameters survives a restart in mid-run.

**The page is the bot's own.** It is rebuilt from the bot's own last revision
every time: if somebody edited it after the bot, their edit is undone by the
same edit that adds the new line — undone literally, not with the revert
button — and a page somebody else created before the bot ever wrote to it is
started afresh. ENTRIES_PER_PAGE lines make a page; the next line opens
``Archive <n+1>``. The page the bot continues is the highest-numbered one it
has written to.

Blocking; called from the worker (tasks/runner.py), like every edit.
"""
import logging
import re
import time

logger = logging.getLogger("fd.tasks.publiclog")

PAGE = "Archive"

ENTRIES_PER_PAGE = 500

MONTHS = ("January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December")

FIELDS = ("wall_wiki", "wall_user", "discord", "telegram")

def settings():
    """config.PUBLIC_LOG, or None when it is not set up completely."""
    import config

    cfg = getattr(config, "PUBLIC_LOG", None)
    if not isinstance(cfg, dict) or not all(cfg.get(name) for name in FIELDS):
        return None
    return cfg

def header(cfg):
    """The first line of every page of the log."""
    return ("If a bot makes harmful edits, please contact an administrator as soon "
            "as possible ([[w:c:{wiki}:Message Wall:{user}|Message Wall]] / "
            "[{discord} Discord] / [{telegram} Telegram]). Let us know on which wiki "
            "this happened and when.").format(wiki=cfg["wall_wiki"], user=cfg["wall_user"],
                                              discord=cfg["discord"],
                                              telegram=cfg["telegram"])

def entry(when, codes, user):
    """One line of the log. `when` is a Unix time; the date is written the way
    MediaWiki signs, in English and in UTC."""
    moment = time.gmtime(when)
    return "* {:02d}:{:02d}, {} {} {} (UTC): Task <code>{}</code> was started by user {}".format(
        moment.tm_hour, moment.tm_min, moment.tm_mday, MONTHS[moment.tm_mon - 1],
        moment.tm_year, ", ".join(codes), user)

def wanted(ctx):
    """Whether this run leaves a line: it may edit, and it is not a preview."""
    from tasks.mechanic import REPORT

    if ctx.dry_run:
        return False
    return any(mechanic.kind != REPORT for mechanic in ctx.mechanics)

def _bot_text(page, bot):
    """The text of the bot's last revision of a page, or None when the bot
    never wrote it (or the page does not exist)."""
    if not page.exists():
        return None
    latest = page.latest_revision
    if latest.user == bot:
        return page.text
    for revision in page.revisions(content=False):
        if revision.user == bot:
            return page.getOldVersion(revision.revid)
    return None

def _number(title):
    """The n of ``…/Archive n``, or None."""
    match = re.search(r"/{} (\d+)$".format(PAGE), title)
    return int(match.group(1)) if match else None

def record(ctx, row):
    """Add the line of this task to the log of its wiki. -> the page's title,
    or None when nothing was written. Never raises: a log that cannot be
    written is a note in the report, not a reason to stop the run."""
    import pywikibot
    import wiki

    cfg = settings()
    if cfg is None or not wanted(ctx):
        return None
    try:
        wiki.use_cookies(ctx.wiki)
        site = ctx.site
        bot = site.username() or ""
        numbers = []
        for page in site.allpages(prefix="{}/{} ".format(bot, PAGE), namespace=2):
            number = _number(page.title())
            if number:
                numbers.append(number)
        current, base = 1, None
        for number in sorted(numbers, reverse=True):
            text = _bot_text(pywikibot.Page(site, "User:{}/{} {}".format(bot, PAGE, number)), bot)
            if text is not None:
                current, base = number, text
                break
        lines = [line for line in (base or "").split("\n") if line.startswith("* ")]
        if len(lines) >= ENTRIES_PER_PAGE:
            current, lines = current + 1, []
        user = row["requested_by_wiki_user"] or "a bot administrator"
        codes = [mechanic.code for mechanic in ctx.mechanics]
        lines.append(entry(row["started_at"] or time.time(), codes, user))
        page = pywikibot.Page(site, "User:{}/{} {}".format(bot, PAGE, current))
        page.text = header(cfg) + "\n\n" + "\n".join(lines) + "\n"
        page.save(summary="Task log: {} started by {}".format(", ".join(codes), user),
                  bot=True, minor=False, apply_cosmetic_changes=False)
        return page.title()
    except Exception as e:
        from tasks import report

        logger.warning("could not write the public log of task %s: %s", ctx.task_id, e)
        ctx.note("note_publog_failed", error=report.safe_error(e, ctx.reader))
        return None
