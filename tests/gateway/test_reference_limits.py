"""abuse-protection, «Бесплатное без ограничений платных»: справочник за настоящим шлюзом.

За шлюзом — настоящее приложение сервиса знаний со справочником (``CatalogService`` из
``tests/knowledge/conftest.py`` не подходит — там нет шлюза, поэтому сборка здесь своя) и
поддельный ассистент, который считает вопросы. Квоты — ``Quota`` шлюза, время — ``ManualClock``.
"""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from philograph.gateway.app import build_app
from philograph.gateway.limits import PAGE_COOKIE, Limits, LimitSettings, Quota
from philograph.knowledge import schema
from philograph.knowledge.app import build_app as knowledge_app
from philograph.knowledge.catalog import Catalog
from philograph.knowledge.entities import Entities
from philograph.knowledge.registry import OntologyRegistry
from philograph.knowledge.snapshot import Snapshots
from philograph.knowledge.statements import Statements
from philograph.operator.access import migrations as operator_migrations

from ..helpers import HostRouter
from ..knowledge.world import World

req = pytest.mark.req
AP = "abuse-protection"
FREE = "Бесплатное без ограничений платных"
UA = {"User-Agent": "Mozilla/5.0 test"}
CATALOG = "/api/knowledge/v1/catalog"


class Stand:
    def __init__(self, engine_for, clock, quotas: dict[str, Quota], rate=1000.0, burst=1000):
        engine = engine_for(schema.migrations, operator_migrations)
        registry = OntologyRegistry(engine, clock)
        registry.load_defaults()
        entities = Entities(engine, registry)
        statements = Statements(engine, registry, entities, {}.get, clock)
        self.world = World(entities, statements)
        self.world.base()
        catalog = Catalog(Snapshots(engine, clock), registry, entities)
        self.asks: list[dict] = []
        assistant = FastAPI()

        @assistant.post("/v1/ask")
        async def ask(request: Request):
            self.asks.append(await request.json())
            return StreamingResponse(
                iter([json.dumps({"type": "done"}) + "\n"]), media_type="application/x-ndjson"
            )

        self.router = HostRouter(
            {"knowledge": knowledge_app(statements, catalog=catalog), "assistant": assistant}
        )
        tick = {"now": 0.0}
        self.tick = tick
        self.limits = Limits(
            LimitSettings(rate_per_second=rate, burst=burst, quotas=quotas, trusted_proxy=True),
            "секрет",
            clock,
            monotonic=lambda: tick["now"],
        )
        self.app = build_app(
            {
                "assistant": "http://assistant",
                "knowledge": "http://knowledge",
                "library": "http://library",
            },
            None,
            transport=self.router,
            limits=self.limits,
        )

    def reader(self, address: str = "203.0.113.5", token: bool = True) -> TestClient:
        client = TestClient(self.app, headers={**UA, "X-Forwarded-For": address})
        if token:
            # Токен страницы выдаёт раздача клиента; здесь клиента нет, токен выписывает шлюз.
            client.cookies.set(PAGE_COOKIE, self.limits.page_token(UA["User-Agent"]))
        return client

    @staticmethod
    def ask(client: TestClient) -> dict:
        response = client.post("/api/assistant/v1/ask", json={"question": "что такое опыт?"})
        return json.loads(response.text.splitlines()[0])


