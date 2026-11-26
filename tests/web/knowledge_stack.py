"""Настоящий сервис знаний за настоящим шлюзом — для браузерных тестов (задача 4.0).

Стенд ``KnowledgeStack`` поднимает в потоке этого процесса шлюз (раздаёт собранный клиент
``web/dist``), библиотеку с двумя учебниками (``Учебник N`` открыт везде, ``Учебник R`` —
только в РФ) и приложение сервиса знаний на SQLite. Данные онтологии задаёт тест через
``stack.world`` (``tests/knowledge/world.py``: ``Entities``/``Statements``) до открытия страницы.
События сервисов идут в журнал теста (фикстура ``events``); событие запроса страницы находится
по ``request_id`` из заголовка ответа ``X-Request-Id`` (``stack.responses``).

Ловушки:

- запрос шлюза к хосту без приложения (сеть наружу) записывается в ``router.unexpected``;
- вызов модели (``http://llm``) записывается в ``llm_calls`` и получает 503;
- запрос браузера не к стенду обрывается и записывается в ``outside``.

Граф (``POST /v1/graph/build``, add-epoch-context, задача 6.4) достраивает фейковая модель
шлюза моделей (``stack.model`` — ``FakeProvider``: ответы — ``stack.model.push(...)``, вызовы —
``stack.model.calls``); это единственный путь к модели на стенде, его вызовы — не ловушка
``llm_calls``. Сохранение достроенного идёт через очередь ``stack.queue`` — тест запускает её
сам (``stack.queue.run_until_empty()``), как воркер.

Фикстура ``knowledge_stack`` (``conftest.py``) в конце теста требует, чтобы все три списка
были пусты. ``page.route`` в тестах — только для 503, задержки и гонки ответов.
"""

from __future__ import annotations

import asyncio
import socket
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from philograph.gateway.app import build_app as gateway_app
from philograph.knowledge import schema as knowledge_schema
from philograph.knowledge.app import build_app as knowledge_app
from philograph.knowledge.app import library_paragraphs
from philograph.knowledge.cards import Cards
from philograph.knowledge.catalog import Catalog, CatalogSettings
from philograph.knowledge.entities import Entities
from philograph.knowledge.graph import Graphs, GraphSettings
from philograph.knowledge.map import SectionMap
from philograph.knowledge.mentions import Mentions
from philograph.knowledge.polities import PolityLayer
from philograph.knowledge.portraits import Portraits
from philograph.knowledge.registry import OntologyRegistry
from philograph.knowledge.snapshot import Snapshots
from philograph.knowledge.statements import Statements
from philograph.library import schema as library_schema
from philograph.library.app import build_app as library_app
from philograph.library.processing import Pipeline
from philograph.library.reading import Reading
from philograph.library.registry import License, Registry
from philograph.llm import store as llm_store
from philograph.llm.app import build_app as llm_app
from philograph.llm.config import GatewayConfig
from philograph.llm.gateway import LLMGateway
from philograph.llm.providers import FakeProvider
from philograph.llm.templates import Template, TemplateRegistry
from philograph.operator.access import migrations as operator_migrations
from philograph.platform.client import ServiceClient
from philograph.platform.db import make_engine
from philograph.platform.files import FileStore
from philograph.platform.queue import Queue
from philograph.platform.queue import migrations as queue_migrations
from philograph.prompts import PROMPTS

from ..helpers import HostRouter, asgi_transport
from ..knowledge.world import World
from ..library.builders import epub

RU_KIND = "public-domain-ru"
NO_PROPOSALS = '{"statements": []}'
MODEL_CONFIG = {
    "providers": {"fake": {"kind": "fake"}},
    "roles": {"main": {"provider": "fake", "model": "flash"}},
    "prices": {"flash": {"input_cache_miss": 0.3, "input_cache_hit": 0.03, "output": 1.2}},
    "budgets": {"site": {"daily_limit_usd": 2.0}, "filling": {}},
}
BOOK = epub(
    [
        (
            "Глава 1. Опыт",
            "<p>Кант пишет об опыте.</p><p>Юм пишет о причинности.</p>"
            # Абзац для сценариев контекста эпохи (add-epoch-context): уникальная фраза.
            "<p>Тогда парламент низложил короля.</p>",
        )
    ]
)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@dataclass
class Seen:
    """Ответ сервиса знаний, полученный страницей: адрес, статус и ``request_id``."""

    url: str
    status: int
    request_id: str | None


