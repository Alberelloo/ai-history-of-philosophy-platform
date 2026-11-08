"""Требования спецификаций source-library и chapter-reading: интерфейс в браузере и журнал."""

from __future__ import annotations

import httpx
import pytest

from ..helpers import aside, reader_context, via_sidebar

req = pytest.mark.req
SL = "source-library"
CR = "chapter-reading"


def titles(page) -> list[str]:
    return page.locator(".source h2").all_inner_texts()


def open_library(page, site):
    page.goto(site.url + "/")
    page.wait_for_selector(".source")


# --- source-library -----------------------------------------------------------------


@req(SL, "Список источников")
def test_only_visible_sources_listed(page, site, events):
    hidden = site.registry.register(
        "operator",
        title="Ещё не опубликован",
        authors=["X"],
        language="ru",
        kind="textbook",
        scope="public",
        license=site.registry.get(site.ids["textbook"]).license,
        files=[{"name": "t", "path": "primary.txt"}],
    )
    open_library(page, site)
    shown = titles(page)
    assert set(shown) == {
        "История теории познания",
        "Critique of Pure Reason",
        "Философский словарь",
    }
    assert "Ещё не опубликован" not in shown
    assert events.of("library.sources.listed")[-1]["count"] == 3
    assert hidden


@req(SL, "Описание источника")
def test_source_description_and_missing_fields(page, site):
    open_library(page, site)
    dictionary = page.locator(".source", has_text="Философский словарь")
    text = dictionary.inner_text()
    assert "Коллектив авторов" in text and "русский" in text and "Справочное издание" in text
    assert "не указано" in text  # год неизвестен
    dictionary.get_by_role("button", name="Общественное достояние").click()
    link = dictionary.get_by_role("link", name="текст лицензии")
    assert link.get_attribute("href") == "https://example.org/public-domain"


def filter_menu(page, name: str):
    """Открывает выпадающий фильтр библиотеки: кнопка и окно со флажками."""
    main = page.get_by_role("main")
    button = main.get_by_role("button", name=name)
    if button.get_attribute("aria-expanded") != "true":
        button.click()
    return button, main.get_by_role("group", name=name, exact=True)


def count(page, n: int) -> None:
    page.wait_for_function(f"document.querySelectorAll('.source').length === {n}")


@req(SL, "Фильтр по виду источника")
def test_kind_filter(page, site):
    open_library(page, site)
    button, menu = filter_menu(page, "Вид")
    menu.get_by_label("Учебник").check()
    count(page, 1)
    assert titles(page) == ["История теории познания"]
    menu.get_by_label("Первоисточник").check()
    count(page, 2)
    assert "Философский словарь" not in titles(page)
    assert button.inner_text().split() == ["Вид", "·", "2"]  # число выбранных видов


@req(SL, "Фильтр по виду источника")
def test_several_kinds_in_one_request(site):
    """Учебник и первоисточник одним запросом через шлюз: в ответе оба, справочника нет."""
    response = httpx.get(
        site.url + "/api/v1/sources", params=[("kind", "textbook"), ("kind", "primary")]
    )
    assert response.status_code == 200
    titles = {s["title"] for s in response.json()["sources"]}
    assert titles == {"История теории познания", "Critique of Pure Reason"}
    three = httpx.get(
        site.url + "/api/v1/sources?kind=textbook&kind=primary&kind=reference&lang=ru&lang=en"
    ).json()["sources"]
    assert len(three) == 3


