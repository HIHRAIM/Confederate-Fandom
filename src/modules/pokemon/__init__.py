"""The species module: the Russian names of Pokémon species on Покемон Вики.

One job, once a night at config.SPECIES_AT. It walks the articles of
config.SPECIES_WIKI and brings the names of the species to the standard ones —
nine thousand pages, three hundred edits, and nobody's evening spent doing it
by hand.

| Module | Responsibility |
|---|---|
| `names.py` | the replacement engine and the hand-written rules: case carrying, stems, tables of endings, protection of file names |
| `rules.py` | the 270 pairs from `data/fromnumber_name_rules.tsv`, the allowed endings, the manual exceptions |
| `walk.py` | one walk over the articles of one wiki, saving only what changed |

Importing `walk` pulls in Pywikibot, so it is not re-exported here: whoever
walks a wiki says `from modules.pokemon import walk` and takes the library
with it.

**It refuses to start without the bot flag** (config.SPECIES_REQUIRE_BOT_FLAG).
A walk of nine thousand articles is hundreds of edits, and hundreds of
unflagged edits arrive in Recent changes as a flood that buries everybody
else's work for the evening. The right belongs to the wiki to give, so the job
says what is missing and waits for tomorrow rather than making a mess that has
to be apologised for.

It reports however it ends, unlike the news: a job that runs once a night and
says nothing cannot be told from one that never ran.
"""
import asyncio
import logging

logger = logging.getLogger("fd.modules.pokemon")

CODE = "pokemon"

JOB = "species"

from modules.pokemon.rules import find_derived, fix_text, fix_title


async def job():
    """One walk of the species wiki, in the worker thread Pywikibot needs."""
    from config import (
        SPECIES_LIMIT, SPECIES_REQUIRE_BOT_FLAG, SPECIES_SUMMARY, SPECIES_WIKI,
    )
    from utils import send_service_event

    if not SPECIES_WIKI:
        return
    try:
        import wiki
        from modules.pokemon import walk

        site = await asyncio.to_thread(
            wiki.get_site, SPECIES_WIKI["family"], SPECIES_WIKI["lang"])
        if SPECIES_REQUIRE_BOT_FLAG and not await asyncio.to_thread(
                wiki.has_bot_right, site):
            await send_service_event(
                "service_species_no_flag",
                wiki="{family}:{lang}".format(**SPECIES_WIKI))
            return
        report = await asyncio.to_thread(
            walk.run, site, SPECIES_SUMMARY, SPECIES_LIMIT)
        await send_service_event(
            "service_species_done",
            checked=report["checked"], edited=report["edited"],
            replaced=report["replaced"], failed=report["failed"],
            unknown=", ".join(report["unknown"]) or "—")
    except Exception as e:
        logger.exception("the species job failed")
        try:
            await send_service_event("service_species_failed", error=e)
        except Exception:
            pass


def jobs():
    """The jobs of this module, for main.py to register. -> a list of dicts."""
    from config import SPECIES_AT, SPECIES_WIKI

    if not SPECIES_WIKI:
        return []
    return [{"name": JOB, "run": job, "daily_at": SPECIES_AT,
             "at_start": False}]
