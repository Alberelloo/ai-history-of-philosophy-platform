from __future__ import annotations

from dataclasses import dataclass

import pytest

from philograph.knowledge import schema
from philograph.knowledge.dates import lifespan, parse
from philograph.knowledge.entities import Entities
from philograph.knowledge.registry import OntologyRegistry
from philograph.knowledge.statements import Attribution, Evidence, Provenance, Statements
from philograph.operator.access import migrations as operator_migrations

PARAGRAPHS = {
    "p1": "Кант признавал, что именно Юм пробудил его от догматического сна.",
    "p2": "Учебник: Кант испытал влияние Юма в вопросе о причинности.",
    "p3": "Локк сравнивал ум с чистой доской, на которой опыт пишет свои знаки.",
}


@dataclass
class Onto:
    registry: OntologyRegistry
    entities: Entities
    statements: Statements
    paragraphs: dict[str, str]

    def person(
        self, name: str, birth: str | None = None, death: str | None = None, **external
    ) -> str:
        entity = self.entities.create(
            "person", [("ru", name, "primary")], external=external or None
        )
        if birth:
            self.statements.add(
                entity,
                "lifespan",
                value=lifespan(birth, death).to_json(),
                attributions=[Attribution("common")],
            )
        return entity

    def thing(self, type_: str, name: str, dating: str | None = None) -> str:
        entity = self.entities.create(type_, [("ru", name, "primary")])
        if dating:
            self.statements.add(
                entity,
                "dating",
                value=parse(dating).to_json(),
                attributions=[Attribution("common")],
            )
        return entity

    def sourced(
        self,
        subject,
        type_,
        obj,
        paragraph="p2",
        quote="Кант испытал влияние Юма",
        who="s_textbook",
        run_id=None,
        **kw,
    ):
        return self.statements.add(
            subject,
            type_,
            obj=obj,
            attributions=[Attribution("source", who)],
            evidence=[Evidence(paragraph, quote, source_id=who)],
            provenance=Provenance("extracted", run_id=run_id),
            **kw,
        )


@pytest.fixture
def onto(engine_for, clock) -> Onto:
    engine = engine_for(schema.migrations, operator_migrations)  # журнал действий оператора
    _ = operator_migrations
    registry = OntologyRegistry(engine, clock)
    registry.load_defaults()
    entities = Entities(engine, registry)
    paragraphs = dict(PARAGRAPHS)
    statements = Statements(engine, registry, entities, paragraphs.get, clock)
    return Onto(registry, entities, statements, paragraphs)


# --- справочник через HTTP-маршрут сервиса (add-reference-catalog) ---------------------

TEXTBOOK_N = "s_textbook_n"  # открыт везде
TEXTBOOK_R = "s_textbook_r"  # доступен только в РФ
VISITOR_ADDRESS = "203.0.113.77"


class CatalogService:
    """Приложение сервиса знаний со справочником и картой на одном снимке.

    Библиотека и шлюз моделей — поддельные транспорты: библиотека закрывает «Учебник R» для
    любого региона, кроме ``RU``; любой вызов модели записывается и получает 503 (модель
    недоступна). Время снимка — ``ManualClock`` теста.
    """

    def __init__(self, onto: Onto, clock, max_stale: float = 15.0) -> None:
        import uuid

        import httpx
        from fastapi.testclient import TestClient

        from philograph.knowledge.app import build_app
        from philograph.knowledge.cards import Cards
        from philograph.knowledge.catalog import Catalog, CatalogSettings
        from philograph.knowledge.map import SectionMap
        from philograph.knowledge.snapshot import Snapshots
        from philograph.platform.client import ServiceClient

        from .world import World

        self._uuid = uuid
        self.onto = onto
        self.clock = clock
        self.world = World(onto.entities, onto.statements, onto.paragraphs)
        self.library_calls: list[dict] = []
        self.llm_calls: list[str] = []

        def library(request: httpx.Request) -> httpx.Response:
            self.library_calls.append({"path": request.url.path, **dict(request.url.params)})
            if request.url.path.endswith("/internal/access"):
                region = request.url.params.get("region")
                closed = [] if region == "RU" else [TEXTBOOK_R]
                return httpx.Response(200, json={"closed": closed, "hidden": []})
            return httpx.Response(404, json={"detail": "Not Found"})

        def llm(request: httpx.Request) -> httpx.Response:
            self.llm_calls.append(str(request.url))
            return httpx.Response(503, json={"error": "модель недоступна"})

        self.snapshots = Snapshots(onto.statements.engine, clock)
        self.catalog = Catalog(
            self.snapshots, onto.registry, onto.entities, CatalogSettings(max_stale)
        )
        self.section_map = SectionMap(onto.statements, snapshots=self.snapshots)
        llm_client = ServiceClient("llm", "http://llm", transport=httpx.MockTransport(llm))
        app = build_app(
            onto.statements,
            catalog=self.catalog,
            section_map=self.section_map,
            cards=Cards(onto.statements, None, llm_client),
            library=ServiceClient(
                "library", "http://library/api", transport=httpx.MockTransport(library)
            ),
        )
        self.client = TestClient(app, raise_server_exceptions=False)

    def get(self, path: str = "/v1/catalog", params=None, region: str | None = None):
        """Ответ и ``request_id`` запроса; адрес посетителя передаётся, как это делает шлюз."""
        rid = f"rid-{self._uuid.uuid4().hex[:10]}"
        headers = {"X-Request-Id": rid, "X-Forwarded-For": VISITOR_ADDRESS}
        if region is not None:
            headers["X-Philograph-Region"] = region
        response = self.client.get(path, params=params, headers=headers)
        return response, rid

    def catalog_ok(self, params=None, region: str | None = None) -> tuple[dict, str]:
        response, rid = self.get(params=params, region=region)
        assert response.status_code == 200, response.text
        return response.json(), rid


@pytest.fixture
def svc(onto, clock) -> CatalogService:
    return CatalogService(onto, clock)


# --- запрет сети (improve-extraction-naming, design.md «Наблюдаемость») -----------------


def _allowed_hosts() -> set[str]:
    """Хосты базы тестов (PostgreSQL в CI): к ним соединение разрешено, к остальным — нет."""
    import os
    from urllib.parse import urlsplit

    url = os.environ.get("PHILOGRAPH_TEST_DATABASE_URL", "")
    host = urlsplit(url).hostname if "://" in url else None
    if not host:
        return set()
    if host == "localhost":
        return {"localhost", "127.0.0.1", "::1"}
    return {host}


class NetworkForbidden(AssertionError):
    pass


@pytest.fixture(autouse=True)
def _forbid_network(monkeypatch):
    """Тесты знаний идут без сети: соединение сокета вне базы тестов — ошибка теста.

    Модель — фейковый провайдер шлюза, Wikidata — фикстуры; попытка выйти в сеть падает
    сразу, а не ждёт таймаута, и попадает в ``attempts``."""
    import socket

    allowed = _allowed_hosts()
    attempts: list[str] = []
    original = socket.socket.connect
    original_ex = socket.socket.connect_ex

    def _check(sock, address):
        if sock.family == getattr(socket, "AF_UNIX", object()):
            return
        host = address[0] if isinstance(address, tuple) else str(address)
        if host not in allowed:
            attempts.append(repr(address))
            raise NetworkForbidden(f"сеть запрещена в тестах знаний: {address!r}")

    def connect(sock, address):
        _check(sock, address)
        return original(sock, address)

    def connect_ex(sock, address):
        _check(sock, address)
        return original_ex(sock, address)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    yield attempts