@req(SL, "Фильтр по виду источника")
def test_kind_filter_select_all_clear_all_and_closing(page, site):
    open_library(page, site)
    button, menu = filter_menu(page, "Вид")
    boxes = menu.get_by_role("checkbox")
    assert boxes.count() == 3
    menu.get_by_role("button", name="Выбрать все").click()
    assert all(boxes.nth(i).is_checked() for i in range(3))
    count(page, 3)  # все виды — все источники
    assert button.inner_text().split() == ["Вид", "·", "3"]
    assert menu.get_by_role("button", name="Выбрать все").is_disabled()
    menu.get_by_role("button", name="Снять все").click()
    assert not any(boxes.nth(i).is_checked() for i in range(3))
    count(page, 3)  # пустой выбор — тоже все
    assert button.inner_text().strip() == "Вид"
    # Esc закрывает окно и возвращает фокус на кнопку
    menu.get_by_label("Учебник").check()
    page.keyboard.press("Escape")
    assert menu.count() == 0
    assert button.evaluate("el => el === document.activeElement")
    # щелчок вне окна закрывает его, выбор сохраняется
    button.click()
    assert menu.is_visible() and menu.get_by_label("Учебник").is_checked()
    page.get_by_role("heading", name="Библиотека", exact=True).click()
    assert menu.count() == 0
    count(page, 1)
    assert button.inner_text().split() == ["Вид", "·", "1"]


@req(SL, "Фильтр по виду источника")
@req(SL, "Фильтр по языку")
@pytest.mark.parametrize("name", ["Вид", "Язык"])
@pytest.mark.parametrize("action", ["Выбрать все", "Снять все"])
def test_escape_after_select_all_and_clear_all(page, site, name, action):
    """Esc сразу после «Выбрать все» или «Снять все» закрывает окно, фокус — на кнопке фильтра.

    Кнопка, которая после нажатия стала неактивной, не теряет фокус: иначе Esc уходил бы
    в пустоту, а Tab начинал обход страницы сначала.
    """
    open_library(page, site)
    button, menu = filter_menu(page, name)
    select_all = menu.get_by_role("button", name="Выбрать все")
    clear_all = menu.get_by_role("button", name="Снять все")
    if action == "Снять все":
        select_all.click()
        page.wait_for_function(
            "() => [...document.querySelectorAll('.pg-filter-menu input')].every(i => i.checked)"
        )
    target = select_all if action == "Выбрать все" else clear_all
    target.click()
    # Кнопка теперь ничего не изменит: неактивна, но в фокусе (aria-disabled, не disabled).
    assert target.get_attribute("aria-disabled") == "true"
    assert target.evaluate("el => el === document.activeElement")
    page.keyboard.press("Escape")
    assert menu.count() == 0
    assert button.evaluate("el => el === document.activeElement")


@req(SL, "Фильтр по языку")
def test_language_filter_offers_available_languages(page, site):
    open_library(page, site)
    _, menu = filter_menu(page, "Язык")
    languages = menu.locator(".pg-filter-menu__option").all_inner_texts()
    assert sorted(languages) == ["английский", "русский"]
    assert menu.get_by_role("button", name="Выбрать все").is_visible()
    menu.get_by_label("английский").check()
    count(page, 1)
    assert titles(page) == ["Critique of Pure Reason"]


@req(SL, "Поиск по названию и автору")
def test_search_by_title_and_author(page, site, events):
    open_library(page, site)
    search = page.get_by_label("Поиск по названию и автору")
    one = "document.querySelectorAll('.source').length === 1"
    search.fill("асмус")
    page.wait_for_function(one)
    assert titles(page) == ["История теории познания"]
    search.fill("ФИЛОСОФСКИЙ СЛОВАРЬ")
    page.wait_for_selector(".source h2:text('Философский словарь')")
    page.wait_for_function(one)
    assert titles(page) == ["Философский словарь"]
    result = site.reading.sources(query="познан")  # часть слова: «познания»
    assert {s["title"] for s in result["sources"]} == {"История теории познания"}
    assert site.reading.sources(query="ёж")["sources"] == []
    from philograph.library.reading import _norm

    assert _norm("Учёный ЁЖ") == _norm("ученый еж")  # «е» и «ё» не различаются
    search.fill("")
    page.wait_for_function("document.querySelectorAll('.source').length === 3")
    assert events.where("library.sources.listed", query_length=5)


