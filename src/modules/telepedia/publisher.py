"""One publishing pass, from the stored posts to every wiki and back.

This is the module that owns the sequence: read the posts, decide what the
three news are (news.py), fetch the pictures that are not already up there,
hand a finished plan to the wiki half (wiki/pages.py) once per wiki in a worker
thread, and record what went through. Both callers — the quarter-hour loop in
main.py and the /update command — come through `run_pass`, which is why it
lives here and not in either of them: a module imported by `python main.py` and
imported again by a command would run as two copies of itself.

The same three news go to every wiki of config.WIKIS, and each wiki is written
to on its own: it has its own template titles and file names, its own row per
slot in the database, and its own turn in the worker thread. A wiki that is
down, or that refuses an edit, costs its own news and nobody else's.

Three economies are worth knowing about, because they are what keeps the wikis'
history and the Bot API quiet:

* **A picture is downloaded once per pass, however many wikis want it.** Every
  slot of every wiki remembers the Telegram file_unique_id of what it holds; a
  picture no wiki is missing is never fetched at all. `force` (from ``/update
  force``) is what overrides that, for a file that was changed on a wiki behind
  the bot's back. Once per pass, but not once only: a download that fails is
  tried again a few seconds later (`PICTURE_ATTEMPTS`), because the answer that
  costs a card its picture is usually the CDN having a bad second.
* **A file is uploaded only to the wikis that are missing it.** Two wikis are
  rarely out of step, but when one of them failed last time it is the only one
  that pays for it.
* **A template is edited only when it would change.** wiki/pages.py compares
  before it saves, so a pass that finds everything in place leaves no trace.

A pass is never run twice at once — a lock sees to that, so the loop and a
hand-typed /update cannot upload the same file over each other.
"""
import asyncio
import logging
import time

import db
import wiki
from modules.telepedia import news, preview
from config import (
    EDIT_SUMMARY, NEWS_CSS_PREFIX, NEWS_FILES, NEWS_TEMPLATES, UPLOAD_SUMMARY, WIKIS,
)
from telegram_bot import download_photo, source_chat_id, source_username
from utils import wiki_key

logger = logging.getLogger("fd.publisher")

PICTURE_ATTEMPTS = 3
"""How many times one picture is asked for before the card goes up without it.

Telegram's CDN answers an occasional `HTTP 500` for a file that is perfectly
there, and one such answer used to cost that card its picture until the news
itself changed. Three attempts is the shape of the failure rather than a round
number: what is being covered is a single bad second, and a file that is really
gone (an expired file_id, a post that was deleted) says so just as quickly three
times as once."""

PICTURE_RETRY_PAUSE = 3
"""Seconds between two attempts at the same picture.

Long enough to be a different second at the other end, short enough that three
slots failing together cost a pass twelve seconds out of the fifteen minutes it
has."""

_pass_lock = asyncio.Lock()

_pass_state = {"running": False}

def is_running():
    """Whether a pass is under way. /update asks before starting one, so that
    the answer is 'a pass is already running' rather than a silent wait."""
    return _pass_state["running"]

def wiki_templates(wiki_config):
    """The template titles one wiki uses: its own when it names them, the
    shared config.NEWS_TEMPLATES otherwise."""
    return tuple(wiki_config.get("templates") or NEWS_TEMPLATES)

def wiki_files(wiki_config):
    """The file names one wiki uses: its own when it names them, the shared
    config.NEWS_FILES otherwise."""
    return tuple(wiki_config.get("files") or NEWS_FILES)

def wiki_css_prefix(wiki_config):
    """The stem of the card's CSS classes on one wiki: its own when it names
    one, the shared config.NEWS_CSS_PREFIX otherwise. It is what makes the same
    news `tp-news__item` on one wiki and `rp-news__item` on another."""
    return wiki_config.get("css_prefix") or NEWS_CSS_PREFIX

def _slot_count():
    """How many news there is room for: the shortest of every wiki's two
    tuples, so a half-finished config cannot walk off the end of one of them."""
    lengths = []
    for wiki_config in WIKIS:
        lengths.append(len(wiki_templates(wiki_config)))
        lengths.append(len(wiki_files(wiki_config)))
    return min(lengths) if lengths else 0

def _holds_picture(key, slot, item):
    """Whether that wiki's slot already holds this news' picture."""
    stored = db.get_slot(key, slot)
    held = (stored["image_key"] if stored else "") or ""
    return bool(item["photo_unique_id"]) and held == item["photo_unique_id"]

async def _download(reference):
    """The bytes of one picture, wherever it came from, or None.

    A post the bot saw itself carries a Telegram file_id; one recovered from
    the channel's public preview (backfill.py) carries the URL the preview
    named it by, because the preview has no file ids. The "http" in front is
    what tells the two apart.

    Asked for more than once, and that is the whole of the difference between a
    card with a picture and a card without. Both sources answer a failure the
    same way — with None, having logged what went wrong — and the one seen
    in production was Telegram's own CDN returning `HTTP 500` for a file that
    was there all along. A single such second used to be final for that pass:
    the card goes up without the picture, and the earliest anything is tried
    again is the next quarter of an hour.

    The retry costs nothing when the first attempt works, which is nearly
    always, and the pass has fourteen idle minutes to spend when it does not.
    """
    for attempt in range(1, PICTURE_ATTEMPTS + 1):
        if str(reference).startswith("http"):
            data = await preview.fetch_picture(reference)
        else:
            data = await download_photo(reference)
        if data is not None:
            if attempt > 1:
                logger.info("the picture arrived on attempt %s of %s",
                            attempt, PICTURE_ATTEMPTS)
            return data
        if attempt < PICTURE_ATTEMPTS:
            await asyncio.sleep(PICTURE_RETRY_PAUSE)
    return None

