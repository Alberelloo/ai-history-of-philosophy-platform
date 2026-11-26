"""Глобус: медальоны философов и место персоны по нажатию (rework-globe-political-map, 5.3–5.4).

Требования «Медальоны философов» и «Место персоны по нажатию» дельты
``openspec/changes/archive/2026-11-26-rework-globe-political-map/specs/geo-timeline/spec.md``.
Настоящий сервис знаний (``knowledge_stack``); ``page.route`` — только там, где сервер такие
данные не отдаёт: 51 360 персон («Предел медальонов») и ответ ``/map`` без ``short``.
Центры кругов — по прямоугольнику элемента, проекция мест — формулой теста (``project``).
Клиент событий журнала не пишет: серверный якорь — ``knowledge.geo.built`` по ``request_id``.
"""

# ruff: noqa: E501 — встроенные скрипты страницы и имена инвариантов спецификации

from __future__ import annotations

import math
import re
import struct
import subprocess
import zlib
from pathlib import Path

import pytest
from playwright.sync_api import expect

from philograph.knowledge.statements import Attribution

from .geo_helpers import (
    CITIES,
    GEO_BUILT,
    MAP_API,
    MAX_PERSONS,
    MAX_SHIFT,
    MEDAL,
    PLACES_API,
    SIZES,
    SOURCED,
    Geo,
    center_on,
    collisions,
    crowd,
    drag_frames,
    drawn,
    errors,
    focus_globe,
    geo_built,
    globe,
    globe_ready,
    open_globe,
    open_globe_map,
    outside,
    play_button,
    press,
    project,
    scene,
    settle,
    shapes,
    synthetic,
    where_block,
)

WEB = Path(__file__).resolve().parents[2] / "web"
req = pytest.mark.req
GEO = "geo-timeline"
MED = "Медальоны философов"
WHERE = "Место персоны по нажатию"
COMMON = [Attribution("common")]
XSS_IMG = '<img src=x onerror="window.__xss=1">'
XSS_IMG_NOSPACE = "<img/src=x/onerror=window.__xss=1>"
XSS_B = '<b onmouseover="window.__xss=1">Афины</b>'
expect.set_options(timeout=20000)


def fuzzy(a: int, b: int | None = None) -> dict:
    b = a if b is None else b
    return {
        "earliest_start": a,
        "latest_start": a,
        "earliest_end": b,
        "latest_end": b,
        "precision": "year",
        "original": f"{a}–{b}",
    }


def ancient(world, name: str, born: int, died: int) -> str:
    """Персона с годами жизни как целыми годами шкалы (−427 — «427 до н. э.» на шкале)."""
    entity = world.entities.create("person", [("ru", name, "primary")])
    world.statements.add(entity, "lifespan", value=fuzzy(born, died), attributions=COMMON)
    return entity


def lived_years(g: Geo, who: str, where: str, role: str | None, a: int | None, b: int | None):
    qualifiers = {}
    if role:
        qualifiers["place_role"] = role
    if a is not None:
        qualifiers["time"] = fuzzy(a, b)
    return g.statements.add(who, "lived_in", obj=where, qualifiers=qualifiers, **SOURCED)


def athens_world(world) -> dict[str, str]:
    g = Geo(world)
    ids = {
        "plato": ancient(world, "Платон", -427, -347),
        "aristotle": ancient(world, "Аристотель", -384, -322),
        "kant": world.person("Иммануил Кант", "1724", "1804"),
        "athens": g.place("Афины", 37.98, 23.73),
        "konigsberg": g.place("Кёнигсберг", 54.71, 20.51),
    }
    lived_years(g, ids["plato"], ids["athens"], "activity", -387, -347)
    lived_years(g, ids["aristotle"], ids["athens"], "activity", -367, -322)
    g.lived(ids["kant"], ids["konigsberg"], "birth", "1724")
    return ids


def png(rgb=(120, 80, 40)) -> bytes:
    raw = b"".join(b"\x00" + bytes(rgb) * 4 for _ in range(4))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 4, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def add_portrait(stack, entity: str) -> tuple[int, str]:
    data = png()
    file_id = stack.portraits.files.put(data)
    pid = stack.portraits.add_draft(
        entity,
        file_id=file_id,
        width=4,
        height=4,
        author=None,
        year=None,
        license="public-domain",
        license_url=None,
        source_url="https://example.org/p",
        origin="test",
        phash=f"ph{entity}",
    )
    stack.portraits.approve(pid, "operator")
    return pid, file_id


