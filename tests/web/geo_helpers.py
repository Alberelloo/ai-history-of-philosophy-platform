"""Общее для браузерных тестов глобуса (geo-timeline; rework-globe-political-map, задача 5.1).

Данные задаёт каждый тест сам через ``stack.world`` (настоящий сервис знаний, ``knowledge_stack``).
Ожидания берутся из дельты ``openspec/changes/rework-globe-political-map/specs/geo-timeline``.
Клиент событий журнала не пишет: серверный якорь — ``knowledge.geo.built`` по ``request_id``
ответа ``/map/places``, полученного страницей (``geo_built``).

Независимый расчёт (иначе проверка атрибутов, которые сообщает сам код, тавтологична):

- центры кругов и прямоугольники текста — ``getBoundingClientRect`` элементов (``scene``);
- проекция мест — ортографическая формула в этом модуле (``project``) по ``data-center``
  и кругу обода ``.geo-rim__inner`` (радиус — масштаб проекции);
- площадь, ширина видимой части стран, линии границ, страна точки — d3-geo и topojson-client
  из ``web/node_modules`` на отдельной пустой странице теста (``Oracle``) по данным
  ``world-atlas/countries-110m.json``, а не функциями кода продукта.

Геометрия пересечений — дословно из «Медальоны философов»: маркеры — круги (``MEDAL`` 26,
``EVENT_MARK`` 10), текст — прямоугольник с полем 1,5 px, пересечение — глубина больше 0,5 px.
"""

# ruff: noqa: E501 — встроенные скрипты страницы

from __future__ import annotations

import itertools
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from philograph.knowledge.dates import parse
from philograph.knowledge.statements import Attribution, Provenance

ROOT = Path(__file__).resolve().parents[2]
NODE = ROOT / "web" / "node_modules"
WORLD_JSON = NODE / "world-atlas" / "countries-110m.json"
RU_JSON = ROOT / "web" / "src" / "map" / "geo" / "countries.ru.json"

PLACES_API = re.compile(r".*/api/knowledge/v1/map/places(\?.*)?$")
MAP_API = re.compile(r".*/api/knowledge/v1/map(\?.*)?$")
GEO_BUILT = "knowledge.geo.built"
WD = [Attribution("source", "wikidata:Q1", place="https://www.wikidata.org/wiki/Q1")]
SOURCED = {
    "attributions": WD,
    "provenance": Provenance("imported", run_id="geo_t"),
    "status": "sourced",
}
GENERATED = {"attributions": WD, "provenance": Provenance("generated"), "status": "generated"}

# Константы дельты (числа из текста требований, не из кода).
MEDAL = 26
MEDAL_GAP = 4
EVENT_MARK = 10
TOUCH = 0.5
PAD = 1.5
MAX_SHIFT = 3 * (MEDAL + MEDAL_GAP)
COUNTRY_MIN_AREA = 1500
MAX_COUNTRY_LABELS = 24
MAX_PERSONS = 600
MAX_PORTRAITS = 60
SIZES = [(1024, 576), (1366, 768), (1920, 1080)]
EPS = 0.05  # округление атрибутов до 0,01 px и субпиксели прямоугольников

# Города Европы и Средиземноморья (координаты — общеизвестные, для данных тестов).
CITIES: list[tuple[str, float, float]] = [
    ("Афины", 37.98, 23.73),
    ("Рим", 41.90, 12.50),
    ("Париж", 48.86, 2.35),
    ("Лондон", 51.51, -0.13),
    ("Эдинбург", 55.95, -3.19),
    ("Амстердам", 52.37, 4.90),
    ("Берлин", 52.52, 13.40),
    ("Кёнигсберг", 54.71, 20.51),
    ("Вена", 48.21, 16.37),
    ("Прага", 50.08, 14.44),
    ("Мадрид", 40.42, -3.70),
    ("Лиссабон", 38.72, -9.14),
    ("Стокгольм", 59.33, 18.07),
    ("Копенгаген", 55.68, 12.57),
    ("Варшава", 52.23, 21.01),
    ("Женева", 46.20, 6.14),
    ("Флоренция", 43.77, 11.26),
    ("Неаполь", 40.85, 14.27),
    ("Александрия", 31.20, 29.92),
    ("Константинополь", 41.01, 28.98),
    ("Иерусалим", 31.77, 35.21),
    ("Карфаген", 36.85, 10.32),
    ("Сиракузы", 37.08, 15.29),
    ("Милет", 37.53, 27.28),
    ("Кордова", 37.88, -4.78),
    ("Лейпциг", 51.34, 12.37),
    ("Йена", 50.93, 11.59),
    ("Оксфорд", 51.75, -1.26),
    ("Дублин", 53.35, -6.26),
    ("Брюссель", 50.85, 4.35),
    ("Мюнхен", 48.14, 11.58),
    ("Марсель", 43.30, 5.37),
    ("Будапешт", 47.50, 19.04),
    ("Белград", 44.79, 20.45),
]


