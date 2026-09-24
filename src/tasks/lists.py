"""What the list commands show, built once for both messengers.

`/tasks`, `/jobs` and `/schedule` print the same three lists on Discord and on
Telegram, and they used to print them from two identical copies of the same
loop — one in each half's `commands/tasks.py`. A key renamed on one side and
not the other was a difference nobody would notice until somebody ran the
command on the quieter messenger.

So the content lives here and the markup does not. Each builder returns
``(title, lines)``: the title goes at the top of the embed, or in bold above
the message, and the lines are the body, already localized and already in the
order they are meant to be read.

Markup arrives as `fmt`, an object with three functions on it — `code`, `bold`
and `esc`. Each half's `pages` module *is* that object, which is why it is
passed as one: `fmt.code("replace")` becomes `` `replace` `` on Discord and
``<code>replace</code>`` on Telegram, and nothing here has to know either
spelling. `esc` is not decoration: Telegram is sent HTML, so every value that
came from a wiki, a person or an exception has to be escaped, and routing all
three through `fmt` is what makes "did I escape this one?" answerable by
looking at a single line.

Not this module's zone: paging and buttons (`discord_bot/pages.py`,
`telegram_bot/pages.py`), and the plain-text catalogue the dialog asks its
first question with (`tasks/dialog.py: mechanics_list`).
"""


class _Plain:
    """Markup for a place that has none, such as a dialog's own message."""

    code = staticmethod(str)
    bold = staticmethod(str)
    esc = staticmethod(str)


PLAIN = _Plain()
"""The `fmt` to pass when the answer is plain text and must stay plain."""

RECENT_TASKS = 5
"""How many finished runs `/jobs` shows under the ones still going.

Here rather than in each half's commands module, where it used to be twice:
how much history a person is shown is part of what the list *says*, and two
copies of it is how the two messengers start answering differently."""


def catalogue(lang, fmt=PLAIN):
    """The mechanics, numbered. -> (title, lines)

    One line each, in the order `registry.numbered()` gives — which is the
    order the numbers *mean*, so it may not be sorted or grouped here. The
    number stays in front because `/run 1 4` takes it; then the name a person
    knows the script by, then its code in brackets, then what it does.
    """
    from tasks import dialog
    from utils import localized

    lines = []
    for entry in dialog.mechanics_entries(lang):
        mark = (" " + fmt.esc(localized("tasks_destructive_mark", lang))
                if entry["destructive"] else "")
        lines.append("{}. {} [{}] — {}{}".format(
            entry["number"],
            fmt.bold(entry["name"]),
            fmt.code(entry["code"]),
            fmt.esc(entry["description"]),
            mark))
    return localized("tasks_title", lang), lines


def jobs(lang, fmt=PLAIN, recent=RECENT_TASKS):
    """What is running, what is queued and how the last runs ended.

    The first line is the scheduler's own state rather than a task's, which is
    why it is a line of the body and not the title: it changes every minute
    and a title that changed every minute would be a title nobody trusted.
    """
    import db
    import scheduler
    from utils import job_label, localized

    waiting = [job_label(name, lang) for name in scheduler.waiting()]
    lines = [localized(
        "jobs_header", lang,
        running=fmt.code(job_label(scheduler.running(), lang)),
        waiting=fmt.esc(", ".join(waiting) or "—"))]
    active = db.active_tasks()
    if active:
        lines.append(localized("jobs_active", lang))
        for row in active:
            lines.append(localized(
                "jobs_task", lang, id=row["id"], wiki=fmt.code(row["wiki"]),
                state=fmt.esc(row["state"]),
                mechanics=fmt.code(", ".join(db.task_mechanics(row))),
                checked=row["checked"], total=db.count_pages(row["id"]),
                edited=row["edited"], failed=row["failed"]))
    for row in db.recent_tasks(recent):
        if row["state"] in ("pending", "confirm", "running"):
            continue
        lines.append(localized(
            "jobs_finished", lang, id=row["id"], wiki=fmt.code(row["wiki"]),
            state=fmt.esc(row["state"]), edited=row["edited"],
            failed=row["failed"], error=fmt.esc(row["error"] or "")))
    return localized("jobs_title", lang), lines


def schedules(lang, fmt=PLAIN):
    """The repeating runs. -> (title, lines); the lines are empty when none.

    An empty list is the caller's to report, not this module's: `/schedule`
    has a sentence of its own for "there are none", and a page with nothing on
    it would be a worse way of saying it.
    """
    import db
    from tasks import dialog
    from utils import localized

    lines = []
    for row in db.list_schedules():
        lines.append(localized(
            "schedule_line", lang, id=row["id"], wiki=fmt.code(row["wiki"]),
            mechanics=fmt.code(", ".join(db.schedule_mechanics(row))),
            when=fmt.esc(dialog.describe_schedule(row, lang)),
            state=fmt.esc(localized("schedule_state_on" if row["enabled"]
                                    else "schedule_state_off", lang))))
    return localized("schedule_header", lang), lines


