"""Глобус: вид, вращение и масштаб, год и проигрывание (geo-timeline, задача 7.4–7.5).

Требования «Вид „Глобус“ на карте раздела», «Вращение и масштаб глобуса», «Год
и проигрывание» дельты ``openspec/specs/geo-timeline/spec.md``.
Настоящий сервис знаний (``knowledge_stack``), данные задаёт каждый тест, время — ``page.clock``.
Клиент событий журнала не пишет: серверный якорь — ``knowledge.geo.built`` по ``request_id``.
"""

# ruff: noqa: E501 — встроенные скрипты страницы и имена инвариантов спецификации

from __future__ import annotations

import math
import re

import pytest
from playwright.sync_api import expect

from philograph.knowledge.statements import Attribution

from .geo_helpers import (
    GEO_BUILT,
    MAP_API,
    PLACES_API,
    SIZES,
    Geo,
    address,
    center,
    errors,
    fmt,
    focus_globe,
    geo_built,
    globe,
    globe_ready,
    open_globe,
    persons,
    play_button,
    plural,
    press,
    project,
    rows,
    scene,
    settle,
    summary_counts,
    year,
    zoom,
)

req = pytest.mark.req
GEO = "geo-timeline"
VIEW = "Вид «Глобус» на карте раздела"
ROT = "Вращение и масштаб глобуса"
YEAR = "Год и проигрывание"
WD_COMMON = [Attribution("common")]
expect.set_options(timeout=15000)


def kant_world(world) -> dict[str, str]:
    g = Geo(world)
    ids = {
        "kant": world.person("Иммануил Кант", "1724", "1804"),
        "hume": world.person("Дэвид Юм", "1711", "1776"),
        "wolff": world.person("Христиан Вольф", "1679", "1754"),
        "rationalism": world.thing("group", "Рационализм"),
        "empiricism": world.thing("group", "Эмпиризм"),
    }
    world.statements.add(
        ids["rationalism"], "group_kind", value="direction", attributions=WD_COMMON
    )
    world.statements.add(ids["empiricism"], "group_kind", value="direction", attributions=WD_COMMON)
    world.relate(ids["kant"], "member_of", ids["rationalism"])
    world.relate(ids["wolff"], "member_of", ids["rationalism"])
    world.relate(ids["hume"], "member_of", ids["empiricism"])
    ids["konigsberg"] = g.place("Кёнигсберг", 54.71, 20.51)
    ids["edinburgh"] = g.place("Эдинбург", 55.95, -3.19)
    g.lived(ids["kant"], ids["konigsberg"], "birth", "1724")
    g.lived(ids["kant"], ids["konigsberg"], "death", "1804")
    g.lived(ids["hume"], ids["edinburgh"])
    world.relate(ids["kant"], "influenced_by", ids["hume"])
    world.relate(ids["kant"], "influenced_by", ids["wolff"])
    return ids


def switch(page, view: str) -> None:
    name = {"globe": "Глобус", "chrono": "Хронология"}[view]
    page.locator(".map-view-switch").get_by_role("button", name=name).click()


def selection_in_address(page, entity: str) -> bool:
    path, query = address(page)
    return path.rstrip("/") == f"/graph/{entity}" and "sel" not in query


# --- Вид «Глобус» ----------------------------------------------------------------------


@req(GEO, VIEW, scenario="Переключение с выбранным Кантом")
def test_switch_keeps_selection_filters_window(knowledge_context, knowledge_stack, events):
    w = kant_world(knowledge_stack.world)
    context = knowledge_context(1920, 1080)
    page = context.new_page()
    page.set_default_timeout(15000)
    query = f"groups={w['rationalism']}&from=1700&to=1800"
    page.goto(f"{knowledge_stack.url}/graph/{w['kant']}?{query}")
    page.locator(".map-canvas").wait_for()
    settle(page)
    selected = page.locator(".map-selected__name")
    expect(selected).to_contain_text("Иммануил Кант")
    with page.expect_response(lambda r: PLACES_API.match(r.url)) as info:
        switch(page, "globe")
    globe_ready(page)
    _path, q = address(page)
    assert q.get("view") == "globe"
    assert selection_in_address(page, w["kant"]), page.url
    assert q.get("groups") == w["rationalism"]
    assert (q.get("from"), q.get("to")) == ("1700", "1800")
    expect(selected).to_contain_text("Иммануил Кант")
    geo_built(events, info.value)
    # Обратно: адрес без view и t, выбор и фильтры те же; слой не перезапрашивается.
    switch(page, "chrono")
    page.locator(".map-canvas").wait_for()
    settle(page)
    _path, q = address(page)
    assert "view" not in q and "t" not in q
    assert selection_in_address(page, w["kant"])
    assert q.get("groups") == w["rationalism"]
    assert (q.get("from"), q.get("to")) == ("1700", "1800")
    expect(selected).to_contain_text("Иммануил Кант")
    assert len(events.of(GEO_BUILT)) == 1
    errors(page)


