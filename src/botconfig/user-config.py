"""Pywikibot's own configuration, kept inside the bot's tree.

wiki/site.py points PYWIKIBOT_DIR at this directory before importing
pywikibot, so the login cookies, the API cache and the throttle bookkeeping
land here instead of in the user's global Pywikibot installation, and this
bot's account never leaks into another project's config.

No secrets here: the account name is set from config.py at runtime and the
password comes from .env, so `password_file` stays unset — a value in it would
make Pywikibot look for credentials on disk instead.

The family named below is only Pywikibot's default, which it insists on
having: the bot builds a Site per wiki of config.WIKIS and never relies on it.
"""
family = 'hihraimtest'
mylang = 'ru'
put_throttle = 1
maxlag = 5
console_encoding = 'utf-8'
