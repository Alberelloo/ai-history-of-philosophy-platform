"""Глобус: люди и связи во времени, размещение, выбор, текстовая альтернатива, состояния
(geo-timeline, задачи 7.4–7.5).

Требования «Люди, события и связи во времени», «Размещение на глобусе», «Выбор на глобусе»,
«Текстовая альтернатива и клавиатура глобуса», «Состояния глобуса» дельты
``openspec/specs/geo-timeline/spec.md``. Настоящий сервис знаний
(``knowledge_stack``); ``page.route`` — только для задержки и ответа 500.
Клиент событий журнала не пишет: серверный якорь — ``knowledge.geo.built`` по ``request_id``.
"""

# ruff: noqa: E501 — встроенные скрипты страницы и имена инвариантов спецификации

from __future__ import annotations

import itertools
import math
import re

import pytest
from playwright.sync_api import expect

from philograph.knowledge.statements import Attribution

from .geo_helpers import (
    GEO_BUILT,
    MAX_SHIFT,
    PLACES_API,
    Geo,
    address,
    arc_end_error,
    arc_faults,
    center,
    drawn,
    errors,
    focus_globe,
    geo_built,
    globe,
    globe_ready,
    links,
    open_globe,
    open_globe_map,
    persons,
    play_button,
    plural,
    press,
    project,
    row_order,
    rows,
    scene,
    settle,
    where_is,
    year,
    zoom,
)
from .test_geo_medals import coords_of, dataset, shift_faults

req = pytest.mark.req
GEO = "geo-timeline"
TIME = "Люди, события и связи во времени"
PLACE = "Размещение на глобусе"
SEL = "Выбор на глобусе"
A11Y = "Текстовая альтернатива и клавиатура глобуса"
STATES = "Состояния глобуса"
COMMON = [Attribution("common")]
expect.set_options(timeout=15000)


def facet(page, title: str):
    details = page.locator(".map-facet").filter(
        has=page.locator("summary", has_text=re.compile(f"^{title}"))
    )
    if details.get_attribute("open") is None:
        details.locator("summary").click()
    return details


# --- Люди, события и связи во времени ---------------------------------------------------


def descartes_world(world) -> dict[str, str]:
    g = Geo(world)
    ids = {
        "descartes": world.person("Рене Декарт", "1596", "1650"),
        "schelling": world.person("Фридрих Шеллинг", "1775", "1854"),  # без места: окно до 1854
        "lahaye": g.place("Ла-Э", 46.98, 0.7),
        "amsterdam": g.place("Амстердам", 52.37, 4.89),
        "stockholm": g.place("Стокгольм", 59.33, 18.07),
    }
    g.lived(ids["descartes"], ids["lahaye"], "birth", "1596")
    g.lived(ids["descartes"], ids["amsterdam"], "activity", "1628–1649")
    g.lived(ids["descartes"], ids["stockholm"], "death", "1650")
    return ids


@req(GEO, TIME, scenario="Декарт переезжает")
def test_descartes_moves(knowledge_context, knowledge_stack, events):
    w = descartes_world(knowledge_stack.world)
    page, response = open_globe(
        knowledge_context, knowledge_stack, "/graph?view=globe&from=1590&to=1850&t=1610"
    )
    d = w["descartes"]
    seen = []
    focus_globe(page)
    for t, keys in (
        (1610, []),
        (1640, ["PageUp"] * 3),
        (1650, ["]"] * 10),
        (1800, ["PageUp"] * 15),
    ):
        for k in keys:
            press(page, k)
        assert year(page) == t
        m = persons(page)
        assert set(m) == {d}, (t, set(m))
        seen.append((m[d]["place"], m[d]["age"]))
        assert where_is(page, "Рене Декарт") == [m[d]["place"]]
    assert seen == [
        (w["lahaye"], 0),
        (w["amsterdam"], 0),
        (w["stockholm"], 0),
        (w["stockholm"], 150),
    ]
    press(page, "]")
    assert year(page) == 1801
    assert d not in persons(page)
    assert where_is(page, "Рене Декарт") == []
    geo_built(events, response)
    errors(page)


@req(GEO, TIME, scenario="Юм без вида места")
def test_hume_without_role(knowledge_context, knowledge_stack, events):
    g = Geo(knowledge_stack.world)
    hume = knowledge_stack.world.person("Дэвид Юм", "1711", "1776")
    ed = g.place("Эдинбург", 55.95, -3.19)
    g.lived(hume, ed)
    page, response = open_globe(knowledge_context, knowledge_stack, "/graph?view=globe&t=1740")
    m = persons(page)[hume]
    assert (m["place"], m["age"]) == (ed, 0)
    focus_globe(page)
    press(page, "PageUp", 3)
    assert year(page) == 1770
    m = persons(page)[hume]
    assert (m["place"], m["age"]) == (ed, 0)
    geo_built(events, response)


def link_world(world) -> dict[str, str]:
    g = Geo(world)
    ids = {
        "kant": world.person("Иммануил Кант", "1724", "1804"),
        "hume": world.person("Дэвид Юм", "1711", "1776"),
        "bergson": world.person("Анри Бергсон", "1859", "1941"),  # без места: окно до 1941
        "konigsberg": g.place("Кёнигсберг", 54.71, 20.51),
        "edinburgh": g.place("Эдинбург", 55.95, -3.19),
    }
    g.lived(ids["kant"], ids["konigsberg"], "birth", "1724")
    g.lived(ids["hume"], ids["edinburgh"])
    ids["link"] = world.relate(ids["kant"], "influenced_by", ids["hume"])
    return ids


def _hume_kant_arc(page, w) -> dict:
    sc = scene(page)
    [lk] = [x for x in sc["links"] if x["id"] == w["link"]]
    assert (lk["from"], lk["to"], lk["hidden"]) == (w["hume"], w["kant"], "false"), lk
    assert arc_faults(sc) == [] and arc_end_error(sc) <= 1
    return lk


