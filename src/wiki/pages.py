"""Writing the news to one wiki: the three files, then the three templates.

One entry point, `apply_plan`, and it is blocking from top to bottom —
Pywikibot has no asynchronous half. publisher.py hands it a finished plan, one
wiki at a time, and runs it in a worker thread; nothing here reads the
database, asks Telegram anything or decides what a news is.

Three rules shape the order of what it does:

* **One wiki at a time.** The plan names the wiki it belongs to, and the
  wikis of config.WIKIS are walked one after another, so a wiki that is down
  costs its own news and nobody else's.

* **The picture goes up before the template that shows it.** A template
  pointing at a file that has not arrived yet is a red link on the main page,
  even if only for a second.
* **A slot is independent of the other two.** A file that will not upload
  fails its own slot and leaves the other two alone; the caller records only
  the slots that went through, so the next pass retries exactly what did not.
"""
import logging
import os
import tempfile

from wiki.site import get_site

logger = logging.getLogger("tprp.wiki")

UPLOAD_IGNORED_WARNINGS = (
    "exists",
    "exists-normalized",
    "duplicate",
    "duplicate-version",
    "duplicate-archive",
    "was-deleted",
    "no-change",
)

def upload_file(site, file_name, data, summary):
    """Put the bytes of one picture into one file page, replacing what was
    there.

    An upload follows the same rule as an edit: it is marked as a bot action
    on a wiki where the account holds the `bot` right, and appears in Recent
    changes like anyone else's where it does not.

    Pywikibot uploads from a path, so the bytes are written to a temporary
    file that is removed whatever happens. The warnings that are ignored are
    the ones that describe exactly what the bot means to do — the file exists,
    the same picture is already on the wiki, the name was deleted once — while
    anything else is left to fail, because an unexpected warning is the wiki
    saying that the upload was not what was meant."""
    import pywikibot

    handle, path = tempfile.mkstemp(suffix="-" + file_name)
    os.close(handle)
    try:
        with open(path, "wb") as f:
            f.write(data)
        file_page = pywikibot.FilePage(site, "File:" + file_name)
        return bool(site.upload(
            file_page,
            source_filename=path,
            comment=summary,
            ignore_warnings=UPLOAD_IGNORED_WARNINGS,
            report_success=False,
        ))
    finally:
        try:
            os.remove(path)
        except OSError:
            pass

def edit_template(site, title, wikitext, summary):
    """Make one template page say exactly `wikitext`; True when that was a
    change.

    The page is compared before it is written, so a pass that finds the wiki
    already up to date leaves no edit behind — the news change three times a
    day at most and the history should say so. Cosmetic changes are switched
    off: the bot's business is the news, not reformatting somebody's page.

    The edit asks to be marked as a bot edit. Whether it *is* marked is the
    wiki's decision and not the code's: MediaWiki honours the flag only for an
    account that holds the `bot` right there, which takes both a local group
    (a bureaucrat's `Special:UserRights`) and the "High-volume editing" grant
    on the BotPassword. Without them the edit goes through unflagged and shows
    up in Recent changes like anyone else's — see README: The wiki login."""
    import pywikibot

    page = pywikibot.Page(site, title)
    current = page.text if page.exists() else ""
    if current.strip() == wikitext.strip():
        return False
    page.text = wikitext
    page.save(summary=summary, minor=False, bot=True, apply_cosmetic_changes=False)
    return True

def apply_plan(family, lang, plan):
    """Carry out one publishing pass on one wiki; one result dict per slot.

    Each entry of `plan` is a slot to write: its template title, its file
    name, the wikitext the template should end up with, the picture to upload
    (or None to leave the file alone) and the two edit summaries. Each result
    carries what actually happened — whether the file was uploaded, whether
    the template was edited, and the error if the slot failed.

    The caller runs this once per wiki of config.WIKIS, which is what keeps a
    wiki that is down or refusing an edit from costing the others their news."""
    site = get_site(family, lang)
    results = []
    for entry in plan:
        result = {"slot": entry["slot"], "uploaded": False, "edited": False,
                  "ok": False, "error": None}
        try:
            if entry.get("image"):
                result["uploaded"] = upload_file(
                    site, entry["file"], entry["image"], entry["upload_summary"])
            result["edited"] = edit_template(
                site, entry["template"], entry["wikitext"], entry["edit_summary"])
            result["ok"] = True
        except Exception as e:
            result["error"] = "{}: {}".format(type(e).__name__, e)
            logger.warning("slot %s failed: %s", entry["slot"], result["error"])
        results.append(result)
    return results
