"""Записи Wikidata для сценарных тестов ``epochs``: тест сам задаёт ответ ``EntityData``.

Форма ответа — как у ``https://www.wikidata.org/wiki/Special:EntityData/<QID>.json``:
``{"entities": {QID: {labels, descriptions, claims}}}``; значение утверждения — ``mainsnak``
с ``datavalue`` и рангом. QID здесь — только метки синтетических записей.

``no_network`` — ловушка сети: любой настоящий HTTP-запрос (``httpx.HTTPTransport``) или
соединение сокета в тесте — падение. Подменённые транспорты (``httpx.MockTransport``,
``FixtureFetch``) работают.
"""

from __future__ import annotations

import socket
from typing import Any

import httpx
import pytest

PERIOD = "Q11514315"  # «исторический период» — класс периода (P31)
FILM = "Q11424"  # «фильм» — не период


def time_value(value: str, precision: int = 9) -> dict[str, Any]:
    return {
        "type": "time",
        "value": {
            "time": value,
            "timezone": 0,
            "before": 0,
            "after": 0,
            "precision": precision,
            "calendarmodel": "http://www.wikidata.org/entity/Q1985727",
        },
    }


def item_value(qid: str) -> dict[str, Any]:
    return {
        "type": "wikibase-entityid",
        "value": {"entity-type": "item", "numeric-id": int(qid[1:]), "id": qid},
    }


def claim(prop: str, datavalue: dict[str, Any], rank: str = "normal") -> dict[str, Any]:
    return {
        "mainsnak": {"snaktype": "value", "property": prop, "datavalue": datavalue},
        "type": "statement",
        "rank": rank,
    }


def record(
    qid: str,
    *,
    ru: str | None = None,
    en: str | None = None,
    description: str | None = None,
    classes: tuple[str, ...] = (PERIOD,),
    times: dict[str, list[tuple[str, int, str]] | tuple[str, int]] | None = None,
    items: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Ответ ``EntityData``. ``times``: свойство → (время, точность) или список
    (время, точность, ранг); ``items``: свойство → QID-значения (P737 и т. п.)."""
    claims: dict[str, list[dict[str, Any]]] = {}
    if classes:
        claims["P31"] = [claim("P31", item_value(c)) for c in classes]
    for prop, values in (times or {}).items():
        if isinstance(values, tuple):
            values = [(values[0], values[1], "normal")]
        claims[prop] = [claim(prop, time_value(v, p), r) for v, p, r in values]
    for prop, qids in (items or {}).items():
        claims[prop] = [claim(prop, item_value(q)) for q in qids]
    labels = {
        lang: {"language": lang, "value": text} for lang, text in (("ru", ru), ("en", en)) if text
    }
    descriptions = {"ru": {"language": "ru", "value": description}} if description else {}
    return {
        "entities": {
            qid: {
                "type": "item",
                "id": qid,
                "labels": labels,
                "descriptions": descriptions,
                "claims": claims,
            }
        }
    }


def dated(qid: str, start: str, end: str, precision: int = 9, **kw) -> dict[str, Any]:
    """Запись периода с P580/P582."""
    return record(qid, times={"P580": (start, precision), "P582": (end, precision)}, **kw)


def year(y: int) -> str:
    sign = "-" if y < 0 else "+"
    return f"{sign}{abs(y):04d}-00-00T00:00:00Z"


@pytest.fixture
def no_network(monkeypatch):
    """Сеть запрещена: настоящий транспорт httpx и соединения сокетов падают."""
    attempts: list[str] = []

    def refuse_http(self, request):
        attempts.append(str(request.url))
        raise AssertionError(f"сеть запрещена в тесте: {request.url}")

    def refuse_socket(*args, **kwargs):
        attempts.append(repr(args[:1]))
        raise AssertionError("сеть запрещена в тесте (socket)")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse_http)
    monkeypatch.setattr(socket, "create_connection", refuse_socket)
    yield attempts
    assert attempts == [], attempts