@dataclass
class Geo:
    """Построитель мест и размещений поверх ``World`` стенда."""

    world: Any

    @property
    def statements(self):
        return self.world.statements

    def place(self, name: str, lat: float | None = None, lon: float | None = None) -> str:
        entity = self.world.entities.create("place", [("ru", name, "primary")])
        if lat is not None:
            self.statements.add(entity, "coordinates", value={"lat": lat, "lon": lon}, **SOURCED)
        return entity

    def coords(self, place: str, lat: float, lon: float) -> str:
        return self.statements.add(place, "coordinates", value={"lat": lat, "lon": lon}, **SOURCED)

    def lived(
        self,
        who: str,
        where: str,
        role: str | None = None,
        when: str | None = None,
        *,
        generated: bool = False,
    ) -> str:
        qualifiers: dict[str, Any] = {}
        if role:
            qualifiers["place_role"] = role
        if when:
            qualifiers["time"] = parse(when).to_json()
        return self.statements.add(
            who,
            "lived_in",
            obj=where,
            qualifiers=qualifiers,
            **(GENERATED if generated else SOURCED),
        )

    def happened(self, event: str, where: str) -> str:
        return self.statements.add(event, "happened_in", obj=where, **SOURCED)

    def influence(self, student: str, teacher: str, *, generated: bool = False) -> str:
        if generated:
            return self.statements.add(student, "influenced_by", obj=teacher, **GENERATED)
        return self.world.relate(student, "influenced_by", teacher)


def crowd(
    world,
    cities: list[tuple[str, float, float]],
    per_place: int,
    *,
    born="1700",
    died="1780",
    prefix="Мыслитель",
) -> dict[str, list[str]]:
    """``per_place`` персон в каждом из ``cities``; все живы в 1700–1780. Место → персоны."""
    g = Geo(world)
    out: dict[str, list[str]] = {}
    for c, (name, lat, lon) in enumerate(cities):
        place = g.place(name, lat, lon)
        out[place] = []
        for i in range(per_place):
            p = world.person(f"{prefix} {c:02d}-{i:02d}", born, died)
            g.lived(p, place)
            out[place].append(p)
    return out


# --- страница ----------------------------------------------------------------------------


def settle(page) -> None:
    page.evaluate("document.fonts.ready.then(() => true)")
    page.evaluate(
        "new Promise(r => requestAnimationFrame(() => requestAnimationFrame(() => r(true))))"
    )


def globe_ready(page) -> None:
    page.locator(".geo-globe[aria-busy='false']").wait_for()
    settle(page)


def open_globe(make, stack, path: str, *, width=1920, height=1080, before=None, **options):
    """Страница глобуса и ответ ``/map/places``, полученный ею."""
    context = make(width, height, **options)
    page = context.new_page()
    page.set_default_timeout(30000)
    if before is not None:
        before(page)
    with page.expect_response(lambda r: PLACES_API.match(r.url)) as info:
        page.goto(stack.url + path)
    globe_ready(page)
    return page, info.value


def open_globe_map(make, stack, path: str, *, before_extra=None, **kw):
    """Как ``open_globe``, плюс JSON ответа ``/map``, полученного страницей."""
    holder: dict[str, Any] = {}

    def before(page):
        page.on("response", lambda r: holder.setdefault("map", r) if MAP_API.match(r.url) else None)
        if before_extra is not None:
            before_extra(page)

    page, response = open_globe(make, stack, path, before=before, **kw)
    return page, response, holder["map"].json()


def geo_built(events, response):
    rid = response.headers.get("x-request-id")
    assert rid, response.url
    found = events.where(GEO_BUILT, request_id=rid)
    assert len(found) == 1, (rid, events.names())
    return found[0]


def globe(page):
    return page.locator(".geo-globe")


def year(page) -> int:
    return int(globe(page).get_attribute("data-year"))


def center(page) -> str:
    return globe(page).get_attribute("data-center")


def zoom(page) -> str:
    return globe(page).get_attribute("data-zoom")


def address(page) -> tuple[str, dict[str, str]]:
    url = urlparse(page.url)
    return url.path, {k: v[0] for k, v in parse_qs(url.query).items()}


