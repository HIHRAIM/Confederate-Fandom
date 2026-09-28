"""Keeping the stored posts in step with the channel through its web preview.

Two gaps make this module necessary, and both come from the same place: the
Bot API tells a bot about a post as it happens, and never again.

* **Posts from before the bot arrived.** A channel that has been running for
  years leaves a freshly added bot with an empty database and three empty
  slots. The preview holds about twenty posts, which is plenty for three news.
* **Changes the bot was not listening for.** An edit made while the bot was
  down, or to a post that came from the preview in the first place, produces
  no update the bot will ever see. Reading the preview again is what notices
  it, and rewriting the stored row is what carries the correction to the wikis
  at the next pass.

One rule keeps the second from doing damage: **a post the bot heard itself is
not overwritten from the preview.** Its row carries a real file_id, its
picture is the larger one, and its text is what Telegram itself handed over,
while the preview's copy of a long link is sometimes elided — comparing the
two would rewrite the templates over a difference nobody can see. Those posts
are corrected by `edited_channel_post` instead. `/backfill all` is the door
out of that rule when a post really was edited while the bot was away.
"""
import logging

import db
from modules.teleradiopedia import preview
from modules.teleradiopedia.settings import PREVIEW_LIMIT

logger = logging.getLogger("fd.backfill")

async def sync(chat_id, channel, limit=None, refresh_all=False):
    """Read the preview and bring the stored posts in line with it.

    Adds the posts that are missing, and refreshes the ones whose text,
    formatting or picture has changed — by default only those the preview gave
    us in the first place, or every one of them when `refresh_all` is set.

    `channel` is the @name: the preview is addressed by name, so a channel
    without a public one cannot be read this way. Returns
    ``(seen, added, updated)``. Raises `preview.PreviewError` when the page
    cannot be read."""
    limit = PREVIEW_LIMIT if limit is None else limit
    posts = await preview.fetch_posts(channel)
    posts = posts[-limit:] if limit > 0 else posts

    added = updated = 0
    for post in posts:
        row = db.get_post(chat_id, post["message_id"])
        if row is None:
            _store(chat_id, post)
            added += 1
            continue
        if not refresh_all and row["source"] != "preview":
            if _fill_forward(chat_id, row, post):
                updated += 1
            continue
        if not _differs(row, post):
            continue
        _store(chat_id, post)
        updated += 1

    if added:
        db.cleanup_old_posts(chat_id)
    logger.info("preview sync for @%s: %s post(s) seen, %s added, %s updated",
                channel, len(posts), added, updated)
    return len(posts), added, updated

def _store(chat_id, post):
    """Write one preview post into the database, marked as coming from there."""
    url = post["photo_url"]
    db.save_post(
        chat_id=chat_id,
        message_id=post["message_id"],
        date=post["date"],
        text=post["text"],
        entities=post["entities"],
        source="preview",
        forward_type=post["forward_type"],
        forward_name=post["forward_name"],
        media_group_id=None,
        photo_file_id=url,
        photo_unique_id=preview.picture_key(url) if url else None,
    )

def _fill_forward(chat_id, row, post):
    """Give a post the bot heard itself the repost line it never got; True
    when something was filled in.

    The rule above protects what the Bot API said — but it cannot protect what
    it never stored. A post collected before the bot knew about reposts has
    both columns empty, and no edit will ever arrive to fill them, so its card
    would be missing the line for as long as it stays on the main page. The
    preview knows where that post came from, and saying so is not rewriting
    anything: an empty field is filled, a filled one is left alone."""
    if row["forward_type"] or not post["forward_type"]:
        return False
    db.set_post_forward(chat_id, row["message_id"],
                        post["forward_type"], post["forward_name"])
    logger.info("post %s: filled in the repost line from the preview (%s)",
                row["message_id"], post["forward_name"])
    return True

def _differs(row, post):
    """Whether the preview now says something else than the stored row does.

    The picture counts only when the stored one came from the preview as
    well — a row that holds a Telegram file_id is not "changed" merely because
    the preview names its picture by URL."""
    if (row["text"] or "") != (post["text"] or ""):
        return True
    if db.post_entities(row) != (post["entities"] or []):
        return True
    if (row["forward_name"] or "") != (post["forward_name"] or ""):
        return True
    stored_picture = row["photo_file_id"] or ""
    if stored_picture.startswith("http") or not stored_picture:
        return stored_picture != (post["photo_url"] or "")
    return False
