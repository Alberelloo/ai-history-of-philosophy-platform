"""Глобус: политическая карта и страна места (rework-globe-political-map, задачи 5.2, 5.5).

Требования «Политическая карта» и «Страна места» дельты
``openspec/changes/rework-globe-political-map/specs/geo-timeline/spec.md``.
Настоящий сервис знаний (``knowledge_stack``), данные задаёт каждый тест.
Площадь и ширина видимой части стран, линии границ и страна точки считаются независимо:
d3-geo на пустой странице теста (``Oracle``) по ``world-atlas/countries-110m.json``.
Клиент событий журнала не пишет: серверный якорь — ``knowledge.geo.built`` по ``request_id``.
"""

# ruff: noqa: E501 — встроенные скрипты страницы и имена инвариантов спецификации

from __future__ import annotations

import json
import math

import pytest

from .geo_helpers import (
    CITIES,
    COUNTRY_INSET,
    COUNTRY_MIN_AREA,
    COUNTRY_MIN_LABELS,
    COUNTRY_STEP,
    COUNTRY_TRIES,
    FILL_FONT,
    LABEL_FONT,
    MAX_COUNTRY_LABELS,
    PAD,
    PLACES_API,
    RU_JSON,
    RU_TEXT,
    SIZES,
    WORLD_JSON,
    Geo,
    Oracle,
    center_on,
    collisions,
    crowd,
    errors,
    focus_globe,
    geo_built,
    globe_ready,
    open_globe,
    outside,
    overlap,
    overlay_obstacles,
    press,
    rows,
    ru_names,
    scene,
    settle,
    shapes,
    view_arg,
    where_block,
    world_ids,
)

req = pytest.mark.req
GEO = "geo-timeline"
POL = "Политическая карта"
COUNTRY = "Страна места"
NO_COUNTRY = "страна не определена"

# Наборы центров: из сценария «Пять подписей» и ещё шесть до десяти (инвариант 5.2а).
SCENARIO_CENTERS = [(15, 50), (100, 40), (-60, -10), (20, 0)]
MORE_CENTERS = [(-100, 40), (140, -25), (78, 22), (-3, 40), (30, 60), (120, 35)]
# Приближения: ряд 1,25^k — клавиши дают только его; «2» и «4» — ближайшие 1,95 и 3,81.
ZOOM_STEPS = {1: 0, 2: 3, 4: 6}


def centers_world(world, centers) -> list[str]:
    """По персоне в месте на каждом центре (выбор места в списке ставит центр вида)."""
    g = Geo(world)
    ids = []
    for i, (lon, lat) in enumerate(centers):
        place = g.place(f"Центр {i:02d}", lat, lon)
        g.lived(world.person(f"Путник {i:02d}", "1700", "1780"), place)
        ids.append(place)
    return ids