SCENE_JS = """() => {
  const svg = document.querySelector('.geo-globe');
  const s = svg.getBoundingClientRect();
  const rel = e => { const r = e.getBoundingClientRect();
    return {x: r.x - s.x, y: r.y - s.y, w: r.width, h: r.height,
            cx: r.x - s.x + r.width / 2, cy: r.y - s.y + r.height / 2}; };
  const rim = rel(svg.querySelector('.geo-rim__inner'));
  const num = v => (v === undefined || v === null || v === '') ? null : Number(v);
  const land = document.querySelector('[data-geo-land]');
  const all = q => [...svg.querySelectorAll(q)];
  return {
    w: s.width, h: s.height, left: s.x, top: s.y, cx: rim.cx, cy: rim.cy, R: rim.w / 2,
    center: svg.dataset.center, zoom: Number(svg.dataset.zoom), year: Number(svg.dataset.year),
    borders: num(land?.dataset.borders), countryCount: num(land?.dataset.countries),
    persons: all('[data-geo-person]').map(e => ({
      id: e.dataset.geoPerson, place: e.dataset.place, hidden: e.dataset.hidden,
      packed: e.dataset.packed, x: num(e.dataset.x), y: num(e.dataset.y), age: num(e.dataset.age),
      unverified: e.dataset.unverified, role: e.dataset.role ?? null, dim: e.dataset.dim ?? null,
      opacity: Number(getComputedStyle(e).opacity), children: e.childElementCount,
      display: getComputedStyle(e).display, box: rel(e),
      image: e.querySelector('image')?.getAttribute('href') ?? null,
      mono: e.querySelector('text')?.textContent ?? null})),
    more: all('[data-geo-more]').map(e => ({
      places: (e.dataset.places || '').split(' ').filter(Boolean), count: num(e.dataset.count),
      hidden: e.dataset.hidden, x: num(e.dataset.x), y: num(e.dataset.y), box: rel(e),
      children: e.childElementCount, text: e.textContent})),
    events: all('[data-geo-event]').map(e => ({
      id: e.dataset.geoEvent, place: e.dataset.place, hidden: e.dataset.hidden,
      x: num(e.dataset.x), y: num(e.dataset.y), age: num(e.dataset.age),
      role: e.dataset.role ?? null, dim: e.dataset.dim ?? null, children: e.childElementCount,
      box: rel(e)})),
    names: all('[data-geo-name]').map(e => ({id: e.dataset.geoName, text: e.textContent,
      html: e.innerHTML, box: rel(e), cls: e.getAttribute('class')})),
    countries: all('[data-geo-country]').map(e => ({id: e.dataset.geoCountry,
      text: e.textContent, area: num(e.dataset.area), span: num(e.dataset.span),
      ax: num(e.getAttribute('x')), ay: num(e.getAttribute('y')), box: rel(e)})),
    links: all('[data-geo-link]').map(e => ({id: e.dataset.geoLink, from: e.dataset.from,
      to: e.dataset.to, hidden: e.dataset.hidden, status: e.dataset.status,
      generated: e.dataset.generated, age: num(e.dataset.age), role: e.dataset.role ?? null,
      dim: e.dataset.dim ?? null, opacity: Number(getComputedStyle(e).opacity),
      paths: e.querySelectorAll('path').length,
      d: e.querySelector('path.geo-link__arc')?.getAttribute('d') ?? null,
      arrow: e.querySelector('path.geo-link__arrow')?.getAttribute('d') ?? null,
      arrows: e.querySelectorAll('path.geo-link__arrow').length})),
    anchors: all('[data-geo-anchor]').map(e => ({id: e.dataset.geoAnchor,
      r: num(e.getAttribute('r')), box: rel(e)})),
    places_attr: all('[data-geo-place]:not([data-geo-person]):not([data-geo-event])').length,
  };
}"""


def scene(page) -> dict[str, Any]:
    return page.evaluate(SCENE_JS)


def persons(page) -> dict[str, dict[str, Any]]:
    return {p["id"]: p for p in scene(page)["persons"]}


def links(page) -> dict[str, dict[str, Any]]:
    return {lk["id"]: lk for lk in scene(page)["links"]}


def drawn(p: dict) -> bool:
    return p["hidden"] == "false" and p.get("packed", "false") == "false"