def _no_link(page, w) -> bool:
    return w["link"] not in links(page)


@req(GEO, TIME, scenario="Связь Юм → Кант")
def test_link_hume_kant_lifetime(knowledge_context, knowledge_stack, events):
    w = link_world(knowledge_stack.world)
    page, response = open_globe(
        knowledge_context, knowledge_stack, "/graph?view=globe&from=1700&to=1940&t=1743"
    )
    assert _no_link(page, w)
    focus_globe(page)
    press(page, "]")
    assert year(page) == 1744
    assert _hume_kant_arc(page, w)["age"] == 0
    press(page, "PageUp", 15)
    assert year(page) == 1894
    assert links(page)[w["link"]]["age"] == 150
    press(page, "]")
    assert year(page) == 1895
    assert _no_link(page, w)
    geo_built(events, response)


@req(GEO, TIME, scenario="Только проверенные")
def test_only_verified_hides_generated_arcs(knowledge_context, knowledge_stack, events):
    w = link_world(knowledge_stack.world)
    g = Geo(knowledge_stack.world)
    fichte = knowledge_stack.world.person("Иоганн Фихте", "1762", "1814")
    jena = g.place("Йена", 50.93, 11.59)
    g.lived(fichte, jena, "activity")
    generated = g.influence(fichte, w["kant"], generated=True)
    page, response = open_globe(knowledge_context, knowledge_stack, "/graph?view=globe&t=1800")
    before = links(page)
    assert before[generated]["generated"] == "true"
    assert before[w["link"]]["generated"] == "false"
    facet(page, "Связи").locator(".map-check", has_text="Только проверенные").locator(
        "input"
    ).check()
    settle(page)
    after = links(page)
    assert [k for k, v in after.items() if v["generated"] == "true"] == []
    assert w["link"] in after
    assert page.locator("[data-geo-link][data-generated='true']").count() == 0
    geo_built(events, response)


@req(GEO, TIME, invariant="граница 150 лет включительно у события; не наступившее не видно")
def test_event_visible_150_inclusive(knowledge_context, knowledge_stack, events):
    g = Geo(knowledge_stack.world)
    world = knowledge_stack.world
    world.person("Опорная персона", "1600", "1850")  # без места: окно 1600–1850
    ev = world.thing("event", "Основание академии", "1666")
    paris = g.place("Париж", 48.86, 2.35)
    g.happened(ev, paris)
    page, response = open_globe(
        knowledge_context, knowledge_stack, "/graph?view=globe&from=1600&to=1850&t=1665"
    )

    def mark():
        return {e["id"]: e for e in scene(page)["events"]}.get(ev)

    assert mark() is None
    focus_globe(page)
    press(page, "]")
    assert (mark()["age"], mark()["place"]) == (0, paris)
    assert "Основание академии" in rows(page)[paris]["who"]
    press(page, "PageUp", 15)
    assert year(page) == 1816
    assert mark()["age"] == 150
    press(page, "]")
    assert mark() is None
    geo_built(events, response)


@req(GEO, TIME, invariant="не родившаяся персона и связь до своего года не показываются")
def test_not_born_not_shown(knowledge_context, knowledge_stack, events):
    w = link_world(knowledge_stack.world)
    page, response = open_globe(
        knowledge_context, knowledge_stack, "/graph?view=globe&from=1700&to=1940&t=1723"
    )
    assert where_is(page, "Иммануил Кант") == []
    assert w["kant"] not in persons(page)
    assert _no_link(page, w)
    focus_globe(page)
    press(page, "]")
    assert where_is(page, "Иммануил Кант") == [w["konigsberg"]]
    assert persons(page)[w["kant"]]["place"] == w["konigsberg"]
    assert _no_link(page, w)  # год связи — 1744
    geo_built(events, response)


@req(GEO, TIME, invariant="непрозрачность убывает с data-age от 1 до 0,15")
def test_opacity_by_age(knowledge_context, knowledge_stack, events):
    w = link_world(knowledge_stack.world)
    page, response = open_globe(
        knowledge_context, knowledge_stack, "/graph?view=globe&from=1700&to=1940&t=1744"
    )
    seen = []
    focus_globe(page)
    for step in range(16):
        m = persons(page)[w["hume"]]
        lk = links(page)[w["link"]]
        seen.append((m["age"], m["opacity"], lk["age"], lk["opacity"]))
        if step < 15:
            press(page, "PageUp")
    # Юм умер 1776 → возраст медальона с 1776; связь — с 1744.
    link_ages = [s[2] for s in seen]
    link_op = [s[3] for s in seen]
    assert link_ages[0] == 0 and link_ages[-1] == 150
    assert link_op[0] == pytest.approx(1, abs=0.01)
    assert link_op[-1] == pytest.approx(0.15, abs=0.01)
    assert all(a >= b for a, b in itertools.pairwise(link_op))
    medal = [(s[0], s[1]) for s in seen]
    assert medal[0] == (0, pytest.approx(1, abs=0.01))
    assert all(a[1] >= b[1] for a, b in itertools.pairwise(medal))
    assert medal[-1][0] == 1894 - 1776
    geo_built(events, response)


@req(
    GEO,
    TIME,
    invariant="связь, у одной из персон которой нет места на год T, не рисуется и не считается; связь со скрытым поворотом концом считается",
)
def test_link_without_main_place_not_drawn(knowledge_context, knowledge_stack, events):
    w = link_world(knowledge_stack.world)
    world = knowledge_stack.world
    wolff = world.person("Христиан Вольф", "1679", "1754")  # без места
    no_place = world.relate(w["kant"], "influenced_by", wolff)
    page, response = open_globe(knowledge_context, knowledge_stack, "/graph?view=globe&t=1760")
    assert no_place not in links(page)
    assert set(links(page)) == {w["link"]}
    assert page.locator("[data-geo-limit='links']").count() == 0
    # Конец скрыт поворотом — связь в DOM (data-hidden) и в счёте.
    focus_globe(page)
    press(page, "Shift+ArrowRight", 6)
    settle(page)
    lk = links(page)[w["link"]]
    assert lk["hidden"] == "true" and lk["d"] is None
    geo_built(events, response)


