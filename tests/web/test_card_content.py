# ruff: noqa: E501 (встроенный JS и длинные формулировки сценариев)
"""Полная карточка в браузере: шапка и сводка персоны, метки строк, легенда, свёрнутые списки,
страна, пустые состояния, тексты как текст (redesign-entity-cards, дельта entity-cards).

Стенд — ``knowledge_stack``: настоящий шлюз, библиотека и сервис знаний; данные задаёт тест
(``tests/web/card_world.py``). Карточка открывается из справочника (``/reference``). Серверный
якорь каждой проверки — событие ``knowledge.card.served`` с ``request_id`` ответа карточки.
"""

from __future__ import annotations

import re
from urllib.parse import quote

import pytest
from playwright.sync_api import expect

from . import card_world as cw

req = pytest.mark.req
EC = "entity-cards"
SERVED = "knowledge.card.served"
CARD = re.compile(r"/api/knowledge/v1/entities/[^/]+/card")
CATALOG = "**/api/knowledge/v1/catalog*"
STATUS_WORDS = re.compile(
    r"проверено|по источникам|сгенерировано|спорно|так считает|не согласны", re.I
)
# Разделы карточки; блок «Граф» (кнопки рецептов) к разделам с данными не относится.
SECTION = "[data-section]:not([data-section=graph])"
SECTION_NOT_WHERE = "[data-section]:not([data-section=graph]):not([data-section=where])"
WITH_POLITIES = [{"polities_env": cw.polities_env()}]
expect.set_options(timeout=8000)


def open_card(make, stack, label: str, *, width=1920, height=1080, page=None, **options):
    """Справочник → поиск по названию → «Открыть»: карточка в правой панели."""
    if page is None:
        page = make(width, height, **options).new_page()
        page.set_default_timeout(8000)
    with page.expect_response(CATALOG):
        page.goto(f"{stack.url}/reference?q={quote(label)}")
    page.locator('.reference__list[aria-busy="false"]').wait_for()
    item = page.locator(".reference-item:not(.reference-item--placeholder)").filter(
        has=page.locator(".reference-item__name", has_text=re.compile(f"^{re.escape(label)}$"))
    )
    with page.expect_response(CARD) as response:
        item.locator(".reference-item__open").click()
    return page, response.value


def panel(page):
    return page.locator("aside#side-panel")


def body(page):
    return panel(page).locator(".pg-panel__body")


def loaded(page, title: str) -> None:
    panel(page).locator("h3.pg-entity-head__name", has_text=title).wait_for()


def served(events, response, **expected):
    rid = response.headers.get("x-request-id")
    assert rid, response.url
    found = events.where(SERVED, request_id=rid)
    assert len(found) == 1, (rid, events.names())
    for key, value in expected.items():
        assert found[0][key] == value, (key, found[0].fields)
    return found[0]


def card_requests(stack) -> int:
    return len([r for r in stack.responses if CARD.search(r.url)])


def visible_text(page) -> str:
    """Видимый текст тела карточки без легенды, ``<title>`` и скрытых подробностей строк."""
    return body(page).evaluate(
        """el => {
          const c = el.cloneNode(true);
          c.querySelectorAll('[data-card-legend], title, [hidden]').forEach(e => e.remove());
          return c.textContent;
        }"""
    )


# --- Карточка персоны ----------------------------------------------------------------------


@req(EC, "Карточка персоны", scenario="Шапка и сводка Локка")
@pytest.mark.parametrize("knowledge_stack", WITH_POLITIES, indirect=True)
def test_locke_header_and_summary(knowledge_context, knowledge_stack, events):
    cw.locke(knowledge_stack.world)
    page, response = open_card(knowledge_context, knowledge_stack, "Джон Локк")
    loaded(page, "Джон Локк")
    data = response.json()
    assert data["layout"] == "person" and data["where_to_read"] == []
    assert data["summary"]["polity"]["name"] == "Королевство Англия"
    summary = panel(page).locator("[data-card-summary]")
    expect(summary).to_have_count(1)
    for word in ("философ", "Лондон", "Королевство Англия", "1632–1704"):
        expect(summary).to_contain_text(word)
    assert "ныне" not in summary.inner_text()
    expect(summary.locator("[data-summary=country][data-country-kind=historical]")).to_have_text(
        "Королевство Англия"
    )
    assert body(page).inner_text().count("1632") == 1
    for selector in (
        ".pg-lifeline",
        ".card-summary",
        "[data-section=where]",
        "[data-section=life]",
    ):
        expect(panel(page).locator(selector)).to_have_count(0)
    assert "Где читать" not in body(page).inner_text()
    served(events, response, type="person", layout="person", empty=False, polity="found")
    assert page.context.errors == []


