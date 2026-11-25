"""Глобус: люди и связи во времени, размещение, выбор, текстовая альтернатива, состояния
(geo-timeline, задачи 7.4–7.5).

Требования «Люди, события и связи во времени», «Размещение на глобусе», «Выбор на глобусе»,
«Текстовая альтернатива и клавиатура глобуса», «Состояния глобуса» дельты
``openspec/specs/geo-timeline/spec.md``. Настоящий сервис знаний
(``knowledge_stack``); ``page.route`` — только для задержки и ответа 500.
Клиент событий журнала не пишет: серверный якорь — ``knowledge.geo.built`` по ``request_id``.
"""

from __future__ import annotations

import itertools
import re

import pytest
from playwright.sync_api import expect

from philograph.knowledge.statements import Attribution

from .geo_helpers import (
    GEO_BUILT,
    PLACES_API,
    Geo,
    address,
    center,
    errors,
    focus_globe,
    geo_built,
    globe,
    globe_ready,
    links,
    marks,
    open_globe,
    play_button,
    plural,
    press,
    row_order,
    rows,
    settle,
    where_is,
    year,
    zoom,
)

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
    name = "Рене Декарт"
    assert where_is(page, name) == [w["lahaye"]]
    assert set(marks(page)) == {w["lahaye"]}
    focus_globe(page)
    press(page, "PageUp", 3)
    assert year(page) == 1640
    assert where_is(page, name) == [w["amsterdam"]]
    press(page, "]", 10)
    assert year(page) == 1650
    assert where_is(page, name) == [w["stockholm"]]
    assert marks(page)[w["stockholm"]]["age"] == 0
    press(page, "PageUp", 15)
    assert year(page) == 1800
    assert where_is(page, name) == [w["stockholm"]]
    assert marks(page)[w["stockholm"]]["age"] == 150
    press(page, "]")
    assert year(page) == 1801
    assert where_is(page, name) == []
    assert w["stockholm"] not in marks(page)
    geo_built(events, response)
    errors(page)


@req(GEO, TIME, scenario="Юм без вида места")
def test_hume_without_role(knowledge_context, knowledge_stack, events):
    g = Geo(knowledge_stack.world)
    hume = knowledge_stack.world.person("Дэвид Юм", "1711", "1776")
    ed = g.place("Эдинбург", 55.95, -3.19)
    g.lived(hume, ed)
    page, response = open_globe(knowledge_context, knowledge_stack, "/graph?view=globe&t=1740")
    assert where_is(page, "Дэвид Юм") == [ed]
    assert marks(page)[ed]["age"] == 0
    focus_globe(page)
    press(page, "PageUp", 3)
    assert year(page) == 1770
    assert where_is(page, "Дэвид Юм") == [ed]
    assert marks(page)[ed]["age"] == 0
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


def _start_end(d: str) -> tuple[tuple[float, float], tuple[float, float]]:
    nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", d)]
    return (nums[0], nums[1]), (nums[-2], nums[-1])


def _translate(transform: str) -> tuple[float, float]:
    x, y = re.search(r"translate\(([-\d.]+),\s*([-\d.]+)\)", transform).groups()
    return float(x), float(y)


@req(GEO, TIME, scenario="Связь Юм → Кант")
def test_link_hume_kant_lifetime(knowledge_context, knowledge_stack, events):
    w = link_world(knowledge_stack.world)
    page, response = open_globe(
        knowledge_context, knowledge_stack, "/graph?view=globe&from=1700&to=1940&t=1743"
    )
    assert w["link"] not in links(page)
    focus_globe(page)
    press(page, "]")
    assert year(page) == 1744
    link = links(page)[w["link"]]
    assert link["age"] == 0
    start, end = _start_end(link["d"])
    m = marks(page)
    ex, ey = _translate(m[w["edinburgh"]]["transform"])
    kx, ky = _translate(m[w["konigsberg"]]["transform"])
    assert abs(start[0] - ex) < 2 and abs(start[1] - ey) < 2, (start, ex, ey)
    assert abs(end[0] - kx) < 2 and abs(end[1] - ky) < 2, (end, kx, ky)
    press(page, "PageUp", 15)
    assert year(page) == 1894
    assert links(page)[w["link"]]["age"] == 150
    press(page, "]")
    assert year(page) == 1895
    assert w["link"] not in links(page)
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
    assert paris not in marks(page)
    focus_globe(page)
    press(page, "]")
    assert marks(page)[paris]["age"] == 0
    assert "Основание академии" in rows(page)[paris]["who"]
    press(page, "PageUp", 15)
    assert year(page) == 1816
    assert marks(page)[paris]["age"] == 150
    press(page, "]")
    assert paris not in marks(page)
    geo_built(events, response)


