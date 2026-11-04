"""Точка входа ассистента: ``uvicorn philograph.assistant.main:app``."""

from __future__ import annotations

import os

from philograph import __version__
from philograph.assistant.app import build_app
from philograph.assistant.clients import LlmHttp, SearchHttp
from philograph.assistant.service import Assistant
from philograph.platform import events
from philograph.platform.client import ServiceClient
from philograph.platform.health import Health

if os.environ.get("PHILOGRAPH_SEARCH_URL"):
    events.configure(sinks=[events.json_sink()])
    _assistant = Assistant(
        SearchHttp(ServiceClient("search", os.environ["PHILOGRAPH_SEARCH_URL"], timeout=10)),
        LlmHttp(ServiceClient("llm", os.environ["PHILOGRAPH_LLM_URL"], timeout=60)),
    )
    app = build_app(_assistant, Health("assistant", __version__))
