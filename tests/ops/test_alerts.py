"""Требования спецификации operational-alerts."""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from philograph.ops import schema as ops_schema
from philograph.ops.alerts import (
    Alerts,
    AlertSettings,
    BudgetRule,
    Check,
    ErrorRateRule,
    QueueRule,
    ReadinessRule,
    TelegramChannel,
    UnknownRegionRule,
    WebhookChannel,
    standard_rules,
)
from philograph.platform.health import Health
from philograph.platform.metrics import metrics
from philograph.platform.queue import Queue
from philograph.platform.queue import migrations as queue_migrations
from philograph.platform.web import create_app

req = pytest.mark.req
OA = "operational-alerts"


class Hook:
    """Вебхук оператора: запоминает доставленные сообщения."""

    def __init__(self, fail: bool = False) -> None:
        self.messages: list[str] = []
        self.fail = fail

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if self.fail:
            return httpx.Response(500)
        self.messages.append(json.loads(request.read())["text"])
        return httpx.Response(200)

    def channel(self) -> WebhookChannel:
        return WebhookChannel(
            "https://alerts.example/hook", httpx.Client(transport=httpx.MockTransport(self))
        )


@pytest.fixture
def ops_engine(engine_for):
    return engine_for(ops_schema.migrations, queue_migrations)


@req(OA, "Правила оповещений")
def test_rules_from_settings(ops_engine, clock):
    ready = {"value": True}
    rule = ReadinessRule("search", lambda: (ready["value"], "database"), 5, clock)
    assert not rule().firing
    ready["value"] = False
    assert not rule().firing
    clock.advance(minutes=4)
    assert not rule().firing  # короткий сбой не беспокоит
    clock.advance(minutes=1)
    check = rule()
    assert check.firing and check.summary == "search не готов 5 мин: database"
    # Пороги — настройка.
    settings = AlertSettings.from_env(
        {"PHILOGRAPH_ALERT_RULES": '{"queue_age_minutes": 10, "budget_ratio": 0.5}'}
    )
    assert settings.queue_age_minutes == 10 and settings.not_ready_minutes == 5
    budget = BudgetRule(
        lambda: [{"budget": "site", "period": "day", "spent_usd": 1.2, "limit_usd": 2.0}], settings
    )
    assert budget().firing and "site за сутки: $1.20 из $2.00" in budget().summary
    queue = Queue(ops_engine, clock)
    queue.enqueue("search:source.published", {"x": 1}, key="k1")
    stuck = QueueRule(ops_engine, settings, clock)
    assert not stuck().firing
    clock.advance(minutes=11)
    assert stuck().firing and "задач в очереди: 1" in stuck().summary
    env = {
        "PHILOGRAPH_SEARCH_URL": "http://search:8002",
        "PHILOGRAPH_GATEWAY_URL": "http://gateway:8080",
        "PHILOGRAPH_LLM_URL": "http://llm:8000",
    }
    codes = set(standard_rules(env, ops_engine, settings, clock))
    assert codes == {
        "ready:search",
        "ready:gateway",
        "ready:llm",
        "errors:gateway",
        "region",
        "budget",
        "queue",
        "backup",
    }


@req(OA, "Без персональных данных")
def test_unknown_region_rule():
    """Доля запросов шлюза без определённой страны: порог, минимум запросов, без стран."""

    snapshots = iter(
        [
            {
                "counters": [
                    {"name": "gateway.region", "labels": {"kind": "known"}, "value": 60},
                    {"name": "gateway.region", "labels": {"kind": "unknown"}, "value": 0},
                ]
            },
            {
                "counters": [
                    {"name": "gateway.region", "labels": {"kind": "known"}, "value": 66},
                    {"name": "gateway.region", "labels": {"kind": "unknown"}, "value": 4},
                ]
            },
            {
                "counters": [
                    {"name": "gateway.region", "labels": {"kind": "known"}, "value": 67},
                    {"name": "gateway.region", "labels": {"kind": "unknown"}, "value": 5},
                ]
            },
        ]
    )
    settings = AlertSettings(unknown_region_ratio=0.1, unknown_region_min_requests=10)
    rule = UnknownRegionRule(lambda: next(snapshots), settings)
    assert not rule().firing  # первое измерение — точка отсчёта
    check = rule()
    assert check.firing and check.summary == "регион не определён у 40.0% из 10 запросов"
    assert "CF-" not in check.summary and "country" not in check.details
    # Мало запросов в окне — доля не считается, шума нет.
    assert rule().summary == "мало запросов: 2"


