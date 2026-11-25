"""epochs («Страница эпох», «Клавиатура и доступность страницы эпох») и visual-design
(«Старая закладка эпох») в браузере (add-epochs, задача 5.6).

Стенд — ``knowledge_stack``: настоящий шлюз, библиотека и сервис знаний; данные онтологии
задаёт тест через ``stack.world`` до открытия страницы. Адрес, выбор и фокус — интерфейсные
результаты без клиентского журнала; серверный якорь — ``knowledge.epochs.listed`` и
``knowledge.catalog.listed`` с ``request_id`` ответов, полученных страницей. ``page.route`` —
только для 503 и задержки.
"""

from __future__ import annotations

import re
from itertools import combinations
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
    link = nav.get_by_role("link", name="Эпохи")
    assert link.get_attribute("href") == "/epochs"
    assert "скоро" not in link.inner_text().lower()
    assert link.get_attribute("aria-current") == "page"
    assert event_of(events, anchor.value)["epochs"] == 2
    page.go_back()
    page.wait_for_url(re.compile(r"/$"))
    assert "/soon/" not in page.url
    no_page_errors(page)
