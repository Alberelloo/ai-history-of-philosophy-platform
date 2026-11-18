"""Синхронологическая карта раздела в браузере (openspec/changes/synchro-map, задача 7.2).

Сервер библиотеки из ``conftest.py`` сервиса знаний не поднимает, поэтому карта открывается
с набором ``?fixture=dense`` (``web/src/map/fixture.ts``: 41 персона, 64 труда, 50 влияний,
14 событий, 4 эпохи, 12 групп) — он не требует сервиса. Ответы ``GET /v1/map`` для пустой
карты, карты без связей и «показана часть» подменяются в браузере (``page.route``).

Проверяется клиент: выбор и цвета принадлежности, приглушение, фильтры и поиск, панель,
линзы и окно времени, кадр 16:9, пунктир достроенных связей, сцена в тёмной теме,
подписи без наложений. Сервис карты — ``tests/knowledge/test_map.py``.
"""

from __future__ import annotations

import itertools
import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import expect

from ..e2e import visual
from ..helpers import reader_context

req = pytest.mark.req
KG = "knowledge-graph"
VD = "visual-design"

DENSE = "fixture=dense"
TOTAL_PEOPLE = 41
EMPIRICISM = {"bacon", "hobbes", "gassendi", "locke", "berkeley", "hume", "condillac"}
RATIONALISM = {"descartes", "spinoza", "malebranche", "leibniz", "wolff", "arnauld", "baumgarten"}
ENCYCLOPEDIA = "e8"  # «Энциклопедия», 1751
MAP_API = "**/api/knowledge/v1/map*"
# Стол вокруг листа рисуется SVG-фильтрами: в программном рендере кадр небыстрый.
expect.set_options(timeout=15000)


# --- открытие карты ---------------------------------------------------------------------


def settle(page) -> None:
    """Шрифты загружены, раскладка пересчитана после них (два кадра)."""
    page.evaluate("document.fonts.ready.then(() => true)")
    page.evaluate(
        "new Promise(r => requestAnimationFrame(() => requestAnimationFrame(() => r(true))))"
    )


def open_map(browser, site, path: str = "/graph", query: str = DENSE, **options):
    """Контекст и страница карты; ``query`` без ``?``."""
    options.setdefault("viewport", {"width": 1920, "height": 1080})
    context = reader_context(browser, **options)
    page = context.new_page()
    page.set_default_timeout(8000)
    page.goto(f"{site.url}{path}{'?' + query if query else ''}")
    page.locator(".map-canvas, .map-empty").first.wait_for()
    settle(page)
    return context, page


def person(page, pid: str):
    return page.locator(f".map-person[data-person='{pid}']")


def role_of(page, pid: str) -> str | None:
    """Цвет принадлежности персоны: self, teacher, student, c1…c6, other или None."""
    cls = person(page, pid).get_attribute("class") or ""
    found = re.search(r"map-role-(\w+)", cls)
    return found.group(1) if found else None


def is_dim(page, pid: str) -> bool:
    return "is-dim" in (person(page, pid).get_attribute("class") or "").split()


def roles(page) -> dict[str, str]:
    return page.evaluate(
        """() => Object.fromEntries([...document.querySelectorAll('.map-person')]
            .map(e => [e.dataset.person,
                       (e.getAttribute('class').match(/map-role-(\\w+)/) || [])[1]])
            .filter(([, r]) => r))"""
    )


def lifespans(page) -> dict[str, tuple[int, int]]:
    """Годы жизни показанных персон — из подписи для чтения экрана «Имя, 1724–1804»."""
    labels = page.evaluate(
        "() => [...document.querySelectorAll('.map-person')]"
        ".map(e => [e.dataset.person, e.getAttribute('aria-label')])"
    )
    out = {}
    for pid, label in labels:
        birth, death = re.search(r"(-?\d+)–(-?\d+)$", label).groups()
        out[pid] = (int(birth), int(death))
    return out


def work_labels(page) -> list[str]:
    return page.locator(".map-work").evaluate_all(
        "els => els.map(e => e.getAttribute('aria-label'))"
    )


def address(page) -> tuple[str, dict[str, str]]:
    url = urlparse(page.url)
    return url.path, {k: v[0] for k, v in parse_qs(url.query).items()}


def facet(page, title: str):
    """Раздел фильтров по заголовку; раскрывается, если свёрнут."""
    details = page.locator(".map-facet").filter(
        has=page.locator("summary", has_text=re.compile(f"^{title}"))
    )
    if details.get_attribute("open") is None:
        details.locator("summary").click()
    return details


