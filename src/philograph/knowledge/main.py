"""Точка входа сервиса знаний: ``uvicorn philograph.knowledge.main:app``."""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass

from sqlalchemy import text

from philograph import __version__
from philograph.knowledge import schema
from philograph.knowledge.app import build_app, library_paragraphs, subscribe
from philograph.knowledge.cards import Cards
from philograph.knowledge.entities import Entities
from philograph.knowledge.filling import Filling
from philograph.knowledge.graph import Graphs, GraphSettings
from philograph.knowledge.mentions import Mentions
from philograph.knowledge.registry import OntologyRegistry
from philograph.knowledge.review import Review
from philograph.knowledge.statements import Statements
from philograph.operator.access import ActionLog, OperatorAuth
from philograph.operator.access import migrations as operator_migrations
from philograph.platform import events
from philograph.platform.client import ServiceClient
from philograph.platform.db import make_engine
from philograph.platform.health import Health
from philograph.platform.queue import Queue
from philograph.platform.queue import migrations as queue_migrations


@dataclass
class Components:
    statements: Statements
    health: Health
    queue: Queue
    review: Review
    auth: OperatorAuth | None
    cards: Cards
    mentions: Mentions
    graphs: Graphs


def components(env: dict[str, str]) -> Components:
    sets = (schema.migrations, queue_migrations, operator_migrations)
    engine = make_engine(env["PHILOGRAPH_DATABASE_URL"], [m.schema for m in sets])
    for m in sets:
        m.upgrade(engine)
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
    filling = None
    if env.get("PHILOGRAPH_LLM_URL"):
        filling = Filling(
            statements, ServiceClient("llm", env["PHILOGRAPH_LLM_URL"], timeout=120), library
        )
    queue = Queue(engine)
    mentions = Mentions(statements, library)
    subscribe(queue, statements, filling, mentions)
    review = Review(statements, ActionLog(engine))
    llm = (
        ServiceClient("llm", env["PHILOGRAPH_LLM_URL"], timeout=60)
        if env.get("PHILOGRAPH_LLM_URL")
        else None
    )
    cards = Cards(statements, mentions, llm, on_view=review.record_views)
    graphs = Graphs(
        statements,
        llm,
        queue,
        GraphSettings(
            min_edges=int(env.get("PHILOGRAPH_GRAPH_MIN_EDGES", "5")),
            max_nodes=int(env.get("PHILOGRAPH_GRAPH_MAX_NODES", "60")),
        ),
    )
    password = env.get("PHILOGRAPH_OPERATOR_PASSWORD_HASH")
    auth = OperatorAuth(password) if password else None
    return Components(statements, health, queue, review, auth, cards, mentions, graphs)


if os.environ.get("PHILOGRAPH_KNOWLEDGE_SERVICE"):
    events.configure(sinks=[events.json_sink()])
    _c = components(dict(os.environ))
    _stop = threading.Event()
    threading.Thread(
        target=_c.queue.serve, args=(_stop,), daemon=True, name="knowledge-queue"
    ).start()
    app = build_app(
        _c.statements,
        _c.health,
        review=_c.review,
        auth=_c.auth,
        cards=_c.cards,
        mentions=_c.mentions,
        graphs=_c.graphs,
    )