@req(SL, "Сочетание поиска и фильтров")
def test_search_and_filters_combined_and_reset(page, site):
    open_library(page, site)
    reset = page.locator(".filters").get_by_role("button", name="Сбросить поиск и фильтры")
    assert reset.is_disabled()  # сбрасывать нечего, но кнопка на месте
    _, menu = filter_menu(page, "Вид")
    menu.get_by_label("Первоисточник").check()
    page.get_by_label("Поиск по названию и автору").fill("kant")
    count(page, 1)
    assert titles(page) == ["Critique of Pure Reason"]
    assert reset.is_enabled()
    page.get_by_label("Поиск по названию и автору").fill("гегель")
    status = page.get_by_role("status")
    assert "Подходящих источников нет" in status.inner_text()
    status.get_by_role("button", name="Сбросить поиск и фильтры").click()
    count(page, 3)
    assert page.get_by_label("Поиск по названию и автору").input_value() == ""
    assert reset.is_disabled()
    _, menu = filter_menu(page, "Вид")
    assert not menu.get_by_label("Первоисточник").is_checked()


@req(SL, "Сочетание поиска и фильтров")
def test_search_width_constant(page, site):
    """Ширина поиска и место кнопки сброса не меняются при выборе фильтров и вводе запроса."""
    open_library(page, site)

    def measure():
        return page.evaluate("""() => {
            const search = document.querySelector('.filters__search').getBoundingClientRect();
            const reset = document.querySelector('.filters__reset').getBoundingClientRect();
            return {width: search.width, left: search.left, reset: reset.left, top: reset.top};
        }""")

    before = measure()
    _, menu = filter_menu(page, "Вид")
    menu.get_by_label("Учебник").check()
    menu.get_by_label("Первоисточник").check()
    page.keyboard.press("Escape")
    _, menu = filter_menu(page, "Язык")
    menu.get_by_label("русский").check()
    page.keyboard.press("Escape")
    page.get_by_label("Поиск по названию и автору").fill("история теории познания")
    count(page, 1)
    after = measure()
    assert after["width"] == before["width"] and after["left"] == before["left"], (before, after)
    assert after["top"] == before["top"]  # кнопка сброса не переехала на другую строку
    assert abs(after["reset"] - before["reset"]) <= 1, (before, after)


@req(SL, "Выбор источника для чтения")
def test_choose_source_makes_it_current(page, site):
    open_library(page, site)
    page.locator(".source", has_text="Critique").get_by_role("button", name="Читать").click()
    page.wait_for_selector(".chapter p")
    assert f"/read/{site.ids['primary']}" in page.url
    via_sidebar(page, "Библиотека")
    page.wait_for_selector(".source.current")
    current = page.locator(".source.current")
    assert "Critique of Pure Reason" in current.inner_text() and "Текущий" in current.inner_text()


@req(SL, "Учебник по умолчанию")
def test_default_textbook_on_first_visit(page, site):
    open_library(page, site)
    page.get_by_role("button", name="Перейти к чтению").click()
    page.wait_for_selector(".chapter p")
    assert f"/read/{site.ids['textbook']}" in page.url


@req(SL, "Запоминание выбранного источника")
def test_remembered_source_and_fallback(browser, site):
    context = reader_context(browser)
    page = context.new_page()
    open_library(page, site)
    page.locator(".source", has_text="Critique").get_by_role("button", name="Читать").click()
    page.wait_for_selector(".chapter p")
    page.goto(site.url + "/read")
    page.wait_for_selector(".chapter p")
    assert f"/read/{site.ids['primary']}" in page.url  # повторный визит

    site.registry.unpublish("operator", site.ids["primary"])
    try:
        page.goto(site.url + "/read")
        page.wait_for_selector(".notice")
        assert "Прежний источник недоступен" in page.locator(".notice").inner_text()
        assert f"/read/{site.ids['textbook']}" in page.url
    finally:
        site.registry.republish("operator", site.ids["primary"])
    other = reader_context(browser).new_page()  # другой браузер — своё хранилище
    other.goto(site.url + "/read")
    other.wait_for_selector(".chapter p")
    assert f"/read/{site.ids['textbook']}" in other.url
    context.close()