def check(page, facet_title: str, label: str) -> None:
    facet(page, facet_title).locator(".map-check", has_text=label).locator("input").check()


def set_window(page, start: int, end: int) -> None:
    years = facet(page, "Время").locator(".map-year")
    for field, value in ((years.nth(0), start), (years.nth(1), end)):
        field.fill(str(value))
        field.press("Enter")


def life_box(page, pid: str) -> dict:
    return person(page, pid).locator(".map-person__life").bounding_box()


def map_payload(**extra) -> dict:
    base = {
        "range": [1700, 1800],
        "truncated": False,
        "limit": 400,
        "people": [],
        "works": [],
        "events": [],
        "eras": [],
        "groups": [],
        "links": [],
        "undated": [],
    }
    base.update(extra)
    return base


def kant_alone() -> dict:
    """Карта из одной персоны без связей: «Выбрано» должно сказать, что связей пока нет."""
    return map_payload(
        people=[
            {
                "id": "kant",
                "label": "Иммануил Кант",
                "short": "Кант",
                "birth": 1724,
                "death": 1804,
                "precision": "year",
                "roles": ["philosopher"],
                "weight": 5,
            }
        ],
        works=[
            {
                "id": "kcpr",
                "label": "Критика чистого разума",
                "type": "work",
                "kind": "work",
                "year": 1781,
                "author": "kant",
                "weight": 8,
            }
        ],
    )


# --- выбор ------------------------------------------------------------------------------


@req(KG, "Выбор на карте")
def test_kant_selected_colours_teachers_students_and_removes_foreign_works(browser, site):
    context, page = open_map(browser, site)
    try:
        total_works = page.locator(".map-work").count()
        assert total_works > 20  # без выбора видны труды всех
        person(page, "kant").locator(".map-person__name").click()
        settle(page)
        assert address(page)[0] == "/graph/kant"
        colours = roles(page)
        assert colours["kant"] == "self"
        assert colours["hume"] == colours["wolff"] == "teacher"
        assert colours["fichte"] == "student"
        # Учителя и ученики — разными цветами; цвет — значение токена палитры выбора.
        palette = page.evaluate(
            """() => ['kant', 'hume', 'fichte'].map(id => getComputedStyle(
                document.querySelector(`.map-person[data-person=${id}] .map-person__life`)).fill)"""
        )
        assert len(set(palette)) == 3, palette
        # Труды — только Канта, цветом выбранного.
        labels = work_labels(page)
        assert labels and len(labels) < total_works
        assert all(label.endswith("— Иммануил Кант") for label in labels), labels
        assert all(
            "map-role-self" in c
            for c in page.locator(".map-work").evaluate_all(
                "els => els.map(e => e.getAttribute('class'))"
            )
        )
        # Линии — только в страте людей: между стратами линий нет.
        assert page.locator("svg[data-part='people'] .map-thread").count() >= 8
        assert (
            page.locator(
                "svg[data-part='top'] .map-thread, svg[data-part='bottom'] .map-thread"
            ).count()
            == 0
        )
        # Несвязанные приглушены, но читаемы и выбираемы.
        assert is_dim(page, "locke") and role_of(page, "locke") is None
        name = person(page, "locke").locator(".map-person__name")
        assert page.evaluate(
            "el => getComputedStyle(el).pointerEvents !== 'none'"
            " && parseFloat(getComputedStyle(el.closest('g')).opacity) === 1",
            name.element_handle(),
        )
        selected = page.locator(".map-selected")
        expect(selected).to_contain_text("Иммануил Кант")
        expect(selected).to_contain_text("Учителя:")
        expect(selected).to_contain_text("Ученики:")
        expect(selected.get_by_role("button", name="Открыть карточку")).to_be_visible()
        expect(selected.get_by_role("button", name="Достроить связи")).to_be_visible()
        # Переключение на приглушённого.
        name.click()
        settle(page)
        assert address(page)[0] == "/graph/locke"
        assert role_of(page, "locke") == "self" and not is_dim(page, "locke")
        expect(selected).to_contain_text("Джон Локк")
    finally:
        context.close()