def label_faults(sc, o, names, *, with_markers=True, overlay_rects=None) -> list:
    """Нарушения правила подписей стран в кадре ``sc``: словарь, площадь, ширина, точка внутри,
    пересечения и кадр. Площадь и ширина сверяются с независимым расчётом d3-geo."""
    bad = []
    vis = o("visible", view_arg(sc))
    labels = sc["countries"]
    if len(labels) > MAX_COUNTRY_LABELS:
        bad.append(("больше 24 подписей", len(labels)))
    for c in labels:
        if c["text"] != names.get(c["id"]):
            bad.append(("текст не из словаря", c["id"], c["text"], names.get(c["id"])))
        if not RU_TEXT.match(c["text"] or ""):
            bad.append(
                ("символы вне кириллицы, пробела, дефиса, точки, апострофа", c["id"], c["text"])
            )
        v = vis.get(c["id"])
        if v is None:
            bad.append(("подпись страны не на видимой стороне", c["id"]))
            continue
        if c["fill"] is None and (c["area"] < COUNTRY_MIN_AREA or v["area"] < COUNTRY_MIN_AREA - 1):
            bad.append(
                (
                    "площадь меньше 1500 у подписи без data-fill",
                    c["id"],
                    c["area"],
                    round(v["area"]),
                )
            )
        if c["fill"] not in (None, "true"):
            bad.append(("data-fill не «true»", c["id"], c["fill"]))
        if c["fill"] is None and abs(c["fs"] - LABEL_FONT) > 0.01:
            bad.append(("кегль основной подписи не 10,5 px", c["id"], c["fs"]))
        if c["fill"] == "true" and min(abs(c["fs"] - LABEL_FONT), abs(c["fs"] - FILL_FONT)) > 0.01:
            bad.append(("кегль подписи добора не 10,5 и не 9 px", c["id"], c["fs"]))
        if abs(c["area"] - v["area"]) > max(2.0, 0.01 * v["area"]):
            bad.append(
                ("data-area не равна видимой площади", c["id"], c["area"], round(v["area"], 1))
            )
        if abs(c["span"] - v["span"]) > 1.5:
            bad.append(
                ("data-span не равна ширине видимой части", c["id"], c["span"], round(v["span"], 1))
            )
        if c["box"]["w"] > c["span"] + 0.5 or c["box"]["w"] > v["span"] + 0.5:
            bad.append(("подпись шире страны", c["id"], c["box"]["w"], c["span"]))
        # Точка подписи — центр прямоугольника текста (по горизонтали — x при text-anchor
        # middle, по вертикали — середина между верхней и нижней метрикой шрифта).
        point = o("invert", view_arg(sc), c["box"]["cx"], c["box"]["cy"])
        if not point or not o("contains", c["id"], point[0], point[1]):
            bad.append(("точка подписи не внутри страны", c["id"], c["box"]["cx"], c["box"]["cy"]))
        if abs(c["box"]["cx"] - c["ax"]) > 1.0:  # ширина текста округляется до целого
            bad.append(("подпись не по центру точки", c["id"], c["box"]["cx"], c["ax"]))
    main = [c for c in labels if c["fill"] is None]
    fill = [c for c in labels if c["fill"] == "true"]
    if fill and len(main) >= COUNTRY_MIN_LABELS:
        bad.append(("добор при 5 и больше основных подписях", len(main), [c["id"] for c in fill]))
    if fill and len(labels) > COUNTRY_MIN_LABELS:
        bad.append(("с добором подписей больше 5", len(labels)))
    # Добор идёт по убыванию видимой площади. Какая страна «поместилась бы» кеглем добора,
    # независимо не посчитать (нужна ширина текста), поэтому сверяется порядок внутри добора.
    areas = [c["area"] for c in fill]
    if areas != sorted(areas, reverse=True):
        bad.append(("добор не по убыванию площади", [(c["id"], c["area"]) for c in fill]))
    items = [s for s in shapes(sc) if with_markers or s[0] == "country"]
    for a, b in collisions(items):
        if "country" in (a[0], b[0]):
            bad.append(("пересечение", a[:2], b[:2]))
    bad += [x for x in outside(sc, items) if x[0] == "country"]
    # Правило 5 (после Д10): подпись не пересекает наложенные элементы вида.
    for c in labels:
        b = c["box"]
        rect = ("r", b["x"] - PAD, b["y"] - PAD, b["x"] + b["w"] + PAD, b["y"] + b["h"] + PAD)
        for r in overlay_rects or []:
            if overlap(rect, r):
                bad.append(("подпись страны на наложенном элементе вида", c["id"], r))
    return bad


# --- Политическая карта: сценарии -----------------------------------------------------


@req(GEO, POL, scenario="Границы и подписи")
def test_borders_and_labels(knowledge_context, knowledge_stack, events):
    [_c] = centers_world(knowledge_stack.world, [(40, 50)])
    page, response = open_globe(knowledge_context, knowledge_stack, "/graph?view=globe&t=1750")
    focus_globe(page)
    press(page, "-", 12)  # исходный вид одного места — приближение 4; к 1
    settle(page)
    sc = scene(page)
    assert (sc["center"], sc["zoom"]) == ("40,50", 1), (sc["center"], sc["zoom"])
    o = Oracle(page.context)
    topo = json.loads(WORLD_JSON.read_text("utf-8"))
    assert sc["borders"] > 0
    assert sc["borders"] == o("borders", view_arg(sc))["n"]
    assert sc["countryCount"] == len(topo["objects"]["countries"]["geometries"]), sc["countryCount"]
    # Пиксель на общей границе Франции и Германии.
    probe = border_pixel(page, o, sc, "250", "276")
    assert probe["ok"], probe
    labels = {c["id"]: c for c in sc["countries"]}
    assert labels.get("643", {}).get("text") == "Россия", sorted(labels)
    boxes = [s for s in shapes(sc) if s[0] == "country"]
    assert collisions(boxes) == []
    geo_built(events, response)
    errors(page)


