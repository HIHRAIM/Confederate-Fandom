"""Семейство pokemon.fandom.com — все языковые разделы, нужные проекту.

Заменяет урезанное семейство из ``core/pywikibot/families/pokemon_family.py``
(там только ``ru``). Подключается из скриптов так:

    pywikibot.config.register_families_folder(<эта папка>)

до создания первого ``Site`` — ``register_families_folder`` перезаписывает
запись по имени файла, поэтому ``core`` трогать не нужно.

Английский раздел лежит в корне (``/wiki/``), остальные — в подкаталоге по
коду языка (``/ru/wiki/``, ``/pt-br/wiki/`` и т. д.).
"""
from pywikibot import family

class Family(family.Family):

    name = 'pokemon'

    langs = {code: 'pokemon.fandom.com' for code in (
        'en',
        'ru', 'uk',
        'bg', 'ca', 'da', 'de', 'es', 'nl', 'no', 'pt-br', 'tr', 'vi',
    )}

    def scriptpath(self, code):
        return '' if code == 'en' else f'/{code}'

    def protocol(self, code):
        return 'HTTPS'
