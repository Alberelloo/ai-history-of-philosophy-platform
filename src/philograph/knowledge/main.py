"""Точка входа сервиса знаний: ``uvicorn philograph.knowledge.main:app``."""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text

from philograph import __version__
from philograph.knowledge import schema
from philograph.knowledge.app import build_app, library_paragraphs, subscribe
from philograph.knowledge.assist import AssistantKnowledge
from philograph.knowledge.cards import Cards
from philograph.knowledge.entities import Entities
from philograph.knowledge.filling import Filling
from philograph.knowledge.graph import Graphs, GraphSettings
from philograph.knowledge.mentions import Mentions
from philograph.knowledge.portraits import Portraits
from philograph.knowledge.registry import OntologyRegistry
from philograph.knowledge.review import Review
from philograph.knowledge.statements import Statements
from philograph.operator.access import ActionLog, OperatorAuth
from philograph.operator.access import migrations as operator_migrations
from philograph.platform import events
from philograph.platform.client import ServiceClient
from philograph.platform.db import make_engine
from philograph.platform.files import FileStore
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
    portraits: Portraits
    actions: ActionLog
    mentions: Mentions
    graphs: Graphs
    assistant: AssistantKnowledge
    library: ServiceClient


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
    actions = ActionLog(engine)
    review = Review(statements, actions)
    llm = (
        ServiceClient("llm", env["PHILOGRAPH_LLM_URL"], timeout=60)
        if env.get("PHILOGRAPH_LLM_URL")
        else None
    )
    portraits = Portraits(engine, FileStore(Path(env["PHILOGRAPH_FILES_ROOT"])))
    cards = Cards(statements, mentions, llm, on_view=review.record_views, portraits=portraits)
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
    assistant = AssistantKnowledge(statements, mentions)
    return Components(
        statements,
        health,
        queue,
        review,
        auth,
        cards,
        portraits,
        actions,
        mentions,
        graphs,
        assistant,
        library,
    )


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
        portraits=_c.portraits,
        actions=_c.actions,
        mentions=_c.mentions,
        graphs=_c.graphs,
        assistant=_c.assistant,
        library=_c.library,
    )