BORDER_PIXEL_JS = """
([p, n, step]) => {
  const canvas = document.querySelector('[data-geo-land]');
  const svg = document.querySelector('.geo-globe').getBoundingClientRect();
  const r = canvas.getBoundingClientRect();
  const k = canvas.width / r.width;
  const ctx = canvas.getContext('2d');
  const at = (x, y) => { const px = Math.round((x + svg.x - r.x) * k - 0.5), py = Math.round((y + svg.y - r.y) * k - 0.5);
    return [...ctx.getImageData(px, py, 1, 1).data]; };
  const token = name => { const d = document.createElement('div'); d.style.color = `var(${name})`;
    document.body.appendChild(d); const c = getComputedStyle(d).color.match(/[\\d.]+/g).map(Number); d.remove(); return c.slice(0, 3); };
  const border = token('--globe-border');
  const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
  let best = null;
  for (let dx = -1; dx <= 1; dx += 0.5) for (let dy = -1; dy <= 1; dy += 0.5) {
    const c = at(p[0] + dx, p[1] + dy); if (!best || dist(c, border) < dist(best, border)) best = c; }
  // Суша по обе стороны: из точек в 2…6 px от линии — ближайшая к цвету токена globe-land
  // (рядом может пройти береговая линия или сетка).
  const land = token('--globe-land');
  const side = sgn => { let pick = null; for (let d = 2; d <= step + 1; d += 0.5) {
      const c = at(p[0] + sgn * n[0] * d, p[1] + sgn * n[1] * d); if (!pick || dist(c, land) < dist(pick, land)) pick = c; }
    return pick; };
  const left = side(1), right = side(-1);
  return {best, left, right, border, dBest: dist(best, border), dLeft: dist(left, border),
          dRight: dist(right, border), sideL: dist(best, left), sideR: dist(best, right),
          landL: dist(left, land), landR: dist(right, land)};
}
"""


def border_pixel(page, o, sc, a: str, b: str, step: float = 5.0) -> dict:
    """Пиксель canvas в проекции середины линии общей границы ``a``/``b`` (проекция — d3 теста)
    против пикселей суши по обе стороны от линии и цвета токена ``globe-border``."""
    line = o("pairLine", a, b)
    assert line and len(line) >= 3, (a, b, line)
    i = len(line) // 2
    v = view_arg(sc)
    p = o("project", v, *line[i])
    p0, p1 = o("project", v, *line[i - 1]), o("project", v, *line[i + 1])
    tx, ty = p1[0] - p0[0], p1[1] - p0[1]
    norm = math.hypot(tx, ty)
    n = (-ty / norm, tx / norm)
    got = page.evaluate(BORDER_PIXEL_JS, [p, n, step])
    # С допуском сглаживания: пиксель линии ближе к цвету границы, чем суша по обе стороны,
    # не дальше 60 % пути от суши к цвету границы, и отличается от обеих сторон.
    got["ok"] = (
        got["dBest"] <= 0.6 * min(got["dLeft"], got["dRight"])
        and got["sideL"] > 10
        and got["sideR"] > 10
        and got["landL"] <= 40
        and got["landR"] <= 40
    )
    got["point"] = p
    return got


@req(GEO, POL, scenario="Пять подписей на видимой стороне")
@pytest.mark.parametrize(("width", "height"), SIZES)
def test_five_labels_visible_side(knowledge_context, knowledge_stack, events, width, height):
    places = centers_world(knowledge_stack.world, SCENARIO_CENTERS)
    page, response = open_globe(
        knowledge_context,
        knowledge_stack,
        "/graph?view=globe&t=1750",
        width=width,
        height=height,
        reduced_motion="reduce",
    )
    o = Oracle(page.context)
    names = ru_names()
    seen = []
    for place, lonlat in zip(places, SCENARIO_CENTERS, strict=True):
        center_on(page, place, lonlat)
        focus_globe(page)
        for z, steps in ((1, 0), (2, 3)):
            press(page, "-", 10)
            press(page, "+", steps)
            settle(page)
            sc = scene(page)
            vis = o("visible", view_arg(sc))
            labels = sc["countries"]
            seen.append((lonlat, z, sc["zoom"], len(labels)))
            assert len(labels) >= 5, (lonlat, z, [c["text"] for c in labels])
            for c in labels:
                assert c["id"] in vis, ("подпись страны не на видимом полушарии", c)
                assert c["text"] == names[c["id"]], c
                assert RU_TEXT.match(c["text"]), c["text"]
    assert len(seen) == 8
    geo_built(events, response)
    errors(page)


@req(GEO, POL, scenario="Подписи на исходном виде")
@pytest.mark.parametrize(("width", "height"), SIZES)
def test_labels_on_home_view(knowledge_context, knowledge_stack, events, width, height):
    crowd(knowledge_stack.world, CITIES[:30], 1)
    page, response = open_globe(
        knowledge_context, knowledge_stack, "/graph?view=globe&t=1750", width=width, height=height
    )
    sc = scene(page)
    assert len([p for p in sc["persons"]]) == 30
    labels = sc["countries"]
    assert len(labels) >= 5, (sc["zoom"], [c["text"] for c in labels])
    clashes = [(a[:2], b[:2]) for a, b in collisions(shapes(sc)) if "country" in (a[0], b[0])]
    assert clashes == [], clashes
    geo_built(events, response)