@req(KG, "Выбор на карте")
def test_event_selection_colours_living_participants(browser, site):
    context, page = open_map(browser, site)
    try:
        page.locator(f".map-event[data-entity='{ENCYCLOPEDIA}']").click()
        settle(page)
        assert address(page)[0] == f"/graph/{ENCYCLOPEDIA}"
        colours = roles(page)
        own = {pid: r for pid, r in colours.items() if re.fullmatch(r"c[1-6]", r)}
        assert 1 <= len(own) <= 6, colours
        assert len(set(own.values())) == len(own)  # каждому — свой цвет
        years = lifespans(page)
        for pid in colours:
            birth, death = years[pid]
            assert birth <= 1751 <= death, (pid, years[pid])
        for label in work_labels(page):
            year = int(re.search(r"», (-?\d+)", label).group(1))
            assert 1741 <= year <= 1761, label
        expect(page.locator(".map-selected")).to_contain_text("Энциклопедия")
    finally:
        context.close()


@req(KG, "Выбор на карте")
def test_escape_and_empty_field_clear_selection(browser, site):
    context, page = open_map(browser, site, "/graph/kant")
    try:
        assert role_of(page, "kant") == "self"
        page.keyboard.press("Escape")
        settle(page)
        assert address(page)[0] == "/graph"
        assert not roles(page) and page.locator(".map-person.is-dim").count() == 0
        # Клавиатура: Enter на ленте выбирает.
        person(page, "hume").focus()
        page.keyboard.press("Enter")
        settle(page)
        assert address(page)[0] == "/graph/hume"
        # Щелчок по пустому полю (у оси, правый край) снимает выбор.
        bottom = page.locator("svg[data-part='bottom']").bounding_box()
        page.mouse.click(bottom["x"] + bottom["width"] - 3, bottom["y"] + bottom["height"] - 3)
        settle(page)
        assert address(page)[0] == "/graph"
    finally:
        context.close()


# --- фильтры, поиск, адрес --------------------------------------------------------------


@req(KG, "Фильтры и поиск карты")
def test_directions_and_window_show_n_of_m_and_repack(browser, site):
    context, page = open_map(browser, site)
    try:
        lanes_before = len({round(b["y"]) for b in _life_boxes(page)})
        check(page, "Направление", "Эмпиризм")
        check(page, "Направление", "Рационализм")
        set_window(page, 1630, 1800)
        settle(page)
        shown = page.locator(".map-person").evaluate_all("els => els.map(e => e.dataset.person)")
        assert shown and set(shown) <= EMPIRICISM | RATIONALISM
        years = lifespans(page)
        assert all(death >= 1630 and birth <= 1800 for birth, death in years.values())
        text = page.locator(".map-shown").inner_text()
        found = re.match(r"Показано (\d+) из (\d+)", text)
        assert found, text
        assert int(found.group(1)) == len(shown) and int(found.group(2)) == TOTAL_PEOPLE
        # Дорожки перепакованы: занятые идут подряд от верха страты с одним шагом.
        lanes = sorted({round(b["y"]) for b in _life_boxes(page)})
        assert len(lanes) < lanes_before
        steps = {b - a for a, b in itertools.pairwise(lanes)}
        assert len(steps) <= 1 or max(steps) - min(steps) <= 1, lanes
        people_top = page.locator(".map-people").bounding_box()["y"]
        step = min(steps) if steps else 40
        assert lanes[0] - people_top <= step + 10, (lanes[0], people_top, step)
        # Состояние — в адресе; обновление страницы его сохраняет.
        query = address(page)[1]
        assert query["groups"].split(",") == ["g-emp", "g-rat"]
        assert (query["from"], query["to"]) == ("1630", "1800")
        page.reload()
        page.locator(".map-canvas").wait_for()
        settle(page)
        assert sorted(
            page.locator(".map-person").evaluate_all("els => els.map(e => e.dataset.person)")
        ) == sorted(shown)
        # Сбросить — снова все.
        page.locator(".map-panel").get_by_role("button", name="Сбросить").first.click()
        expect(page.locator(".map-person")).to_have_count(TOTAL_PEOPLE)
    finally:
        context.close()


def _life_boxes(page) -> list[dict]:
    return page.locator(".map-person__life").evaluate_all(
        "els => els.map(e => { const r = e.getBoundingClientRect();"
        " return {x: r.x, y: r.y, w: r.width, h: r.height}; })"
    )


