"""Требования спецификации observability."""

from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from philograph.platform import context
from philograph.platform import events as ev
from philograph.platform.client import ServiceClient
from philograph.platform.health import Health
from philograph.platform.metrics import Metrics
from philograph.platform.privacy import visitor_hash
from philograph.platform.queue import Queue
from philograph.platform.queue import migrations as queue_migrations
from philograph.platform.web import create_app

from ..helpers import asgi_transport

SRC = Path(__file__).resolve().parents[2] / "src" / "philograph"
req = pytest.mark.req

ev.define("test.chapter.served", "info", "Тестовое событие: глава отдана", required=("chapter_id",))


@req("observability", "Структурированный журнал событий")
def test_events_are_structured_with_context(events):
    app = create_app("library", "0.1.0", Health("library", "0.1.0"))

    @app.get("/v1/chapters/{chapter_id}")
    def chapter(chapter_id: str) -> dict[str, str]:
        ev.emit("test.chapter.served", chapter_id=chapter_id)
        return {"id": chapter_id}

    TestClient(app).get("/v1/chapters/ch-3", headers={"X-Request-Id": "req-9"})
    served = events.one("test.chapter.served")
    assert served.level == "info" and served.time
    assert served.fields == {"request_id": "req-9", "service": "library", "chapter_id": "ch-3"}
    events.assert_sequence("test.chapter.served", "http.request.completed")


@req("observability", "Каталог событий")
def test_catalog_is_enforced(events):
    with pytest.raises(ev.CatalogViolation):
        ev.emit("nobody.knows.me")
    with pytest.raises(ev.CatalogViolation):
        ev.emit("llm.call.completed", role="main")  # нет обязательных полей

    ev.configure(strict=False)
    ev.emit("test.chapter.served")  # без chapter_id
    violation = events.one("observability.catalog.violation")
    assert violation["event"] == "test.chapter.served"
    assert "chapter_id" in violation["problem"]


@req("observability", "Сквозной идентификатор запроса")
def test_request_id_flows_through_services_and_queue(events, engine_for, clock):
    downstream = create_app("search", "0.1.0", Health("search", "0.1.0"))

    @downstream.get("/v1/search")
    def search() -> dict[str, list]:
        return {"results": []}

    client = ServiceClient("search", "http://search", transport=asgi_transport(downstream))
    upstream = create_app("assistant", "0.1.0", Health("assistant", "0.1.0"))

    @upstream.post("/v1/ask")
    def ask() -> dict[str, int]:
        return {"found": len(client.get("search").json()["results"])}

    TestClient(upstream).post("/v1/ask", headers={"X-Request-Id": "req-77"})
    services = {e["service"]: e["request_id"] for e in events.of("http.request.completed")}
    assert services == {"assistant": "req-77", "search": "req-77"}

    engine = engine_for(queue_migrations)
    queue = Queue(engine, clock)
    queue.handler("index")(lambda job: ev.emit("test.chapter.served", chapter_id="x"))
    with context.scope(run_id="run-5"):
        queue.enqueue("index", {}, key="k1")
    events.clear()
    queue.run_once()
    assert {e.get("run_id") for e in events.items} == {"run-5"}


@req("observability", "Без персональных данных")
def test_no_personal_data_in_events(events, clock):
    ev.define(
        "test.question.asked",
        "info",
        "Тест: вопрос задан",
        required=("question_length",),
        optional=("visitor",),
    )
    with pytest.raises(ev.CatalogViolation):
        ev.emit("test.question.asked", question_length=12, question_text="Что такое cogito?")

    ev.configure(strict=False)
    ev.emit(
        "test.question.asked", question_length=12, question_text="Что такое cogito?", ip="10.0.0.1"
    )
    asked = events.one("test.question.asked")
    assert "question_text" not in asked.fields and "ip" not in asked.fields

    today = visitor_hash("10.0.0.1", "Firefox", clock.now(), "secret")
    tomorrow = visitor_hash("10.0.0.1", "Firefox", clock.now() + timedelta(days=1), "secret")
    assert today != tomorrow and "10.0.0.1" not in today
    assert today == visitor_hash("10.0.0.1", "Firefox", clock.now(), "secret")


@req("observability", "Уровни и ошибки")
def test_errors_logged_with_kind_and_hidden_from_user(events):
    ev.register_secret("sk-live-1234567890abcdef")
    app = create_app(
        "library",
        "0.1.0",
        Health("library", "0.1.0"),
        internal_error_message="Не удалось открыть главу",
    )

    @app.get("/v1/chapters/{chapter_id}")
    def chapter(chapter_id: str) -> dict:
        raise RuntimeError("провайдер ответил: ключ sk-live-1234567890abcdef неверен")

    response = TestClient(app, raise_server_exceptions=False).get("/v1/chapters/c1")
    assert response.status_code == 500
    body = response.json()
    assert body["error"] == "Не удалось открыть главу" and body["request_id"]
    assert "sk-" not in response.text
    failed = events.one("http.request.failed")
    assert failed.level == "error" and failed["error_kind"] == "internal"
    assert "sk-live" not in failed["detail"] and "[скрыто]" in failed["detail"]


@req("observability", "Метрики")
def test_metrics_counters_percentiles_and_queue(engine_for, clock):
    m = Metrics()
    for value in [0.1, 0.2, 0.3, 0.4, 2.0]:
        m.observe("assistant.first_token_seconds", value)
    summary = m.summary("assistant.first_token_seconds")
    assert summary == {"count": 5, "p50": 0.3, "p95": 2.0}
    m.inc("http.requests", route="/v1/ask", status="500")
    assert m.counter("http.requests", route="/v1/ask", status="500") == 1

    queue = Queue(engine_for(queue_migrations), clock)
    queue.enqueue("index", {}, key="a")
    clock.advance(minutes=10)
    stats = queue.stats()
    assert stats["pending"] == 1 and stats["oldest_age_seconds"] == pytest.approx(600)


@req("observability", "Проверки состояния")
def test_health_required_and_optional_dependencies(events):
    def db_down() -> None:
        raise ConnectionError("нет связи с базой")

    def llm_down() -> None:
        raise TimeoutError("провайдер не отвечает")

    library = Health("library", "0.1.0")
    library.depends_on("llm-provider", llm_down, required=False)
    client = TestClient(create_app("library", "0.1.0", library))
    ready = client.get("/health/ready")
    assert ready.status_code == 200 and ready.json()["degraded"] == {
        "llm-provider": "провайдер не отвечает"
    }

    library.depends_on("database", db_down)
    not_ready = client.get("/health/ready")
    assert not_ready.status_code == 503
    assert not_ready.json()["problems"] == {"database": "нет связи с базой"}
    assert client.get("/health/live").json()["status"] == "live"


@req("observability", "Журнал как основа проверок поведения")
def test_every_catalog_event_is_emitted_somewhere():
    import philograph.llm.gateway
    import philograph.operator.access  # noqa: F401

    source = "\n".join(p.read_text(encoding="utf-8") for p in SRC.rglob("*.py"))
    emitted = set(re.findall(r'emit\(\s*"([a-z_.]+)"', source))
    emitted.add(ev.VIOLATION.name)  # пишется напрямую через _write
    unused = sorted(
        name for name in ev.catalog() if not name.startswith("test.") and name not in emitted
    )
    assert unused == [], f"события каталога, которые никто не пишет: {unused}"