@req(EC, "Карточка персоны", scenario="Где жил свёрнут")
@req(
    EC,
    "Свёрнутые списки",
    invariant="кнопка «Показать все (N)» при total > visible, без нового запроса",
)
def test_places_collapsed_and_expanded(knowledge_context, knowledge_stack, events):
    cw.locke(knowledge_stack.world)
    page, response = open_card(knowledge_context, knowledge_stack, "Джон Локк")
    loaded(page, "Джон Локк")
    places = response.json()["sections"][0]
    assert (places["code"], places["display"], places["visible"], places["total"]) == (
        "places",
        "inline",
        3,
        5,
    )
    section = panel(page).locator("[data-section=places]")
    shown = section.inner_text()
    first_three = [r["label"] for r in places["rows"][:3]]
    last_two = [r["label"] for r in places["rows"][3:]]
    assert places["rows"][0]["label"] == "Лондон"
    assert all(name in shown for name in first_three)
    assert not any(name in shown for name in last_two)
    more = section.locator("[data-card-more]")
    expect(more).to_have_text("Показать все (5)")
    expect(more).to_have_attribute("aria-expanded", "false")
    before = card_requests(knowledge_stack)
    more.click()
    expect(more).to_have_attribute("aria-expanded", "true")
    expect(more).to_have_text("Свернуть")
    shown = section.inner_text()
    assert all(name in shown for name in [*first_three, *last_two])
    assert card_requests(knowledge_stack) == before
    more.click()
    expect(more).to_have_attribute("aria-expanded", "false")
    assert not any(name in section.inner_text() for name in last_two)
    served(events, response, type="person")


@req(EC, "Свёрнутые списки", scenario="Короткий список без кнопки")
@req(EC, "Свёрнутые списки", scenario="Длинный список")
def test_short_and_long_lists(knowledge_context, knowledge_stack, events):
    w = knowledge_stack.world
    short = w.person("Автор Короткий", "1700", "1760")
    for i in range(3):
        cw.add(
            w, w.thing("work", f"Малый труд {'АБВ'[i]}"), "author", obj=short, attributions=cw.src()
        )
    long = w.person("Автор Длинный", "1700", "1760")
    titles = [f"Большой труд {c}" for c in "АБВГДЕЖЗИ"]
    for title in titles:
        cw.add(w, w.thing("work", title), "author", obj=long, attributions=cw.src())
    page, response = open_card(knowledge_context, knowledge_stack, "Автор Короткий")
    loaded(page, "Автор Короткий")
    works = panel(page).locator("[data-section=works]")
    expect(works.locator(".card-row")).to_have_count(3)
    expect(works.locator("[data-card-more]")).to_have_count(0)
    served(events, response, type="person")
    page, response = open_card(knowledge_context, knowledge_stack, "Автор Длинный", page=page)
    loaded(page, "Автор Длинный")
    works = panel(page).locator("[data-section=works]")
    answer_order = [r["label"] for r in response.json()["sections"][0]["rows"]]
    assert len(answer_order) == 9
    rows = works.locator(".card-row")
    expect(rows).to_have_count(6)
    assert [t for t in rows.locator(".card-row__entity").all_inner_texts()] == answer_order[
        :6
    ]  # порядок клиента — порядок ответа
    before = card_requests(knowledge_stack)
    works.locator("[data-card-more]").click()
    expect(rows).to_have_count(9)
    assert rows.locator(".card-row__entity").all_inner_texts() == answer_order
    assert card_requests(knowledge_stack) == before
    assert len(events.where(SERVED, request_id=response.headers["x-request-id"])) == 1


@req(EC, "Карточка персоны", scenario="Влияние в обе стороны без повторов")
def test_influence_sections_without_repeats(knowledge_context, knowledge_stack, events):
    cw.kant(knowledge_stack.world, knowledge_stack)
    page, response = open_card(knowledge_context, knowledge_stack, "Иммануил Кант")
    loaded(page, "Иммануил Кант")
    by = panel(page).locator("[data-section=influenced_by]")
    hume_rows = by.locator(".card-row", has_text="Дэвид Юм")
    expect(hume_rows).to_have_count(1)
    expect(hume_rows.locator("button.card-mark")).to_have_attribute("data-mark", "verified")
    on = panel(page).locator("[data-section=influenced]")
    assert sorted(on.locator(".card-row__entity").all_inner_texts()) == [
        "Иоганн Фихте",
        "Фридрих Шеллинг",
    ]
    expect(panel(page).locator("[data-section=teachers]")).to_contain_text("Мартин Кнутцен")
    assert "Кнутцен" not in by.inner_text() + on.inner_text()
    expect(panel(page).locator("[data-section=influence]")).to_have_count(0)
    for row in (
        panel(page)
        .locator("[data-section=influenced_by] .card-row, [data-section=influenced] .card-row")
        .all()
    ):
        assert not STATUS_WORDS.search(row.inner_text()), row.inner_text()
    data = response.json()
    served(
        events,
        response,
        sections=len(data["sections"]),
        rows=sum(len(s["rows"]) for s in data["sections"]),
    )


@req(EC, "Карточка персоны", scenario="Только годы жизни")
def test_only_lifespan(knowledge_context, knowledge_stack, events):
    knowledge_stack.world.person("Томас Гоббс", "1588", "1679")
    page, response = open_card(knowledge_context, knowledge_stack, "Томас Гоббс")
    loaded(page, "Томас Гоббс")
    expect(panel(page).locator("[data-card-summary]")).to_contain_text("1588–1679")
    for selector in ("[data-card-empty]", "[data-card-legend]", SECTION):
        expect(panel(page).locator(selector)).to_have_count(0)
    served(events, response, sections=0, rows=0, empty=False)