@req(GEO, TIME, invariant="связи — только те, что карта показывает, с её фильтрами")
def test_links_follow_map_filters(knowledge_context, knowledge_stack, events):
    w = link_world(knowledge_stack.world)
    page, response = open_globe(
        knowledge_context, knowledge_stack, "/graph?view=globe&t=1760&to=1770&from=1700"
    )
    assert set(links(page)) == {w["link"]}
    geo_built(events, response)
    page.context.close()
    # Окно, в котором ученика нет, — карта связи не показывает, и глобус тоже.
    page, response = open_globe(
        knowledge_context, knowledge_stack, "/graph?view=globe&from=1700&to=1720&t=1720"
    )
    assert links(page) == {}
    geo_built(events, response)


# --- Размещение на глобусе --------------------------------------------------------------


def placement_world(world) -> dict[str, str]:
    g = Geo(world)
    ids = {
        "kant": world.person("Иммануил Кант", "1724", "1804"),
        "descartes": world.person("Рене Декарт", "1596", "1650"),
        "wolff": world.person("Христиан Вольф", "1679", "1754"),
        "konigsberg": g.place("Кёнигсберг", 54.71, 20.51),
        "amsterdam": g.place("Амстердам", 52.37, 4.89),
    }
    g.lived(ids["kant"], ids["konigsberg"])
    g.lived(ids["descartes"], ids["amsterdam"])
    return ids


@req(GEO, PLACE, scenario="Счётчик без места")
def test_unplaced_counter(knowledge_context, knowledge_stack, events):
    w = placement_world(knowledge_stack.world)
    page, response = open_globe(knowledge_context, knowledge_stack, "/graph?view=globe&t=1740")
    assert w["wolff"] not in persons(page)
    assert set(persons(page)) == {w["kant"], w["descartes"]}
    counter = page.locator("[data-geo-unplaced]")
    expect(counter).to_have_text("1 без места")
    counter.click()
    listed = page.locator(".geo-list__unplaced")
    expect(listed.get_by_role("button", name="Христиан Вольф")).to_be_visible()
    listed.get_by_role("button", name="Христиан Вольф").click()
    expect(page.get_by_role("complementary", name="Карточка")).to_contain_text("Христиан Вольф")
    assert geo_built(events, response).get("unplaced") == 1


@req(GEO, PLACE, scenario="Непроверенное место")
def test_unverified_place(knowledge_context, knowledge_stack, events):
    g = Geo(knowledge_stack.world)
    locke = knowledge_stack.world.person("Джон Локк", "1632", "1704")
    london = g.place("Лондон", 51.51, -0.13)
    g.lived(locke, london, generated=True)
    page, response = open_globe(knowledge_context, knowledge_stack, "/graph?view=globe&t=1690")
    assert persons(page)[locke]["unverified"] == "true"
    assert rows(page)[london]["unverified"]
    # Отличие не только цветом: пунктирное кольцо медальона.
    ring = page.locator(f"[data-geo-person='{locke}'] .geo-medal__ring")
    dash = ring.evaluate("e => getComputedStyle(e).strokeDasharray")
    assert dash not in ("none", "", "0"), dash
    geo_built(events, response)


@req(GEO, PLACE, invariant="непроверенным место — только когда все показанные размещения достроены")
def test_mixed_place_is_verified(knowledge_context, knowledge_stack, events):
    g = Geo(knowledge_stack.world)
    world = knowledge_stack.world
    locke = world.person("Джон Локк", "1632", "1704")
    newton = world.person("Исаак Ньютон", "1643", "1727")
    london = g.place("Лондон", 51.51, -0.13)
    g.lived(locke, london, generated=True)
    g.lived(newton, london)
    page, response = open_globe(knowledge_context, knowledge_stack, "/graph?view=globe&t=1690")
    m = persons(page)
    assert (m[locke]["unverified"], m[newton]["unverified"]) == ("true", "false")
    assert not rows(page)[london]["unverified"]
    unverified_ring = page.locator(f"[data-geo-person='{newton}'] .geo-medal__ring")
    assert unverified_ring.evaluate("e => getComputedStyle(e).strokeDasharray") in ("none", "")
    geo_built(events, response)


XSS = '<img src=x onerror="window.__xss=1">'


@req(GEO, PLACE, scenario="Название как текст")
def test_place_name_as_text(knowledge_context, knowledge_stack, events):
    g = Geo(knowledge_stack.world)
    who = knowledge_stack.world.person("Персона <b>X</b>", "1700", "1780")
    evil = g.place(XSS, 48.0, 10.0)
    g.lived(who, evil)
    page, response = open_globe(knowledge_context, knowledge_stack, "/graph?view=globe&t=1740")
    sc = scene(page)
    [m] = sc["persons"]
    page.mouse.move(sc["left"] + m["box"]["cx"], sc["top"] + m["box"]["cy"])
    expect(page.locator("[data-geo-tip]")).to_have_text(f"<b>X</b> — {XSS}, Германия")
    assert rows(page)[evil]["label"] == f"{XSS}, Германия"
    page.locator(f"[data-geo-row='{evil}'] .geo-row__place").click()
    expect(page.locator(".map-selected__name")).to_contain_text(XSS)
    assert page.evaluate("typeof window.__xss") == "undefined"
    assert page.locator(".geo-stage img, .map-panel img, .geo-globe image").count() == 0
    assert page.locator(".geo-stage b, .map-panel b").count() == 0
    assert "Персона <b>X</b>" in rows(page)[evil]["who"]
    geo_built(events, response)
    errors(page)