@req(GEO, TIME, invariant="не родившаяся персона и связь до своего года не показываются")
def test_not_born_not_shown(knowledge_context, knowledge_stack, events):
    w = link_world(knowledge_stack.world)
    page, response = open_globe(
        knowledge_context, knowledge_stack, "/graph?view=globe&from=1700&to=1940&t=1723"
    )
    assert where_is(page, "Иммануил Кант") == []
    assert w["konigsberg"] not in marks(page)
    assert w["link"] not in links(page)
    focus_globe(page)
    press(page, "]")
    assert where_is(page, "Иммануил Кант") == [w["konigsberg"]]
    assert w["link"] not in links(page)  # год связи — 1744
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
        m = marks(page)[w["edinburgh"]]
        lk = links(page)[w["link"]]
        seen.append((m["age"], m["opacity"], lk["age"], lk["opacity"]))
        if step < 15:
            press(page, "PageUp")
    # Эдинбург: Юм умер 1776 → возраст с 1776; связь — с 1744.
    link_ages = [s[2] for s in seen]
    link_op = [s[3] for s in seen]
    assert link_ages[0] == 0 and link_ages[-1] == 150
    assert link_op[0] == pytest.approx(1, abs=0.01)
    assert link_op[-1] == pytest.approx(0.15, abs=0.01)
    assert all(a >= b for a, b in itertools.pairwise(link_op))
    place_op = [(s[0], s[1]) for s in seen]
    assert place_op[0] == (0, pytest.approx(1, abs=0.01))
    assert all(a[1] >= b[1] for a, b in itertools.pairwise(place_op))
    geo_built(events, response)


@req(GEO, TIME, invariant="связь без главного места не рисуется и не считается")
def test_link_without_main_place_not_drawn(knowledge_context, knowledge_stack, events):
    w = link_world(knowledge_stack.world)
    world = knowledge_stack.world
    wolff = world.person("Христиан Вольф", "1679", "1754")  # без места
    no_place = world.relate(w["kant"], "influenced_by", wolff)
    page, response = open_globe(knowledge_context, knowledge_stack, "/graph?view=globe&t=1760")
    assert no_place not in links(page)
    assert set(links(page)) == {w["link"]}
    assert page.locator("[data-geo-limit='links']").count() == 0
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
    assert w["wolff"] not in marks(page)
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
    assert marks(page)[london]["unverified"] == "true"
    assert rows(page)[london]["unverified"]
    ring = page.locator(f"[data-geo-place='{london}'] .geo-place__dot")
    fill = ring.evaluate("e => getComputedStyle(e).fill")
    stroke = ring.evaluate("e => getComputedStyle(e).stroke")
    assert fill in ("none", "transparent", "rgba(0, 0, 0, 0)") or fill != stroke  # полое кольцо
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
    assert marks(page)[london]["unverified"] == "false"
    assert not rows(page)[london]["unverified"]
    geo_built(events, response)


XSS = '<img src=x onerror="window.__xss=1">'


@req(GEO, PLACE, scenario="Название как текст")
def test_place_name_as_text(knowledge_context, knowledge_stack, events):
    g = Geo(knowledge_stack.world)
    who = knowledge_stack.world.person("Персона <b>X</b>", "1700", "1780")
    evil = g.place(XSS, 48.0, 10.0)
    g.lived(who, evil)
    page, response = open_globe(knowledge_context, knowledge_stack, "/graph?view=globe&t=1740")
    expect(page.locator(f"[data-geo-label='{evil}']")).to_have_text(XSS)
    assert rows(page)[evil]["label"] == XSS
    page.locator(f"[data-geo-row='{evil}'] .geo-row__place").click()
    expect(page.locator(".map-selected__name")).to_contain_text(XSS)
    assert page.evaluate("typeof window.__xss") == "undefined"
    assert page.locator(".geo-stage img, .map-panel img").count() == 0
    assert "Персона <b>X</b>" in rows(page)[evil]["who"]
    geo_built(events, response)
    errors(page)


@req(GEO, PLACE, invariant="нет отметок без размещения и в (0, 0)")
def test_no_marks_without_placement(knowledge_context, knowledge_stack, events):
    w = placement_world(knowledge_stack.world)
    world = knowledge_stack.world
    world.thing("event", "Событие без места", "1740")
    nowhere = Geo(world).place("Место без координат")
    g = Geo(world)
    leibniz = world.person("Готфрид Лейбниц", "1646", "1716")
    g.lived(leibniz, nowhere)
    page, response = open_globe(knowledge_context, knowledge_stack, "/graph?view=globe&t=1700")
    m = marks(page)
    assert set(m) == {w["amsterdam"]}  # Декарт виден до 1800; Кант ещё не родился
    assert set(rows(page)) == set(m)
    assert page.locator("[data-geo-place]").count() == 1
    expect(page.locator("[data-geo-unplaced]")).to_have_text("3 без места")
    built = geo_built(events, response)
    assert built.get("unplaced") == 3  # Вольф, Лейбниц (место без координат), событие
    errors(page)