# --- Природа каждой строки -----------------------------------------------------------------


@req(EC, "Природа каждой строки", scenario="По источникам без подтверждения")
@req(EC, "Природа каждой строки", scenario="Сгенерированная строка")
@req(EC, "Природа каждой строки", scenario="Спорное")
def test_row_marks_sourced_generated_disputed(knowledge_context, knowledge_stack, events):
    ids = cw.kant(knowledge_stack.world, knowledge_stack)
    page, response = open_card(knowledge_context, knowledge_stack, "Иммануил Кант")
    loaded(page, "Иммануил Кант")
    by = panel(page).locator("[data-section=influenced_by]")
    # По источникам, без подтверждения.
    sourced = by.locator(".card-row", has_text="Фрэнсис Хатчесон")
    expect(sourced.locator("button.card-mark")).to_have_attribute("data-mark", "sourced")
    expect(sourced.locator("a.pg-cite")).to_have_count(0)
    # По источникам с подтверждением: ссылка на абзац остаётся номером.
    backed = by.locator(".card-row", has_text="Джордж Беркли")
    expect(backed.locator("a.pg-cite")).to_have_count(1)
    # Сгенерированная.
    rows = {r["label"]: r for s in response.json()["sections"] for r in s["rows"]}
    assert rows["Христиан Вольф"]["mark"] == "generated" and rows["Христиан Вольф"]["generated"]
    generated = panel(page).locator(".card-row", has_text="Христиан Вольф")
    expect(generated).to_have_attribute("data-unverified", "true")
    mark = generated.locator("button.card-mark[data-mark=generated]")
    assert mark.get_attribute("aria-label").startswith("Сгенерировано")
    assert "сгенерировано" not in generated.inner_text().lower()
    expect(panel(page).locator("[data-legend=generated]")).to_have_count(1)
    # Спорная: подробности раскрываются нажатием на метку.
    disputed = panel(page).locator(".card-row", has_text="Готфрид Лейбниц")
    assert rows["Готфрид Лейбниц"]["mark"] == "disputed"
    assert rows["Готфрид Лейбниц"]["disputed_by"] == ["Рассел"]
    text = disputed.inner_text().lower()
    assert "спорно" not in text and "не согласны" not in text
    mark = disputed.locator("button.card-mark")
    name = mark.get_attribute("aria-label")
    assert "Спорно" in name and "не согласны: рассел" in name.lower(), name
    expect(mark).to_have_attribute("aria-expanded", "false")
    mark.click()
    expect(mark).to_have_attribute("aria-expanded", "true")
    details = disputed.locator(".card-row__details")
    expect(details).to_be_visible()
    expect(details).to_contain_text("так считает: Учебник N")
    expect(details).to_contain_text("не согласны: Рассел")
    served(events, response, type="person")
    _ = ids


@req(EC, "Природа каждой строки", scenario="Спорное")
def test_disputed_mark_accessible_name_wording(knowledge_context, knowledge_stack, events):
    """Сценарий «Спорное»: имя метки содержит «Спорно» и «Не согласны: B» (регистр по тексту)."""
    cw.kant(knowledge_stack.world, knowledge_stack)
    page, response = open_card(knowledge_context, knowledge_stack, "Иммануил Кант")
    loaded(page, "Иммануил Кант")
    mark = panel(page).locator(".card-row", has_text="Готфрид Лейбниц").locator("button.card-mark")
    name = mark.get_attribute("aria-label")
    assert "Спорно" in name and "Не согласны: Рассел" in name, name
    assert mark.get_attribute("title") == name
    served(events, response, type="person")


@req(EC, "Природа каждой строки", scenario="Одна легенда")
@req(
    EC,
    "Природа каждой строки",
    invariant="только цвет: у каждой строки одна метка с именем, слов статуса нет",
)
def test_one_legend_and_no_status_words(knowledge_context, knowledge_stack, events):
    cw.kant(knowledge_stack.world, knowledge_stack)
    cw.locke(knowledge_stack.world)
    page, response = open_card(knowledge_context, knowledge_stack, "Иммануил Кант")
    loaded(page, "Иммануил Кант")
    data = response.json()
    legend = panel(page).locator("[data-card-legend]")
    expect(legend).to_have_count(1)
    shown = {
        x
        for x in legend.locator("[data-legend]").evaluate_all(
            "els => els.map(e => e.dataset.legend)"
        )
    }
    assert shown == set(data["legend"]) == {r["mark"] for s in data["sections"] for r in s["rows"]}
    for item in legend.locator("[data-legend]").all():
        text = item.inner_text()
        assert re.search(r"\S\s*—\s*\S", text), text  # подпись статуса и краткое описание
    rows = panel(page).locator(".card-row")
    assert rows.count() > 5
    for row in rows.all():
        marks = row.locator("button.card-mark")
        assert marks.count() == 1
        assert (marks.get_attribute("aria-label") or "").strip()
        assert row.locator(".pg-status").count() == 0
    assert not STATUS_WORDS.search(visible_text(page)), visible_text(page)
    served(events, response, type="person")
    # Другой тип и другая карточка — тоже одна легенда.
    page, response = open_card(knowledge_context, knowledge_stack, "Джон Локк", page=page)
    loaded(page, "Джон Локк")
    expect(panel(page).locator("[data-card-legend]")).to_have_count(1)
    served(events, response, type="person")
    assert page.context.errors == []