def rows(page) -> dict[str, dict[str, Any]]:
    """Строки «Места в году»: id места → название, люди и события (кнопки), «не проверено»."""
    return page.evaluate(
        """() => Object.fromEntries([...document.querySelectorAll('[data-geo-row]')].map(e => [
            e.dataset.geoRow, {
              label: e.querySelector('.geo-row__name')?.textContent ?? '',
              people: Number(e.dataset.people),
              who: [...e.querySelectorAll('.geo-row__who button')].map(b => b.textContent.trim()),
              unverified: e.textContent.includes('не проверено'),
              text: e.textContent,
            }]))"""
    )


def row_order(page) -> list[str]:
    return page.locator("[data-geo-row]").evaluate_all("es => es.map(e => e.dataset.geoRow)")


def where_is(page, name: str) -> list[str]:
    """Места, в строках которых есть кнопка ``name``."""
    return [pid for pid, r in rows(page).items() if name in r["who"]]


def where_block(page) -> dict[str, str] | None:
    return page.evaluate(
        """() => { const w = document.querySelector('[data-geo-where]'); if (!w) return null;
            const t = q => w.querySelector(q)?.textContent ?? null;
            return {place: t('[data-geo-where-place]'), country: t('[data-geo-where-country]'),
                    role: t('[data-geo-where-role]'), years: t('[data-geo-where-years]'),
                    text: w.textContent}; }"""
    )


def press(page, key: str, times: int = 1) -> None:
    for _ in range(times):
        page.keyboard.press(key)


def focus_globe(page) -> None:
    globe(page).focus()


def play_button(page):
    return page.locator(".geo-yearbar__play")


def live(page) -> str:
    return page.locator("[data-geo-live]").inner_text()


def errors(page) -> None:
    assert page.context.errors == [], page.context.errors
    assert page.evaluate("window.__consoleErrors") == []


def center_on(page, place_id: str, lonlat: tuple[float, float] | None = None) -> None:
    """Центр вида на место через строку списка (правило «Текстовая альтернатива»)."""
    page.locator(f"[data-geo-row='{place_id}'] .geo-row__place").click()
    if lonlat is not None:
        page.locator(f".geo-globe[data-center='{fmt(lonlat[0])},{fmt(lonlat[1])}']").wait_for()
    settle(page)


def fmt(x: float) -> str:
    r = round(x, 2)
    return str(int(r)) if r == int(r) else f"{r:g}"


RU_PLACES = ("место", "места", "мест")
RU_PEOPLE = ("человек", "человека", "человек")


def plural(n: int, forms: tuple[str, str, str]) -> str:
    """Русское склонение по числу: 1 место, 2 места, 5 мест; 11–14 — «мест»."""
    if n % 10 == 1 and n % 100 != 11:
        return forms[0]
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return forms[1]
    return forms[2]


def summary_counts(page) -> tuple[int, int]:
    """Число мест и людей по списку «Места в году»."""
    r = rows(page)
    return len(r), sum(v["people"] for v in r.values())


# --- независимая проекция ---------------------------------------------------------------


def view_of(sc: dict) -> tuple[float, float]:
    lon, lat = (float(v) for v in sc["center"].split(","))
    return lon, lat


def project(lon: float, lat: float, sc: dict) -> tuple[float, float, float]:
    """Ортографическая проекция места на экран вида ``sc``: (x, y, cos углового расстояния)."""
    lon0, lat0 = view_of(sc)
    la, lo, la0 = math.radians(lat), math.radians(lon - lon0), math.radians(lat0)
    x = math.cos(la) * math.sin(lo)
    y = math.cos(la0) * math.sin(la) - math.sin(la0) * math.cos(la) * math.cos(lo)
    cosc = math.sin(la0) * math.sin(la) + math.cos(la0) * math.cos(la) * math.cos(lo)
    return sc["cx"] + sc["R"] * x, sc["cy"] - sc["R"] * y, cosc


# --- геометрия пересечений (дельта, «Медальоны философов») -----------------------------


def shapes(sc: dict, *, countries: bool = True) -> list[tuple[str, str, tuple]]:
    """Нарисованные фигуры: ("c", x, y, r) для маркеров по прямоугольнику элемента,
    ("r", x0, y0, x1, y1) для текста с полем 1,5 px."""
    out: list[tuple[str, str, tuple]] = []
    for p in sc["persons"]:
        if drawn(p):
            out.append(("medal", p["id"], ("c", p["box"]["cx"], p["box"]["cy"], MEDAL / 2)))
    for i, b in enumerate(sc["more"]):
        if b["hidden"] == "false":
            out.append(("more", str(i), ("c", b["box"]["cx"], b["box"]["cy"], MEDAL / 2)))
    for e in sc["events"]:
        if e["hidden"] == "false":
            out.append(("event", e["id"], ("c", e["box"]["cx"], e["box"]["cy"], EVENT_MARK / 2)))
    for n in sc["names"]:
        b = n["box"]
        out.append(
            (
                "name",
                n["id"],
                ("r", b["x"] - PAD, b["y"] - PAD, b["x"] + b["w"] + PAD, b["y"] + b["h"] + PAD),
            )
        )
    if countries:
        for c in sc["countries"]:
            b = c["box"]
            out.append(
                (
                    "country",
                    c["id"],
                    ("r", b["x"] - PAD, b["y"] - PAD, b["x"] + b["w"] + PAD, b["y"] + b["h"] + PAD),
                )
            )
    return out


