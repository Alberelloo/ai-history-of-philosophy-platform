"""Стенд поиска: библиотека, сервис LLM и поиск общаются через свои HTTP-интерфейсы.

Модель эмбеддингов — тестовая: слова сводятся к понятиям, поэтому «из прошлого нельзя вывести
будущее» близко к абзацу о проблеме индукции, а «чистая доска» — к «blank slate». Это
проверяет механику смыслового канала; качество настоящей модели меряет оценка (этап 3).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import pytest
from qdrant_client import QdrantClient

from philograph.library import schema as library_schema
from philograph.library.app import build_app as library_app
from philograph.library.processing import Pipeline
from philograph.library.reading import Reading
from philograph.library.registry import License, Registry
from philograph.llm import store as llm_store
from philograph.llm.app import build_app as llm_app
from philograph.llm.config import GatewayConfig
from philograph.llm.gateway import LLMGateway
from philograph.llm.providers import TransientProviderError, Usage
from philograph.llm.templates import TemplateRegistry
from philograph.operator.access import migrations as operator_migrations
from philograph.platform.client import ServiceClient
from philograph.platform.files import FileStore
from philograph.platform.queue import Queue
from philograph.platform.queue import migrations as queue_migrations
from philograph.search import schema
from philograph.search.app import subscribe
from philograph.search.clients import LibraryHttp, LlmEmbedder
from philograph.search.indexing import Indexer, IndexSettings
from philograph.search.searching import Searcher
from philograph.search.text import normalize
from philograph.search.vectors import VectorStore

from ..helpers import asgi_transport

CONCEPTS = {
    "induction": [
        "индукция",
        "будущее",
        "прошлое",
        "вывести",
        "future",
        "past",
        "induction",
        "предсказать",
        "привычка",
    ],
    "slate": ["доска", "чистый", "slate", "blank", "tabula", "rasa"],
    "causality": ["причинность", "причина", "causation", "cause", "следствие"],
    "knowledge": ["знание", "познание", "knowledge", "опыт", "experience"],
    "reason": ["рассудок", "разум", "категория", "understanding", "reason"],
    "ethics": ["добродетель", "благо", "virtue"],
}
LEMMA_TO_CONCEPT = {normalize(w): i for i, (_, ws) in enumerate(CONCEPTS.items()) for w in ws}


@dataclass
class ConceptProvider:
    calls: list[list[str]] = field(default_factory=list)
    fail: bool = False

    def embed(self, model, texts, timeout_seconds):
        if self.fail:
            raise TransientProviderError("провайдер эмбеддингов недоступен")
        self.calls.append(list(texts))
        vectors = []
        for text in texts:
            v = [0.0] * (len(CONCEPTS) + 1)
            for w in text.replace(",", " ").replace(".", " ").split():
                index = LEMMA_TO_CONCEPT.get(normalize(w))
                if index is not None:
                    v[index] += 1.0
            v[-1] = 0.05  # чтобы у текста без понятий был ненулевой вектор
            norm = math.sqrt(sum(x * x for x in v))
            vectors.append([x / norm for x in v])
        return vectors, Usage(sum(len(t) // 4 for t in texts), 0, 0)

    def generate(self, request):  # pragma: no cover — поиску не нужно
        raise NotImplementedError

    def stream(self, request):  # pragma: no cover
        raise NotImplementedError


LLM_CONFIG = {
    "providers": {"concept": {"kind": "fake"}},
    "roles": {"embeddings": {"provider": "concept", "model": "concept-v1"}},
    "prices": {"concept-v1": {"input_cache_miss": 0.02, "input_cache_hit": 0.02}},
    "budgets": {"site": {"daily_limit_usd": 2.0}, "filling": {}},
    "retry_base_seconds": 0.0,
    "max_retries": 0,
}

TEXTBOOK = (
    "Глава 1. Юм\n\nЮм показал, что из прошлого опыта нельзя с необходимостью заключить о "
    "будущем: это проблема индукции.\n\nПо Юму, причинность есть привычка ума, а не "
    "наблюдаемая связь.\n\nХьюм в старых переводах — тот же Юм.\n\n"
    "Глава 2. Локк\n\nЛокк сравнивал ум с чистой доской, на которой опыт пишет свои знаки.\n\n"
    "Образ tabula rasa восходит к Аристотелю.\n\n"
    "Глава 3. Кант\n\nКант отвечает Юму: причинность — категория рассудка.\n\n"
    "Канту важно, что категории делают опыт возможным.\n\n"
    "Учение Канта о рассудке изложено в первой Критике.\n\n"
    "Кантом сформулированы антиномии разума.\n\n"
    "Именной указатель\n\nЮм 12, 15\n"
).encode()
ENGLISH = (
    b"Chapter 1\n\nLocke described the mind at birth as a blank slate.\n\n"
    b"Hume on the future and the past of experience.\n"
)


@dataclass
class Rig:
    registry: Registry
    pipeline: Pipeline
    indexer: Indexer
    searcher: Searcher
    queue: Queue
    provider: ConceptProvider
    llm: LLMGateway
    files: dict[str, bytes]
    ids: dict[str, str]

    def publish(self, key: str) -> str:
        version = self.pipeline.start("operator", self.ids[key])
        self.registry.publish("operator", version)
        self.sync()
        return version

    def sync(self) -> None:
        self.pipeline.dispatch_outbox(self.queue)
        self.queue.run_until_empty()

    def search(self, text: str, **kwargs):
        from philograph.search.searching import Query

        return self.searcher.search(Query(text=text, **kwargs))

    def paragraph(self, key: str, needle: str) -> str:
        doc = self.registry.load_document(self.registry.get(self.ids[key]).published_version)
        return next(b.id for _, b in doc.blocks() if needle in b.text)


@pytest.fixture
def rig(engine_for, clock, tmp_path) -> Rig:
    engine = engine_for(
        library_schema.migrations,
        operator_migrations,
        queue_migrations,
        schema.migrations,
        llm_store.migrations,
    )
    registry = Registry(engine, clock)
    registry.add_license_kind(
        "pd",
        "Общественное достояние",
        None,
        {"display": True, "external_processing": True, "quoting": True},
    )
    registry.add_license_kind(
        "local",
        "Только показ",
        None,
        {"display": True, "external_processing": False, "quoting": True},
    )
    files = {"ru.txt": TEXTBOOK, "en.txt": ENGLISH}
    pipeline = Pipeline(
        registry, FileStore(tmp_path / "files"), lambda s: files[s["path"]], clock=clock
    )
    lic = License("pd", "public_domain", author_death_years=[1900])
    ids = {
        "ru": registry.register(
            "operator",
            title="Теория познания",
            authors=["А"],
            language="ru",
            kind="textbook",
            license=lic,
            scope="public",
            files=[{"name": "r", "path": "ru.txt"}],
        ),
        "en": registry.register(
            "operator",
            title="Empiricism",
            authors=["B"],
            language="en",
            kind="primary",
            license=lic,
            scope="public",
            files=[{"name": "e", "path": "en.txt"}],
        ),
    }
    reading = Reading(registry, engine)
    library = ServiceClient(
        "library", "http://library/api", transport=asgi_transport(library_app(reading))
    )
    provider = ConceptProvider()
    gateway = LLMGateway(
        GatewayConfig.model_validate(LLM_CONFIG),
        {"concept": provider},
        TemplateRegistry(),
        llm_store.Store(engine),
        clock=clock,
        sleep=lambda _s: None,
    )
    llm = ServiceClient("llm", "http://llm", transport=asgi_transport(llm_app(gateway)))
    embedder = LlmEmbedder(llm, "concept-v1", len(CONCEPTS) + 1)
    vectors = VectorStore(QdrantClient(":memory:"))
    indexer = Indexer(
        engine,
        LibraryHttp(library),
        embedder,
        vectors,
        IndexSettings(chunk_chars=120, chunk_overlap=20),
    )
    searcher = Searcher(engine, embedder, vectors, lambda: indexer.active_collection)
    queue = Queue(engine, clock)
    subscribe(queue, indexer)
    return Rig(registry, pipeline, indexer, searcher, queue, provider, gateway, files, ids)
