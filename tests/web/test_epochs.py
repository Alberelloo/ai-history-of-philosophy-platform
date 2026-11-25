"""epochs («Страница эпох», «Клавиатура и доступность страницы эпох») и visual-design
(«Старая закладка эпох») в браузере (add-epochs, задача 5.6).

Стенд — ``knowledge_stack``: настоящий шлюз, библиотека и сервис знаний; данные онтологии
задаёт тест через ``stack.world`` до открытия страницы. Адрес, выбор и фокус — интерфейсные
результаты без клиентского журнала; серверный якорь — ``knowledge.epochs.listed`` и
``knowledge.catalog.listed`` с ``request_id`` ответов, полученных страницей. ``page.route`` —
только для 503 и задержки.
"""

from __future__ import annotations

import json
import re
from itertools import combinations, pairwise
from urllib.parse import parse_qs, quote, urlparse

import pytest
from playwright.sync_api import expect

from ..helpers import sidenav

req = pytest.mark.req
EP = "epochs"
VD = "visual-design"
PAGE = "Страница эпох"
KEYS = "Клавиатура и доступность страницы эпох"
EPOCHS_API = "**/api/knowledge/v1/epochs*"
MAP_API = "**/api/knowledge/v1/map*"
LISTED = "knowledge.epochs.listed"
CATALOG_LISTED = "knowledge.catalog.listed"
XSS = '<img src=x onerror="window.__xss=1">'
SPAN = ".epochs-span"
expect.set_options(timeout=8000)


# --- данные ---------------------------------------------------------------------------------


def list_world(world, *, fuzzy_end: bool = False) -> dict[str, str]:
    """Данные сценария «Список эпох» и событие «Выход первого тома «Энциклопедии»» (1751)."""
    from philograph.knowledge.dates import FuzzyDate

    if fuzzy_end:
        sci = world.dated(
            "epoch",
            "Научная революция",
            FuzzyDate(1543, 1543, 1687, 1700, "approx", "1543 – 1687…1700").to_json(),
        )
    else:
        sci = world.thing("epoch", "Научная революция", "1543–1687")
    ids = {
        "sci": sci,
        "enl": world.thing("epoch", "Просвещение", "1680–1800"),
        "baroque": world.thing("epoch", "Барокко"),
        "descartes": world.person("Рене Декарт", "1596", "1650"),
        "locke": world.person("Джон Локк", "1632", "1704"),
        "hume": world.person("Дэвид Юм", "1711", "1776"),
        "kant": world.person("Иммануил Кант", "1724", "1804"),
        "leibniz": world.person("Готфрид Лейбниц"),
        "encyclopedia": world.thing("event", "Выход первого тома «Энциклопедии»", "1751"),
    }
    world.belongs(ids["leibniz"], ids["baroque"])
    return ids


# --- помощники ------------------------------------------------------------------------------


def open_epochs(make, stack, path: str = "/epochs", *, width=1920, height=1080):
    context = make(width, height)
    page = context.new_page()
    page.set_default_timeout(8000)
    with page.expect_response(EPOCHS_API) as info:
        page.goto(stack.url + path)
    return page, info.value


def event_of(events, response, name: str = LISTED):
    rid = response.headers.get("x-request-id")
    assert rid, response.url
    found = events.where(name, request_id=rid)
    assert len(found) == 1, (name, rid, events.names())
    return found[0]


def span(page, entity: str):
    return page.locator(f"{SPAN}[data-epoch='{entity}']")


def ribbon_ready(page) -> None:
    page.locator(SPAN).first.wait_for()


def heading(page):
    return page.locator("#epochs-details-title")


def members(page, list_: str) -> list[str]:
    section = page.locator(f".epochs-members[data-list='{list_}']")
    expect(section).to_have_attribute("aria-busy", "false")
    return section.locator(".epochs-members__name").all_inner_texts()


def catalog_wait(page, n: int):
    """Ждать, пока страница получит ``n`` ответов справочника (списки описания эпохи)."""
    seen = []

    def on(response):
        if "/api/knowledge/v1/catalog" in response.url:
            seen.append(response)

    page.on("response", on)
    return seen


def no_page_errors(page) -> None:
    assert page.context.errors == [], page.context.errors
    assert page.evaluate("window.__consoleErrors") == []


def selected(page) -> list[str]:
    return page.locator(f"{SPAN}[aria-selected='true']").evaluate_all(
        "els => els.map(e => e.dataset.epoch)"
    )


def path_of(page) -> str:
    return urlparse(page.url).path


def boxes(page, selector: str) -> list[dict]:
    return page.locator(selector).evaluate_all(
        "els => els.map(e => { const r = e.getBoundingClientRect();"
        " return {x: r.x, y: r.y, w: r.width, h: r.height, id: e.closest('[data-epoch]')"
        " ? e.closest('[data-epoch]').dataset.epoch : e.className}; })"
    )


def overlap(a: dict, b: dict, slack: float = 0.5) -> bool:
    return (
        a["x"] + a["w"] - slack > b["x"]
        and b["x"] + b["w"] - slack > a["x"]
        and a["y"] + a["h"] - slack > b["y"]
        and b["y"] + b["h"] - slack > a["y"]
    )


# --- Страница эпох ----------------------------------------------------------------------------


@req(EP, PAGE, scenario="Выбор эпохи")
def test_select_epoch(knowledge_context, knowledge_stack, events):
    w = list_world(knowledge_stack.world)
    page, listed = open_epochs(knowledge_context, knowledge_stack)
    ribbon_ready(page)
    seen = catalog_wait(page, 3)

    def of_type(code):
        return lambda r: "/api/knowledge/v1/catalog" in r.url and f"type={code}" in r.url

    with (
        page.expect_response(of_type("person")),
        page.expect_response(of_type("work")),
        page.expect_response(of_type("event")),
    ):
        span(page, w["enl"]).click()
    page.wait_for_url(re.compile(f"/epochs/{w['enl']}$"))
    expect(heading(page)).to_have_text("Просвещение")
    expect(page.locator(".epochs-details__range")).to_have_text("1680–1800")
    expect(page.locator(".epochs-details__count[data-count='people']")).to_have_text("Персоны 2")
    assert sorted(members(page, "people")) == ["Дэвид Юм", "Иммануил Кант"]
    assert "Выход первого тома «Энциклопедии»" in members(page, "events")
    # Журнал: список эпох и три запроса справочника с фильтрами эпохи и типа.
    assert event_of(events, listed)["epochs"] == 2
    catalog = [r for r in seen if "/api/knowledge/v1/catalog" in r.url]
    assert len(catalog) == 3, [r.url for r in catalog]
    for response in catalog:
        query = parse_qs(urlparse(response.url).query)
        assert query["epoch"] == [w["enl"]]
        assert event_of(events, response, CATALOG_LISTED)["filters"] == ["epoch", "type"]
    no_page_errors(page)


