"""The files a task sends back: the diffs, the list, the failures.

A chat window is not where four thousand diffs belong, so everything long
becomes a file. Three of them, and a task writes only the ones it has
something for:

* ``task-<id>.diff.txt`` — every change the run made or would make, as a
  unified diff per page. There is no cap on how many: the operator asked for
  all of them, and a file is where all of them fit.
* ``task-<id>.report.txt`` — what a REPORT mechanic collected.
* ``task-<id>.errors.txt`` — the pages that would not be written, with the
  reason.

**What may go into these files.** Wiki content and nothing else. No
tracebacks, no file paths, no configuration, no tokens — the files leave the
machine, and a stack trace names directories that are nobody's business.
Errors are written as `type: message`, which is what a person needs to know
what went wrong, and the full traceback stays in the bot's own log where it
belongs. `safe_error` is the one place that decides this, and every mechanic
goes through it.

The files live in src/reports/ and are swept after REPORT_KEEP_DAYS: they are
a copy of what was already sent, not a record.
"""
import logging
import os
import re
import time

logger = logging.getLogger("fd.tasks.report")

REPORTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "reports")

REPORT_KEEP_DAYS = 14

_PATH_RE = re.compile(r"[A-Za-z]:[\\/][^\s'\"]+|/(?:home|usr|etc|root|var)/[^\s'\"]+")

def safe_error(error, lang=None):
    """One exception as a line a person can read and nothing else.

    The type and the message, with anything that looks like a path on this
    machine taken out. The full traceback goes to the log; what leaves the
    machine says what went wrong on the wiki, not where the bot lives.

    An error the bot raised for a person (utils.Explained) is worded in
    `lang` — the reader's language — and without the type in front, which
    would only be noise in a sentence written for them. Its values can still
    carry a library's message, so the paths come out of it all the same.
    """
    from utils import DEFAULT_LANG, Explained

    if isinstance(error, str):
        text = error
    elif isinstance(error, Explained):
        text = error.text(lang or DEFAULT_LANG)
    else:
        text = "{}: {}".format(type(error).__name__, error)
    text = _PATH_RE.sub("<path>", text)
    return " ".join(text.split())[:500]

def _path(task_id, suffix):
    """Where one of a task's files lives."""
    return os.path.join(REPORTS_DIR, "task-{}.{}".format(int(task_id), suffix))

def _ensure_dir():
    """Make the reports directory, once."""
    try:
        os.makedirs(REPORTS_DIR, exist_ok=True)
    except OSError as e:
        logger.warning("could not make the reports directory: %s", e)

class DiffFile:
    """The diff file of one run, written as the run goes.

    Opened lazily: a task that changes nothing leaves no file behind, and a
    dry run over four thousand pages that match nothing does not create an
    empty one to send.
    """

    def __init__(self, task_id, wiki, dry_run=False, lang=None):
        """Remember where to write; open nothing yet. `lang` is the language
        of the person the file goes to, for its heading."""
        self.task_id = int(task_id)
        self.wiki = wiki
        self.dry_run = dry_run
        self.lang = lang
        self.path = _path(task_id, "diff.txt")
        self.count = 0
        if os.path.isfile(self.path):
            with open(self.path, encoding="utf-8") as existing:
                self.count = sum(line.startswith("=== ") for line in existing)
        self._handle = None

    def _open(self):
        """Append after a restart; an earlier chunk's evidence must survive."""
        _ensure_dir()
        exists = os.path.exists(self.path) and os.path.getsize(self.path) > 0
        self._handle = open(self.path, "a", encoding="utf-8")
        if exists:
            return
        from utils import DEFAULT_LANG, localized

        lang = self.lang or DEFAULT_LANG
        self._handle.write("# {}\n# {}\n# {}\n\n".format(
            localized("report_diff_dry" if self.dry_run else "report_diff_done",
                      lang),
            localized("report_diff_wiki", lang, wiki=self.wiki),
            time.strftime("%d.%m.%Y %H:%M")))

    def add(self, title, old, new, summary=None):
        """One page's diff. Nothing is written when the text is unchanged."""
        if old == new:
            return
        from scripts import wikitools as wt

        if self._handle is None:
            self._open()
        self.count += 1
        if summary:
            self._handle.write("=== {} — {}\n".format(title, summary))
        else:
            self._handle.write("=== {}\n".format(title))
        self._handle.write(wt.diff_text(title, old, new))
        self._handle.write("\n\n")
        self._handle.flush()

    def close(self):
        """Finish the file. -> its path, or None when there was nothing."""
        if self._handle is None:
            return None
        self._handle.close()
        self._handle = None
        return self.path

def write_lines(task_id, suffix, heading, lines):
    """One list of lines as a file. -> its path, or None when there are none."""
    if not lines:
        return None
    _ensure_dir()
    path = _path(task_id, suffix)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write("# {}\n# {}\n\n".format(heading, time.strftime("%d.%m.%Y %H:%M")))
            f.write("\n".join(str(line) for line in lines))
            f.write("\n")
    except OSError as e:
        logger.warning("could not write %s: %s", path, e)
        return None
    return path

def files_of(task_id):
    """Every file one task left behind, in the order to send them."""
    found = []
    for suffix in ("report.txt", "diff.txt", "errors.txt"):
        path = _path(task_id, suffix)
        if os.path.exists(path):
            found.append(path)
    return found

def cleanup(keep_days=REPORT_KEEP_DAYS):
    """Delete the report files of runs that are long over.

    They are a copy of what was already sent, not a record — the record is the
    rows in `tasks`. Swept by the same daily job that sweeps the page lists.
    """
    if not os.path.isdir(REPORTS_DIR):
        return 0
    cutoff = time.time() - int(keep_days) * 86400
    removed = 0
    for name in os.listdir(REPORTS_DIR):
        path = os.path.join(REPORTS_DIR, name)
        try:
            if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                os.remove(path)
                removed += 1
        except OSError as e:
            logger.warning("could not remove %s: %s", path, e)
    return removed