@req(KG, "Фильтры и поиск карты")
@req(KG, "Пометка достроенного")
def test_only_verified_hides_generated_links(browser, site):
    context, page = open_map(browser, site, "/graph/kant")
    try:
        assert page.locator(".map-thread[data-generated='true']").count() >= 1
        assert role_of(page, "rousseau") == "teacher"  # Руссо → Кант достроена моделью
        check(page, "Связи", "Только проверенные")
        settle(page)
        assert page.locator(".map-thread[data-generated='true']").count() == 0
        assert page.locator(".map-thread").count() >= 1  # проверенные остались
        assert role_of(page, "rousseau") is None
        assert address(page)[1].get("verified") == "1"
    finally:
        context.close()


@req(KG, "Фильтры и поиск карты")
def test_search_groups_hints_and_selects(browser, site):
    context, page = open_map(browser, site)
    try:
        field = page.locator(".map-search input")
        field.fill("крит")
        listbox = page.locator(".map-search__list")
        works = listbox.get_by_role("group", name="Труды")
        expect(works).to_contain_text("Критика чистого разума")
        expect(listbox.get_by_role("group", name="Эпохи и направления")).to_contain_text(
            "Критицизм"
        )
        assert address(page)[1].get("q") == "крит"
        works.get_by_role("option", name=re.compile("Критика чистого разума")).click()
        settle(page)
        primary = page.locator(".map-work.is-primary")
        expect(primary).to_have_count(1)
        assert "Критика чистого разума" in primary.get_attribute("aria-label")
        assert address(page)[0].startswith("/graph/w")
        # Найденное, но скрытое фильтром, помечено; выбор подсказки снимает мешающий фильтр.
        check(page, "Направление", "Эмпиризм")
        field.fill("Кант")
        row = page.locator(".map-search__row", has_text="Иммануил Кант")
        expect(row).to_contain_text("скрыт фильтром")
        row.click()
        settle(page)
        assert role_of(page, "kant") == "self"
        # Без даты: не на оси, но находится с пометкой.
        field.fill("Врожд")
        expect(page.locator(".map-search__row", has_text="Врождённые идеи")).to_contain_text(
            "без даты"
        )
        assert page.locator("[data-entity='u-innate']").count() == 0
    finally:
        context.close()


# --- панель -----------------------------------------------------------------------------


@req(KG, "Панель карты")
def test_panel_collapses_to_rail_and_is_remembered(browser, site):
    context, page = open_map(browser, site, "/graph/kant")
    try:
        chart = page.locator(".map-chart")
        before = chart.bounding_box()["width"]
        page.locator(".map-panel__toggle").click()
        expect(page.locator(".map-panel.is-collapsed")).to_be_visible()
        expect(page.locator(".map-panel__rail-btn")).to_have_count(4)
        page.wait_for_function(
            "w => document.querySelector('.map-chart').getBoundingClientRect().width > w",
            arg=before + 100,
        )
        settle(page)
        # Холст забрал ширину: ось доходит почти до края рабочей области.
        assert (
            page.locator(".map-canvas svg[data-part='bottom']").bounding_box()["width"]
            > before + 100
        )
        page.reload()
        page.locator(".map-canvas").wait_for()
        expect(page.locator(".map-panel.is-collapsed")).to_be_visible()
        # Значок рельса разворачивает панель к своему разделу.
        page.locator(".map-panel__rail-btn[data-rail='search']").click()
        expect(page.locator(".map-panel.is-collapsed")).to_have_count(0)
        expect(page.locator(".map-search input")).to_be_focused()
        page.reload()
        page.locator(".map-canvas").wait_for()
        expect(page.locator(".map-panel.is-collapsed")).to_have_count(0)
    finally:
        context.close()


# --- линзы и окно времени ---------------------------------------------------------------


@req(KG, "Линзы и окно времени")
def test_collapse_events_lens_gives_height_to_people(browser, site):
    context, page = open_map(browser, site)
    try:
        people = page.locator(".map-people")
        before = people.bounding_box()["height"]
        events = page.locator(".map-lens[data-lens='events']")
        events.click()
        settle(page)
        expect(events).to_have_attribute("aria-pressed", "false")
        assert page.locator(".map-event-tick").count() == 14  # отметки в узкой полосе
        assert page.locator(".map-event").count() == 0
        assert people.bounding_box()["height"] > before
        assert address(page)[1].get("lens") == "events"
    finally:
        context.close()


