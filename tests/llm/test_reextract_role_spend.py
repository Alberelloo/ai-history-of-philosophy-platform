"""llm-gateway (reextract-with-claude): «Сведения о роли» и «Сводка расходов» (токены).

По дельте ``specs/llm-gateway``. Маршрут — настоящее приложение сервиса LLM через ASGI-транспорт
(ответ маршрута), вызовы идут настоящим ``LLMGateway`` на фейковом провайдере с известным
расходом токенов. Журнал — ``llm.budget.near_limit``, ``llm.call.completed``.
"""

from __future__ import annotations

import json

import httpx
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as hst

from philograph.llm.app import build_app
from philograph.llm.config import GatewayConfig
from philograph.llm.gateway import LLMGateway
from philograph.llm.providers import Completion, FakeProvider, Usage
from philograph.platform import context

from ..conftest import PROFILES
from ..helpers import asgi_transport
from .conftest import CONFIG

req = pytest.mark.req
LG = "llm-gateway"
ROLE = "Сведения о роли"
SPEND = "Сводка расходов"


class Fixed(FakeProvider):
    """Каждый вызов — ровно 1000 входных и 200 выходных токенов."""

    def generate(self, request):
        self.calls.append(request)
        return Completion("ответ", Usage(1000, 0, 200))


def make_gateway(rig, config_update=None, roles=None, prices=None, provider=None):
    data = json.loads(json.dumps(CONFIG))
    data.update(config_update or {})
    data["roles"].update(roles or {})
    data["prices"].update(prices or {})
    config = GatewayConfig.model_validate(data)
    fixed = provider or Fixed()
    return LLMGateway(
        config,
        {"fake": fixed, "other": FakeProvider()},
        rig.templates,
        rig.store,
        clock=rig.clock,
        sleep=lambda _s: None,
    )


def client(gateway) -> httpx.Client:
    return httpx.Client(base_url="http://llm", transport=asgi_transport(build_app(gateway)))


def formula(timeout, max_retries, base, schema_retries) -> float:
    pauses = sum(base * 2 ** (k - 1) for k in range(1, max_retries + 1))
    return (schema_retries + 1) * ((max_retries + 1) * timeout + pauses)


# --- Сведения о роли ---------------------------------------------------------------------


@req(LG, ROLE, scenario="Роль извлечения")
def test_role_info_extraction_role(rig):
    gateway = make_gateway(
        rig,
        {"max_retries": 2, "retry_base_seconds": 0.5, "schema_retries": 2},
        roles={
            "strong": {"provider": "fake", "model": "deepseek-v4-pro", "timeout_seconds": 120},
        },
        prices={
            "deepseek-v4-pro": {"input_cache_miss": 7.77, "input_cache_hit": 3.33, "output": 9.99}
        },
    )
    response = client(gateway).get("/v1/roles/strong")
    assert response.status_code == 200
    assert response.json() == {
        "role": "strong",
        "model": "deepseek-v4-pro",
        "call_budget_seconds": 1084.5,
    }


@req(LG, ROLE, scenario="Неизвестная роль")
def test_role_info_unknown_role(rig, events):
    response = client(rig.gateway).get("/v1/roles/nope")
    assert response.status_code == 404
    body = response.json()
    assert body["kind"] == "unknown_role"
    assert "model" not in body and "call_budget_seconds" not in body


@pytest.mark.parametrize(
    "role", ["", "STRONG", "strong ", "stron", "../strong", "main/x", "%00", "ё"]
)
@req(LG, ROLE, invariant="Любая роль вне конфигурации — 404 unknown_role")
def test_role_info_hostile_names_are_404(rig, role):
    response = client(rig.gateway).get(f"/v1/roles/{role}")
    assert response.status_code == 404
    if response.headers.get("content-type", "").startswith("application/json"):
        assert response.json().get("kind") in ("unknown_role", None)
    assert "call_budget_seconds" not in response.text


@req(LG, ROLE, invariant="Ключи провайдеров и цены не попадают в ответ")
def test_role_info_has_no_secrets_or_prices(rig, monkeypatch):
    monkeypatch.setenv("TEST_PROVIDER_SECRET", "sk-topsecret-123")
    gateway = make_gateway(
        rig,
        {
            "providers": {
                "fake": {"kind": "fake", "api_key_env": "TEST_PROVIDER_SECRET"},
                "other": {"kind": "fake"},
            }
        },
        prices={"pro": {"input_cache_miss": 7.77, "input_cache_hit": 3.33, "output": 9.99}},
    )
    for role in ("main", "strong", "fast", "embeddings"):
        response = client(gateway).get(f"/v1/roles/{role}")
        assert response.status_code == 200
        assert set(response.json()) == {"role", "model", "call_budget_seconds"}
        for secret in (
            "sk-topsecret",
            "TEST_PROVIDER_SECRET",
            "7.77",
            "3.33",
            "9.99",
            "api_key",
            "price",
        ):
            assert secret not in response.text