@req(GEO, VIEW, scenario="Ссылка на глобус")
def test_link_to_globe(knowledge_context, knowledge_stack, events):
    w = kant_world(knowledge_stack.world)
    page, response = open_globe(
        knowledge_context, knowledge_stack, f"/graph/{w['kant']}?view=globe&t=1781"
    )
    assert year(page) == 1781
    expect(page.locator(".map-selected__name")).to_contain_text("Иммануил Кант")
    assert persons(page)[w["kant"]]["role"] == "self"
    assert page.locator(".map-canvas").count() == 0
    geo_built(events, response)
    errors(page)


@req(GEO, VIEW, scenario="Хронология не грузит глобус")
def test_chronology_does_not_load_globe(knowledge_context, knowledge_stack, events):
    kant_world(knowledge_stack.world)
    context = knowledge_context(1920, 1080)
    page = context.new_page()
    urls: list[str] = []
    bodies: list = []
    page.on("request", lambda r: urls.append(r.url))
    page.on(
        "response",
        lambda r: bodies.append(r) if r.url.endswith((".js", ".css", ".json")) else None,
    )
    with page.expect_response(lambda r: MAP_API.match(r.url)):
        page.goto(knowledge_stack.url + "/graph")
    page.locator(".map-canvas").wait_for()
    settle(page)
    # Действия на хронологии без переключения вида.
    page.locator(".map-search input").fill("Кант")
    page.keyboard.press("Escape")
    settle(page)
    assert not [u for u in urls if PLACES_API.match(u)]
    assert not [u for u in urls if "GlobeView" in u]
    assert not [u for u in urls if re.search(r"land|world-atlas|topojson|110m|countries", u)]
    # Словарь названий стран не в основном бандле: ни одна загруженная строка не содержит
    # названий из countries.ru.json.
    for r in bodies:
        text = r.body().decode("utf-8", "replace")
        assert "Буркина-Фасо" not in text and "Папуа-Новая Гвинея" not in text, r.url
    assert [r for r in bodies if r.url.endswith(".js")]
    events.assert_none(GEO_BUILT)
    # Тот же контекст: при переключении фрагмент и слой загружаются — значит, ловушка видит их.
    with page.expect_response(lambda r: PLACES_API.match(r.url)):
        switch(page, "globe")
    globe_ready(page)
    assert [u for u in urls if "GlobeView" in u]
    assert len(events.of(GEO_BUILT)) == 1
    errors(page)


@req(GEO, VIEW, invariant="линзы хронологии в виде «Глобус» скрыты")
def test_lenses_hidden_on_globe(knowledge_context, knowledge_stack, events):
    w = kant_world(knowledge_stack.world)
    page, response = open_globe(
        knowledge_context, knowledge_stack, f"/graph/{w['kant']}?view=globe"
    )
    lenses = page.locator(".map-lens, .map-canvas, [data-lens]")
    assert lenses.evaluate_all("es => es.filter(e => e.offsetParent !== null).length") == 0
    geo_built(events, response)
    switch(page, "chrono")
    page.locator(".map-canvas").wait_for()
    assert page.locator(".map-canvas").is_visible()


# --- Вращение и масштаб ----------------------------------------------------------------


def prague_world(world) -> dict[str, str]:
    g = Geo(world)
    ids = {"p": world.person("Ян Коменский", "1592", "1670")}
    ids["place"] = g.place("Точка", 50, 15)
    g.lived(ids["p"], ids["place"])
    return ids