@req(KG, "Линзы и окно времени")
def test_last_expanded_lens_cannot_collapse(browser, site):
    context, page = open_map(browser, site, query=f"{DENSE}&lens=events,eras,works")
    try:
        lens = page.locator(".map-lens[data-lens='people']")
        expect(lens).to_have_attribute("aria-pressed", "true")
        expect(lens).to_have_attribute("aria-disabled", "true")
        lens.click(force=True)  # aria-disabled: Playwright без force не нажимает
        settle(page)
        expect(lens).to_have_attribute("aria-pressed", "true")
        assert page.locator(".map-person").count() == TOTAL_PEOPLE
        # Адрес со всеми свёрнутыми стратами не принимается.
        page.goto(f"{site.url}/graph?{DENSE}&lens=events,eras,people,works")
        page.locator(".map-canvas").wait_for()
        expect(page.locator(".map-lens[aria-pressed='false']")).to_have_count(0)
    finally:
        context.close()


@req(KG, "Линзы и окно времени")
def test_overview_window_zooms_map(browser, site):
    context, page = open_map(browser, site)
    try:
        width_before = life_box(page, "kant")["width"]
        set_window(page, 1700, 1800)
        settle(page)
        assert life_box(page, "kant")["width"] > width_before * 2  # окно уже — карта ближе
        assert address(page)[1].get("from") == "1700"
    finally:
        context.close()


@req(KG, "Линзы и окно времени")
@pytest.mark.parametrize("selection", ["/graph", "/graph/kant"])
def test_frame_16_9_axis_and_works_visible_without_page_scroll(browser, site, selection):
    context, page = open_map(browser, site, selection, viewport={"width": 1920, "height": 1080})
    try:
        # Ось, труды и обзорная шкала — в окне без прокрутки страницы.
        assert page.evaluate("scrollY") == 0
        axis = page.locator(".map-axis").bounding_box()
        assert axis["y"] + axis["height"] <= 1080, axis
        works = page.locator(".map-work").first.bounding_box()
        assert works["y"] + works["height"] <= 1080
        overview = page.locator(".map-chart").bounding_box()
        assert overview["y"] + overview["height"] <= 1080
        visual.assert_no_horizontal_scroll(page)
    finally:
        context.close()


# --- показ, достроенное, пустая карта ---------------------------------------------------


@req(KG, "Карта раздела")
@req(KG, "Показ графа")
def test_people_ordered_by_time(browser, site):
    context, page = open_map(browser, site, "/graph/kant")
    try:
        hume, kant, descartes = (life_box(page, p) for p in ("hume", "kant", "descartes"))
        assert hume["x"] < kant["x"]
        # Юм и Кант — современники, Декарт умер до рождения Канта.
        assert hume["x"] + hume["width"] > kant["x"]
        assert descartes["x"] + descartes["width"] < kant["x"]
        # Значок труда стоит на своём году, подпись — под значком (труды Канта видны при выборе).
        work = page.locator(
            ".map-work", has=page.locator("title", has_text="Критика чистого разума, 1781")
        )
        tick = work.locator(".map-work__tick").bounding_box()
        mark = work.locator(".map-work__mark").bounding_box()
        title = work.locator(".map-work__title").bounding_box()
        assert abs(mark["x"] + mark["width"] / 2 - (title["x"] + title["width"] / 2)) < 2
        assert -2 <= title["y"] - (mark["y"] + mark["height"]) < 20  # рамка текста с запасом
        assert abs(tick["x"] - mark["x"]) < 120  # «булавка» от года к значку
    finally:
        context.close()


@req(KG, "Пометка достроенного")
def test_generated_link_dashed_in_details_legend_and_export(browser, site):
    context, page = open_map(browser, site, "/graph/kant", accept_downloads=True)
    try:
        dashed = page.locator(".map-thread[data-generated='true']")
        assert dashed.count() >= 1
        assert dashed.first.get_attribute("stroke-dasharray") == "4 3"
        assert (
            page.locator(".map-thread[data-generated='false']").first.get_attribute(
                "stroke-dasharray"
            )
            is None
        )
        expect(page.locator(".map-legend")).to_contain_text("не проверено")
        expect(page.locator(".map-selected")).to_contain_text("Пунктир")
        # Подробности достроенной связи: видно, что она сгенерирована.
        hit = page.locator(".map-thread-hit[aria-label*='достроено моделью']").first
        hit.focus()
        page.keyboard.press("Enter")
        details = page.locator(".map-link")
        expect(details).to_contain_text("достроена моделью")
        expect(page.locator(".map-thread.is-picked")).to_have_count(1)
        page.keyboard.press("Escape")  # закрывает подробности, выбор остаётся
        expect(details).to_have_count(0)
        assert address(page)[0] == "/graph/kant"
        # Смена фильтра не теряет пометку.
        set_window(page, 1650, 1850)
        settle(page)
        assert page.locator(".map-thread[data-generated='true']").count() >= 1
        # Экспорт: в файле пунктир.
        with page.expect_download() as download:
            page.get_by_role("button", name="Сохранить изображение").click()
        text = Path(download.value.path()).read_text(encoding="utf-8")
        assert text.startswith("<svg") or "<svg" in text[:200]
        assert 'stroke-dasharray="4 3"' in text
    finally:
        context.close()