@req(EP, PAGE, scenario="Выбор эпохи")
def test_open_address_selects_epoch(knowledge_context, knowledge_stack, events):
    w = list_world(knowledge_stack.world)
    page, listed = open_epochs(knowledge_context, knowledge_stack, f"/epochs/{w['enl']}")
    ribbon_ready(page)
    expect(heading(page)).to_have_text("Просвещение")
    assert selected(page) == [w["enl"]]
    # Ссылки счётчиков — в справочник с эпохой и группой.
    link = page.locator(".epochs-details__count[data-count='people']")
    href = urlparse(link.get_attribute("href"))
    assert href.path == "/reference"
    assert parse_qs(href.query) == {"epoch": [w["enl"]], "group": ["person"]}
    # Эпохи без датировки — списком под лентой.
    expect(page.locator(".epochs__undated-link")).to_have_text(["Барокко"])
    assert event_of(events, listed)["undated"] == 1
    no_page_errors(page)


@req(EP, PAGE, scenario="На карте")
def test_on_the_map(knowledge_context, knowledge_stack, events):
    w = list_world(knowledge_stack.world)
    page, _ = open_epochs(knowledge_context, knowledge_stack, f"/epochs/{w['enl']}")
    expect(heading(page)).to_have_text("Просвещение")
    with page.expect_response(MAP_API) as built:
        page.get_by_role("link", name="На карте").click()
    page.wait_for_url(re.compile(r"/graph\?"))
    url = urlparse(page.url)
    assert url.path == "/graph" and parse_qs(url.query) == {"epochs": [w["enl"]]}
    page.locator(".map-canvas").wait_for()
    epoch_facet = page.locator(".map-facet").filter(
        has=page.locator("summary", has_text=re.compile("^Эпоха"))
    )
    if epoch_facet.get_attribute("open") is None:
        epoch_facet.locator("summary").click()
    box = epoch_facet.locator(".map-check", has_text="Просвещение").locator("input")
    expect(box).to_be_checked()
    time_facet = page.locator(".map-facet").filter(
        has=page.locator("summary", has_text=re.compile("^Время"))
    )
    if time_facet.get_attribute("open") is None:
        time_facet.locator("summary").click()
    years = time_facet.locator(".map-year")
    assert (years.nth(0).input_value(), years.nth(1).input_value()) == ("1680", "1800")
    assert event_of(events, built.value, "knowledge.map.built")
    no_page_errors(page)


@req(EP, PAGE, invariant="«Карточка эпохи» — в правой панели")
def test_epoch_card_action(knowledge_context, knowledge_stack, events):
    w = list_world(knowledge_stack.world)
    page, _ = open_epochs(knowledge_context, knowledge_stack, f"/epochs/{w['enl']}")
    expect(heading(page)).to_have_text("Просвещение")
    with page.expect_response("**/api/knowledge/v1/entities/*/card*") as card:
        page.get_by_role("button", name="Карточка эпохи").click()
    expect(page.locator(".pg-entity-head__name").first).to_have_text("Просвещение")
    served = event_of(events, card.value, "knowledge.card.served")
    assert (served["entity_id"], served["type"]) == (w["enl"], "epoch")
    assert path_of(page) == f"/epochs/{w['enl']}"
    no_page_errors(page)


@req(EP, PAGE, scenario="Пересекающиеся эпохи")
def test_overlapping_epochs_on_lanes(knowledge_context, knowledge_stack, events):
    w = list_world(knowledge_stack.world)
    page, listed = open_epochs(knowledge_context, knowledge_stack)
    ribbon_ready(page)
    assert span(page, w["sci"]).get_attribute("data-lane") != span(page, w["enl"]).get_attribute(
        "data-lane"
    )
    rects = boxes(page, SPAN) + boxes(page, ".epochs-span__label")
    clashes = [
        (a["id"], b["id"])
        for a, b in combinations(rects, 2)
        if a["id"] != b["id"] and overlap(a, b)
    ]
    assert clashes == []
    assert event_of(events, listed)["epochs"] == 2
    no_page_errors(page)


@req(EP, PAGE, invariant="пересекающиеся эпохи — по дорожкам без наложения пролётов и подписей")
def test_many_overlapping_epochs_packed(knowledge_context, knowledge_stack, events):
    world = knowledge_stack.world
    spans = [
        ("Античность", "-800–500"),
        ("Средние века", "500–1500"),
        ("Схоластика", "1050–1450"),
        ("Возрождение", "1400–1600"),
        ("Реформация", "1517–1648"),
        ("Научная революция", "1543–1687"),
        ("Барокко", "1600–1750"),
        ("Просвещение", "1680–1800"),
        ("Романтизм", "1790–1850"),
    ]
    for name, dates in spans:
        world.thing("epoch", name, dates)
    page, listed = open_epochs(knowledge_context, knowledge_stack)
    ribbon_ready(page)
    expect(page.locator(SPAN)).to_have_count(len(spans))
    rects = boxes(page, SPAN) + boxes(page, ".epochs-span__label")
    clashes = [
        (a["id"], b["id"])
        for a, b in combinations(rects, 2)
        if a["id"] != b["id"] and overlap(a, b)
    ]
    assert clashes == []
    assert event_of(events, listed)["epochs"] == len(spans)
    no_page_errors(page)


@req(EP, PAGE, scenario="Растушёвка")
def test_fuzzy_edges(knowledge_context, knowledge_stack, events):
    w = list_world(knowledge_stack.world, fuzzy_end=True)
    page, listed = open_epochs(knowledge_context, knowledge_stack)
    ribbon_ready(page)
    expect(span(page, w["sci"])).to_have_attribute("data-fuzzy-start", "0")
    expect(span(page, w["sci"])).to_have_attribute("data-fuzzy-end", "13")
    expect(span(page, w["enl"])).to_have_attribute("data-fuzzy-start", "0")
    expect(span(page, w["enl"])).to_have_attribute("data-fuzzy-end", "0")
    assert event_of(events, listed)["epochs"] == 2
    no_page_errors(page)


@req(EP, PAGE, scenario="Эпох нет")
def test_no_epochs(knowledge_context, knowledge_stack, events):
    page, listed = open_epochs(knowledge_context, knowledge_stack)
    expect(page.get_by_text("Эпохи появятся, когда онтология будет наполнена.")).to_be_visible()
    assert page.locator(".epochs-ribbon").count() == 0
    assert page.locator(SPAN).count() == 0
    event = event_of(events, listed)
    assert (event["epochs"], event["undated"]) == (0, 0)
    no_page_errors(page)


@req(EP, PAGE, scenario="Неизвестная эпоха и разметка в адресе")
def test_unknown_epoch_and_markup_in_address(knowledge_context, knowledge_stack, events):
    w = list_world(knowledge_stack.world)
    page, listed = open_epochs(knowledge_context, knowledge_stack, "/epochs/" + quote(XSS, safe=""))
    ribbon_ready(page)
    expect(page.get_by_text("Эпоха не найдена.")).to_be_visible()
    assert selected(page) == []
    assert span(page, w["enl"]).count() == 1  # лента показана
    assert page.evaluate("window.__xss") is None
    assert page.locator("img[src='x']").count() == 0
    assert event_of(events, listed)["epochs"] == 2
    no_page_errors(page)