@req(
    EC,
    "Природа каждой строки",
    invariant="метка одинакова во всех карточках и различима по отметке",
)
def test_mark_looks_same_in_every_card(knowledge_context, knowledge_stack, events):
    w = knowledge_stack.world
    cw.kant(w, knowledge_stack)
    concept = w.thing("concept", "Вещь в себе")
    author = w.person("Иоганн Автор", "1700", "1760")
    work = w.thing("work", "Критика трактата")
    cw.add(w, work, "author", obj=author, attributions=cw.src(), status="verified")
    cw.add(w, work, "discusses", obj=concept, provenance=cw.Provenance("generated"))
    cw.add(w, concept, "definition", value="не явление", attributions=cw.src(), status="verified")

    def look(page, mark: str) -> dict:
        return page.locator(f"button.card-mark[data-mark={mark}] .card-mark__shape").first.evaluate(
            """el => {
              const s = getComputedStyle(el);
              return {bg: s.backgroundColor, border: s.borderTopColor, radius: s.borderTopLeftRadius,
                      clip: s.clipPath, w: s.width, h: s.height};
            }"""
        )

    page, response = open_card(knowledge_context, knowledge_stack, "Иммануил Кант")
    loaded(page, "Иммануил Кант")
    person = {m: look(page, m) for m in ("verified", "sourced", "generated", "disputed")}
    assert len({tuple(v.items()) for v in person.values()}) == 4  # отметки различимы
    page, response = open_card(knowledge_context, knowledge_stack, "Вещь в себе", page=page)
    loaded(page, "Вещь в себе")
    other = {m: look(page, m) for m in ("verified", "generated")}
    assert other["verified"] == person["verified"] and other["generated"] == person["generated"]
    served(events, response, type="concept")


@req(
    EC,
    "Выведенные строки",
    invariant="раздел с выведенным подписан «по трудам и связям», подробности — через что",
)
def test_inferred_section_label_and_via(knowledge_context, knowledge_stack, events):
    w = knowledge_stack.world
    hume = w.person("Дэвид Юм", "1711", "1776")
    work = w.thing("work", "Трактат о природе")
    cause = w.thing("concept", "причинность")
    cw.add(w, work, "author", obj=hume, attributions=cw.src(), status="verified")
    cw.add(w, work, "discusses", obj=cause, provenance=cw.Provenance("generated"))
    page, response = open_card(knowledge_context, knowledge_stack, "Дэвид Юм")
    loaded(page, "Дэвид Юм")
    interests = panel(page).locator("[data-section=interests]")
    expect(interests.locator(".card-section__inferred[data-inferred]")).to_contain_text(
        "по трудам и связям"
    )
    row = interests.locator(".card-row", has_text="причинность")
    mark = row.locator("button.card-mark")
    expect(mark).to_have_attribute("data-mark", "generated")
    assert "Трактат о природе" in mark.get_attribute("aria-label")
    mark.click()
    expect(row.locator(".card-row__details")).to_contain_text("через Трактат о природе")
    assert panel(page).locator("[data-section=works] .card-section__inferred").count() == 0
    served(events, response, inferred=1)


# --- Государство основного места ----------------------------------------------------------


def kant_in_koenigsberg(w, coords=(54.71, 20.51)) -> str:
    k = w.person("Иммануил Кант", "1724", "1804")
    city = cw.place(w, "Кёнигсберг", *coords) if coords else cw.place(w, "Кёнигсберг")
    cw.lived(w, k, city, "activity")
    return k


@req(EC, "Государство основного места", scenario="Историческое государство")
@pytest.mark.parametrize("knowledge_stack", WITH_POLITIES, indirect=True)
def test_historical_state_in_summary(knowledge_context, knowledge_stack, events):
    kant_in_koenigsberg(knowledge_stack.world)
    page, response = open_card(knowledge_context, knowledge_stack, "Иммануил Кант")
    loaded(page, "Иммануил Кант")
    data = response.json()
    assert (data["summary"]["polity"]["name"], data["summary"]["polity"]["year"]) == (
        "Королевство Пруссия",
        1724,
    )
    country = panel(page).locator("[data-summary=country]")
    expect(country).to_have_attribute("data-country-kind", "historical")
    expect(country).to_have_text("Королевство Пруссия")
    summary = panel(page).locator("[data-card-summary]").inner_text()
    assert "Россия" not in summary and "ныне" not in summary
    served(events, response, polity="found")