# Ширина подписи — тем же начертанием, что подписи стран на странице (кегль задаёт тест).
TEXT_WIDTH_JS = """([texts, size]) => {
  const ref = document.querySelector('[data-geo-country]') || document.querySelector('.geo-globe text');
  const st = getComputedStyle(ref);
  const ctx = document.createElement('canvas').getContext('2d');
  ctx.font = `${st.fontStyle} ${st.fontWeight} ${size}px ${st.fontFamily}`;
  return Object.fromEntries(texts.map(t => [t, ctx.measureText(t).width]));
}"""


def fitting_countries(page, sc, o, names) -> dict[str, list]:
    """Страны видимой стороны с кодом, чья подпись кеглем добора (9 px) помещается по правилам
    3–5, считая препятствиями всё, что нарисовано в кадре (медальоны, значки, подписи персон и
    уже поставленные подписи стран). Независимый расчёт: d3-geo и world-atlas на пустой
    странице, ширина текста — canvas. Подписанные продуктом страны входят без проверки.
    Возвращает {код: точка подписи или «продукт»}."""
    labelled = {c["id"] for c in sc["countries"]}
    # Препятствия: фигуры SVG и наложенные элементы вида (правило 5 после Д10), измеренные тестом.
    obstacles = [s for _k, _i, s in shapes(sc)] + overlay_obstacles(page)
    ref = sc["countries"][0] if sc["countries"] else None
    height = (ref["box"]["h"] / ref["fs"] * FILL_FONT) if ref else FILL_FONT * 1.3
    out: dict[str, list] = {cid: ["продукт"] for cid in labelled}
    spots = o("labelSpots", view_arg(sc), COUNTRY_STEP, COUNTRY_TRIES, COUNTRY_INSET)
    texts = [names[c] for c in spots if c in names and c not in labelled]
    width = page.evaluate(TEXT_WIDTH_JS, [texts, FILL_FONT])
    for cid, spot in spots.items():
        if cid in labelled or cid not in names:
            continue
        w = width[names[cid]]
        if w > spot["span"]:
            continue
        for x, y in spot["points"]:
            rect = (
                "r",
                x - w / 2 - 1.5,
                y - height / 2 - 1.5,
                x + w / 2 + 1.5,
                y + height / 2 + 1.5,
            )
            if (
                x - w / 2 < 0
                or y - height / 2 < 0
                or x + w / 2 > sc["w"]
                or y + height / 2 > sc["h"]
            ):
                continue
            if any(overlap(rect, ob) for ob in obstacles):
                continue
            out[cid] = [round(x, 1), round(y, 1)]
            break
    return out


@req(
    GEO,
    POL,
    invariant="на видах после действий читателя подписей меньше 5 только тогда, когда меньше 5 стран с кодом помещают подпись по правилам 3–5",
)
@pytest.mark.parametrize(("width", "height"), SIZES)
def test_fewer_labels_only_when_few_fit(knowledge_context, knowledge_stack, events, width, height):
    crowd(knowledge_stack.world, CITIES[:30], 1)
    page, response = open_globe(
        knowledge_context,
        knowledge_stack,
        "/graph?view=globe&t=1750",
        width=width,
        height=height,
        reduced_motion="reduce",
    )
    o = Oracle(page.context)
    names = ru_names()
    focus_globe(page)
    views = []
    for keys in (["+", "+"], ["+"], ["Shift+ArrowLeft"], ["Shift+ArrowUp"], ["+", "+"]):
        for k in keys:
            press(page, k)
        settle(page)
        sc = scene(page)
        n = len(sc["countries"])
        views.append((sc["center"], sc["zoom"], n))
        if n >= COUNTRY_MIN_LABELS:
            continue
        fit = fitting_countries(page, sc, o, names)
        assert len(fit) < COUNTRY_MIN_LABELS, (
            "подписей меньше 5, а помещается подпись у 5 и больше стран",
            sc["center"],
            sc["zoom"],
            [c["id"] for c in sc["countries"]],
            fit,
        )
    assert len(views) == 5, views
    geo_built(events, response)
    errors(page)


def empty_scene_world(world, centers) -> list[str]:
    """Места на центрах с персонами 1700–1780 и персона без места 1950–2000: в конце окна
    (после 1930) в сцене никого нет, а вид остаётся на последнем выбранном центре."""
    places = centers_world(world, centers)
    world.person("Опорный без места", "1950", "2000")
    return places


def to_window_edge(page, key: str) -> None:
    slider = page.locator("[role='slider'][data-year]")
    slider.focus()
    page.keyboard.press(key)
    settle(page)


