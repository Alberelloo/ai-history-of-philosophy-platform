"""Стенд извлечения без библиотеки и сети (improve-extraction-naming и следующие изменения).

Извлечение идёт настоящим путём ``Filling.extract_version``: шлюз моделей — настоящий
``LLMGateway`` поверх фейкового провайдера с очередью ответов, библиотека — поддельный
транспорт, который отдаёт абзацы версии по контракту
``GET /v1/internal/versions/{id}/paragraphs``. Каждый запрос знаний к шлюзу записывается
целиком (шаблон, данные, ``json_schema``), чтобы тест проверял, что именно ушло модели.
"""

from __future__ import annotations

import json
import uuid
from collections import deque
from typing import Any

import httpx
from sqlalchemy import func, select

from philograph.knowledge import schema as t
from philograph.knowledge.filling import Filling
from philograph.llm import store as llm_store
from philograph.llm.app import build_app as llm_app
from philograph.llm.config import GatewayConfig
from philograph.llm.gateway import LLMGateway
from philograph.llm.providers import Completion, FakeProvider, Usage
from philograph.llm.templates import Template, TemplateRegistry
from philograph.platform.client import ServiceClient
from philograph.platform.queue import migrations as queue_migrations
from philograph.prompts import PROMPTS

from ..helpers import asgi_transport

CONFIG = {
    "providers": {"fake": {"kind": "fake"}},
    "roles": {r: {"provider": "fake", "model": "flash"} for r in ("main", "strong")},
    "prices": {"flash": {"input_cache_miss": 0.3, "input_cache_hit": 0.03, "output": 1.2}},
    "retry_base_seconds": 0.0,
    "schema_retries": 0,
}


class Scripted(FakeProvider):
    """Ответы модели по очереди; пусто — нет утверждений."""

    def __init__(self) -> None:
        super().__init__()
        self.replies: deque = deque()

    def generate(self, request):
        self.calls.append(request)
        reply = self.replies.popleft() if self.replies else {"statements": []}
        text = reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)
        return Completion(text, Usage(1000, 0, 200))


class Recording(httpx.BaseTransport):
    """Транспорт, который записывает тела запросов и передаёт их дальше."""

    def __init__(self, inner: httpx.BaseTransport) -> None:
        self.inner = inner
        self.bodies: list[dict[str, Any]] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        body = request.read()
        if request.url.path.endswith("/structured") and body:
            self.bodies.append(json.loads(body))
        return self.inner.handle_request(request)


class PassedGateway(httpx.BaseTransport):
    """Шлюз, ответ которого уже прошёл его проверку схемы: тело ``{"value": ответ}``.

    Нужен сценариям, где сервер знаний проверяет ответ сам и не полагается на шлюз
    (тип вне реестра в ``entities``): настоящий шлюз отбросил бы такой ответ раньше."""

    def __init__(self, model: Scripted) -> None:
        self.model = model

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/structured"):
            reply = self.model.replies.popleft() if self.model.replies else {"statements": []}
            self.model.calls.append(json.loads(request.read()))
            return httpx.Response(200, json={"value": reply})
        if request.url.path.endswith("/spend"):
            return httpx.Response(200, json=[])
        return httpx.Response(404, json={"detail": "Not Found"})


