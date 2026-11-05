"""Точка входа ассистента: ``uvicorn philograph.assistant.main:app``."""

from __future__ import annotations

import os

from philograph import __version__
from philograph.assistant.app import build_app
from philograph.assistant.clients import LlmHttp, SearchHttp
from philograph.assistant.ontology import KnowledgeHttp, Ontology, OntologySteps
from philograph.assistant.service import Assistant
from philograph.platform import events
from philograph.platform.client import ServiceClient
from philograph.platform.health import Health

if os.environ.get("PHILOGRAPH_SEARCH_URL"):
    events.configure(sinks=[events.json_sink()])
    # Онтология — если задан сервис знаний; шаги — PHILOGRAPH_ASSISTANT_ONTOLOGY (по умолчанию все).
    _ontology = (
        Ontology(
            KnowledgeHttp(
                ServiceClient("knowledge", os.environ["PHILOGRAPH_KNOWLEDGE_URL"], timeout=5)
            ),
            OntologySteps.parse(os.environ.get("PHILOGRAPH_ASSISTANT_ONTOLOGY")),
        )
        if os.environ.get("PHILOGRAPH_KNOWLEDGE_URL")
        else None
    )
    _assistant = Assistant(
        SearchHttp(ServiceClient("search", os.environ["PHILOGRAPH_SEARCH_URL"], timeout=10)),
        LlmHttp(ServiceClient("llm", os.environ["PHILOGRAPH_LLM_URL"], timeout=60)),
        ontology=_ontology,
    )
    app = build_app(_assistant, Health("assistant", __version__))