@req(KG, "Пустой граф")
def test_empty_map_says_so(browser, site):
    context = reader_context(browser, viewport={"width": 1440, "height": 900})
    page = context.new_page()
    try:
        page.route(MAP_API, lambda route: route.fulfill(status=404, json={"error": "not found"}))
        page.goto(f"{site.url}/graph")
        expect(page.locator(".map-empty")).to_contain_text("Карта пока пуста")
        assert page.locator(".map-canvas").count() == 0
        page.unroute(MAP_API)
        page.route(
            MAP_API,
            lambda route: route.fulfill(json=map_payload(range=None)),
        )
        page.reload()
        expect(page.locator(".map-empty")).to_contain_text("Карта пока пуста")
    finally:
        context.close()


@req(KG, "Пустой граф")
def test_selected_without_links_offers_generation(browser, site):
    context = reader_context(browser, viewport={"width": 1440, "height": 900})
    page = context.new_page()
    try:
        page.route(MAP_API, lambda route: route.fulfill(json=kant_alone()))
        page.goto(f"{site.url}/graph/kant")
        page.locator(".map-canvas").wait_for()
        switch = page.locator(".map-head").get_by_label("Достраивать моделью")
        if switch.is_checked():
            switch.uncheck()
        selected = page.locator(".map-selected")
        expect(selected).to_contain_text("Связей пока нет")
        selected.get_by_role("button", name="Включить достройку моделью").click()
        expect(switch).to_be_checked()
    finally:
        context.close()


@req(KG, "Ограничение размера")
def test_truncated_map_says_part_is_shown(browser, site):
    context = reader_context(browser, viewport={"width": 1440, "height": 900})
    page = context.new_page()
    try:
        page.route(
            MAP_API,
            lambda route: route.fulfill(json={**kant_alone(), "truncated": True, "limit": 1}),
        )
        page.goto(f"{site.url}/graph")
        expect(page.locator(".map-notice", has_text="Показана часть карты")).to_be_visible()
    finally:
        context.close()


# --- сцена, раскладка, шрифты (visual-design) -------------------------------------------

# Контраст текста листа: и HTML (шапка, панель), и подписи SVG (их цвет — fill).
_SHEET_CONTRAST_JS = """
(min) => {
  const ctx = (() => { const c = document.createElement('canvas'); c.width = c.height = 1;
    return c.getContext('2d', {willReadFrequently: true}); })();
  const rgba = color => { ctx.clearRect(0, 0, 1, 1); ctx.fillStyle = '#000';
    ctx.fillStyle = color; ctx.fillRect(0, 0, 1, 1);
    const d = ctx.getImageData(0, 0, 1, 1).data; return [d[0], d[1], d[2], d[3] / 255]; };
  const lum = c => { const f = v => { v /= 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); };
  const over = (top, bottom) =>
    [0, 1, 2].map(i => top[i] * top[3] + bottom[i] * (1 - top[3])).concat(1);
  const sheet = document.querySelector('.map-sheet');
  // Бумага — токен --sheet (фон рисует подложка стола, у самого листа он прозрачен).
  const own = rgba(getComputedStyle(sheet).backgroundColor);
  const paper = own[3] >= 1 ? own
    : rgba(getComputedStyle(sheet).getPropertyValue('--sheet').trim());
  const background = el => {
    const layers = [];
    for (let e = el; e && e !== sheet.parentElement; e = e.parentElement) {
      if (e instanceof SVGElement) continue;
      const c = rgba(getComputedStyle(e).backgroundColor);
      if (c[3] > 0) layers.push(c);
      if (c[3] >= 1) break;
    }
    let result = paper;
    for (const layer of layers.reverse()) result = over(layer, result);
    return result;
  };
  const faded = el => { for (let e = el; e; e = e.parentElement) {
    if (parseFloat(getComputedStyle(e).opacity) < 1) return true;
    if (e.matches && e.matches(':disabled, [aria-disabled=true]')) return true; } return false; };
  const out = [];
  for (const el of sheet.querySelectorAll('*')) {
    if (!el.getClientRects().length) continue;
    const svgText = el instanceof SVGTextElement;
    if (el.closest('svg') && !svgText) continue;
    const text = svgText ? el.textContent.trim() : [...el.childNodes].filter(n => n.nodeType === 3)
      .map(n => n.textContent.trim()).join('');
    if (!text) continue;
    const st = getComputedStyle(el);
    if (st.visibility === 'hidden' || faded(el)) continue;
    const bg = svgText ? paper : background(el);
    const fg = over(rgba(svgText ? st.fill : st.color), bg);
    const [hi, lo] = [lum(fg), lum(bg)].sort((a, b) => b - a);
    const ratio = (hi + 0.05) / (lo + 0.05);
    if (ratio < min) out.push({text: text.slice(0, 40), ratio: +ratio.toFixed(2),
      cls: String(el.getAttribute('class'))});
  }
  return {paper, out};
}
"""