@req(AP, FREE, scenario="Справочник при исчерпанном лимите")
def test_catalog_when_paid_limits_exhausted(engine_for, clock, events):
    stand = Stand(engine_for, clock, {"ask": Quota(1, 1), "graph": Quota(1, 1)})
    reader = stand.reader()
    assert stand.ask(reader) == {"type": "done"}
    assert stand.ask(reader)["reason"] == "visitor_limit"
    graph = {"entity_id": "e1", "recipe": "genesis", "generation": True}
    reader.post("/api/knowledge/v1/graph/build", json=graph)
    reader.post("/api/knowledge/v1/graph/build", json=graph)
    assert events.where("gateway.limit.triggered", operation="graph")  # достройка исчерпана
    # Без cookie токена страницы — тот же посетитель (адрес и браузер).
    plain = stand.reader(token=False)
    assert PAGE_COOKIE not in plain.cookies
    response = plain.get(CATALOG, params={"q": "кант"})
    assert response.status_code == 200
    assert [i["label"] for i in response.json()["items"]] == ["Иммануил Кант"]
    rid = response.headers["X-Request-Id"]
    assert not [e for e in events.of("gateway.limit.triggered") if e.get("request_id") == rid]
    listed = events.where("knowledge.catalog.listed", request_id=rid)
    assert len(listed) == 1 and listed[0]["q_len"] == 4
    assert stand.router.unexpected == []


@req(AP, FREE, scenario="Справочник не тратит квоту")
def test_catalog_does_not_spend_quota(engine_for, clock, events):
    stand = Stand(engine_for, clock, {"ask": Quota(3, 100)})
    reader = stand.reader()
    assert stand.ask(reader) == {"type": "done"}
    statuses = [
        reader.get(CATALOG, params={"q": f"к{'а' * (i % 3)}"}).status_code for i in range(10)
    ]
    assert statuses == [200] * 10
    assert len(events.of("knowledge.catalog.listed")) == 10
    answers = [stand.ask(reader) for _ in range(3)]
    assert answers[0] == {"type": "done"} and answers[1] == {"type": "done"}
    assert answers[2]["type"] == "unavailable" and answers[2]["reason"] == "visitor_limit"
    triggered = events.of("gateway.limit.triggered")
    assert len([e for e in triggered if e.get("operation") == "ask"]) == 1
    assert len(triggered) == 1
    assert len(stand.asks) == 3


@req(AP, FREE, invariant="справочник ограничен только общим лимитом частоты")
def test_catalog_only_rate_limited(engine_for, clock, events):
    stand = Stand(engine_for, clock, {"ask": Quota(1, 1)}, rate=2.0, burst=3)
    bot = stand.reader("192.0.2.1", token=False)
    statuses = [bot.get(CATALOG).status_code for _ in range(5)]
    assert statuses == [200, 200, 200, 429, 429]
    rate = events.where("gateway.limit.triggered", kind="rate")
    assert len(rate) == 2 and all(e.get("operation") is None for e in rate)
    assert len(events.of("knowledge.catalog.listed")) == 3
    stand.tick["now"] += 1.0
    assert bot.get(CATALOG).status_code == 200
    # Ни один запрос справочника не потребовал токена страницы и не тронул квоту вопросов.
    assert not events.where("gateway.limit.triggered", kind="page_token")
    assert stand.ask(stand.reader("192.0.2.1")) == {"type": "done"}


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"q": "кант"},
        {"type": "person"},
        {"sort": "weight", "page": "2", "limit": "1"},
        {"q": "щ" * 201},  # отказ 400 — тоже без лимитов платных
    ],
)
@req(AP, FREE, invariant="справочник без токена страницы и без платных лимитов")
def test_catalog_never_paid(engine_for, clock, events, params):
    stand = Stand(engine_for, clock, {"ask": Quota(0, 0), "graph": Quota(0, 0)})
    plain = stand.reader(token=False)
    response = plain.get(CATALOG, params=params)
    assert response.status_code in (200, 400)
    assert response.json().get("kind") not in ("page_token_required", "rate_limited")
    events_of_rid = [
        e for e in events.items if e.get("request_id") == response.headers["X-Request-Id"]
    ]
    names = [e.name for e in events_of_rid]
    assert "gateway.limit.triggered" not in names
    assert ("knowledge.catalog.listed" in names) != ("knowledge.catalog.rejected" in names)
    assert httpx.codes.is_success(response.status_code) == ("knowledge.catalog.listed" in names)
