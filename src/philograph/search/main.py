"""Точка входа сервиса поиска: ``uvicorn philograph.search.main:app``."""

from __future__ import annotations

import os

from qdrant_client import QdrantClient
from sqlalchemy import text

from philograph import __version__
from philograph.platform import events
from philograph.platform.client import ServiceClient
from philograph.platform.db import make_engine
from philograph.platform.health import Health
from philograph.search import schema
from philograph.search.app import build_app
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
    qdrant = QdrantClient(url=env["PHILOGRAPH_QDRANT_URL"])
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


if os.environ.get("PHILOGRAPH_QDRANT_URL"):
    events.configure(sinks=[events.json_sink()])
    _indexer, _searcher, _health = components(dict(os.environ))
    app = build_app(_searcher, _indexer, _health)
