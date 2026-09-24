"""Running a task: the plan, the chunks, and the report at the end.

Everything here is **blocking** and runs in the one worker thread the
scheduler owns. Pywikibot is synchronous and the bot has exactly one thread
for it; the loop reaches this module through `asyncio.to_thread` and never
otherwise.

A task goes through four moments:

1. **plan** — open the wiki, put the caller and the bot through every check
   (tasks/access.py), let each mechanic prepare itself, and settle the page
   list. Nothing is written. This is where a bad regular expression, a missing
   right or a wiki the bot has no status on stops the task, and where the
   person is told how many pages they are about to change.
2. **confirm** — a person says yes. Not a state the code does anything in; it
   is where the task waits.
3. **chunks** — the pages are walked a chunk at a time. A chunk ends after
   CHUNK_PAGES pages, after CHUNK_SECONDS, or as soon as something more
   important is waiting for the worker (scheduler.waiting_ahead) — so a walk
   of nine thousand articles never holds the quarter-hourly news pass for more
   than about a minute.
4. **finish** — the standalone mechanics do their work, the files are written,
   the counters are stored.

**One edit per page.** The TEXT mechanics compose: the page is read once, its
text goes through each of them in turn, and it is saved once with a summary
built from what all of them actually did. Four mechanics over one page is one
line in the history, not four.

The context of a running task is kept in memory between chunks, because
`prepare` is not free — compiling six hundred rules and running their
self-test every chunk would cost more than the walking. It is rebuilt from the
row when it is not there, which is what makes a task survive a restart.
"""
import logging
import time

logger = logging.getLogger("fd.tasks.runner")

CHUNK_PAGES = 50

CHUNK_SECONDS = 60

PREVIEW_TITLES = 20

_contexts = {}

_busy = set()


def is_busy(task_id):
    """Whether the worker owns this context; /stop must not close it then."""
    return task_id in _busy


class Context:
    """Everything one running task carries, handed to every mechanic.

    `state` is where each mechanic keeps whatever `prepare` gave it, under its
    own code. `notes` are the lines the run wants a person to read — they go
    into the report and, when there are few, into the message.
    """

    __slots__ = ("task_id", "site", "wiki", "family", "lang", "params",
                 "summary", "dry_run", "mechanics", "state", "notes",
                 "requester", "diffs", "report_lines")

    def __init__(self, task_id, site, wiki, family, lang, params, summary,
                 dry_run, mechanics, requester):
        """Assemble the context. Nothing here touches the wiki."""
        self.task_id = task_id
        self.site = site
        self.wiki = wiki
        self.family = family
        self.lang = lang
        self.params = params
        self.summary = summary
        self.dry_run = dry_run
        self.mechanics = mechanics
        self.requester = requester
        self.state = {}
        self.notes = []
        self.diffs = None
        self.report_lines = []

    def note(self, text):
        """Say something a person should read at the end of the run."""
        line = str(text)
        if line not in self.notes:
            self.notes.append(line)
        logger.info("task %s: %s", self.task_id, line)


def _target(row):
    """The (family, lang) of a task's wiki, from its stored key."""
    key = str(row["wiki"])
    family, _, lang = key.partition(":")
    return family, lang


def _build_context(row):
    """Open the wiki and assemble a context for one task. -> Context.

    Blocking: it logs in. Called from the worker thread only.
    """
    import db
    import wiki
    from tasks import registry

    family, lang = _target(row)
    site = wiki.get_site(family, lang)
    params = db.task_params(row)
    mechanics, unknown = registry.find_all(db.task_mechanics(row))
    if unknown:
        raise ValueError("неизвестные механики: {}".format(", ".join(unknown)))
    if not mechanics:
        raise ValueError("в задаче не осталось ни одной механики")

    requester = {"platform": row["requested_by_platform"],
                 "id": row["requested_by_id"],
                 "name": row["requested_by_name"],
                 "wiki_user": row["requested_by_wiki_user"],
                 "role": None}
    return Context(
        task_id=row["id"], site=site, wiki=str(row["wiki"]), family=family,
        lang=lang, params=params, summary=(params.get("summary") or "").strip(),
        dry_run=bool(row["dry_run"]), mechanics=mechanics, requester=requester)


def context_for(row):
    """Reuse preparation, but always read the current preview flag from SQL.

    /go may enable dry mode after planning has cached a live context. Keeping
    that old flag would turn an explicitly requested preview into real edits.
    Page reports and notes are checkpointed with progress for process restarts.
    """
    import db

    ctx = _contexts.get(row["id"])
    if ctx is None:
        ctx = _build_context(row)
        _prepare(ctx)
        saved = db.task_report(row).get("checkpoint") or {}
        ctx.report_lines = list(saved.get("report_lines") or [])
        for note in saved.get("notes") or []:
            ctx.note(note)
        _contexts[row["id"]] = ctx
    ctx.dry_run = bool(row["dry_run"])
    return ctx