@req(GEO, ROT, scenario="Исходный вид детерминирован")
@pytest.mark.parametrize(("width", "height"), SIZES)
def test_initial_view_deterministic(knowledge_context, knowledge_stack, events, width, height):
    w = kant_world(knowledge_stack.world)
    path = "/graph?view=globe&t=1760&from=1700&to=1800"
    seen = []
    for _ in range(2):
        page, response = open_globe(
            knowledge_context, knowledge_stack, path, width=width, height=height
        )
        sc = scene(page)
        seen.append(
            (sc["center"], sc["zoom"], sorted((p["id"], p["x"], p["y"]) for p in sc["persons"]))
        )
        geo_built(events, response)
        page.context.close()
    assert seen[0] == seen[1]
    assert {p[0] for p in seen[0][2]} == {w["kant"], w["hume"]}
    assert seen[0][1] in SERIES


def series_zoom(z: float, k: int) -> float:
    """Значение ряда 1,25^k после ``k`` шагов от ``z`` (ряд исходного вида), в пределах 1–8."""
    n = round(math.log(z) / math.log(1.25))
    return round(min(8.0, max(1.0, 1.25 ** (n + k))), 2)


SERIES = [round(1.25**k, 2) for k in range(7)]  # 1 … 3.81; 4.77 > HOME_MAX_ZOOM


HOME_SETS = {
    "athens-rome": [("Афины", 37.98, 23.73), ("Рим", 41.90, 12.50)],
    "edinburgh-alexandria": [("Эдинбург", 55.95, -3.19), ("Александрия", 31.20, 29.92)],
    "london-boston": [("Лондон", 51.51, -0.13), ("Бостон", 42.36, -71.06)],
}


def centroid(points: list[tuple[float, float]]) -> tuple[float, float]:
    """Сферический центр масс (lat, lon) — независимо от кода продукта."""
    xs = ys = zs = 0.0
    for lat, lon in points:
        la, lo = math.radians(lat), math.radians(lon)
        xs += math.cos(la) * math.cos(lo)
        ys += math.cos(la) * math.sin(lo)
        zs += math.sin(la)
    lon = math.degrees(math.atan2(ys, xs))
    lat = math.degrees(math.atan2(zs, math.hypot(xs, ys)))
    return lat, lon


def fits(sc: dict, points, zoom_value: float) -> bool:
    k = zoom_value / sc["zoom"]
    view = {**sc, "R": sc["R"] * k}
    for lat, lon in points:
        x, y, cosc = project(lon, lat, view)
        if cosc < 0 or not (26 <= x <= sc["w"] - 26 and 26 <= y <= sc["h"] - 26):
            return False
    return True


@req(GEO, ROT, scenario="Исходное приближение")
@req(
    GEO,
    ROT,
    invariant="исходный вид — сферический центр масс мест года и наибольшее приближение ряда 1,25^k ≤ 4, при котором места в кадре с полем MEDAL",
)
@pytest.mark.parametrize("key", list(HOME_SETS))
def test_home_zoom(knowledge_context, knowledge_stack, events, key):
    world = knowledge_stack.world
    g = Geo(world)
    pts = []
    for i, (name, lat, lon) in enumerate(HOME_SETS[key]):
        g.lived(world.person(f"Житель {i}", "1700", "1780"), g.place(name, lat, lon))
        pts.append((lat, lon))
    page, response = open_globe(
        knowledge_context, knowledge_stack, "/graph?view=globe&t=1750", width=1366, height=768
    )
    sc = scene(page)
    z = sc["zoom"]
    assert z in SERIES and z <= 4, z
    lat, lon = centroid(pts)
    assert sc["center"] == f"{fmt(lon)},{fmt(lat)}", (sc["center"], lon, lat)
    if fits(sc, pts, 1.0):
        assert fits(sc, pts, z)
        nxt = round(z * 1.25, 2)
        assert nxt > 4 or not fits(sc, pts, z * 1.25), (z, nxt)
    else:
        assert z == 1
    assert z >= 1
    geo_built(events, response)


@req(GEO, ROT, scenario="Клавиши")
def test_keys_rotate_zoom_reset(knowledge_context, knowledge_stack, events):
    prague_world(knowledge_stack.world)
    page, response = open_globe(knowledge_context, knowledge_stack, "/graph?view=globe")
    z0 = float(zoom(page))
    assert center(page) == "15,50" and z0 in SERIES, (center(page), z0)
    focus_globe(page)
    press(page, "ArrowRight", 3)
    press(page, "ArrowUp", 5)
    assert center(page) == "45,80"
    press(page, "+", 2)
    assert float(zoom(page)) == series_zoom(z0, 2)
    press(page, "0")
    assert (center(page), float(zoom(page))) == ("15,50", z0)
    geo_built(events, response)
    errors(page)