@req(EC, "Государство основного места", scenario="Слоя нет — современная страна с пометкой")
def test_no_layer_shows_modern_country_with_note(knowledge_context, knowledge_stack, events):
    kant_in_koenigsberg(knowledge_stack.world)
    context = knowledge_context(1920, 1080)
    page = context.new_page()
    page.set_default_timeout(8000)
    chunks = []
    page.on("request", lambda r: chunks.append(r.url) if "countries" in r.url else None)
    page, response = open_card(knowledge_context, knowledge_stack, "Иммануил Кант", page=page)
    loaded(page, "Иммануил Кант")
    assert response.json()["summary"]["polity"] is None
    country = panel(page).locator("[data-summary=country]")
    expect(country).to_have_attribute("data-country-kind", "modern")
    expect(country).to_have_text("ныне Россия")
    assert any("countries" in u for u in chunks)  # модуль границ подгружен по требованию
    served(events, response, polity="unavailable")


@req(EC, "Государство основного места", scenario="Вне покрытия слоя")
@pytest.mark.parametrize("knowledge_stack", WITH_POLITIES, indirect=True)
def test_outside_layer_coverage(knowledge_context, knowledge_stack, events):
    w = knowledge_stack.world
    p = w.person("Далёкий Житель", "1500", "1580")  # слой на 1500 год точку не содержит
    cw.lived(w, p, cw.place(w, "Кёнигсберг", 54.71, 20.51), "activity")
    page, response = open_card(knowledge_context, knowledge_stack, "Далёкий Житель")
    loaded(page, "Далёкий Житель")
    assert response.json()["summary"]["polity"] is None
    country = panel(page).locator("[data-summary=country]")
    expect(
        panel(page).locator("[data-summary=country][data-country-kind=historical]")
    ).to_have_count(0)
    if country.count():
        expect(country).to_have_attribute("data-country-kind", "modern")
        assert country.inner_text().startswith("ныне ")
    served(events, response, polity="none")


@req(EC, "Государство основного места", scenario="Место с координатами")
def test_place_card_shows_modern_country(knowledge_context, knowledge_stack, events):
    cw.place(knowledge_stack.world, "Кёнигсберг", 54.71, 20.51)
    page, response = open_card(knowledge_context, knowledge_stack, "Кёнигсберг")
    loaded(page, "Кёнигсберг")
    data = response.json()
    assert data["geo"] == {"lat": 54.71, "lon": 20.51} and data["summary"] is None
    country = panel(page).locator("[data-card-country]")
    expect(country).to_have_attribute("data-country-kind", "modern")
    expect(country).to_have_text("ныне Россия")
    served(events, response, type="place", polity="skipped")


@req(EC, "Государство основного места", scenario="Без координат")
@pytest.mark.parametrize("knowledge_stack", WITH_POLITIES, indirect=True)
def test_no_coordinates_no_country_no_fragment(knowledge_context, knowledge_stack, events):
    kant_in_koenigsberg(knowledge_stack.world, coords=None)
    context = knowledge_context(1920, 1080)
    page = context.new_page()
    page.set_default_timeout(8000)
    chunks = []
    page.on("request", lambda r: chunks.append(r.url) if "countries" in r.url else None)
    page, response = open_card(knowledge_context, knowledge_stack, "Иммануил Кант", page=page)
    loaded(page, "Иммануил Кант")
    data = response.json()
    assert data["summary"]["place"]["geo"] is None and data["summary"]["polity"] is None
    expect(panel(page).locator("[data-summary=place]")).to_contain_text("Кёнигсберг")
    expect(panel(page).locator("[data-summary=country]")).to_have_count(0)
    assert chunks == []
    served(events, response, layout="person", polity="skipped")


@req(
    EC,
    "Государство основного места",
    invariant="страна не показывается ни названием, ни заглушкой, если модуль границ не загрузился",
)
def test_country_module_failure_shows_nothing(knowledge_context, knowledge_stack, events):
    kant_in_koenigsberg(knowledge_stack.world)
    context = knowledge_context(1920, 1080)
    page = context.new_page()
    page.set_default_timeout(8000)
    aborted = []
    page.route(
        re.compile(r"/assets/countries-.*\.js"),
        lambda route: (aborted.append(route.request.url), route.abort()),
    )
    page, response = open_card(knowledge_context, knowledge_stack, "Иммануил Кант", page=page)
    loaded(page, "Иммануил Кант")
    summary = panel(page).locator("[data-card-summary]")
    expect(summary).to_contain_text("Кёнигсберг")
    page.wait_for_function(
        "performance.getEntriesByType('resource').some(r => r.name.includes('countries'))"
    )
    assert aborted
    expect(panel(page).locator("[data-summary=country]")).to_have_count(0)
    assert "ныне" not in summary.inner_text() and "Россия" not in body(page).inner_text()
    served(events, response, type="person")


# --- Разделы других типов ------------------------------------------------------------------