@req(GEO, PLACE, invariant="нет медальонов и значков без размещения и в (0, 0)")
def test_no_marks_without_placement(knowledge_context, knowledge_stack, events):
    w = placement_world(knowledge_stack.world)
    world = knowledge_stack.world
    ev = world.thing("event", "Событие без места", "1740")
    nowhere = Geo(world).place("Место без координат")
    g = Geo(world)
    leibniz = world.person("Готфрид Лейбниц", "1646", "1716")
    g.lived(leibniz, nowhere)
    page, response = open_globe(knowledge_context, knowledge_stack, "/graph?view=globe&t=1700")
    sc = scene(page)
    assert {p["id"] for p in sc["persons"]} == {w["descartes"]}  # Кант ещё не родился
    assert [e["id"] for e in sc["events"]] == []
    assert ev not in {e["id"] for e in sc["events"]}
    assert set(rows(page)) == {w["amsterdam"]}
    for p in sc["persons"]:
        assert not (abs(p["box"]["cx"]) < 1 and abs(p["box"]["cy"]) < 1), p
    expect(page.locator("[data-geo-unplaced]")).to_have_text("3 без места")
    built = geo_built(events, response)
    assert built.get("unplaced") == 3  # Вольф, Лейбниц (место без координат), событие
    errors(page)


@req(
    GEO,
    PLACE,
    invariant="медальон персоны и значок события — только у точки привязки места, сдвиг не больше MAX_SHIFT",
)
def test_people_merged_in_one_mark(knowledge_context, knowledge_stack, events):
    g = Geo(knowledge_stack.world)
    world = knowledge_stack.world
    paris = g.place("Париж", 48.86, 2.35)
    who = []
    for name, b, d in (
        ("Дидро", "1713", "1784"),
        ("Д'Аламбер", "1717", "1783"),
        ("Руссо", "1712", "1778"),
    ):
        who.append(world.person(name, b, d))
        g.lived(who[-1], paris)
    ev = world.thing("event", "Энциклопедия", "1751")
    g.happened(ev, paris)
    page, response = open_globe(knowledge_context, knowledge_stack, "/graph?view=globe&t=1760")
    sc = scene(page)
    assert {p["id"]: p["place"] for p in sc["persons"]} == dict.fromkeys(who, paris)
    assert [(e["id"], e["place"]) for e in sc["events"]] == [(ev, paris)]
    x, y, _ = project(2.35, 48.86, sc)
    for m in [
        *(p for p in sc["persons"] if drawn(p)),
        *(e for e in sc["events"] if e["hidden"] == "false"),
    ]:
        assert math.hypot(m["box"]["cx"] - x, m["box"]["cy"] - y) <= MAX_SHIFT + 0.5, m
    assert rows(page)[paris]["people"] == 3
    assert "Энциклопедия" in rows(page)[paris]["who"]
    geo_built(events, response)


@req(GEO, PLACE, scenario="Сдвиг от места")
@pytest.mark.parametrize("key", ["1x1", "7x1", "19x1", "40x1", "1x40"])
def test_shift_from_place(knowledge_context, knowledge_stack, events, key):
    people = dataset(knowledge_stack.world, key)
    knowledge_stack.world.person("Без места", "1700", "1780")
    checked = 0
    for width, height in ((1024, 576), (1920, 1080)):
        page, response = open_globe(
            knowledge_context,
            knowledge_stack,
            "/graph?view=globe&t=1750",
            width=width,
            height=height,
        )
        coords = coords_of(response.json())
        focus_globe(page)
        for steps in (0, 3, 10):  # 1; 1,95; 8
            press(page, "-", 12)
            press(page, "+", steps)
            settle(page)
            sc = scene(page)
            assert shift_faults(sc, coords) == [], (width, sc["zoom"], shift_faults(sc, coords))
            ids = {p["id"] for p in sc["persons"]}
            assert ids == {p for ps in people.values() for p in ps}
            checked += sum(1 for p in sc["persons"] if drawn(p))
        geo_built(events, response)
        page.context.close()
    assert checked > 0


# --- Выбор на глобусе -------------------------------------------------------------------


def school_world(world) -> dict[str, str]:
    g = Geo(world)
    ids = {
        "kant": world.person("Иммануил Кант", "1724", "1804"),
        "hume": world.person("Дэвид Юм", "1711", "1776"),
        "fichte": world.person("Иоганн Фихте", "1762", "1814"),
        "locke": world.person("Джон Локк", "1632", "1704"),
        "konigsberg": g.place("Кёнигсберг", 54.71, 20.51),
        "edinburgh": g.place("Эдинбург", 55.95, -3.19),
        "jena": g.place("Йена", 50.93, 11.59),
        "london": g.place("Лондон", 51.51, -0.13),
    }
    for who, where in (
        ("kant", "konigsberg"),
        ("hume", "edinburgh"),
        ("fichte", "jena"),
        ("locke", "london"),
    ):
        g.lived(ids[who], ids[where])
    ids["hume_kant"] = world.relate(ids["kant"], "influenced_by", ids["hume"])
    ids["kant_fichte"] = world.relate(ids["fichte"], "influenced_by", ids["kant"])
    ids["locke_hume"] = world.relate(ids["hume"], "influenced_by", ids["locke"])
    return ids


@req(GEO, SEL, scenario="Выбран Кант")
def test_kant_selected(knowledge_context, knowledge_stack, events):
    w = school_world(knowledge_stack.world)
    page, response = open_globe(
        knowledge_context, knowledge_stack, f"/graph/{w['kant']}?view=globe&t=1800"
    )
    m, lk = persons(page), links(page)
    assert m[w["kant"]]["role"] == "self"
    assert m[w["hume"]]["role"] == "teacher" and lk[w["hume_kant"]]["role"] == "teacher"
    assert m[w["fichte"]]["role"] == "student" and lk[w["kant_fichte"]]["role"] == "student"
    for pid in (w["kant"], w["hume"], w["fichte"]):
        assert m[pid]["dim"] != "true"
    for lid in (w["hume_kant"], w["kant_fichte"]):
        assert lk[lid]["dim"] != "true"
    assert lk[w["locke_hume"]]["dim"] == "true" and lk[w["locke_hume"]]["role"] is None
    assert m[w["locke"]]["dim"] == "true" and m[w["locke"]]["role"] is None
    expect(page.locator("[data-geo-where]")).to_be_visible()
    geo_built(events, response)