@req(GEO, ROT, invariant="шаг стрелок 10°, с Shift 30°, широта в −80…80, приближение 1–8")
def test_key_steps_and_bounds(knowledge_context, knowledge_stack, events):
    prague_world(knowledge_stack.world)
    page, response = open_globe(knowledge_context, knowledge_stack, "/graph?view=globe")
    focus_globe(page)
    press(page, "-", 12)
    assert zoom(page) == "1"
    press(page, "ArrowLeft")
    assert center(page) == "5,50"
    press(page, "Shift+ArrowLeft")
    assert center(page) == "-25,50"
    press(page, "ArrowDown", 2)
    assert center(page) == "-25,30"
    press(page, "Shift+ArrowDown", 5)
    assert center(page) == "-25,-80"
    press(page, "Shift+ArrowRight")
    assert center(page) == "5,-80"
    press(page, "-")
    assert zoom(page) == "1"
    press(page, "+", 30)
    assert zoom(page) == "8"
    press(page, "-")
    assert zoom(page) == "6.4"
    geo_built(events, response)


@req(GEO, ROT, invariant="колесо меняет приближение в 1,25 раза за шаг")
def test_wheel_zoom(knowledge_context, knowledge_stack, events):
    prague_world(knowledge_stack.world)
    page, response = open_globe(knowledge_context, knowledge_stack, "/graph?view=globe")
    focus_globe(page)
    press(page, "-", 12)
    expect(globe(page)).to_have_attribute("data-zoom", "1")
    box = globe(page).bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.wheel(0, -100)
    expect(globe(page)).to_have_attribute("data-zoom", "1.25")
    page.mouse.wheel(0, 100)
    expect(globe(page)).to_have_attribute("data-zoom", "1")
    geo_built(events, response)


@req(GEO, ROT, invariant="вращение перетаскиванием")
def test_drag_rotates(knowledge_context, knowledge_stack, events):
    prague_world(knowledge_stack.world)
    page, response = open_globe(
        knowledge_context, knowledge_stack, "/graph?view=globe", reduced_motion="reduce"
    )
    box = globe(page).bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 120, y, steps=6)
    page.mouse.up()
    settle(page)
    lon = float(center(page).split(",")[0])
    assert lon < 15  # тянем вправо — центр уходит к западу
    geo_built(events, response)


def far_world(world) -> dict[str, str]:
    g = Geo(world)
    ids = kant_world(world)
    ids["cook"] = world.person("Джеймс Кук", "1728", "1779")
    ids["pacific"] = g.place("Тихий океан", 0, -160)
    g.lived(ids["cook"], ids["pacific"])
    ids["edge"] = world.person("Край", "1700", "1790")
    ids["edge_in"] = g.place("Ровно 90°", 0, -70)
    g.lived(ids["edge"], ids["edge_in"])
    ids["over"] = world.person("За краем", "1700", "1790")
    ids["over_in"] = g.place("Чуть дальше 90°", 0, -69.99)
    g.lived(ids["over"], ids["over_in"])
    return ids


@req(GEO, ROT, scenario="Дальнее полушарие")
def test_far_hemisphere_hidden(knowledge_context, knowledge_stack, events):
    w = far_world(knowledge_stack.world)
    page, response = open_globe(knowledge_context, knowledge_stack, "/graph?view=globe&t=1760")
    page.locator(f"[data-geo-row='{w['pacific']}'] .geo-row__place").click()
    expect(globe(page)).to_have_attribute("data-center", "-160,0")
    settle(page)
    m = persons(page)
    assert m[w["kant"]]["hidden"] == "true" and m[w["kant"]]["children"] == 0
    assert w["konigsberg"] in rows(page)
    assert rows(page)[w["konigsberg"]]["label"].startswith("Кёнигсберг")
    assert m[w["cook"]]["hidden"] == "false"
    geo_built(events, response)


