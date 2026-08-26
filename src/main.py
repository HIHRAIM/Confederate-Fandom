"""Entry point: the Telegram polling task and the loop that writes the wikis.

Run it from this directory — the database, the .env file and Pywikibot's own
directory are all opened by relative path: ``python main.py``.

There is very little here on purpose. Collecting the posts belongs to the
Telegram half (telegram_bot/channel.py), deciding what a news is belongs to
news.py, writing it belongs to the wiki half, and the sequence that ties the
three together belongs to publisher.py — which both this loop and the /update
command call, so that neither owns it.

What is left is the schedule, and it is a clock rather than a stopwatch: the
passes happen at the minutes past the hour named in config.PUBLISH_AT_MINUTES
— :00, :15, :30 and :45 — so that a restart at twenty past does not move every
later pass with it. One pass also runs at start-up, so a restart is not a
quarter of an hour of silence.

The loop reports to the service chats only when there is something a person
should know — a pass that failed, or a pass that changed what a main page says.
A pass that found nothing to do says nothing.

Import order at the top matters: `db.init()` runs before the Telegram package
is imported further, so the schema exists before anything queries it.
"""
import asyncio
import logging
from datetime import datetime, timedelta

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("tprp.main")

import db
from config import PREVIEW_SYNC, SOURCE_CHANNEL
from telegram_bot import (
    bot, main as tg_main, resolve_source_channel, source_chat_id, source_username,
)
from utils import publish_marks, send_service_event

db.init()

_channel = {"resolved": False}

async def _ensure_channel():
    """Make sure the bot knows which channel it is following.

    Asked once at start-up and again at every tick until it works: a channel
    the bot has just been added to, or a name that was corrected in config,
    should not need a restart. Until it succeeds the posts are still collected
    — is_source_chat falls back to the configured name — but nothing is
    published, since the news would have no links."""
    if _channel["resolved"]:
        return True
    try:
        await resolve_source_channel()
        _channel["resolved"] = True
        return True
    except Exception as e:
        logger.warning("could not resolve the source channel %s: %s", SOURCE_CHANNEL, e)
        await send_service_event("service_channel_failed", channel=SOURCE_CHANNEL, error=e)
        return source_chat_id() is not None

async def _sync_from_preview():
    """Read the channel's public preview before a pass, if it is switched on.

    This is what makes the bot notice two things the Bot API never tells it
    about: posts published before it was added or while it was down, and edits
    to the posts the preview itself gave us. A post the bot heard from
    Telegram is left alone — `edited_channel_post` is the authority on those.

    A preview that cannot be read is reported and let go: it is a way of
    catching up, not a condition for publishing what is already stored."""
    if not PREVIEW_SYNC:
        return
    chat_id = source_chat_id()
    username = source_username()
    if chat_id is None:
        return
    if not username:
        logger.info("the source channel has no public @name — its preview cannot be read")
        return

    from backfill import sync

    try:
        seen, added, updated = await sync(chat_id, username)
    except Exception as e:
        logger.warning("preview sync failed: %s", e)
        await send_service_event("backfill_failed", error=e)
        return
    if added or updated:
        await send_service_event("backfill_done", seen=seen, added=added, updated=updated)

def seconds_until_next_mark(now=None):
    """How long to wait for the next scheduled pass.

    The wait is measured against the clock, not against the previous pass: the
    bot publishes at :00, :15, :30 and :45 whatever time it was started at, and
    a pass that took two minutes does not push the next one two minutes late.
    The last mark of an hour is followed by the first mark of the next one —
    which is what ':60' means when the schedule is read aloud."""
    now = now or datetime.now()
    for minute in publish_marks():
        target = now.replace(minute=minute, second=0, microsecond=0)
        if target > now:
            return (target - now).total_seconds()
    target = (now + timedelta(hours=1)).replace(
        minute=publish_marks()[0], second=0, microsecond=0)
    return max(1.0, (target - now).total_seconds())

async def publish_loop():
    """Rebuild the news, then sleep until the next mark on the clock.

    One pass runs at start-up and the rest fall on config.PUBLISH_AT_MINUTES.

    Every failure is caught here: a wiki that is down, a network that is out
    and a bug alike must cost one pass and not the process. The next round is
    minutes away and the posts are already stored, so nothing is lost by
    letting one go."""
    while True:
        try:
            if await _ensure_channel():
                import publisher

                await _sync_from_preview()
                result = await publisher.run_pass()
                if result["errors"]:
                    await send_service_event(
                        "service_publish_failed", error="; ".join(result["errors"]))
                elif result["templates"] or result["files"]:
                    await send_service_event(
                        "service_publish_done",
                        templates=result["templates"],
                        files=result["files"],
                        link=result["newest_link"] or "-",
                    )
        except Exception as e:
            logger.exception("publish_loop failed")
            try:
                await send_service_event("service_publish_failed", error=e)
            except Exception:
                pass
        await asyncio.sleep(seconds_until_next_mark())

async def main():
    """Start the polling task and the publishing loop, then wait.

    The service chats are told once the bot has had five seconds to connect,
    and told again on the way out however the gather ends."""
    tasks = [
        asyncio.create_task(tg_main()),
        asyncio.create_task(publish_loop()),
    ]

    await asyncio.sleep(5)
    await send_service_event("service_started")

    try:
        await asyncio.gather(*tasks)
    finally:
        try:
            await send_service_event("service_stopped")
        finally:
            await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