@req(
    LG, ROLE, invariant="call_budget_seconds — (schema_retries+1)·((max_retries+1)·timeout+Σ пауз)"
)
@given(
    hst.integers(0, 4),
    hst.integers(0, 4),
    hst.sampled_from([0.0, 0.25, 0.5, 1.0, 2.0]),
    hst.sampled_from([0.5, 1.0, 30.0, 120.0, 600.0]),
)
@settings(
    parent=PROFILES["pure"],
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    max_examples=120,
)
def test_role_budget_formula_property(rig, max_retries, schema_retries, base, timeout):
    gateway = make_gateway(
        rig,
        {"max_retries": max_retries, "retry_base_seconds": base, "schema_retries": schema_retries},
        roles={"strong": {"provider": "fake", "model": "pro", "timeout_seconds": timeout}},
    )
    body = client(gateway).get("/v1/roles/strong").json()
    assert body["call_budget_seconds"] == pytest.approx(
        formula(timeout, max_retries, base, schema_retries), abs=6e-4
    )
    assert body["model"] == "pro" and body["role"] == "strong"


@req(LG, ROLE, invariant="Модель роли — идентификатор модели из конфигурации, для каждой роли свой")
def test_role_model_per_role(rig):
    http = client(rig.gateway)
    assert http.get("/v1/roles/main").json()["model"] == "flash"
    assert http.get("/v1/roles/strong").json()["model"] == "pro"
    assert http.get("/v1/roles/fast").json()["model"] == "flash"


# --- Сводка расходов ---------------------------------------------------------------------


@req(LG, SPEND, scenario="Токены в сводке по запуску")
def test_spend_tokens_by_run(rig, events):
    gateway = make_gateway(rig)
    for run_id, n in (("run-1", 2), ("run-2", 1)):
        with context.scope(run_id=run_id):
            for i in range(n):
                gateway.generate(rig.call(data={"question": f"{run_id}-{i}"}))
    rows = {r["run_id"]: r for r in gateway.spend_summary(1, ("run_id",))}
    run1 = rows["run-1"]
    assert (run1["calls"], run1["input_tokens"], run1["output_tokens"]) == (2, 2000, 400)
    assert (
        rows["run-2"]["calls"],
        rows["run-2"]["input_tokens"],
        rows["run-2"]["output_tokens"],
    ) == (1, 1000, 200)
    # то же — через маршрут сервиса
    body = client(gateway).get("/v1/spend", params={"days": 1, "group_by": "run_id"}).json()
    by_run = {r["run_id"]: r for r in body}
    assert by_run["run-1"]["input_tokens"] == 2000 and by_run["run-1"]["output_tokens"] == 400
    assert by_run["run-1"]["calls"] == 2
    # стоимость и токены согласованы с журналом вызовов
    completed = [e for e in events.of("llm.call.completed")]
    assert len(completed) == 3


@pytest.mark.parametrize(
    "group",
    [
        ("budget",),
        ("operation",),
        ("caller",),
        ("role",),
        ("model",),
        ("budget", "role"),
        ("run_id", "model"),
    ],
)
@req(
    LG,
    SPEND,
    invariant="В каждой строке сводки, кроме cost_usd и calls, суммы input_tokens и output_tokens",
)
def test_every_group_has_token_sums(rig, group):
    gateway = make_gateway(rig)
    with context.scope(run_id="run-1"):
        for i in range(3):
            gateway.generate(rig.call(data={"question": str(i)}))
    rows = gateway.spend_summary(1, group)
    assert rows
    for row in rows:
        assert {"cost_usd", "calls", "input_tokens", "output_tokens"} <= set(row)
    assert sum(r["calls"] for r in rows) == 3
    assert sum(r["input_tokens"] for r in rows) == 3000
    assert sum(r["output_tokens"] for r in rows) == 600
    assert sum(r["cost_usd"] for r in rows) == pytest.approx(3 * (1000 * 0.3 + 200 * 1.2) / 1e6)


@req(LG, SPEND, invariant="Токены суммируются по вызовам группы и не смешиваются между запусками")
@given(hst.lists(hst.integers(1, 4), min_size=1, max_size=4))
@settings(
    parent=PROFILES["heavy"],
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
def test_tokens_per_run_property(rig, plan):
    gateway = make_gateway(rig)
    for run, n in enumerate(plan):
        with context.scope(run_id=f"prop-{run}-{id(plan)}"):
            for i in range(n):
                gateway.generate(rig.call(data={"question": f"{id(plan)}-{run}-{i}"}))
    rows = {r["run_id"]: r for r in gateway.spend_summary(1, ("run_id",))}
    for run, n in enumerate(plan):
        row = rows[f"prop-{run}-{id(plan)}"]
        assert (row["calls"], row["input_tokens"], row["output_tokens"]) == (n, 1000 * n, 200 * n)


@req(LG, SPEND, scenario="Приближение к лимиту")
def test_near_limit_event(rig, events):
    gateway = make_gateway(
        rig,
        {"budgets": {"site": {"daily_limit_usd": 0.01, "alert_ratio": 0.8}, "filling": {}}},
    )
    for i in range(14):  # 14 · 0.00054 = 0.00756 — ниже порога 0.008
        gateway.generate(rig.call(data={"question": f"вопрос {i}"}))
    assert events.of("llm.budget.near_limit") == []
    gateway.generate(rig.call(data={"question": "вопрос 14"}))  # 0.0081 — порог пройден
    [alert] = events.of("llm.budget.near_limit")
    assert alert["budget"] == "site" and alert["period"] == "day"
    assert alert["spent_usd"] == pytest.approx(15 * 0.00054) and alert["limit_usd"] == 0.01
    summary = {r["budget"]: r for r in gateway.spend_summary(1, ("budget",))}
    assert summary["site"]["calls"] == 15
    assert (summary["site"]["input_tokens"], summary["site"]["output_tokens"]) == (15000, 3000)