@req(EP, PAGE, invariant="названия из данных выводятся текстом")
def test_markup_in_epoch_name(knowledge_context, knowledge_stack, events):
    world = knowledge_stack.world
    bad = world.thing("epoch", XSS, "1680–1800")
    undated = world.thing("epoch", XSS + " без даты")
    page, listed = open_epochs(knowledge_context, knowledge_stack, f"/epochs/{bad}")
    ribbon_ready(page)
    expect(heading(page)).to_have_text(XSS)
    expect(span(page, bad).locator(".epochs-span__label")).to_have_text(XSS)
    assert span(page, bad).get_attribute("aria-label").startswith(XSS)
    expect(page.locator(".epochs__undated-link")).to_have_text([XSS + " без даты"])
    assert page.evaluate("window.__xss") is None
    assert page.locator("img[src='x']").count() == 0
    assert event_of(events, listed)["undated"] == 1
    assert undated
    no_page_errors(page)


@req(EP, PAGE, invariant="ссылка «Wikidata» — только из проверенного идентификатора")
@pytest.mark.parametrize(
    "who,link",
    [
        ("wikidata:Q12539", "https://www.wikidata.org/wiki/Q12539"),
        ("wikidata:javascript:alert(1)", None),
        ('wikidata:Q1"><img src=x onerror="window.__xss=1">', None),
        ("wikidata:Q1/../../w/api.php", None),
    ],
    ids=["valid", "js", "markup", "path"],
)
def test_wikidata_link_from_checked_id(knowledge_context, knowledge_stack, events, who, link):
    from philograph.knowledge.dates import FuzzyDate
    from philograph.knowledge.statements import Attribution

    world = knowledge_stack.world
    enl = world.entities.create("epoch", [("ru", "Просвещение", "primary")])
    world.statements.add(
        enl,
        "dating",
        value=FuzzyDate(1685, 1685, 1815, 1815, "year", "1685–1815").to_json(),
        attributions=[Attribution("source", who)],
    )
    page, listed = open_epochs(knowledge_context, knowledge_stack, f"/epochs/{enl}")
    expect(heading(page)).to_have_text("Просвещение")
    anchors = page.locator(".epochs-details a[href*='wikidata']")
    if link is None:
        expect(anchors).to_have_count(0)
    else:
        expect(anchors).to_have_count(1)
        assert anchors.get_attribute("href") == link
        assert "noopener" in (anchors.get_attribute("rel") or "")
    hrefs = page.locator("a[href]").evaluate_all("els => els.map(e => e.getAttribute('href'))")
    assert not [h for h in hrefs if h.lower().startswith("javascript:")]
    assert page.evaluate("window.__xss") is None
    assert event_of(events, listed)["epochs"] == 1
    no_page_errors(page)


@req(EP, PAGE, invariant="до 8 персон и до 8 трудов по значимости, до 20 событий по времени")
def test_member_limits(knowledge_context, knowledge_stack, events):
    world = knowledge_stack.world
    enl = world.thing("epoch", "Просвещение", "1680–1800")
    for n in range(10):
        world.person(f"Философ {n:02d}", str(1700 + n), str(1760 + n))
        world.thing("work", f"Трактат {n:02d}", str(1700 + n))
    years = [1790 - 4 * n for n in range(25)]  # в обратном порядке создания
    for y in years:
        world.thing("event", f"Событие {y}", str(y))
    page, listed = open_epochs(knowledge_context, knowledge_stack, f"/epochs/{enl}")
    expect(heading(page)).to_have_text("Просвещение")
    assert len(members(page, "people")) == 8
    assert len(members(page, "works")) == 8
    shown = members(page, "events")
    assert shown == [f"Событие {y}" for y in sorted(years)[:20]]
    expect(page.locator(".epochs-details__count[data-count='people']")).to_have_text("Персоны 10")
    assert event_of(events, listed)["epochs"] == 1
    no_page_errors(page)


@req(EP, PAGE, invariant="ошибка сервиса — «Повторить», без pageerror и console.error")
def test_service_error_and_retry(knowledge_context, knowledge_stack, events):
    w = list_world(knowledge_stack.world)
    context = knowledge_context()
    page = context.new_page()
    page.route(
        EPOCHS_API,
        lambda r: r.fulfill(status=503, json={"error": "Сервис временно недоступен"}),
    )
    page.goto(knowledge_stack.url + "/epochs")
    expect(page.get_by_text("Эпохи временно недоступны.")).to_be_visible()
    retry = page.get_by_role("button", name="Повторить")
    expect(retry).to_be_visible()
    assert page.locator(SPAN).count() == 0
    assert events.of(LISTED) == []  # ответ подменён: до сервиса запрос не дошёл
    page.unroute(EPOCHS_API)
    with page.expect_response(EPOCHS_API) as again:
        retry.click()
    ribbon_ready(page)
    expect(span(page, w["enl"])).to_have_count(1)
    assert event_of(events, again.value)["epochs"] == 2
    no_page_errors(page)


@req(EP, PAGE, invariant="состояние загрузки")
def test_loading_state(knowledge_context, knowledge_stack, events):
    w = list_world(knowledge_stack.world)
    context = knowledge_context()
    page = context.new_page()
    held = []
    page.route(EPOCHS_API, lambda r: held.append(r))
    page.goto(knowledge_stack.url + "/epochs")
    page.wait_for_function("document.querySelector('.epochs-ribbon[aria-busy=\"true\"]')")
    assert page.locator(SPAN).count() == 0
    assert events.of(LISTED) == []
    with page.expect_response(EPOCHS_API) as answer:
        held[0].continue_()
    page.unroute(EPOCHS_API)
    ribbon_ready(page)
    expect(span(page, w["sci"])).to_have_count(1)
    assert event_of(events, answer.value)["epochs"] == 2
    no_page_errors(page)


# --- Клавиатура и доступность ---------------------------------------------------------------


def tab_to_ribbon(page, limit: int = 40) -> None:
    for _ in range(limit):
        page.keyboard.press("Tab")
        if page.evaluate("document.activeElement.classList.contains('epochs-span')"):
            return
    raise AssertionError("Tab не привёл к ленте")


def focused_epoch(page) -> str | None:
    return page.evaluate("document.activeElement.dataset.epoch || null")


@req(EP, KEYS, scenario="Выбор с клавиатуры")
def test_keyboard_select(knowledge_context, knowledge_stack, events):
    w = list_world(knowledge_stack.world)
    page, listed = open_epochs(knowledge_context, knowledge_stack)
    ribbon_ready(page)
    tab_to_ribbon(page)
    assert focused_epoch(page) == w["sci"]  # первая по времени
    page.keyboard.press("ArrowRight")
    assert focused_epoch(page) == w["enl"]
    page.keyboard.press("Enter")
    page.wait_for_url(re.compile(f"/epochs/{w['enl']}$"))
    assert selected(page) == [w["enl"]]
    expect(heading(page)).to_be_focused()
    expect(heading(page)).to_have_text("Просвещение")
    assert event_of(events, listed)["epochs"] == 2
    no_page_errors(page)


@req(EP, KEYS, scenario="Края ленты")
def test_ribbon_edges(knowledge_context, knowledge_stack, events):
    w = list_world(knowledge_stack.world)
    knowledge_stack.world.thing("epoch", "Романтизм", "1790–1850")
    page, listed = open_epochs(knowledge_context, knowledge_stack, f"/epochs/{w['enl']}")
    ribbon_ready(page)
    tab_to_ribbon(page)
    page.keyboard.press("End")
    last = focused_epoch(page)
    assert span(page, last).get_attribute("aria-label").startswith("Романтизм")
    page.keyboard.press("ArrowRight")
    assert focused_epoch(page) == last  # без перехода по кругу
    page.keyboard.press("Escape")
    page.wait_for_url(re.compile(r"/epochs$"))
    assert selected(page) == []
    page.keyboard.press("Home")
    assert focused_epoch(page) == w["sci"]
    page.keyboard.press("ArrowLeft")
    assert focused_epoch(page) == w["sci"]
    assert event_of(events, listed)["epochs"] == 3
    no_page_errors(page)