@req(EC, "К кому относится", scenario="Учение без сторонников, но с трудом")
@req(EC, "Выведенные строки", scenario="Компактное окно без выводов")
def test_doctrine_card_relates_to_and_in_works(knowledge_context, knowledge_stack, events):
    w = knowledge_stack.world
    berkeley = w.person("Джордж Беркли", "1685", "1753")
    work = w.thing("work", "Трактат о началах человеческого знания")
    doctrine = w.thing("doctrine", "Имматериализм")
    cw.add(w, work, "author", obj=berkeley, attributions=cw.src(), status="verified")
    cw.add(w, work, "discusses", obj=doctrine, attributions=cw.src())
    page, response = open_card(knowledge_context, knowledge_stack, "Имматериализм")
    loaded(page, "Имматериализм")
    data = response.json()
    assert [s["code"] for s in data["sections"]] == ["relates_to", "in_works"]
    relates = panel(page).locator("[data-section=relates_to]")
    expect(relates).to_contain_text("Джордж Беркли")
    expect(relates.locator(".card-section__inferred[data-inferred]")).to_contain_text(
        "по трудам и связям"
    )
    mark = relates.locator("button.card-mark")
    expect(mark).to_have_attribute("data-mark", "sourced")
    assert "Трактат о началах человеческого знания" in mark.get_attribute("aria-label")
    expect(panel(page).locator("[data-section=in_works]")).to_contain_text("Трактат о началах")
    expect(panel(page).locator("[data-section=in_works] .card-section__inferred")).to_have_count(0)
    served(events, response, type="doctrine", sections=2, rows=2, inferred=1, empty=False)


@req(EC, "Разделы карточки по типу", scenario="Карточка труда")
def test_work_card_infobox(knowledge_context, knowledge_stack, events):
    w = knowledge_stack.world
    locke = w.person("Джон Локк", "1632", "1704")
    essay = w.thing("work", "Опыт о человеческом разумении")
    idea, innate = w.thing("concept", "идея"), w.thing("concept", "врождённые идеи")
    cw.add(w, essay, "author", obj=locke, attributions=cw.src(), status="verified")
    cw.add(w, essay, "dating", value=cw.fixed("1689"), attributions=cw.src())
    cw.add(w, essay, "discusses", obj=idea, attributions=cw.src())
    cw.add(w, essay, "discusses", obj=innate, attributions=cw.src())
    page, response = open_card(knowledge_context, knowledge_stack, "Опыт о человеческом разумении")
    loaded(page, "Опыт о человеческом разумении")
    facts = panel(page).locator("dl.card-facts").first
    pairs = facts.locator(".card-facts__item").evaluate_all(
        "els => els.map(e => [e.querySelector('dt').innerText.trim(),"
        " e.querySelector('dd').innerText.trim()])"
    )
    assert len(pairs) == 2, pairs
    assert pairs[0][1].startswith("Джон Локк") and pairs[1][1].startswith("1689"), pairs
    topics = panel(page).locator("[data-section=topics]")
    expect(topics).to_contain_text("идея")
    expect(topics).to_contain_text("врождённые идеи")
    expect(panel(page).locator("[data-section=cites]")).to_have_count(0)
    marks = [m.get_attribute("data-mark") for m in facts.locator("button.card-mark").all()]
    assert marks == ["verified", "sourced"]
    served(events, response, type="work", sections=2, rows=4)


@req(EC, "Разделы карточки по типу", scenario="Карточка труда")
def test_work_card_infobox_labels(knowledge_context, knowledge_stack, events):
    """Сценарий «Карточка труда»: в DOM ``dt`` «Автор» с ``dd`` «Локк» и ``dt`` «Дата» с ``dd`` «1689»."""
    w = knowledge_stack.world
    locke = w.person("Джон Локк", "1632", "1704")
    essay = w.thing("work", "Опыт о разумении")
    cw.add(w, essay, "author", obj=locke, attributions=cw.src(), status="verified")
    cw.add(w, essay, "dating", value=cw.fixed("1689"), attributions=cw.src())
    page, response = open_card(knowledge_context, knowledge_stack, "Опыт о разумении")
    loaded(page, "Опыт о разумении")
    labels = panel(page).locator("dl.card-facts dt").all_inner_texts()
    assert [x.strip() for x in labels] == ["Автор", "Дата"], labels
    served(events, response, type="work")


@req(EC, "Разделы карточки по типу", scenario="Карточка группы")
@req(EC, "Разделы карточки по типу", scenario="Карточка события")
def test_group_and_event_cards(knowledge_context, knowledge_stack, events):
    w = knowledge_stack.world
    group = w.thing("group", "Кембриджские платоники")
    cw.add(w, group, "group_kind", value="school", attributions=cw.src())
    for name in ("Ральф Кедворт", "Генри Мор"):
        cw.add(w, w.person(name, "1617", "1688"), "member_of", obj=group, attributions=cw.src())
    event = w.thing("event", "Славная революция")
    cw.add(w, event, "event_kind", value="political", attributions=cw.src())
    cw.add(w, event, "dating", value=cw.fixed("1688"), attributions=cw.src())
    page, response = open_card(knowledge_context, knowledge_stack, "Кембриджские платоники")
    loaded(page, "Кембриджские платоники")
    assert [s["code"] for s in response.json()["sections"]] == ["facts", "membership"]
    expect(panel(page).locator("dl.card-facts")).to_contain_text("школа")
    members = panel(page).locator("[data-section=membership]")
    expect(members).to_contain_text("Ральф Кедворт")
    expect(members).to_contain_text("Генри Мор")
    served(events, response, type="group", sections=2, rows=3)
    page, response = open_card(knowledge_context, knowledge_stack, "Славная революция", page=page)
    loaded(page, "Славная революция")
    assert [s["code"] for s in response.json()["sections"]] == ["when"]
    when = panel(page).locator("[data-section=when]")
    expect(when.locator("dl.card-facts")).to_have_count(1)
    expect(when).to_contain_text("1688")
    served(events, response, type="event", sections=1, rows=2)