def europe(n: int) -> list[tuple[str, float, float]]:
    """``n`` разных мест Европы: города, затем сетка 40–58° с. ш., −5…30° в. д."""
    out = list(CITIES[:n])
    k = 0
    while len(out) < n:
        out.append((f"Точка {k:02d}", 41 + (k % 6) * 3.1, -4 + (k // 6) * 6.3))
        k += 1
    return out


DATASETS = {
    "1x1": (1, 1),
    "2x1": (2, 1),
    "7x1": (7, 1),
    "19x1": (19, 1),
    "40x1": (40, 1),
    "1x40": (1, 40),
}


def dataset(world, key: str) -> dict[str, list[str]]:
    per, places = DATASETS[key]
    return crowd(world, europe(places) if places > 1 else [("Афины", 37.98, 23.73)], per)


def count_faults(
    sc: dict, people: dict[str, list[str]], coords: dict[str, tuple[float, float]]
) -> list:
    """«Число медальонов» и учёт персон в значках (инварианты 5.3 а, в)."""
    bad = []
    expected = {p for ps in people.values() for p in ps}
    got = {p["id"] for p in sc["persons"]}
    if got != expected:
        bad.append(("медальоны не по одному на персону года", len(got), len(expected)))
    names = {n["id"] for n in sc["names"]}
    for p in sc["persons"]:
        if p["hidden"] == "false" and p["packed"] == "false" and p["id"] not in names:
            bad.append(("нарисованный медальон без подписи", p["id"]))
        if p["id"] in names and not drawn(p):
            bad.append(("подпись у ненарисованного медальона", p["id"]))
        if drawn(p) and p["children"] == 0:
            bad.append(("медальон не нарисован", p["id"]))
        if not drawn(p) and p["children"] > 0:
            bad.append(("скрытый или свёрнутый медальон нарисован", p["id"]))
    visible_place = {}
    for place, (lat, lon) in coords.items():
        x, y, cosc = project(lon, lat, sc)
        visible_place[place] = cosc > 1e-9 and 0 <= x <= sc["w"] and 0 <= y <= sc["h"]
    packed = [p for p in sc["persons"] if p["packed"] == "true" and visible_place.get(p["place"])]
    for p in packed:
        holders = [b for b in sc["more"] if p["place"] in b["places"] and b["hidden"] == "false"]
        if len(holders) != 1:
            bad.append(("свёрнутая персона не ровно в одном значке", p["id"], len(holders)))
    total = sum(b["count"] for b in sc["more"] if b["hidden"] == "false")
    if total != len(packed):
        bad.append(("сумма data-count не равна числу свёрнутых", total, len(packed)))
    for b in sc["more"]:
        if b["hidden"] == "false" and b["text"].strip() != f"+{b['count']}":
            bad.append(("текст значка не «+N»", b["text"], b["count"]))
    if sc["places_attr"] or sc.get("anchors_bad"):
        bad.append(("отметки мест [data-geo-place]", sc["places_attr"]))
    return bad


def shift_faults(sc: dict, coords: dict[str, tuple[float, float]]) -> list:
    """Сдвиг нарисованного медальона от проекции места не больше MAX_SHIFT; нет (0, 0)."""
    bad = []
    for p in sc["persons"]:
        if not drawn(p):
            continue
        lat, lon = coords[p["place"]]
        x, y, _ = project(lon, lat, sc)
        d = math.hypot(p["box"]["cx"] - x, p["box"]["cy"] - y)
        if d > MAX_SHIFT + 0.5:
            bad.append(("сдвиг больше MAX_SHIFT", p["id"], round(d, 2)))
        if abs(p["box"]["cx"]) < 0.5 and abs(p["box"]["cy"]) < 0.5:
            bad.append(("медальон в (0, 0)", p["id"]))
    return bad


def coords_of(layer: dict) -> dict[str, tuple[float, float]]:
    return {p["id"]: (p["lat"], p["lon"]) for p in layer["places"]}


def zoom_to(page, steps: int) -> None:
    press(page, "-", 12)
    press(page, "+", steps)
    settle(page)


# --- Медальоны философов: сценарии ------------------------------------------------------


@req(GEO, MED, scenario="Философы на глобусе")
def test_philosophers_on_globe(knowledge_context, knowledge_stack, events):
    w = athens_world(knowledge_stack.world)
    page, response = open_globe(knowledge_context, knowledge_stack, "/graph?view=globe&t=-360")
    sc = scene(page)
    m = {p["id"]: p for p in sc["persons"]}
    assert set(m) == {w["plato"], w["aristotle"]}, set(m)
    assert m[w["plato"]]["place"] == w["athens"] and m[w["aristotle"]]["place"] == w["athens"]
    names = {n["id"]: n["text"] for n in sc["names"]}
    assert names == {w["plato"]: "Платон", w["aristotle"]: "Аристотель"}
    assert page.locator("[data-geo-place]").count() == 0
    assert "Афины" not in globe(page).text_content()
    geo_built(events, response)
    errors(page)


@req(GEO, MED, scenario="Портрет и инициал")
def test_portrait_and_initial(knowledge_context, knowledge_stack, events):
    w = athens_world(knowledge_stack.world)
    _pid, file_id = add_portrait(knowledge_stack, w["plato"])
    page, response, data = open_globe_map(
        knowledge_context, knowledge_stack, "/graph?view=globe&t=-360"
    )
    portrait = {p["id"]: p.get("portrait") for p in data["people"]}
    assert portrait[w["plato"]] and not portrait.get(w["aristotle"])
    m = {p["id"]: p for p in scene(page)["persons"]}
    assert m[w["plato"]]["image"] == portrait[w["plato"]]
    assert m[w["aristotle"]]["image"] is None and m[w["aristotle"]]["mono"] == "А"
    geo_built(events, response)
    errors(page)
    page.context.close()
    # Второй прогон: файл портрета отвечает 404 — инициал «П», без ошибок страницы.
    knowledge_stack.portraits.files.delete(file_id)
    page, response = open_globe(knowledge_context, knowledge_stack, "/graph?view=globe&t=-360")
    plato = page.locator(f"[data-geo-person='{w['plato']}']")
    expect(plato.locator("text")).to_have_text("П")
    assert plato.locator("image").count() == 0
    geo_built(events, response)
    errors(page)


@req(GEO, MED, scenario="Число медальонов")
@req(
    GEO,
    MED,
    invariant="у каждой персоны года ровно один медальон; видимая — нарисована с подписью или учтена ровно в одном значке; сумма data-count равна числу свёрнутых; отметок мест нет",
)
@pytest.mark.parametrize("key", list(DATASETS))
def test_medal_count(knowledge_context, knowledge_stack, events, key):
    people = dataset(knowledge_stack.world, key)
    for width, height in SIZES:
        page, response, _data = open_globe_map(
            knowledge_context,
            knowledge_stack,
            "/graph?view=globe&t=1750",
            width=width,
            height=height,
        )
        layer = response.json()
        coords = coords_of(layer)
        focus_globe(page)
        for steps in (None, 0, 3, 6):  # исходный вид, затем 1; 1,95; 3,81
            if steps is not None:
                zoom_to(page, steps)
            sc = scene(page)
            assert count_faults(sc, people, coords) == [], (
                width,
                steps,
                count_faults(sc, people, coords),
            )
        geo_built(events, response)
        errors(page)
        page.context.close()


def many_places(n_places=320) -> tuple[list[dict], list[tuple[str, str, str]]]:
    places, people = [], []
    for i in range(1, n_places + 1):
        pid = f"g{i:03d}"
        places.append(
            {
                "id": pid,
                "label": f"Место {i}",
                "lat": -60 + (i * 37) % 120,
                "lon": -170 + (i * 53) % 340,
            }
        )
        people.extend((f"x{i:03d}_{j:03d}", f"Человек {i}-{j}", pid) for j in range(i))
    return places, people


@req(GEO, MED, scenario="Предел медальонов")
def test_medal_limit(knowledge_context, knowledge_stack, events):
    knowledge_stack.world.person("Опорный", "1720", "1780")
    context = knowledge_context(1366, 768)
    places, people = many_places()
    assert len(people) == 51360
    data, layer = synthetic(knowledge_stack, context, places, people)
    page = context.new_page()
    page.set_default_timeout(180000)
    page.route(MAP_API, lambda r: r.fulfill(json=data))
    page.route(PLACES_API, lambda r: r.fulfill(json=layer))
    page.goto(knowledge_stack.url + "/graph?view=globe&t=1750")
    page.locator(".geo-globe[aria-busy='false']").wait_for(timeout=240000)
    settle(page)
    sc = scene(page)
    assert len(sc["persons"]) == MAX_PERSONS
    # Порядок мест: по убыванию людей, затем по id; в сцене — первые 300 (места 21…320).
    order = [f"g{i:03d}" for i in range(320, 20, -1)]
    with_medal = {p["place"] for p in sc["persons"]}
    assert set(order) <= with_medal, sorted(set(order) - with_medal)[:5]
    coords = coords_of(layer)
    by_place = {}
    for _pid, _label, place in people:
        by_place[place] = by_place.get(place, 0) + 1
    vis = set()
    for place in order:
        lat, lon = coords[place]
        x, y, cosc = project(lon, lat, sc)
        if cosc > 1e-9 and 0 <= x <= sc["w"] and 0 <= y <= sc["h"]:
            vis.add(place)
    expected = sum(by_place[p] for p in vis)
    got = sum(1 for p in sc["persons"] if drawn(p)) + sum(
        b["count"] for b in sc["more"] if b["hidden"] == "false"
    )
    assert got == expected, (got, expected)
    expect(page.locator("[data-geo-limit='people']")).to_have_text("показаны 600 из 51 150 человек")
    assert len(events.of(GEO_BUILT)) == 1  # ответы подменены: событие — прямого запроса теста


@req(GEO, MED, scenario="Предел медальонов")
def test_medal_limit_layout_budget(knowledge_context, knowledge_stack, events, tmp_path):
    """THEN «раскладка в покое укладывается в бюджет задачи 3.8» — в редакции дельты:
    (1) функции раскладки на этих данных в node — медиана 5 прогонов ≤ 150 мс процессорного
    времени (юнит-тест ``web/unit/geo/budget.test.ts``, его вывод сверяется здесь);
    (2) в браузере одно действие читателя в покое даёт ровно одну полную раскладку.
    Полная раскладка наблюдается снаружи как кадр, в котором меняются подписи (подписи стран
    и персон ставит только полная раскладка; кадры движения их не трогают)."""
    out = WEB / "unit" / "geo" / "budget.test.ts"
    assert out.exists(), "нет юнит-теста бюджета из дельты"
    bundle = tmp_path / "budget.mjs"
    subprocess.run(
        [
            str(WEB / "node_modules" / ".bin" / "esbuild"),
            str(out),
            "--bundle",
            "--platform=node",
            "--format=esm",
            f"--outfile={bundle}",
            "--log-level=error",
        ],
        cwd=WEB,
        check=True,
    )
    run = subprocess.run(
        ["node", str(bundle)], cwd=WEB, capture_output=True, text=True, timeout=300
    )
    print("budget.test.ts:", run.stdout.strip()[-400:])
    assert run.returncode == 0 and "failed 0" in run.stdout, run.stdout + run.stderr

    knowledge_stack.world.person("Опорный", "1720", "1780")
    context = knowledge_context(1366, 768, reduced_motion="reduce")
    places, people = many_places()
    data, layer = synthetic(knowledge_stack, context, places, people)
    page = context.new_page()
    page.set_default_timeout(180000)
    page.route(MAP_API, lambda r: r.fulfill(json=data))
    page.route(PLACES_API, lambda r: r.fulfill(json=layer))
    page.goto(knowledge_stack.url + "/graph?view=globe&t=1750")
    page.locator(".geo-globe[aria-busy='false']").wait_for(timeout=240000)
    settle(page)
    page.evaluate(LAYOUT_WATCH_JS)
    focus_globe(page)
    counts = []
    # Смена года (PageUp) на этих данных сцену не меняет (у всех одни годы), и полная
    # раскладка даёт тот же DOM — снаружи её не увидеть; поэтому три поворота.
    for key in ("ArrowRight", "ArrowDown", "ArrowLeft"):
        page.evaluate("() => { window.__layoutTicks = new Set(); }")
        before = (globe(page).get_attribute("data-center"), globe(page).get_attribute("data-year"))
        page.keyboard.press(key)
        page.wait_for_function(
            "b => { const g = document.querySelector('.geo-globe');"
            " return g.dataset.center !== b[0] || g.dataset.year !== b[1]; }",
            arg=list(before),
        )
        settle(page)
        page.wait_for_timeout(300)  # не доказательство отсутствия: число уже снято после покоя
        counts.append(page.evaluate("() => window.__layoutTicks.size"))
    print("полных раскладок на действие:", counts)
    assert counts == [1, 1, 1], counts
    assert len(events.of(GEO_BUILT)) == 1


LAYOUT_WATCH_JS = """
() => {
  let tick = 0;
  const loop = () => { tick += 1; requestAnimationFrame(loop); };
  requestAnimationFrame(loop);
  window.__layoutTicks = new Set();
  const label = n => n && n.nodeType === 1 && n.matches && n.matches('[data-geo-country],[data-geo-name]');
  const inside = n => { for (let x = n; x; x = x.parentNode) if (label(x)) return true; return false; };
  new MutationObserver(list => {
    for (const m of list) {
      const nodes = [...m.addedNodes, ...m.removedNodes];
      if (inside(m.target) || nodes.some(n => label(n) || (n.querySelector && n.querySelector('[data-geo-country],[data-geo-name]')))) {
        window.__layoutTicks.add(tick);
      }
    }
  }).observe(document.querySelector('.geo-globe'), {subtree: true, childList: true, attributes: true, characterData: true});
}
"""


@req(GEO, MED, scenario="Без наложений")
@req(
    GEO,
    MED,
    invariant="нарисованные медальоны, значки и подписи персон попарно не пересекаются по геометрии пересечений, лежат в кадре, центры — в круге",
)
@pytest.mark.parametrize("key", list(DATASETS))
def test_no_overlaps(knowledge_context, knowledge_stack, events, key):
    people = dataset(knowledge_stack.world, key)
    frames = 0
    for width, height in SIZES:
        page, response = open_globe(
            knowledge_context,
            knowledge_stack,
            "/graph?view=globe&t=1750",
            width=width,
            height=height,
            reduced_motion="reduce",
        )
        coords = coords_of(response.json())
        focus_globe(page)
        press(page, "-", 12)
        steps = ["+"] * 10 + [
            "ArrowRight",
            "ArrowUp",
            "ArrowLeft",
            "ArrowLeft",
            "ArrowDown",
            "ArrowDown",
        ]
        for key_ in [None, *steps]:
            if key_:
                press(page, key_)
                settle(page)
            sc = scene(page)
            items = [s for s in shapes(sc, countries=False)]
            assert collisions(items) == [], (width, sc["zoom"], sc["center"], collisions(items)[:3])
            assert outside(sc, items) == [], (width, sc["zoom"], outside(sc, items)[:3])
            for p in sc["persons"]:  # центр по прямоугольнику = data-x/data-y
                if drawn(p):
                    assert (
                        abs(p["box"]["cx"] - p["x"]) <= 0.05
                        and abs(p["box"]["cy"] - p["y"]) <= 0.05
                    ), p
            assert shift_faults(sc, coords) == []
            frames += 1
        assert sc["zoom"] == 8
        geo_built(events, response)
        page.context.close()
    assert frames == 3 * 17
    assert people


def rim_world(world) -> dict:
    """19 персон в одном месте (сдвинутые медальоны), опорное место в 80° к западу
    и связь от опорной персоны к каждой из 19."""
    g = Geo(world)
    rim = g.place("У обода", 50.0, 60.0)
    base = g.place("Опора", 50.0, -20.0)
    anchor = world.person("Опорный учитель", "1700", "1780")
    g.lived(anchor, base)
    people = []
    for i in range(19):
        p = world.person(f"Ученик {i:02d}", "1700", "1780")
        g.lived(p, rim)
        world.relate(p, "influenced_by", anchor)
        people.append(p)
    return {"rim": rim, "base": base, "people": people}


@req(GEO, MED, scenario="У обода при перетаскивании")
@pytest.mark.parametrize(("width", "height"), SIZES)
def test_rim_while_dragging(knowledge_context, knowledge_stack, events, width, height):
    w = rim_world(knowledge_stack.world)
    page, response = open_globe(
        knowledge_context,
        knowledge_stack,
        "/graph?view=globe&t=1750",
        width=width,
        height=height,
        reduced_motion="reduce",
    )
    center_on(page, w["base"], (-20, 50))
    focus_globe(page)
    zoom_to(page, 0)
    sc0 = scene(page)
    shifted = [
        p
        for p in sc0["persons"]
        if drawn(p)
        and math.hypot(
            p["box"]["cx"] - project(60, 50, sc0)[0], p["box"]["cy"] - project(60, 50, sc0)[1]
        )
        > MEDAL / 2
    ]
    assert shifted, "нет медальонов, сдвинутых от точки привязки"
    # Тянем вправо на ~26°: центр уходит на запад, место (80° от центра) — за край полушария.
    went_hidden = set()
    shots = drag_frames(
        page, sc0["R"] * 0.45, 0, frames=5, start=(sc0["cx"] - sc0["R"] * 0.5, sc0["cy"])
    )
    assert len(shots) == 5
    for sc in shots:
        items = [s for s in shapes(sc, countries=False) if s[0] in ("medal", "more", "event")]
        assert outside(sc, items) == [], (sc["center"], outside(sc, items))
        hidden = {p["id"] for p in sc["persons"] if p["hidden"] == "true"}
        went_hidden |= hidden & {p["id"] for p in shifted}
        for lk in sc["links"]:
            if lk["to"] in hidden or lk["from"] in hidden:
                assert lk["hidden"] == "true" and lk["d"] is None, lk
    assert went_hidden, "ни один сдвинутый медальон не вышел из круга за 5 кадров"
    geo_built(events, response)


@req(GEO, MED, scenario="Детерминированность раскладки")
@pytest.mark.parametrize(("width", "height"), SIZES)
def test_layout_deterministic(knowledge_context, knowledge_stack, events, width, height):
    crowd(knowledge_stack.world, europe(5), 8)
    seen = []
    for _ in range(2):
        page, response = open_globe(
            knowledge_context,
            knowledge_stack,
            "/graph?view=globe&t=1750",
            width=width,
            height=height,
        )
        sc = scene(page)
        seen.append(
            (
                sorted((p["id"], p["x"], p["y"], p["packed"]) for p in sc["persons"]),
                sorted((tuple(b["places"]), b["text"]) for b in sc["more"]),
            )
        )
        geo_built(events, response)
        page.context.close()
    assert seen[0] == seen[1]
    assert len(seen[0][0]) == 40


@req(GEO, MED, scenario="Имя как текст")
def test_name_as_text(knowledge_context, knowledge_stack, events):
    world = knowledge_stack.world
    g = Geo(world)
    place = g.place("Афины", 37.98, 23.73)
    evil = world.person(XSS_IMG, "1700", "1780")
    evil2 = world.person(XSS_IMG_NOSPACE, "1700", "1780")
    g.lived(evil, place)
    g.lived(evil2, place)
    page, response, data = open_globe_map(
        knowledge_context, knowledge_stack, "/graph?view=globe&t=1750"
    )
    short = {p["id"]: p.get("short") or p["label"] for p in data["people"]}
    assert short[evil2] == XSS_IMG_NOSPACE
    names = {n["id"]: n for n in scene(page)["names"]}
    for who in (evil, evil2):
        assert names[who]["text"] == short[who]
        assert "<img" not in names[who]["html"]
    assert page.evaluate("typeof window.__xss") == "undefined"
    assert page.locator(".geo-stage img").count() == 0
    assert page.locator(".geo-globe image").count() == 0  # портретов нет
    geo_built(events, response)
    errors(page)


HOSTILE = {
    "html": XSS_IMG,
    "long": "Длинноимённый" * 12,
    "rtl": "ابن سينا",
    "mixed": "Анри‮Бергсон",
    "quote": "Д'Аламбер «Энциклопедист» & Ко",
}


@req(
    GEO,
    MED,
    invariant="подпись медальона — short из ответа /map, а если его нет — label, текстом, без перевода и замены на id",
)
def test_name_is_short_or_label(knowledge_context, knowledge_stack, events):
    world = knowledge_stack.world
    g = Geo(world)
    places = [g.place(n, lat, lon) for n, lat, lon in europe(8)]
    ids = {}
    for i, (k, label) in enumerate(HOSTILE.items()):
        ids[k] = world.person(label, "1700", "1780")
        g.lived(ids[k], places[i])
    ids["noshort"] = world.person("Без краткого Имени", "1700", "1780")
    g.lived(ids["noshort"], places[6])
    ids["emptyshort"] = world.person("Пустое Краткое", "1700", "1780")
    g.lived(ids["emptyshort"], places[7])

    def patch(route):
        body = route.fetch().json()
        for p in body["people"]:
            if p["id"] == ids["noshort"]:
                p.pop("short", None)
            if p["id"] == ids["emptyshort"]:
                p["short"] = ""
        route.fulfill(json=body)

    page, response, data = open_globe_map(
        knowledge_context,
        knowledge_stack,
        "/graph?view=globe&t=1750",
        width=1920,
        height=1080,
        before_extra=lambda p: p.route(MAP_API, patch),
    )
    by_id = {p["id"]: p for p in data["people"]}
    assert "short" not in by_id[ids["noshort"]] and by_id[ids["emptyshort"]]["short"] == ""
    sc = scene(page)
    names = {n["id"]: n["text"] for n in sc["names"]}
    shown = 0
    for p in sc["persons"]:
        if not drawn(p):
            continue
        src = by_id[p["id"]]
        want = src.get("short") or src["label"]
        assert names[p["id"]] == want, (p["id"], names.get(p["id"]), want)
        assert names[p["id"]] != p["id"]
        shown += 1
    assert shown >= 6
    assert names.get(ids["noshort"]) == "Без краткого Имени"
    assert names.get(ids["emptyshort"]) == "Пустое Краткое"
    assert page.evaluate("typeof window.__xss") == "undefined"
    items = shapes(sc, countries=True)
    assert collisions(items) == [] and outside(sc, items) == []
    geo_built(events, response)
    errors(page)


@req(GEO, MED, invariant="значок события — по правилам раскладки, без подписи и без свёртки")
def test_event_marks(knowledge_context, knowledge_stack, events):
    world = knowledge_stack.world
    g = Geo(world)
    people = crowd(world, [("Париж", 48.86, 2.35)], 19)
    [paris] = people
    evs = [world.thing("event", f"Событие {i}", "1740") for i in range(5)]
    for e in evs:
        g.happened(e, paris)
    for width, height in SIZES:
        page, response = open_globe(
            knowledge_context,
            knowledge_stack,
            "/graph?view=globe&t=1750",
            width=width,
            height=height,
        )
        sc = scene(page)
        marks = {e["id"]: e for e in sc["events"]}
        assert set(marks) == set(evs)
        for e in marks.values():
            assert e["place"] == paris
            if e["hidden"] == "false":
                assert abs(e["box"]["w"] - 10) < 0.6, e["box"]  # ромб, вписанный в круг 10 px
        assert not [n for n in sc["names"] if n["id"] in evs]
        assert not [b for b in sc["more"] if b["count"] and set(evs) & set(b["places"])]
        items = shapes(sc, countries=False)
        assert collisions(items) == [] and outside(sc, items) == []
        geo_built(events, response)
        page.context.close()


# --- Место персоны по нажатию -----------------------------------------------------------


def medal_click(page, entity: str) -> None:
    sc = scene(page)
    p = next(x for x in sc["persons"] if x["id"] == entity)
    assert drawn(p), p
    page.mouse.click(sc["left"] + p["box"]["cx"], sc["top"] + p["box"]["cy"])
    settle(page)


@req(GEO, WHERE, scenario="Нажатие на медальон")
@pytest.mark.parametrize(("width", "height"), SIZES)
def test_click_medal(knowledge_context, knowledge_stack, events, width, height):
    # На всех трёх размерах: в тесной панели (1024×576, 1366×768) блок «Где» SHALL быть
    # виден без раскрытия «Выбрано» (Д8). Тест раздел не раскрывает.
    w = athens_world(knowledge_stack.world)
    page, response = open_globe(
        knowledge_context,
        knowledge_stack,
        "/graph?view=globe&t=-360",
        width=width,
        height=height,
    )
    medal_click(page, w["plato"])
    # Выбранное названо в «Выбрано»: заголовком раздела («Выбрано · Платон», тесная панель)
    # или строкой имени под ним.
    expect(page.locator("h2", has_text="Выбрано").first).to_be_visible()
    chosen = page.locator("h2", has_text="Выбрано").first.text_content() or ""
    if page.locator(".map-selected__name").count():
        chosen += " " + (page.locator(".map-selected__name").first.text_content() or "")
    assert "Платон" in chosen, chosen
    expect(page.locator("[data-geo-where]")).to_be_visible()
    for part in ("place", "country", "role", "years"):
        expect(page.locator(f"[data-geo-where-{part}]")).to_be_visible()
    box = page.locator("[data-geo-where]").bounding_box()
    assert box and box["y"] >= 0 and box["y"] + box["height"] <= height, box
    block = where_block(page)
    assert (block["place"], block["country"], block["role"], block["years"]) == (
        "Афины",
        "Греция",
        "деятельность",
        "387–347 до н. э.",
    ), block
    assert "после смерти" not in block["text"]
    path, _q = page.url.split("?")[0], None
    assert path.rstrip("/").endswith(w["plato"])
    geo_built(events, response)
    errors(page)


def descartes(world) -> dict[str, str]:
    g = Geo(world)
    ids = {
        "descartes": world.person("Рене Декарт", "1596", "1650"),
        "anchor": world.person("Опорный", "1580", "1850"),
        "lahaye": g.place("Ла-Э", 46.98, 0.70),
        "amsterdam": g.place("Амстердам", 52.37, 4.90),
        "stockholm": g.place("Стокгольм", 59.33, 18.07),
    }
    g.lived(ids["descartes"], ids["lahaye"], "birth", "1596")
    g.lived(ids["descartes"], ids["amsterdam"], "activity", "1628–1649")
    g.lived(ids["descartes"], ids["stockholm"], "death", "1650")
    return ids


@req(GEO, WHERE, scenario="Годы по правилу")
def test_years_by_rule(knowledge_context, knowledge_stack, events):
    w = descartes(knowledge_stack.world)
    page, response = open_globe(
        knowledge_context,
        knowledge_stack,
        f"/graph/{w['descartes']}?view=globe&t=1610&from=1580&to=1850",
    )
    expected = {
        1610: ("Ла-Э", "Франция", "рождение", "1596–1627", False),
        1640: ("Амстердам", "Нидерланды", "деятельность", "1628–1649", False),
        1650: ("Стокгольм", "Швеция", "смерть", "1650", False),
        1700: ("Стокгольм", "Швеция", "смерть", "1650", True),
    }
    focus_globe(page)
    got = {}
    for t, keys in ((1610, []), (1640, ["PageUp"] * 3), (1650, ["PageUp"]), (1700, ["PageUp"] * 5)):
        for k in keys:
            press(page, k)
        expect(globe(page)).to_have_attribute("data-year", str(t))
        settle(page)
        b = where_block(page)
        got[t] = (b["place"], b["country"], b["role"], b["years"], "после смерти" in b["text"])
    assert got == expected
    geo_built(events, response)
    errors(page)


@req(GEO, WHERE, scenario="Нажатие на значок события")
def test_click_event_mark(knowledge_context, knowledge_stack, events):
    w = athens_world(knowledge_stack.world)
    ev = knowledge_stack.world.dated("event", "Основание Академии", fuzzy(-387))
    Geo(knowledge_stack.world).happened(ev, w["athens"])
    page, response = open_globe(knowledge_context, knowledge_stack, "/graph?view=globe&t=-380")
    sc = scene(page)
    [mark] = [e for e in sc["events"] if e["id"] == ev]
    assert mark["hidden"] == "false"
    page.mouse.click(sc["left"] + mark["box"]["cx"], sc["top"] + mark["box"]["cy"])
    settle(page)
    expect(page.locator(".map-selected__name")).to_contain_text("Основание Академии")
    block = where_block(page)
    assert (block["place"], block["country"], block["role"], block["years"]) == (
        "Афины",
        "Греция",
        "событие",
        "387 до н. э.",
    ), block
    geo_built(events, response)
    errors(page)


def tip(page):
    return page.locator("[data-geo-tip]")


@req(GEO, WHERE, scenario="Подсказка")
def test_tooltip(knowledge_context, knowledge_stack, events):
    w = athens_world(knowledge_stack.world)
    page, response = open_globe(knowledge_context, knowledge_stack, "/graph?view=globe&t=1760")
    sc = scene(page)
    k = next(p for p in sc["persons"] if p["id"] == w["kant"])
    page.mouse.move(sc["left"] + k["box"]["cx"], sc["top"] + k["box"]["cy"])
    expect(tip(page)).to_have_text("Кант — Кёнигсберг, Россия")
    page.mouse.move(sc["left"] + 5, sc["top"] + 5)
    expect(tip(page)).to_have_count(0)
    # Подпись персоны тоже даёт подсказку; начало перетаскивания её скрывает.
    [name] = [n for n in sc["names"] if n["id"] == w["kant"]]
    page.mouse.move(sc["left"] + name["box"]["cx"], sc["top"] + name["box"]["cy"])
    expect(tip(page)).to_have_text("Кант — Кёнигсберг, Россия")
    page.mouse.down()
    page.mouse.move(
        sc["left"] + name["box"]["cx"] + 40, sc["top"] + name["box"]["cy"] + 10, steps=4
    )
    expect(tip(page)).to_have_count(0)
    page.mouse.up()
    geo_built(events, response)
    errors(page)


@req(GEO, WHERE, scenario="Значок «+N»")
def test_click_more_badge(knowledge_context, knowledge_stack, events):
    people = crowd(knowledge_stack.world, [("Париж", 48.86, 2.35)], 19)
    [paris] = people
    page, response = open_globe(
        knowledge_context, knowledge_stack, "/graph?view=globe&t=1750", width=1024, height=576
    )
    focus_globe(page)
    press(page, "-", 12)
    settle(page)
    sc = scene(page)
    packed = [p for p in sc["persons"] if p["packed"] == "true"]
    assert packed, "при 19 персонах на 1024×576 никто не свёрнут"
    [badge] = [b for b in sc["more"] if b["hidden"] == "false"]
    assert badge["places"] == [paris]
    page.mouse.click(sc["left"] + badge["box"]["cx"], sc["top"] + badge["box"]["cy"])
    settle(page)
    expect(page).to_have_url(re.compile(rf"/graph/{paris}\?"))
    # На 1024×576 панель складывает разделы до заголовков («Панель карты») — читатель
    # раскрывает «Выбрано».
    fold = page.locator(".map-fold", has_text="Выбрано")
    if fold.get_attribute("aria-expanded") == "false":
        fold.click()
        expect(fold).to_have_attribute("aria-expanded", "true")
    expect(page.locator(".map-selected__name")).to_contain_text("Париж")
    who = page.locator(".geo-selected__who button")
    expect(who).to_have_count(19)
    expected = {f"Мыслитель 00-{i:02d}" for i in range(19)}
    assert set(who.all_inner_texts()) == expected
    geo_built(events, response)
    errors(page)


@req(GEO, WHERE, scenario="Место и страна как текст")
def test_place_and_country_as_text(knowledge_context, knowledge_stack, events):
    world = knowledge_stack.world
    g = Geo(world)
    place = g.place(XSS_B, 37.98, 23.73)
    who = world.person("Сократ", "1700", "1780")
    g.lived(who, place)
    page, response = open_globe(knowledge_context, knowledge_stack, "/graph?view=globe&t=1750")
    sc = scene(page)
    [m] = sc["persons"]
    page.mouse.move(sc["left"] + m["box"]["cx"], sc["top"] + m["box"]["cy"])
    expect(tip(page)).to_have_text(f"Сократ — {XSS_B}, Греция")
    medal_click(page, who)
    expect(page.locator("[data-geo-where-place]")).to_have_text(XSS_B)
    assert page.evaluate("typeof window.__xss") == "undefined"
    assert page.locator(".geo-stage b, .map-panel b").count() == 0
    geo_built(events, response)
    errors(page)


def mixed_world(world) -> dict:
    ids = descartes(world)
    g = Geo(world)
    ids["kant"] = world.person("Иммануил Кант", "1724", "1804")
    ids["konigsberg"] = g.place("Кёнигсберг", 54.71, 20.51)
    g.lived(ids["kant"], ids["konigsberg"], "birth", "1724")
    ids["hume"] = world.person("Дэвид Юм", "1711", "1776")
    ids["edinburgh"] = g.place("Эдинбург", 55.95, -3.19)
    g.lived(ids["hume"], ids["edinburgh"])
    ids["leibniz"] = world.person("Готфрид Лейбниц", "1646", "1716")
    ids["leipzig"] = g.place("Лейпциг", 51.34, 12.37)
    ids["hanover"] = g.place("Ганновер", 52.37, 9.74)
    g.lived(ids["leibniz"], ids["leipzig"], "birth", "1646")
    g.lived(ids["leibniz"], ids["hanover"], "activity", "1676–1716")
    g.lived(ids["leibniz"], ids["hanover"], "death", "1716")
    ids["locke"] = world.person("Джон Локк", "1632", "1704")
    ids["london"] = g.place("Лондон", 51.51, -0.13)
    ids["amst2"] = ids["amsterdam"]
    g.lived(ids["locke"], ids["london"], "residence", "1632–1683")
    g.lived(ids["locke"], ids["amsterdam"], "residence", "1683–1689")
    g.lived(ids["locke"], ids["london"], "residence", "1689–1704")
    return ids


def years_cover(text: str, t: int) -> bool:
    nums = [int(x) for x in re.findall(r"\d+", text)]
    if "до н. э." in text:
        nums = [-x for x in nums]
    if len(nums) == 1:
        return nums[0] == t
    return nums[0] <= t <= nums[1]


@req(
    GEO,
    WHERE,
    invariant="блок «Где в <год> году» совпадает с местом медальона, годы содержат T, если T не позже смерти",
)
def test_where_matches_medal(knowledge_context, knowledge_stack, events):
    w = mixed_world(knowledge_stack.world)
    death = {
        w["descartes"]: 1650,
        w["kant"]: 1804,
        w["hume"]: 1776,
        w["leibniz"]: 1716,
        w["locke"]: 1704,
    }
    page, response = open_globe(
        knowledge_context,
        knowledge_stack,
        "/graph?view=globe&t=1600&from=1580&to=1850",
        reduced_motion="reduce",
    )
    label = {p["id"]: p["label"] for p in response.json()["places"]}
    checked = 0
    for t in (1600, 1640, 1650, 1686, 1700, 1716, 1750, 1790, 1804, 1830):
        page.goto(knowledge_stack.url + f"/graph?view=globe&t={t}&from=1580&to=1850")
        globe_ready(page)
        sc = scene(page)
        for p in sc["persons"]:
            if not drawn(p) or p["id"] not in death:
                continue
            medal_click(page, p["id"])
            b = where_block(page)
            assert b and b["place"] == label[p["place"]], (t, p["id"], b)
            if t <= death[p["id"]]:
                assert years_cover(b["years"], t), (t, b)
                assert "после смерти" not in b["text"]
            else:
                assert "после смерти" in b["text"], (t, b)
            checked += 1
            page.keyboard.press("Escape")
    assert checked >= 15
    geo_built(events, response)
    errors(page)


@req(
    GEO,
    WHERE,
    invariant="значок нескольких мест приближает вид в 2 раза с центром в середине мест, на MAX_ZOOM выбирает первое",
)
def test_multi_place_badge(knowledge_context, knowledge_stack, events):
    crowd(knowledge_stack.world, [("Левый берег", 48.85, 2.30), ("Правый берег", 48.87, 2.40)], 12)
    page, response = open_globe(
        knowledge_context,
        knowledge_stack,
        "/graph?view=globe&t=1750",
        width=1024,
        height=576,
        reduced_motion="reduce",
    )
    coords = coords_of(response.json())
    focus_globe(page)
    press(page, "-", 12)
    settle(page)
    sc = scene(page)
    multi = [b for b in sc["more"] if b["hidden"] == "false" and len(b["places"]) >= 2]
    assert multi, sc["more"]
    b = multi[0]
    z0 = sc["zoom"]
    page.mouse.click(sc["left"] + b["box"]["cx"], sc["top"] + b["box"]["cy"])
    settle(page)
    sc1 = scene(page)
    assert sc1["zoom"] == round(min(8, z0 * 2), 2), (z0, sc1["zoom"])
    lats = [coords[p][0] for p in b["places"]]
    lons = [coords[p][1] for p in b["places"]]
    lon, lat = (float(v) for v in sc1["center"].split(","))
    assert abs(lat - sum(lats) / len(lats)) < 0.05 and abs(lon - sum(lons) / len(lons)) < 0.05, sc1[
        "center"
    ]
    geo_built(events, response)
    errors(page)


@req(
    GEO,
    MED,
    invariant="точка привязки рисуется только у сдвинутых маркеров, радиус не больше 2 px, без подписи",
)
def test_anchor_points(knowledge_context, knowledge_stack, events):
    people = dataset(knowledge_stack.world, "7x1")
    [athens] = people
    page, response = open_globe(knowledge_context, knowledge_stack, "/graph?view=globe&t=1750")
    sc = scene(page)
    x, y, _ = project(23.73, 37.98, sc)
    moved = [
        p
        for p in sc["persons"]
        if drawn(p) and math.hypot(p["box"]["cx"] - x, p["box"]["cy"] - y) > MEDAL / 2
    ]
    anchors = sc["anchors"]
    assert moved and len(anchors) == 1, (len(moved), anchors)
    a = anchors[0]
    assert a["r"] <= 2 and abs(a["box"]["cx"] - x) <= 0.6 and abs(a["box"]["cy"] - y) <= 0.6, (
        a,
        x,
        y,
    )
    assert page.locator(".geo-leader").count() >= len(moved)
    geo_built(events, response)
    page.context.close()
    # Один медальон в месте не сдвинут — точки привязки нет.
    assert athens


@req(GEO, MED, invariant="одна персона в месте — медальон в точке привязки, точки привязки нет")
def test_single_medal_no_anchor(knowledge_context, knowledge_stack, events):
    dataset(knowledge_stack.world, "1x1")
    page, response = open_globe(knowledge_context, knowledge_stack, "/graph?view=globe&t=1750")
    sc = scene(page)
    [p] = sc["persons"]
    x, y, _ = project(23.73, 37.98, sc)
    assert drawn(p) and math.hypot(p["box"]["cx"] - x, p["box"]["cy"] - y) <= 0.6
    assert sc["anchors"] == []
    geo_built(events, response)


TIME = "Люди, события и связи во времени"


@req(
    GEO,
    MED,
    invariant="сцена сменилась во время перетаскивания (проигрывание) — в каждом кадре медальоны ровно персон года T, медальонов персон вне сцены нет",
)
@req(
    GEO,
    TIME,
    invariant="проигрывание + перетаскивание: в каждом кадре число [data-geo-person] равно числу персон года",
)
@pytest.mark.parametrize(("width", "height"), SIZES)
def test_playback_while_dragging(knowledge_context, knowledge_stack, events, width, height):
    world = knowledge_stack.world
    g = Geo(world)
    births = {}
    # 12 персон, рождение 1702…1790 через 8 лет, смерть +30: в окне 1700–1800 конец видимости
    # (смерть + 150) за окном, поэтому персона в сцене года T ⇔ рождение ≤ T.
    for i in range(12):
        b = 1702 + 8 * i
        p = world.person(f"Странник {i:02d}", str(b), str(b + 30))
        g.lived(p, g.place(f"Город {i:02d}", 40 + (i % 4) * 4, -5 + (i // 4) * 10))
        births[p] = b
    page, response = open_globe(
        knowledge_context,
        knowledge_stack,
        "/graph?view=globe&from=1700&to=1800&t=1700",
        width=width,
        height=height,
    )
    play_button(page).click()
    years = set()
    frames = 0
    for dx, dy in ((0.3, 0.0), (-0.3, 0.1), (0.2, -0.2), (-0.2, 0.1)):
        sc = scene(page)
        for shot in drag_frames(page, sc["R"] * dx, sc["R"] * dy, frames=5):
            t = shot["year"]
            expected = {p for p, b in births.items() if b <= t}
            got = [p["id"] for p in shot["persons"]]
            assert len(got) == len(set(got)), (t, got)
            assert set(got) == expected, (t, sorted(set(got) ^ expected))
            years.add(t)
            frames += 1
    print(f"{width}×{height}: кадров {frames}, годы {sorted(years)}")
    assert frames == 20 and len(years) >= 2, years
    geo_built(events, response)
    errors(page)