@req(EP, KEYS, invariant="доступное имя пролёта «Название, начало–конец»")
def test_accessible_names(knowledge_context, knowledge_stack, events):
    w = list_world(knowledge_stack.world)
    from philograph.knowledge.dates import FuzzyDate

    ant = knowledge_stack.world.dated(
        "epoch",
        "Античность",
        FuzzyDate(-799, -799, 476, 476, "year", "800 до н. э. – 476").to_json(),
    )
    page, listed = open_epochs(knowledge_context, knowledge_stack)
    ribbon_ready(page)
    assert span(page, w["enl"]).get_attribute("aria-label") == "Просвещение, 1680–1800"
    assert span(page, w["sci"]).get_attribute("aria-label") == "Научная революция, 1543–1687"
    expect(page.get_by_role("option", name="Просвещение, 1680–1800")).to_have_count(1)
    assert span(page, ant).get_attribute("aria-label").startswith("Античность, 800 до н. э.")
    order = page.locator(SPAN).evaluate_all("els => els.map(e => e.dataset.epoch)")
    focus_order = []
    tab_to_ribbon(page)
    for _ in range(3):
        focus_order.append(focused_epoch(page))
        page.keyboard.press("ArrowRight")
    assert focus_order == [ant, w["sci"], w["enl"]]
    assert sorted(order) == sorted(focus_order)
    assert event_of(events, listed)["epochs"] == 3
    no_page_errors(page)


@req(EP, KEYS, scenario="Малое окно")
@pytest.mark.parametrize("width,height", [(1024, 576), (1920, 1080)])
def test_layout_fits(knowledge_context, knowledge_stack, events, width, height):
    w = list_world(knowledge_stack.world)
    page, listed = open_epochs(
        knowledge_context, knowledge_stack, f"/epochs/{w['enl']}", width=width, height=height
    )
    ribbon_ready(page)
    expect(heading(page)).to_have_text("Просвещение")
    members(page, "people")
    assert page.evaluate("document.documentElement.scrollWidth") <= width
    assert page.evaluate("window.scrollY") == 0
    for target in (page.locator(".epochs-ribbon"), heading(page)):
        box = target.bounding_box()
        assert box["y"] >= 0 and box["y"] + box["height"] <= height, box
        assert box["x"] >= 0 and box["x"] + box["width"] <= width, box
    rects = boxes(page, SPAN) + boxes(page, ".epochs-span__label")
    assert [
        (a["id"], b["id"])
        for a, b in combinations(rects, 2)
        if a["id"] != b["id"] and overlap(a, b)
    ] == []
    # Крупные блоки страницы не налезают друг на друга.
    blocks = [
        page.locator(s).bounding_box()
        for s in (".epochs__header", ".epochs-ribbon", "#epochs-details-title")
    ]
    as_rect = [{"x": b["x"], "y": b["y"], "w": b["width"], "h": b["height"]} for b in blocks]
    assert [(i, j) for i, j in combinations(range(3), 2) if overlap(as_rect[i], as_rect[j])] == []
    assert event_of(events, listed)["epochs"] == 2
    no_page_errors(page)


# --- visual-design: Разделы в разработке ------------------------------------------------------


@req(VD, "Разделы в разработке", scenario="Старая закладка эпох")
def test_old_epochs_bookmark(knowledge_context, knowledge_stack, events):
    w = list_world(knowledge_stack.world)
    context = knowledge_context()
    page = context.new_page()
    page.goto(knowledge_stack.url + "/")
    page.locator(".sidebar").wait_for()
    history = page.evaluate("history.length")
    with page.expect_response(EPOCHS_API) as anchor:
        page.goto(knowledge_stack.url + "/soon/epochs")
    page.wait_for_url(re.compile(r"/epochs$"))
    assert page.evaluate("history.length") == history + 1  # только переход, замена без записи
    ribbon_ready(page)
    expect(span(page, w["enl"])).to_have_count(1)
    expect(page.locator("h1.page-title")).to_have_text("Эпохи")
    assert page.locator(".soon").count() == 0
    nav = sidenav(page)
    # add-epoch-context: подпись раздела — «Эпохи и контекст» (дельта visual-design).
    link = nav.get_by_role("link", name="Эпохи и контекст", exact=True)
    expect(link).to_have_count(1)
    assert link.get_attribute("href") == "/epochs"
    assert "скоро" not in link.inner_text().lower()
    assert link.get_attribute("aria-current") == "page"
    assert event_of(events, anchor.value)["epochs"] == 2
    page.go_back()
    page.wait_for_url(re.compile(r"/$"))
    assert "/soon/" not in page.url
    no_page_errors(page)


# --- epoch-context: «Контекст на странице эпохи», «Достройка контекста моделью» ---------------
# (add-epoch-context, задачи 6.4 и 6.6). Стенд ``knowledge_stack`` с графом и фейковой моделью
# (``stack.model``); серверный якорь блока — ``knowledge.context.served`` с ``request_id`` ответа
# ``/v1/context``, полученного страницей; адрес (``kinds``, ``verified``) — интерфейсный
# результат без клиентского журнала.

ECX = "epoch-context"
BLOCK = "Контекст на странице эпохи"
EXTEND = "Достройка контекста моделью"
MARK = "Пометка непроверенного контекста"
MECH = "Механизм влияния"
CONTEXT_API = "**/api/knowledge/v1/context*"
GRAPH_API = "**/api/knowledge/v1/graph/build"
SERVED = "knowledge.context.served"
LOCKE_DOCTRINE = "Политическая философия Локка"


def _parse(text: str):
    from philograph.knowledge.dates import parse

    return parse(text)


def _common():
    from philograph.knowledge.statements import Attribution

    return [Attribution("common")]


def context_world(stack, *, sourced: bool = True) -> dict[str, str]:
    """Данные «Контекста Просвещения»: две эпохи, четыре события, Лондон, учение Локка;
    связь «Славная революция → Политическая философия Локка» (political, по источникам,
    подтверждена абзацем «Учебника N»)."""
    from philograph.knowledge.statements import Attribution, Evidence, Provenance

    world = stack.world
    ids = {
        "sci": world.thing("epoch", "Научная революция", "1543–1687"),
        "enl": world.thing("epoch", "Просвещение", "1680–1800"),
        "newton": world.thing("event", "Выход «Начал» Ньютона", "1687"),
        "glorious": world.thing("event", "Славная революция", "1688"),
        "bubble": world.thing("event", "Южноморский пузырь", "1720"),
        "encyclopedia": world.thing("event", "Выход первого тома «Энциклопедии»", "1751"),
        "london": world.thing("place", "Лондон"),
        "locke_doctrine": world.thing("doctrine", LOCKE_DOCTRINE),
    }
    for key, kind in (
        ("glorious", "political"),
        ("newton", "scientific"),
        ("encyclopedia", "intellectual"),
        ("bubble", "economic"),
    ):
        world.statements.add(
            ids[key], "event_kind", value=kind, attributions=[Attribution("common")]
        )
    world.relate(ids["glorious"], "happened_in", ids["london"])
    if sourced:
        textbook = stack.textbooks["N"]
        ids["p_1"] = stack.paragraph("N", "Кант пишет об опыте")
        ids["link"] = world.statements.add(
            ids["glorious"],
            "stimulated",
            obj=ids["locke_doctrine"],
            qualifiers={"mechanism": "political"},
            attributions=[Attribution("source", textbook)],
            evidence=[Evidence(ids["p_1"], "Кант пишет об опыте", source_id=textbook)],
            provenance=Provenance("extracted"),
        )
    return ids


