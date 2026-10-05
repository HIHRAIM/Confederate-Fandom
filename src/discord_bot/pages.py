"""Long answers as paginated embeds, with arrows under them.

Nineteen mechanics, or every scheduled run, or the whole of `/help` does not
belong in one message. Discord cuts a plain message at 2000 characters, and
long before that a person has stopped reading a wall of text with the
technical names buried in it. So a long answer becomes an embed: a title, one
page of the list, a footer saying which page this is, and two buttons. It is
here rather than in the command modules for the ordinary reason: `/tasks`,
`/jobs`, `/schedule` and `/help` all want it, and three copies of it would
drift.

The pages are built once and held by the view. Pressing an arrow only moves
between them; nothing here goes back to the database, so the list a person
pages through is the list they were shown, and the page they are on cannot
change under them because a task finished.

A view belongs to whoever ran the command. Somebody else pressing is told so
rather than moving that person's page, and after DIALOG_TIMEOUT the view stops
answering and Discord greys the buttons out on its own.

One page means no buttons at all. The arrows exist because the text does not
fit, and a lone «1 / 1» with two dead arrows under it is worse than nothing.

Not this module's zone: what the lists say (`tasks/lists.py`).
"""
import logging
import types

import discord
from discord import ButtonStyle, ui

from discord_bot.dialogs import DIALOG_TIMEOUT
from utils import localized, paginate

logger = logging.getLogger("fd.discord.pages")

EMBED_COLOR = 0x3B7DD8

TITLE_LIMIT = 256

DESCRIPTION_LIMIT = 4096

def esc(text):
    """Text that has to survive Discord's markdown as it was written."""
    return discord.utils.escape_markdown(str(text))

def code(text):
    """One technical name, as monospace: `replace`.

    A backtick inside would end the span and spill the rest of the line into
    code, so it is replaced rather than escaped — these are wiki keys and
    mechanic codes, and none of them has ever contained one."""
    return "`{}`".format(str(text).replace("`", "'"))

def bold(text):
    """One name, as the eye's first stop on the line."""
    return "**{}**".format(discord.utils.escape_markdown(str(text)))

MARKUP = types.SimpleNamespace(code=code, bold=bold, esc=esc)
"""This half's three formatters, in the shape `tasks/lists.py` takes."""

def embed(title, pages, index, lang):
    """One page as an embed. The footer appears only when there is more than
    one page — on a single-page answer it would be noise."""
    built = discord.Embed(title=str(title)[:TITLE_LIMIT],
                          description=pages[index][:DESCRIPTION_LIMIT],
                          color=discord.Color(EMBED_COLOR))
    if len(pages) > 1:
        built.set_footer(text=localized("page_of", lang, page=index + 1,
                                        total=len(pages)))
    return built

class _PagedView(ui.View):
    """The two arrows under a paginated answer, for one person."""

    def __init__(self, lang, title, pages, user_id):
        """Build the arrows and start on the first page."""
        super().__init__(timeout=DIALOG_TIMEOUT)
        self.lang = lang
        self.title = title
        self.pages = pages
        self.user_id = user_id
        self.index = 0
        self.prev = ui.Button(label=localized("page_prev", lang),
                              style=ButtonStyle.secondary)
        self.next = ui.Button(label=localized("page_next", lang),
                              style=ButtonStyle.secondary)
        self.prev.callback = self._make_cb(-1)
        self.next.callback = self._make_cb(1)
        self.add_item(self.prev)
        self.add_item(self.next)
        self._sync()

    def _sync(self):
        """Grey out the arrow that has nowhere to go."""
        self.prev.disabled = self.index == 0
        self.next.disabled = self.index >= len(self.pages) - 1

    def _make_cb(self, step):
        """One arrow's callback, closing over which way it steps."""
        async def callback(interaction: discord.Interaction):
            """Turn a page for the person who ran the command, and nobody else."""
            if interaction.user.id != self.user_id:
                await interaction.response.send_message(
                    localized("page_not_yours", self.lang), ephemeral=True)
                return
            self.index = max(0, min(len(self.pages) - 1, self.index + step))
            self._sync()
            await interaction.response.edit_message(
                embed=embed(self.title, self.pages, self.index, self.lang),
                view=self)
        return callback

async def send(interaction, title, lines, lang, ephemeral=False):
    """Answer an interaction with a paginated embed.

    The view is only attached when there is a second page to go to, and it is
    passed as a keyword that is simply absent otherwise: discord.py tells "no
    view" from "a view" by the argument being missing, not by it being None.
    """
    pages = paginate(lines)
    payload = {"embed": embed(title, pages, 0, lang), "ephemeral": ephemeral}
    if len(pages) > 1:
        payload["view"] = _PagedView(lang, title, pages, interaction.user.id)
    await interaction.response.send_message(**payload)