@req(GEO, SEL, invariant="приглушённые остаются выбираемыми")
def test_dimmed_still_selectable(knowledge_context, knowledge_stack, events):
    w = school_world(knowledge_stack.world)
    page, response = open_globe(
        knowledge_context, knowledge_stack, f"/graph/{w['kant']}?view=globe&t=1800"
    )
    sc = scene(page)
    locke = next(p for p in sc["persons"] if p["id"] == w["locke"])
    assert locke["dim"] == "true"
    page.mouse.click(sc["left"] + locke["box"]["cx"], sc["top"] + locke["box"]["cy"])
    expect(page.locator(".map-selected__name")).to_contain_text("Джон Локк")
    m = persons(page)
    assert m[w["locke"]]["role"] == "self" and m[w["locke"]]["dim"] != "true"
    geo_built(events, response)


@req(GEO, SEL, invariant="щелчок по полю глобуса снимает выбор")
def test_click_on_field_clears(knowledge_context, knowledge_stack, events):
    w = school_world(knowledge_stack.world)
    page, response = open_globe(
        knowledge_context, knowledge_stack, f"/graph/{w['kant']}?view=globe&t=1800"
    )
    assert persons(page)[w["kant"]]["role"] == "self"
    sc = scene(page)
    page.mouse.click(sc["left"] + 3, sc["top"] + sc["h"] - 3)
    settle(page)
    path, q = address(page)
    assert w["kant"] not in path and q.get("view") == "globe"
    assert all(p["role"] is None and p["dim"] is None for p in persons(page).values())
    geo_built(events, response)


@req(GEO, SEL, scenario="Место")
def test_place_mark_selection(knowledge_context, knowledge_stack, events):
    g = Geo(knowledge_stack.world)
    world = knowledge_stack.world
    paris = g.place("Париж", 48.86, 2.35)
    diderot = world.person("Дидро", "1713", "1784")
    dal = world.person("д'Аламбер", "1717", "1783")
    g.lived(diderot, paris)
    g.lived(dal, paris)
    page, response = open_globe(knowledge_context, knowledge_stack, "/graph?view=globe&t=1750")
    page.locator(f"[data-geo-row='{paris}'] .geo-row__place").click()
    expect(page.locator(".map-selected__name")).to_have_text("Париж, Франция, 1750")
    who = page.locator(".geo-selected__who button")
    expect(who).to_have_count(2)
    assert sorted(who.all_inner_texts()) == sorted(["Дидро", "д'Аламбер"])
    m = persons(page)
    assert m[diderot]["role"] == "self" and m[dal]["role"] == "self"
    geo_built(events, response)


@req(GEO, SEL, scenario="Выбран без места")
def test_selected_without_place(knowledge_context, knowledge_stack, events):
    placement_world(knowledge_stack.world)
    page, response = open_globe(knowledge_context, knowledge_stack, "/graph?view=globe&t=1740")
    before = (center(page), zoom(page))
    field = page.locator(".map-search input")
    field.fill("Вольф")
    page.locator(".map-search__row", has_text="Христиан Вольф").click()
    settle(page)
    expect(page.locator(".map-selected")).to_contain_text("Христиан Вольф")
    expect(page.locator(".map-selected")).to_contain_text("нет места на глобусе")
    assert (center(page), zoom(page)) == before
    geo_built(events, response)


@req(
    GEO,
    SEL,
    invariant="выбор события выделяет его значок и медальоны участников, остальное приглушено",
)
def test_event_selection(knowledge_context, knowledge_stack, events):
    g = Geo(knowledge_stack.world)
    world = knowledge_stack.world
    ev = world.thing("event", "Спор о пантеизме", "1785")
    berlin = g.place("Берлин", 52.52, 13.4)
    kgb = g.place("Кёнигсберг", 54.71, 20.51)
    old = g.place("Лондон", 51.51, -0.13)
    g.happened(ev, berlin)
    jacobi = world.person("Фридрих Якоби", "1743", "1819")
    kant = world.person("Иммануил Кант", "1724", "1804")
    locke = world.person("Джон Локк", "1632", "1704")
    g.lived(jacobi, berlin)
    g.lived(kant, kgb)
    g.lived(locke, old)  # к 1785 давно умер, виден бледным
    world.relate(jacobi, "participated", ev)
    world.relate(kant, "participated", ev)
    page, response = open_globe(
        knowledge_context, knowledge_stack, f"/graph/{ev}?view=globe&t=1785"
    )
    sc = scene(page)
    [mark] = [e for e in sc["events"] if e["id"] == ev]
    assert mark["role"] is not None and mark["dim"] != "true", mark
    m = {p["id"]: p for p in sc["persons"]}
    for pid in (jacobi, kant):
        assert m[pid]["role"] is not None and m[pid]["dim"] != "true", m[pid]
    assert m[locke]["role"] is None and m[locke]["dim"] == "true"
    block = page.locator("[data-geo-where]")
    expect(block.locator("[data-geo-where-place]")).to_have_text("Берлин")
    expect(block.locator("[data-geo-where-role]")).to_have_text("событие")
    geo_built(events, response)