@req(GEO, PLACE, invariant="люди в одном месте — одна отметка с числом людей")
def test_people_merged_in_one_mark(knowledge_context, knowledge_stack, events):
    g = Geo(knowledge_stack.world)
    world = knowledge_stack.world
    paris = g.place("Париж", 48.86, 2.35)
    for name, b, d in (
        ("Дидро", "1713", "1784"),
        ("Д'Аламбер", "1717", "1783"),
        ("Руссо", "1712", "1778"),
    ):
        g.lived(world.person(name, b, d), paris)
    ev = world.thing("event", "Энциклопедия", "1751")
    g.happened(ev, paris)
    page, response = open_globe(knowledge_context, knowledge_stack, "/graph?view=globe&t=1760")
    assert page.locator(f"[data-geo-place='{paris}']").count() == 1
    assert marks(page)[paris]["people"] == 3
    assert rows(page)[paris]["people"] == 3
    assert "Энциклопедия" in rows(page)[paris]["who"]
    geo_built(events, response)


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
    m, lk = marks(page), links(page)
    assert m[w["konigsberg"]]["role"] == "self"
    assert lk[w["hume_kant"]]["role"] == "teacher"
    assert lk[w["kant_fichte"]]["role"] == "student"
    assert lk[w["locke_hume"]]["dim"] == "true"
    for lid in (w["hume_kant"], w["kant_fichte"]):
        assert lk[lid]["dim"] != "true"
    assert m[w["london"]]["dim"] == "true"
    geo_built(events, response)


@req(GEO, SEL, invariant="приглушённые остаются выбираемыми")
def test_dimmed_still_selectable(knowledge_context, knowledge_stack, events):
    w = school_world(knowledge_stack.world)
    page, response = open_globe(
        knowledge_context, knowledge_stack, f"/graph/{w['kant']}?view=globe&t=1800"
    )
    assert marks(page)[w["london"]]["dim"] == "true"
    page.locator(f"[data-geo-place='{w['london']}'] .geo-place__hit").click(force=True)
    expect(page.locator(".map-selected__name")).to_contain_text("Лондон, 1800")
    assert marks(page)[w["london"]]["dim"] != "true"
    geo_built(events, response)


@req(GEO, SEL, scenario="Отметка места")
def test_place_mark_selection(knowledge_context, knowledge_stack, events):
    g = Geo(knowledge_stack.world)
    world = knowledge_stack.world
    paris = g.place("Париж", 48.86, 2.35)
    g.lived(world.person("Дидро", "1713", "1784"), paris)
    g.lived(world.person("д'Аламбер", "1717", "1783"), paris)
    page, response = open_globe(knowledge_context, knowledge_stack, "/graph?view=globe&t=1750")
    page.locator(f"[data-geo-place='{paris}'] .geo-place__hit").click(force=True)
    expect(page.locator(".map-selected__name")).to_have_text("Париж, 1750")
    who = page.locator(".geo-selected__who button")
    expect(who).to_have_count(2)
    assert sorted(who.all_inner_texts()) == sorted(["Дидро", "д'Аламбер"])
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


@req(GEO, SEL, invariant="выбор события выделяет его место и места участников")
def test_event_selection(knowledge_context, knowledge_stack, events):
    # «Участники» события на карте — живые в год события и стимулированные им (правило
    # хронологии); участник с явной связью «участвовал» жив в 1785 — подходит под оба чтения.
    g = Geo(knowledge_stack.world)
    world = knowledge_stack.world
    ev = world.thing("event", "Спор о пантеизме", "1785")
    berlin = g.place("Берлин", 52.52, 13.4)
    kgb = g.place("Кёнигсберг", 54.71, 20.51)
    old = g.place("Лондон", 51.51, -0.13)
    g.happened(ev, berlin)
    jacobi = world.person("Фридрих Якоби", "1743", "1819")
    kant = world.person("Иммануил Кант", "1724", "1804")
    g.lived(jacobi, berlin)
    g.lived(kant, kgb)
    g.lived(world.person("Джон Локк", "1632", "1704"), old)  # к 1785 давно умер, виден бледным
    world.relate(jacobi, "participated", ev)
    world.relate(kant, "participated", ev)
    page, response = open_globe(
        knowledge_context, knowledge_stack, f"/graph/{ev}?view=globe&t=1785"
    )
    m = marks(page)
    assert m[berlin]["role"] == "self" and m[berlin]["dim"] != "true"
    assert m[kgb]["role"] is not None and m[kgb]["dim"] != "true"
    assert m[old]["role"] is None and m[old]["dim"] == "true"
    geo_built(events, response)