def forget(task_id):
    """Drop a finished task's context so its rules stop taking up room."""
    ctx = _contexts.pop(task_id, None)
    if ctx is not None and ctx.diffs is not None:
        ctx.diffs.close()


def _prepare(ctx):
    """Let every mechanic get itself ready. Raises on anything unusable."""
    for mechanic in ctx.mechanics:
        ctx.state[mechanic.code] = mechanic.prepare(ctx)


def plan(task_id):
    """Retain the preparing context while the messenger may stop this task."""
    _busy.add(task_id)
    try:
        return _plan(task_id)
    finally:
        _busy.discard(task_id)


def _plan(task_id):
    """Check everything and settle the page list. -> a mapping for the person.

    Nothing is written to the wiki here, and that is the whole point: this is
    the moment a person is shown how many pages they are about to change, and
    the moment a task that cannot work says so.
    """
    import db
    from tasks import access, pagesets, registry

    row = db.get_task(task_id)
    if row is None:
        raise ValueError("задача не найдена")
    if row["state"] != "pending":
        return {}

    ctx = _build_context(row)
    requester = ctx.requester
    if requester.get("id") is not None:
        resolved = access.caller(requester["platform"], requester["id"],
                                 requester.get("name"))
        if resolved:
            requester.update(resolved)

    access.check_all(ctx.site, ctx.wiki, ctx.mechanics, requester)
    _prepare(ctx)
    _contexts[task_id] = ctx

    pages = 0
    sample = []
    if registry.needs_pages(ctx.mechanics):
        titles = pagesets.collect(
            ctx.site, ctx.params,
            redirects=registry.redirects_wanted(ctx.mechanics, ctx.params))
        pages = db.set_pages(task_id, titles)
        sample = titles[:PREVIEW_TITLES]
        if not pages:
            ctx.note("по этому источнику не нашлось ни одной страницы")

    if not db.set_task_state(task_id, "confirm", expected_state="pending"):
        forget(task_id)
        return {}
    return {"pages": pages, "sample": sample, "notes": list(ctx.notes),
            "destructive": registry.is_destructive(ctx.mechanics),
            "dry_run": ctx.dry_run,
            "mechanics": [m.code for m in ctx.mechanics],
            "wiki": ctx.wiki}


def _compose_summary(ctx, per_mechanic):
    """The edit summary of one page, from what actually happened to it.

    A summary the person gave wins outright — they asked for those words. With
    none, the mechanics say what they did and the parts are joined, which is
    how the spelling mechanics end up writing «правописание, пунктуация и
    косметические изменения» and nothing they did not do.
    """
    if ctx.summary:
        return ctx.summary
    parts = [part for part in per_mechanic if part]
    if not parts:
        return "правки бота"
    if len(parts) == 1:
        return parts[0]
    return "{} и {}".format(", ".join(parts[:-1]), parts[-1])


def _walk_page(ctx, row):
    """One page through every mechanic. -> (state, note).

    The TEXT mechanics come first and share one edit; the ACTION ones follow,
    because deleting a page one has just edited is wasteful and moving it
    changes what the next mechanic would be editing.
    """
    import pywikibot
    import wiki
    from tasks import registry, report
    from tasks.mechanic import ACTION, REPORT, TEXT

    wiki.use_cookies(ctx.wiki)
    title = row["title"]
    page = pywikibot.Page(ctx.site, title)

    notes = []
    edited = False

    text_mechanics = registry.of_kind(ctx.mechanics, TEXT)
    if text_mechanics:
        try:
            original = page.text
        except Exception as e:
            return "fail", report.safe_error(e)
        text = original
        parts = []
        for mechanic in text_mechanics:
            before = text
            try:
                text, labels = mechanic.apply(ctx, page, text)
            except Exception as e:
                logger.exception("mechanic %s failed on %s", mechanic.code, title)
                return "fail", "{}: {}".format(mechanic.code, report.safe_error(e))
            if labels and text != before:
                parts.append(mechanic.summary_part(ctx, labels))
        if text.rstrip() != original.rstrip():
            summary = _compose_summary(ctx, parts)
            if ctx.diffs is not None:
                ctx.diffs.add(title, original, text, summary)
            if not ctx.dry_run:
                try:
                    page.text = text
                    page.save(summary=summary, bot=True, minor=False,
                              apply_cosmetic_changes=False)
                    edited = True
                except Exception as e:
                    logger.warning("could not save %s: %s", title, e)
                    return "fail", report.safe_error(e)
            else:
                edited = True

    for mechanic in registry.of_kind(ctx.mechanics, ACTION):
        try:
            state, note = mechanic.act(ctx, page)
        except Exception as e:
            logger.exception("mechanic %s failed on %s", mechanic.code, title)
            return "fail", "{}: {}".format(mechanic.code, report.safe_error(e))
        if note:
            notes.append(note)
        if state == "fail":
            return "fail", "; ".join(notes) or None
        if state == "done":
            edited = True

    for mechanic in registry.of_kind(ctx.mechanics, REPORT):
        if mechanic.standalone:
            continue
        try:
            lines = mechanic.collect(ctx, page)
        except Exception as e:
            logger.warning("report mechanic %s failed on %s: %s",
                           mechanic.code, title, e)
            lines = ["{}\tошибка: {}".format(title, report.safe_error(e))]
        if lines:
            ctx.report_lines += list(lines)

    return ("done" if edited else "skip"), ("; ".join(notes) or None)