@req(GEO, POL, scenario="Только крупные")
def test_only_large_countries(knowledge_context, knowledge_stack, events):
    places = empty_scene_world(knowledge_stack.world, SCENARIO_CENTERS)
    page, response = open_globe(
        knowledge_context,
        knowledge_stack,
        "/graph?view=globe&t=1750",
        width=1366,
        height=768,
        reduced_motion="reduce",
    )
    o = Oracle(page.context)
    names = ru_names()
    checked = 0
    for place, lonlat in zip(places, SCENARIO_CENTERS, strict=True):
        to_window_edge(page, "Home")
        center_on(page, place, lonlat)
        to_window_edge(page, "End")
        focus_globe(page)
        for z, steps in ((1, 0), (2, 3)):
            press(page, "-", 10)
            press(page, "+", steps)
            settle(page)
            sc = scene(page)
            assert [p for p in sc["persons"]] == [], "в сцене есть персоны"
            assert sc["countries"], (lonlat, z)
            main = [c for c in sc["countries"] if c["fill"] is None]
            fill = [c for c in sc["countries"] if c["fill"] == "true"]
            for c in main:
                assert c["area"] >= COUNTRY_MIN_AREA, c
            if fill:
                assert (
                    len(main) < COUNTRY_MIN_LABELS and len(sc["countries"]) <= COUNTRY_MIN_LABELS
                ), (lonlat, z, main, fill)
            for c in sc["countries"]:
                assert c["box"]["w"] <= c["span"] + 0.5, c
            assert (
                label_faults(
                    sc, o, names, with_markers=False, overlay_rects=overlay_obstacles(page)
                )
                == []
            )
            if lonlat == (15, 50) and z == 1:
                ids = {c["id"] for c in sc["countries"]}
                assert sc["center"] == "15,50" and sc["zoom"] == 1
                assert "056" not in ids, "подпись Бельгии"
                assert "643" in ids, "нет подписи России"
            checked += 1
    assert checked == 8
    geo_built(events, response)
    errors(page)


@req(GEO, POL, scenario="Полнота словаря")
def test_dictionary_complete(knowledge_context, knowledge_stack, events):
    data = json.loads(RU_JSON.read_text("utf-8"))
    names = data["names"]
    ids = world_ids()
    assert len(ids) == len(set(ids))
    missing = [i for i in ids if not (names.get(i) or "").strip()]
    assert missing == []
    extra = sorted(set(names) - set(ids))
    assert extra == []
    assert all(RU_TEXT.match(names[i]) for i in ids), [
        names[i] for i in ids if not RU_TEXT.match(names[i])
    ]
    # Территории без id подписи не получают: на глобусе нет подписи с кодом не из world-atlas.
    centers_world(
        knowledge_stack.world, [(21, 42.6), (33.5, 35.2), (45, 9.5)]
    )  # Косово, Сев. Кипр, Сомалиленд
    page, response = open_globe(knowledge_context, knowledge_stack, "/graph?view=globe&t=1750")
    focus_globe(page)
    for _ in range(4):
        sc = scene(page)
        assert {c["id"] for c in sc["countries"]} <= set(ids)
        assert all(c["id"] and c["text"] for c in sc["countries"])
        press(page, "-")
        settle(page)
    geo_built(events, response)


@req(GEO, POL, scenario="Подписи не наезжают")
def test_labels_do_not_collide_on_rotation(knowledge_context, knowledge_stack, events):
    crowd(knowledge_stack.world, CITIES[:30], 1)
    page, response = open_globe(
        knowledge_context,
        knowledge_stack,
        "/graph?view=globe&t=1750",
        width=1024,
        height=576,
        reduced_motion="reduce",
    )
    focus_globe(page)
    frames = 0
    for _ in range(12):
        press(page, "Shift+ArrowRight")
        settle(page)
        sc = scene(page)
        items = shapes(sc)
        clashes = [(a[:2], b[:2]) for a, b in collisions(items) if "country" in (a[0], b[0])]
        assert clashes == [], (sc["center"], clashes)
        frames += 1
    assert frames == 12
    geo_built(events, response)


# --- Политическая карта: инварианты -----------------------------------------------------


@req(
    GEO,
    POL,
    invariant="подписи стран не пересекаются между собой, с медальонами, значками и подписями персон и лежат в кадре",
)
@pytest.mark.parametrize(("width", "height"), SIZES)
def test_country_labels_never_overlap(knowledge_context, knowledge_stack, events, width, height):
    world = knowledge_stack.world
    centers = SCENARIO_CENTERS + MORE_CENTERS
    places = centers_world(world, centers)
    crowd(world, CITIES[:12], 3)  # медальоны, подписи и значки «+N» в Европе
    page, response = open_globe(
        knowledge_context,
        knowledge_stack,
        "/graph?view=globe&t=1750",
        width=width,
        height=height,
        reduced_motion="reduce",
    )
    frames = []
    for place, lonlat in zip(places, centers, strict=True):
        center_on(page, place, lonlat)
        focus_globe(page)
        for z, steps in ZOOM_STEPS.items():
            press(page, "-", 10)
            press(page, "+", steps)
            settle(page)
            sc = scene(page)
            items = shapes(sc)
            clashes = [(a[:2], b[:2]) for a, b in collisions(items) if "country" in (a[0], b[0])]
            off = [x for x in outside(sc, items) if x[0] == "country"]
            assert clashes == [] and off == [], (lonlat, z, clashes, off)
            assert len(sc["countries"]) <= MAX_COUNTRY_LABELS
            frames.append((lonlat, sc["zoom"], len(sc["countries"]), len(items)))
    assert len(frames) == 30
    assert sum(f[2] for f in frames) > 0
    geo_built(events, response)


