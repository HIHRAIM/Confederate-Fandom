"""Радиопедия на Fandom — radiopedia.fandom.com/ru.

Отдельное семейство, а не язык внутри telepedia: это другая вики, со своей
заглавной и своими классами карточек новостей (rp-news вместо tp-news).
"""
from pywikibot import family


class Family(family.Family):

    """Радиопедия на Fandom."""

    name = 'radiopedia'
    langs = {
        'ru': 'radiopedia.fandom.com',
    }

    def scriptpath(self, code):
        return '/ru'

    def protocol(self, code):
        return 'https'