@req(GEO, SEL, invariant="выбор группы — места до шести значимых участников цветами c1…c6")
def test_group_selection_c1_c6(knowledge_context, knowledge_stack, events):
    g = Geo(knowledge_stack.world)
    world = knowledge_stack.world
    group = world.thing("group", "Эмпиризм")
    world.statements.add(group, "group_kind", value="direction", attributions=COMMON)
    places = []
    for i in range(7):
        p = world.person(f"Эмпирик {i}", str(1700 + i), str(1770 + i))
        world.relate(p, "member_of", group)
        for _ in range(7 - i):  # вес убывает с i
            world.describe(p, f"описание {i} {_}")
        place = g.place(f"Город {i}", 40 + i, -10 + 5 * i)
        g.lived(p, place)
        places.append(place)
    outsider_place = g.place("Город чужой", 30, 30)
    g.lived(world.person("Чужой", "1700", "1780"), outsider_place)
    page, response = open_globe(
        knowledge_context, knowledge_stack, f"/graph/{group}?view=globe&t=1750"
    )
    m = marks(page)
    colored = [m[p]["role"] for p in places if re.fullmatch(r"c[1-6]", m[p]["role"] or "")]
    assert len(colored) == 6, [m[p]["role"] for p in places]
    assert len(set(colored)) == 6
    assert m[outsider_place]["dim"] == "true"
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
    page, response = open_globe(knowledge_context, knowledge_stack, "/graph?view=globe&t=1781")
    m, r = marks(page), rows(page)
    assert page.locator("[data-geo-row]").count() == page.locator("[data-geo-place]").count()
    assert set(r) == set(m)
    assert sum(v["people"] for v in r.values()) == sum(v["people"] for v in m.values())
    order = row_order(page)
    assert [r[i]["people"] for i in order] == sorted((r[i]["people"] for i in order), reverse=True)
    expect(page.locator(".geo-list .map-panel__h")).to_have_text("Места в 1781 году")
    geo_built(events, response)


@req(GEO, A11Y, invariant="список включает отметки дальнего полушария")
def test_list_includes_hidden(knowledge_context, knowledge_stack, events):
    w = many_world(knowledge_stack.world)
    g = Geo(knowledge_stack.world)
    pacific = g.place("Тихий океан", 0, -160)
    g.lived(knowledge_stack.world.person("Мореплаватель", "1728", "1779"), pacific)
    page, response = open_globe(knowledge_context, knowledge_stack, "/graph?view=globe&t=1760")
    m = marks(page)
    page.locator(f"[data-geo-row='{w['konigsberg']}'] .geo-row__place").click()
    expect(globe(page)).to_have_attribute("data-center", "20.51,54.71")
    m = marks(page)
    assert m[pacific]["hidden"] == "true"
    assert page.locator("[data-geo-row]").count() == page.locator("[data-geo-place]").count()
    assert pacific in rows(page)
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
    invariant="глобус — одна точка фокуса с ролью, сводкой и подсказкой; отметки скрыты от читалок",
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
    hidden_marks = page.locator("[data-geo-place]").evaluate_all(
        "es => es.every(e => e.closest('[aria-hidden=\"true\"]') !== null)"
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
    assert marks(page)[w["konigsberg"]]["role"] == "self"
    focus_globe(page)
    page.keyboard.press("Escape")
    settle(page)
    path, q = address(page)
    assert w["kant"] not in path and q.get("sel") is None
    assert q.get("view") == "globe"
    assert all(v["role"] is None and v["dim"] is None for v in marks(page).values())
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
    assert page.locator("[data-geo-place]").count() == 0
    assert len(held) == 1
    with page.expect_response(PLACES_API) as info:
        held[0].continue_()
    globe_ready(page)
    expect(page.locator(".geo-state--loading")).to_have_count(0)
    assert globe(page).get_attribute("aria-busy") == "false"
    assert w["konigsberg"] in marks(page)
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
    assert page.locator("[data-geo-place]").count() == 0
    stage.get_by_role("button", name="К ближайшему году").click()
    expect(globe(page)).to_have_attribute("data-year", "1724")
    assert k in marks(page)
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
    assert w["konigsberg"] in marks(page)
    assert len(events.of(GEO_BUILT)) == 1
    geo_built(events, info.value)
    errors(page)
