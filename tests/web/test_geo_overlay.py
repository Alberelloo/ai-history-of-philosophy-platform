"""Глобус: наложенные элементы вида — препятствия раскладки (rework-globe-political-map, 6а.11, Д10).

Сценарий «Наложенные элементы вида» и нормативные фразы дельты
``openspec/changes/archive/2026-11-26-rework-globe-political-map/specs/geo-timeline/spec.md``: правило 5
«Политической карты», правило 3 и инвариант раскладки «Медальонов философов».

Прямоугольники наложенных элементов тест меряет сам (``getBoundingClientRect`` относительно
вида), а подпись источника, кнопку «Клавиши» и подсказку к ней находит по тексту и роли, а не
по ``data-geo-overlay``: иначе проверка пометки была бы тавтологией. Фигуры глобуса — по
прямоугольникам элементов (``shapes``), геометрия пересечений — из «Медальонов философов».
"""

# ruff: noqa: E501 — встроенные скрипты страницы и имена инвариантов спецификации

from __future__ import annotations

import pytest

from .geo_helpers import (
    CITIES,
    COUNTRY_MIN_LABELS,
    KEYS_TEXT,
    SIZES,
    crowd,
    drag_frames,
    errors,
    focus_globe,
    geo_built,
    globe_ready,
    obstacle_rects,
    open_globe,
    overlap,
    overlays,
    press,
    scene,
    settle,
    shapes,
)

req = pytest.mark.req
GEO = "geo-timeline"
MED = "Медальоны философов"
POL = "Политическая карта"


def overlay_faults(sc: dict, ov: dict, *, moving: bool = False) -> list:
    """Фигуры глобуса (нарисованные медальоны, значки «+N», значки событий, подписи персон
    и стран), пересекающие видимый наложенный элемент глубже 0,5 px."""
    bad = []
    rects = obstacle_rects(ov)
    for kind, ident, shape in shapes(sc):
        for what, r in rects:
            if overlap(shape, r):
                bad.append((kind, ident, what, tuple(round(v, 1) for v in shape[1:])))
    # В кадрах движения подписи не рисуются (инвариант раскладки «Медальонов»).
    if moving and sc["names"]:
        bad.append(("подписи персон в кадре движения", len(sc["names"])))
    return bad


def marks_faults(ov: dict, *, hint: bool) -> list:
    """Подпись источника и кнопка «Клавиши» (и раскрытая подсказка) найдены по тексту/роли
    и помечены нужным значением ``data-geo-overlay``."""
    want = {"coast": "coast", "keys": "keys"} | ({"keys-hint": "keys-hint"} if hint else {})
    got = {r["what"]: r["mark"] for r in ov["found"] if r["w"] > 0 and r["h"] > 0}
    return [(what, got.get(what), mark) for what, mark in want.items() if got.get(what) != mark]


def open_view(knowledge_context, knowledge_stack, dataset: str, width: int, height: int):
    if dataset == "europe30":
        crowd(knowledge_stack.world, CITIES[:30], 1)
        page, response = open_globe(
            knowledge_context,
            knowledge_stack,
            "/graph?view=globe&t=1750",
            width=width,
            height=height,
            reduced_motion="reduce",
        )
        return page, response
    context = knowledge_context(width, height, reduced_motion="reduce")
    page = context.new_page()
    page.set_default_timeout(30000)
    page.goto(knowledge_stack.url + "/graph?fixture=dense&view=globe")
    globe_ready(page)
    return page, None


def open_hint(page) -> None:
    page.get_by_role("button", name=KEYS_TEXT).click()
    page.locator(".geo-globe[aria-busy='false']").wait_for()
    settle(page)


@req(GEO, MED, scenario="Наложенные элементы вида")
@req(
    GEO,
    MED,
    invariant="нарисованные медальоны, значки, подписи персон и стран не пересекают прямоугольники видимых [data-geo-overlay]; в кадрах движения медальон или значок, пересёкший наложенный элемент, скрыт",
)
@pytest.mark.parametrize("dataset", ["europe30", "dense"])
@pytest.mark.parametrize(("width", "height"), SIZES)
def test_overlay_elements(knowledge_context, knowledge_stack, events, dataset, width, height):
    page, response = open_view(knowledge_context, knowledge_stack, dataset, width, height)
    frames = []
    ov = overlays(page)
    assert marks_faults(ov, hint=False) == [], (width, dataset, ov["found"])
    sc = scene(page)
    assert len(sc["countries"]) >= COUNTRY_MIN_LABELS, (
        width,
        dataset,
        sc["zoom"],
        len(sc["countries"]),
    )
    assert overlay_faults(sc, ov) == [], (width, dataset, "исходный вид", overlay_faults(sc, ov))
    frames.append("home")
    focus_globe(page)
    for i in range(12):
        press(
            page, "Shift+ArrowRight" if i < 6 else "Shift+ArrowUp" if i < 8 else "Shift+ArrowLeft"
        )
        settle(page)
        sc, ov = scene(page), overlays(page)
        assert overlay_faults(sc, ov) == [], (width, dataset, sc["center"], overlay_faults(sc, ov))
        frames.append(sc["center"])
    # Раскрытая подсказка «Клавиши»: исходный вид и приближение.
    press(page, "0")
    settle(page)
    open_hint(page)
    for key in (None, "+", "+"):
        if key:
            focus_globe(page)
            press(page, key)
            settle(page)
        sc, ov = scene(page), overlays(page)
        assert ov["expanded"] == "true", ov["expanded"]
        assert marks_faults(ov, hint=True) == [], (width, dataset, ov["found"])
        assert any(r["kind"] == "keys-hint" for r in ov["marked"]), ov["marked"]
        assert overlay_faults(sc, ov) == [], (
            width,
            dataset,
            "подсказка",
            key,
            overlay_faults(sc, ov),
        )
        frames.append(("hint", sc["zoom"]))
    # Кадры перетаскивания (кнопка мыши нажата).
    for shot in drag_frames(page, -120, 40, frames=3):
        assert overlay_faults(shot, ov, moving=True) == [], (
            width,
            dataset,
            "перетаскивание",
            overlay_faults(shot, ov, moving=True),
        )
        frames.append(("drag", shot["center"]))
    assert len(frames) == 1 + 12 + 3 + 3, frames
    if response is not None:
        geo_built(events, response)
    errors(page)
