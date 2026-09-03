"""Who may set the bot to work, and what the bot may do once it is set.

Three questions, asked in this order, because each is cheaper than the next
and a refusal should cost as little as possible:

1. **Is the caller allowed at all?** A bot administrator (config.ADMINS) or a
   wiki administrator the bot's owner appointed (db/admins.py). Nobody else
   gets an answer beyond "эта команда только для администраторов".
2. **Has the bot any standing on this wiki?** It must be in one of three
   groups — bot, content moderator, administrator. Without one it is an
   ordinary account and has no business running a hundred edits over
   somebody's wiki, and the refusal says exactly that.
3. **Has it the rights this task needs, and has the caller standing here?**
   A missing right is reported as the *group* that would grant it, because
   «нужен статус модератора контента» is something a person can act on and
   «нужно право editprotected» is not. And a wiki administrator is checked on
   the wiki itself: the appointment is the bot owner's, the standing has to be
   the wiki's own.

The order matters for a second reason: only the first question can be answered
without logging in anywhere, so a stranger's command costs the bot nothing.

Not this module's zone: the group and right tables (wiki/rights.py), and the
wording of the answers (i18n/, the commands).
"""
import logging

logger = logging.getLogger("fd.tasks.access")

BOT_ADMIN = "bot_admin"
WIKI_ADMIN = "wiki_admin"


def caller(platform, user_id, display_name=None):
    """Who is asking. -> a mapping, or None when they may not ask at all.

    The mapping is what a task row stores and what the service log prints:
    the platform, the numeric id that identifies them, the name they are shown
    under, their Fandom account where there is one, and their role.
    """
    import db
    from utils import is_admin

    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return None

    if is_admin(platform, uid):
        row = db.get_wiki_admin(platform, uid)
        return {"platform": str(platform), "id": uid,
                "name": display_name or (row["display_name"] if row else None) or str(uid),
                "wiki_user": row["wiki_user"] if row else None,
                "role": BOT_ADMIN}

    row = db.get_wiki_admin(platform, uid)
    if row is None:
        return None
    if display_name and display_name != row["display_name"]:
        db.touch_display_name(platform, uid, display_name)
    return {"platform": str(platform), "id": uid,
            "name": display_name or row["display_name"] or str(uid),
            "wiki_user": row["wiki_user"], "role": WIKI_ADMIN}


def describe(requester):
    """How the service log names the person who asked: «Имя (id)».

    Never a mention. A report that pings somebody every quarter of an hour is
    a report people mute, and the log is meant to be read.
    """
    if not requester:
        return "—"
    name = requester.get("name") or str(requester.get("id"))
    wiki_user = requester.get("wiki_user")
    if wiki_user and wiki_user != name:
        return "{} ({}, на вики — {})".format(name, requester.get("id"), wiki_user)
    return "{} ({})".format(name, requester.get("id"))


class Refusal(Exception):
    """A check said no, with a text a person can act on.

    An exception rather than a return value because every caller does the same
    thing with it — send it and stop — and because a check that is forgotten
    should break loudly rather than quietly allow.
    """

    def __init__(self, text):
        """Carry the reason, already worded for the person who asked."""
        super().__init__(text)
        self.text = text


def check_bot_standing(site, wiki_key):
    """The bot's own right to work on one wiki. -> the statuses it holds.

    Raises Refusal naming what is missing. This is the check the operator
    asked for in as many words: without the status of a bot, a content
    moderator or an administrator, the bot refuses and explains why.
    """
    from wiki import rights

    ok, held = rights.may_work(site, fresh=True)
    if not ok:
        current = rights.groups(site)
        raise Refusal(
            "На вики {} у бота нет ни статуса бота, ни модератора контента, "
            "ни администратора{}. Без одного из них он за работу не берётся: "
            "сотня правок от аккаунта без статуса — это то, за что банят.".format(
                wiki_key,
                " (сейчас: {})".format(", ".join(rights.group_label(g) for g in current))
                if current else ""))
    return held


def check_rights(site, wiki_key, mechanics):
    """The rights this task needs. -> None, or raises Refusal naming a group."""
    from tasks import registry
    from wiki import rights

    needed = registry.rights_for(mechanics)
    missing = rights.missing_rights(site, needed)
    if not missing:
        return
    groups = rights.needed_groups(missing)
    what = ", ".join(rights.right_label(right) for right, _group in missing)
    if groups:
        raise Refusal(
            "На вики {} боту не хватает прав: {}. Нужен статус: {}.".format(
                wiki_key, what,
                ", ".join(rights.group_label(group) for group in groups)))
    raise Refusal(
        "На вики {} боту не хватает прав: {}. Это права обычного участника — "
        "похоже, аккаунт заблокирован или вики закрыта для правок.".format(
            wiki_key, what))


def check_caller_standing(site, wiki_key, requester):
    """A wiki administrator's own standing on the wiki they chose.

    A bot administrator is not checked: they own the bot. Anybody else must
    hold something on that wiki — rollback, content moderator, discussions
    moderator, administrator, bureaucrat or bot. The appointment is global and
    deliberately cheap to give; this is what keeps it from being a way to
    borrow rights where one has none.
    """
    from wiki import rights

    if not requester or requester.get("role") == BOT_ADMIN:
        return
    wiki_user = requester.get("wiki_user")
    if not wiki_user:
        raise Refusal(
            "У вас не указан аккаунт на Fandom — попросите администратора "
            "бота назначить вас заново, указав ник.")
    try:
        ok, held = rights.is_wiki_staff(site, wiki_user)
    except Exception as e:
        raise Refusal("Не удалось проверить ваши права на вики {}: {}".format(
            wiki_key, e))
    if ok:
        return
    raise Refusal(
        "У участника {} нет особых прав на вики {}{}. Запускать работы бота "
        "может только тот, у кого на этой вики есть статус: откатчик, "
        "модератор контента, модератор обсуждений, администратор, бюрократ "
        "или бот.".format(
            wiki_user, wiki_key,
            " (сейчас: {})".format(", ".join(rights.group_label(g) for g in held))
            if held else ""))


def check_all(site, wiki_key, mechanics, requester):
    """Every check, in the order that costs the least. -> the bot's statuses."""
    held = check_bot_standing(site, wiki_key)
    check_caller_standing(site, wiki_key, requester)
    check_rights(site, wiki_key, mechanics)
    return held
