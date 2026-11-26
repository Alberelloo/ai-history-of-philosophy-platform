"""Глобус в историческом режиме (add-historical-polities, задачи 6.1, 6.5, 6.6, 6.8).

Требования дельты ``openspec/changes/add-historical-polities/specs/geo-timeline/spec.md``:
«Исторические границы на глобусе», «Атрибуция исторических границ», «Русские названия
образований» (пометка на глобусе, разметка как текст) и новые сценарии MODIFIED-требований.

Фикстурный артефакт собирается один раз на модуль из GeoJSON теста (``europe.geojson``
фикстуры плюс образования сценариев) и передаётся сервису знаний стенда через
``PHILOGRAPH_POLITIES_DB``. Ожидания считаются независимо: интервал и состав слоя — наивным
фильтром строк GeoJSON, названия — по словарю Wikidata теста, видимая площадь и ширина
подписи — d3-geo на пустой странице теста, число колец на видимой стороне — проекцией теста.
Клиент событий журнала не пишет: серверный якорь — ``knowledge.polities.served`` по
``request_id`` ответа ``/map/polities``, полученного страницей.
"""

# ruff: noqa: E501 — встроенные скрипты страницы и имена инвариантов спецификации

from __future__ import annotations

import copy
import hashlib
import itertools
import json
import re
import threading
import time
from pathlib import Path

import pytest
from playwright.sync_api import expect

from philograph.knowledge.polities_build import build

from ..knowledge.cliopatria_fixture import FIXTURES, FakeWikidata, entities, make_archive, manifest
from ..knowledge.test_polities_layer_spec import expected_name
from .conftest import DIST
from .geo_helpers import (
    CITIES,
    MAX_COUNTRY_LABELS,
    PAD,
    PLACES_API,
    Geo,
    Oracle,
    center_on,
    collisions,
    errors,
    focus_globe,
    geo_built,
    globe,
    globe_ready,
    open_globe,
    outside,
    overlap,
    overlay_obstacles,
    play_button,
    press,
    project,
    scene,
    settle,
    shapes,
    view_arg,
)
from .test_geo_limits import NO_WEBGL
from .test_geo_political import BORDER_PIXEL_JS

req = pytest.mark.req
GEO = "geo-timeline"
HIST = "Исторические границы на глобусе"
ATTR = "Атрибуция исторических границ"
NAMES = "Русские названия образований"
VIEW = "Вид «Глобус» на карте раздела"
POL = "Политическая карта"
LIMITS = "Пределы глобуса"
NOGL = "Глобус без WebGL и без сторонних запросов"
STATES = "Состояния глобуса"
COUNTRY = "Страна места"
POLITIES_API = re.compile(r".*/api/knowledge/v1/map/polities(\?.*)?$")
LIMIT = 9999
SIZES = [(1024, 576), (1366, 768), (1920, 1080)]
CENTERS = [(15, 50), (30, 40)]
ZOOM_STEPS = {1: 0, 2: 3}  # клавиши «-»×10, затем «+»×k: приближение 1 и ≈2 (ряд 1,25^k)
NOTE_TEXT = "Исторические границы не загрузились — показаны современные"
MODERN_TEXT = "Границы и береговая линия — современные, Natural Earth"


# --- фикстура образований ----------------------------------------------------------------


def box(lon0, lat0, lon1, lat1):
    return {
        "type": "Polygon",
        "coordinates": [[[lon0, lat0], [lon1, lat0], [lon1, lat1], [lon0, lat1], [lon0, lat0]]],
    }


def feat(name, start, end, geometry, qid, area):
    return {
        "type": "Feature",
        "properties": {
            "Name": name,
            "Type": "POLITY",
            "FromYear": start,
            "ToYear": end,
            "Wikidata": qid,
            "Area": area,
        },
        "geometry": geometry,
    }


EXTRA = [
    # «Одна подпись на QID»: владение с тем же QID, что у Испанской империи, площадь меньше.
    feat("(Spanish Empire)", 1500, 1700, box(8, 44.5, 10.5, 46), "Q80702", 50000),
    # «Испорченные метки»: метка ru — разметка; на глобусе — буквальный текст.
    feat("Markup Khanate", 1600, 1850, box(60, 52, 75, 62), "Q900030", 400000),
    # «Пометка на глобусе»: крупное образование без русского названия.
    feat("Steppe Horde", 1600, 1850, box(46, 43, 60, 52), "Q900031", 450000),
    # Два крупных образования без QID: подписываются независимо друг от друга.
    feat("Null West", 1600, 1850, box(-10, 24, 4, 33), "", 300000),
    feat("Null East", 1600, 1850, box(6, 24, 20, 33), "", 300000),
]
RECORDS = {
    **entities(),
    "Q900030": {
        "id": "Q900030",
        "labels": {"ru": {"language": "ru", "value": "<b>Империя</b>"}},
        "sitelinks": {},
    },
    "Q900031": {
        "id": "Q900031",
        "labels": {"en": {"language": "en", "value": "Steppe"}},
        "sitelinks": {},
    },
}


def all_features() -> list[dict]:
    fc = json.loads((FIXTURES / "europe.geojson").read_text("utf-8"))
    return fc["features"] + copy.deepcopy(EXTRA)


def valid_rows() -> list[dict]:
    out = []
    for f in all_features():
        p = f["properties"]
        if p["Type"] == "POLITY" and p["Name"] and p["FromYear"] <= p["ToYear"]:
            out.append(p)
    return out


ROWS = valid_rows()


def sid(name: str) -> str:
    return hashlib.sha1(name.encode("utf-8")).hexdigest()[:12]


def active(year: int) -> frozenset[int]:
    return frozenset(i for i, p in enumerate(ROWS) if p["FromYear"] <= year <= p["ToYear"])