@req(
    GEO,
    POL,
    invariant="текст подписи страны равен названию из словаря по коду, data-area ≥ 1500 и равна видимой площади, ширина подписи ≤ data-span, точка подписи внутри страны",
)
@pytest.mark.parametrize(("width", "height"), SIZES)
def test_country_label_rule_on_many_views(
    knowledge_context, knowledge_stack, events, width, height
):
    centers = SCENARIO_CENTERS + MORE_CENTERS
    places = centers_world(knowledge_stack.world, centers)
    page, response = open_globe(
        knowledge_context,
        knowledge_stack,
        "/graph?view=globe&t=1750",
        width=width,
        height=height,
        reduced_motion="reduce",
    )
    o = Oracle(page.context)
    names = ru_names()
    n = 0
    for place, lonlat in zip(places, centers, strict=True):
        center_on(page, place, lonlat)
        focus_globe(page)
        for z, steps in ZOOM_STEPS.items():
            press(page, "-", 10)
            press(page, "+", steps)
            settle(page)
            sc = scene(page)
            faults = label_faults(sc, o, names, overlay_rects=overlay_obstacles(page))
            assert faults == [], (lonlat, z, faults)
            n += len(sc["countries"])
    assert n > 0
    geo_built(events, response)


PAIRS = [
    ("250", "276"),
    ("724", "620"),
    ("616", "276"),
    ("643", "398"),
    ("840", "124"),
    ("076", "032"),
]