@req(
    GEO,
    ROT,
    invariant="медальон с точкой привязки дальше 90° от центра скрыт и не рисуется, ровно 90° — не скрыт; связь со скрытым концом не рисуется",
)
def test_hidden_boundary_90(knowledge_context, knowledge_stack, events):
    w = far_world(knowledge_stack.world)
    link = knowledge_stack.world.relate(w["edge"], "influenced_by", w["over"])
    page, response = open_globe(knowledge_context, knowledge_stack, "/graph?view=globe&t=1760")
    page.locator(f"[data-geo-row='{w['pacific']}'] .geo-row__place").click()
    expect(globe(page)).to_have_attribute("data-center", "-160,0")
    settle(page)
    sc = scene(page)
    m = {p["id"]: p for p in sc["persons"]}
    assert project(-70, 0, sc)[2] == pytest.approx(0, abs=1e-9)
    assert project(-69.99, 0, sc)[2] < 0
    assert m[w["edge"]]["hidden"] == "false"
    assert m[w["over"]]["hidden"] == "true"
    # Скрытый медальон не рисуется, его связь — без пути.
    assert m[w["over"]]["children"] == 0
    hidden = page.locator(f"[data-geo-person='{w['over']}']")
    assert hidden.evaluate("e => e.getBoundingClientRect().width === 0")
    [lk] = [x for x in sc["links"] if x["id"] == link]
    assert lk["hidden"] == "true" and lk["d"] is None
    assert {w["edge_in"], w["over_in"]} <= set(rows(page))
    geo_built(events, response)


# --- Год и проигрывание ----------------------------------------------------------------


def busy_world(world) -> dict[str, str]:
    """Больше всего живых (3) в 1711–1716; эпоха «Просвещение» 1680–1800."""
    g = Geo(world)
    ids = {
        "a": world.person("Персона А", "1650", "1716"),
        "b": world.person("Персона Б", "1700", "1760"),
        "hume": world.person("Дэвид Юм", "1711", "1776"),
        "enl": world.thing("epoch", "Просвещение", "1680–1800"),
    }
    ids["paris"] = g.place("Париж", 48.86, 2.35)
    for key in ("a", "b", "hume"):
        g.lived(ids[key], ids["paris"])
    return ids


def install_clock(page) -> None:
    page.clock.install()


@req(GEO, YEAR, scenario="Без автозапуска")
def test_no_autoplay(knowledge_context, knowledge_stack, events):
    busy_world(knowledge_stack.world)
    page, response = open_globe(
        knowledge_context, knowledge_stack, "/graph?view=globe", before=install_clock
    )
    page.clock.run_for(5000)
    expect(play_button(page)).to_have_text("Играть")
    assert year(page) == 1711
    expect(page.locator(".geo-yearbar__year")).to_have_text("1711 · Просвещение")
    assert "t" not in address(page)[1]
    geo_built(events, response)
    errors(page)


@req(GEO, YEAR, scenario="Шаг клавишей")
def test_page_up_step_and_announce(knowledge_context, knowledge_stack, events):
    w = kant_world(knowledge_stack.world)
    page, response = open_globe(
        knowledge_context, knowledge_stack, f"/graph/{w['kant']}?view=globe&t=1781"
    )
    focus_globe(page)
    page.keyboard.press("PageUp")
    expect(globe(page)).to_have_attribute("data-year", "1791")
    assert address(page)[1].get("t") == "1791"
    n, m = summary_counts(page)
    text = f"1791 год: {n} {plural(n, ('место', 'места', 'мест'))}, {m} {plural(m, ('человек', 'человека', 'человек'))}"
    expect(page.locator("[data-geo-live]")).to_have_text(text)
    assert (n, m) == (2, 2)  # Кёнигсберг (Кант), Эдинбург (Юм бледнеет, но виден 150 лет)
    geo_built(events, response)


@req(GEO, YEAR, scenario="Год вне окна")
def test_year_outside_window(knowledge_context, knowledge_stack, events):
    busy_world(knowledge_stack.world)
    page, response = open_globe(
        knowledge_context, knowledge_stack, "/graph?view=globe&from=1700&to=1800&t=1900"
    )
    assert year(page) == 1800
    geo_built(events, response)
    page.context.close()
    page, response = open_globe(
        knowledge_context, knowledge_stack, "/graph?view=globe&from=1700&to=1800&t=abc"
    )
    assert year(page) == 1711  # по умолчанию: больше всего живых, раньше при равенстве
    geo_built(events, response)