def naive_interval(year: int) -> tuple[int, int]:
    s = active(year)
    lo = year
    while lo > -LIMIT and active(lo - 1) == s:
        lo -= 1
    hi = year
    while hi < LIMIT and active(hi + 1) == s:
        hi += 1
    return lo, hi


def naive_ids(year: int) -> set[str]:
    return {sid(ROWS[i]["Name"]) for i in active(year)}


def intervals_in(a: int, b: int) -> int:
    n, y = 0, a
    while y <= b:
        n += 1
        y = naive_interval(y)[1] + 1
    return n


def expected_names(year: int) -> dict[str, tuple[str, str]]:
    """id → (name, name_status) на год по правилу дельты: строка с наибольшим FromYear."""
    lead: dict[str, dict] = {}
    for i in sorted(active(year)):
        p = ROWS[i]
        k = sid(p["Name"])
        if k not in lead or p["FromYear"] > lead[k]["FromYear"]:
            lead[k] = p
    return {k: expected_name(p["Name"], p["Wikidata"], RECORDS)[:2] for k, p in lead.items()}


@pytest.fixture(scope="module")
def artifact(tmp_path_factory) -> Path:
    tmp = tmp_path_factory.mktemp("polities")
    src = tmp / "web.geojson"
    src.write_text(
        json.dumps({"type": "FeatureCollection", "features": all_features()}, ensure_ascii=False),
        encoding="utf-8",
    )
    archive, sha = make_archive(tmp / "src", src)
    out = tmp / "polities.sqlite"
    build(manifest(sha), archive, out, tmp / "labels.ru.json", fetch_json=FakeWikidata(RECORDS))
    return out


@pytest.fixture
def knowledge_stack(request, tmp_path, events, artifact):
    """Стенд ``conftest.knowledge_stack`` с артефактом образований (6.1). Параметр
    ``{"artifact": False}`` — путь к несуществующему файлу (режим 503)."""
    if not (DIST / "index.html").exists():
        pytest.skip("клиент не собран: npm run build в web/")
    from .knowledge_stack import start

    params = getattr(request, "param", {})
    path = artifact if params.get("artifact", True) else tmp_path / "нет" / "polities.sqlite"
    stack = start(tmp_path, DIST, polities_env={"PHILOGRAPH_POLITIES_DB": str(path)})
    yield stack
    stack.stop()
    assert stack.router.unexpected == [], f"запросы шлюза наружу: {stack.router.unexpected}"
    assert stack.llm_calls == [], f"вызовы модели: {stack.llm_calls}"
    assert stack.outside == [], f"запросы браузера не к стенду: {stack.outside}"


def europe_world(world) -> dict[str, str]:
    """30 персон в 30 местах Европы и Средиземноморья, все живы в 1650 и 1800; два места —
    в центрах сценария (15, 50) и (30, 40). Три связи влияния."""
    g = Geo(world)
    centers = {}
    cities = [*CITIES[:28], ("Центр 15,50", 50.0, 15.0), ("Центр 30,40", 40.0, 30.0)]
    people = []
    for i, (name, lat, lon) in enumerate(cities):
        place = g.place(name, lat, lon)
        p = world.person(f"Мыслитель {i:02d}", "1600", "1850")
        g.lived(p, place)
        people.append(p)
        if name.startswith("Центр"):
            centers[(lon, lat)] = place
    for a, b in ((1, 0), (2, 1), (5, 3)):
        g.influence(people[a], people[b])
    return centers


# --- сцена исторического режима ---------------------------------------------------------

POLITY_JS = """() => {
  const svg = document.querySelector('.geo-globe');
  const s = svg.getBoundingClientRect();
  const rel = e => { const r = e.getBoundingClientRect();
    return {x: r.x - s.x, y: r.y - s.y, w: r.width, h: r.height}; };
  const num = v => (v === undefined || v === null || v === '') ? null : Number(v);
  const land = document.querySelector('[data-geo-land]');
  return {
    mode: land?.dataset.mapMode ?? null, from: num(land?.dataset.polityFrom),
    to: num(land?.dataset.polityTo), polities: num(land?.dataset.polities),
    borders: num(land?.dataset.borders), busy: svg.getAttribute('aria-busy'),
    year: Number(svg.dataset.year),
    countries: svg.querySelectorAll('[data-geo-country]').length,
    labels: [...svg.querySelectorAll('[data-geo-polity]')].map(e => ({
      id: e.dataset.geoPolity,
      text: [...e.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join(''),
      html: e.innerHTML, bold: e.querySelector('b') !== null,
      status: e.dataset.nameStatus ?? null, area: num(e.dataset.area), span: num(e.dataset.span),
      fill: e.dataset.fill ?? null, style: getComputedStyle(e).fontStyle,
      title: e.querySelector('title')?.textContent ?? null, box: rel(e)})),
  };
}"""

# Видимая площадь и ширина образования — d3-geo на странице оракула (та же проекция, что
# у глобуса: ортографическая, обрезка по полушарию и кадру).
POLITY_VIS_JS = """([v, feats]) => {
  const proj = d3.geoOrthographic().rotate([-v.lon, -v.lat]).scale(v.R)
    .translate([v.cx, v.cy]).clipExtent([[0, 0], [v.w, v.h]]).precision(0.1);
  const path = d3.geoPath(proj); const out = {};
  for (const f of feats) { const a = path.area(f);
    if (a > 0) { const b = path.bounds(f); out[f.id] = {area: a, span: b[1][0] - b[0][0]}; } }
  return out; }"""


def pscene(page) -> dict:
    return page.evaluate(POLITY_JS)