def _rect_dist(cx: float, cy: float, r: tuple) -> float:
    nx = min(max(cx, r[1]), r[3])
    ny = min(max(cy, r[2]), r[4])
    return math.hypot(nx - cx, ny - cy)


def overlap(a: tuple, b: tuple) -> bool:
    """Пересечение двух фигур глубже ``TOUCH`` — дословно правило дельты."""
    if a[0] == "c" and b[0] == "c":
        return math.hypot(a[1] - b[1], a[2] - b[2]) < a[3] + b[3] - TOUCH
    if a[0] == "r" and b[0] == "r":
        ox = min(a[3], b[3]) - max(a[1], b[1])
        oy = min(a[4], b[4]) - max(a[2], b[2])
        return ox > TOUCH and oy > TOUCH
    c, r = (a, b) if a[0] == "c" else (b, a)
    return _rect_dist(c[1], c[2], r) < c[3] - TOUCH


def collisions(items: list[tuple[str, str, tuple]]) -> list[tuple]:
    found = []
    for (ka, ia, a), (kb, ib, b) in itertools.combinations(items, 2):
        if overlap(a, b):
            found.append(((ka, ia, a), (kb, ib, b)))
    return found


def outside(sc: dict, items: list[tuple[str, str, tuple]]) -> list[tuple]:
    """Фигуры не в кадре (целиком в прямоугольнике вида) или маркеры с центром вне круга."""
    bad = []
    for kind, ident, s in items:
        if s[0] == "c":
            x0, y0, x1, y1 = s[1] - s[3], s[2] - s[3], s[1] + s[3], s[2] + s[3]
            if math.hypot(s[1] - sc["cx"], s[2] - sc["cy"]) > sc["R"] + EPS:
                bad.append((kind, ident, "вне круга", s))
        else:
            x0, y0, x1, y1 = s[1] + PAD, s[2] + PAD, s[3] - PAD, s[4] - PAD
        if x0 < -EPS or y0 < -EPS or x1 > sc["w"] + EPS or y1 > sc["h"] + EPS:
            bad.append((kind, ident, "вне кадра", s))
    return bad


# --- дуги ---------------------------------------------------------------------------------

NUM = r"-?\d+(?:\.\d+)?(?:e-?\d+)?"


def parse_arc(d: str) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float]]:
    """``M x0,y0 Q cx,cy x1,y1`` → начало, контрольная точка, конец."""
    m = re.fullmatch(
        rf"\s*M\s*({NUM})[ ,]\s*({NUM})\s*Q\s*({NUM})[ ,]\s*({NUM})[ ,]\s*({NUM})[ ,]\s*({NUM})\s*",
        d,
    )
    assert m, f"путь дуги не квадратичная кривая M…Q…: {d!r}"
    v = [float(x) for x in m.groups()]
    return (v[0], v[1]), (v[2], v[3]), (v[4], v[5])


def parse_arrow(d: str) -> list[tuple[float, float]]:
    """``M<xв>,<yв>L<x1>,<y1>L<x2>,<y2>Z`` → [вершина, (x1, y1), (x2, y2)]."""
    m = re.fullmatch(
        rf"\s*M\s*({NUM})[ ,]\s*({NUM})\s*L\s*({NUM})[ ,]\s*({NUM})\s*L\s*({NUM})[ ,]\s*({NUM})\s*Z\s*",
        d,
    )
    assert m, f"путь стрелки не M…L…L…Z: {d!r}"
    v = [float(x) for x in m.groups()]
    return [(v[0], v[1]), (v[2], v[3]), (v[4], v[5])]


def bezier(p0, c, p1, t: float) -> tuple[float, float]:
    u = 1 - t
    return (
        u * u * p0[0] + 2 * u * t * c[0] + t * t * p1[0],
        u * u * p0[1] + 2 * u * t * c[1] + t * t * p1[1],
    )


