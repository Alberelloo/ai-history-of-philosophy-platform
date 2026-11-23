"""Эмбеддинги через OpenAI-совместимый прокси: endpoint, модель, размерность, маппинг."""

from __future__ import annotations

import json

import httpx
import pytest

from philograph.llm.config import GatewayConfig
from philograph.llm.gateway import LLMGateway
from philograph.llm.providers import FakeProvider, OpenAICompatibleProvider

from .conftest import CONFIG

req = pytest.mark.req
LG = "llm-gateway"


@req(LG, "Эмбеддинги через OpenAI-совместимый прокси")
def test_embed_posts_model_and_dimensions_and_maps_vectors():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/embeddings"
        seen["body"] = json.loads(request.content)
        data = {
            "data": [
                {"index": 1, "embedding": [0.1, 0.2]},
                {"index": 0, "embedding": [0.5, 0.6]},
            ],
            "usage": {"prompt_tokens": 8},
        }
        return httpx.Response(200, json=data, request=request)

    provider = OpenAICompatibleProvider(
        "http://litellm:4000/v1", "sk-test", transport=httpx.MockTransport(handler)
    )
    vectors, usage = provider.embed("bge-m3", ["a", "b"], 60, dimensions=1024)

    assert seen["body"] == {"model": "bge-m3", "input": ["a", "b"], "dimensions": 1024}
    assert vectors == [[0.5, 0.6], [0.1, 0.2]]  # по индексу
    assert usage.input_tokens == 8


@req(LG, "Эмбеддинги через OpenAI-совместимый прокси")
def test_embed_without_dimensions_omits_field():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"data": [], "usage": {}}, request=request)

    provider = OpenAICompatibleProvider(
        "http://litellm:4000/v1", "sk-test", transport=httpx.MockTransport(handler)
    )
    provider.embed("bge-m3", ["a"], 60)
    assert "dimensions" not in seen["body"]
    assert seen["body"]["model"] == "bge-m3"


@req(LG, "Эмбеддинги через OpenAI-совместимый прокси")
def test_gateway_passes_dimensions_to_provider(rig, events):
    config = dict(
        CONFIG,
        roles={
            **CONFIG["roles"],
            "embeddings": {"provider": "fake", "model": "embed", "dimensions": 512},
        },
    )
    gateway = LLMGateway(
        GatewayConfig.model_validate(config),
        {"fake": rig.provider, "other": FakeProvider()},
        rig.templates,
        rig.store,
        clock=rig.clock,
        sleep=lambda _s: None,
    )
    gateway.embed(["текст"], caller="search", operation="index", budget="filling")
    assert rig.provider.embed_dimensions == [512]
    assert rig.provider.embed_calls == [["текст"]]