@req(EC, "Разделы карточки по типу", scenario="Ничего не теряется")
def test_other_section_in_dom(knowledge_context, knowledge_stack, events):
    w = knowledge_stack.world
    term = w.thing("term", "tabula rasa")
    translation = w.thing("idea_event", "Перевод Аристотеля")
    cw.add(w, translation, "result", obj=term, attributions=cw.src())
    page, response = open_card(knowledge_context, knowledge_stack, "tabula rasa")
    loaded(page, "tabula rasa")
    other = panel(page).locator("[data-section=other]")
    expect(other).to_contain_text("Перевод Аристотеля")
    served(events, response, type="term", rows=1)


# --- Пустые разделы ------------------------------------------------------------------------


@req(EC, "Пустые разделы", scenario="Мало данных")
@req(EC, "Пустые разделы", scenario="Совсем пусто")
def test_empty_states(knowledge_context, knowledge_stack, events):
    w = knowledge_stack.world
    doctrine = w.thing("doctrine", "Эмпириокритицизм")
    w.mention(
        doctrine, knowledge_stack.textbooks["N"], knowledge_stack.paragraph("N", "Кант пишет")
    )
    w.mention(doctrine, knowledge_stack.textbooks["N"], knowledge_stack.paragraph("N", "Юм пишет"))
    w.thing("place", "Пустошь")
    page, response = open_card(knowledge_context, knowledge_stack, "Эмпириокритицизм")
    loaded(page, "Эмпириокритицизм")
    data = response.json()
    assert data["sections"] == [] and data["empty"] is True and len(data["where_to_read"]) == 1
    empty = panel(page).locator("[data-card-empty]")
    expect(empty).to_contain_text("Об этом пока известно мало")
    expect(empty).to_contain_text("где об этом читать")
    expect(panel(page).locator("[data-section=where]")).to_have_count(1)
    expect(panel(page).locator("[data-card-legend]")).to_have_count(0)
    expect(panel(page).locator(SECTION_NOT_WHERE)).to_have_count(0)
    served(events, response, sections=0, rows=0, empty=True)
    page, response = open_card(knowledge_context, knowledge_stack, "Пустошь", page=page)
    loaded(page, "Пустошь")
    data = response.json()
    assert (data["empty"], data["where_to_read"], data["geo"]) == (True, [], None)
    empty = panel(page).locator("[data-card-empty]")
    expect(empty).to_contain_text("Об этом пока известно мало")
    expect(empty).to_contain_text("ассистента")
    expect(panel(page).locator("[data-section=where]")).to_have_count(0)
    assert body(page).inner_text().replace("Пустошь", "").strip()
    served(events, response, type="place", empty=True)


CASES = [
    ("person", "Тип Персона"),
    ("concept", "Тип Понятие"),
    ("doctrine", "Тип Учение"),
    ("term", "Тип Термин"),
    ("work", "Тип Труд"),
    ("event", "Тип Событие"),
    ("phenomenon", "Тип Явление"),
    ("group", "Тип Группа"),
    ("place", "Тип Место"),
]


@req(EC, "Пустые разделы", scenario="Ни одной пустой карточки")
def test_no_card_is_empty_in_every_type(knowledge_context, knowledge_stack, events):
    w = knowledge_stack.world
    helper = w.person("Помощник Автор", "1700", "1760")
    helper_work = w.thing("work", "Помощник Труд")
    cw.add(w, helper_work, "author", obj=helper, attributions=cw.src())
    ids = {}
    for type_, name in CASES:
        ids[type_] = w.person(name, "1700", "1760") if type_ == "person" else w.thing(type_, name)
    cw.add(w, ids["person"], "lived_in", obj=ids["place"], attributions=cw.src())  # место: жители
    cw.add(w, ids["concept"], "definition", value="определение", attributions=cw.src())
    cw.add(w, helper_work, "discusses", obj=ids["doctrine"], attributions=cw.src())
    cw.add(w, ids["term"], "denotes", obj=ids["concept"], attributions=cw.src())
    cw.add(w, ids["work"], "author", obj=helper, attributions=cw.src())
    cw.add(w, ids["event"], "event_kind", value="political", attributions=cw.src())
    cw.add(w, ids["phenomenon"], "event_kind", value="political", attributions=cw.src())
    cw.add(w, ids["group"], "group_kind", value="school", attributions=cw.src())
    page = None
    for type_, name in CASES:
        page, response = open_card(knowledge_context, knowledge_stack, name, page=page)
        loaded(page, name)
        data = response.json()
        assert data["type"] == type_ and data["empty"] is False, type_
        expect(panel(page).locator("[data-card-empty]")).to_have_count(0)
        has_section = panel(page).locator("[data-section]:not([data-section=where])").count()
        has_summary = panel(page).locator("[data-card-summary]").count()
        assert has_section or has_summary, type_
        served(events, response, type=type_, empty=False)
    assert page.context.errors == []