class Layers:
    """Ответы ``/map/polities``, полученные страницей (JSON и ``request_id``)."""

    def __init__(self, page) -> None:
        self.items: list[tuple[dict | None, int, str | None]] = []
        self.requested: list[str] = []
        page.on(
            "request", lambda r: self.requested.append(r.url) if POLITIES_API.match(r.url) else None
        )
        page.on("response", self._on)

    def _on(self, r) -> None:
        if POLITIES_API.match(r.url):
            try:
                body = r.json() if r.status == 200 else None
            except Exception:
                body = None
            self.items.append((body, r.status, r.headers.get("x-request-id")))

    def drawn(self, ps: dict) -> dict:
        found = [
            b
            for b, s, _ in self.items
            if s == 200 and b and b["valid_from"] == ps["from"] and b["valid_to"] == ps["to"]
        ]
        assert found, ("нарисованного слоя нет среди ответов", ps["from"], ps["to"])
        return found[-1]


def wait_layer(page, year: int | None = None) -> None:
    """Точка синхронизации: нарисован слой, интервал которого содержит текущий год."""
    page.wait_for_function(
        """(y) => { const l = document.querySelector('[data-geo-land]');
            const g = document.querySelector('.geo-globe'); const t = y ?? Number(g.dataset.year);
            return l && l.dataset.mapMode === 'historical' && Number(l.dataset.polityFrom) <= t
              && t <= Number(l.dataset.polityTo) && Number(g.dataset.year) === t; }""",
        arg=year,
        timeout=30000,
    )
    settle(page)


def served_for(events, layers: Layers, year: int | None = None) -> list:
    out = []
    for body, status, rid in layers.items:
        if status != 200 or (year is not None and body["year"] != year):
            continue
        assert rid, "ответ без x-request-id"
        found = events.where("knowledge.polities.served", request_id=rid)
        assert len(found) == 1, (rid, events.names())
        out.append(found[0])
    return out


def ring_count(layer: dict, sc: dict) -> int:
    """Кольца образований слоя хотя бы с одной вершиной на видимом полушарии (проекция теста)."""
    n = 0
    for p in layer["polities"]:
        g = p["geometry"]
        polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
        for poly in polys:
            for ring in poly:
                if any(project(lon, lat, sc)[2] > 1e-9 for lon, lat in ring):
                    n += 1
    return n


def polity_faults(page, o, layers: Layers, *, check_vis: bool = True) -> list:
    """Нарушения правил подписей образований в текущем кадре (H5, R8, правила 1–7)."""
    bad: list = []
    sc = scene(page)
    ps = pscene(page)
    layer = layers.drawn(ps)
    by_id = {p["id"]: p for p in layer["polities"]}
    order = [p["id"] for p in layer["polities"]]
    labels = ps["labels"]
    if ps["mode"] != "historical":
        bad.append(("режим не исторический", ps["mode"]))
    if ps["countries"]:
        bad.append(("подписи стран в историческом режиме", ps["countries"]))
    if len(labels) > MAX_COUNTRY_LABELS:
        bad.append(("подписей больше 24", len(labels)))
    if ps["polities"] != len(layer["polities"]):
        bad.append(
            (
                "data-polities не равно числу образований слоя",
                ps["polities"],
                len(layer["polities"]),
            )
        )
    if (ps["from"], ps["to"]) != naive_interval(ps["year"]):
        bad.append(
            ("интервал не наибольший по фикстуре", ps["from"], ps["to"], naive_interval(ps["year"]))
        )
    if {p["id"] for p in layer["polities"]} != naive_ids(ps["year"]):
        bad.append(("состав слоя не по наивному фильтру", ps["year"]))
    if ps["borders"] != ring_count(layer, sc):
        bad.append(
            (
                "data-borders не равно числу колец на видимой стороне",
                ps["borders"],
                ring_count(layer, sc),
            )
        )
    names = expected_names(ps["year"])
    seen_qid: dict[str, str] = {}
    vis = (
        o.page.evaluate(
            POLITY_VIS_JS,
            [
                view_arg(sc),
                [
                    {"type": "Feature", "id": p["id"], "geometry": p["geometry"]}
                    for p in layer["polities"]
                ],
            ],
        )
        if check_vis
        else {}
    )
    for lab in labels:
        p = by_id.get(lab["id"])
        if p is None:
            bad.append(("подпись не из слоя", lab["id"]))
            continue
        if (lab["text"], lab["status"]) != names[lab["id"]]:
            bad.append(
                ("название не по правилу", lab["id"], lab["text"], lab["status"], names[lab["id"]])
            )
        q = p["wikidata"]
        if q is not None:
            if q in seen_qid:
                bad.append(("две подписи на один QID", q, seen_qid[q], lab["id"]))
            seen_qid[q] = lab["id"]
            first = next(x for x in order if by_id[x]["wikidata"] == q)
            if lab["id"] != first:
                bad.append(("подпись QID не у первого в порядке ответа", q, lab["id"], first))
        if lab["box"]["w"] > lab["span"] + 0.5:
            bad.append(("подпись шире образования", lab["id"], lab["box"]["w"], lab["span"]))
        if lab["fill"] is None and lab["area"] < 1500:
            bad.append(("площадь < 1500 у подписи без data-fill", lab["id"], lab["area"]))
        if check_vis:
            v = vis.get(lab["id"])
            if v is None:
                bad.append(("подпись образования не на видимой стороне", lab["id"]))
            else:
                if abs(lab["area"] - v["area"]) > max(2.0, 0.01 * v["area"]):
                    bad.append(
                        (
                            "data-area не равна видимой площади",
                            lab["id"],
                            lab["area"],
                            round(v["area"], 1),
                        )
                    )
                if abs(lab["span"] - v["span"]) > 1.5:
                    bad.append(
                        (
                            "data-span не равна ширине видимой части",
                            lab["id"],
                            lab["span"],
                            round(v["span"], 1),
                        )
                    )
    rects = [
        (
            "polity",
            lab["id"],
            (
                "r",
                lab["box"]["x"] - PAD,
                lab["box"]["y"] - PAD,
                lab["box"]["x"] + lab["box"]["w"] + PAD,
                lab["box"]["y"] + lab["box"]["h"] + PAD,
            ),
        )
        for lab in labels
    ]
    items = shapes(sc, countries=False) + rects
    for a, b in collisions(items):
        if "polity" in (a[0], b[0]):
            bad.append(("пересечение", a[:2], b[:2]))
    bad += [x for x in outside(sc, rects)]
    for _k, ident, r in rects:
        for ob in overlay_obstacles(page):
            if overlap(r, ob):
                bad.append(("подпись на наложенном элементе вида", ident, ob))
    return bad


