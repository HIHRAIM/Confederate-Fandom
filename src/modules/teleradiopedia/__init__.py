"""The news module: the main pages of Телепедия and Радиопедия.

One job, and everything it needs. The bot administrates a Telegram channel;
its three newest posts become three cards on the main page of every wiki in
config.WIKIS, and the pass that keeps them in step runs at the minutes named
in config.PUBLISH_AT_MINUTES — :00, :15, :30, :45 — and once at start-up, so a
restart is not a quarter of an hour of silence.

| Module | Responsibility |
|---|---|
| `news.py` | what a news *is*: selection, shortening, dates, the card's wikitext |
| `publisher.py` | one publishing pass end to end, one wiki at a time |
| `preview.py` | the channel's public web preview — the only way to posts published before the bot was added |
| `backfill.py` | what the preview recovers and what it may refresh |

Why it is a module rather than the bot: the bot now does two other things
beside this one (the species walk, and the script mechanics anybody may ask
for), and all three share one worker thread. Being a module means this job is
registered like the others, queued like the others, and — because it is what
somebody's readers actually see — runs *before* the others when both are due
(scheduler.py: MODULE_PRIORITY).

The pass reports only when there is something a person should know: a failure,
or a change to what a main page says. A pass that found nothing new says
nothing, four times an hour, for ever.
"""
import logging

logger = logging.getLogger("fd.modules.teleradiopedia")

CODE = "teleradiopedia"

JOB = "news"

_channel = {"resolved": False}


async def _ensure_channel():
    """Make sure the bot knows which channel it is following.

    Asked once at start-up and again at every tick until it works: a channel
    the bot has just been added to, or a name that was corrected in config,
    should not need a restart. Until it succeeds the posts are still collected
    — is_source_chat falls back to the configured name — but nothing is
    published, since the news would have no links.
    """
    from modules.teleradiopedia.settings import SOURCE_CHANNEL
    from telegram_bot import resolve_source_channel, source_chat_id
    from utils import send_service_event

    if _channel["resolved"]:
        return True
    try:
        await resolve_source_channel()
        _channel["resolved"] = True
        return True
    except Exception as e:
        logger.warning("could not resolve the source channel %s: %s",
                       SOURCE_CHANNEL, e)
        await send_service_event("service_channel_failed",
                                 channel=SOURCE_CHANNEL, error=e)
        return source_chat_id() is not None


async def _sync_from_preview():
    """Read the channel's public preview before a pass, if it is switched on.

    This is what makes the bot notice two things the Bot API never tells it
    about: posts published before it was added or while it was down, and edits
    to the posts the preview itself gave us. A post the bot heard from
    Telegram is left alone — `edited_channel_post` is the authority on those.

    A preview that cannot be read is reported and let go: it is a way of
    catching up, not a condition for publishing what is already stored.
    """
    from modules.teleradiopedia.settings import PREVIEW_SYNC
    from telegram_bot import source_chat_id, source_username
    from utils import send_service_event

    if not PREVIEW_SYNC:
        return
    chat_id = source_chat_id()
    username = source_username()
    if chat_id is None:
        return
    if not username:
        logger.info("the source channel has no public @name — its preview cannot be read")
        return

    from modules.teleradiopedia.backfill import sync

    try:
        seen, added, updated = await sync(chat_id, username)
    except Exception as e:
        logger.warning("preview sync failed: %s", e)
        await send_service_event("backfill_failed", error=e)
        return
    if added or updated:
        await send_service_event("backfill_done", seen=seen, added=added,
                                 updated=updated)


async def job():
    """One news pass: catch up with the channel, then write the wikis.

    Every failure is caught here: a wiki that is down, a network that is out
    and a bug alike must cost one pass and not the process. The next round is
    minutes away and the posts are already stored, so nothing is lost by
    letting one go.
    """
    from utils import send_service_event

    try:
        if not await _ensure_channel():
            return
        from modules.teleradiopedia import publisher

        await _sync_from_preview()
        result = await publisher.run_pass()
        if result["errors"]:
            await send_service_event("service_publish_failed",
                                     error="; ".join(result["errors"]))
        elif result["templates"] or result["files"]:
            await send_service_event(
                "service_publish_done",
                templates=result["templates"],
                files=result["files"],
                link=result["newest_link"] or "-")
    except Exception as e:
        logger.exception("the news job failed")
        try:
            await send_service_event("service_publish_failed", error=e)
        except Exception:
            pass


def jobs():
    """The jobs of this module, for main.py to register. -> a list of dicts.

    None at all when the deployment publishes no news (settings.enabled):
    no pass four times an hour, no channel resolved at start-up, nothing in
    the Discord presence."""
    from modules.teleradiopedia import settings
    from utils import publish_marks

    if not settings.enabled():
        return []
    return [{"name": JOB, "run": job, "minutes": publish_marks(),
             "at_start": True}]
