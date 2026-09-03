"""The wiki half of the bot, as a package.

Import order matters here for one reason only: wiki/site.py sets PYWIKIBOT_DIR
before it imports pywikibot, so it must be the first module of the package to
be imported. Everything else reaches the library through it.

The re-exports are the package's public API — `apply_plan` is the whole of it
for the publisher, `get_site` for anything that needs to ask the wiki a
question of its own.
"""
from wiki.site import (
    forget_sessions,
    get_site,
    has_bot_right,
    is_signed_in,
    use_cookies,
)
from wiki.families import ensure_family, known_families, parse_target
from wiki.rights import (
    groups,
    is_wiki_staff,
    may_work,
    missing_rights,
    needed_groups,
    user_groups,
)
from wiki.pages import apply_plan, edit_template, upload_file