@dataclass
class KnowledgeStack:
    url: str
    world: World
    textbooks: dict[str, str]  # "N" | "R" → id источника библиотеки
    router: HostRouter
    model: Any = None  # FakeProvider достройки графа
    portraits: Any = None  # портреты персон: файлы отдаёт /api/knowledge/v1/portraits/<id>
    queue: Any = None  # очередь сохранения достроенного
    llm_calls: list[str] = field(default_factory=list)
    outside: list[str] = field(default_factory=list)
    responses: list[Seen] = field(default_factory=list)
    paragraphs: dict[str, list[tuple[str, str]]] = field(default_factory=dict)  # "N" → (id, текст)
    # Слой образований (add-historical-polities, 6.1): задержка ответа ``/map/polities``
    # в секундах и «ворота» — ``threading.Event``, до установки которого ответ ждёт.
    polities_delay: float = 0.0
    polities_gate: Any = None
    _server: Any = None
    _thread: Any = None

    # --- браузер ---

    def watch(self, context) -> None:
        """Ловушка сети наружу и запись ответов ``/api/knowledge`` для страницы контекста."""

        def route(r):
            if r.request.url.startswith(self.url):
                r.continue_()
            else:
                self.outside.append(r.request.url)
                r.abort()

        context.route("**/*", route)

        def on_response(response) -> None:
            if "/api/knowledge/" in response.url:
                self.responses.append(
                    Seen(response.url, response.status, response.headers.get("x-request-id"))
                )

        context.on("response", on_response)

    def paragraph(self, key: str, needle: str) -> str:
        """Идентификатор абзаца учебника ``key`` («N» | «R»), содержащего ``needle``."""
        [found] = [pid for pid, text in self.paragraphs[key] if needle in text]
        return found

    def catalog_responses(self) -> list[Seen]:
        return [r for r in self.responses if "/api/knowledge/v1/catalog" in r.url]

    def stop(self) -> None:
        self._server.should_exit = True
        self._thread.join(5)


