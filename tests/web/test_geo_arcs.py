"""Глобус: точные связи (rework-globe-political-map, задача 5.6).

Требование «Точные связи» дельты
``openspec/changes/rework-globe-political-map/specs/geo-timeline/spec.md``.
Концы дуг сверяются с центрами маркеров по прямоугольнику элемента и по ``data-x``/``data-y``;
вершина стрелки — с кривой, разобранной из ``d``, и с окружностью маркера цели (``arc_faults``).
Клиент событий журнала не пишет: серверный якорь — ``knowledge.geo.built`` по ``request_id``.
"""

# ruff: noqa: E501 — имена инвариантов спецификации

from __future__ import annotations

import math

import pytest

from .geo_helpers import (
    MEDAL,
    SIZES,
    Geo,
    arc_end_error,
    arc_faults,
    center_on,
    crowd,
    drag_frames,
    drawn,
    errors,
    focus_globe,
    geo_built,
    marker_of,
    open_globe,
    parse_arrow,
    press,
    project,
    scene,
    settle,
)
from .test_geo_medals import ancient, athens_world

req = pytest.mark.req
GEO = "geo-timeline"
ARCS = "Точные связи"

# 9 городов Европы и Средиземноморья, по две персоны; 12 связей учитель → ученик.
NINE = [
    ("Афины", 37.98, 23.73),
    ("Рим", 41.90, 12.50),
    ("Париж", 48.86, 2.35),
    ("Эдинбург", 55.95, -3.19),
    ("Кёнигсберг", 54.71, 20.51),
    ("Амстердам", 52.37, 4.90),
    ("Александрия", 31.20, 29.92),
    ("Мадрид", 40.42, -3.70),
    ("Стокгольм", 59.33, 18.07),
]
PAIRS = [
    (0, 2),
    (1, 3),
    (2, 5),
    (3, 8),
    (4, 9),
    (5, 11),
    (6, 13),
    (7, 15),
    (8, 17),
    (10, 1),
    (12, 16),
    (14, 4),
]


def links_world(world) -> dict:
    people = crowd(world, NINE, 2, prefix="Философ")
    flat = [p for ps in people.values() for p in ps]
    links = [world.relate(flat[b], "influenced_by", flat[a]) for a, b in PAIRS]
    g = Geo(world)
    pivot = g.place("Опора вращения", -60.0, -180.0)  # центр (−180, −60) выбором строки
    g.lived(world.person("Штурман", "1700", "1780"), pivot)
    return {"people": flat, "links": links, "pivot": pivot}


@req(GEO, ARCS, scenario="Дуга Платон → Аристотель")
def test_arc_plato_aristotle(knowledge_context, knowledge_stack, events):
    w = athens_world(knowledge_stack.world)
    link = knowledge_stack.world.relate(w["aristotle"], "influenced_by", w["plato"])
    page, response = open_globe(knowledge_context, knowledge_stack, "/graph?view=globe&t=-360")
    sc = scene(page)
    [lk] = [x for x in sc["links"] if x["id"] == link]
    assert (lk["from"], lk["to"], lk["hidden"]) == (w["plato"], w["aristotle"], "false"), lk
    assert arc_faults(sc) == []
    assert arc_end_error(sc) <= 1
    tip = parse_arrow(lk["arrow"])[0]
    px, py, _ = marker_of(sc, w["plato"])
    ax, ay, _ = marker_of(sc, w["aristotle"])
    assert abs(math.hypot(tip[0] - ax, tip[1] - ay) - MEDAL / 2) <= 1
    assert abs(math.hypot(tip[0] - px, tip[1] - py) - MEDAL / 2) > 1, "стрелка у источника"
    assert lk["arrows"] == 1
    geo_built(events, response)
    errors(page)


@req(GEO, ARCS, scenario="Концы на наборе поворотов и размеров")
@req(
    GEO,
    ARCS,
    invariant="концы пути ≤ 1 px от центров маркеров data-from/data-to, вершина стрелки на кривой и на окружности цели, ось по касательной ±5°, кривая в круге и в кадре, мёртвых дуг 0 — в покое и при перетаскивании",
)
@pytest.mark.parametrize(("width", "height"), SIZES)
def test_arc_ends_on_rotations(knowledge_context, knowledge_stack, events, width, height):
    w = links_world(knowledge_stack.world)
    page, response = open_globe(
        knowledge_context,
        knowledge_stack,
        "/graph?view=globe&t=1750",
        width=width,
        height=height,
        reduced_motion="reduce",
    )
    # Исходный вид и 5 кадров перетаскивания с него.
    sc = scene(page)
    assert {lk["id"] for lk in sc["links"]} == set(w["links"])
    assert arc_faults(sc) == []
    for shot in drag_frames(page, sc["R"] * 0.3, sc["R"] * 0.1, frames=5):
        assert arc_faults(shot) == [], (shot["center"], arc_faults(shot))
    settle(page)
    center_on(page, w["pivot"], (-180, -60))
    focus_globe(page)
    frames = visible = 0
    worst = 0.0
    for _lat_step in range(3):  # широта −60, 0, 60
        for _lon_step in range(12):  # долгота −180…150 через 30°
            for steps in (0, 3, 6):  # приближение 1; 1,95; 3,81
                press(page, "-", 12)
                press(page, "+", steps)
                settle(page)
                sc = scene(page)
                faults = arc_faults(sc)
                assert faults == [], (sc["center"], sc["zoom"], faults)
                worst = max(worst, arc_end_error(sc))
                visible += sum(1 for lk in sc["links"] if lk["hidden"] == "false")
                frames += 1
            press(page, "Shift+ArrowRight")
        press(page, "Shift+ArrowUp", 2)
    print(
        f"{width}×{height}: кадров {frames}, видимых дуг {visible}, худшее расхождение {worst:.3f} px"
    )
    assert frames == 108 and visible > 0
    geo_built(events, response)
    errors(page)