@req(GEO, SEL, invariant="выбор группы — медальоны до шести значимых участников цветами c1…c6")
def test_group_selection_c1_c6(knowledge_context, knowledge_stack, events):
    g = Geo(knowledge_stack.world)
    world = knowledge_stack.world
    group = world.thing("group", "Эмпиризм")
    world.statements.add(group, "group_kind", value="direction", attributions=COMMON)
    members = []
    for i in range(7):
        p = world.person(f"Эмпирик {i}", str(1700 + i), str(1770 + i))
        world.relate(p, "member_of", group)
        for _ in range(7 - i):  # вес убывает с i
            world.describe(p, f"описание {i} {_}")
        place = g.place(f"Город {i}", 40 + i, -10 + 5 * i)
        g.lived(p, place)
        members.append(p)
    outsider = world.person("Чужой", "1700", "1780")
    g.lived(outsider, g.place("Город чужой", 30, 30))
    page, response = open_globe(
        knowledge_context, knowledge_stack, f"/graph/{group}?view=globe&t=1750"
    )
    m = persons(page)
    colored = [m[p]["role"] for p in members if re.fullmatch(r"c[1-6]", m[p]["role"] or "")]
    assert len(colored) == 6, [m[p]["role"] for p in members]
    assert len(set(colored)) == 6
    # Седьмой по весу — не среди выделенных цветом c1…c6 (роль остальных спецификация не задаёт).
    assert m[members[6]]["role"] not in {
        "c1",
        "c2",
        "c3",
        "c4",
        "c5",
        "c6",
        "self",
        "teacher",
        "student",
    }
    assert m[outsider]["dim"] == "true"
    geo_built(events, response)


# --- Текстовая альтернатива и клавиатура ------------------------------------------------


def many_world(world) -> dict[str, str]:
    ids = school_world(world)
    g = Geo(world)
    berlin = g.place("Берлин", 52.52, 13.4)
    for name, b, d in (
        ("Мендельсон", "1729", "1786"),
        ("Николаи", "1733", "1811"),
        ("Ламберт", "1728", "1777"),
    ):
        g.lived(world.person(name, b, d), berlin)
    ids["berlin"] = berlin
    return ids


@req(GEO, A11Y, scenario="Список совпадает с глобусом")
def test_list_matches_globe(knowledge_context, knowledge_stack, events):
    many_world(knowledge_stack.world)
    g = Geo(knowledge_stack.world)
    ev = knowledge_stack.world.thing("event", "Событие года", "1780")
    g.happened(ev, g.place("Рига", 56.95, 24.1))
    page, response, data = open_globe_map(
        knowledge_context, knowledge_stack, "/graph?view=globe&t=1781"
    )
    sc, r = scene(page), rows(page)
    label_of = {p["id"]: p["label"] for p in data["people"]}
    places = {p["place"] for p in sc["persons"]} | {e["place"] for e in sc["events"]}
    assert page.locator("[data-geo-row]").count() == len(places)
    assert set(r) == places
    assert sum(v["people"] for v in r.values()) == len(sc["persons"])
    labels = {p["id"]: p["label"] for p in response.json()["places"]}
    for p in sc["persons"]:
        assert label_of[p["id"]] in r[p["place"]]["who"], (p["id"], r[p["place"]]["who"])
    order = row_order(page)
    assert [r[i]["people"] for i in order] == sorted((r[i]["people"] for i in order), reverse=True)
    for pid in order:
        assert r[pid]["label"].split(", ")[0] == labels[pid]
    expect(page.locator(".geo-list .map-panel__h")).to_have_text("Места в 1781 году")
    geo_built(events, response)


@req(GEO, A11Y, invariant="список включает места медальонов дальнего полушария")
def test_list_includes_hidden(knowledge_context, knowledge_stack, events):
    w = many_world(knowledge_stack.world)
    g = Geo(knowledge_stack.world)
    pacific = g.place("Тихий океан", 0, -160)
    sailor = knowledge_stack.world.person("Мореплаватель", "1728", "1779")
    g.lived(sailor, pacific)
    page, response = open_globe(knowledge_context, knowledge_stack, "/graph?view=globe&t=1760")
    page.locator(f"[data-geo-row='{w['konigsberg']}'] .geo-row__place").click()
    expect(globe(page)).to_have_attribute("data-center", "20.51,54.71")
    settle(page)
    sc = scene(page)
    m = {p["id"]: p for p in sc["persons"]}
    assert m[sailor]["hidden"] == "true"
    assert page.locator("[data-geo-row]").count() == len({p["place"] for p in sc["persons"]})
    assert pacific in rows(page) and "Мореплаватель" in rows(page)[pacific]["who"]
    geo_built(events, response)


def _focus_visible(page) -> bool:
    return page.evaluate(
        """() => { const e = document.activeElement;
            if (!e || e === document.body) return false;
            if (!e.matches(':focus-visible')) return false;
            const s = getComputedStyle(e);
            const ringOf = n => { const t = getComputedStyle(n);
              return (t.outlineStyle !== 'none' && parseFloat(t.outlineWidth) > 0)
                || (t.boxShadow && t.boxShadow !== 'none'); };
            // кольцо — у самого элемента или у его рамки (поле поиска — у обёртки)
            const ring = ringOf(e) || (e.parentElement && ringOf(e.parentElement))
              || (e.parentElement?.parentElement && ringOf(e.parentElement.parentElement));
            const host = e.closest('.geo-stage');
            const hostRing = host && getComputedStyle(host).outlineStyle !== 'none';
            return ring || Boolean(hostRing) || e.matches('.geo-globe:focus-visible'); }"""
    )


@req(GEO, A11Y, scenario="Только клавиатурой")
def test_keyboard_only(knowledge_context, knowledge_stack, events):
    w = many_world(knowledge_stack.world)
    page, response = open_globe(knowledge_context, knowledge_stack, "/graph?view=globe&t=1781")
    for _ in range(80):
        page.keyboard.press("Tab")
        assert _focus_visible(page), page.evaluate("document.activeElement.outerHTML.slice(0,200)")
        if page.evaluate("document.activeElement.classList.contains('geo-globe')"):
            break
    else:
        raise AssertionError("Tab не дошёл до глобуса")
    page.keyboard.press("PageDown")
    assert year(page) == 1771
    target = f"[data-geo-row='{w['konigsberg']}'] .geo-row__place"
    for _ in range(80):
        page.keyboard.press("Tab")
        assert _focus_visible(page), page.evaluate("document.activeElement.outerHTML.slice(0,200)")
        if page.evaluate(f'document.activeElement === document.querySelector("{target}")'):
            break
    else:
        raise AssertionError("Tab не дошёл до строки Кёнигсберга")
    page.keyboard.press("Enter")
    expect(globe(page)).to_have_attribute("data-center", "20.51,54.71")
    assert year(page) == 1771
    assert _focus_visible(page)
    geo_built(events, response)