def open_context(make, stack, epoch: str, query: str = "", *, width=1920, height=1080):
    context = make(width, height)
    page = context.new_page()
    page.set_default_timeout(8000)
    with page.expect_response(CONTEXT_API) as info:
        page.goto(f"{stack.url}/epochs/{epoch}{'?' + query if query else ''}")
    block(page).wait_for()
    expect(block(page)).to_have_attribute("aria-busy", "false")
    return page, info.value


def block(page):
    return page.locator("section.epochs-context")


def context_event(page, entity: str):
    return page.locator(f".epochs-context__event[data-event='{entity}']")


def groups(page) -> list[str]:
    return page.locator(".epochs-context__group").evaluate_all(
        "els => els.map(e => e.dataset.group)"
    )


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("→", "")).strip()


def disable_generation(context) -> None:
    """Читатель выключил достройку моделью в настройках (хранилище браузера)."""
    from ..helpers import NOTICE_VERSION, STORAGE_KEY

    state = {
        "version": 3,
        "notice": NOTICE_VERSION,
        "settings": {"generation": False, "sourcesOnly": False, "onlyTextbook": False},
    }
    context.add_init_script(
        f"if (!localStorage.getItem('philograph:v4')) localStorage.setItem("
        f"'{STORAGE_KEY}', {json.dumps(json.dumps(state))});"
    )


@req(ECX, BLOCK, scenario="Блок контекста")
def test_context_block(knowledge_context, knowledge_stack, events):
    w = context_world(knowledge_stack)
    page, response = open_context(knowledge_context, knowledge_stack, w["enl"])
    expect(block(page).locator("#epochs-context-title")).to_have_text("Контекст эпохи")
    # Под описанием эпохи.
    title_box = heading(page).bounding_box()
    assert block(page).bounding_box()["y"] > title_box["y"]
    assert groups(page) == ["political", "economic", "scientific", "intellectual"]
    titles = page.locator(".epochs-context__group-title").all_inner_texts()
    assert titles == ["Политика", "Экономика", "Наука", "Идеи"]
    glorious = context_event(page, w["glorious"])
    assert glorious.locator("xpath=ancestor::section[1]").get_attribute("data-group") == "political"
    assert flat(glorious.locator(".epochs-context__event-title").inner_text()) == (
        "1688 Славная революция · Лондон"
    )
    [row] = glorious.locator(".epochs-context__link").all()
    assert flat(row.inner_text()).startswith(
        "Политическая философия Локка · политический · по источникам · ¶"
    ), row.inner_text()
    assert row.get_attribute("data-unverified") == "false"
    assert row.locator(".epochs-context__evidence").get_attribute("href") == f"/p/{w['p_1']}"
    bubble = context_event(page, w["bubble"])
    assert flat(bubble.locator(".epochs-context__event-title").inner_text()) == (
        "1720 Южноморский пузырь"
    )
    expect(bubble.locator(".epochs-context__no-links")).to_have_text("связей пока нет")
    newton = context_event(page, w["newton"])
    assert flat(newton.locator(".epochs-context__event-title").inner_text()) == (
        "1687 Выход «Начал» Ньютона"
    )
    enc = context_event(page, w["encyclopedia"])
    assert flat(enc.locator(".epochs-context__event-title").inner_text()) == (
        "1751 Выход первого тома «Энциклопедии»"
    )
    for absent in ("Общество", "Религия", "Биография", "Прочее"):
        assert absent not in titles
    served = event_of(events, response, SERVED)
    assert (served["mode"], served["events"]) == ("epoch", 4)
    no_page_errors(page)


@req(ECX, BLOCK, scenario="Фильтр групп")
def test_context_kind_filter(knowledge_context, knowledge_stack, events):
    w = context_world(knowledge_stack)
    page, _ = open_context(knowledge_context, knowledge_stack, w["enl"])
    science = block(page).locator(".epochs-context__kind[data-kind='scientific']")
    expect(science).to_have_attribute("aria-pressed", "false")
    with page.expect_response(CONTEXT_API) as again:
        science.click()
    expect(block(page)).to_have_attribute("aria-busy", "false")
    expect(page.locator(".epochs-context__event")).to_have_count(1)
    expect(context_event(page, w["newton"])).to_have_count(1)
    expect(science).to_have_attribute("aria-pressed", "true")
    assert parse_qs(urlparse(page.url).query).get("kinds") == ["scientific"]
    served = event_of(events, again.value, SERVED)
    assert served["events"] == 1
    # Счётчики групп не зависят от фильтра.
    expect(block(page).locator(".epochs-context__kind[data-kind='political']")).to_contain_text("1")
    no_page_errors(page)


@req(ECX, BLOCK, invariant="фильтры из адреса страницы (kinds, verified=1) применяются при входе")
def test_context_filters_from_address(knowledge_context, knowledge_stack, events):
    from philograph.knowledge.statements import Provenance

    w = context_world(knowledge_stack)
    knowledge_stack.world.statements.add(
        w["newton"], "stimulated", obj=w["locke_doctrine"], provenance=Provenance("generated")
    )
    page, response = open_context(
        knowledge_context, knowledge_stack, w["enl"], "kinds=scientific,political&verified=1"
    )
    assert sorted(groups(page)) == ["political", "scientific"]
    assert page.locator(".epochs-context__link[data-unverified='true']").count() == 0
    expect(block(page).get_by_label("Только проверенные")).to_be_checked()
    query = parse_qs(urlparse(response.url).query)
    assert query.get("verified") == ["true"]
    served = event_of(events, response, SERVED)
    assert (served["events"], served["generated_links"]) == (2, 0)
    no_page_errors(page)


@req(ECX, BLOCK, scenario="Закрытый источник")
def test_context_closed_source(knowledge_context, knowledge_stack, events):
    from philograph.knowledge.statements import Attribution, Evidence, Provenance

    w = context_world(knowledge_stack, sourced=False)
    closed = knowledge_stack.textbooks["R"]
    p_9 = knowledge_stack.paragraph("R", "парламент низложил короля")
    link = knowledge_stack.world.statements.add(
        w["glorious"],
        "stimulated",
        obj=w["locke_doctrine"],
        qualifiers={"mechanism": "political"},
        attributions=[Attribution("source", closed)],
        evidence=[Evidence(p_9, "парламент низложил короля", source_id=closed)],
        provenance=Provenance("extracted"),
    )
    page, response = open_context(knowledge_context, knowledge_stack, w["enl"])
    row = page.locator(f".epochs-context__link[data-statement='{link}']")
    expect(row).to_have_count(1)
    expect(row.locator(".pg-status")).to_have_text("по источникам")
    assert row.locator(".epochs-context__evidence").count() == 0
    assert "¶" not in row.inner_text()
    body = response.text()
    [api_link] = {e["id"]: e for e in response.json()["events"]}[w["glorious"]]["stimulated"]
    assert api_link["evidence"] == [] and api_link["status"] == "sourced"
    assert p_9 not in body and "парламент низложил короля" not in body
    assert "парламент низложил короля" not in page.content()
    event_of(events, response, SERVED)
    no_page_errors(page)


