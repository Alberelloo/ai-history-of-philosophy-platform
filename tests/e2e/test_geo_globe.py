"""Глобус на живом продукте (geo-timeline, задача 7.7).

Демо-данные стенда (``scripts/seed_demo.py``) задают места с координатами и людей без места.
Ожидания здесь — только из спецификации, без чисел демо-набора: на глобусе есть отметки,
счётчик «N без места» совпадает с полем ``unplaced`` события ``knowledge.geo.built`` того же
запроса, внешних запросов нет. На машине агента (1 ГБ RAM, без Docker) не прогоняется —
прогон в CI или у ведущего.
"""

from __future__ import annotations

import re

import pytest

from .conftest import reader_context, wait_logs

req = pytest.mark.req
pytestmark = pytest.mark.e2e
GEO = "geo-timeline"
PLACES = re.compile(r".*/api/knowledge/v1/map/places(\?.*)?$")


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
        assert page.locator("[data-geo-place]").count() >= 1
        assert page.locator("[data-geo-row]").count() == page.locator("[data-geo-place]").count()
        counter = page.locator("[data-geo-unplaced]")
        text = counter.inner_text()
        found = re.fullmatch(r"(\d+) без места", text.strip())
        assert found, text
        rid = info.value.headers.get("x-request-id")
        built = wait_logs(
            stack,
            "knowledge",
            lambda e: e.get("event") == "knowledge.geo.built" and e.get("request_id") == rid,
            20,
        )
        assert len(built) == 1, rid
        assert built[0]["unplaced"] == int(found.group(1))
        assert built[0]["places"] >= 1
        assert foreign == []
    finally:
        context.close()