# --- Тексты карточки — текст ---------------------------------------------------------------


@req(EC, "Тексты карточки — текст", scenario="Разметка в названии")
def test_markup_is_text(knowledge_context, knowledge_stack, events):
    w = knowledge_stack.world
    evil_person = '<img src=x onerror="window.__pwned=1">'
    evil_work = "<b>Труд</b>"
    evil_place = "<script>window.__pwned=2</script>"
    person = cw.legacy_person(w, evil_person, "1700", "1760")
    work = w.thing("work", "Прежний Труд")
    place = w.thing("place", "Прежнее Место")
    cw.add(w, work, "author", obj=person, attributions=cw.src())
    cw.lived(w, person, place, "activity")
    for entity, label in ((work, evil_work), (place, evil_place)):
        from philograph.knowledge import schema as t
        from philograph.knowledge.entities import normalize

        with w.engine.begin() as conn:
            conn.execute(
                t.names.update()
                .where(t.names.c.entity_id == entity)
                .values(text=label, normalized=normalize(label))
            )
    page, response = open_card(knowledge_context, knowledge_stack, evil_person)
    assert response.json()["title"] == evil_person
    served(events, response, type="person")
    panel(page).locator("h3.pg-entity-head__name").wait_for()
    checks = {
        "img[src=x]": 0,
        "b": 0,
        "script": 0,
    }

    def assert_inert() -> None:
        for selector, count in checks.items():
            assert panel(page).locator(selector).count() == count, selector
        assert page.evaluate("() => window.__pwned") is None

    assert_inert()
    assert evil_person in body(page).inner_text() or evil_person in panel(page).inner_text()
    with page.expect_response(CARD) as work_card:
        panel(page).locator("[data-section=works] .card-row__entity").click()
    assert work_card.value.json()["title"] == evil_work
    served(events, work_card.value, type="work")
    panel(page).locator("h3.pg-entity-head__name", has_text="<b>Труд</b>").wait_for()
    assert_inert()
    assert evil_work in panel(page).inner_text()
    # Назад к персоне, затем к месту из сводки.
    panel(page).get_by_role("button", name="Назад").click()
    panel(page).locator("h3.pg-entity-head__name").first.wait_for()
    with page.expect_response(CARD) as place_card:
        panel(page).locator("[data-summary=place] button").click()
    assert place_card.value.json()["title"] == evil_place
    served(events, place_card.value, type="place")
    panel(page).locator("h3.pg-entity-head__name", has_text="<script>").wait_for()
    assert_inert()
    assert evil_place in panel(page).inner_text()
    assert page.context.errors == []


@req(EC, "Тексты карточки — текст", invariant="значение, примечание и «через» выводятся текстом")
def test_markup_in_values_notes_and_via_is_text(knowledge_context, knowledge_stack, events):
    from philograph.knowledge import schema as t
    from philograph.knowledge.entities import normalize

    w = knowledge_stack.world
    evil = "<i id=pwned>x</i>"
    author = w.person("Автор Значений", "1700", "1760")
    work = w.thing("work", "Труд для разметки", "1739")
    idea = w.thing("concept", "Идея для разметки")
    cw.add(w, work, "author", obj=author, attributions=cw.src())
    cw.add(w, work, "discusses", obj=idea, attributions=cw.src())
    cw.add(w, idea, "definition", value=evil, attributions=cw.src())
    with w.engine.begin() as conn:
        conn.execute(
            t.names.update()
            .where(t.names.c.entity_id == work)
            .values(text="<u>Труд</u>", normalized=normalize("<u>Труд</u>"))
        )
    page, _ = open_card(knowledge_context, knowledge_stack, "Идея для разметки")
    loaded(page, "Идея для разметки")
    expect(panel(page).locator("[data-section=definitions]")).to_contain_text(evil)
    relates = panel(page).locator("[data-section=relates_to]")
    mark = relates.locator("button.card-mark")
    mark.click()
    expect(relates.locator(".card-row__details")).to_contain_text("<u>Труд</u>")
    for selector in ("i#pwned", "u", "#pwned"):
        assert panel(page).locator(selector).count() == 0, selector
    page, _ = open_card(knowledge_context, knowledge_stack, "Автор Значений", page=page)
    loaded(page, "Автор Значений")
    assert panel(page).locator("u").count() == 0
    expect(panel(page).locator("[data-section=works]")).to_contain_text("<u>Труд</u>")
    expect(panel(page).locator("[data-section=works] .card-row__note")).to_contain_text("1739")
    assert page.context.errors == []