@req(ECX, BLOCK, scenario="Контекста нет")
def test_context_empty(knowledge_context, knowledge_stack, events):
    world = knowledge_stack.world
    enl = world.thing("epoch", "Просвещение", "1680–1800")
    world.person("Иммануил Кант", "1724", "1804")  # не событие — в контекст не попадает
    page, response = open_context(knowledge_context, knowledge_stack, enl)
    expect(block(page).locator(".epochs-context__empty")).to_have_text(
        "Для этой эпохи контекст пока не собран."
    )
    assert page.locator(".epochs-context__event").count() == 0
    assert event_of(events, response, SERVED)["events"] == 0
    no_page_errors(page)


@req(ECX, BLOCK, scenario="Разметка в названии события")
def test_context_markup_in_event_name(knowledge_context, knowledge_stack, events):
    world = knowledge_stack.world
    enl = world.thing("epoch", "Просвещение", "1680–1800")
    hostile = world.thing("event", XSS, "1720")
    target = world.thing("doctrine", XSS + " учение")
    world.relate(hostile, "stimulated", target)
    page, response = open_context(knowledge_context, knowledge_stack, enl)
    name = context_event(page, hostile).locator(".epochs-context__name")
    expect(name).to_have_text(XSS)
    expect(context_event(page, hostile).locator(".epochs-context__target")).to_have_text(
        XSS + " учение"
    )
    assert page.locator(".epochs-context img").count() == 0
    assert page.evaluate("typeof window.__xss") == "undefined"
    assert event_of(events, response, SERVED)["events"] == 1
    no_page_errors(page)


@req(ECX, BLOCK, invariant="ошибка загрузки — «Повторить», без pageerror и console.error")
def test_context_error_and_retry(knowledge_context, knowledge_stack, events):
    w = context_world(knowledge_stack)
    context = knowledge_context()
    page = context.new_page()
    page.route(
        CONTEXT_API, lambda r: r.fulfill(status=503, json={"error": "Сервис временно недоступен"})
    )
    page.goto(f"{knowledge_stack.url}/epochs/{w['enl']}")
    expect(block(page).get_by_text("Контекст временно недоступен.")).to_be_visible()
    retry = block(page).get_by_role("button", name="Повторить")
    assert events.of(SERVED) == []  # ответ подменён: до сервиса запрос не дошёл
    page.unroute(CONTEXT_API)
    with page.expect_response(CONTEXT_API) as again:
        retry.click()
    expect(context_event(page, w["glorious"])).to_have_count(1)
    assert event_of(events, again.value, SERVED)["events"] == 4
    no_page_errors(page)


@req(ECX, BLOCK, invariant="показана часть при truncated")
def test_context_partial(knowledge_context, knowledge_stack, events):
    from philograph.knowledge.statements import Attribution

    world = knowledge_stack.world
    enl = world.thing("epoch", "Просвещение", "1680–1800")
    for i in range(201):
        event = world.thing("event", f"Событие {i:03d}", str(1700 + i % 90))
        if i:  # у «Событие 000» вида нет — оно наименее значимое
            world.statements.add(
                event, "event_kind", value="social", attributions=[Attribution("common")]
            )
    page, response = open_context(knowledge_context, knowledge_stack, enl)
    expect(block(page).locator(".epochs-context__partial")).to_have_text(
        "Показана часть событий: самые значимые 200 из 201."
    )
    assert page.locator(".epochs-context__event").count() == 200
    served = event_of(events, response, SERVED)
    assert served["truncated"] is True and served["events"] == 200
    no_page_errors(page)


@req(
    ECX, BLOCK, invariant="с клавиатуры: группы — кнопки с aria-pressed, ссылки и кнопки в порядке"
)
def test_context_keyboard(knowledge_context, knowledge_stack, events):
    w = context_world(knowledge_stack)
    page, _ = open_context(knowledge_context, knowledge_stack, w["enl"])
    kinds = block(page).locator("[role=group] button")
    assert kinds.count() >= 5
    assert all(
        kinds.nth(i).get_attribute("aria-pressed") in ("true", "false")
        for i in range(kinds.count())
    )
    science = block(page).locator(".epochs-context__kind[data-kind='scientific']")
    science.focus()
    with page.expect_response(CONTEXT_API) as again:
        page.keyboard.press("Enter")
    expect(science).to_have_attribute("aria-pressed", "true")
    assert event_of(events, again.value, SERVED)["events"] == 1
    # Все ссылки и кнопки блока доступны с Tab, порядок Tab — порядок чтения (сверху вниз,
    # в строке — слева направо).
    science.focus()
    with page.expect_response(CONTEXT_API):
        page.keyboard.press("Enter")  # снять фильтр
    expect(page.locator(".epochs-context__event")).to_have_count(4)
    expected = block(page).locator("a[href], button, input").count()
    block(page).locator("input[type=checkbox]").focus()
    seen = []
    for _ in range(expected + 5):
        info = page.evaluate(
            """() => { const e = document.activeElement;
                const inside = !!e.closest('section.epochs-context');
                const r = e.getBoundingClientRect();
                const b = document.querySelector('section.epochs-context').getBoundingClientRect();
                return {inside, cls: e.className, y: r.y - b.y + r.height / 2, x: r.x - b.x}; }"""
        )
        if not info["inside"]:
            break
        seen.append(info)
        page.keyboard.press("Tab")
    assert len(seen) == expected, (len(seen), expected, [s["cls"] for s in seen])
    for a, b in pairwise(seen):
        same_row = abs(a["y"] - b["y"]) <= 8
        assert (same_row and b["x"] > a["x"]) or (not same_row and b["y"] > a["y"]), (a, b)
    kinds_seen = [s for s in seen if "epochs-context__kind" in s["cls"]]
    assert kinds_seen and seen.index(kinds_seen[0]) < 3  # виды — первыми после переключателя
    no_page_errors(page)


@req(ECX, MARK, scenario="Сгенерированная связь помечена")
def test_generated_link_marked_on_page(knowledge_context, knowledge_stack, events):
    from philograph.knowledge.statements import Provenance

    w = context_world(knowledge_stack)
    generated = knowledge_stack.world.statements.add(
        w["newton"],
        "stimulated",
        obj=w["locke_doctrine"],
        provenance=Provenance("generated", actor="graph"),
    )
    page, response = open_context(knowledge_context, knowledge_stack, w["enl"])
    row = page.locator(f".epochs-context__link[data-statement='{generated}']")
    expect(row).to_have_attribute("data-unverified", "true")
    expect(row.locator(".pg-status")).to_have_text("не проверено")
    [api] = {e["id"]: e for e in response.json()["events"]}[w["newton"]]["stimulated"]
    assert api["generated"] is True and api["status"] == "generated"
    assert event_of(events, response, SERVED)["generated_links"] == 1
    no_page_errors(page)


