"""Getting a post's picture out of Telegram and into memory.

The bytes go straight to the wiki upload, so nothing is written to disk here:
the publisher hands them to a temporary file of its own only because Pywikibot
uploads from a path (wiki/pages.py).
"""
import logging
from io import BytesIO

from telegram_bot.client import bot

logger = logging.getLogger("fd.files")

async def download_photo(file_id):
    """The bytes of one photo, or None when Telegram will not give them.

    A file_id stops working once the post it belongs to is gone, and the Bot
    API refuses files above 20 MB — neither is worth failing a whole pass
    over, so both come back as None and the news is published as a card with
    no picture instead."""
    try:
        buffer = BytesIO()
        await bot.download(file_id, destination=buffer)
        return buffer.getvalue()
    except Exception as e:
        logger.warning("could not download photo %s: %s", file_id, e)
        return None
