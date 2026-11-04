from __future__ import annotations

from dataclasses import dataclass

import pytest

from philograph.llm import store as st
from philograph.llm.config import GatewayConfig
from philograph.llm.gateway import Call, LLMGateway
from philograph.llm.providers import FakeProvider
from philograph.llm.templates import Template, TemplateRegistry
from philograph.platform.clock import ManualClock

CONFIG = {
    "providers": {"fake": {"kind": "fake"}, "other": {"kind": "fake"}},
    "roles": {
        "fast": {"provider": "fake", "model": "flash", "max_output_tokens": 100},
        "main": {"provider": "fake", "model": "flash", "max_output_tokens": 500},
        "strong": {"provider": "fake", "model": "pro", "max_output_tokens": 500},
        "embeddings": {"provider": "fake", "model": "embed"},
    },
    "prices": {
        "flash": {
            "input_cache_miss": 0.3,
            "input_cache_hit": 0.03,
            "output": 1.2,
            "night": {"start_minute": 990, "end_minute": 30, "multiplier": 0.5},
        },
        "pro": {"input_cache_miss": 1.0, "input_cache_hit": 0.1, "output": 4.0},
        "embed": {"input_cache_miss": 0.02, "input_cache_hit": 0.02},
    },
    "budgets": {
        "site": {"daily_limit_usd": 2.0, "monthly_limit_usd": 50.0, "alert_ratio": 0.8},
        "filling": {},
    },
    "retry_base_seconds": 0.0,
}


@dataclass
class Rig:
    gateway: LLMGateway
    provider: FakeProvider
    store: st.Store
    clock: ManualClock
    templates: TemplateRegistry

    def call(self, **overrides) -> Call:
        params = {
            "role": "main",
            "template": "answer",
            "caller": "assistant",
            "operation": "answer",
            "budget": "site",
            "data": {"question": "Что такое a priori?"},
        }
        params.update(overrides)
        return Call(**params)


@pytest.fixture
def rig(engine_for, clock) -> Rig:
    engine = engine_for(st.migrations)
    templates = TemplateRegistry()
    templates.register(Template("answer", "Ответь по источникам.", ("question", "passages")))
    templates.register(Template("route", "Определи тип вопроса.", ("question",)))
    provider = FakeProvider()
    store = st.Store(engine)
    gateway = LLMGateway(
        GatewayConfig.model_validate(CONFIG),
        {"fake": provider, "other": FakeProvider()},
        templates,
        store,
        clock=clock,
        sleep=lambda _s: None,
    )
    return Rig(gateway, provider, store, clock, templates)