# --- chapter-reading ----------------------------------------------------------------


def open_textbook(page, site, suffix=""):
    page.goto(f"{site.url}/read/{site.ids['textbook']}{suffix}")
    page.wait_for_selector(".chapter p")


@req(CR, "Оглавление")
def test_toc_navigation_and_current_mark(page, site):
    open_textbook(page, site)
    toc = page.get_by_role("navigation", name="Оглавление")
    assert toc.locator("[aria-current=page]").inner_text() == "Глава 1. Опыт"
    toc.get_by_role("link", name="Глава 3. Разум").click()
    page.wait_for_selector("h1:text('Глава 3. Разум')")
    assert toc.locator("[aria-current=page]").inner_text() == "Глава 3. Разум"
    toc.get_by_role("link", name="Схематизм").click()
    page.wait_for_selector("h1:text('Глава 2. Рассудок')")
    heading = page.locator("h2", has_text="Схематизм")
    page.wait_for_function(
        "el => el.getBoundingClientRect().top < window.innerHeight", arg=heading.element_handle()
    )


@req(CR, "Текст главы")
def test_chapter_text_as_in_source(page, site, events):
    open_textbook(page, site)
    paragraphs = page.locator(".chapter p.block").all_inner_texts()
    assert paragraphs[0].startswith("Всякое знание начинается с опыта, говорит Кант.")
    served = events.of("library.chapter.served")[-1]
    assert served["source_id"] == site.ids["textbook"] and served["blocks"] == 42


@req(CR, "Переход между главами")
def test_previous_and_next(page, site):
    open_textbook(page, site)
    nav = page.get_by_role("navigation", name="Главы")
    assert nav.get_by_role("button", name="Предыдущая глава").count() == 0
    nav.get_by_role("button", name="Следующая глава").click()
    page.wait_for_selector("h1:text('Глава 2. Рассудок')")
    nav.get_by_role("button", name="Следующая глава").click()
    page.wait_for_selector("h1:text('Глава 3. Разум')")
    assert nav.get_by_role("button", name="Следующая глава").count() == 0


@req(CR, "Запоминание места чтения")
def test_reading_position_per_source(browser, site):
    context = reader_context(browser)
    page = context.new_page()
    open_textbook(page, site)
    page.get_by_role("link", name="Глава 2. Рассудок").click()
    page.wait_for_selector("h1:text('Глава 2. Рассудок')")
    target = page.locator("p.block", has_text="Схема 20 ")
    target.evaluate("el => el.scrollIntoView({block: 'start'})")
    page.mouse.wheel(0, 1)
    page.wait_for_timeout(400)
    saved = page.evaluate(
        f"JSON.parse(localStorage['philograph:v4']).positions['{site.ids['textbook']}']"
    )
    page.goto(f"{site.url}/read/{site.ids['primary']}")
    page.wait_for_selector(".chapter p")
    page.goto(f"{site.url}/read/{site.ids['textbook']}")
    page.wait_for_selector("h1:text('Глава 2. Рассудок')")
    # Видимое — ниже отступа прокрутки: туда абзац встаёт при возврате к месту.
    first_visible = page.evaluate("""() => {
        const top = parseFloat(getComputedStyle(document.documentElement).scrollPaddingTop) || 0;
        return [...document.querySelectorAll('p.block')]
            .find(p => p.getBoundingClientRect().bottom > top).dataset.paragraph;
    }""")
    assert first_visible == saved["paragraphId"]
    chapter_start = page.locator("p.block").first.get_attribute("data-paragraph")
    assert saved["paragraphId"] != chapter_start  # место в середине главы, а не её начало
    fresh = reader_context(browser).new_page()
    fresh.goto(f"{site.url}/read/{site.ids['reference']}")
    fresh.wait_for_selector(".chapter p")
    assert fresh.evaluate("window.scrollY") == 0  # первое открытие — с начала
    context.close()