def _watch_live(page) -> None:
    page.evaluate(
        """() => { window.__live = [];
            const el = document.querySelector('[data-geo-live]');
            new MutationObserver(() => window.__live.push([performance.now(), el.textContent,
                document.querySelector('.geo-yearbar__play').textContent]))
              .observe(el, {childList: true, characterData: true, subtree: true}); }"""
    )


@req(GEO, A11Y, scenario="Живая область не частит")
def test_live_region_not_chatty(knowledge_context, knowledge_stack, events):
    many_world(knowledge_stack.world)
    page, response = open_globe(
        knowledge_context,
        knowledge_stack,
        "/graph?view=globe&t=1781&from=1700&to=1800",
        before=lambda p: p.clock.install(),
    )
    _watch_live(page)
    focus_globe(page)
    for _ in range(5):
        page.keyboard.press("]")
        page.clock.run_for(100)
    play_button(page).click()
    expect(play_button(page)).to_have_text("Пауза")
    page.clock.run_for(3000)
    changes = page.evaluate("window.__live")
    assert len(changes) <= 1, changes
    for _, _text, button in changes:
        assert "Играть" in button, changes  # только до запуска проигрывания
    geo_built(events, response)


@req(GEO, A11Y, invariant="живая область объявляет на паузе после шага, не чаще раза в секунду")
def test_live_region_announces_after_step(knowledge_context, knowledge_stack, events):
    many_world(knowledge_stack.world)
    page, response = open_globe(
        knowledge_context,
        knowledge_stack,
        "/graph?view=globe&t=1781",
        before=lambda p: p.clock.install(),
    )
    _watch_live(page)
    focus_globe(page)
    for _ in range(3):
        page.keyboard.press("]")
        page.clock.run_for(200)
    page.clock.run_for(2000)
    changes = page.evaluate("window.__live")
    assert len(changes) >= 1
    times = [c[0] for c in changes]
    assert all(b - a >= 1000 for a, b in itertools.pairwise(times)), times
    n = len(rows(page))
    m = sum(v["people"] for v in rows(page).values())
    expected = (
        f"1784 год: {n} {plural(n, ('место', 'места', 'мест'))}, "
        f"{m} {plural(m, ('человек', 'человека', 'человек'))}"
    )
    assert changes[-1][1] == expected
    geo_built(events, response)


@req(
    GEO,
    A11Y,
    invariant="глобус — одна точка фокуса с ролью, сводкой и подсказкой; медальоны, значки, подписи и подсказка скрыты от читалок",
)
def test_globe_accessibility_attributes(knowledge_context, knowledge_stack, events):
    many_world(knowledge_stack.world)
    page, response = open_globe(knowledge_context, knowledge_stack, "/graph?view=globe&t=1781")
    g = globe(page)
    assert g.get_attribute("role") == "application"
    assert g.get_attribute("aria-roledescription") == "глобус"
    n = len(rows(page))
    m = sum(v["people"] for v in rows(page).values())
    assert g.get_attribute("aria-label") == (
        f"Глобус, 1781 год: {n} {plural(n, ('место', 'места', 'мест'))}, "
        f"{m} {plural(m, ('человек', 'человека', 'человек'))}"
    )
    hint = g.get_attribute("aria-describedby")
    assert hint and page.locator(f"#{hint}").count() == 1
    assert page.locator(f"#{hint}").text_content().strip()
    assert g.get_attribute("tabindex") == "0"
    sc = scene(page)
    m0 = next(p for p in sc["persons"] if drawn(p))
    page.mouse.move(sc["left"] + m0["box"]["cx"], sc["top"] + m0["box"]["cy"])
    page.locator("[data-geo-tip]").wait_for()
    hidden_marks = page.locator(
        "[data-geo-person], [data-geo-name], [data-geo-more], [data-geo-event], [data-geo-country], [data-geo-tip]"
    ).evaluate_all(
        "es => es.length > 0 && es.every(e => e.closest('[aria-hidden=\"true\"]') !== null)"
    )
    assert hidden_marks
    focusable_inside = page.locator(
        ".geo-globe [tabindex], .geo-globe a, .geo-globe button"
    ).count()
    assert focusable_inside == 0
    geo_built(events, response)


@req(GEO, A11Y, invariant="Esc снимает выбор")
def test_escape_clears_selection(knowledge_context, knowledge_stack, events):
    w = school_world(knowledge_stack.world)
    page, response = open_globe(
        knowledge_context, knowledge_stack, f"/graph/{w['kant']}?view=globe&t=1800"
    )
    assert persons(page)[w["kant"]]["role"] == "self"
    focus_globe(page)
    page.keyboard.press("Escape")
    settle(page)
    path, q = address(page)
    assert w["kant"] not in path and q.get("sel") is None
    assert q.get("view") == "globe"
    assert all(v["role"] is None and v["dim"] is None for v in persons(page).values())
    assert all(v["role"] is None and v["dim"] is None for v in links(page).values())
    geo_built(events, response)


# --- Состояния --------------------------------------------------------------------------


@req(GEO, STATES, scenario="Загрузка")
def test_loading_state(knowledge_context, knowledge_stack, events):
    w = placement_world(knowledge_stack.world)
    held = []
    context = knowledge_context(1920, 1080)
    page = context.new_page()
    page.route(PLACES_API, lambda route: held.append(route))
    page.goto(f"{knowledge_stack.url}/graph?view=globe&t=1740")
    expect(page.locator(".geo-state--loading")).to_have_text("Загружаем места…")
    expect(globe(page)).to_have_attribute("aria-busy", "true")
    expect(page.locator("canvas[data-geo-land][data-drawn='true']")).to_have_count(1)
    borders = int(page.locator("canvas[data-geo-land]").get_attribute("data-borders"))
    assert borders > 0
    assert page.locator("[data-geo-person]").count() == 0
    assert len(held) == 1
    with page.expect_response(PLACES_API) as info:
        held[0].continue_()
    globe_ready(page)
    expect(page.locator(".geo-state--loading")).to_have_count(0)
    assert globe(page).get_attribute("aria-busy") == "false"
    assert w["kant"] in persons(page)
    geo_built(events, info.value)
    errors(page)


