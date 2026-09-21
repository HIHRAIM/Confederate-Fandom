"""Long answers as paged messages, with arrows under them.

The Telegram half of what `discord_bot/pages.py` does, and the same reason:
`/tasks` printed nineteen mechanics as one block of plain text with the codes
on lines of their own, and Telegram, sent no parse mode, showed the backticks
around them as backticks. Here a long answer is an HTML message — the name in
bold, the code in monospace — cut into pages, with two arrows under it.

**Paging is stateless, and that is the difference from the Discord side.** A
Discord view holds its pages in memory; an inline keyboard holds nothing but
sixty-four bytes of callback data, so the button carries only *which* list and
*which* page, and the list is built again when it is pressed. That costs a
couple of queries and buys three things: the buttons still work after a
restart, nothing has to be remembered per person, and `/jobs` shows what is
running now rather than what was running when the message was sent.

`build` is the whole of that contract: every list this module can page through
is named there, and a kind that is not is not pageable. The permission check
is made again on every press, because a button lives longer than the moment
somebody was allowed to press it.

Not this module's zone: what the lists say (`tasks/lists.py`).
"""
import html
import logging
import types

from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from telegram_bot.client import router
from utils import localized, paginate

logger = logging.getLogger("fd.telegram.pages")

CALLBACK_PREFIX = "pg:"

MESSAGE_LIMIT = 4096

def esc(text):
    """One value, safe to put in an HTML message.

    Everything interpolated goes through this. The messages carry wiki names,
    mechanic codes and the text of exceptions, and one `<` in any of them
    would make Telegram reject the whole message — or, worse, swallow the rest
    of the line as a tag it did not recognise."""
    return html.escape(str(text), quote=False)


def code(text):
    """One technical name, as monospace."""
    return "<code>{}</code>".format(esc(text))


def bold(text):
    """One name, as the eye's first stop on the line."""
    return "<b>{}</b>".format(esc(text))


MARKUP = types.SimpleNamespace(code=code, bold=bold, esc=esc)
"""This half's three formatters, in the shape `tasks/lists.py` takes."""


def build(kind, lang):
    """Title and lines for one pageable list. -> (title, lines) or None.

    The catalogue of what may be paged. A kind that is not named here comes
    back as None and the press is ignored, which is also what happens to a
    button from a version of the bot that knew a kind this one does not."""
    from tasks import lists

    if kind == "tasks":
        return lists.catalogue(lang, MARKUP)
    if kind == "jobs":
        return lists.jobs(lang, MARKUP)
    if kind == "sched":
        return lists.schedules(lang, MARKUP)
    if kind == "help":
        return lists.help_text(lang, MARKUP, lists.TELEGRAM)
    return None


def _allowed(kind, query):
    """Whether the person pressing may see this list at all.

    Checked again on every press rather than trusted from the command that
    sent the message: a keyboard sits in a chat for as long as the message
    does, and whoever ran the command is not necessarily whoever pressed."""
    from utils import is_admin

    user = query.from_user
    if user is None:
        return False
    if kind == "help":
        return is_admin("telegram", user.id)

    from tasks import access

    name = ("@" + user.username) if user.username else user.full_name
    return access.caller("telegram", user.id, name) is not None


def render(title, pages, index, lang):
    """One page as the text of a message."""
    body = [bold(title), "", pages[index]]
    if len(pages) > 1:
        body.append("")
        body.append(esc(localized("page_of", lang, page=index + 1,
                                  total=len(pages))))
    return "\n".join(body)[:MESSAGE_LIMIT]


def keyboard(kind, index, total, lang):
    """The arrows under a paged message, or None when there is one page.

    Only the arrow that leads somewhere is shown. A greyed-out button is a
    Discord idea; Telegram has no disabled state, and a button that answers
    nothing reads as a bot that is broken."""
    if total <= 1:
        return None
    row = []
    if index > 0:
        row.append(InlineKeyboardButton(
            text=localized("page_prev", lang),
            callback_data="{}{}:{}".format(CALLBACK_PREFIX, kind, index - 1)))
    if index < total - 1:
        row.append(InlineKeyboardButton(
            text=localized("page_next", lang),
            callback_data="{}{}:{}".format(CALLBACK_PREFIX, kind, index + 1)))
    return InlineKeyboardMarkup(inline_keyboard=[row])


async def send(message, kind, lang, index=0):
    """Answer with one page of a list, and the arrows to reach the rest."""
    built = build(kind, lang)
    if built is None:
        logger.warning("no such pageable list: %s", kind)
        return
    title, lines = built
    pages = paginate(lines)
    index = max(0, min(len(pages) - 1, index))
    await message.answer(render(title, pages, index, lang),
                         parse_mode="HTML",
                         reply_markup=keyboard(kind, index, len(pages), lang))


@router.callback_query(lambda query: query.data
                       and query.data.startswith(CALLBACK_PREFIX))
async def turn_page(query: CallbackQuery):
    """Turn a page: rebuild that list and rewrite the message in place.

    Every failure is answered rather than left to spin: an unparseable button,
    a list this version does not know, somebody who may not see it, or an edit
    Telegram refuses because the text came out identical.
    """
    from utils import user_lang

    parts = (query.data or "").split(":")
    if len(parts) != 3 or not parts[2].lstrip("-").isdigit():
        await query.answer()
        return
    kind, index = parts[1], int(parts[2])
    lang = user_lang(query.from_user)

    if not _allowed(kind, query):
        await query.answer(localized("not_admin", lang), show_alert=True)
        return

    built = build(kind, lang)
    if built is None or query.message is None:
        await query.answer()
        return
    title, lines = built
    pages = paginate(lines)
    index = max(0, min(len(pages) - 1, index))
    try:
        await query.message.edit_text(
            render(title, pages, index, lang), parse_mode="HTML",
            reply_markup=keyboard(kind, index, len(pages), lang))
    except Exception as e:
        logger.info("could not turn the page: %s", e)
    await query.answer()
