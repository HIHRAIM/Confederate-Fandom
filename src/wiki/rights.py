"""Who may do what: the bot's own standing on a wiki, and the caller's.

Two questions are asked here, and they are not the same question.

**May the bot work on this wiki at all?** It must hold one of three statuses —
bot, content moderator or administrator. Without any of them it is an ordinary
account and has no business running a hundred edits over somebody's wiki, so
the task is refused with the reason said out loud.

**May the bot do this particular thing?** A status is not a permission: an
account can be in the bot group and still be unable to touch a protected page
or delete anything. So every mechanic names the MediaWiki rights it needs, the
rights are checked against what the wiki says this session holds, and a
refusal names the *group* that would grant what is missing — a person can act
on «нужен статус модератора контента», not on «нужно право editprotected».

**And may the caller ask for it?** A wiki administrator the bot's owner
appointed is checked again on the wiki itself before their task runs: they
must hold some standing there (rollback, content moderator, discussions
moderator, administrator, bureaucrat, bot). A person with no rights on a wiki
cannot borrow the bot's.

The group names are Fandom's own. «Модератор сообщества» in Fandom's interface
is the discussions moderator, `threadmoderator`; there is no other group by
that name.

Not this module's zone: logging in (wiki/site.py), and who is an administrator
of the *bot* (utils.is_admin, db/admins.py).
"""
import logging

logger = logging.getLogger("fd.wiki.rights")

IMPLICIT_GROUPS = ("*", "user", "autoconfirmed", "emailconfirmed", "wiki_guardian")
"""Groups every registered account has. They say nothing about standing and
are dropped before a list of groups is shown to anybody."""

WORK_GROUPS = ("bot", "content-moderator", "sysop")
"""Any one of these lets the bot work on a wiki at all."""

STAFF_GROUPS = ("rollback", "content-moderator", "threadmoderator",
                "sysop", "bureaucrat", "bot")
"""What counts as standing for a wiki administrator the bot's owner
appointed: rollback, content moderator, discussions moderator, administrator,
bureaucrat, bot. Fandom's global groups (staff, helper, soap) are deliberately
not here — they are not this wiki's community."""


RIGHT_GRANTED_BY = {
    "edit": None,
    "createpage": None,
    "upload": None,
    "move": "content-moderator",
    "move-subpages": "content-moderator",
    "suppressredirect": "content-moderator",
    "editprotected": "content-moderator",
    "reupload": "content-moderator",
    "reupload-own": None,
    "rollback": "rollback",
    "delete": "sysop",
    "undelete": "sysop",
    "deleterevision": "sysop",
    "protect": "sysop",
    "block": "sysop",
    "apihighlimits": "bot",
    "bot": "bot",
}
"""Which group is the lowest one that grants a right on Fandom. None means
every registered account has it. Used only to word a refusal — the right
itself is always read from the wiki, never guessed from a group."""

GRANT_OF = {
    "edit": "editpage",
    "createpage": "createeditmovepage",
    "move": "createeditmovepage",
    "move-subpages": "createeditmovepage",
    "suppressredirect": "createeditmovepage",
    "upload": "uploadfile",
    "reupload-own": "uploadfile",
    "reupload": "uploadeditmovefile",
    "delete": "delete",
    "undelete": "delete",
    "deleterevision": "delete",
    "protect": "protect",
    "editprotected": "editprotected",
    "rollback": "rollback",
    "bot": "highvolume",
    "apihighlimits": "highvolume",
}
"""Which BotPassword grant lets a session use a right its account holds.

The bot logs in with a BotPassword, and the session gets only the rights that
are both the account's and allowed by the password's grants. So a right can
be missing for two different reasons, and they want two different fixes: the
account lacks it (a group on the wiki), or the password does not pass it on
(a checkbox on Special:BotPasswords). `explain_missing` tells them apart."""



def _info(site, fresh=False):
    """What the wiki says about this session. -> the userinfo mapping.

    With `fresh` the cached copy is dropped first, which is what makes a right
    granted a minute ago visible without restarting the bot.
    """
    if fresh:
        try:
            del site.userinfo
        except Exception:
            pass
    try:
        return site.userinfo or {}
    except Exception as e:
        logger.warning("could not read the user info on %s: %s", site, e)
        return {}


def groups(site, fresh=False):
    """The groups this session's account holds on one wiki, implicit ones out."""
    info = _info(site, fresh)
    return [g for g in info.get("groups", []) if g not in IMPLICIT_GROUPS]


def rights(site, fresh=False):
    """Every right this session holds on one wiki, as a set."""
    return set(_info(site, fresh).get("rights", []))


def has_right(site, right, fresh=False):
    """Whether this session may do one particular thing on one wiki."""
    return right in rights(site, fresh)