@req(
    GEO,
    POL,
    invariant="пиксель на линии общей границы отличается от суши по обе стороны и близок к цвету globe-border",
)
@pytest.mark.parametrize(("width", "height"), SIZES)
def test_border_pixels(knowledge_context, knowledge_stack, events, width, height):
    # Центр — на каждой паре соседей: место на общей границе (середина линии из world-atlas).
    context = knowledge_context(width, height, reduced_motion="reduce")
    o = Oracle(context)
    g = Geo(knowledge_stack.world)
    ids = []
    for i, (a, b) in enumerate(PAIRS):
        line = o("pairLine", a, b)
        lon, lat = line[len(line) // 2]
        place = g.place(f"Граница {i}", round(lat, 2), round(lon, 2))
        g.lived(knowledge_stack.world.person(f"Пограничник {i}", "1700", "1780"), place)
        ids.append((place, (round(lon, 2), round(lat, 2))))
    page = context.new_page()
    page.set_default_timeout(30000)
    with page.expect_response(lambda r: PLACES_API.match(r.url)) as info:
        page.goto(knowledge_stack.url + "/graph?view=globe&t=1750")
    globe_ready(page)
    results = []
    for (place, lonlat), (a, b) in zip(ids, PAIRS, strict=True):
        center_on(page, place, lonlat)
        focus_globe(page)
        for steps in (0, 3):
            press(page, "-", 10)
            press(page, "+", steps)
            settle(page)
            sc = scene(page)
            probe = border_pixel(page, o, sc, a, b)
            results.append(
                (
                    (a, b),
                    sc["zoom"],
                    probe["ok"],
                    {k: probe[k] for k in ("best", "left", "right", "point")},
                )
            )
    assert [r for r in results if not r[2]] == []
    assert len(results) == 12
    geo_built(events, info.value)


@req(GEO, POL, invariant="data-borders — число линий сетки границ с вершиной на видимом полушарии")
@pytest.mark.parametrize(("width", "height"), SIZES)
def test_borders_count_matches_mesh(knowledge_context, knowledge_stack, events, width, height):
    centers = SCENARIO_CENTERS + MORE_CENTERS + [(0, 89), (180, 0), (-180, -60), (-150, -5)]
    places = centers_world(knowledge_stack.world, centers)
    page, response = open_globe(
        knowledge_context,
        knowledge_stack,
        "/graph?view=globe&t=1750",
        width=width,
        height=height,
        reduced_motion="reduce",
    )
    o = Oracle(page.context)
    seen = []
    for place, _lonlat in zip(places, centers, strict=True):
        center_on(page, place)
        settle(page)
        sc = scene(page)
        expected = o("borders", view_arg(sc))
        seen.append((sc["center"], sc["borders"], expected))
        # Линия ровно на краю полушария (угол 90° ± 1e-6) может считаться по-разному.
        assert expected["n"] <= sc["borders"] <= expected["n"] + expected["edge"], seen[-1]
    # (−150, −5) — Тихий океан: сухопутных границ на видимой стороне почти нет, но > 0 есть
    assert all(s[1] > 0 for s in seen if s[2]["n"] > 0)
    geo_built(events, response)


# --- Страна места -------------------------------------------------------------------------

PILOT = [
    ("Афины", 37.98, 23.73, "Греция"),
    ("Кёнигсберг", 54.71, 20.51, "Россия"),
    ("Эдинбург", 55.95, -3.19, "Великобритания"),
    ("Амстердам", 52.37, 4.90, "Нидерланды"),
    ("Париж", 48.86, 2.35, "Франция"),
    ("Рим", 41.90, 12.50, "Италия"),
    ("Стокгольм", 59.33, 18.07, "Швеция"),
    ("Александрия", 31.20, 29.92, "Египет"),
]


def placed(world, items) -> dict[str, tuple[str, str]]:
    """По персоне в каждом месте: id места → (название, имя персоны)."""
    g = Geo(world)
    out = {}
    for i, (name, lat, lon, *_rest) in enumerate(items):
        place = g.place(name, lat, lon)
        who = f"Житель{i:02d}"
        g.lived(world.person(who, "1700", "1780"), place)
        out[place] = (name, who)
    return out


def country_in_panel(page, place: str, who: str) -> dict:
    page.locator(f"[data-geo-row='{place}'] .geo-row__who button", has_text=who).click()
    page.locator("[data-geo-where]").wait_for()
    settle(page)
    return where_block(page)


@req(GEO, COUNTRY, scenario="Города пилотного раздела")
def test_pilot_cities(knowledge_context, knowledge_stack, events):
    ids = placed(knowledge_stack.world, PILOT)
    page, response = open_globe(knowledge_context, knowledge_stack, "/graph?view=globe&t=1750")
    r = rows(page)
    for (place, (name, who)), (_n, _lat, _lon, country) in zip(ids.items(), PILOT, strict=True):
        assert r[place]["label"] == f"{name}, {country}", r[place]
        block = country_in_panel(page, place, who)
        assert (block["place"], block["country"]) == (name, country), block
    geo_built(events, response)
    errors(page)


@req(GEO, COUNTRY, scenario="Побережье и открытое море")
def test_coast_and_open_sea(knowledge_context, knowledge_stack, events):
    items = [("Сиракузы", 37.08, 15.29), ("Точка в Атлантике", 0, -30)]
    ids = placed(knowledge_stack.world, items)
    page, response = open_globe(knowledge_context, knowledge_stack, "/graph?view=globe&t=1750")
    (syr, (_syr_name, syr_who)), (sea, (_sea_name, sea_who)) = ids.items()
    r = rows(page)
    assert r[syr]["label"] == "Сиракузы, Италия"
    assert r[sea]["label"] == "Точка в Атлантике"
    assert country_in_panel(page, syr, syr_who)["country"] == "Италия"
    assert country_in_panel(page, sea, sea_who)["country"] == NO_COUNTRY
    geo_built(events, response)
    errors(page)


@req(GEO, COUNTRY, scenario="Края и мусор")
def test_edges_and_garbage(knowledge_context, knowledge_stack, events):
    context = knowledge_context(1920, 1080)
    o = Oracle(context)
    inside = o("nearBorderInside", "Kosovo", 10)
    assert inside and abs(inside["d"] - 10) < 1.5, inside
    lon, lat = inside["p"]
    items = [
        ("Северный полюс", 90, 180),
        ("Южный полюс", -90, -180),
        ("Сто восьмидесятый", 0, 180),
        ("Минус сто восьмидесятый", 0, -180),
        ("Приштина", 42.66, 21.17),
        ("Косово у границы", round(lat, 4), round(lon, 4)),
    ]
    ids = placed(knowledge_stack.world, items)
    page = context.new_page()
    page.set_default_timeout(30000)
    with page.expect_response(lambda r: PLACES_API.match(r.url)) as info:
        page.goto(knowledge_stack.url + "/graph?view=globe&t=1750")
    globe_ready(page)
    names = set(ru_names().values())
    got = {}
    for place, (name, who) in ids.items():
        block = country_in_panel(page, place, who)
        assert block["place"] == name
        assert block["country"] in names or block["country"] == NO_COUNTRY, block
        got[name] = block["country"]
    assert got["Приштина"] == NO_COUNTRY
    assert got["Косово у границы"] == NO_COUNTRY
    geo_built(events, info.value)
    errors(page)


@req(
    GEO,
    COUNTRY,
    invariant="страна места — по принадлежности, иначе ближайшая вершина ≤ 150 км среди стран с id, иначе нет; территория без id останавливает поиск; название только из словаря",
)
@pytest.mark.parametrize("batch", ["cities", "edges"])
def test_country_rule_on_many_points(knowledge_context, knowledge_stack, events, batch):
    if batch == "cities":
        items = [(n, lat, lon) for n, lat, lon in CITIES]  # 34 города
    else:
        items = [
            ("Полюс N", 90, 0),
            ("Полюс S", -90, 0),
            ("Полюс N180", 90, 180),
            ("Полюс S-180", -90, -180),
            ("Экватор 180", 0, 180),
            ("Экватор -180", 0, -180),
            ("Фиджи 180", -17, 180),
            ("Чукотка -180", 66, -179.99),
            ("Чукотка 180", 66, 179.99),
            ("Атлантика", 0, -30),
            ("Тихий", -40, -120),
            ("Индийский", -30, 80),
            ("Саргассово", 30, -60),
            ("У Шетландов", 61.5, -1.5),
            ("Мальта", 35.9, 14.5),
            ("Крит у берега", 35.6, 24.0),
            ("Сеута", 35.89, -5.32),
            ("Ватикан", 41.9, 12.45),
            ("Монако", 43.73, 7.42),
            ("Сан-Марино", 43.94, 12.45),
            ("Сев. Кипр", 35.25, 33.6),
            ("Сомалиленд", 9.56, 44.06),
            ("Антарктида", -80, 0),
            ("Гренландия", 72, -40),
            ("Огненная Земля", -54.8, -68.3),
            ("Шпицберген", 78.2, 15.6),
            ("Гонолулу", 21.3, -157.86),
            ("Сингапур", 1.35, 103.82),
            ("Бахрейн", 26.07, 50.55),
            ("Люксембург", 49.61, 6.13),
        ]
    context = knowledge_context(1920, 1080)
    o = Oracle(context)
    names = ru_names()
    expected = {}
    for name, lat, lon in items:
        cid = o("countryAt", lon, lat)
        expected[name] = names[cid] if cid else None
    ids = placed(knowledge_stack.world, items)
    page = context.new_page()
    page.set_default_timeout(30000)
    with page.expect_response(lambda r: PLACES_API.match(r.url)) as info:
        page.goto(knowledge_stack.url + "/graph?view=globe&t=1750")
    globe_ready(page)
    r = rows(page)
    wrong = []
    for place, (name, _who) in ids.items():
        want = f"{name}, {expected[name]}" if expected[name] else name
        if r[place]["label"] != want:
            wrong.append((name, r[place]["label"], want))
    assert wrong == [], wrong
    assert len(ids) >= 30
    # Блок «Где» на выборке: страна та же, что в строке, или «страна не определена».
    for place, (name, who) in list(ids.items())[:8]:
        block = country_in_panel(page, place, who)
        assert block["country"] == (expected[name] or NO_COUNTRY), (name, block)
    geo_built(events, info.value)
    errors(page)


@req(GEO, COUNTRY, invariant="подпись источника говорит, что границы современные")
def test_source_note_modern_borders(knowledge_context, knowledge_stack, events):
    placed(knowledge_stack.world, PILOT[:1])
    page, response = open_globe(knowledge_context, knowledge_stack, "/graph?view=globe&t=1750")
    text = page.locator(".geo-coast").inner_text().strip()
    assert text == "Границы и береговая линия — современные, Natural Earth"
    geo_built(events, response)


# Независимая проверка оракула: ожидания пилотных городов из спецификации совпадают
# с расчётом по правилу дельты (иначе ошибка в тесте, а не в продукте).
@req(GEO, COUNTRY, invariant="правило страны места на данных world-atlas даёт страны сценариев")
def test_oracle_agrees_with_scenarios(knowledge_context, knowledge_stack, events):
    placed(knowledge_stack.world, PILOT[:1])
    context = knowledge_context(1024, 576)
    o = Oracle(context)
    names = ru_names()
    for name, lat, lon, country in [*PILOT, ("Сиракузы", 37.08, 15.29, "Италия")]:
        assert names[o("countryAt", lon, lat)] == country, name
    assert o("countryAt", -30, 0) is None
    assert o("countryAt", 21.17, 42.66) is None
    page = context.new_page()
    with page.expect_response(lambda r: PLACES_API.match(r.url)) as info:
        page.goto(knowledge_stack.url + "/graph?view=globe&t=1750")
    globe_ready(page)
    geo_built(events, info.value)