@req(
    GEO,
    ARCS,
    invariant="дуга не начинается и не кончается вне маркера во время вращения: 5 кадров перетаскивания на каждом размере и приближении",
)
@pytest.mark.parametrize(("width", "height"), SIZES)
def test_arc_ends_while_dragging(knowledge_context, knowledge_stack, events, width, height):
    w = links_world(knowledge_stack.world)
    page, response = open_globe(
        knowledge_context,
        knowledge_stack,
        "/graph?view=globe&t=1750",
        width=width,
        height=height,
        reduced_motion="reduce",
    )
    focus_globe(page)
    shots = 0
    for steps in (0, 3, 6):
        press(page, "0")
        press(page, "-", 12)
        press(page, "+", steps)
        settle(page)
        sc = scene(page)
        for dx, dy in ((0.4, 0), (-0.3, 0.2), (0.1, -0.4)):
            for shot in drag_frames(page, sc["R"] * dx, sc["R"] * dy, frames=5):
                assert arc_faults(shot) == [], (shot["center"], shot["zoom"], arc_faults(shot))
                shots += 1
            settle(page)
            assert arc_faults(scene(page)) == []
    assert shots == 45
    assert w["links"]
    geo_built(events, response)
    errors(page)


@req(GEO, ARCS, scenario="Конец за краем")
def test_end_beyond_edge(knowledge_context, knowledge_stack, events):
    g = Geo(knowledge_stack.world)
    world = knowledge_stack.world
    kant = world.person("Иммануил Кант", "1724", "1804")
    hume = world.person("Дэвид Юм", "1711", "1776")
    kgb = g.place("Кёнигсберг", 54.71, 20.51)
    edi = g.place("Эдинбург", 55.95, -3.19)
    g.lived(kant, kgb)
    g.lived(hume, edi)
    link = world.relate(kant, "influenced_by", hume)
    turn = g.place("Поворот", 20.0, -120.0)
    g.lived(world.person("Наблюдатель", "1700", "1790"), turn)
    page, response = open_globe(
        knowledge_context, knowledge_stack, "/graph?view=globe&t=1760", reduced_motion="reduce"
    )
    center_on(page, turn, (-120, 20))
    sc = scene(page)
    assert project(20.51, 54.71, sc)[2] < 0 and project(-3.19, 55.95, sc)[2] > 0
    m = {p["id"]: p for p in sc["persons"]}
    assert m[kant]["hidden"] == "true" and m[hume]["hidden"] == "false"
    [lk] = [x for x in sc["links"] if x["id"] == link]
    assert (lk["hidden"], lk["d"], lk["arrow"], lk["paths"]) == ("true", None, None, 0), lk
    assert (lk["from"], lk["to"]) == (hume, kant)
    geo_built(events, response)
    errors(page)


@req(GEO, ARCS, scenario="Оба в одном значке")
def test_both_in_one_badge(knowledge_context, knowledge_stack, events):
    world = knowledge_stack.world
    people = crowd(world, [("Париж", 48.86, 2.35)], 40)
    [ps] = people.values()
    links = [world.relate(ps[i + 1], "influenced_by", ps[i]) for i in range(0, 39, 2)]
    page, response = open_globe(
        knowledge_context, knowledge_stack, "/graph?view=globe&t=1750", width=1024, height=576
    )
    focus_globe(page)
    press(page, "-", 12)
    settle(page)
    sc = scene(page)
    packed = {p["id"] for p in sc["persons"] if p["packed"] == "true"}
    both = [lk for lk in sc["links"] if lk["from"] in packed and lk["to"] in packed]
    assert both, "нет связи, оба конца которой свёрнуты"
    for lk in both:
        assert (lk["hidden"], lk["d"], lk["arrow"]) == ("true", None, None), lk
    assert {lk["id"] for lk in sc["links"]} == set(links)
    assert arc_faults(sc) == []
    geo_built(events, response)
    errors(page)


@req(
    GEO,
    ARCS,
    invariant="связь — от маркера учителя к маркеру ученика, data-from — учитель, data-to — ученик, маркер свёрнутой персоны — её значок",
)
def test_link_direction_and_packed_marker(knowledge_context, knowledge_stack, events):
    world = knowledge_stack.world
    g = Geo(world)
    crowded = crowd(world, [("Лейпциг", 51.34, 12.37)], 30)
    [ps] = crowded.values()
    teacher = world.person("Одинокий учитель", "1700", "1780")
    g.lived(teacher, g.place("Кёнигсберг", 54.71, 20.51))
    links = {world.relate(p, "influenced_by", teacher): p for p in ps}
    plato = ancient(world, "Неважный", -400, -300)  # вне года — связи не касается
    assert plato
    page, response = open_globe(
        knowledge_context, knowledge_stack, "/graph?view=globe&t=1750", width=1366, height=768
    )
    focus_globe(page)
    press(page, "-", 12)
    settle(page)
    sc = scene(page)
    m = {p["id"]: p for p in sc["persons"]}
    to_badge = 0
    for lk in sc["links"]:
        assert lk["from"] == teacher and lk["to"] == links[lk["id"]], lk
        if m[lk["to"]]["packed"] == "true" and lk["hidden"] == "false":
            to_badge += 1
        if drawn(m[lk["to"]]):
            assert lk["hidden"] == "false"
    assert to_badge > 0, "нет связи к свёрнутой персоне"
    assert arc_faults(sc) == []
    geo_built(events, response)
    errors(page)
