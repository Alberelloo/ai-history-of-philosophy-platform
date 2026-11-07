"""chapter-reading в браузере: устаревшее место не выбрасывает из книги, необработанное видно.

Свой сервер на модуль (фикстура ``site`` в conftest): сценарии обрабатывают учебник заново и
добавляют источники, это не должно задевать другие модули.
"""

from __future__ import annotations

import json

import pytest

from ..helpers import reader_context
from ..library.builders import BODY, epub, pdf
from .conftest import TEXTBOOK_CHAPTERS

req = pytest.mark.req
CR = "chapter-reading"
KEY = "philograph:v4"
RENAMED = "Глава 2. Рассудок и его правила"


def stored(page) -> dict:
    return json.loads(page.evaluate(f"localStorage.getItem('{KEY}')") or "{}")


def first_visible(page) -> str:
    return page.evaluate("""() => {
        const top = parseFloat(getComputedStyle(document.documentElement).scrollPaddingTop) || 0;
        return [...document.querySelectorAll('p.block')]
            .find(p => p.getBoundingClientRect().bottom > top).dataset.paragraph;
    }""")


def republish_textbook(site, chapters) -> None:
    """Повторная обработка учебника с другим файлом: так меняются идентификаторы глав."""
    data = epub(chapters)
    site.pipeline.fetch = lambda spec: data
    version = site.pipeline.start("operator", site.ids["textbook"])
    assert site.registry.version(version)["state"] == "checked"
    site.registry.publish("operator", version)


@req(CR, "Запоминание места чтения")
def test_changed_chapter_keeps_reader_in_book(browser, site):
    """Регресс: место в главе, которую переименовали при обработке, — остаёмся в книге."""
    context = reader_context(browser)
    page = context.new_page()
    page.set_default_timeout(8000)
    textbook = site.ids["textbook"]
    page.goto(f"{site.url}/read/{textbook}")
    page.wait_for_selector(".chapter p")
    page.get_by_role("navigation", name="Оглавление").get_by_role(
        "link", name="Глава 2. Рассудок"
    ).click()
    page.wait_for_selector("h1:text('Глава 2. Рассудок')")
    target = page.locator("p.block", has_text="Схема 20 ")
    target.evaluate("el => el.scrollIntoView({block: 'start'})")
    page.mouse.wheel(0, 1)
    page.wait_for_timeout(400)
    saved = stored(page)["positions"][textbook]
    old_chapter = saved["chapterId"]

    chapters = [(RENAMED if t == "Глава 2. Рассудок" else t, body) for t, body in TEXTBOOK_CHAPTERS]
    republish_textbook(site, chapters)
    toc = {item["title"]: item for item in site.reading.toc(textbook)}
    assert old_chapter not in {item["id"] for item in toc.values()}

    page.goto(f"{site.url}/read/{textbook}")
    page.wait_for_selector(f"h1:text('{RENAMED}')")
    notice = page.get_by_role("status").filter(has_text="изменилась при обновлении книги")
    assert notice.is_visible()
    assert f"/read/{textbook}/{toc[RENAMED]['id']}" in page.url
    assert page.get_by_role("alert").count() == 0  # без полноэкранной ошибки
    page.wait_for_function(
        "id => document.querySelector(`#p-${id}`)?.classList.contains('highlight')",
        arg=saved["paragraphId"],
    )
    assert first_visible(page) == saved["paragraphId"]  # то же место, что до обновления
    page.wait_for_function(
        f"JSON.parse(localStorage['{KEY}']).positions['{textbook}'].chapterId"
        f" === '{toc[RENAMED]['id']}'"
    )  # сохранённое место обновлено

    # Ссылка на главу, которой больше нет: первая глава с уведомлением о ссылке.
    page.goto(f"{site.url}/read/{textbook}/{old_chapter}")
    page.wait_for_selector("h1:text('Глава 1. Опыт')")
    assert page.get_by_role("status").filter(has_text="Главы по этой ссылке нет").is_visible()

    # Ссылка на раздел внутри главы: глава раздела, прокрученная к нему.
    section = next(c for c in toc[RENAMED]["children"] if c["title"] == "Схематизм")
    page.goto(f"{site.url}/read/{textbook}/{section['id']}")
    page.wait_for_selector(f"h1:text('{RENAMED}')")
    page.wait_for_url(f"**/read/{textbook}/{toc[RENAMED]['id']}#s-{section['id']}")
    heading = page.locator(f"#s-{section['id']}")
    page.wait_for_function(
        "el => el.getBoundingClientRect().top >= 0"
        " && el.getBoundingClientRect().top < window.innerHeight / 2",
        arg=heading.element_handle(),
    )
    context.close()


@req(CR, "Необработанные части в тексте")
def test_placeholder_visible_in_chapter(browser, site):
    """Пустая страница PDF — плашка на своём месте в тексте, оформленная не как абзац."""
    sentence = "All our knowledge begins with experience, but it does not all arise from it."
    pages = [[(f"{sentence} Page {i}.", BODY) for _ in range(12)] for i in range(1, 12)]
    pages.insert(2, [])
    data = pdf(pages)
    site.pipeline.fetch = lambda spec: data
    source = site.registry.register(
        "operator",
        title="Scanned essay",
        authors=["J. Locke"],
        year=1690,
        language="en",
        kind="primary",
        license=site.registry.get(site.ids["primary"]).license,
        scope="public",
        files=[{"name": "s", "path": "scan.pdf"}],
        settings={"languages": ["en"]},
    )
    site.pipeline.ocr = None
    version = site.pipeline.start("operator", source)
    if site.registry.version(version)["state"] == "awaiting_quality":
        site.pipeline.decide_quality("operator", version, "accept")
    site.registry.publish("operator", version)

    context = reader_context(browser)
    page = context.new_page()
    page.set_default_timeout(8000)
    page.goto(f"{site.url}/read/{source}")
    placeholder = page.locator(".chapter .unrendered")
    placeholder.wait_for()
    text = placeholder.inner_text().lower()
    assert "не передано в тексте" in text and "страница 3: текст не распознан" in text
    # на месте страницы: после текста второй страницы, перед текстом третьей
    before = placeholder.locator("xpath=preceding-sibling::p[1]").inner_text()
    after = placeholder.locator("xpath=following-sibling::p[1]").inner_text()
    assert "Page 2." in before and "Page 3." in after
    # плашка со значком и тёплой подложкой, шрифт интерфейса, а не абзац источника
    assert placeholder.locator("svg.unrendered__icon").count() == 1
    style = placeholder.evaluate(
        "el => { const s = getComputedStyle(el); const p = getComputedStyle("
        "document.querySelector('p.block'));"
        " return [s.backgroundColor, s.borderStyle, s.fontFamily, p.backgroundColor,"
        " getComputedStyle(document.documentElement).getPropertyValue('--generated-tint')]; }"
    )
    assert style[1] == "dashed" and style[2].startswith("Onest") and style[0] != style[3]
    context.close()
