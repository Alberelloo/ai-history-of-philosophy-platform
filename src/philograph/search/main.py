"""Точка входа сервиса поиска: ``uvicorn philograph.search.main:app``."""

from __future__ import annotations

import os
import threading

from qdrant_client import QdrantClient
from sqlalchemy import text

from philograph import __version__
from philograph.platform import events
from philograph.platform.client import ServiceClient
from philograph.platform.db import make_engine
from philograph.platform.health import Health
from philograph.search import schema
from philograph.search.app import build_app, subscribe
from philograph.search.clients import LibraryHttp, LlmEmbedder
from philograph.search.indexing import Indexer
from philograph.search.searching import Searcher
from philograph.search.vectors import VectorStore


def components(env: dict[str, str]) -> tuple[Indexer, Searcher, Health]:
    engine = make_engine(env["PHILOGRAPH_DATABASE_URL"], [schema.SCHEMA])
    schema.migrations.upgrade(engine)
    library = LibraryHttp(ServiceClient("library", env["PHILOGRAPH_LIBRARY_URL"] + "/api"))
    embedder = LlmEmbedder(
        ServiceClient("llm", env["PHILOGRAPH_LLM_URL"], timeout=30),
        env["PHILOGRAPH_EMBEDDING_MODEL"],
        int(env["PHILOGRAPH_EMBEDDING_DIMENSION"]),
    )
    if env.get("PHILOGRAPH_QDRANT_URL"):
        qdrant = QdrantClient(url=env["PHILOGRAPH_QDRANT_URL"])
    else:  # стенд без Docker: Qdrant внутри процесса, данные в каталоге
        qdrant = QdrantClient(path=env["PHILOGRAPH_QDRANT_PATH"])
    vectors = VectorStore(qdrant)
    indexer = Indexer(engine, library, embedder, vectors)
    searcher = Searcher(engine, embedder, vectors, lambda: indexer.active_collection)
    health = Health("search", __version__)

    def database() -> None:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))

    health.depends_on("database", database)
    health.depends_on("qdrant", lambda: qdrant.get_collections(), required=False)
    return indexer, searcher, health


def consume(indexer: Indexer, env: dict[str, str]) -> threading.Event:
    """Поиск сам разбирает свою подписку на события библиотеки (задачи ``search:*``)."""
    from philograph.platform.queue import Queue
    from philograph.platform.queue import migrations as queue_migrations

    engine = make_engine(env["PHILOGRAPH_DATABASE_URL"], [queue_migrations.schema])
    queue_migrations.upgrade(engine)
    queue = Queue(engine)
    subscribe(queue, indexer)
    stop = threading.Event()
    threading.Thread(target=queue.serve, args=(stop,), daemon=True, name="search-queue").start()
    return stop


if os.environ.get("PHILOGRAPH_QDRANT_URL") or os.environ.get("PHILOGRAPH_QDRANT_PATH"):
    events.configure(sinks=[events.json_sink()])
    _indexer, _searcher, _health = components(dict(os.environ))
    _stop = consume(_indexer, dict(os.environ))
    app = build_app(_searcher, _indexer, _health)
