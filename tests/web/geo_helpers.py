"""Общее для браузерных тестов глобуса (geo-timeline, задачи 7.4–7.6).

Данные задаёт каждый тест сам через ``stack.world`` (настоящий сервис знаний, ``knowledge_stack``).
Ожидания берутся из спецификации ``openspec/changes/add-geo-timeline/specs/geo-timeline/spec.md``.
Клиент событий журнала не пишет: серверный якорь — ``knowledge.geo.built`` по ``request_id``
ответа ``/map/places``, полученного страницей (``geo_built``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse

from philograph.knowledge.dates import parse
from philograph.knowledge.statements import Attribution, Provenance

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
    page.set_default_timeout(15000)
    if before is not None:
        before(page)
    with page.expect_response(lambda r: PLACES_API.match(r.url)) as info:
        page.goto(stack.url + path)
    globe_ready(page)
    return page, info.value


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


def marks(page) -> dict[str, dict[str, Any]]:
    return page.evaluate(
        """() => Object.fromEntries([...document.querySelectorAll('[data-geo-place]')].map(e => {
            const r = e.getBoundingClientRect();
            return [e.dataset.geoPlace, {
              people: Number(e.dataset.people), age: Number(e.dataset.age),
              hidden: e.dataset.hidden, unverified: e.dataset.unverified,
              role: e.dataset.role ?? null, dim: e.dataset.dim ?? null,
              opacity: Number(getComputedStyle(e).opacity),
              transform: e.getAttribute('transform'),
              x: r.x + r.width / 2, y: r.y + r.height / 2,
            }];
        }))"""
    )


def links(page) -> dict[str, dict[str, Any]]:
    return page.evaluate(
        """() => Object.fromEntries([...document.querySelectorAll('[data-geo-link]')].map(e => [
            e.dataset.geoLink, {
              status: e.dataset.status, generated: e.dataset.generated,
              age: Number(e.dataset.age), role: e.dataset.role ?? null, dim: e.dataset.dim ?? null,
              opacity: Number(getComputedStyle(e).opacity),
              d: e.querySelector('path')?.getAttribute('d') ?? null,
            }]))"""
    )


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