@req(OA, "Канал оповещений")
def test_repeats_grouped_and_channels(clock, events):
    state = {"firing": True}
    hook = Hook()
    alerts = Alerts(
        {"search": ("Сервис search", lambda: Check(state["firing"], "не готов"))}, hook.channel()
    )
    for _ in range(60):  # правило срабатывает каждую минуту в течение часа
        alerts.evaluate()
    state["firing"] = False
    alerts.evaluate()
    assert hook.messages == [
        "⚠ Сервис search: не готов",
        "✓ Сервис search: восстановлено. не готов",
    ]
    telegram = []
    channel = TelegramChannel(
        "123:abc",
        "-100500",
        httpx.Client(
            transport=httpx.MockTransport(lambda r: telegram.append(r) or httpx.Response(200))
        ),
    )
    channel.send("⚠ проверка")
    assert telegram[0].url.path == "/bot123:abc/sendMessage"
    assert json.loads(telegram[0].read()) == {"chat_id": "-100500", "text": "⚠ проверка"}
    broken = Alerts({"x": ("X", lambda: Check(True, "плохо"))}, Hook(fail=True).channel())
    broken.evaluate()
    assert events.one("ops.alert.delivery_failed")["channel"] == "webhook"


@req(OA, "Восстановление")
def test_recovery_message(clock):
    hook = Hook()
    up = {"value": False}
    rule = ReadinessRule("search", lambda: (up["value"], "qdrant"), 5, clock)
    alerts = Alerts({"ready:search": ("Сервис search", rule)}, hook.channel())
    alerts.evaluate()
    clock.advance(minutes=6)
    alerts.evaluate()
    up["value"] = True
    alerts.evaluate()
    alerts.evaluate()
    assert len(hook.messages) == 2
    assert hook.messages[1].startswith("✓ Сервис search: восстановлено")


@req(OA, "Без персональных данных")
def test_error_alert_has_rates_not_questions(monkeypatch):
    snapshots = iter(
        [
            {
                "counters": [
                    {
                        "name": "http.requests",
                        "labels": {"route": "/api/assistant/{path:path}", "status": "200"},
                        "value": 100,
                    }
                ]
            },
            {
                "counters": [
                    {
                        "name": "http.requests",
                        "labels": {"route": "/api/assistant/{path:path}", "status": "200"},
                        "value": 150,
                    },
                    {
                        "name": "http.requests",
                        "labels": {"route": "/api/assistant/{path:path}", "status": "502"},
                        "value": 10,
                    },
                ]
            },
        ]
    )
    rule = ErrorRateRule(lambda: next(snapshots), AlertSettings())
    assert not rule().firing  # первое измерение — точка отсчёта
    check = rule()
    assert check.firing and check.summary == "доля ошибок 16.7% из 60 запросов (502: 10)"
    hook = Hook()
    Alerts({"errors": ("Ошибки на сайте", lambda: check)}, hook.channel()).evaluate()
    assert "assistant" not in hook.messages[0] and "?" not in hook.messages[0]
    # Метрики шлюза отдаются только со служебным токеном.
    monkeypatch.setenv("PHILOGRAPH_INTERNAL_TOKEN", "служебный".encode().hex())
    client = TestClient(create_app("gateway", "1.0", Health("gateway", "1.0")))
    assert client.get("/internal/metrics").status_code == 404
    metrics.inc("http.requests", route="/x", status="200")
    response = client.get(
        "/internal/metrics", headers={"X-Internal-Token": "служебный".encode().hex()}
    )
    assert response.status_code == 200 and response.json()["counters"]
