"""Точка входа сервиса знаний: ``uvicorn philograph.knowledge.main:app``."""

from __future__ import annotations

import os
import threading

from sqlalchemy import text

from philograph import __version__
from philograph.knowledge import schema
from philograph.knowledge.app import build_app, library_paragraphs, subscribe
from philograph.knowledge.entities import Entities
from philograph.knowledge.registry import OntologyRegistry
from philograph.knowledge.statements import Statements
from philograph.platform import events
from philograph.platform.client import ServiceClient
from philograph.platform.db import make_engine
from philograph.platform.health import Health
from philograph.platform.queue import Queue
from philograph.platform.queue import migrations as queue_migrations


def components(env: dict[str, str]) -> tuple[Statements, Health, Queue]:
    engine = make_engine(env["PHILOGRAPH_DATABASE_URL"], [schema.SCHEMA, queue_migrations.schema])
    schema.migrations.upgrade(engine)
    queue_migrations.upgrade(engine)
    registry = OntologyRegistry(engine)
    registry.load_defaults()
    library = ServiceClient("library", env["PHILOGRAPH_LIBRARY_URL"] + "/api")
    statements = Statements(
        engine, registry, Entities(engine, registry), library_paragraphs(library)
    )
    health = Health("knowledge", __version__)

    def database() -> None:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))

    health.depends_on("database", database)
    queue = Queue(engine)
    subscribe(queue, statements)
    return statements, health, queue


if os.environ.get("PHILOGRAPH_KNOWLEDGE_SERVICE"):
    events.configure(sinks=[events.json_sink()])
    _statements, _health, _queue = components(dict(os.environ))
    _stop = threading.Event()
    threading.Thread(
        target=_queue.serve, args=(_stop,), daemon=True, name="knowledge-queue"
    ).start()
    app = build_app(_statements, _health)