@req(GEO, YEAR, invariant="год всегда в окне")
@pytest.mark.parametrize(
    ("t", "expected"),
    [
        ("1699", 1700),
        ("1700", 1700),
        ("1750", 1750),
        ("1800", 1800),
        ("1801", 1800),
        ("-5000", 1700),
        ("1750.5", 1711),
        ("1e3", 1711),
        ("", 1711),
    ],
)
def test_year_always_in_window(knowledge_context, knowledge_stack, events, t, expected):
    busy_world(knowledge_stack.world)
    page, response = open_globe(
        knowledge_context, knowledge_stack, f"/graph?view=globe&from=1700&to=1800&t={t}"
    )
    assert year(page) == expected
    focus_globe(page)
    press(page, "PageUp", 12)
    assert year(page) == 1800
    press(page, "PageDown", 12)
    assert year(page) == 1700
    press(page, "[")
    assert year(page) == 1700
    geo_built(events, response)


@req(GEO, YEAR, invariant="клавиши шкалы: PageUp/PageDown ±10, [ ] ±1, Home/End — края окна")
def test_year_keys(knowledge_context, knowledge_stack, events):
    busy_world(knowledge_stack.world)
    page, response = open_globe(
        knowledge_context, knowledge_stack, "/graph?view=globe&from=1700&to=1800&t=1750"
    )
    focus_globe(page)
    for key, value in (("]", 1751), ("[", 1750), ("PageDown", 1740), ("PageUp", 1750)):
        press(page, key)
        assert year(page) == value, key
    slider = page.locator("[role='slider'][data-year]")
    slider.focus()
    press(page, "End")
    assert year(page) == 1800
    press(page, "Home")
    assert year(page) == 1700
    assert slider.get_attribute("aria-valuenow") == "1700"
    geo_built(events, response)


@req(GEO, YEAR, invariant="год выбирается щелчком по шкале")
def test_click_on_scale(knowledge_context, knowledge_stack, events):
    busy_world(knowledge_stack.world)
    page, response = open_globe(
        knowledge_context, knowledge_stack, "/graph?view=globe&from=1700&to=1800&t=1700"
    )
    dot = page.locator("[role='slider'][data-year]").bounding_box()
    tick = page.locator(".map-overview__year", has_text=re.compile("^1775$")).bounding_box()
    page.mouse.click(tick["x"] + tick["width"] / 2, dot["y"] + dot["height"] / 2)
    settle(page)
    assert abs(year(page) - 1775) <= 1, year(page)
    assert address(page)[1].get("t") == str(year(page))
    geo_built(events, response)


def eras_world(world) -> dict[str, str]:
    ids = busy_world(world)
    ids["sci"] = world.thing("epoch", "Научная революция", "1543–1687")
    ids["late"] = world.thing("epoch", "Барокко поздн.", "1680–1750")
    return ids


@req(
    GEO,
    YEAR,
    invariant="эпоха года — с более поздним началом, затем по названию; без эпохи — только год",
)
def test_year_label_era(knowledge_context, knowledge_stack, events):
    eras_world(knowledge_stack.world)
    page, response = open_globe(
        knowledge_context, knowledge_stack, "/graph?view=globe&from=1600&to=1900&t=1685"
    )
    label = page.locator(".geo-yearbar__year")
    # 1685: «Научная революция» (1543) и два пролёта с началом 1680 — позднее начало, по названию.
    expect(label).to_have_text("1685 · Барокко поздн.")
    focus_globe(page)
    press(page, "PageUp", 7)  # 1755: только «Просвещение»
    expect(label).to_have_text("1755 · Просвещение")
    press(page, "PageUp", 6)  # 1815: без эпохи
    expect(label).to_have_text("1815")
    press(page, "PageDown", 20)  # 1615: «Научная революция»
    expect(label).to_have_text("1615 · Научная революция")
    geo_built(events, response)


@req(GEO, YEAR, invariant="год по умолчанию — середина жизни выбранной персоны")
def test_default_year_mid_life(knowledge_context, knowledge_stack, events):
    w = kant_world(knowledge_stack.world)
    page, response = open_globe(
        knowledge_context, knowledge_stack, f"/graph/{w['kant']}?view=globe"
    )
    assert year(page) == 1764  # (1724 + 1804) / 2
    geo_built(events, response)
    page.context.close()
    page, response = open_globe(
        knowledge_context, knowledge_stack, f"/graph/{w['hume']}?view=globe"
    )
    assert year(page) == 1743  # floor((1711 + 1776) / 2)
    geo_built(events, response)