def tangent(p0, c, p1, t: float) -> tuple[float, float]:
    return (
        2 * (1 - t) * (c[0] - p0[0]) + 2 * t * (p1[0] - c[0]),
        2 * (1 - t) * (c[1] - p0[1]) + 2 * t * (p1[1] - c[1]),
    )


def nearest_t(p0, c, p1, q, n: int = 2000) -> tuple[float, float]:
    """Параметр точки кривой, ближайшей к ``q``, и расстояние до неё."""
    best = (0.0, math.inf)
    for i in range(n + 1):
        t = i / n
        x, y = bezier(p0, c, p1, t)
        dist = math.hypot(x - q[0], y - q[1])
        if dist < best[1]:
            best = (t, dist)
    return best


def marker_of(sc: dict, person: str) -> tuple[float, float, dict] | None:
    """Экранный центр маркера персоны по прямоугольнику элемента: нарисованный медальон,
    а у свёрнутой — значок «+N», в котором учтено её место. ``None`` — маркер не виден."""
    p = next((x for x in sc["persons"] if x["id"] == person), None)
    if p is None or p["hidden"] == "true":
        return None
    if p["packed"] == "false":
        return p["box"]["cx"], p["box"]["cy"], p
    badges = [b for b in sc["more"] if p["place"] in b["places"]]
    assert len(badges) <= 1, ("место учтено в нескольких значках", p, badges)
    if not badges or badges[0]["hidden"] == "true":
        return None
    b = badges[0]
    return b["box"]["cx"], b["box"]["cy"], b


def arc_faults(sc: dict) -> list[tuple]:
    """Все нарушения правила «Точные связи» в кадре ``sc`` (пустой список — всё верно)."""
    bad: list[tuple] = []
    for lk in sc["links"]:
        a, b = marker_of(sc, lk["from"]), marker_of(sc, lk["to"])
        if lk["hidden"] == "true":
            if lk["d"] is not None or lk["arrow"] is not None or lk["paths"]:
                bad.append(("скрытая связь с путём", lk["id"]))
            continue
        if a is None or b is None:
            bad.append(("мёртвая дуга: маркер конца не виден", lk["id"], a is None, b is None))
            continue
        if lk["d"] is None or lk["arrow"] is None or lk["arrows"] != 1:
            bad.append(("видимая связь без пути или не с одной стрелкой", lk["id"], lk["arrows"]))
            continue
        p0, c, p1 = parse_arc(lk["d"])
        ax_, ay_ = a[2]["x"], a[2]["y"]
        bx_, by_ = b[2]["x"], b[2]["y"]
        for what, got, want in (
            ("начало ↔ центр источника по прямоугольнику", p0, a[:2]),
            ("начало ↔ data-x/y источника", p0, (ax_, ay_)),
            ("конец ↔ центр цели по прямоугольнику", p1, b[:2]),
            ("конец ↔ data-x/y цели", p1, (bx_, by_)),
        ):
            dist = math.hypot(got[0] - want[0], got[1] - want[1])
            if dist > 1:
                bad.append((what, lk["id"], round(dist, 3)))
        if math.hypot(a[0] - b[0], a[1] - b[1]) < 0.5:
            bad.append(("дуга между одним и тем же маркером", lk["id"]))
        tip, q1, q2 = parse_arrow(lk["arrow"])
        t, on_curve = nearest_t(p0, c, p1, tip)
        if on_curve > 1:
            bad.append(("вершина стрелки не на кривой", lk["id"], round(on_curve, 3)))
        ring = abs(math.hypot(tip[0] - b[0], tip[1] - b[1]) - MEDAL / 2)
        if ring > 1:
            bad.append(("вершина стрелки не на окружности цели", lk["id"], round(ring, 3)))
        back = ((q1[0] + q2[0]) / 2, (q1[1] + q2[1]) / 2)
        axis = (tip[0] - back[0], tip[1] - back[1])
        tan = tangent(p0, c, p1, t)
        na, nt = math.hypot(*axis), math.hypot(*tan)
        if na == 0 or nt == 0:
            bad.append(("вырожденная стрелка", lk["id"]))
        else:
            cos = (axis[0] * tan[0] + axis[1] * tan[1]) / (na * nt)
            angle = math.degrees(math.acos(max(-1.0, min(1.0, cos))))
            if angle > 5:  # остриё к цели вдоль кривой: угол с касательной по ходу ≤ 5°
                bad.append(("ось стрелки не по касательной к цели", lk["id"], round(angle, 2)))
        for i in range(201):
            x, y = bezier(p0, c, p1, i / 200)
            if math.hypot(x - sc["cx"], y - sc["cy"]) > sc["R"] + EPS:
                bad.append(("точка дуги вне круга глобуса", lk["id"], (x, y)))
                break
            if x < -EPS or y < -EPS or x > sc["w"] + EPS or y > sc["h"] + EPS:
                bad.append(("точка дуги вне кадра", lk["id"], (x, y)))
                break
    return bad


