"""Глобус: пределы, без WebGL и сторонних запросов, без лишнего движения, глобус на листе
(geo-timeline, задачи 7.5–7.6).

Требования «Пределы глобуса», «Глобус без WebGL и без сторонних запросов», «Глобус без
лишнего движения», «Глобус на листе» дельты
``openspec/specs/geo-timeline/spec.md``. Настоящий сервис знаний;
``page.route`` — только для 320 мест (ответы ``/map`` и ``/map/places`` дополняются
синтетическими людьми и местами). Время — ``page.clock``. Визуальное проверяется по DOM
(снимки-эталоны есть только для Windows).
"""

# ruff: noqa: E501 — встроенные скрипты страницы и имена инвариантов спецификации

from __future__ import annotations

import gzip
import itertools
import math

import pytest
from playwright.sync_api import expect

from .geo_helpers import (
    MAP_API,
    PLACES_API,
    Geo,
    arc_faults,
    center,
    collisions,
    drawn,
    focus_globe,
    geo_built,
    globe,
    globe_ready,
    links,
    open_globe,
    persons,
    play_button,
    press,
    rows,
    scene,
    settle,
    shapes,
    synthetic,
    year,
)
from .test_geo_medals import add_portrait, many_places

req = pytest.mark.req
GEO = "geo-timeline"
LIMITS = "Пределы глобуса"
NOGL = "Глобус без WebGL и без сторонних запросов"
MOTION = "Глобус без лишнего движения"
SHEET = "Глобус на листе"
expect.set_options(timeout=20000)


def base_world(world) -> dict[str, str]:
    g = Geo(world)
    ids = {
        "kant": world.person("Иммануил Кант", "1724", "1804"),
        "hume": world.person("Дэвид Юм", "1711", "1776"),
        "fichte": world.person("Иоганн Фихте", "1762", "1814"),
        "konigsberg": g.place("Кёнигсберг", 54.71, 20.51),
        "edinburgh": g.place("Эдинбург", 55.95, -3.19),
        "jena": g.place("Йена", 50.93, 11.59),
    }
    g.lived(ids["kant"], ids["konigsberg"])
    g.lived(ids["hume"], ids["edinburgh"])
    g.lived(ids["fichte"], ids["jena"])
    world.relate(ids["kant"], "influenced_by", ids["hume"])
    world.relate(ids["fichte"], "influenced_by", ids["kant"])
    return ids


# --- Пределы ----------------------------------------------------------------------------


@req(GEO, LIMITS, scenario="Много мест")
def test_many_places(knowledge_context, knowledge_stack, events):
    base_world(knowledge_stack.world)
    context = knowledge_context(1920, 1080)
    places, people = many_places()
    data, layer = synthetic(knowledge_stack, context, places, people)
    page = context.new_page()
    page.set_default_timeout(180000)
    page.route(MAP_API, lambda r: r.fulfill(json=data))
    page.route(PLACES_API, lambda r: r.fulfill(json=layer))
    page.goto(knowledge_stack.url + "/graph?view=globe&t=1750")
    page.locator(".geo-globe[aria-busy='false']").wait_for(timeout=240000)
    settle(page)
    sc = scene(page)
    shown = {p["place"] for p in sc["persons"]}
    assert len(shown) == 300
    assert not ({f"g{i:03d}" for i in range(1, 21)} & shown)
    assert shown == {f"g{i:03d}" for i in range(21, 321)}
    assert len(rows(page)) == 300
    expect(page.locator("[data-geo-limit='places']")).to_have_text("показаны 300 из 320 мест")
    # Ответы подменены: событие слоя пишут прямые запросы теста, а не страница.
    assert len(events.of("knowledge.geo.built")) == 1


@req(GEO, LIMITS, invariant="при равенстве людей места отбираются по id")
def test_place_limit_tie_by_id(knowledge_context, knowledge_stack, events):
    base_world(knowledge_stack.world)
    context = knowledge_context(1920, 1080)
    places = [
        {"id": f"t{i:03d}", "label": f"Т{i}", "lat": (i % 60) - 30, "lon": (i * 7) % 300 - 150}
        for i in range(305)
    ]
    people = [(f"y{i:03d}", f"Y{i}", f"t{i:03d}") for i in range(305)]  # у всех по одному
    data, layer = synthetic(knowledge_stack, context, places, people)
    page = context.new_page()
    page.set_default_timeout(60000)
    page.route(MAP_API, lambda r: r.fulfill(json=data))
    page.route(PLACES_API, lambda r: r.fulfill(json=layer))
    page.goto(knowledge_stack.url + "/graph?view=globe&t=1750")
    globe_ready(page)
    assert {p["place"] for p in scene(page)["persons"]} == {f"t{i:03d}" for i in range(300)}
    expect(page.locator("[data-geo-limit='places']")).to_have_text("показаны 300 из 305 мест")
    assert len(events.of("knowledge.geo.built")) == 1