@req(GEO, YEAR, invariant="год по умолчанию: больше всего живых, при равенстве — более ранний")
def test_default_year_tie_earlier(knowledge_context, knowledge_stack, events):
    g = Geo(knowledge_stack.world)
    w = knowledge_stack.world
    a, b = w.person("Первый", "1600", "1640"), w.person("Второй", "1700", "1740")
    p = g.place("Место", 10, 10)
    g.lived(a, p)
    g.lived(b, p)
    page, response = open_globe(knowledge_context, knowledge_stack, "/graph?view=globe")
    assert year(page) == 1600
    geo_built(events, response)


def window_clock(page) -> None:
    page.clock.install()


def start_play(page, speed: str | None = None) -> None:
    if speed:
        page.locator(".geo-yearbar__speed").get_by_role("button", name=speed).click()
    play_button(page).click()
    expect(play_button(page)).to_have_text("Пауза")


@req(GEO, YEAR, scenario="Проигрывание в окне")
def test_playback_in_window(knowledge_context, knowledge_stack, events):
    busy_world(knowledge_stack.world)
    page, response = open_globe(
        knowledge_context,
        knowledge_stack,
        "/graph?view=globe&from=1700&to=1800&t=1700",
        before=window_clock,
    )
    start_play(page, "×2")
    page.clock.run_for(15000)
    expect(globe(page)).to_have_attribute("data-year", "1750")
    page.clock.run_for(15000)
    expect(globe(page)).to_have_attribute("data-year", "1800")
    expect(play_button(page)).to_have_text("Играть")
    page.clock.run_for(2000)
    assert year(page) == 1800
    play_button(page).click()
    expect(globe(page)).to_have_attribute("data-year", "1700")
    geo_built(events, response)
    errors(page)


@req(GEO, YEAR, invariant="окно за 60 с на ×1, за 120 с на ×0,5, за 30 с на ×2")
@pytest.mark.parametrize(("speed", "half"), [("×0,5", 60000), ("×1", 30000), ("×2", 15000)])
def test_playback_speeds(knowledge_context, knowledge_stack, events, speed, half):
    busy_world(knowledge_stack.world)
    page, response = open_globe(
        knowledge_context,
        knowledge_stack,
        "/graph?view=globe&from=1700&to=1800&t=1700",
        before=window_clock,
    )
    start_play(page, speed)
    page.clock.run_for(half)
    expect(globe(page)).to_have_attribute("data-year", "1750")
    page.clock.run_for(half)
    expect(globe(page)).to_have_attribute("data-year", "1800")
    expect(play_button(page)).to_have_text("Играть")
    geo_built(events, response)


@req(GEO, YEAR, invariant="проигрывание запускается и останавливается кнопкой или пробелом")
def test_space_toggles_playback(knowledge_context, knowledge_stack, events):
    busy_world(knowledge_stack.world)
    page, response = open_globe(
        knowledge_context,
        knowledge_stack,
        "/graph?view=globe&from=1700&to=1800&t=1700",
        before=window_clock,
    )
    focus_globe(page)
    page.keyboard.press(" ")
    expect(play_button(page)).to_have_text("Пауза")
    page.clock.run_for(6000)
    page.keyboard.press(" ")
    expect(play_button(page)).to_have_text("Играть")
    stopped = year(page)
    assert 1700 < stopped < 1800
    page.clock.run_for(10000)
    assert year(page) == stopped
    geo_built(events, response)


def hide_tab(page, hidden: bool) -> None:
    page.evaluate(
        """h => {
            Object.defineProperty(document, 'visibilityState', {configurable: true, get: () => h ? 'hidden' : 'visible'});
            Object.defineProperty(document, 'hidden', {configurable: true, get: () => h});
            document.dispatchEvent(new Event('visibilitychange'));
        }""",
        hidden,
    )


@req(GEO, YEAR, scenario="Скрытая вкладка")
def test_hidden_tab_pauses(knowledge_context, knowledge_stack, events):
    busy_world(knowledge_stack.world)
    page, response = open_globe(
        knowledge_context,
        knowledge_stack,
        "/graph?view=globe&from=1700&to=1800&t=1700",
        before=window_clock,
    )
    start_play(page)
    page.clock.run_for(6000)
    hide_tab(page, True)
    expect(play_button(page)).to_have_text("Играть")
    at = year(page)
    page.clock.run_for(10000)
    hide_tab(page, False)
    page.clock.run_for(5000)
    expect(play_button(page)).to_have_text("Играть")
    assert year(page) == at
    geo_built(events, response)