def invite_until(added_at):
    """The day an invitation made at `added_at` lapses, as people read it."""
    import time

    import db

    return time.strftime("%d.%m.%Y", time.localtime(
        int(added_at or 0) + db.INVITE_DAYS * 86400))


def wiki_admins(lang, fmt=PLAIN):
    """Who is appointed, then who is invited. -> (title, lines); the lines are
    empty when there is nobody, which the caller reports in its own words.

    The invitations are Telegram's (telegram_bot/people.py) and are shown on
    both messengers, like everything else here: whoever asks on Discord is
    looking at the same list of people."""
    import db
    from utils import localized

    lines = []
    for row in db.list_wiki_admins():
        lines.append(localized(
            "wikiadmin_line", lang, platform=fmt.esc(row["platform"]),
            name=fmt.esc(row["display_name"] or row["user_id"]),
            user_id=row["user_id"], wiki_user=fmt.esc(row["wiki_user"])))
    for row in db.list_wiki_admin_invites():
        lines.append(localized(
            "wikiadmin_invite_line", lang, username=fmt.esc(row["username"]),
            wiki_user=fmt.esc(row["wiki_user"]),
            until=invite_until(row["added_at"])))
    return localized("wikiadmin_header", lang), lines


TELEGRAM = "telegram"

DISCORD = "discord"

BOTH = (TELEGRAM, DISCORD)

HELP_SECTIONS = (
    ("help_wiki", (
        ("cmd_tasks", BOTH),
        ("cmd_run", BOTH),
        ("cmd_go", BOTH),
        ("cmd_jobs", BOTH),
        ("cmd_stop", BOTH),
        ("cmd_schedule", BOTH),
    )),
    ("help_news", (
        ("cmd_status", BOTH),
        ("cmd_update", (TELEGRAM,)),
        ("cmd_backfill", (TELEGRAM,)),
    )),
    ("help_access", (
        ("cmd_wikiadmin", BOTH),
        ("cmd_remwikiadmin", BOTH),
        ("cmd_backup", BOTH),
    )),
)
"""Every command `/help` lists: its section, its i18n key, and where it exists.

The list is written by hand, and that is the trap every project of this shape
carries: a command added without a line here keeps working while staying
invisible. What is *not* carried any more is the older trap — one block of
prose per language, describing the Telegram spelling to both messengers. It
told a person on Discord to run `/go 2 dry`, which cannot be typed there; they
used the option picker instead, never touched `dry` because nothing mentioned
it, and got a real run where they had asked for a preview.

So the platform is a column. A command that does not exist on a messenger is
not listed there (`/update` and `/backfill` are Telegram's), and a command
spelled differently carries a `_tg` and a `_dc` key beside the shared one."""


def _command_line(key, platform, lang):
    """One command's line, in that messenger's spelling.

    `cmd_go_tg` and `cmd_go_dc` where the two differ, `cmd_jobs` where they do
    not, and the fallback is a question about the key rather than a second
    table of which commands have variants — one place to add a spelling, and
    no list to keep in step with it.

    Asked through `has_translation` and not by comparing what `localized`
    returns: that function warns about a missing key, which is right for a
    reply that fell back to its own name and wrong here, where the miss is the
    ordinary case and would put a line in the log for every command on every
    `/help`."""
    from utils import has_translation, localized

    specific = "{}_{}".format(key, "dc" if platform == DISCORD else "tg")
    return localized(specific if has_translation(specific) else key, lang)


def help_text(lang, fmt=PLAIN, platform=TELEGRAM):
    """The `/help` answer for one messenger. -> (title, lines)

    Built from HELP_SECTIONS rather than from a block of prose, so that the
    two halves cannot drift and neither can list a command the other one has.

    Lines are escaped whole. These are the project's own strings that carry angle
    brackets (`/go <номер>`), so a messenger sent HTML would swallow half of
    them. The title stays plain like every other list title: each messenger
    applies its own title formatting, so escaping it here would show literal
    entities on Telegram and unnecessary markdown escapes on Discord."""
    from utils import localized

    lines = []
    for title_key, commands in HELP_SECTIONS:
        rows = [_command_line(key, platform, lang)
                for key, platforms in commands if platform in platforms]
        if not rows:
            continue
        if lines:
            lines.append("")
        lines.append(fmt.bold(localized(title_key, lang)))
        lines.extend(fmt.esc(row) for row in rows)
    footer = localized("help_footer", lang)
    if footer and footer != "help_footer":
        lines.append("")
        lines.append(fmt.esc(footer))
    return localized("help_intro", lang), lines
