"""Тестовая вики HIHRAIM на Fandom — hihraim-test.fandom.com/ru.

Полигон, на котором обкатывается дизайн заглавной перед переносом на
русскую Телепедию Fandom (семейство `telepedia`, язык `ru`).
"""
from pywikibot import family


class Family(family.Family):

    """Вики-полигон HIHRAIM на Fandom."""

    name = 'hihraimtest'
    langs = {
        'ru': 'hihraim-test.fandom.com',
    }

    def scriptpath(self, code):
        return '/ru'

    def protocol(self, code):
        return 'https'
