"""Asking a bot administrator whether a repeating run may start.

A repeating run works on somebody's wiki every hour or every night for as
long as nobody stops it, so one set up by a wiki administrator does not start
by itself: it is written disabled (db/schedules.py: PENDING) and a message
goes to the Discord log channels, pinging the first bot administrator
config.py names on Discord, with two buttons. Yes starts it; no deletes it
and tells the person who asked, privately. `config.SCHEDULE_APPROVAL = False`
turns the whole step off, and a bot administrator's own schedules never need
it.

The one message in the log channels that mentions somebody. The rule there is
never to ping (tasks/notify.py), because a log that pings every quarter of an
hour is a log people mute; a question that waits for one person's answer is
the exception the rule is for.

**The buttons outlive the process.** They are `DynamicItem`s: Discord sends
back the custom id — `sched:approve:<id>` or `sched:reject:<id>` — and the
bot rebuilds the button from it, so a question asked before a restart is
still answered after one. The decision is checked against the row, not the
message: a schedule already decided says so, whichever copy of the question
was pressed.

Registers no command and no event, so the handler counts stay as they are.
"""
import logging

import discord

from discord_bot.client import client

logger = logging.getLogger("fd.discord.approvals")

APPROVE = "approve"
REJECT = "reject"

class Decision(discord.ui.DynamicItem[discord.ui.Button],
               template=r"sched:(?P<action>approve|reject):(?P<id>[0-9]+)"):
    """One of the two buttons under an approval request."""

    def __init__(self, action, schedule_id, lang=None):
        """The button for one action on one schedule."""
        from utils import DEFAULT_LANG, localized

        label = localized("schedule_button_" + action, lang or DEFAULT_LANG)
        style = (discord.ButtonStyle.success if action == APPROVE
                 else discord.ButtonStyle.danger)
        super().__init__(discord.ui.Button(
            label=label, style=style,
            custom_id="sched:{}:{}".format(action, int(schedule_id))))
        self.action = action
        self.schedule_id = int(schedule_id)

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        """Rebuild the button from what Discord sent back."""
        return cls(match["action"], int(match["id"]))

    async def callback(self, interaction):
        """A bot administrator pressed it: decide, and say so everywhere."""
        await decide(interaction, self.action, self.schedule_id)

client.add_dynamic_items(Decision)

def _log_channels():
    """The Discord channels of config.SERVICE_CHATS, as numbers."""
    from tasks import notify
    from utils import service_chat_keys

    out = []
    for key in service_chat_keys():
        target = notify.parse_chat(key)
        if target and target[0] == "discord":
            out.append(target[1])
    return out

def _describe(row, lang):
    """The request, as the log channel reads it."""
    import db
    from tasks import access, dialog
    from utils import localized

    requester = {"name": row["created_by_name"], "id": row["created_by_id"],
                 "wiki_user": row["created_by_wiki_user"]}
    summary = (db.schedule_params(row).get("summary") or "").strip()
    return localized(
        "schedule_approval_request", lang, id=row["id"],
        who=access.describe(requester, lang), platform=row["created_by_platform"],
        wiki=row["wiki"], mechanics=", ".join(db.schedule_mechanics(row)),
        when=dialog.describe_schedule(row, lang),
        summary=summary or localized("schedule_summary_by_bot", lang))

async def request(schedule_id):
    """Post the question with its buttons. -> whether any channel took it."""
    import db
    from utils import first_admin, service_lang

    row = db.get_schedule(schedule_id)
    channels = _log_channels()
    if row is None or not channels:
        logger.warning("schedule %s waits for approval, but there is no Discord "
                       "log channel to ask in", schedule_id)
        return False
    lang = service_lang()
    admin = first_admin("discord")
    text = ("<@{}> ".format(admin) if admin else "") + _describe(row, lang)
    view = discord.ui.View(timeout=None)
    view.add_item(Decision(APPROVE, schedule_id, lang))
    view.add_item(Decision(REJECT, schedule_id, lang))

    from discord_bot.client import _channel

    sent = False
    for channel_id in channels:
        channel = await _channel(channel_id)
        if channel is None:
            continue
        try:
            await channel.send(text[:1900], view=view,
                               allowed_mentions=discord.AllowedMentions(
                                   users=True, roles=False, everyone=False))
            sent = True
        except Exception as e:
            logger.warning("could not ask for approval in %s: %s", channel_id, e)
    return sent

async def decide(interaction, action, schedule_id):
    """Approve or reject one schedule, for a bot administrator only.

    The message loses its buttons and says who decided; the person who asked
    is told in a private message, in their own language, or in the chat they
    asked from when a private message cannot be delivered.
    """
    import db
    from tasks import dialog, notify
    from utils import is_admin, lang_of, localized, service_lang

    presser = lang_of("discord", interaction.user.id)
    if not is_admin("discord", interaction.user.id):
        await interaction.response.send_message(localized("not_admin", presser),
                                                ephemeral=True)
        return
    if action == APPROVE:
        row = db.approve_schedule(schedule_id)
    else:
        row = db.reject_schedule(schedule_id)
    if row is None:
        await interaction.response.send_message(
            localized("schedule_already_decided", presser, id=schedule_id),
            ephemeral=True)
        return

    lang = service_lang()
    verdict = localized("schedule_approved_by" if action == APPROVE
                        else "schedule_rejected_by", lang,
                        who=interaction.user.mention)
    content = (interaction.message.content if interaction.message else "")
    try:
        await interaction.response.edit_message(
            content="{}\n\n{}".format(content, verdict)[:1990], view=None,
            allowed_mentions=discord.AllowedMentions.none())
    except Exception as e:
        logger.warning("could not update the approval message: %s", e)

    reader = lang_of(row["created_by_platform"], row["created_by_id"])
    text = localized(
        "schedule_approved" if action == APPROVE else "schedule_rejected",
        reader, id=schedule_id, wiki=row["wiki"],
        mechanics=", ".join(db.schedule_mechanics(row)),
        when=dialog.describe_schedule(row, reader))
    await notify.to_person(row["created_by_platform"], row["created_by_id"],
                           text, fallback=row["reply_chat"])
    logger.info("schedule %s %s by %s", schedule_id,
                "approved" if action == APPROVE else "rejected",
                interaction.user.id)