@req(ECX, MARK, invariant="сгенерированная связь не показывается без пометки (страница эпохи)")
def test_every_generated_row_marked(knowledge_context, knowledge_stack, events):
    from philograph.knowledge.statements import Provenance

    w = context_world(knowledge_stack)
    world = knowledge_stack.world
    for event in ("newton", "bubble", "encyclopedia", "glorious"):
        world.statements.add(
            w[event],
            "stimulated",
            obj=world.thing("doctrine", f"Учение от {event}"),
            provenance=Provenance("generated"),
        )
    page, response = open_context(knowledge_context, knowledge_stack, w["enl"])
    generated = {
        link["statement_id"]
        for e in response.json()["events"]
        for link in e["stimulated"]
        if link["generated"]
    }
    assert len(generated) == 4
    for sid in generated:
        row = page.locator(f".epochs-context__link[data-statement='{sid}']")
        expect(row).to_have_attribute("data-unverified", "true")
        expect(row).to_contain_text("не проверено")
    marked = page.locator(".epochs-context__link[data-unverified='true']").count()
    assert marked == 4
    # «Только проверенные» — пометок нет, события на месте, адрес verified=1.
    with page.expect_response(CONTEXT_API) as again:
        block(page).get_by_label("Только проверенные").check()
    expect(page.locator(".epochs-context__link[data-unverified='true']")).to_have_count(0)
    expect(page.locator(".epochs-context__event")).to_have_count(4)
    assert parse_qs(urlparse(page.url).query).get("verified") == ["1"]
    assert event_of(events, again.value, SERVED)["generated_links"] == 0
    no_page_errors(page)


@req(ECX, MECH, scenario="Механизм не указан")
def test_mechanism_missing_on_page(knowledge_context, knowledge_stack, events):
    w = context_world(knowledge_stack, sourced=False)
    sid = knowledge_stack.world.relate(w["glorious"], "stimulated", w["locke_doctrine"])
    page, response = open_context(knowledge_context, knowledge_stack, w["enl"])
    row = page.locator(f".epochs-context__link[data-statement='{sid}']")
    expect(row.locator(".epochs-context__mechanism")).to_have_text("механизм не указан")
    [api] = {e["id"]: e for e in response.json()["events"]}[w["glorious"]]["stimulated"]
    assert api["mechanism"] is None
    event_of(events, response, SERVED)
    no_page_errors(page)


# --- Достройка контекста моделью ---------------------------------------------------------------


def push_proposals(stack, *items: dict) -> None:
    stack.model.push(json.dumps({"statements": list(items)}, ensure_ascii=False))


TREATISES = "Два трактата о правлении"


def extend_world(stack) -> dict[str, str]:
    w = context_world(stack)
    w["treatises"] = stack.world.thing("work", TREATISES, "1689")
    w["locke"] = stack.world.person("Джон Локк", "1632", "1704")
    return w


def extend(page, event: str):
    """Нажать «Достроить контекст» и дождаться ответа потока и перезапроса контекста."""
    button = context_event(page, event).get_by_role("button", name="Достроить контекст")
    with page.expect_response(GRAPH_API) as stream:
        button.click()
    return stream.value


@req(ECX, EXTEND, scenario="Достроить контекст")
def test_extend_context(knowledge_context, knowledge_stack, events):
    w = extend_world(knowledge_stack)
    push_proposals(
        knowledge_stack,
        {
            "subject": "Славная революция",
            "relation": "stimulated",
            "object": TREATISES,
            "mechanism": "political",
        },
        {"subject": "Славная революция", "relation": "influenced_by", "object": "Джон Локк"},
    )
    page, _ = open_context(knowledge_context, knowledge_stack, w["enl"])
    with page.expect_response(CONTEXT_API) as refetch:
        stream = extend(page, w["glorious"])
    assert stream.status == 200
    row = context_event(page, w["glorious"]).locator(
        ".epochs-context__link", has=page.locator(".epochs-context__target", has_text=TREATISES)
    )
    expect(row).to_have_attribute("data-unverified", "true")
    expect(row.locator(".epochs-context__mechanism")).to_have_text("механизм не указан")
    expect(row).to_contain_text("не проверено")
    assert len(knowledge_stack.model.calls) == 1
    [extended] = events.of("knowledge.graph.extended")
    assert extended["recipe"] == "context" and extended["entity_id"] == w["glorious"]
    assert (extended["proposed"], extended["dropped"]) == (1, 1)
    [dropped] = events.of("knowledge.graph.proposal_dropped")
    assert dropped["reason"] == "outside_recipe"
    event_of(events, refetch.value, SERVED)
    # Сохранение — воркер очереди; затем у утверждения нет механизма, статус «сгенерировано».
    assert knowledge_stack.queue.run_until_empty() == 1
    assert events.one("knowledge.graph.saved")["statements"] == 1
    [stored] = [
        s
        for s in knowledge_stack.world.statements.about(w["glorious"], types=["stimulated"])
        if s["object"] == w["treatises"]
    ]
    assert stored["qualifiers"] == {} and stored["status"] == "generated"
    with page.expect_response(CONTEXT_API) as reloaded:
        page.reload()
    saved_row = page.locator(f".epochs-context__link[data-statement='{stored['id']}']")
    expect(saved_row).to_have_attribute("data-unverified", "true")
    expect(saved_row.locator(".epochs-context__mechanism")).to_have_text("механизм не указан")
    assert event_of(events, reloaded.value, SERVED)["generated_links"] == 1
    no_page_errors(page)


@req(ECX, EXTEND, scenario="Уже достраивали")
def test_extend_done_before(knowledge_context, knowledge_stack, events):
    w = extend_world(knowledge_stack)
    push_proposals(
        knowledge_stack,
        {"subject": "Славная революция", "relation": "stimulated", "object": TREATISES},
    )
    page, _ = open_context(knowledge_context, knowledge_stack, w["enl"])
    with page.expect_response(CONTEXT_API):
        extend(page, w["glorious"])
    calls = len(knowledge_stack.model.calls)
    assert calls == 1
    events.clear()
    with page.expect_response(CONTEXT_API):
        extend(page, w["glorious"])
    expect(context_event(page, w["glorious"]).locator(".epochs-context__notice")).to_have_text(
        "Контекст этого события уже достраивали."
    )
    assert len(knowledge_stack.model.calls) == calls
    assert events.where("knowledge.graph.built", extension="done_before")
    events.assert_none("knowledge.graph.extended")
    no_page_errors(page)


@req(ECX, EXTEND, scenario="Связей достаточно")
def test_extend_not_needed(knowledge_context, knowledge_stack, events):
    w = extend_world(knowledge_stack)
    world = knowledge_stack.world
    for name in ("Деизм", "Веротерпимость", "Общественный договор", "Права человека"):
        world.relate(w["bubble"], "stimulated", world.thing("doctrine", name))
    world.relate(w["bubble"], "happened_in", w["london"])  # пятая связь семейства «контекст»
    page, _ = open_context(knowledge_context, knowledge_stack, w["enl"])
    with page.expect_response(CONTEXT_API):
        extend(page, w["bubble"])
    expect(context_event(page, w["bubble"]).locator(".epochs-context__notice")).to_have_text(
        "Связей достаточно, достройка не нужна."
    )
    assert knowledge_stack.model.calls == []
    assert events.where("knowledge.graph.built", extension="not_needed")
    events.assert_none("knowledge.graph.extended")
    no_page_errors(page)