def arc_end_error(sc: dict) -> float:
    """Наибольшее расхождение концов видимых дуг с центрами маркеров (px), G6."""
    worst = 0.0
    for lk in sc["links"]:
        if lk["hidden"] == "true" or not lk["d"]:
            continue
        a, b = marker_of(sc, lk["from"]), marker_of(sc, lk["to"])
        if a is None or b is None:
            return math.inf
        p0, _c, p1 = parse_arc(lk["d"])
        worst = max(
            worst, math.hypot(p0[0] - a[0], p0[1] - a[1]), math.hypot(p1[0] - b[0], p1[1] - b[1])
        )
    return worst


# --- перетаскивание ------------------------------------------------------------------------


def drag_frames(page, dx: float, dy: float, frames: int = 5, *, start=None) -> list[dict]:
    """Тянет глобус на (dx, dy) за ``frames`` шагов и снимает сцену в каждом кадре, пока
    кнопка мыши нажата (во время перетаскивания)."""
    sc = scene(page)
    x0 = sc["left"] + (start[0] if start else sc["cx"])
    y0 = sc["top"] + (start[1] if start else sc["cy"])
    page.mouse.move(x0, y0)
    page.mouse.down()
    shots = []
    for i in range(1, frames + 1):
        page.mouse.move(x0 + dx * i / frames, y0 + dy * i / frames, steps=2)
        settle(page)
        shots.append(scene(page))
    page.mouse.up()
    return shots


# --- независимый расчёт по данным карты (d3-geo на пустой странице теста) -----------------

ORACLE_JS = """
(() => {
  const topo = window.__TOPO;
  const fc = topojson.feature(topo, topo.objects.countries).features;
  const KM = 6371;
  const proj = v => d3.geoOrthographic().rotate([-v.lon, -v.lat]).scale(v.R)
    .translate([v.cx, v.cy]).clipExtent([[0, 0], [v.w, v.h]]).precision(0.1);
  window.oracle = {
    ids: () => fc.filter(f => f.id !== undefined).map(f => f.id),
    total: () => fc.length,
    countryAt: (lon, lat) => {
      for (const f of fc) if (d3.geoContains(f, [lon, lat])) return f.id === undefined ? null : f.id;
      let best = null, dist = Infinity;
      for (const f of fc) {
        if (f.id === undefined) continue;
        const polys = f.geometry.type === 'Polygon' ? [f.geometry.coordinates] : f.geometry.coordinates;
        for (const poly of polys) for (const ring of poly) for (const v of ring) {
          const d = d3.geoDistance([lon, lat], v) * KM; if (d < dist) { dist = d; best = f.id; } }
      }
      return dist <= 150 ? best : null;
    },
    contains: (id, lon, lat) => { const f = fc.find(x => x.id === id); return !!f && d3.geoContains(f, [lon, lat]); },
    visible: v => { const path = d3.geoPath(proj(v)); const out = {};
      for (const f of fc) { if (f.id === undefined) continue; const a = path.area(f);
        if (a > 0) { const b = path.bounds(f); out[f.id] = {area: a, span: b[1][0] - b[0][0]}; } }
      return out; },
    invert: (v, x, y) => proj(v).invert([x, y]),
    borders: v => { const m = topojson.mesh(topo, topo.objects.countries, (a, b) => a !== b);
      const c = [v.lon, v.lat]; let n = 0, edge = 0;
      for (const line of m.coordinates) {
        const ds = line.map(p => d3.geoDistance(p, c));
        if (ds.some(d => d < Math.PI / 2 - 1e-6)) n++;
        else if (ds.some(d => d <= Math.PI / 2 + 1e-6)) edge++; }
      return {n, edge, total: m.coordinates.length}; },
    pairLine: (a, b) => { const m = topojson.mesh(topo, topo.objects.countries,
        (x, y) => (x.id === a && y.id === b) || (x.id === b && y.id === a));
      return m.coordinates.sort((p, q) => q.length - p.length)[0]; },
    project: (v, lon, lat) => proj(v)([lon, lat]),
    noId: () => fc.filter(f => f.id === undefined).map(f => ({name: f.properties.name,
      bounds: d3.geoBounds(f)})),
    nearBorderInside: (name, km) => {
      // точка внутри территории без кода в ``km`` от её границы
      const f = fc.find(x => x.id === undefined && x.properties.name === name);
      const ring = (f.geometry.type === 'Polygon' ? f.geometry.coordinates : f.geometry.coordinates[0])[0];
      const [[x0, y0], [x1, y1]] = d3.geoBounds(f);
      let best = null;
      for (let i = 0; i <= 80; i++) for (let j = 0; j <= 80; j++) {
        const p = [x0 + (x1 - x0) * i / 80, y0 + (y1 - y0) * j / 80];
        if (!d3.geoContains(f, p)) continue;
        // расстояние до границы — до ближайшей точки отрезков кольца (с шагом 0,5 км)
        let d = Infinity;
        for (let k = 0; k + 1 < ring.length; k++) {
          const seg = d3.geoInterpolate(ring[k], ring[k + 1]);
          const len = d3.geoDistance(ring[k], ring[k + 1]) * KM;
          const steps = Math.max(1, Math.ceil(len / 0.5));
          for (let s = 0; s <= steps; s++) d = Math.min(d, d3.geoDistance(p, seg(s / steps)) * KM);
        }
        if (best === null || Math.abs(d - km) < Math.abs(best.d - km)) best = {p, d};
      }
      return best;
    },
  };
  return true;
})()
"""


