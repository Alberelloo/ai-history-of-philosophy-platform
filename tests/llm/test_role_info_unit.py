"""Юнит-тесты сведений о роли и токенов в сводке расходов; сценарии «Сведения о роли» и
«Сводка расходов» — у тестировщика."""

from __future__ import annotations

import httpx

from philograph.llm.app import build_app
from philograph.llm.gateway import LLMGateway
from philograph.platform import context

from ..helpers import asgi_transport


def test_role_info_budget_formula(rig):
    config = rig.gateway.config.model_copy(
        update={"max_retries": 2, "retry_base_seconds": 0.5, "schema_retries": 2}
    )
    config.roles["strong"] = config.roles["strong"].model_copy(update={"timeout_seconds": 120})
    gateway = LLMGateway(config, rig.gateway.providers, rig.templates, rig.store)
    assert gateway.role_info("strong") == {
        "role": "strong",
        "model": "pro",
        "call_budget_seconds": 1084.5,  # 3 · (3 · 120 + 0.5 + 1)
    }


def test_role_route(rig):
    client = httpx.Client(base_url="http://llm", transport=asgi_transport(build_app(rig.gateway)))
    ok = client.get("/v1/roles/main")
    assert ok.status_code == 200
    assert set(ok.json()) == {"role", "model", "call_budget_seconds"}
    missing = client.get("/v1/roles/nope")
    assert missing.status_code == 404 and missing.json()["kind"] == "unknown_role"


def test_spend_summary_has_tokens(rig):
    rig.provider.default = "ответ"
    with context.scope(run_id="run-1"):
        for i in range(2):
            rig.gateway.generate(rig.call(data={"question": f"вопрос {i}"}))
    [row] = [r for r in rig.gateway.spend_summary(1, ("run_id",)) if r["run_id"] == "run-1"]
    assert row["calls"] == 2
    assert row["input_tokens"] > 0 and row["output_tokens"] > 0
