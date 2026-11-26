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


class RecordFetch:
    """Функция загрузки ``wikidata.Fetch`` (адрес → JSON) по данным теста, без сети.

    ``records`` — QID → ответ ``EntityData``; ``searches`` — (название, язык) → найденные
    ``[{id, label, description}]`` (нет — пустой поиск); QID из ``failing`` и записи, которых
    нет, — сбой загрузки. Все адреса записываются в ``calls``."""

    def __init__(self, records=None, searches=None, failing=()) -> None:
        self.records: dict[str, dict[str, Any]] = dict(records or {})
        self.searches: dict[tuple[str, str], list[dict[str, Any]]] = dict(searches or {})
        self.failing = set(failing)
        self.calls: list[str] = []

    def entity_calls(self) -> list[str]:
        return [c for c in self.calls if "/Special:EntityData/" in c]

    def search_calls(self) -> list[str]:
        return [c for c in self.calls if "wbsearchentities" in c]

    def __call__(self, url: str) -> dict[str, Any]:
        from urllib.parse import parse_qs, urlsplit

        from philograph.knowledge.wikidata import WikidataError

        self.calls.append(url)
        parts = urlsplit(url)
        assert parts.scheme == "https" and parts.hostname == "www.wikidata.org", url
        if parts.path.startswith("/wiki/Special:EntityData/"):
            qid = parts.path.rsplit("/", 1)[1].removesuffix(".json")
            if qid in self.failing or qid not in self.records:
                raise WikidataError(f"сбой загрузки (тест): {qid}")
            return self.records[qid]
        if parts.path == "/w/api.php":
            query = parse_qs(parts.query)
            assert query["action"] == ["wbsearchentities"], url
            key = (query["search"][0], query["language"][0])
            return {"search": self.searches.get(key, [])}
        raise AssertionError(f"неожиданный адрес {url}")