def set_zoom(page, z: int) -> None:
    focus_globe(page)
    press(page, "-", 10)
    press(page, "+", ZOOM_STEPS[z])
    settle(page)


def to_year(page, target: int) -> None:
    focus_globe(page)
    cur = int(globe(page).get_attribute("data-year"))
    while cur != target:
        step = 10 if abs(target - cur) >= 10 else 1
        key = (
            ("PageUp" if step == 10 else "]")
            if target > cur
            else ("PageDown" if step == 10 else "[")
        )
        press(page, key)
        cur += step if target > cur else -step
    expect(globe(page)).to_have_attribute("data-year", str(target))


# --- Исторические границы на глобусе ----------------------------------------------------


@req(GEO, HIST, scenario="Подписи не перекрывают медальоны и вид")
@req(
    GEO,
    HIST,
    invariant="H5: 0 пересечений подписей образований между собой, с медальонами, значками, подписями персон и [data-geo-overlay]; все в кадре; не больше 24",
)
@pytest.mark.parametrize(("width", "height"), SIZES)
def test_polity_labels_no_overlap(knowledge_context, knowledge_stack, events, width, height):
    centers = europe_world(knowledge_stack.world)
    context = knowledge_context(width, height, reduced_motion="reduce")
    page = context.new_page()
    page.set_default_timeout(30000)
    layers = Layers(page)
    with page.expect_response(lambda r: PLACES_API.match(r.url)) as info:
        page.goto(knowledge_stack.url + "/graph?view=globe&from=1600&to=1900&t=1650")
    globe_ready(page)
    wait_layer(page, 1650)
    o = Oracle(context)
    frames: dict = {}

    def frame(tag):
        wait_layer(page)
        frames[tag] = polity_faults(page, o, layers)

    frame((1650, "home"))
    to_year(page, 1800)
    frame((1800, "home"))
    for y in (1800, 1650):
        if y != 1800:
            to_year(page, y)
        for c in CENTERS:
            center_on(page, centers[c], c)
            for z in (1, 2):
                set_zoom(page, z)
                frame((y, c, z))
    assert len(frames) == 10
    failed = {str(k): v for k, v in frames.items() if v}
    assert failed == {}, json.dumps(failed, ensure_ascii=False, indent=1, default=str)
    assert served_for(events, layers, 1650) and served_for(events, layers, 1800)
    geo_built(events, info.value)
    errors(page)