async def _fetch_pictures(items, force):
    """The bytes of every picture at least one wiki is missing, by slot.

    Downloading is per pass, not per wiki: two wikis showing the same news ask
    for it once. A slot maps to None when the news has no picture, when every
    wiki already holds it, or when the picture would not download — the third
    case being the reason the result cannot simply be read off the news.

    A slot that ends up in that third case is not left to itself. The card goes
    up without the picture and the slot is recorded holding none (`image_key`
    is ''), which is exactly the state `_holds_picture` reads as "this wiki is
    missing it" — so the next pass asks for the picture again, uploads it and
    edits the card into the one with the picture in it. Nothing has to remember
    that the download failed; the empty key already says so."""
    pictures = {}
    for item in items:
        slot = item["slot"]
        if not item["photo_file_id"]:
            pictures[slot] = None
            continue
        wanted = force or any(
            not _holds_picture(wiki_key(wiki_config), slot, item) for wiki_config in WIKIS)
        if not wanted:
            pictures[slot] = None
            continue
        data = await _download(item["photo_file_id"])
        if data is None:
            logger.warning("slot %s: the picture could not be downloaded, the card is "
                           "published without one where it is not already up", slot)
        pictures[slot] = data
    return pictures

def _build_plan(wiki_config, items, pictures, force):
    """The list of slots wiki/pages.py works through for one wiki.

    Each slot answers two questions here. *Does the file have to move?* — only
    when this wiki is missing the picture and the bytes are in hand. *Does the
    card show a picture at all?* — when this wiki's file will hold it after
    this pass, which is true both when it already does and when it is about to.
    That second question is what keeps a card from pointing at a file that
    holds the picture of an older news when a download failed."""
    key = wiki_key(wiki_config)
    templates = wiki_templates(wiki_config)
    files = wiki_files(wiki_config)
    prefix = wiki_css_prefix(wiki_config)

    plan = []
    for item in items:
        slot = item["slot"]
        file_name = files[slot - 1]
        held = _holds_picture(key, slot, item)
        data = pictures.get(slot)
        upload = data if (force or not held) else None
        shown = file_name if (held or upload) else None
        link = item["link"] or ""
        plan.append({
            "slot": slot,
            "template": templates[slot - 1],
            "file": file_name,
            "wikitext": news.render_template(item, shown, prefix),
            "image": upload,
            "image_key": item["photo_unique_id"] if shown else "",
            "edit_summary": EDIT_SUMMARY.format(link=link),
            "upload_summary": UPLOAD_SUMMARY.format(link=link),
        })
    return plan

async def run_pass(force=False):
    """Bring every wiki in line with the channel once.

    Returns what happened: how many templates were edited and how many files
    uploaded across all wikis, how many news there were to publish (`have`) out
    of how many there is room for (`count`), the link of the newest one, and
    the errors of the slots that failed, each named by its wiki. Slots that
    failed keep the state they had, so the next pass tries them again."""
    async with _pass_lock:
        _pass_state["running"] = True
        try:
            return await _run_pass(force)
        finally:
            _pass_state["running"] = False

async def _run_pass(force):
    """The body of a pass, with the lock already held."""
    count = _slot_count()
    empty = {"templates": 0, "files": 0, "have": 0, "count": count,
             "newest_link": None, "errors": []}

    chat_id = source_chat_id()
    if chat_id is None:
        logger.warning("the source channel is not resolved yet — nothing to publish")
        return empty

    items = news.collect_news(db.get_recent_posts(chat_id), source_username(), count)
    if not items:
        return empty

    pictures = await _fetch_pictures(items, force)

    templates = files = 0
    errors = []
    by_slot = {item["slot"]: item for item in items}
    for wiki_config in WIKIS:
        key = wiki_key(wiki_config)
        plan = _build_plan(wiki_config, items, pictures, force)
        by_plan_slot = {entry["slot"]: entry for entry in plan}
        try:
            results = await asyncio.to_thread(
                wiki.apply_plan, wiki_config["family"], wiki_config["lang"], plan)
        except Exception as e:
            errors.append("{}: {}: {}".format(key, type(e).__name__, e))
            logger.warning("wiki %s failed as a whole: %s", key, e)
            continue

        for result in results:
            item = by_slot[result["slot"]]
            if result["ok"]:
                templates += 1 if result["edited"] else 0
                files += 1 if result["uploaded"] else 0
                db.set_slot(key, result["slot"], item["chat_id"], item["message_id"],
                            by_plan_slot[result["slot"]]["image_key"])
            else:
                errors.append("{} {}: {}".format(key, result["slot"], result["error"]))

    db.set_state("last_pass_ts", int(time.time()))
    db.set_state("last_error", "; ".join(errors))
    logger.info("pass done over %s wiki(s): %s template(s) edited, %s file(s) uploaded, "
                "%s error(s)", len(WIKIS), templates, files, len(errors))
    return {"templates": templates, "files": files, "have": len(items), "count": count,
            "newest_link": items[0]["link"], "errors": errors}