def _luminance(rgb: list[float]) -> float:
    def f(v: float) -> float:
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    return 0.2126 * f(rgb[0]) + 0.7152 * f(rgb[1]) + 0.0722 * f(rgb[2])


@req(VD, "Сцена карты")
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_sheet_stays_light_and_readable(browser, site, theme):
    context, page = open_map(browser, site, "/graph/kant", color_scheme=theme)
    try:
        result = page.evaluate(_SHEET_CONTRAST_JS, 4.5)
        assert _luminance(result["paper"]) > 0.7, result["paper"]  # лист светлый в обеих темах
        if theme == "dark":
            page_bg = visual.computed(page, "body", "backgroundColor")
            assert _luminance(page_bg) < 0.2, page_bg  # вокруг листа — тёмная тема
        assert not result["out"], f"контраст на листе ниже 4.5: {result['out']}"
    finally:
        context.close()


@req(VD, "Сцена карты")
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_narrow_desktop_hides_desk_props(browser, site, theme):
    context, page = open_map(
        browser, site, "/graph/kant", viewport={"width": 1024, "height": 768}, color_scheme=theme
    )
    try:
        visual.assert_no_horizontal_scroll(page)
        props = page.evaluate(
            "() => [...document.querySelectorAll('.desk-prop')]"
            ".filter(e => e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden')"
            ".map(e => e.className)"
        )
        assert not props, f"предметы стола видны на 1024: {props}"
        visual.assert_no_overlap(page, [".map-chart", ".map-panel"])
        sheet = page.locator(".map-sheet").bounding_box()
        assert sheet["x"] + sheet["width"] <= 1024
    finally:
        context.close()


# Подписи карты: прямоугольники текстов, видимых в своей части холста (люди прокручиваются
# внутри страты — подписи за краем прокрутки не считаются), и лент жизни.
_LABELS_JS = """
() => {
  const visibleRect = el => {
    const part = el.closest('svg[data-part]');
    const holder = part.dataset.part === 'people' ? part.closest('.map-people') : part;
    return holder.getBoundingClientRect();
  };
  const inside = (r, v) => r.left >= v.left - 1 && r.right <= v.right + 1
    && r.top >= v.top - 1 && r.bottom <= v.bottom + 1;
  const shown = el => { for (let e = el; e && e.tagName !== 'svg'; e = e.parentElement) {
    const st = getComputedStyle(e);
    if (st.display === 'none' || st.visibility === 'hidden' || parseFloat(st.opacity) === 0)
      return false; } return true; };
  const box = r => ({left: r.left, top: r.top, right: r.right, bottom: r.bottom});
  const texts = [...document.querySelectorAll('.map-canvas svg[data-part] text')]
    .filter(t => !t.classList.contains('map-person__mono') && t.textContent.trim() && shown(t))
    .map(t => ({t, r: t.getBoundingClientRect()}))
    .filter(({t, r}) => r.width > 0 && inside(r, visibleRect(t)))
    .map(({t, r}) => ({text: t.textContent.trim().slice(0, 40),
      part: t.closest('svg[data-part]').dataset.part,
      person: t.closest('[data-person]')?.dataset.person ?? null, ...box(r)}));
  // Ленты — только видимая в прокрутке часть: за краем страты их не видно.
  const lives = [...document.querySelectorAll('.map-person__life')].map(e => {
    const r = e.getBoundingClientRect(), v = visibleRect(e);
    return {person: e.closest('[data-person]').dataset.person,
      left: Math.max(r.left, v.left), right: Math.min(r.right, v.right),
      top: Math.max(r.top, v.top), bottom: Math.min(r.bottom, v.bottom)};
  }).filter(b => b.right > b.left && b.bottom > b.top);
  return {texts, lives};
}
"""


