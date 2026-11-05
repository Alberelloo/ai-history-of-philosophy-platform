"""Стенд ассистента: поиск и сервис LLM через HTTP, модель отвечает по сценарию.

Поиск — настоящий сервис поиска поверх настоящей библиотеки (стенд из tests/search), модель —
тестовый провайдер: маршрутизатор возвращает заданный JSON, основная модель — заданный текст
со ссылками ``[n]``. Так проверяются цепочки, проверка ссылок и пометка, а не качество модели.
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field

import pytest
from fastapi.testclient import TestClient

from philograph.assistant.app import build_app
from philograph.assistant.clients import LlmHttp, SearchHttp
from philograph.assistant.service import Assistant, AssistantSettings
from philograph.llm.app import build_app as llm_app
from philograph.llm.config import GatewayConfig
from philograph.llm.gateway import LLMGateway
from philograph.llm.providers import Completion, StreamChunk, Usage
from philograph.llm.templates import Template, TemplateRegistry
from philograph.platform.client import ServiceClient
from philograph.prompts import PROMPTS
from philograph.search.app import build_app as search_app

from ..helpers import asgi_transport
from ..search.conftest import LLM_CONFIG, ConceptProvider
from ..search.conftest import rig as search_rig  # noqa: F401 — стенд поиска как фикстура


@dataclass
class ScriptedModel(ConceptProvider):
    """Эмбеддинги — понятийные, ответы — по сценарию."""

    routes: deque = field(default_factory=deque)
    answers: deque = field(default_factory=deque)
    requests: list = field(default_factory=list)

    def generate(self, request):
        self.requests.append(request)
        item = (
            self.routes.popleft()
            if self.routes
            else {"type": "knowledge", "confidence": 0.9, "names": []}
        )
        if isinstance(item, Exception):
            raise item
        return Completion(json.dumps(item, ensure_ascii=False), Usage(100, 0, 20))

    def stream(self, request):
        self.requests.append(request)
        item = self.answers.popleft() if self.answers else ["Ответ без ссылок."]
        if isinstance(item, Exception):
            raise item
        if callable(item):  # ответ, зависящий от переданных абзацев
            item = item(request.messages[-1].content)
        for part in item:
            if isinstance(part, Exception):
                raise part
            if isinstance(part, float):  # пауза: медленная модель
                import time

                time.sleep(part)
                continue
            yield StreamChunk(text=part)
        yield StreamChunk(usage=Usage(500, 0, 80))


CONFIG = {
    **LLM_CONFIG,
    "providers": {"concept": {"kind": "fake"}},
    "roles": {
        **LLM_CONFIG["roles"],
        "fast": {"provider": "concept", "model": "flash", "max_output_tokens": 100},
        "main": {"provider": "concept", "model": "flash", "max_output_tokens": 800},
        "strong": {"provider": "concept", "model": "flash", "max_output_tokens": 800},
    },
    "prices": {
        **LLM_CONFIG["prices"],
        "flash": {"input_cache_miss": 0.3, "input_cache_hit": 0.03, "output": 1.2},
    },
}


@dataclass
class Bot:
    rig: object
    model: ScriptedModel
    gateway: LLMGateway
    assistant: Assistant
    client: TestClient

    def ask(self, **body) -> list[dict]:
        response = self.client.post("/v1/ask", json=body)
        assert response.status_code == 200
        return [json.loads(line) for line in response.text.splitlines() if line.strip()]

    @staticmethod
    def number(prompt: str, needle: str) -> int:
        """Номер абзаца в блоке passages запроса к модели."""
        import re

        for match in re.finditer(r"\[(\d+)\] [^\n]*\n([^\n]*)", prompt):
            if needle in match.group(2):
                return int(match.group(1))
        raise AssertionError(f"нет абзаца с «{needle}»")

    def para(self, needle: str) -> str:
        return self.rig.paragraph("ru", needle)


@pytest.fixture
def bot(search_rig, clock, engine_for) -> Bot:
    rig = search_rig
    rig.publish("ru")
    rig.publish("en")
    model = ScriptedModel()
    templates = TemplateRegistry()
    for spec in PROMPTS:
        templates.register(Template(spec.name, spec.instructions, spec.data_slots))
    gateway = LLMGateway(
        GatewayConfig.model_validate(CONFIG),
        {"concept": model},
        templates,
        rig.llm.store,
        clock=clock,
        sleep=lambda _s: None,
    )
    # Поиск идёт через свой HTTP-интерфейс, его эмбеддинги — через тот же шлюз.
    llm_client = ServiceClient("llm", "http://llm", transport=asgi_transport(llm_app(gateway)))
    rig.indexer.embedder.client = llm_client
    search = ServiceClient(
        "search", "http://search", transport=asgi_transport(search_app(rig.searcher, rig.indexer))
    )
    assistant = Assistant(
        SearchHttp(search),
        LlmHttp(llm_client),
        clock=clock,
        settings=AssistantSettings(visitor_per_hour=5),
    )
    client = TestClient(build_app(assistant))
    return Bot(rig, model, gateway, assistant, client)
