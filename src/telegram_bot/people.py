"""Who is who on Telegram: naming a person, and the moment the bot meets them.

Discord's /wikiadmin is handed a user object, so it has the id at once. The
Telegram one is handed an @name, and a bot cannot ask Telegram whose it is:
getChat resolves the @name of a public group or channel and answers «chat not
found» for a person. That is why appointing by @name never worked here — every
@name got «не понял, о ком речь» — and why the command leaned on a reply to the
person's message instead.

So an @name the bot has no id for becomes an invitation (db/admins.py), and
this module keeps the other half of that arrangement: it looks at every
message and button press the bot receives, and the first one from an account
holding an invited @name turns the invitation into an appointment keyed by
that account's numeric id. From then on the @name does not matter — the
person may change it, and whoever picks it up afterwards gets nothing.

The check is an outer middleware, so it runs before any handler: the message
that claims an invitation is already answered as an administrator's, and a
person told «напишите боту /tasks» can do exactly that. It stores nothing
about anybody whose @name is not invited.
"""
import logging
import re

from telegram_bot.client import bot, router

logger = logging.getLogger("fd.telegram.people")

_USERNAME_RE = re.compile(r"^@?([A-Za-z][A-Za-z0-9_]{3,31})$")
"""A Telegram @name: a letter, then letters, digits and underscores, five to
thirty-two characters in all; four are let through for the short collectible
names."""

def display_name(user):
    """How a person is named in the list and in the log: @name, or their name."""
    return ("@" + user.username) if user.username else user.full_name

def _utf16_tail(text, units):
    """What follows the first `units` UTF-16 code units of `text`.

    Telegram counts entity offsets in UTF-16 units, so an emoji in a name
    shifts every offset after it by two; slicing the Python string by the
    offset would cut the Fandom account in the wrong place."""
    return text.encode("utf-16-le")[units * 2:].decode("utf-16-le", "ignore")

async def resolve(message):
    """Who an administrator named after the command, and what follows.

    -> (id, display name, @name without '@', the rest of the text).

    Three spellings, and a reply to somebody's message is not one of them:
    it used to win over anything typed, so replying to one person while
    typing another person's @name appointed the first.

    * **a person picked from Telegram's list** — for somebody with no @name
      that arrives as a text_mention carrying the account itself, id included;
    * **a numeric id** — exact, and how somebody with no @name is named by
      hand;
    * **an @name** — no id comes back (see the module docstring), and the
      caller turns it into an invitation.

    The id is None when there is none to be had; the @name is None when the
    person was not named by one, and all three are None when the first word
    is none of these.
    """
    text = message.text or ""
    for entity in message.entities or []:
        if entity.type == "text_mention" and entity.user:
            rest = _utf16_tail(text, entity.offset + entity.length)
            return (entity.user.id, display_name(entity.user),
                    entity.user.username, rest.strip())

    parts = text.split(maxsplit=2)
    token = parts[1] if len(parts) > 1 else ""
    rest = parts[2].strip() if len(parts) > 2 else ""
    if token.isascii() and token.isdecimal():
        name = None
        try:
            chat = await bot.get_chat(int(token))
            name = ("@" + chat.username) if chat.username else chat.full_name
        except Exception as e:
            logger.info("no name for %s: %s", token, e)
        return int(token), name, None, rest
    match = _USERNAME_RE.match(token)
    if match:
        return None, "@" + match.group(1), match.group(1), rest
    return None, None, None, rest

async def claim_invitation(user):
    """Turn a waiting invitation for this account's @name into an appointment."""
    import db
    from utils import lang_of, localized, user_lang

    name = display_name(user)
    invite = db.claim_wiki_admin_invite(user.username, user.id, name)
    if invite is None:
        return
    logger.info("the invitation for @%s is claimed by %s", user.username, user.id)

    try:
        await bot.send_message(user.id, localized(
            "wikiadmin_welcome", user_lang(user), wiki_user=invite["wiki_user"]))
    except Exception as e:
        logger.info("could not greet %s: %s", user.id, e)

    added_by = str(invite["added_by"] or "")
    if added_by.isdecimal():
        try:
            await bot.send_message(int(added_by), localized(
                "wikiadmin_claimed", lang_of("telegram", added_by),
                username=user.username,
                user_id=user.id, wiki_user=invite["wiki_user"]))
        except Exception as e:
            logger.info("could not tell %s about the claim: %s", added_by, e)

async def _claim_invitation(handler, event, data):
    """Outer middleware: claim an invitation, then let the update through.

    A failure here is logged and never stops the update: the person's message
    is answered either way, and the invitation is still waiting for the next.
    """
    user = getattr(event, "from_user", None)
    if user is not None and user.username and not user.is_bot:
        try:
            await claim_invitation(user)
        except Exception:
            logger.exception("could not check the invitations for @%s",
                             user.username)
    return await handler(event, data)

router.message.outer_middleware(_claim_invitation)
router.callback_query.outer_middleware(_claim_invitation)