def start(
    tmp: Path, dist: Path, max_stale: float = 15.0, polities_env: dict[str, str] | None = None
) -> KnowledgeStack:
    """``max_stale`` — окно устарелости справочника (0 — изменения базы видны сразу).

    ``polities_env`` — переменные ``PHILOGRAPH_POLITIES_*`` сервиса знаний (артефакт
    исторических границ, add-historical-polities 6.1). Без них слой образований отвечает 503
    (запасной режим): так идут все тесты глобуса, написанные до этого изменения."""
    # --- библиотека: два учебника ---
    lib_engine = make_engine(
        f"sqlite:///{(tmp / 'library.db').as_posix()}",
        [library_schema.SCHEMA, operator_migrations.schema],
    )
    library_schema.migrations.upgrade(lib_engine)
    operator_migrations.upgrade(lib_engine)
    registry = Registry(lib_engine)
    registry.add_license_kind(
        "public-domain",
        "Общественное достояние",
        "https://example.org/public-domain",
        {"display": True, "external_processing": True, "quoting": True},
    )
    registry.add_license_kind(
        RU_KIND,
        "Общественное достояние по праву РФ",
        None,
        {"display": True, "external_processing": True, "quoting": True},
        regions=["RU"],
    )
    pipeline = Pipeline(registry, FileStore(tmp / "files"), lambda spec: BOOK)
    textbooks = {}
    for key, title, kind in (("N", "Учебник N", "public-domain"), ("R", "Учебник R", RU_KIND)):
        source_id = registry.register(
            "operator",
            title=title,
            authors=["Автор учебника"],
            year=1950,
            language="ru",
            kind="textbook",
            license=License(kind, "public_domain", author_death_years=[1900]),
            scope="public",
            files=[{"name": key, "path": f"{key}.epub"}],
        )
        registry.publish("operator", pipeline.start("operator", source_id))
        textbooks[key] = source_id
    reading = Reading(registry, lib_engine)
    reading.set_default("operator", textbooks["N"])
    paragraphs: dict[str, list[tuple[str, str]]] = {}
    for key, source_id in textbooks.items():
        doc = registry.load_document(registry.get(source_id).published_version)
        paragraphs[key] = [
            (block.id, block.text)
            for chapter in reading.chapters(doc)
            for section in chapter.walk()
            for block in section.blocks
        ]
    library = library_app(reading)

    # --- сервис знаний ---
    engine = make_engine(
        f"sqlite:///{(tmp / 'knowledge.db').as_posix()}",
        [knowledge_schema.migrations.schema, operator_migrations.schema],
    )
    knowledge_schema.migrations.upgrade(engine)
    operator_migrations.upgrade(engine)
    onto = OntologyRegistry(engine)
    onto.load_defaults()
    entities = Entities(engine, onto)
    library_client = ServiceClient(
        "library", "http://library/api", transport=asgi_transport(library)
    )
    statements = Statements(engine, onto, entities, library_paragraphs(library_client))
    llm_calls: list[str] = []

    def llm(request: httpx.Request) -> httpx.Response:
        llm_calls.append(str(request.url))
        return httpx.Response(503, json={"error": "модель недоступна в тесте"})

    llm_client = ServiceClient("llm", "http://llm", transport=httpx.MockTransport(llm))
    snapshots = Snapshots(engine)
    mentions = Mentions(statements, library_client)
    # --- граф: шлюз моделей с фейковым провайдером и очередь сохранения ---
    jobs_engine = make_engine(
        f"sqlite:///{(tmp / 'jobs.db').as_posix()}",
        [llm_store.migrations.schema, queue_migrations.schema],
    )
    llm_store.migrations.upgrade(jobs_engine)
    queue_migrations.upgrade(jobs_engine)
    templates = TemplateRegistry()
    for spec in PROMPTS:
        templates.register(Template(spec.name, spec.instructions, spec.data_slots))
    model = FakeProvider(default=NO_PROPOSALS)
    model_gateway = LLMGateway(
        GatewayConfig.model_validate(MODEL_CONFIG),
        {"fake": model},
        templates,
        llm_store.Store(jobs_engine),
    )
    graph_llm = ServiceClient("llm", "http://llm", transport=asgi_transport(llm_app(model_gateway)))
    queue = Queue(jobs_engine)
    graphs = Graphs(statements, graph_llm, queue, GraphSettings(min_edges=5, max_nodes=60))
    portraits = Portraits(engine, FileStore(tmp / "portraits"))
    knowledge = knowledge_app(
        statements,
        portraits=portraits,
        library=library_client,
        mentions=mentions,
        cards=Cards(statements, mentions, llm_client),
        section_map=SectionMap(statements, snapshots=snapshots),
        graphs=graphs,
        catalog=Catalog(snapshots, onto, entities, CatalogSettings(max_stale_seconds=max_stale)),
        polity_layer=PolityLayer.from_env(polities_env) if polities_env is not None else None,
    )
    world = World(entities, statements)
    for key, source_id in textbooks.items():
        world.source(source_id, f"Учебник {key}")

    # --- шлюз ---
    import uvicorn

    holder: dict[str, KnowledgeStack] = {}

    async def knowledge_paced(scope, receive, send):
        """Задержка и ворота ответа ``/map/polities`` (сценарии задержанного слоя)."""
        if scope["type"] == "http" and scope["path"].endswith("/map/polities"):
            stack_ = holder.get("stack")
            if stack_ is not None and stack_.polities_delay:
                await asyncio.sleep(stack_.polities_delay)
            if stack_ is not None and stack_.polities_gate is not None:
                await asyncio.to_thread(stack_.polities_gate.wait, 60)
        await knowledge(scope, receive, send)

    router = HostRouter({"library": library, "knowledge": knowledge_paced})
    gateway = gateway_app(
        {
            "library": "http://library",
            "knowledge": "http://knowledge",
            "assistant": "http://assistant",
        },
        dist,
        transport=router,
    )
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(gateway, host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.02)  # запуск сервера, не проверка поведения
    stack = KnowledgeStack(
        f"http://127.0.0.1:{port}", world, textbooks, router, model, queue, llm_calls
    )
    stack.paragraphs = paragraphs
    holder["stack"] = stack
    stack.portraits = portraits
    stack._server, stack._thread = server, thread
    return stack
