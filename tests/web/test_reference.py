"""entity-catalog (страница справочника) и visual-design («Разделы в разработке») в браузере.

Стенд — ``knowledge_stack`` (``tests/web/knowledge_stack.py``): настоящий шлюз, библиотека и
сервис знаний; данные онтологии задаёт тест через ``stack.world`` до открытия страницы.
Интерфейсный результат (адрес, фокус, DOM) проверяется на странице, серверный — событием
сервиса знаний с ``request_id`` из ответа, который получила страница. ``page.route`` — только
для 503, задержки и гонки; время ввода — ``page.clock``.
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from itertools import combinations
from urllib.parse import parse_qs, quote, unquote, urlparse

import pytest
from playwright.sync_api import expect

from ..helpers import sidenav

req = pytest.mark.req
EC = "entity-catalog"
VD = "visual-design"
PAGE = "Страница справочника"
STATES = "Состояния страницы справочника"
SAFE = "Безопасный вывод справочника"
KEYS = "Клавиатура и доступность справочника"
LISTED = "knowledge.catalog.listed"
CATALOG = "**/api/knowledge/v1/catalog*"
ITEMS = ".reference-item:not(.reference-item--placeholder)"
XSS = '<img src=x onerror="window.__xss=1">'
expect.set_options(timeout=8000)


# --- помощники ----------------------------------------------------------------------------


def open_page(make, stack, path: str = "/reference", *, width=1920, height=1080, clock=False):
    context = make(width, height)
    page = context.new_page()
    page.set_default_timeout(8000)
    if clock:
        page.clock.install()
        page.clock.pause_at("2026-11-25T10:00:00")
    with page.expect_response(CATALOG):
        page.goto(stack.url + path)
    return page


def loaded(page) -> None:
    """Ответ показан: список не занят и «Найдено» объявлено."""
    page.locator('.reference__list[aria-busy="false"]').wait_for()


def names(page) -> list[str]:
    return page.locator(f"{ITEMS} .reference-item__name").all_inner_texts()


def item(page, label: str):
    return page.locator(ITEMS).filter(
        has=page.locator(".reference-item__name", has_text=re.compile(f"^{re.escape(label)}$"))
    )


def address(page) -> tuple[str, dict[str, str]]:
    url = urlparse(page.url)
    return url.path, {k: v[0] for k, v in parse_qs(url.query).items()}


def event_of(events, response, name: str = LISTED):
    """Единственное событие ``name`` запроса, ответ на который получила страница."""
    rid = response.headers.get("x-request-id")
    assert rid, response.url
    found = events.where(name, request_id=rid)
    assert len(found) == 1, (name, rid, events.names())
    return found[0]


@contextmanager
def catalog_response(page, predicate=None):
    """Ответ справочника, вызванный действием внутри блока."""

    def match(response):
        if "/api/knowledge/v1/catalog" not in response.url:
            return False
        return predicate(parse_qs(urlparse(response.url).query)) if predicate else True

    with page.expect_response(match) as info:
        yield info


def no_page_errors(page) -> None:
    assert page.context.errors == [], page.context.errors
    assert page.evaluate("window.__consoleErrors") == []


def select_of(page, caption: str):
    """Нативный выбор фильтра по его подписи («Эпоха», «Раздел», «Сортировка»)."""
    return (
        page.locator("label.reference__select")
        .filter(has=page.locator(".pg-field__label", has_text=re.compile(f"^{caption}$")))
        .locator("select")
    )


def type_search(page, text: str) -> None:
    box = page.locator("#reference-search")
    box.click()
    box.press_sequentially(text)


# --- Страница справочника -----------------------------------------------------------------


@req(EC, PAGE, scenario="Найти и открыть")
def test_find_and_open(knowledge_context, knowledge_stack, events):
    w = knowledge_stack.world.base()
    page = open_page(knowledge_context, knowledge_stack)
    loaded(page)
    expect(page.locator(ITEMS)).to_have_count(5)
    with catalog_response(page, lambda q: q.get("q") == ["юм"]) as search:
        type_search(page, "юм")
    expect(page.locator(ITEMS)).to_have_count(1)
    assert names(page) == ["Дэвид Юм"]
    assert address(page) == ("/reference", {"q": "юм"})
    assert unquote(page.url).endswith("/reference?q=юм")
    event = event_of(events, search.value)
    assert event["filters"] == ["q"] and event["q_len"] == 2
    with page.expect_response(re.compile(rf"/api/knowledge/v1/entities/{w['hume']}/card")) as card:
        item(page, "Дэвид Юм").locator(".reference-item__open").click()
    panel = page.locator("aside#side-panel")
    expect(panel).to_be_visible()
    expect(panel).to_contain_text("Дэвид Юм")
    served = event_of(events, card.value, "knowledge.card.served")
    assert served["entity_id"] == w["hume"]
    no_page_errors(page)


@req(EC, PAGE, scenario="Группа и эпоха из адреса")
def test_group_and_epoch_from_address(knowledge_context, knowledge_stack, events):
    w = knowledge_stack.world.epochs_and_people()
    context = knowledge_context()
    page = context.new_page()
    with catalog_response(page) as first:
        page.goto(f"{knowledge_stack.url}/reference?group=person&epoch={w['enl']}")
    loaded(page)
    people = page.get_by_role("group").get_by_role("button", name=re.compile("^Персоны"))
    expect(people).to_have_attribute("aria-pressed", "true")
    expect(people.locator(".reference__count")).to_have_text("2")
    epoch = select_of(page, "Эпоха")
    expect(epoch).to_have_value(w["enl"])
    assert epoch.evaluate("s => s.selectedOptions[0].textContent").startswith("Просвещение")
    assert sorted(names(page)) == sorted(["Дэвид Юм", "Иммануил Кант"])
    assert event_of(events, first.value)["filters"] == ["epoch", "type"]
    no_page_errors(page)


@req(EC, PAGE, scenario="Показать ещё")
def test_show_more(knowledge_context, knowledge_stack, events):
    for i in range(30):
        knowledge_stack.world.thing("concept", f"Понятие {i:02d}")
    page = open_page(knowledge_context, knowledge_stack)
    loaded(page)
    expect(page.locator(ITEMS)).to_have_count(24)
    more = page.get_by_role("button", name=re.compile("^Показать ещё"))
    with catalog_response(page, lambda q: q.get("page") == ["2"]) as second:
        more.click()
    expect(page.locator(ITEMS)).to_have_count(30)
    shown = names(page)
    assert len(set(shown)) == 30
    assert shown == [f"Понятие {i:02d}" for i in range(30)]
    expect(page.get_by_role("button", name=re.compile("^Показать ещё"))).to_have_count(0)
    focused = page.evaluate(
        "() => { const li = document.activeElement.closest('li.reference-item');"
        " return li ? [...li.parentElement.children].indexOf(li) : -1; }"
    )
    assert focused == 24  # 25-я запись, первая из новых
    expect(page.locator(":focus")).to_contain_text("Понятие 24")
    assert event_of(events, second.value)["page"] == 2
    no_page_errors(page)


@req(EC, PAGE, scenario="Задержка ввода")
def test_input_debounce(knowledge_context, knowledge_stack, events):
    knowledge_stack.world.base()
    knowledge_stack.world.person("Георг Кантор", "1845", "1918")
    page = open_page(knowledge_context, knowledge_stack, clock=True)
    page.clock.run_for(50)
    loaded(page)
    sent: list[dict] = []
    page.on(
        "request",
        lambda r: (
            sent.append(parse_qs(urlparse(r.url).query))
            if "/api/knowledge/v1/catalog" in r.url
            else None
        ),
    )
    box = page.locator("#reference-search")
    box.click()
    for i, char in enumerate("кан"):
        box.press_sequentially(char)
        page.clock.run_for(100 if i < 2 else 0)
    with catalog_response(page, lambda q: q.get("q") == ["кан"]) as answer:
        page.clock.run_for(250)
    expect(page.locator(ITEMS)).to_have_count(2)
    assert sorted(names(page)) == ["Георг Кантор", "Иммануил Кант"]
    assert [q.get("q") for q in sent] == [["кан"]]
    with_query = [e for e in events.of(LISTED) if e["q_len"] > 0]
    assert len(with_query) == 1 and with_query[0]["q_len"] == 3
    assert event_of(events, answer.value)["q_len"] == 3
    no_page_errors(page)


@req(EC, PAGE, scenario="Устаревший ответ")
def test_stale_response_discarded(knowledge_context, knowledge_stack, events):
    knowledge_stack.world.base()
    page = open_page(knowledge_context, knowledge_stack, clock=True)
    page.clock.run_for(50)
    loaded(page)
    held = []

    def hold(route):
        if parse_qs(urlparse(route.request.url).query).get("q") == ["ка"]:
            held.append(route)  # ответ на «ка» задержан до конца теста
        else:
            route.continue_()

    page.route(CATALOG, hold)
    box = page.locator("#reference-search")
    box.click()
    box.press_sequentially("ка")
    with page.expect_request(
        lambda r: "q=%D0%BA%D0%B0&" in r.url or r.url.endswith("q=%D0%BA%D0%B0")
    ):
        page.clock.run_for(300)
    assert len(held) == 1
    with catalog_response(page, lambda q: q.get("q") == ["кан"]) as newer:
        box.press_sequentially("н")
        page.clock.run_for(300)
    expect(page.locator(ITEMS)).to_have_count(1)
    assert names(page) == ["Иммануил Кант"]
    assert address(page) == ("/reference", {"q": "кан"})
    assert event_of(events, newer.value)["q_len"] == 3
    # Поздний ответ на «ка» (две записи: Кант и «Критика…») приходит после ответа на «кан».
    late = held[0]
    if late.request.failure is None:
        with page.expect_event("requestfinished", lambda r: r == late.request):
            late.continue_()
        page.evaluate("new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")
    else:
        late.abort()  # страница уже отменила устаревший запрос сама
    expect(page.locator(ITEMS)).to_have_count(1)
    assert names(page) == ["Иммануил Кант"]
    assert address(page) == ("/reference", {"q": "кан"})
    no_page_errors(page)


@req(EC, PAGE, scenario="На карте")
def test_on_the_map(knowledge_context, knowledge_stack, events):
    w = knowledge_stack.world.base()
    knowledge_stack.world.relate(w["kant"], "influenced_by", w["hume"])
    page = open_page(knowledge_context, knowledge_stack)
    loaded(page)
    with page.expect_response(re.compile(r"/api/knowledge/v1/map(\?|$)")) as built:
        item(page, "Иммануил Кант").locator(".reference-item__map").click()
    page.wait_for_url(re.compile(rf"/graph/{w['kant']}$"))
    selected = page.locator(".map-selected")
    expect(selected).to_contain_text("Иммануил Кант")
    assert event_of(events, built.value, "knowledge.map.built")["entities"] >= 2
    no_page_errors(page)


@req(EC, PAGE, scenario="Пометка сгенерированного")
def test_generated_mark(knowledge_context, knowledge_stack, events):
    w = knowledge_stack.world.base()
    knowledge_stack.world.describe(w["causality"], "Связь причины и следствия", generated=True)
    knowledge_stack.world.describe(w["kant"], "Немецкий философ")
    page = open_page(knowledge_context, knowledge_stack)
    loaded(page)
    mark = item(page, "Причинность").locator('[data-generated="true"]')
    expect(mark).to_have_count(1)
    # Подпись — та же, что у пометки в карточке (общий StatusMark): «Сгенерировано».
    assert mark.inner_text().strip().lower() == "сгенерировано"
    expect(item(page, "Иммануил Кант").locator('[data-generated="true"]')).to_have_count(0)
    assert knowledge_stack.catalog_responses()[-1].status == 200
    rid = knowledge_stack.catalog_responses()[-1].request_id
    assert events.where(LISTED, request_id=rid)[0]["total"] == 5
    no_page_errors(page)


@req(EC, PAGE, invariant="состояние в адресе: q, group, epoch, textbook, sort восстанавливаются")
def test_state_round_trip_through_address(knowledge_context, knowledge_stack, events):
    w = knowledge_stack.world.epochs_and_people()
    knowledge_stack.world.mention(w["kant"], knowledge_stack.textbooks["N"])
    knowledge_stack.world.mention(w["hume"], knowledge_stack.textbooks["N"])
    tb = knowledge_stack.textbooks["N"]
    path = f"/reference?q=%D0%B8&group=person&epoch={w['enl']}&textbook={tb}&sort=date"
    page = open_page(knowledge_context, knowledge_stack, path)
    loaded(page)
    assert page.locator("#reference-search").input_value() == "и"
    expect(select_of(page, "Раздел")).to_have_value(tb)
    expect(select_of(page, "Эпоха")).to_have_value(w["enl"])
    assert names(page) == ["Дэвид Юм", "Иммануил Кант"]  # по времени: 1711, 1724
    rid = knowledge_stack.catalog_responses()[-1].request_id
    event = events.where(LISTED, request_id=rid)[0]
    assert event["filters"] == ["epoch", "q", "textbook", "type"] and event["sort"] == "date"
    # Смена сортировки — в адресе; «Назад» возвращает прежнюю.
    with catalog_response(page, lambda q: q.get("sort") == ["label"]):
        select_of(page, "Сортировка").select_option("label")
    assert address(page)[1]["sort"] == "label"
    assert names(page) == ["Дэвид Юм", "Иммануил Кант"]
    with catalog_response(page, lambda q: q.get("sort") == ["date"]):
        page.go_back()
    assert address(page)[1]["sort"] == "date"
    no_page_errors(page)


# --- Состояния страницы справочника ---------------------------------------------------------


@req(EC, STATES, scenario="Ничего не найдено")
def test_nothing_found(knowledge_context, knowledge_stack, events):
    knowledge_stack.world.base()
    page = open_page(knowledge_context, knowledge_stack)
    loaded(page)
    with catalog_response(page, lambda q: q.get("q") == ["зззз"]) as empty:
        type_search(page, "зззз")
    expect(page.get_by_text("Ничего не найдено по запросу «зззз».", exact=True)).to_be_visible()
    reset = page.get_by_role("button", name="Сбросить фильтры")
    expect(reset).to_be_visible()
    expect(page.locator(ITEMS)).to_have_count(0)
    assert event_of(events, empty.value)["total"] == 0
    with catalog_response(page, lambda q: "q" not in q) as full:
        reset.click()
    page.wait_for_url(re.compile(r"/reference$"))
    expect(page.locator(ITEMS)).to_have_count(5)
    assert event_of(events, full.value)["filters"] == []
    no_page_errors(page)


@req(EC, STATES, scenario="Сервис недоступен")
def test_service_unavailable(knowledge_context, knowledge_stack, events):
    knowledge_stack.world.base()
    context = knowledge_context()
    page = context.new_page()
    page.route(
        CATALOG,
        lambda r: r.fulfill(
            status=503,
            json={"error": "Сервис временно недоступен", "kind": "knowledge_unavailable"},
        ),
    )
    page.goto(knowledge_stack.url + "/reference")
    expect(page.get_by_text("Справочник временно недоступен.")).to_be_visible()
    retry = page.get_by_role("button", name="Повторить")
    expect(retry).to_be_visible()
    box = page.locator("#reference-search")
    expect(box).to_be_enabled()
    with catalog_response(page, lambda q: q.get("q") == ["кант"]) as failed:
        box.fill("кант")
    assert failed.value.status == 503
    assert box.input_value() == "кант"
    expect(page.get_by_text("Справочник временно недоступен.")).to_be_visible()
    nav = sidenav(page)
    expect(nav.get_by_role("link", name="Справочник")).to_be_visible()
    assert events.of(LISTED) == []  # ответ подменён: до сервиса запрос не дошёл
    page.unroute(CATALOG)
    with catalog_response(page) as again:
        page.get_by_role("button", name="Повторить").click()
    expect(page.locator(ITEMS)).to_have_count(1)
    assert event_of(events, again.value)["q_len"] == 4
    via = nav.get_by_role("link", name="Библиотека")
    via.click()
    page.wait_for_url(re.compile(r"/$|/library"))
    no_page_errors(page)


@req(EC, STATES, invariant="ошибка сервиса: уже показанные записи остаются")
def test_error_keeps_shown_records(knowledge_context, knowledge_stack, events):
    knowledge_stack.world.base()
    page = open_page(knowledge_context, knowledge_stack)
    loaded(page)
    expect(page.locator(ITEMS)).to_have_count(5)
    page.route(CATALOG, lambda r: r.fulfill(status=503, body="Service Unavailable"))
    type_search(page, "юм")
    expect(page.get_by_text("Справочник временно недоступен.")).to_be_visible()
    expect(page.locator(ITEMS)).to_have_count(5)
    assert len(events.of(LISTED)) == 1
    no_page_errors(page)


@req(EC, STATES, scenario="Пустая онтология")
def test_empty_ontology(knowledge_context, knowledge_stack, events):
    # На стенде только сущности-источники «Учебник N» и «Учебник R».
    page = open_page(knowledge_context, knowledge_stack)
    loaded(page)
    expect(page.get_by_text(re.compile("^Справочник пока пуст"))).to_be_visible()
    expect(page.locator(ITEMS)).to_have_count(0)
    expect(page.locator(".reference__count")).to_have_count(0)
    rid = knowledge_stack.catalog_responses()[-1].request_id
    assert events.where(LISTED, request_id=rid)[0]["total"] == 0
    no_page_errors(page)


@req(EC, STATES, scenario="Учебник закрыт")
def test_closed_textbook(knowledge_context, knowledge_stack, events):
    w = knowledge_stack.world.base()
    closed = knowledge_stack.textbooks["R"]
    knowledge_stack.world.mention(w["kant"], closed)
    page = open_page(knowledge_context, knowledge_stack)
    loaded(page)
    with catalog_response(page, lambda q: q.get("textbook") == [closed]) as answer:
        select_of(page, "Раздел").select_option(closed)
    expect(page.get_by_text("Этот учебник недоступен в вашем регионе.")).to_be_visible()
    all_sources = page.get_by_role("button", name="Все источники")
    expect(all_sources).to_be_visible()
    expect(page.locator(ITEMS)).to_have_count(0)
    assert event_of(events, answer.value)["textbook_closed"] is True
    with catalog_response(page, lambda q: "textbook" not in q) as back:
        all_sources.click()
    expect(page.locator(ITEMS)).to_have_count(5)
    assert event_of(events, back.value)["textbook_closed"] is False
    no_page_errors(page)


@req(EC, STATES, invariant="загрузка: заполнители, строка поиска доступна, aria-busy=true")
def test_loading_state(knowledge_context, knowledge_stack, events):
    knowledge_stack.world.base()
    context = knowledge_context()
    page = context.new_page()
    held = []
    page.route(CATALOG, lambda r: held.append(r))
    page.goto(knowledge_stack.url + "/reference")
    page.wait_for_function("document.querySelector('.reference__list[aria-busy=\"true\"]')")
    assert page.locator(".reference-item--placeholder").count() > 0
    expect(page.locator(ITEMS)).to_have_count(0)
    expect(page.locator("#reference-search")).to_be_enabled()
    assert events.of(LISTED) == []
    with catalog_response(page) as answer:
        held[0].continue_()
    page.unroute(CATALOG)
    loaded(page)
    expect(page.locator(ITEMS)).to_have_count(5)
    assert event_of(events, answer.value)["total"] == 5
    no_page_errors(page)


# --- Безопасный вывод справочника ---------------------------------------------------------


@req(EC, SAFE, scenario="Разметка в названии и запросе")
def test_markup_in_name_and_query(knowledge_context, knowledge_stack, events):
    knowledge_stack.world.base()
    knowledge_stack.world.person(XSS, "1700", "1760")
    context = knowledge_context()
    page = context.new_page()
    url = f"{knowledge_stack.url}/reference?q={quote(XSS)}&epoch={quote('<script>')}"
    with (
        catalog_response(page, lambda q: q.get("epoch") == ["<script>"]) as rejected,
        catalog_response(page, lambda q: "epoch" not in q and q.get("q") == [XSS]) as plain,
    ):
        page.goto(url)
    assert rejected.value.status == 400
    assert (
        event_of(events, rejected.value, "knowledge.catalog.rejected")["reason"] == "unknown_epoch"
    )
    assert plain.value.status == 200
    assert event_of(events, plain.value)["filters"] == ["q"]
    expect(page.locator(ITEMS)).to_have_count(1)
    assert names(page) == [XSS]
    assert "<img" in page.locator(".reference__list").inner_text()
    assert page.locator("#reference-search").input_value() == XSS
    assert page.locator(".reference__list img").count() == 0
    assert page.evaluate("typeof window.__xss") == "undefined"
    assert "epoch" not in address(page)[1]
    no_page_errors(page)


HOSTILE_ADDRESSES = [
    "/reference?epoch=%3Cimg%20src%3Dx%20onerror%3D%22window.__xss%3D1%22%3E",
    "/reference?textbook=%3Cscript%3Ewindow.__xss%3D1%3C%2Fscript%3E",
    "/reference?group=%3Cb%3Ex%3C%2Fb%3E&sort=%22%3E%3Csvg%20onload%3Dwindow.__xss%3D1%3E",
    "/reference?q=" + quote("</li><script>window.__xss=1</script>"),
]


@pytest.mark.parametrize("path", HOSTILE_ADDRESSES)
@req(EC, SAFE, invariant="идентификаторы из адреса — текст; ошибки без pageerror/console.error")
def test_hostile_address_parameters(knowledge_context, knowledge_stack, events, path):
    knowledge_stack.world.base()
    page = open_page(knowledge_context, knowledge_stack, path)
    loaded(page)
    expect(page.locator(".reference")).to_be_visible()
    assert page.evaluate("typeof window.__xss") == "undefined"
    assert page.locator(".reference img, .reference script, .reference svg[onload]").count() == 0
    assert page.locator(".reference b").count() == 0
    seen = knowledge_stack.catalog_responses()
    assert seen and all(s.status in (200, 400) for s in seen)
    for s in seen:
        rid = s.request_id
        assert (
            len(
                events.where(LISTED, request_id=rid)
                + events.where("knowledge.catalog.rejected", request_id=rid)
            )
            == 1
        )
    no_page_errors(page)


@pytest.mark.parametrize("failure", ["abort", "html", "500"])
@req(EC, SAFE, invariant="ошибка загрузки любого запроса без pageerror и console.error")
def test_any_load_failure_handled(knowledge_context, knowledge_stack, events, failure):
    knowledge_stack.world.base()
    context = knowledge_context()
    page = context.new_page()

    def broken(route):
        if failure == "abort":
            route.abort()
        elif failure == "html":
            route.fulfill(status=200, body="<html>не JSON</html>", content_type="text/html")
        else:
            route.fulfill(status=500, body="")

    page.route("**/api/**", broken)  # справочник и список учебников библиотеки
    page.goto(knowledge_stack.url + "/reference")
    expect(page.get_by_text("Справочник временно недоступен.")).to_be_visible()
    expect(page.get_by_role("button", name="Повторить")).to_be_visible()
    assert events.of(LISTED) == []
    no_page_errors(page)


# --- Клавиатура и доступность справочника ---------------------------------------------------


@req(EC, KEYS, scenario="Клавиатура")
def test_keyboard(knowledge_context, knowledge_stack, events):
    w = knowledge_stack.world.base()
    page = open_page(knowledge_context, knowledge_stack)
    loaded(page)
    page.locator("h1").click()  # фокус не в поле ввода
    page.keyboard.press("/")
    expect(page.locator("#reference-search")).to_be_focused()
    with catalog_response(page, lambda q: q.get("q") == ["кант"]):
        page.keyboard.type("кант")
    expect(page.locator(ITEMS)).to_have_count(1)
    page.keyboard.press("ArrowDown")
    first = item(page, "Иммануил Кант").locator(".reference-item__open")
    expect(first).to_be_focused()
    with page.expect_response(re.compile(rf"/v1/entities/{w['kant']}/card")) as card:
        page.keyboard.press("Enter")
    expect(page.locator("aside#side-panel")).to_contain_text("Иммануил Кант")
    assert event_of(events, card.value, "knowledge.card.served")["entity_id"] == w["kant"]
    no_page_errors(page)


@req(EC, KEYS, invariant="стрелки по записям, «/» в поле не перехватывается, Esc очищает")
def test_keyboard_navigation_rules(knowledge_context, knowledge_stack, events):
    knowledge_stack.world.base()
    page = open_page(knowledge_context, knowledge_stack)
    loaded(page)
    box = page.locator("#reference-search")
    box.click()
    box.press("ArrowDown")
    order = names(page)
    focused = page.locator(":focus")
    expect(focused).to_contain_text(order[0])
    page.keyboard.press("ArrowDown")
    expect(page.locator(":focus")).to_contain_text(order[1])
    page.keyboard.press("ArrowUp")
    expect(page.locator(":focus")).to_contain_text(order[0])
    # «/» в поле ввода — обычный символ.
    box.click()
    with catalog_response(page, lambda q: q.get("q") == ["а/б"]) as typed:
        box.press_sequentially("а/б")
    assert box.input_value() == "а/б"
    assert event_of(events, typed.value)["q_len"] == 3
    with catalog_response(page, lambda q: "q" not in q) as cleared:
        box.press("Escape")
    assert box.input_value() == ""
    expect(page.locator(ITEMS)).to_have_count(5)
    assert event_of(events, cleared.value)["q_len"] == 0
    no_page_errors(page)


@req(EC, KEYS, invariant="группа кнопок с aria-pressed, список с подписью, aria-live=polite")
def test_accessibility_roles(knowledge_context, knowledge_stack, events):
    knowledge_stack.world.base()
    page = open_page(knowledge_context, knowledge_stack)
    loaded(page)
    group = page.get_by_role("group").filter(has=page.locator(".reference__type"))
    expect(group).to_have_count(1)
    assert group.get_attribute("aria-label")
    buttons = group.locator(".reference__type")
    assert buttons.count() == 9
    for i in range(buttons.count()):
        assert buttons.nth(i).get_attribute("aria-pressed") in ("true", "false")
    lst = page.locator("ul.reference__list")
    assert lst.get_attribute("aria-label")
    found = page.locator('[aria-live="polite"]').filter(has_text=re.compile("Найдено"))
    expect(found).to_have_text(re.compile(r"Найдено:\s*5"))
    rid = knowledge_stack.catalog_responses()[-1].request_id
    assert events.where(LISTED, request_id=rid)[0]["total"] == 5
    no_page_errors(page)


def _rects(page) -> dict[str, dict]:
    return page.evaluate(
        """() => {
          const pick = (s) => { const e = document.querySelector(s);
            if (!e) return null; const r = e.getBoundingClientRect();
            return {x: r.x, y: r.y, w: r.width, h: r.height}; };
          return {
            search: pick('#reference-search'),
            types: pick('.reference__types'),
            first: pick('.reference-item:not(.reference-item--placeholder)'),
          };
        }"""
    )


def _overlap(a, b) -> bool:
    return not (
        a["x"] + a["w"] <= b["x"]
        or b["x"] + b["w"] <= a["x"]
        or a["y"] + a["h"] <= b["y"]
        or b["y"] + b["h"] <= a["y"]
    )


@pytest.mark.parametrize(("width", "height"), [(1024, 576), (1920, 1080)])
@req(EC, KEYS, scenario="Малое окно")
def test_layout_fits_window(knowledge_context, knowledge_stack, events, width, height):
    knowledge_stack.world.base()
    for i in range(30):
        knowledge_stack.world.thing("concept", f"Очень длинное название понятия номер {i:02d}")
    page = open_page(knowledge_context, knowledge_stack, width=width, height=height)
    loaded(page)
    page.evaluate("document.fonts.ready.then(() => true)")
    rects = _rects(page)
    for name, r in rects.items():
        assert r is not None, name
        assert r["w"] > 0 and r["h"] > 0, name
        assert r["x"] >= 0 and r["x"] + r["w"] <= width, (name, r)
        assert r["y"] >= 0 and r["y"] + r["h"] <= height, (name, r)  # видно без прокрутки
    for (na, a), (nb, b) in combinations(rects.items(), 2):
        assert not _overlap(a, b), (na, a, nb, b)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert page.evaluate("window.scrollY") == 0
    rid = knowledge_stack.catalog_responses()[-1].request_id
    assert events.where(LISTED, request_id=rid)[0]["total"] == 35
    no_page_errors(page)


# --- visual-design: Разделы в разработке ----------------------------------------------------


@req(VD, "Разделы в разработке", scenario="Ассистент без метки")
def test_live_items_without_soon(knowledge_context, knowledge_stack, events):
    knowledge_stack.world.base()
    page = open_page(knowledge_context, knowledge_stack)
    loaded(page)
    nav = sidenav(page)
    for name, href in (
        ("Ассистент", "/assistant"),
        ("Граф", "/graph"),
        ("Справочник", "/reference"),
    ):
        link = nav.get_by_role("link", name=name)
        assert "скоро" not in link.inner_text().lower(), name
        assert link.get_attribute("href") == href, name
    assert nav.get_by_role("link", name="Справочник").get_attribute("aria-current") == "page"
    rid = knowledge_stack.catalog_responses()[-1].request_id
    assert events.where(LISTED, request_id=rid)
    no_page_errors(page)


@req(VD, "Разделы в разработке", scenario="Пункт-заглушка")
def test_future_items_keep_soon(knowledge_context, knowledge_stack, events):
    page = open_page(knowledge_context, knowledge_stack)
    nav = sidenav(page)
    for name in (
        "Эпохи и контекст",
        "Сравнение трактовок",
        "Маршрут изучения",
        "Мои материалы",
        "Подборки",
    ):
        assert "скоро" in nav.get_by_role("link", name=name).inner_text().lower(), name
    assert events.of(LISTED)  # якорь: справочник открыт и загружен сервисом
    no_page_errors(page)


@req(VD, "Разделы в разработке", scenario="Старая закладка справочника")
def test_old_reference_bookmark(knowledge_context, knowledge_stack, events):
    knowledge_stack.world.base()
    context = knowledge_context()
    page = context.new_page()
    page.goto(knowledge_stack.url + "/")
    page.locator(".sidebar").wait_for()
    history = page.evaluate("history.length")
    with catalog_response(page) as anchor:
        page.goto(knowledge_stack.url + "/soon/reference")
    page.wait_for_url(re.compile(r"/reference$"))
    assert page.evaluate("history.length") == history + 1  # только переход, замена без записи
    loaded(page)
    expect(page.locator(ITEMS)).to_have_count(5)
    assert page.locator(".soon").count() == 0
    assert event_of(events, anchor.value)["total"] == 5
    page.go_back()
    page.wait_for_url(re.compile(r"/$"))
    assert "/soon/" not in page.url
    no_page_errors(page)