def run_chunk(task_id):
    """Keep ownership of the context until the worker finishes its chunk."""
    _busy.add(task_id)
    try:
        return _run_chunk(task_id)
    finally:
        _busy.discard(task_id)


def _run_chunk(task_id):
    """Walk one chunk of a task's pages. -> True while there is more to do.

    The chunk ends on whichever comes first: CHUNK_PAGES pages, CHUNK_SECONDS
    of wall clock, or something more important arriving in the queue. Handing
    the worker back is what keeps the news on time.
    """
    import db
    import scheduler
    from tasks import report

    row = db.get_task(task_id)
    if row is None or row["state"] != "running":
        return False

    ctx = context_for(row)
    if ctx.diffs is None:
        ctx.diffs = report.DiffFile(task_id, ctx.wiki, ctx.dry_run)

    started = time.monotonic()
    cursor = row["cursor"]
    checked = 0

    while True:
        fresh = db.get_task(task_id)
        if fresh is None or fresh["state"] != "running":
            return False
        ctx.dry_run = bool(fresh["dry_run"])
        pages = db.next_pages(task_id, cursor, 1)
        if not pages:
            break
        page_row = pages[0]
        state, note = _walk_page(ctx, page_row)
        cursor = page_row["seq"]
        checked += 1
        db.record_task_page(task_id, cursor, state, note, {
            "checkpoint": {"notes": list(ctx.notes),
                           "report_lines": list(ctx.report_lines)}})

        if checked >= CHUNK_PAGES:
            break
        if time.monotonic() - started >= CHUNK_SECONDS:
            break
        if scheduler.waiting_ahead(scheduler.TASK_PRIORITY):
            logger.info("task %s yields the worker: something is due", task_id)
            break

    return bool(db.next_pages(task_id, cursor, 1))


def finish(task_id):
    """Close a task while retaining exclusive ownership of its context."""
    _busy.add(task_id)
    try:
        return _finish(task_id)
    finally:
        _busy.discard(task_id)


def _finish(task_id):
    """Close a task: the standalone mechanics, the files, the counters.

    -> a mapping the caller reports: the counters, the notes and the files.
    """
    import db
    from tasks import report

    row = db.get_task(task_id)
    if row is None or row["state"] != "running":
        return {}
    ctx = context_for(row)

    for mechanic in ctx.mechanics:
        if db.get_task(task_id)["state"] != "running":
            return {}
        try:
            lines = mechanic.finish(ctx)
        except Exception as e:
            logger.exception("mechanic %s failed to finish", mechanic.code)
            ctx.note("{}: {}".format(mechanic.code, report.safe_error(e)))
            continue
        if lines:
            ctx.report_lines += list(lines)

    if ctx.diffs is not None:
        ctx.diffs.close()
    report.write_lines(task_id, "report.txt",
                       "Отчёт задачи {} — {}".format(task_id, ctx.wiki),
                       ctx.report_lines)
    failures = db.failed_pages(task_id)
    report.write_lines(
        task_id, "errors.txt",
        "Не удалось обработать — задача {} — {}".format(task_id, ctx.wiki),
        ["{}\t{}".format(entry["title"], entry["note"] or "") for entry in failures])

    row = db.get_task(task_id)
    if row["state"] != "running":
        return {}
    result = {
        "wiki": ctx.wiki,
        "checked": row["checked"],
        "edited": row["edited"],
        "failed": row["failed"],
        "pages": db.count_pages(task_id),
        "notes": list(ctx.notes),
        "diffs": ctx.diffs.count if ctx.diffs is not None else 0,
        "dry_run": ctx.dry_run,
        "files": report.files_of(task_id),
    }
    db.set_report(task_id, {k: v for k, v in result.items() if k != "files"})
    if not db.set_task_state(task_id, "done", expected_state="running"):
        """A stop can arrive while the final report is being persisted."""
        forget(task_id)
        return {}
    forget(task_id)
    return result