@req(GEO, STATES, scenario="Нет мест")
def test_no_places(knowledge_context, knowledge_stack, events):
    world = knowledge_stack.world
    kant = world.person("Иммануил Кант", "1724", "1804")
    world.person("Дэвид Юм", "1711", "1776")
    page, response = open_globe(knowledge_context, knowledge_stack, f"/graph/{kant}?view=globe")
    stage = page.locator(".geo-stage")
    expect(stage).to_contain_text("Мест пока нет")
    expect(stage).to_contain_text("Места появятся после обогащения из Wikidata.")
    assert geo_built(events, response).get("places") == 0
    stage.get_by_role("button", name="К хронологии").click()
    page.locator(".map-canvas").wait_for()
    path, q = address(page)
    assert "view" not in q and path.endswith(kant)
    expect(page.locator(".map-selected__name")).to_contain_text("Иммануил Кант")


@req(GEO, STATES, scenario="Пустой год")
def test_empty_year(knowledge_context, knowledge_stack, events):
    g = Geo(knowledge_stack.world)
    world = knowledge_stack.world
    world.person("Николай Кузанский", "1401", "1464")  # без места: окно с 1401
    kant = world.person("Иммануил Кант", "1724", "1804")
    k = g.place("Кёнигсберг", 54.71, 20.51)
    g.lived(kant, k)
    page, response = open_globe(knowledge_context, knowledge_stack, "/graph?view=globe&t=1500")
    stage = page.locator(".geo-stage")
    expect(stage).to_contain_text("В 1500 году на карте никого нет")
    assert year(page) == 1500
    assert page.locator("[data-geo-person]").count() == 0
    stage.get_by_role("button", name="К ближайшему году").click()
    expect(globe(page)).to_have_attribute("data-year", "1724")
    assert persons(page)[kant]["place"] == k
    geo_built(events, response)


@req(
    GEO,
    STATES,
    invariant="К ближайшему году — по медальонам и значкам событий, считая скрытые поворотом",
)
def test_nearest_year_by_event_marks(knowledge_context, knowledge_stack, events):
    g = Geo(knowledge_stack.world)
    world = knowledge_stack.world
    world.person("Опорный", "1600", "1900")  # без места
    ev = world.thing("event", "Собор", "1700")
    g.happened(ev, g.place("Тихий океан", 0, -160))  # на дальней стороне исходного вида не будет
    page, response = open_globe(knowledge_context, knowledge_stack, "/graph?view=globe&t=1650")
    stage = page.locator(".geo-stage")
    expect(stage).to_contain_text("В 1650 году на карте никого нет")
    stage.get_by_role("button", name="К ближайшему году").click()
    expect(globe(page)).to_have_attribute("data-year", "1700")
    assert [e["id"] for e in scene(page)["events"]] == [ev]
    expect(stage).not_to_contain_text("на карте никого нет")
    # Мест на 1650 нет — исходный вид по умолчанию (Европа); Тихий океан на дальней стороне,
    # значок скрыт поворотом, а год всё равно не пустой.
    sc = scene(page)
    assert project(-160, 0, sc)[2] < 0, sc["center"]
    assert sc["events"][0]["hidden"] == "true"
    expect(stage).not_to_contain_text("на карте никого нет")
    geo_built(events, response)


@req(GEO, STATES, invariant="К ближайшему году: при равенстве — более ранний")
def test_nearest_year_tie_earlier(knowledge_context, knowledge_stack, events):
    g = Geo(knowledge_stack.world)
    world = knowledge_stack.world
    a, b = world.person("Ранний", "1600", "1640"), world.person("Поздний", "1960", "1990")
    p = g.place("Место", 10, 10)
    g.lived(a, p)
    g.lived(b, p)
    # Ранний виден до 1790, Поздний — с 1960; середина — 1875: до обоих по 85 лет.
    page, response = open_globe(knowledge_context, knowledge_stack, "/graph?view=globe&t=1875")
    stage = page.locator(".geo-stage")
    expect(stage).to_contain_text("В 1875 году на карте никого нет")
    stage.get_by_role("button", name="К ближайшему году").click()
    expect(globe(page)).to_have_attribute("data-year", "1790")
    geo_built(events, response)


@req(GEO, STATES, scenario="Ошибка слоя")
def test_layer_error(knowledge_context, knowledge_stack, events):
    w = placement_world(knowledge_stack.world)
    context = knowledge_context(1920, 1080)
    page = context.new_page()
    page.route(PLACES_API, lambda route: route.fulfill(status=500, json={"error": "сбой"}))
    page.goto(f"{knowledge_stack.url}/graph?view=globe&t=1740")
    alert = page.locator(".geo-stage [role='alert']")
    expect(alert).to_contain_text("Не удалось загрузить места")
    expect(alert.get_by_role("button", name="Повторить")).to_be_visible()
    errors(page)
    page.locator(".map-view-switch").get_by_role("button", name="Хронология").click()
    page.locator(".map-canvas").wait_for()
    assert page.locator(".map-person").count() == 3
    page.locator(".map-view-switch").get_by_role("button", name="Глобус").click()
    expect(alert.get_by_role("button", name="Повторить")).to_be_visible()
    page.unroute(PLACES_API)
    with page.expect_response(PLACES_API) as info:
        alert.get_by_role("button", name="Повторить").click()
    globe_ready(page)
    assert w["kant"] in persons(page)
    assert len(events.of(GEO_BUILT)) == 1
    geo_built(events, info.value)
    errors(page)