def _hits(a: dict, b: dict, slack: float = 0.5) -> bool:
    return (
        a["left"] < b["right"] - slack
        and b["left"] < a["right"] - slack
        and a["top"] < b["bottom"] - slack
        and b["top"] < a["bottom"] - slack
    )


def label_clashes(page) -> list[str]:
    found = page.evaluate(_LABELS_JS)
    texts, lives = found["texts"], found["lives"]
    assert len(texts) > 15, texts  # проверка видит подписи, а не пустой холст
    clashes = [
        f"{a['text']!r} × {b['text']!r}"
        for i, a in enumerate(texts)
        for b in texts[i + 1 :]
        if _hits(a, b)
    ]
    clashes += [
        f"{t['text']!r} на ленте {life['person']}"
        for t in texts
        for life in lives
        if t["part"] == "people" and life["person"] != t["person"] and _hits(t, life)
    ]
    return clashes


@req(VD, "Раскладка без наложений")
@pytest.mark.parametrize("size", [(1280, 720), (1920, 1080)], ids=["1280", "1920"])
@pytest.mark.parametrize("selection", ["/graph", "/graph/kant"], ids=["none", "kant"])
def test_map_labels_do_not_overlap(browser, site, size, selection):
    width, height = size
    context, page = open_map(browser, site, selection, viewport={"width": width, "height": height})
    try:
        visual.assert_no_horizontal_scroll(page)
        visual.assert_no_overlap(page, [".map-chart", ".map-panel"])
        clashes = label_clashes(page)
        assert not clashes, f"подписи карты накладываются ({len(clashes)}): {clashes[:15]}"
    finally:
        context.close()


@req(VD, "Шрифты")
def test_desk_notes_in_bad_script_from_same_origin(browser, site):
    context, page = open_map(browser, site, "/graph/kant")
    fonts: list[str] = []
    try:
        page.on("request", lambda r: fonts.append(r.url) if r.resource_type == "font" else None)
        page.reload()
        page.locator(".map-canvas").wait_for()
        settle(page)
        note = page.locator(".desk-note-quote, .desk-note").first
        if note.count() == 0:
            pytest.skip("записки на столе ещё не выводятся на странице карты (DeskNotes)")
        family = note.evaluate("e => getComputedStyle(e).fontFamily")
        assert family.split(",")[0].strip("\"' ") == "Bad Script", family
        assert "Bad Script" in visual.loaded_families(page)
        assert fonts and all(url.startswith(site.url) for url in fonts), fonts
        assert not any("fonts.googleapis.com" in url or "gstatic" in url for url in fonts)
    finally:
        context.close()


def test_fixture_matches_expectations():
    """Опорные числа теста совпадают с набором ``fixture.ts`` (защита от тихой смены набора)."""
    source = (Path(__file__).resolve().parents[2] / "web/src/map/fixture.ts").read_text(
        encoding="utf-8"
    )
    people = re.findall(r'\["(\w+)", "[^"]+", "[^"]+", \d+, \d+\]', source)
    assert len(people) == TOTAL_PEOPLE
    assert '[1751, "Энциклопедия", "intellectual"]' in source
    assert json.dumps("g-emp") in source


@req(VD, "Разделы в разработке")
def test_soon_graph_bookmark_leads_to_map(browser, site):
    """Заглушка «Граф» снята: пункт без «скоро» ведёт на /graph, старая закладка — на карту."""
    context, page = open_map(browser, site)
    try:
        item = page.locator(".sidebar").get_by_role("link", name=re.compile("Граф"))
        assert item.get_attribute("href") == "/graph"
        assert "скоро" not in item.inner_text().lower()
        history = page.evaluate("history.length")
        page.goto(f"{site.url}/soon/graph")
        page.wait_for_function("location.pathname === '/graph'")
        page.locator(".map-canvas, .map-empty").first.wait_for()
        assert page.evaluate("history.length") == history + 1  # заменён без новой записи
        assert page.locator(".soon").count() == 0
    finally:
        context.close()
