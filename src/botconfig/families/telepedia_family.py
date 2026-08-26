from pywikibot import family

class Family(family.Family):
    name = 'telepedia'
    langs = {
        'uk': 'telepedia.fandom.com',
        'ru': 'telepedia.fandom.com',
    }

    def scriptpath(self, code):
        return {
            'uk': '/uk',
            'ru': '/ru',
        }[code]

    def protocol(self, code):
        return 'https'
