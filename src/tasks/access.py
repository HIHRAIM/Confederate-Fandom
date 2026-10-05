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

from utils import Explained

logger = logging.getLogger("fd.tasks.access")

BOT_ADMIN = "bot_admin"
WIKI_ADMIN = "wiki_admin"
SPONSOR = "sponsor"

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
        import sponsors
        sponsor_id = sponsors.canonical_id(platform, uid)
        if sponsor_id and db.sponsor_tier(sponsor_id) != 0:
            return {"platform": str(platform), "id": uid,
                    "name": display_name or str(uid), "wiki_user": None,
                    "role": SPONSOR}
        return None
    if display_name and display_name != row["display_name"]:
        db.touch_display_name(platform, uid, display_name)
    return {"platform": str(platform), "id": uid,
            "name": display_name or row["display_name"] or str(uid),
            "wiki_user": row["wiki_user"], "role": WIKI_ADMIN}

def describe(requester, lang):
    """How the service log names the person who asked: «Name (id)».

    Never a mention. A report that pings somebody every quarter of an hour is
    a report people mute, and the log is meant to be read.
    """
    from utils import localized

    if not requester:
        return "—"
    name = requester.get("name") or str(requester.get("id"))
    wiki_user = requester.get("wiki_user")
    if wiki_user and wiki_user != name:
        return localized("requester_with_wiki_user", lang, name=name,
                         id=requester.get("id"), wiki_user=wiki_user)
    return "{} ({})".format(name, requester.get("id"))

class Refusal(Explained):
    """A check said no, with a reason a person can act on.

    An exception rather than a return value because every caller does the same
    thing with it — send it and stop — and because a check that is forgotten
    should break loudly rather than quietly allow. An `Explained`, so that the
    person reads the reason in their language and the service chats in
    theirs: `refusal.text(lang)`.
    """

def _groups(names):
    """A list of groups as a value of a refusal, worded per reader."""
    from wiki import rights

    return lambda lang: ", ".join(rights.group_label(group, lang)
                                  for group in names)

def _current(names):
    """« (now: …)» after a refusal, or nothing when no group is held."""
    from utils import localized

    if not names:
        return ""
    groups = _groups(names)
    return lambda lang: localized("refusal_current_groups", lang,
                                  groups=groups(lang))

def check_bot_standing(site, wiki_key):
    """The bot's own right to work on one wiki. -> the statuses it holds.

    Raises Refusal naming what is missing. This is the check the operator
    asked for in as many words: without the status of a bot, a content
    moderator or an administrator, the bot refuses and explains why.
    """
    from wiki import rights

    ok, held = rights.may_work(site, fresh=True)
    if not ok:
        raise Refusal("refusal_bot_no_status", wiki=wiki_key,
                      current=_current(rights.groups(site)))
    return held

def check_rights(site, wiki_key, mechanics):
    """The rights this task needs. -> None, or raises Refusal naming a group."""
    from tasks import registry
    from wiki import rights

    needed = registry.rights_for(mechanics)
    missing = rights.missing_rights(site, needed)
    if not missing:
        return
    reason = rights.explain_missing(site, missing, wiki_key)
    raise Refusal(reason.key, **reason.values)

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
        raise Refusal("refusal_no_fandom_account")
    try:
        ok, held = rights.is_wiki_staff(site, wiki_user)
    except Exception as e:
        raise Refusal("refusal_rights_unreadable", wiki=wiki_key, error=str(e))
    if ok:
        return
    raise Refusal("refusal_caller_no_standing", user=wiki_user, wiki=wiki_key,
                  current=_current(held),
                  groups=_groups(rights.STAFF_GROUPS))

def check_all(site, wiki_key, mechanics, requester):
    """Every check, in the order that costs the least. -> the bot's statuses."""
    if requester and requester.get("role") == SPONSOR:
        import db
        import sponsors
        if any(mechanic.standalone for mechanic in mechanics):
            raise Refusal("sponsor_standalone_disabled")
        owner = sponsors.canonical_id(requester["platform"], requester["id"])
        if not sponsors.can_use_wiki(owner, wiki_key):
            raise Refusal("sponsor_wiki_required", wiki=wiki_key)
        requester["wiki_user"] = db.wiki_claim(wiki_key)["wiki_user"]
    held = check_bot_standing(site, wiki_key)
    check_caller_standing(site, wiki_key, requester)
    check_rights(site, wiki_key, mechanics)
    return held