@req(ECX, EXTEND, scenario="Генерация выключена")
def test_extend_hidden_without_generation(knowledge_context, knowledge_stack, events):
    w = extend_world(knowledge_stack)
    context = knowledge_context()
    disable_generation(context)
    page = context.new_page()
    with page.expect_response(CONTEXT_API) as response:
        page.goto(f"{knowledge_stack.url}/epochs/{w['enl']}")
    expect(block(page)).to_have_attribute("aria-busy", "false")
    expect(context_event(page, w["glorious"])).to_have_count(1)
    assert page.get_by_role("button", name="Достроить контекст").count() == 0
    assert (
        page.evaluate(
            "JSON.parse(localStorage.getItem('philograph:v4') || '{}').settings?.generation"
        )
        is False
    )
    event_of(events, response.value, SERVED)
    events.assert_none("knowledge.graph.extended")
    assert knowledge_stack.model.calls == []
    no_page_errors(page)


@req(ECX, EXTEND, invariant="причина без вызова модели: только выбранный учебник (scope)")
def test_extend_scope_message(knowledge_context, knowledge_stack, events):
    from ..helpers import NOTICE_VERSION, STORAGE_KEY

    w = extend_world(knowledge_stack)
    context = knowledge_context()
    state = {
        "version": 3,
        "notice": NOTICE_VERSION,
        "currentSource": knowledge_stack.textbooks["N"],
        "openSources": [{"id": knowledge_stack.textbooks["N"], "openedAt": 1}],
        "settings": {"generation": True, "sourcesOnly": False, "onlyTextbook": True},
    }
    context.add_init_script(
        f"if (!localStorage.getItem('philograph:v4')) localStorage.setItem("
        f"'{STORAGE_KEY}', {json.dumps(json.dumps(state))});"
    )
    page = context.new_page()
    with page.expect_response(CONTEXT_API):
        page.goto(f"{knowledge_stack.url}/epochs/{w['enl']}")
    expect(context_event(page, w["glorious"])).to_have_count(1)
    with page.expect_response(CONTEXT_API):
        extend(page, w["glorious"])
    expect(context_event(page, w["glorious"]).locator(".epochs-context__notice")).to_have_text(
        "В режиме «только выбранный учебник» достройки нет."
    )
    assert knowledge_stack.model.calls == []
    assert events.where("knowledge.graph.built", extension="scope")
    no_page_errors(page)


# --- после ревью, круг 1 -----------------------------------------------------------------------


@req(
    ECX,
    MARK,
    invariant="«только проверенные» скрывает и связи, только что добавленные достройкой",
)
def test_verified_hides_just_extended(knowledge_context, knowledge_stack, events):
    w = extend_world(knowledge_stack)
    push_proposals(
        knowledge_stack,
        {"subject": "Славная революция", "relation": "stimulated", "object": TREATISES},
    )
    page, first = open_context(knowledge_context, knowledge_stack, w["enl"], "verified=1")
    expect(block(page).get_by_label("Только проверенные")).to_be_checked()
    assert event_of(events, first, SERVED)["generated_links"] == 0
    with page.expect_response(CONTEXT_API) as refetch:
        stream = extend(page, w["glorious"])
    assert stream.status == 200
    expect(block(page)).to_have_attribute("aria-busy", "false")
    # Достройка прошла: модель вызвана, связь предложена (событие по request_id потока).
    rid = stream.headers.get("x-request-id")
    assert rid
    [extended] = events.where("knowledge.graph.extended", request_id=rid)
    assert extended["recipe"] == "context" and extended["proposed"] == 1
    assert len(knowledge_stack.model.calls) == 1
    # Под отмеченным фильтром сгенерированной строки нет — ни до сохранения, ни после.
    glorious = context_event(page, w["glorious"])
    expect(glorious.locator(".epochs-context__target", has_text=TREATISES)).to_have_count(0)
    assert page.locator(".epochs-context__link[data-unverified='true']").count() == 0
    assert parse_qs(urlparse(refetch.value.url).query).get("verified") == ["true"]
    assert event_of(events, refetch.value, SERVED)["generated_links"] == 0
    # Снятый фильтр показывает добавленную строку с пометкой.
    with page.expect_response(CONTEXT_API):
        block(page).get_by_label("Только проверенные").uncheck()
    row = glorious.locator(
        ".epochs-context__link", has=page.locator(".epochs-context__target", has_text=TREATISES)
    )
    expect(row).to_have_attribute("data-unverified", "true")
    no_page_errors(page)


@req(ECX, BLOCK, invariant="ссылка «Wikidata ↗» события — только из проверенного QID")
def test_event_wikidata_link(knowledge_context, knowledge_stack, events):
    from sqlalchemy import insert

    from philograph.knowledge import schema

    world = knowledge_stack.world
    enl = world.thing("epoch", "Просвещение", "1680–1800")
    good = world.entities.create(
        "event", [("ru", "Французская революция", "primary")], external={"wikidata": "Q6534"}
    )
    world.statements.add(good, "dating", value=_parse("1789").to_json(), attributions=_common())
    bad = world.thing("event", "Событие с испорченным QID", "1720")
    with world.engine.begin() as conn:
        conn.execute(
            insert(schema.external_ids).values(
                entity_id=bad, system="wikidata", value='Q1x" onmouseover="alert(1)'
            )
        )
    plain = world.thing("event", "Южноморский пузырь", "1720")
    page, response = open_context(knowledge_context, knowledge_stack, enl)
    link = context_event(page, good).locator(".epochs-context__wikidata")
    expect(link).to_have_count(1)
    assert link.get_attribute("href") == "https://www.wikidata.org/wiki/Q6534"
    assert "Wikidata" in link.inner_text()
    for entity in (bad, plain):
        assert context_event(page, entity).locator(".epochs-context__wikidata").count() == 0
    records = {e["id"]: e for e in response.json()["events"]}
    assert (records[good]["wikidata"], records[bad]["wikidata"], records[plain]["wikidata"]) == (
        "Q6534",
        None,
        None,
    )
    assert event_of(events, response, SERVED)["events"] == 3
    no_page_errors(page)


@req(ECX, BLOCK, invariant="вид из адреса без событий — нажатая кнопка и пустое состояние")
def test_kind_from_address_without_events(knowledge_context, knowledge_stack, events):
    w = context_world(knowledge_stack)
    page, response = open_context(knowledge_context, knowledge_stack, w["enl"], "kinds=social")
    social = block(page).locator(".epochs-context__kind[data-kind='social']")
    expect(social).to_have_attribute("aria-pressed", "true")
    expect(social).to_contain_text("0")
    assert page.locator(".epochs-context__event").count() == 0
    expect(block(page).locator(".epochs-context__empty")).to_have_text(
        "Событий выбранных видов в этой эпохе нет."
    )
    served = event_of(events, response, SERVED)
    assert served["events"] == 0
    # Отжатая кнопка возвращает все события.
    with page.expect_response(CONTEXT_API) as again:
        social.click()
    expect(page.locator(".epochs-context__event")).to_have_count(4)
    assert event_of(events, again.value, SERVED)["events"] == 4
    no_page_errors(page)