def links_world(world, n_people: int = 24, n_links: int = 260):
    g = Geo(world)
    people = []
    for i in range(n_people):
        p = world.person(f"Философ {i:02d}", "1700", "1780")
        place = g.place(f"Город {i:02d}", 35 + (i % 6) * 4, -5 + (i // 6) * 8)
        g.lived(p, place)
        for k in range(i % 5):  # разный вес концов
            world.describe(p, f"описание {i} {k}")
        people.append(p)
    pairs = list(itertools.combinations(range(n_people), 2))[:n_links]
    ids = [world.relate(people[b], "influenced_by", people[a]) for a, b in pairs]
    return people, ids


@req(GEO, LIMITS, scenario="Много связей")
def test_many_links(knowledge_context, knowledge_stack, events):
    links_world(knowledge_stack.world)
    page, response = open_globe(knowledge_context, knowledge_stack, "/graph?view=globe&t=1760")
    assert page.locator("[data-geo-link]").count() == 200
    expect(page.locator("[data-geo-limit='links']")).to_have_text("показаны 200 из 260 связей")
    assert arc_faults(scene(page)) == []
    geo_built(events, response)


@req(GEO, LIMITS, invariant="остаются связи с наибольшим весом концов, при равенстве — по id")
def test_link_limit_order(knowledge_context, knowledge_stack, events):
    links_world(knowledge_stack.world)
    context = knowledge_context(1920, 1080)
    page = context.new_page()
    page.set_default_timeout(30000)
    with (
        page.expect_response(lambda r: MAP_API.match(r.url)) as map_info,
        page.expect_response(lambda r: PLACES_API.match(r.url)) as places_info,
    ):
        page.goto(knowledge_stack.url + "/graph?view=globe&t=1760")
    globe_ready(page)
    data = map_info.value.json()
    weight = {p["id"]: p["weight"] for p in data["people"]}
    shown_links = data["links"]
    assert len(shown_links) == 260, len(shown_links)
    ranked = sorted(
        shown_links, key=lambda lk: (-(weight[lk["subject"]] + weight[lk["object"]]), lk["id"])
    )
    assert len({-(weight[lk["subject"]] + weight[lk["object"]]) for lk in ranked}) > 2
    expected = {lk["id"] for lk in ranked[:200]}
    assert set(links(page)) == expected
    geo_built(events, places_info.value)


def labels_world(world) -> None:
    g = Geo(world)
    for i in range(30):
        p = world.person(f"Мыслитель {i:02d}", "1700", "1780")
        place = g.place(f"Городок-{i:02d}", 44 + (i % 6) * 2.2, 0 + (i // 6) * 4.5)
        g.lived(p, place)


@req(GEO, LIMITS, scenario="Подписи без наложений")
@pytest.mark.parametrize(("width", "height"), [(1024, 576), (1280, 720), (1366, 768), (1920, 1080)])
def test_labels_do_not_overlap(knowledge_context, knowledge_stack, events, width, height):
    labels_world(knowledge_stack.world)
    page, response = open_globe(
        knowledge_context, knowledge_stack, "/graph?view=globe&t=1750", width=width, height=height
    )
    focus_globe(page)
    frames = 0
    for zoom_steps in (None, 0, 3, 6):
        if zoom_steps is not None:
            press(page, "-", 12)
            press(page, "+", zoom_steps)
            settle(page)
        sc = scene(page)
        assert len(sc["countries"]) <= 24
        items = shapes(sc)
        assert collisions(items) == [], (zoom_steps, collisions(items)[:3])
        frames += 1
    assert frames == 4
    geo_built(events, response)


@req(GEO, LIMITS, scenario="Вес фрагмента")
def test_fragment_weight(knowledge_context, knowledge_stack, events):
    w = base_world(knowledge_stack.world)
    for who in ("kant", "hume", "fichte"):
        add_portrait(knowledge_stack, w[who])
    context = knowledge_context(1920, 1080)
    page = context.new_page()
    page.set_default_timeout(30000)
    page.goto(knowledge_stack.url + "/graph")
    page.locator(".map-canvas").wait_for()
    settle(page)
    after: list = []
    page.on("response", lambda r: after.append(r))
    with page.expect_response(lambda r: PLACES_API.match(r.url)) as info:
        page.locator(".map-view-switch").get_by_role("button", name="Глобус").click()
    globe_ready(page)
    page.wait_for_load_state("networkidle")
    total = 0
    sizes = {}
    portraits = []
    for r in after:
        if "/portraits/" in r.url or r.request.resource_type == "image":
            portraits.append(r.url)
            continue
        body = r.body()
        packed = len(gzip.compress(body, compresslevel=9))
        sizes[r.url.rsplit("/", 1)[-1][:40]] = packed
        total += packed
    assert any("GlobeView" in u for u in sizes), sizes
    assert total <= 150 * 1024, (total, sizes)
    drawn_n = sum(1 for p in scene(page)["persons"] if drawn(p))
    # Портреты, уже загруженные хронологией, берутся из кэша и запросов после переключения
    # могут не дать; непустой случай проверяет test_portrait_limit.
    assert all(
        u.startswith(knowledge_stack.url + "/api/knowledge/v1/portraits/") for u in portraits
    ), portraits
    assert len(portraits) <= drawn_n and len(portraits) <= 60
    geo_built(events, info.value)


@req(
    GEO,
    LIMITS,
    invariant="портретов одновременно не больше 60, только для нарисованных медальонов и только со своего адреса",
)
def test_portrait_limit(knowledge_context, knowledge_stack, events):
    world = knowledge_stack.world
    g = Geo(world)
    people = []
    for i in range(75):
        p = world.person(f"Портретный {i:02d}", "1700", "1780")
        g.lived(p, g.place(f"Пункт {i:02d}", -50 + (i % 15) * 7, -150 + (i // 15) * 70))
        add_portrait(knowledge_stack, p)
        people.append(p)
    context = knowledge_context(1920, 1080)
    page = context.new_page()
    page.set_default_timeout(60000)
    requested: list[str] = []
    page.on("request", lambda r: requested.append(r.url) if "/portraits/" in r.url else None)
    with page.expect_response(lambda r: PLACES_API.match(r.url)) as info:
        page.goto(knowledge_stack.url + "/graph?view=globe&t=1750")
    globe_ready(page)
    page.wait_for_load_state("networkidle")
    sc = scene(page)
    with_image = [p for p in sc["persons"] if p["image"]]
    assert len(with_image) <= 60
    assert all(drawn(p) for p in with_image)
    drawn_n = sum(1 for p in sc["persons"] if drawn(p))
    assert len(with_image) == min(60, drawn_n), (len(with_image), drawn_n)
    assert len(set(requested)) <= min(60, drawn_n)
    assert all(
        u.startswith(knowledge_stack.url + "/api/knowledge/v1/portraits/") for u in requested
    )
    geo_built(events, info.value)


@req(
    GEO,
    LIMITS,
    invariant="персон в сцене больше MAX_PERSONS — в DOM 600 медальонов и «показаны 600 из K человек»",
)
def test_people_limit_notice(knowledge_context, knowledge_stack, events):
    base_world(knowledge_stack.world)
    context = knowledge_context(1366, 768)
    places = [
        {"id": f"p{i:02d}", "label": f"Пункт {i}", "lat": 40 + i % 10, "lon": i * 3 - 10}
        for i in range(20)
    ]
    people = [(f"z{i:04d}", f"Персона {i}", f"p{i % 20:02d}") for i in range(700)]
    data, layer = synthetic(knowledge_stack, context, places, people)
    page = context.new_page()
    page.set_default_timeout(60000)
    page.route(MAP_API, lambda r: r.fulfill(json=data))
    page.route(PLACES_API, lambda r: r.fulfill(json=layer))
    page.goto(knowledge_stack.url + "/graph?view=globe&t=1750")
    globe_ready(page)
    assert page.locator("[data-geo-person]").count() == 600
    expect(page.locator("[data-geo-limit='people']")).to_have_text("показаны 600 из 700 человек")
    assert len(events.of("knowledge.geo.built")) == 1


# --- Без WebGL и без сторонних запросов ------------------------------------------------

NO_WEBGL = """
(() => {
  const orig = HTMLCanvasElement.prototype.getContext;
  HTMLCanvasElement.prototype.getContext = function (kind, ...rest) {
    if (kind === 'webgl' || kind === 'webgl2' || kind === 'experimental-webgl') return null;
    return orig.call(this, kind, ...rest);
  };
})();
"""


def _scene_counts(page) -> tuple[int, int, int]:
    expect(page.locator("canvas[data-geo-land][data-drawn='true']")).to_have_count(1)
    assert int(page.locator("canvas[data-geo-land]").get_attribute("data-borders")) > 0
    return (
        page.locator("[data-geo-person]").count(),
        page.locator("[data-geo-link]").count(),
        page.locator("[data-geo-country]").count(),
    )


@req(GEO, NOGL, scenario="WebGL недоступен")
def test_without_webgl(knowledge_context, knowledge_stack, events):
    w = base_world(knowledge_stack.world)
    path = f"/graph/{w['kant']}?view=globe&t=1800"
    page, response = open_globe(knowledge_context, knowledge_stack, path)
    normal = _scene_counts(page)
    geo_built(events, response)
    page.context.close()
    page, response = open_globe(
        knowledge_context,
        knowledge_stack,
        path,
        before=lambda p: p.add_init_script(NO_WEBGL),
    )
    assert page.evaluate("document.createElement('canvas').getContext('webgl')") is None
    assert page.evaluate("document.createElement('canvas').getContext('webgl2')") is None
    assert _scene_counts(page) == normal
    assert normal[0] == 3 and normal[1] == 2 and normal[2] > 0
    # Суша нарисована: на холсте есть непрозрачные пиксели.
    drawn = page.locator("canvas[data-geo-land]").evaluate(
        """c => { const x = c.getContext('2d'); const d = x.getImageData(0, 0, c.width, c.height).data;
            let n = 0; for (let i = 3; i < d.length; i += 4) if (d[i] > 0) n++; return n; }"""
    )
    assert drawn > 1000
    geo_built(events, response)


@req(GEO, NOGL, scenario="Только свой адрес")
def test_only_own_address(knowledge_context, knowledge_stack, events):
    base_world(knowledge_stack.world)
    context = knowledge_context(1920, 1080)
    page = context.new_page()
    page.set_default_timeout(30000)
    page.clock.install()
    page.goto(knowledge_stack.url + "/graph")
    page.locator(".map-canvas").wait_for()
    urls: list[str] = []
    page.on("request", lambda r: urls.append(r.url))
    with page.expect_response(lambda r: PLACES_API.match(r.url)) as info:
        page.locator(".map-view-switch").get_by_role("button", name="Глобус").click()
    globe_ready(page)
    box = globe(page).bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 80, y + 30, steps=5)
    page.mouse.up()
    sc = scene(page)
    for p in sc["persons"]:
        if drawn(p):
            page.mouse.move(sc["left"] + p["box"]["cx"], sc["top"] + p["box"]["cy"])
    focus_globe(page)
    press(page, "ArrowLeft")
    press(page, "+")
    press(page, "PageUp")
    play_button(page).click()
    page.clock.run_for(5000)
    play_button(page).click()
    assert urls, "запросы после переключения не записаны"
    foreign = [
        u for u in urls if not u.startswith(knowledge_stack.url) and not u.startswith("data:")
    ]
    assert foreign == []
    assert knowledge_stack.outside == []
    expect(page.locator(".geo-coast")).to_have_text(
        "Границы и береговая линия — современные, Natural Earth"
    )
    geo_built(events, info.value)


# --- Без лишнего движения ---------------------------------------------------------------


def _watch(page, attr: str) -> None:
    page.evaluate(
        """attr => { window.__seen = window.__seen || {}; window.__seen[attr] = [];
            const el = document.querySelector('.geo-globe');
            new MutationObserver(() => window.__seen[attr].push(el.getAttribute(attr)))
              .observe(el, {attributes: true, attributeFilter: [attr]}); }""",
        attr,
    )


def _seen(page, attr: str) -> list[str]:
    return page.evaluate("attr => window.__seen[attr]", attr)


@req(GEO, MOTION, scenario="Уменьшенное движение")
def test_reduced_motion(knowledge_context, knowledge_stack, events):
    w = base_world(knowledge_stack.world)
    page, response = open_globe(
        knowledge_context,
        knowledge_stack,
        "/graph?view=globe&from=1700&to=1800&t=1760",
        reduced_motion="reduce",
        before=lambda p: p.clock.install(),
    )
    target = "20.51,54.71"
    assert center(page) != target
    _watch(page, "data-center")
    row = page.locator(f"[data-geo-row='{w['konigsberg']}'] .geo-row__place")
    # При reduce и остановленных часах страницы Playwright не дожидается «стабильности»
    # элемента (переходы 0,001 с не завершаются без хода времени) — щелчок событием,
    # после явной проверки, что кнопка видна и доступна.
    expect(row).to_be_visible()
    expect(row).to_be_enabled()
    row.dispatch_event("click")
    expect(page.locator(".map-selected__name")).to_have_text("Кёнигсберг, Россия, 1760")
    page.clock.run_for(50)  # один кадр; дальше время страницы стоит
    expect(globe(page)).to_have_attribute("data-center", target)
    assert _seen(page, "data-center") == [target]
    page.clock.run_for(1000)
    assert _seen(page, "data-center") == [target]
    _watch(page, "data-year")
    start = year(page)
    play_button(page).click()
    page.clock.run_for(3000)
    assert year(page) == start + 30
    steps = [int(v) for v in _seen(page, "data-year")]
    assert steps == [start + 10, start + 20, start + 30], steps
    geo_built(events, response)


@req(
    GEO,
    MOTION,
    invariant="при уменьшенном движении поворот клавишами сразу, без промежуточных значений",
)
def test_reduced_motion_keys_immediate(knowledge_context, knowledge_stack, events):
    base_world(knowledge_stack.world)
    page, response = open_globe(
        knowledge_context,
        knowledge_stack,
        "/graph?view=globe&t=1780",
        reduced_motion="reduce",
        before=lambda p: p.clock.install(),
    )
    _watch(page, "data-center")
    start = center(page)
    focus_globe(page)
    press(page, "ArrowRight")
    after = center(page)
    assert after != start
    page.clock.run_for(2000)
    assert _seen(page, "data-center") == [after]
    geo_built(events, response)


@req(GEO, MOTION, scenario="Плавный поворот")
def test_smooth_turn(knowledge_context, knowledge_stack, events):
    w = base_world(knowledge_stack.world)
    page, response = open_globe(
        knowledge_context,
        knowledge_stack,
        "/graph?view=globe&t=1780",
        reduced_motion="no-preference",
        before=lambda p: p.clock.install(),
    )
    page.locator(f"[data-geo-row='{w['edinburgh']}'] .geo-row__place").click()
    page.clock.run_for(600)
    assert center(page) == "-3.19,55.95"
    _watch(page, "data-center")
    page.clock.run_for(5000)
    assert _seen(page, "data-center") == []
    assert center(page) == "-3.19,55.95"
    geo_built(events, response)


@req(GEO, MOTION, invariant="без действия читателя глобус не движется")
@pytest.mark.parametrize("motion", ["reduce", "no-preference"])
def test_still_without_action(knowledge_context, knowledge_stack, events, motion):
    w = base_world(knowledge_stack.world)
    page, response = open_globe(
        knowledge_context,
        knowledge_stack,
        f"/graph/{w['kant']}?view=globe",
        reduced_motion=motion,
        before=lambda p: p.clock.install(),
    )
    _watch(page, "data-center")
    _watch(page, "data-year")
    _watch(page, "data-zoom")
    page.clock.run_for(5000)
    assert _seen(page, "data-center") == _seen(page, "data-year") == _seen(page, "data-zoom") == []
    anims = page.evaluate(
        "() => document.getAnimations().filter(a => a.effect && a.effect.target"
        " && a.effect.target.closest && a.effect.target.closest('.geo-stage')).length"
    )
    assert anims == 0
    expect(play_button(page)).to_have_text("Играть")
    geo_built(events, response)


# --- Глобус на листе --------------------------------------------------------------------

CONTRAST_JS = """
() => {
  const rgb = s => (s.match(/[\\d.]+/g) || []).slice(0, 4).map(Number);
  const lum = c => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); };
  const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
  const bg = e => { for (let n = e; n; n = n.parentElement) { const c = rgb(getComputedStyle(n).backgroundColor);
      if (c.length === 3 || c[3] > 0) return c; } return [255, 255, 255]; };
  const token = name => { const d = document.createElement('div'); d.style.color = `var(${name})`;
    document.body.appendChild(d); const c = rgb(getComputedStyle(d).color); d.remove(); return c; };
  const sea = token('--globe-sea'), land = token('--globe-land');
  const out = [];
  const check = (e, backs, what, a = 1) => { const s = getComputedStyle(e);
    // подпись с ореолом (обводка под текстом): фон — цвет ореола
    if (e instanceof SVGElement && s.stroke !== 'none' && s.paintOrder.startsWith('stroke') && parseFloat(s.strokeWidth) >= 2) backs = [rgb(s.stroke)];
    const fg = rgb(e instanceof SVGElement ? s.fill : s.color);
    for (const b of backs) { const f = fg.slice(0, 3).map((v, i) => a * v + (1 - a) * b[i]); const r = ratio(f, b); if (r < 4.5) out.push([what, e.textContent.slice(0, 30), r.toFixed(2)]); } };
  const alpha = e => { let a = 1; for (let n = e; n && n !== document.body; n = n.parentElement) a *= Number(getComputedStyle(n).opacity); return a; };
  const faded = (e, backs, what) => check(e, backs, what, alpha(e));
  document.querySelectorAll('[data-geo-country]').forEach(e => faded(e, [land], 'country'));
  document.querySelectorAll('[data-geo-name]').forEach(e => faded(e, [sea, land], 'name'));
  document.querySelectorAll('[data-geo-tip]').forEach(e => check(e, [bg(e)], 'tip'));
  document.querySelectorAll('.geo-yearbar__year').forEach(e => check(e, [bg(e)], 'year'));
  document.querySelectorAll('.geo-row__name, .geo-row__count, .geo-row__who button, .geo-row__unverified')
    .forEach(e => check(e, [bg(e)], 'row'));
  const paper = bg(document.querySelector('.geo-yearbar'));
  return {out, sea: lum(sea), land: lum(land), paper: lum(paper),
          labels: document.querySelectorAll('[data-geo-country]').length,
          names: document.querySelectorAll('[data-geo-name]').length,
          rows: document.querySelectorAll('[data-geo-row]').length};
}
"""


@req(GEO, SHEET, scenario="Вечер при лампе")
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_contrast_in_both_themes(knowledge_context, knowledge_stack, events, theme):
    w = base_world(knowledge_stack.world)
    g = Geo(knowledge_stack.world)
    locke = knowledge_stack.world.person("Джон Локк", "1632", "1704")
    g.lived(locke, g.place("Лондон", 51.51, -0.13), generated=True)
    page, response = open_globe(
        knowledge_context,
        knowledge_stack,
        f"/graph/{w['kant']}?view=globe&t=1781",
        color_scheme=theme,
    )
    result = page.evaluate(CONTRAST_JS)
    assert result["labels"] >= 3 and result["names"] >= 3 and result["rows"] >= 3, result
    assert result["out"] == [], result["out"]
    assert result["paper"] > 0.7 and result["sea"] > 0.5 and result["land"] > 0.5, result
    geo_built(events, response)


def _circle(page) -> dict:
    return page.locator(".geo-rim").evaluate(
        """e => { const r = e.getBoundingClientRect();
            return {cx: r.x + r.width / 2, cy: r.y + r.height / 2, r: r.width / 2,
                    top: r.top, bottom: r.bottom, left: r.left, right: r.right}; }"""
    )


def _rect_hits_circle(rect: dict, c: dict) -> bool:
    nx = min(max(c["cx"], rect["x"]), rect["x"] + rect["width"])
    ny = min(max(c["cy"], rect["y"]), rect["y"] + rect["height"])
    return math.hypot(nx - c["cx"], ny - c["cy"]) < c["r"]


@req(GEO, SHEET, scenario="Три кадра")
@pytest.mark.parametrize(("width", "height"), [(1920, 1080), (1366, 768), (1024, 576)])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_three_frames(knowledge_context, knowledge_stack, events, width, height, theme):
    w = base_world(knowledge_stack.world)
    page, response = open_globe(
        knowledge_context,
        knowledge_stack,
        f"/graph/{w['kant']}?view=globe&t=1781",
        width=width,
        height=height,
        color_scheme=theme,
    )
    dims = page.evaluate(
        "() => ({sh: document.documentElement.scrollHeight, sw: document.documentElement.scrollWidth,"
        " ih: innerHeight, iw: innerWidth})"
    )
    assert dims["sh"] <= dims["ih"] and dims["sw"] <= dims["iw"], dims
    c = _circle(page)
    assert c["top"] >= 0 and c["left"] >= 0 and c["bottom"] <= height and c["right"] <= width, c
    scale = page.locator(".map-overview").bounding_box()
    assert scale["y"] >= c["bottom"] - 1, (scale, c)
    assert scale["y"] + scale["height"] <= height
    expect(page.locator(".map-overview")).to_be_visible()
    expect(page.locator(".geo-yearbar__year")).to_be_in_viewport()
    panel = page.locator(".map-panel").bounding_box()
    assert not _rect_hits_circle(panel, c), (panel, c)
    geo_built(events, response)


TOKENS_JS = """
() => {
  const literal = /#[0-9a-f]{3,8}\\b|rgba?\\(|hsla?\\(|\\b(red|blue|green|black|white|gray|grey|navy|brown|gold|silver)\\b/i;
  const bad = [];
  const stage = document.querySelector('.geo-stage');
  for (const e of stage.querySelectorAll('*')) {
    for (const a of ['fill', 'stroke', 'stop-color', 'color', 'style']) {
      const v = e.getAttribute(a);
      if (v && literal.test(v)) bad.push([e.tagName, a, v.slice(0, 60)]);
    }
  }
  const rules = [];
  for (const sheet of document.styleSheets) {
    let list; try { list = sheet.cssRules; } catch { continue; }
    const walk = rs => { for (const r of rs) { if (r.cssRules) walk(r.cssRules);
      if (!r.selectorText || !/geo-/.test(r.selectorText)) continue;
      for (const p of ['fill', 'stroke', 'color', 'background-color', 'stop-color', 'outline-color', 'border-color']) {
        const v = r.style.getPropertyValue(p);
        if (v && !/var\\(--|none|transparent|currentcolor|inherit|initial|url\\(/i.test(v)) rules.push([r.selectorText, p, v]);
      } } };
    walk(list);
  }
  const filters = stage.querySelectorAll('filter').length;
  const cssFilters = [...stage.querySelectorAll('*')].filter(e => getComputedStyle(e).filter !== 'none').length;
  const anims = document.getAnimations().filter(a => a.effect && a.effect.target && a.effect.target.closest
    && a.effect.target.closest('.geo-stage')).length;
  return {bad, rules, filters, cssFilters, anims};
}
"""


@req(GEO, SHEET, scenario="Токены и покой")
def test_tokens_and_calm(knowledge_context, knowledge_stack, events):
    w = base_world(knowledge_stack.world)
    page, response = open_globe(
        knowledge_context, knowledge_stack, f"/graph/{w['kant']}?view=globe&t=1800"
    )
    result = page.evaluate(TOKENS_JS)
    assert result["bad"] == [], result["bad"]
    assert result["rules"] == [], result["rules"]
    assert (result["filters"], result["cssFilters"], result["anims"]) == (0, 0, 0), result
    tokens = page.evaluate(
        "() => ['--globe-sea','--globe-land','--globe-coast','--globe-border','--globe-country','--globe-graticule','--globe-brass']"
        ".map(t => getComputedStyle(document.documentElement).getPropertyValue(t).trim())"
    )
    assert all(tokens), tokens
    assert len(links(page)) == 2 and len(persons(page)) == 3 and len(rows(page)) == 3
    geo_built(events, response)


@req(GEO, SHEET, invariant="токены глобуса одинаковы в обеих темах")
def test_tokens_same_in_themes(knowledge_context, knowledge_stack, events):
    w = base_world(knowledge_stack.world)
    seen = []
    for theme in ("light", "dark"):
        page, response = open_globe(
            knowledge_context,
            knowledge_stack,
            f"/graph/{w['kant']}?view=globe",
            color_scheme=theme,
        )
        seen.append(
            page.evaluate(
                "() => ['--globe-sea','--globe-land','--globe-coast','--globe-border','--globe-country','--globe-graticule','--globe-brass']"
                ".map(t => getComputedStyle(document.documentElement).getPropertyValue(t).trim())"
            )
        )
        geo_built(events, response)
        page.context.close()
    assert seen[0] == seen[1] and all(seen[0])
