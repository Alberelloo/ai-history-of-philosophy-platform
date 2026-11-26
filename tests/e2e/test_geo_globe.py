"""Глобус на живом продукте (geo-timeline; rework-globe-political-map, задача 5.8).

Демо-данные стенда (``scripts/seed_demo.py``) задают места с координатами и людей без места.
Ожидания здесь — только из спецификации, без чисел демо-набора: на глобусе есть медальоны
и подписи стран по словарю, дуги точно соединяют маркеры, медальоны и подписи не налагаются,
счётчик «N без места» совпадает с полем ``unplaced`` события ``knowledge.geo.built`` того же
запроса, внешних запросов нет. На машине агента (1 ГБ RAM, без Docker) не прогоняется —
прогон в CI или у ведущего.
"""

from __future__ import annotations

import re

import pytest

from ..helpers import reader_context as shared_reader_context
from ..web.geo_helpers import (
    RU_TEXT,
    arc_end_error,
    arc_faults,
    collisions,
    drawn,
    outside,
    ru_names,
    scene,
    shapes,
)
from .conftest import reader_context, wait_logs

req = pytest.mark.req
pytestmark = pytest.mark.e2e
GEO = "geo-timeline"
PLACES = re.compile(r".*/api/knowledge/v1/map/places(\?.*)?$")


def _built(stack, response) -> dict:
    rid = response.headers.get("x-request-id")
    built = wait_logs(
        stack,
        "knowledge",
        lambda e: e.get("event") == "knowledge.geo.built" and e.get("request_id") == rid,
        20,
    )
    assert len(built) == 1, rid
    return built[0]


@req(GEO, "Вид «Глобус» на карте раздела", scenario="Ссылка на глобус")
@req(GEO, "Размещение на глобусе", scenario="Счётчик без места")
def test_demo_globe_marks_and_unplaced(browser, stack):
    context = reader_context(browser)
    page = context.new_page()
    page.set_default_timeout(30000)
    foreign: list[str] = []
    page.on("request", lambda r: None if r.url.startswith(stack.url) else foreign.append(r.url))
    try:
        with page.expect_response(lambda r: PLACES.match(r.url)) as info:
            page.goto(stack.url + "/graph?view=globe")
        page.locator(".geo-globe[aria-busy='false']").wait_for()
        assert page.locator("[data-geo-person]").count() >= 1
        assert page.locator("[data-geo-place]").count() == 0
        places = set(
            page.locator("[data-geo-person], [data-geo-event]").evaluate_all(
                "es => es.map(e => e.dataset.place)"
            )
        )
        assert page.locator("[data-geo-row]").count() == len(places)
        counter = page.locator("[data-geo-unplaced]")
        text = counter.inner_text()
        found = re.fullmatch(r"(\d+) без места", text.strip())
        assert found, text
        built = _built(stack, info.value)
        assert built["unplaced"] == int(found.group(1))
        assert built["places"] >= 1
        assert foreign == []
    finally:
        context.close()


@req(GEO, "Медальоны философов", scenario="Без наложений")
@req(GEO, "Политическая карта", scenario="Подписи на исходном виде")
@req(GEO, "Точные связи", scenario="Концы на наборе поворотов и размеров")
@pytest.mark.parametrize(("width", "height"), [(1024, 576), (1366, 768), (1920, 1080)])
def test_demo_globe_medals_labels_arcs(browser, stack, width, height):
    context = shared_reader_context(browser, viewport={"width": width, "height": height})
    page = context.new_page()
    page.set_default_timeout(30000)
    foreign: list[str] = []
    page.on("request", lambda r: None if r.url.startswith(stack.url) else foreign.append(r.url))
    names = ru_names()
    try:
        with page.expect_response(lambda r: PLACES.match(r.url)) as info:
            page.goto(stack.url + "/graph?view=globe")
        page.locator(".geo-globe[aria-busy='false']").wait_for()
        page.locator(".geo-globe").focus()
        frames = 0
        worst = 0.0
        n0 = None
        for key in [None, "Shift+ArrowRight", "Shift+ArrowRight", "+", "+", "Shift+ArrowLeft"]:
            if key:
                page.keyboard.press(key)
            page.evaluate(
                "new Promise(r => requestAnimationFrame(() => requestAnimationFrame(() => r(1))))"
            )
            sc = scene(page)
            assert int(sc["borders"]) > 0
            items = shapes(sc)
            assert collisions(items) == [], (key, collisions(items)[:3])
            assert outside(sc, items) == [], (key, outside(sc, items)[:3])
            for c in sc["countries"]:
                assert c["text"] == names[c["id"]] and RU_TEXT.match(c["text"]), c
            assert arc_faults(sc) == [], (key, arc_faults(sc))
            worst = max(worst, arc_end_error(sc))
            assert all(n["text"] for n in sc["names"])
            if key is None:
                # «Подписи на исходном виде»: на исходном виде не меньше 5 подписей стран.
                assert len(sc["countries"]) >= 5, [c["text"] for c in sc["countries"]]
                assert sum(1 for p in sc["persons"] if drawn(p)) >= 1, (
                    "на исходном виде нет медальонов"
                )
                n0 = len(sc["persons"])
            # Поворот и приближение сцену года не меняют: медальонов в DOM столько же, и каждый
            # нарисован, свёрнут в значок или скрыт поворотом.
            assert len(sc["persons"]) == n0, (key, len(sc["persons"]), n0)
            for p in sc["persons"]:
                assert drawn(p) or p["packed"] == "true" or p["hidden"] == "true", (key, p)
            frames += 1
        assert worst <= 1 and frames == 6
        assert page.evaluate("typeof window.__xss") == "undefined"
        _built(stack, info.value)
        assert foreign == []
    finally:
        context.close()