class Stand:
    def __init__(
        self, onto, engine_for, clock, fragment_size: int = 8, passed_gateway: bool = False
    ) -> None:
        self.onto = onto
        engine = engine_for(llm_store.migrations, queue_migrations)
        templates = TemplateRegistry()
        for spec in PROMPTS:
            templates.register(Template(spec.name, spec.instructions, spec.data_slots))
        self.model = Scripted()
        gateway = LLMGateway(
            GatewayConfig.model_validate(CONFIG),
            {"fake": self.model},
            templates,
            llm_store.Store(engine),
            clock=clock,
            sleep=lambda _s: None,
        )
        inner = PassedGateway(self.model) if passed_gateway else asgi_transport(llm_app(gateway))
        self.llm_transport = Recording(inner)
        self.versions: dict[str, dict[str, Any]] = {}
        self.library_calls: list[str] = []
        llm = ServiceClient("llm", "http://llm", transport=self.llm_transport)
        library = ServiceClient(
            "library", "http://library/api", transport=httpx.MockTransport(self._library)
        )
        self.filling = Filling(
            onto.statements, llm, library, clock=clock, fragment_size=fragment_size
        )

    def _library(self, request: httpx.Request) -> httpx.Response:
        self.library_calls.append(request.url.path)
        parts = request.url.path.split("/")
        if "versions" in parts and parts[-1] == "paragraphs":
            vid = parts[parts.index("versions") + 1]
            if vid in self.versions:
                return httpx.Response(200, json=self.versions[vid])
        return httpx.Response(404, json={"detail": "Not Found"})

    def version(
        self, paragraphs: list[str | tuple[str, str]], lang: str = "ru"
    ) -> tuple[str, list[str]]:
        """Новая опубликованная версия нового источника; абзацы — текст или (текст, язык)."""
        vid = f"v_{uuid.uuid4().hex[:12]}"
        source = f"s_{uuid.uuid4().hex[:12]}"
        chapter = f"sec_{uuid.uuid4().hex[:8]}"
        rows = []
        for i, item in enumerate(paragraphs, start=1):
            text, plang = item if isinstance(item, tuple) else (item, lang)
            pid = f"p_{uuid.uuid4().hex[:12]}"
            self.onto.paragraphs[pid] = text
            rows.append(
                {
                    "id": pid,
                    "text": text,
                    "lang": plang,
                    "ord": i,
                    "section_id": chapter,
                    "section_title": "",
                    "chapter_id": chapter,
                    "searchable": True,
                }
            )
        self.versions[vid] = {
            "source_id": source,
            "source_title": "Учебник",
            "chapters": {chapter: ""},
            "version_id": vid,
            "scope": "public",
            "published": True,
            "permissions": {"display": True, "external_processing": True, "quoting": True},
            "external_processing": True,
            "regions": None,
            "paragraphs": rows,
            "headings": [],
            "footnotes": [],
        }
        return vid, [r["id"] for r in rows]

    def extract(self, paragraphs, reply: dict[str, Any] | str, lang: str = "ru"):
        """Одна версия, один фрагмент, один ответ модели. Возвращает (version_id, абзацы)."""
        vid, ids = self.version(paragraphs, lang)
        self.model.replies.append(reply)
        self.filling.extract_version(vid)
        return vid, ids

    # --- изоляция примеров property-тестов ---------------------------------------------

    RESET_TABLES = (
        "attributions",
        "entities",
        "evidence",
        "external_ids",
        "filling_runs",
        "graph_extensions",
        "mentions",
        "merges",
        "names",
        "portraits",
        "review_items",
        "statement_views",
        "statements",
    )

    def reset(self) -> None:
        """Пустая онтология при том же реестре: пример property-теста не видит прошлых."""
        by_name = {tb.name: tb for tb in t.metadata.sorted_tables}
        with self.onto.statements.engine.begin() as conn:
            for name in self.RESET_TABLES:
                conn.execute(by_name[name].delete())

    # --- чтение базы -----------------------------------------------------------------

    def count(self, table, **where) -> int:
        query = select(func.count()).select_from(table)
        for column, value in where.items():
            query = query.where(table.c[column] == value)
        with self.onto.statements.engine.begin() as conn:
            return conn.scalar(query)

    def entities_of(self, type_: str) -> int:
        return self.count(t.entities, type=type_)

    def statements(self) -> list[dict[str, Any]]:
        with self.onto.statements.engine.begin() as conn:
            ids = list(conn.scalars(select(t.statements.c.id)))
        return [self.onto.statements.get(i) for i in ids]