@req(CR, "Ссылка на абзац")
def test_paragraph_link_opens_and_highlights(page, site, events):
    chapter, pid, _ = next(p for p in site.paragraphs("textbook") if "Схема 25" in p[2])
    page.goto(f"{site.url}/p/{pid}")
    page.wait_for_selector(f"#p-{pid}.highlight")
    assert "Схема 25" in page.locator(f"#p-{pid}").inner_text()
    assert events.where("library.paragraph.resolved", paragraph_id=pid, status="found")

    _, primary_pid, _ = site.paragraphs("primary")[0]
    page.goto(f"{site.url}/p/{primary_pid}")
    page.wait_for_selector(f"#p-{primary_pid}")
    assert site.ids["primary"] in page.url
    assert (
        page.evaluate("JSON.parse(localStorage['philograph:v4']).currentSource")
        == (site.ids["primary"])
    )

    page.locator(f"#p-{primary_pid}").hover()
    page.locator(f"#p-{primary_pid} .copy-link").click()
    copied = page.evaluate("navigator.clipboard.readText()")
    assert copied == f"{site.url}/p/{primary_pid}"
    assert chapter


@req(CR, "Устойчивость ссылок на абзацы")
def test_paragraph_links_survive_reprocessing(page, site):
    _, kept, _ = next(p for p in site.paragraphs("reference") if "Познание —" in p[2])
    old_version = site.registry.get(site.ids["reference"]).published_version
    site.pipeline.fetch = lambda spec: (
        "Статья «Познание»\n\nПознание — процесс постижения мира.\n"
    ).encode()
    site.registry.update_settings("operator", site.ids["reference"], note="v2")
    new_version = site.pipeline.start("operator", site.ids["reference"])
    site.registry.publish("operator", new_version)
    assert new_version != old_version
    page.goto(f"{site.url}/p/{kept}")
    page.wait_for_selector(f"#p-{kept}.highlight")

    _, gone, _ = next(p for p in site.paragraphs("reference") if "Статья" in p[2])
    site.pipeline.fetch = lambda spec: "Совсем другой словарь о логике.\n".encode()
    third = site.pipeline.start("operator", site.ids["reference"])
    site.registry.publish("operator", third)
    page.goto(f"{site.url}/p/{gone}")
    alert = page.get_by_role("alert")
    assert "Абзац не найден" in alert.inner_text()

    site.registry.unpublish("operator", site.ids["reference"])
    try:
        _, last, _ = site.paragraphs("textbook")[0]
        page.goto(f"{site.url}/p/{kept}")
        assert "Источник недоступен" in page.get_by_role("alert").inner_text()
        page.get_by_role("button", name="Перейти в библиотеку").click()
        page.wait_for_selector(".source")
        assert last
    finally:
        site.registry.republish("operator", site.ids["reference"])


@req(CR, "Страницы печатного издания")
def test_printed_page_numbers(page, site):
    open_textbook(page, site)
    marks = page.locator(".page-mark").all_inner_texts()
    assert marks[:2] == ["с. 41", "с. 42"]
    page.goto(f"{site.url}/read/{site.ids['primary']}")
    page.wait_for_selector(".chapter p")
    assert page.locator(".page-mark").count() == 0  # у TXT страниц нет — и не придумываем


@req(CR, "Сноски")
def test_footnote_popup_hover_keyboard_and_links(page, site):
    open_textbook(page, site)
    before = page.evaluate("window.scrollY")
    ref = page.locator(".note-ref").first
    ref.hover()
    popup = page.locator(".note-popup")
    assert "Критика чистого разума" in popup.inner_text()
    assert page.evaluate("window.scrollY") == before
    popup.hover()
    page.wait_for_timeout(300)
    assert popup.is_visible()  # окно не закрылось, пока указатель в нём
    assert popup.get_by_role("link").get_attribute("href") == "https://example.org/kant"
    aside(page)  # не 5,5: указатель в левом верхнем углу раскрыл бы боковую панель
    page.wait_for_timeout(400)
    assert page.locator(".note-popup").count() == 0
    ref.focus()
    assert "Критика чистого разума" in page.locator(".note-popup").inner_text()
