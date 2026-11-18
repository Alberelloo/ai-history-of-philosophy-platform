"""Вид карты от ассистента в браузере (assistant-map-view, задача 3.3).

Ответ ассистента подменяется строками NDJSON (``tests/assistant/browser.py``), карта — плотный
набор клиента (``?fixture=dense``): служебный ``fixture`` клиент пишет после ``via``.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from ..assistant.browser import AskStub, answer, ask, fragment, open_assistant, panel, stored
from ..helpers import reader_context
from .test_map import DENSE, check, open_map

req = pytest.mark.req
AD = "assistant-dialog"
KG = "knowledge-graph"
PAIRS = json.loads((Path(__file__).parents[1] / "fixtures" / "map_views.json").read_text())
VIEW = "/graph/kant?from=1690&to=1800&groups=g-emp&via=assistant"


def map_suggestion(href: str, **extra) -> dict:
    return {
        "type": "suggestion",
        "kind": "map",
        "href": href,
        "caption": "Эмпиристы и Кант",
        "shown": {"people": 8, "works": 12},
        "dropped": [],
        **extra,
    }


def address(page) -> str:
    parts = urlsplit(page.url)
    return parts.path + (f"?{parts.query}" if parts.query else "")


def via(page):
    return page.locator(".map-via")


@req(AD, "Карта по запросу")
def test_open_view_from_answer_and_back(browser, site):
    """Раздел «Ассистент»: кнопка ведёт на вид карты, «Назад» возвращает тот же диалог."""
    context = reader_context(browser, viewport={"width": 1440, "height": 900})
    page = context.new_page()
    page.set_default_timeout(8000)
    try:
        AskStub(page).reply(
            answer(
                fragment("Эмпиристы и Кант на одной ленте.", grounded=False),
                map_suggestion(f"{VIEW}&{DENSE}"),
            )
        )
        page.goto(f"{site.url}/assistant")
        box = page.locator(".assistant-page")
        ask(box, "собери карту вокруг Канта и эмпиристов")
        button = box.get_by_role("link", name="Открыть на карте")
        expect(button).to_be_visible()
        expect(box.locator(".turn__map-caption")).to_have_text("Эмпиристы и Кант")
        expect(box.locator(".turn__map-shown")).to_have_text(
            "На карте 8 философов и 12 трудов и идей"
        )
        button.click()
        page.locator(".map-canvas").wait_for()
        assert address(page) == f"{VIEW}&{DENSE}"
        expect(via(page).locator(".map-via__parts")).to_contain_text("выбрано: Иммануил Кант")
        page.go_back()
        page.wait_for_url("**/assistant")
        box = page.locator(".assistant-page")
        expect(
            box.locator(".question", has_text="собери карту вокруг Канта и эмпиристов")
        ).to_be_visible()
        expect(box.get_by_role("link", name="Открыть на карте")).to_be_visible()
        # Вид хранится с диалогом: после перезагрузки кнопка на месте.
        assert stored(page)["libraryDialogs"]
        page.reload()
        expect(page.get_by_role("link", name="Открыть на карте")).to_be_visible()
    finally:
        context.close()


@req(AD, "Карта по запросу")
def test_reader_panel_button_and_dropped(browser, site):
    """Панель ассистента в читалке: кнопка, «не вошло» и карточка сущности, которой нет."""
    context = reader_context(browser, viewport={"width": 1440, "height": 900})
    page = context.new_page()
    page.set_default_timeout(8000)
    try:
        dropped = [
            {"field": "sel", "value": "e_habit", "label": "Привычка", "reason": "not_on_map"},
            {"field": "from", "value": 1790, "reason": "empty_result"},
            {"field": "lens", "value": "events", "reason": "all_strata"},
        ]
        AskStub(page).reply(
            answer(
                fragment("Карта по Канту.", grounded=False),
                map_suggestion(f"/graph/kant?via=assistant&{DENSE}", dropped=dropped),
            ),
            # Испорченный адрес (не карта) кнопкой не показывается.
            answer(
                fragment("Ещё ответ.", grounded=False),
                map_suggestion("https://example.org/graph?via=assistant"),
            ),
        )
        from .test_reader_cards import CARDS, HUME

        page.route("**/api/knowledge/v1/entities/*/card*", lambda r: r.fulfill(json=CARDS[HUME]))
        page.goto(f"{site.url}/read/{site.ids['textbook']}")
        page.wait_for_selector(".chapter [data-paragraph]")
        open_assistant(page)
        ask(panel(page), "карта вокруг Канта и привычки")
        box = panel(page)
        expect(box.locator(".turn__map-dropped")).to_have_text(
            "Не вошло: Привычка — нет на карте Карточка; 1790 — карта вышла бы пустой"
        )
        ask(panel(page), "ещё")
        expect(box.locator(".turn")).to_have_count(2)
        expect(box.locator(".turn").nth(1).locator(".fragment")).to_be_visible()
        assert box.get_by_role("link", name="Открыть на карте").count() == 1
        box.get_by_role("button", name="Карточка").click()
        # Карточка ложится на стек панели, книга остаётся; «Назад к ассистенту» — к ответу.
        card = page.get_by_role("complementary", name="Карточка")
        card.get_by_text("Шотландский философ.").wait_for()
        assert "/read/" in page.url
        card.get_by_role("button", name="Назад к ассистенту").click()
        box.get_by_role("link", name="Открыть на карте").click()
        page.locator(".map-canvas").wait_for()
        assert address(page) == f"/graph/kant?via=assistant&{DENSE}"
    finally:
        context.close()


@req(KG, "Вид от ассистента")
@pytest.mark.parametrize("size", [(1920, 1080), (1024, 576)])
def test_notice_lists_view_and_reset_keeps_selection(browser, site, size):
    """Пометка — в панели карты: перечень применённого; страница без прокрутки и на 1024×576."""
    path, query = VIEW.split("?")
    context, page = open_map(
        browser, site, path, f"{query}&{DENSE}", viewport={"width": size[0], "height": size[1]}
    )
    try:
        notice = via(page)
        expect(notice.locator(".map-via__title")).to_have_text("Вид подобран ассистентом")
        expect(notice.locator(".map-via__parts")).to_have_text(
            "выбрано: Иммануил Кант; направления и школы: Эмпиризм; годы: 1690–1800"
        )
        assert page.evaluate("document.documentElement.scrollHeight - innerHeight") <= 0
        panel = page.locator(".map-panel").bounding_box()
        box = notice.bounding_box()
        assert box["y"] + box["height"] <= panel["y"] + panel["height"]
        shown = page.locator(".map-person").count()
        notice.get_by_role("button", name="Сбросить вид").click()
        expect(notice).to_have_count(0)
        assert address(page) == f"/graph/kant?{DENSE}"  # фильтров и via нет, выбор остался
        assert page.locator(".map-person").count() > shown
        expect(page.locator(".map-panel")).to_contain_text("Иммануил Кант")
    finally:
        context.close()


@req(KG, "Вид от ассистента")
def test_notice_leaves_on_manual_filter(browser, site):
    context, page = open_map(
        browser, site, "/graph", f"groups=g-emp&lens=events&via=assistant&{DENSE}"
    )
    try:
        expect(via(page).locator(".map-via__parts")).to_have_text(
            "направления и школы: Эмпиризм; свёрнуто: события"
        )
        check(page, "Направление", "Рационализм")
        expect(via(page)).to_have_count(0)
        assert "via=" not in address(page) and "g-rat" in address(page)
    finally:
        context.close()


@req(KG, "Вид от ассистента")
def test_forged_text_in_link_not_shown(browser, site):
    """Произвольный текст в параметрах: на карте его нет, пометка — только из применённого."""
    forged = "ПОДЛОГ"
    query = (
        f"groups=g-emp,{forged}1&roles=philosopher,{forged}2&kinds={forged}3&ekinds={forged}4"
        f"&q={forged}5&caption={forged}6&lens={forged}7&via=assistant&{DENSE}"
    )
    context, page = open_map(browser, site, f"/graph/{forged}8", query)
    try:
        expect(via(page).locator(".map-via__parts")).to_have_text(
            "направления и школы: Эмпиризм; роли: философ"
        )
        assert forged not in page.locator("body").inner_text()
        assert page.locator(".map-search input").input_value() == ""
    finally:
        context.close()


@req(KG, "Проверка вида карты")
@pytest.mark.parametrize("pair", PAIRS, ids=[p["note"] for p in PAIRS])
def test_client_writes_same_address(browser, site, pair):
    """Общий набор «вид → адрес» с сервером: клиент открывает адрес и пишет его же."""
    path, _, query = pair["href"].partition("?")
    context, page = open_map(browser, site, path, f"{query}&{DENSE}")
    try:
        page.wait_for_timeout(300)  # адрес пишется эффектом после отрисовки
        assert address(page) == f"{pair['href']}&{DENSE}"
        expect(via(page)).to_be_visible()
    finally:
        context.close()
