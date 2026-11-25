"""Юнит-тесты маршрута ``GET /v1/catalog`` (``knowledge/app.py``): разбор параметров и регион."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from philograph.knowledge import schema as t
from philograph.knowledge.app import build_app
from philograph.knowledge.catalog import Catalog
from philograph.knowledge.snapshot import Snapshots
from philograph.platform.client import ServiceClient

TEXTBOOK = "s_textbook"


def library(closed: list[str], calls: list[dict], fail: bool = False) -> ServiceClient:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(dict(request.url.params))
        if fail:
            return httpx.Response(503)
        return httpx.Response(200, json={"closed": closed, "hidden": []})

    return ServiceClient("library", "http://library/api", transport=httpx.MockTransport(handler))


@pytest.fixture
def make(onto, clock):
    def make(closed=(), fail=False):
        calls: list[dict] = []
        catalog = Catalog(Snapshots(onto.statements.engine, clock), onto.registry, onto.entities)
        app = build_app(
            onto.statements, catalog=catalog, library=library(list(closed), calls, fail)
        )
        return TestClient(app), calls

    return make


def mention(onto, entity_id: str) -> None:
    with onto.statements.engine.begin() as conn:
        conn.execute(
            t.mentions.insert().values(
                target_id="p1",
                target_kind="paragraph",
                source_id=TEXTBOOK,
                entity_id=entity_id,
                start=0,
                end=4,
                method="name",
            )
        )


@pytest.fixture
def kant(onto):
    kant = onto.person("Иммануил Кант", "1724", "1804")
    onto.entities.source_entity(TEXTBOOK, "Учебник R")
    return kant


def test_repeated_type_and_no_region_call(make, onto, kant):
    onto.thing("work", "Критика чистого разума", "1781")
    onto.thing("concept", "Причинность")
    client, calls = make()
    body = client.get("/v1/catalog", params=[("type", "person"), ("type", "work")]).json()
    assert body["total"] == 2 and calls == []


@pytest.mark.parametrize(
    ("params", "kind"),
    [
        ({"limit": "abc"}, "bad_query"),
        ({"page": "0"}, "bad_query"),
        ({"type": "dragon"}, "unknown_type"),
    ],
)
def test_rejections_are_400(make, kant, events, params, kind):
    client, _ = make()
    response = client.get("/v1/catalog", params=params)
    assert response.status_code == 400 and response.json()["kind"] == kind
    assert len(events.of("knowledge.catalog.rejected")) == 1


def test_region_header_and_closed_textbook(make, onto, kant, events):
    mention(onto, kant)
    client, calls = make(closed=[TEXTBOOK])
    body = client.get(
        "/v1/catalog",
        params={"textbook": TEXTBOOK, "q": "кант"},
        headers={"X-Philograph-Region": "DE"},
    ).json()
    assert body["textbook_closed"] is True and body["items"] == []
    assert calls == [{"region": "DE"}]
    assert events.of("knowledge.catalog.listed")[-1].get("textbook_closed") is True
    open_client, _ = make(closed=[])
    assert open_client.get("/v1/catalog", params={"textbook": TEXTBOOK}).json()["total"] == 1


def test_library_down_with_textbook_is_503(make, onto, kant):
    mention(onto, kant)
    client, _ = make(fail=True)
    response = client.get("/v1/catalog", params={"textbook": TEXTBOOK})
    assert response.status_code == 503
    assert response.json()["kind"] == "knowledge_unavailable"
    assert client.get("/v1/catalog").status_code == 200  # без раздела библиотека не нужна


def test_old_name_lookup_unchanged(make, onto, kant):
    onto.person("Кант")
    onto.person("Кантор")
    client, _ = make()
    found = client.get("/v1/entities", params={"name": "Кант"}).json()
    assert len(found) == 1 and set(found[0]) == {"id", "type", "primary", "names"}