def account_rights(site):
    """Every right the bot's *account* holds on one wiki, whatever the session
    may use. -> a set, or None when the wiki would not say."""
    import pywikibot

    try:
        return set(pywikibot.User(site, site.username()).rights(force=True))
    except Exception as e:
        logger.warning("could not read the account's rights on %s: %s", site, e)
        return None


def explain_missing(site, missing, wiki_key=None):
    """Why this session cannot use these rights. -> utils.Explained, or None.

    `missing` is rights, or the (right, group) pairs `missing_rights` gives.

    When the account holds a right the session lacks, the BotPassword is what
    withholds it, and the answer names the grant to tick. Otherwise it names
    the group that would give the account the right, or says the account
    lacks even an ordinary user's rights. It used to name a group every time,
    and told a content moderator — a group that holds rollback — that rollback
    needed the rollbacker group, when what was missing was the grant.
    """
    from utils import Explained, localized

    missing = [item[0] if isinstance(item, (list, tuple)) else item
               for item in missing]
    missing = [right for right in missing if right]
    if not missing:
        return None
    wiki_key = wiki_key or "{}:{}".format(site.family.name, site.code)
    held = account_rights(site) or set()
    grants = []
    for right in missing:
        grant = GRANT_OF.get(right)
        if right in held and grant and grant not in grants:
            grants.append(grant)
    if grants:
        return Explained(
            "task_missing_grants", wiki=wiki_key,
            grants=lambda lang: ", ".join(
                "«{}»".format(localized("grant_" + grant, lang))
                for grant in grants))
    groups = needed_groups([(right, RIGHT_GRANTED_BY.get(right))
                            for right in missing])
    if groups:
        return Explained(
            "task_missing_group_rights", wiki=wiki_key,
            groups=lambda lang: ", ".join(group_label(group, lang)
                                          for group in groups))
    return Explained("task_missing_basic_rights", wiki=wiki_key)


def group_label(group, lang):
    """A group's name as a person reads it, in their language, with the raw
    name in brackets; a group the i18n files do not name is shown raw.

    The names live in the i18n files as `access_group_<group>`. They used to
    be a Russian table here, which put Russian into every refusal whatever
    the person read the bot in. A right is never named on its own — a refusal
    names the group that grants it, the thing a person can ask for.
    """
    from utils import has_translation, localized

    key = "access_group_" + str(group).replace("-", "_")
    if not has_translation(key):
        return group
    return "{} ({})".format(localized(key, lang), group)


def work_status(site, fresh=False):
    """Which of the three working statuses the bot holds here. -> list."""
    held = set(groups(site, fresh))
    return [g for g in WORK_GROUPS if g in held]


def may_work(site, fresh=False):
    """Whether the bot has any standing on this wiki at all.

    -> (True, the statuses it holds) or (False, []). A False here stops a task
    before it reads a single page: an account with no status has no business
    running a job over somebody's wiki, whatever rights it happens to have.
    """
    held = work_status(site, fresh)
    return bool(held), held


def missing_rights(site, needed, fresh=False):
    """Which of the rights a mechanic needs this session does not hold.

    -> a list of (right, the group that would grant it). The group may be
    None, which means every registered account has that right and its absence
    is a block or a protected wiki rather than a missing status.
    """
    held = rights(site, fresh)
    return [(right, RIGHT_GRANTED_BY.get(right))
            for right in needed if right not in held]


def needed_groups(missing):
    """The distinct groups that would cover everything in `missing`, in order
    of how much they grant."""
    wanted = []
    for _right, group in missing:
        if group and group not in wanted:
            wanted.append(group)
    return sorted(wanted, key=lambda g: WORK_GROUPS.index(g)
                  if g in WORK_GROUPS else -1)


def user_groups(site, username):
    """The groups another account holds on this wiki.

    Asked of the wiki directly rather than through a Page or a User object,
    because the answer is wanted for a name that may not exist at all — and a
    name that does not exist must read as "no standing" rather than raise.
    """
    if not username:
        return []
    try:
        request = site.simple_request(action="query", list="users",
                                      ususers=username, usprop="groups")
        data = request.submit()
    except Exception as e:
        logger.warning("could not ask %s about %s: %s", site, username, e)
        raise
    users = (data.get("query") or {}).get("users") or []
    if not users or "missing" in users[0] or "invalid" in users[0]:
        return []
    return [g for g in users[0].get("groups", []) if g not in IMPLICIT_GROUPS]


def is_wiki_staff(site, username):
    """Whether one account has any standing on one wiki.

    -> (True, the groups) when it holds one of STAFF_GROUPS, (False, groups)
    otherwise. This is the check a wiki administrator of the bot's is put
    through on the wiki they asked the bot to work on: the appointment is the
    bot owner's, but the standing has to be the wiki's own.
    """
    held = user_groups(site, username)
    return bool(set(held) & set(STAFF_GROUPS)), held