@req(GEO, HIST, scenario="Смена года")
@req(GEO, HIST, scenario="Год внутри интервала")
@req(GEO, HIST, scenario="Одна подпись на QID")
@req(GEO, HIST, scenario="Граница на canvas")
@req(GEO, HIST, scenario="Пустой год на глобусе")
@req(GEO, HIST, invariant="H4: набор id подписей и data-polities различаются на 1650 и 1800")
@req(GEO, HIST, invariant="пустой слой — 0 границ и 0 подписей, современные не подставляются")
@req(GEO, NAMES, scenario="Пометка на глобусе")
@req(GEO, NAMES, scenario="Испорченные метки")
@req(GEO, ATTR, scenario="Подпись на глобусе")
@req(GEO, ATTR, scenario="Атрибуция из данных")
@req(GEO, COUNTRY, invariant="подпись источника в историческом режиме: страны мест — современные")
def test_historical_globe_flow(knowledge_context, knowledge_stack, events):
    centers = europe_world(knowledge_stack.world)
    context = knowledge_context(1920, 1080, reduced_motion="reduce")
    page = context.new_page()
    page.set_default_timeout(30000)
    page.add_init_script("window.__marker = 'исходная загрузка';")
    layers = Layers(page)
    with page.expect_response(lambda r: PLACES_API.match(r.url)) as info:
        page.goto(knowledge_stack.url + "/graph?view=globe&from=1600&to=1900&t=1650")
    globe_ready(page)
    wait_layer(page, 1650)
    page.evaluate("window.__marker = 'та же страница'")
    o = Oracle(context)
    bad: dict[str, list] = {}

    # --- исходный вид, 1650 ---
    ps = pscene(page)
    layer = layers.drawn(ps)
    texts = {lab["text"]: lab for lab in ps["labels"]}
    bad["смена года: 1650"] = [
        x
        for x in [
            ps["mode"] != "historical" and ("режим", ps["mode"]),
            not (ps["from"] <= 1650 <= ps["to"]) and ("интервал", ps["from"], ps["to"]),
            "Священная Римская империя" not in texts and ("нет подписи СРИ", sorted(texts)),
            "Речь Посполитая" not in texts and ("нет подписи Речи Посполитой", sorted(texts)),
        ]
        if x
    ] + polity_faults(page, o, layers)
    ids_1650 = {lab["id"] for lab in ps["labels"]}
    polities_1650 = ps["polities"]

    # «Одна подпись на QID»: не больше одной «Испанской империи», и это «Spanish Empire».
    spanish = [lab for lab in ps["labels"] if lab["text"] == "Испанская империя"]
    by_name = {p["original"]: p for p in layer["polities"]}
    assert (
        by_name["Spanish Empire"]["wikidata"] == by_name["(Spanish Empire)"]["wikidata"] == "Q80702"
    )
    assert by_name["Null West"]["wikidata"] is None and by_name["Null East"]["wikidata"] is None
    bad["одна подпись на QID"] = [
        x
        for x in [
            len(spanish) > 1 and ("две подписи «Испанская империя»", [s["id"] for s in spanish]),
            spanish
            and spanish[0]["id"] != sid("Spanish Empire")
            and ("подпись не у Spanish Empire", spanish[0]["id"]),
            sid("(Spanish Empire)") in ids_1650 and ("подпись у владения (Spanish Empire)",),
            not ({sid("Null West"), sid("Null East")} <= ids_1650)
            and ("образования без QID подписаны не оба", sorted(texts)),
        ]
        if x
    ]

    # «Пометка на глобусе» и «Испорченные метки»: ищем кадр, где поставлены обе подписи.
    def name_checks():
        cur = pscene(page)["labels"]
        orig = [lab for lab in cur if lab["id"] == sid("Steppe Horde")]
        ru = sorted(
            (lab for lab in cur if lab["status"] == "ru"),
            key=lambda lab: lab["id"] != sid("Holy Roman Empire"),
        )
        markup = [lab for lab in cur if lab["id"] == sid("Markup Khanate")]
        return orig, ru, markup

    orig, ru, markup = name_checks()
    if not (orig and ru and markup):
        center_on(page, centers[(30, 40)], (30, 40))
        set_zoom(page, 1)
        wait_layer(page)
        orig, ru, markup = name_checks()
    note = []
    if not orig or not ru:
        note.append(
            (
                "GIVEN: подписи original и ru не поставлены ни в одном из двух кадров",
                bool(orig),
                bool(ru),
                [(lab["text"], lab["status"]) for lab in pscene(page)["labels"]],
            )
        )
    else:
        o_, r_ = orig[0], ru[0]
        if o_["status"] != "original" or o_["style"] != "italic":
            note.append(("original: статус/курсив", o_["status"], o_["style"]))
        if o_["title"] != f"{o_['text']} — без русского названия":
            note.append(("original: подсказка", o_["title"]))
        if r_["status"] != "ru" or r_["style"] != "normal" or r_["title"] is not None:
            note.append(("ru: статус/начертание/подсказка", r_["status"], r_["style"], r_["title"]))
    bad["пометка на глобусе"] = note
    bad["испорченные метки"] = (
        [("подпись «<b>Империя</b>» не поставлена",)]
        if not markup
        else [
            x
            for x in [
                markup[0]["text"] != "<b>Империя</b>" and ("текст", markup[0]["text"]),
                markup[0]["bold"] and ("разметка стала элементом <b>",),
                markup[0]["status"] != "ru" and ("статус", markup[0]["status"]),
            ]
            if x
        ]
    )

    # --- атрибуция ---
    src = page.locator("[data-geo-source]")
    text = " ".join(src.inner_text().split())
    s = layer["source"]
    links = src.locator("a").evaluate_all(
        "as => as.map(a => ({href: a.getAttribute('href'), rel: a.getAttribute('rel')}))"
    )
    rect = src.evaluate(
        "e => { const r = e.getBoundingClientRect(); return {x0: r.x, y0: r.y, x1: r.right, y1: r.bottom, w: r.width, h: r.height}; }"
    )
    vp = page.viewport_size
    medal_hits = []
    sc = scene(page)
    box_r = (
        "r",
        rect["x0"] - sc["left"],
        rect["y0"] - sc["top"],
        rect["x1"] - sc["left"],
        rect["y1"] - sc["top"],
    )
    for kind, ident, shp in shapes(sc, countries=False):
        if overlap(box_r, shp):
            medal_hits.append((kind, ident))
    for lab in pscene(page)["labels"]:
        b = lab["box"]
        if overlap(box_r, ("r", b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"])):
            medal_hits.append(("polity", lab["id"]))
    need = [
        "Исторические границы — Cliopatria (Seshat Global History Databank)",
        "Cliopatria",
        "Seshat Global History Databank",
        "Ed Chalstrey",
        "James Bennett",
        "v9.9.9-test",
        "CC BY 4.0",
        "Границы приблизительны: одна из версий",
        "Береговая линия и страны мест — современные, Natural Earth",
        "курсив — без русского названия",
    ]
    bad["атрибуция"] = [("нет текста", n) for n in need if n not in text] + [
        x
        for x in [
            s["version"] != "v9.9.9-test" and ("версия в source", s["version"]),
            s["url"] not in [lk["href"] for lk in links] and ("нет ссылки source.url", links),
            "https://creativecommons.org/licenses/by/4.0/" not in [lk["href"] for lk in links]
            and ("нет ссылки на лицензию", links),
            any("noopener" not in (lk["rel"] or "").split() for lk in links)
            and ("rel без noopener", links),
            not (rect["w"] > 0 and rect["h"] > 0) and ("пустой прямоугольник", rect),
            not (
                rect["x0"] >= -0.5
                and rect["y0"] >= -0.5
                and rect["x1"] <= vp["width"] + 0.5
                and rect["y1"] <= vp["height"] + 0.5
            )
            and ("вне кадра", rect),
            medal_hits and ("подпись источника перекрыта", medal_hits),
        ]
        if x
    ]
    dist_hits = [p.name for p in DIST.rglob("*") if p.is_file() and b"v0.2.2" in p.read_bytes()]
    bad["атрибуция из данных: web/dist"] = dist_hits

    # --- «Год внутри интервала»: 1650 → 1651 клавишей шага, запросов нет ---
    to_year(page, 1650)
    wait_layer(page, 1650)
    before_req = len(layers.requested)
    labels_before = sorted(lab["id"] for lab in pscene(page)["labels"])
    focus_globe(page)
    press(page, "]")
    expect(globe(page)).to_have_attribute("data-year", "1651")
    settle(page)
    settle(page)
    ps = pscene(page)
    bad["год внутри интервала"] = [
        x
        for x in [
            len(layers.requested) != before_req and ("новый запрос", layers.requested[before_req:]),
            not (ps["from"] <= 1651 <= ps["to"]) and ("интервал", ps["from"], ps["to"]),
            sorted(lab["id"] for lab in ps["labels"]) != labels_before and ("подписи изменились",),
        ]
        if x
    ]

    # --- «Граница на canvas»: центр (15, 50), приближение 2, контур Речи Посполитой ---
    center_on(page, centers[(15, 50)], (15, 50))
    set_zoom(page, 2)
    wait_layer(page)
    sc = scene(page)
    v = view_arg(sc)
    plc = next(
        p
        for p in layers.drawn(pscene(page))["polities"]
        if p["original"] == "Polish-Lithuanian Commonwealth"
    )
    ring = plc["geometry"]["coordinates"][0]
    # Восточная сторона (lon = 32): рядом нет контуров других образований 1650 года.
    a, b = next((p, q) for p, q in itertools.pairwise(ring) if p[0] == q[0] == 32)
    mid = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]
    p = o("project", v, *mid)
    p0 = o("project", v, mid[0], mid[1] - 0.2)
    p1 = o("project", v, mid[0], mid[1] + 0.2)
    tx, ty = p1[0] - p0[0], p1[1] - p0[1]
    norm = (tx * tx + ty * ty) ** 0.5
    got = page.evaluate(BORDER_PIXEL_JS, [p, (-ty / norm, tx / norm), 5.0])
    ok = (
        got["dBest"] <= 0.6 * min(got["dLeft"], got["dRight"])
        and got["sideL"] > 10
        and got["sideR"] > 10
        and got["landL"] <= 40
        and got["landR"] <= 40
    )
    bad["граница на canvas"] = [] if ok else [("пиксель контура", got, p)]
    # Обводка «(Spanish Empire)» нарисована: пиксель на её западной стороне — цвета границы.
    sp = next(
        x for x in layers.drawn(pscene(page))["polities"] if x["original"] == "(Spanish Empire)"
    )
    q = o("project", v, 8, 45.25)
    q0, q1 = o("project", v, 8, 45.0), o("project", v, 8, 45.5)
    tx, ty = q1[0] - q0[0], q1[1] - q0[1]
    norm = (tx * tx + ty * ty) ** 0.5
    # Поиск пикселя линии — ±2 px вокруг проекции (у PLC хватает ±1 px).
    wide = BORDER_PIXEL_JS.replace("dx = -1; dx <= 1", "dx = -2; dx <= 2").replace(
        "dy = -1; dy <= 1", "dy = -2; dy <= 2"
    )
    assert wide != BORDER_PIXEL_JS
    got2 = page.evaluate(wide, [q, (-ty / norm, tx / norm), 5.0])
    bad["обводка (Spanish Empire)"] = (
        []
        if got2["dBest"] <= 0.6 * min(got2["dLeft"], got2["dRight"]) and sp["geometry"]
        else [("пиксель", got2)]
    )

    # --- «Смена года» 1650 → 1800 (H4) ---
    navs = page.evaluate("performance.getEntriesByType('navigation').length")
    to_year(page, 1800)
    wait_layer(page, 1800)
    ps = pscene(page)
    ids_1800 = {lab["id"] for lab in ps["labels"]}
    bad["смена года: 1800"] = [
        x
        for x in [
            not (ps["from"] <= 1800 <= ps["to"]) and ("интервал", ps["from"], ps["to"]),
            "Речь Посполитая" in [lab["text"] for lab in ps["labels"]]
            and ("подпись Речи Посполитой на 1800",),
            ids_1800 == ids_1650 and ("набор подписей тот же",),
            ps["polities"] == polities_1650 and ("data-polities тот же", ps["polities"]),
            page.evaluate("window.__marker") != "та же страница" and ("страница перезагружена",),
            page.evaluate("performance.getEntriesByType('navigation').length") != navs
            and ("новая навигация",),
        ]
        if x
    ] + polity_faults(page, o, layers)
    bad["журнал смены года"] = [
        x
        for x in [
            not served_for(events, layers, 1650) and ("нет served 1650",),
            not served_for(events, layers, 1800) and ("нет served 1800",),
        ]
        if x
    ]
    errors(page)

    # --- «Пустой год на глобусе»: t=−3500 ---
    layers.items.clear()
    with page.expect_response(lambda r: POLITIES_API.match(r.url)) as pinfo:
        page.goto(knowledge_stack.url + "/graph?view=globe&from=-4000&to=1900&t=-3500")
    globe_ready(page)
    page.locator("[data-geo-land][data-map-mode='historical']").wait_for()
    settle(page)
    ps = pscene(page)
    sc = scene(page)
    rid = pinfo.value.headers.get("x-request-id")
    ev = events.where("knowledge.polities.served", request_id=rid)
    bad["пустой год"] = [
        x
        for x in [
            ps["mode"] != "historical" and ("режим", ps["mode"]),
            ps["polities"] != 0 and ("data-polities", ps["polities"]),
            ps["borders"] != 0 and ("data-borders", ps["borders"]),
            ps["labels"] and ("подписи образований", len(ps["labels"])),
            ps["countries"] != 0 and ("подписи стран", ps["countries"]),
            sc["persons"] and ("медальоны в −3500 (никто не жив)", len(sc["persons"])),
            page.get_by_text("В 3500 году до н. э. на карте никого нет").count() == 0
            and page.get_by_text(re.compile(r"году на карте никого нет")).count() == 0
            and ("нет пометки пустого года",),
            (len(ev) != 1 or ev[0]["polities"] != 0)
            and ("served polities=0", [e.fields for e in ev]),
        ]
        if x
    ]
    geo_built(events, info.value)
    errors(page)
    failed = {k: v for k, v in bad.items() if v}
    assert failed == {}, json.dumps(failed, ensure_ascii=False, indent=1, default=str)


@req(GEO, HIST, scenario="Медальоны не зависят от режима")
@req(GEO, NOGL, scenario="WebGL недоступен")
def test_medals_independent_of_mode(knowledge_context, knowledge_stack, events):
    europe_world(knowledge_stack.world)
    path = "/graph?view=globe&from=1600&to=1900&t=1650"

    def open_(init=None, polities_503=False):
        context = knowledge_context(1920, 1080, reduced_motion="reduce")
        if init:
            context.add_init_script(init)
        page = context.new_page()
        page.set_default_timeout(30000)
        if polities_503:
            page.route(
                POLITIES_API,
                lambda r: r.fulfill(
                    status=503,
                    content_type="application/json",
                    body='{"detail": "Исторические границы недоступны", "kind": "polities_unavailable"}',
                ),
            )
        layers = Layers(page)
        with page.expect_response(lambda r: PLACES_API.match(r.url)) as info:
            page.goto(knowledge_stack.url + path)
        globe_ready(page)
        if not polities_503:
            wait_layer(page, 1650)
        expect(page.locator("canvas[data-geo-land][data-drawn='true']")).to_have_count(1)
        settle(page)
        sc = scene(page)
        marks = (
            sorted((p["id"], p["x"], p["y"]) for p in sc["persons"]),
            sorted((lk["id"], lk["d"]) for lk in sc["links"]),
        )
        return page, layers, info.value, marks, pscene(page)

    page_a, layers_a, resp_a, marks_a, ps_a = open_()
    page_b, _, _, marks_b, ps_b = open_(init=NO_WEBGL)
    assert page_b.evaluate("document.createElement('canvas').getContext('webgl')") is None
    page_c, _, _, marks_c, ps_c = open_(polities_503=True)
    assert ps_a["mode"] == "historical" and ps_c["mode"] == "modern"
    assert marks_a[0] and marks_a[1], marks_a
    # Медальоны и связи одинаковы в обоих режимах (число и data-x/data-y).
    assert marks_c == marks_a
    # Без WebGL (исторический режим): те же медальоны, связи, подписи образований, границы.
    assert marks_b == marks_a
    assert ps_b["mode"] == "historical" and ps_b["borders"] > 0
    assert sorted(lab["id"] for lab in ps_b["labels"]) == sorted(
        lab["id"] for lab in ps_a["labels"]
    )
    assert ps_c["borders"] > 0 and ps_c["countries"] > 0
    assert served_for(events, layers_a, 1650)
    geo_built(events, resp_a)
    for p in (page_a, page_b, page_c):
        errors(p)


@req(GEO, HIST, scenario="Проигрывание")
@req(
    GEO,
    HIST,
    invariant="при проигрывании одновременно не больше одного запроса /map/polities; ответ не своего года не рисуется",
)
@req(GEO, NOGL, scenario="Только свой адрес")
def test_playback_one_request_at_a_time(knowledge_context, knowledge_stack, events):
    europe_world(knowledge_stack.world)
    knowledge_stack.polities_delay = 0.3
    context = knowledge_context(1366, 768)
    context.add_init_script(
        """window.__pol = {open: 0, max: 0, total: 0};
        const __f = window.fetch;
        window.fetch = function (input, init) {
          const u = typeof input === 'string' ? input : (input && input.url) || String(input);
          if (!u.includes('/map/polities')) return __f.apply(this, arguments);
          const s = window.__pol; s.open++; s.total++; s.max = Math.max(s.max, s.open);
          return __f.apply(this, arguments).then(r => r.clone().arrayBuffer().then(() => r))
            .finally(() => { s.open--; });
        };"""
    )
    page = context.new_page()
    page.set_default_timeout(30000)
    layers = Layers(page)
    inflight = {"now": 0, "max": 0}

    def on_req(r):
        if POLITIES_API.match(r.url):
            inflight["now"] += 1
            inflight["max"] = max(inflight["max"], inflight["now"])

    def on_done(r):
        if POLITIES_API.match(r.url):
            inflight["now"] -= 1

    page.on("request", on_req)
    page.on("requestfinished", on_done)
    page.on("requestfailed", on_done)
    with page.expect_response(lambda r: PLACES_API.match(r.url)) as info:
        page.goto(knowledge_stack.url + "/graph?view=globe&from=1600&to=1900&t=1600")
    globe_ready(page)
    wait_layer(page, 1600)
    # «Только свой адрес»: поворот, наведение на медальон, смена года за пределы интервала.
    focus_globe(page)
    press(page, "Shift+ArrowRight", 2)
    settle(page)
    press(
        page, "Shift+ArrowLeft", 2
    )  # обратно: при большом исходном приближении Европа уходит из кадра
    settle(page)
    first = page.locator("[data-geo-person][data-hidden='false']").first
    first.hover()
    to_year(page, 1750)
    wait_layer(page, 1750)
    to_year(page, 1600)
    wait_layer(page, 1600)
    page.locator(".geo-yearbar__speed").get_by_role("button", name="×2").click()
    play_button(page).click()
    expect(play_button(page)).to_have_text("Пауза")
    expect(play_button(page)).to_have_text("Играть", timeout=90000)
    wait_layer(page)
    pol = page.evaluate("window.__pol")
    ps = pscene(page)
    assert pol["total"] >= 2, pol
    assert pol["max"] <= 1, pol
    assert inflight["max"] <= 1, inflight
    assert len(layers.requested) <= intervals_in(1600, 1900), (
        len(layers.requested),
        intervals_in(1600, 1900),
    )
    assert ps["from"] <= ps["year"] <= ps["to"], ps
    assert ps["year"] == 1900
    # Только свой адрес: все запросы — к стенду (ловушка outside — в конце фикстуры);
    # на каждый ответ слоя — событие served.
    assert all(
        u.startswith(knowledge_stack.url + "/api/knowledge/v1/map/polities")
        for u in layers.requested
    )
    assert len(served_for(events, layers)) == len([1 for _, s, _ in layers.items if s == 200])
    geo_built(events, info.value)
    errors(page)


# --- Состояния глобуса ---------------------------------------------------------------


@req(GEO, STATES, scenario="Слой образований задержан")
def test_polities_delayed(knowledge_context, knowledge_stack, events):
    europe_world(knowledge_stack.world)
    gate = threading.Event()
    knowledge_stack.polities_gate = gate
    context = knowledge_context(1366, 768)
    page = context.new_page()
    page.set_default_timeout(30000)
    layers = Layers(page)
    try:
        with page.expect_response(lambda r: PLACES_API.match(r.url)) as info:
            page.goto(knowledge_stack.url + "/graph?view=globe&from=1600&to=1900&t=1650")
        expect(page.locator("canvas[data-geo-land][data-drawn='true']")).to_have_count(1)
        page.evaluate("document.fonts.ready.then(() => true)")
        settle(page)
        assert layers.requested, "запрос /map/polities не ушёл"
        ps = pscene(page)
        assert ps["mode"] == "modern", ps["mode"]
        assert ps["borders"] > 0
        assert ps["busy"] == "true"
    finally:
        gate.set()
    globe_ready(page)
    wait_layer(page, 1650)
    ps = pscene(page)
    assert ps["mode"] == "historical"
    assert ps["from"] <= 1650 <= ps["to"]
    assert ps["busy"] == "false"
    assert len(served_for(events, layers, 1650)) == 1
    geo_built(events, info.value)
    errors(page)


@req(GEO, STATES, scenario="Ошибка слоя образований")
def test_polities_error_then_ok(knowledge_context, knowledge_stack, events):
    europe_world(knowledge_stack.world)
    context = knowledge_context(1366, 768)
    page = context.new_page()
    page.set_default_timeout(30000)
    calls = {"n": 0}

    def route(r):
        calls["n"] += 1
        if calls["n"] == 1:
            r.fulfill(status=500, content_type="application/json", body='{"detail": "сбой"}')
        else:
            r.continue_()

    page.route(POLITIES_API, route)
    layers = Layers(page)
    with page.expect_response(lambda r: PLACES_API.match(r.url)) as info:
        page.goto(knowledge_stack.url + "/graph?view=globe&from=1600&to=1900&t=1650")
    globe_ready(page)
    note = page.locator("[data-geo-polities-note]")
    expect(note).to_have_text(NOTE_TEXT)
    assert note.get_attribute("data-geo-overlay") is not None
    ps = pscene(page)
    sc = scene(page)
    assert ps["mode"] == "modern"
    assert len(sc["persons"]) == 30
    errors(page)
    to_year(page, 1800)
    wait_layer(page, 1800)
    ps = pscene(page)
    assert ps["mode"] == "historical"
    expect(note).to_have_count(0)
    assert calls["n"] >= 2
    assert served_for(events, layers, 1800)
    geo_built(events, info.value)
    errors(page)


@pytest.mark.parametrize("knowledge_stack", [{"artifact": False}], indirect=True)
@req(GEO, STATES, scenario="Артефакта нет")
@req(
    GEO,
    POL,
    invariant="в современном режиме data-map-mode=modern, границы государств и подписи стран",
)
@req(GEO, COUNTRY, invariant="подпись источника в современном режиме: границы современные")
def test_no_artifact_modern(knowledge_context, knowledge_stack, events):
    europe_world(knowledge_stack.world)
    page, response = open_globe(
        knowledge_context, knowledge_stack, "/graph?view=globe&from=1600&to=1900&t=1650"
    )
    ps = pscene(page)
    assert ps["mode"] == "modern"
    assert ps["busy"] == "false"
    assert ps["borders"] > 0 and ps["countries"] > 0
    assert ps["labels"] == []
    assert page.locator("[data-geo-source]").inner_text().strip() == MODERN_TEXT
    expect(page.locator("[data-geo-polities-note]")).to_have_count(0)
    reasons = [e["reason"] for e in events.of("knowledge.polities.unavailable")]
    assert reasons and set(reasons) == {"missing"}, reasons
    events.assert_none("knowledge.polities.served")
    geo_built(events, response)
    errors(page)


# --- MODIFIED: хронология и вес фрагмента -------------------------------------------


@req(GEO, VIEW, scenario="Хронология не грузит глобус")
@req(GEO, LIMITS, scenario="Вес фрагмента")
def test_chronology_no_polities_and_fragment_weight(knowledge_context, knowledge_stack, events):
    import gzip

    europe_world(knowledge_stack.world)
    context = knowledge_context(1920, 1080)
    page = context.new_page()
    page.set_default_timeout(30000)
    urls: list[str] = []
    page.on("request", lambda r: urls.append(r.url))
    page.goto(knowledge_stack.url + "/graph")
    page.locator(".map-canvas").wait_for()
    settle(page)
    page.locator(".map-search input").fill("Мыслитель")
    page.keyboard.press("Escape")
    settle(page)
    assert [u for u in urls if POLITIES_API.match(u)] == []
    assert [u for u in urls if PLACES_API.match(u)] == []
    events.assert_none("knowledge.polities.served")
    events.assert_none("knowledge.geo.built")
    after: list = []
    page.on("response", lambda r: after.append(r))
    layers = Layers(page)
    with page.expect_response(lambda r: PLACES_API.match(r.url)):
        page.locator(".map-view-switch").get_by_role("button", name="Глобус").click()
    globe_ready(page)
    wait_layer(page)
    page.wait_for_load_state("networkidle")
    total, sizes, polities = 0, {}, 0
    for r in after:
        if POLITIES_API.match(r.url):
            polities += 1
            continue
        if "/portraits/" in r.url or r.request.resource_type == "image":
            continue
        packed = len(gzip.compress(r.body(), compresslevel=9))
        sizes[r.url.rsplit("/", 1)[-1][:40]] = packed
        total += packed
    assert polities >= 1
    assert any("GlobeView" in u for u in sizes), sizes
    assert total <= 150 * 1024, (total, sizes)
    assert served_for(events, layers)
    errors(page)


_ = time  # время стенда меряет 8.4 отдельным скриптом
