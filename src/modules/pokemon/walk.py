"""Ходить по статьям вики и приводить названия видов покемонов к стандарту.

Одна точка входа — `run(family, lang, summary, ...)`, и она блокирующая от
начала до конца, как всё в Pywikibot: планировщик запускает её в рабочем
потоке (`asyncio.to_thread`), одну задачу за раз.

Что делает проход. Берёт все страницы основного пространства имён вместе с
текстом (одним запросом на пачку, иначе восемь тысяч страниц превращаются в
восемь тысяч запросов), прогоняет каждую через `rules.fix_text` и сохраняет
только те, где текст действительно изменился. Правка помечается флагом бота —
как и всё, что бот пишет, — и несёт описание из config.SPECIES_SUMMARY.

Чего проход не делает. Не переименовывает страницы: переезд заголовка тянет
за собой перенаправления, ссылки и категории, и это отдельная задача с другой
ценой ошибки. Не трогает перенаправления — их текст и есть цель ссылки. Не
исправляет то, что рядом с правилом, но им не является: «Глайгермен»,
«Троупринт», «Брианна» остаются как есть и попадают в отчёт (`derived`),
как и формы, которых нет в таблице окончаний (`unknown`) — их правит человек.
"""
import logging

from modules.pokemon import rules

logger = logging.getLogger("fd.species")

REPORT_LIMIT = 20

def run(site, summary, limit=0, dry_run=False, progress_every=500):
    """Пройти по статьям и исправить названия; вернуть отчёт о проходе.

    `limit` больше нуля обрезает проход после стольких *проверенных* страниц —
    это для ручной пробы, а не для расписания. `dry_run` считает всё то же
    самое, но ничего не сохраняет.

    Отчёт: сколько страниц просмотрено и сколько сохранено, сколько всего
    замен, а также непонятные формы и производные слова — по нескольку
    примеров, чтобы отчёт можно было отправить в служебный чат целиком."""
    import pywikibot

    checked = edited = replaced = failed = 0
    unknown, derived, pages = [], [], []

    for page in site.allpages(namespace=0, filterredir=False, content=True):
        checked += 1
        if limit and checked > limit:
            break
        if progress_every and checked % progress_every == 0:
            logger.info("названия покемонов: просмотрено %s страниц, исправлено %s",
                        checked, edited)

        text = page.text or ""
        if not rules.PREFILTER.search(text):
            continue

        new_text, changes, unknown_forms = rules.fix_text(text)
        for form in unknown_forms:
            if form not in unknown:
                unknown.append(form)
        for word in rules.find_derived(text):
            if word not in derived:
                derived.append(word)
        if not changes or new_text == text:
            continue

        replaced += len(changes)
        pages.append(page.title())
        if dry_run:
            edited += 1
            continue

        page.text = new_text
        try:
            page.save(summary=summary, minor=False, bot=True, apply_cosmetic_changes=False)
            edited += 1
        except Exception as e:
            failed += 1
            logger.warning("страница %s не сохранена: %s", page.title(), e)

    logger.info("названия покемонов: просмотрено %s, исправлено %s, замен %s, ошибок %s",
                checked, edited, replaced, failed)
    return {
        "checked": checked,
        "edited": edited,
        "replaced": replaced,
        "failed": failed,
        "pages": pages[:REPORT_LIMIT],
        "unknown": unknown[:REPORT_LIMIT],
        "derived": derived[:REPORT_LIMIT],
    }