class Oracle:
    """Пустая страница теста с d3-geo, topojson-client и данными world-atlas (без сети)."""

    def __init__(self, context) -> None:
        self.page = context.new_page()
        self.page.set_content("<!doctype html><meta charset='utf-8'><title>oracle</title>")
        for lib in (
            "d3-array/dist/d3-array.min.js",
            "d3-geo/dist/d3-geo.min.js",
            "topojson-client/dist/topojson-client.min.js",
        ):
            self.page.add_script_tag(path=str(NODE / lib))
        self.page.add_script_tag(content="window.__TOPO = " + WORLD_JSON.read_text("utf-8"))
        assert self.page.evaluate(ORACLE_JS)

    def __call__(self, fn: str, *args):
        return self.page.evaluate(f"([a]) => oracle.{fn}(...a)", [list(args)])

    def close(self) -> None:
        self.page.close()


def view_arg(sc: dict) -> dict:
    lon, lat = view_of(sc)
    return {
        "lon": lon,
        "lat": lat,
        "R": sc["R"],
        "cx": sc["cx"],
        "cy": sc["cy"],
        "w": sc["w"],
        "h": sc["h"],
    }


def ru_names() -> dict[str, str]:
    return json.loads(RU_JSON.read_text("utf-8"))["names"]


def world_ids() -> list[str]:
    topo = json.loads(WORLD_JSON.read_text("utf-8"))
    return [g["id"] for g in topo["objects"]["countries"]["geometries"] if "id" in g]


RU_TEXT = re.compile(r"^[А-Яа-яЁё][А-Яа-яЁё \-.'’]*$")


# --- синтетический слой (только для пределов: десятки тысяч персон) ------------------------


def synthetic(
    stack,
    context,
    places: list[dict],
    people: list[tuple[str, str, str]],
    links_: list[dict] | None = None,
) -> tuple[dict, dict]:
    """Ответы ``/map`` и ``/map/places`` по образцу настоящих: ``places`` — {id, label, lat,
    lon}; ``people`` — (id, label, place). Все живы 1720–1780."""
    real_map = context.request.get(stack.url + "/api/knowledge/v1/map").json()
    real_places = context.request.get(stack.url + "/api/knowledge/v1/map/places").json()
    template = real_map["people"][0]
    data = {
        **real_map,
        "people": [
            {
                **template,
                "id": pid,
                "label": label,
                "short": label.split()[-1],
                "birth": 1720,
                "death": 1780,
                "weight": 1,
                "epochs": [],
                "roles": [],
                "portrait": None,
            }
            for pid, label, _ in people
        ],
        "works": [],
        "events": [],
        "links": links_ or [],
        "groups": [],
        "eras": [],
        "truncated": False,
    }
    data["people"] = [
        {k: v for k, v in p.items() if not (k == "portrait" and v is None)} for p in data["people"]
    ]
    layer = {
        **real_places,
        "places": [{**p, "status": "sourced"} for p in places],
        "placements": [
            {
                "entity": pid,
                "place": place,
                "role": None,
                "from": None,
                "to": None,
                "status": "sourced",
                "generated": False,
                "statement": f"s_{pid}",
            }
            for pid, _, place in people
        ],
        "unplaced": [],
    }
    return data, layer
