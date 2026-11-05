"""Требования спецификации abuse-protection: настоящий шлюз, за ним — поддельные сервисы."""

from __future__ import annotations

import json
import re

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from philograph.gateway.app import build_app
from philograph.gateway.limits import PAGE_COOKIE, Limits, LimitSettings, Quota

req = pytest.mark.req
AP = "abuse-protection"
UA = {"User-Agent": "Mozilla/5.0 test"}


class Upstreams:
    """Ассистент, сервис знаний и библиотека в одном приложении: считают вызовы."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        app = FastAPI()

        @app.post("/assistant/v1/ask")
        async def ask(request: Request):
            self.calls.append(("ask", await request.json()))
            return StreamingResponse(
                iter([json.dumps({"type": "done"}) + "\n"]), media_type="application/x-ndjson"
            )

        @app.post("/knowledge/v1/graph/build")
        async def graph(request: Request):
            body = await request.json()
            self.calls.append(("graph", body))
            return StreamingResponse(
                iter([json.dumps({"type": "graph", "request": body}) + "\n"]),
                media_type="application/x-ndjson",
            )

        @app.post("/knowledge/v1/entities/{entity_id}/description")
        async def describe(entity_id: str, request: Request):
            self.calls.append(("description", dict(request.query_params)))
            return StreamingResponse(
                iter([json.dumps({"type": "done", "text": "описание"}) + "\n"]),
                media_type="application/x-ndjson",
            )

        @app.get("/knowledge/v1/entities/{entity_id}/card")
        def card(entity_id: str):
            return {"id": entity_id}

        @app.get("/library/api/v1/sources")
        def sources():
            return {"items": []}

        self.app = app

    def count(self, kind: str) -> int:
        return len([c for c in self.calls if c[0] == kind])


@pytest.fixture
def gw(tmp_path, clock):
    root = tmp_path / "web"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<html>PhiloGraph</html>", encoding="utf-8")
    up = Upstreams()
    tick = {"now": 0.0}
    settings = LimitSettings(
        rate_per_second=1000.0,
        burst=1000,
        quotas={"ask": Quota(2, 3), "graph": Quota(1, 5), "description": Quota(1, 5)},
        trusted_proxy=True,
    )
    limits = Limits(settings, "секрет", clock, monotonic=lambda: tick["now"])
    app = build_app(
        {
            "assistant": "http://up/assistant",
            "knowledge": "http://up/knowledge",
            "library": "http://up/library",
        },
        root,
        transport=httpx.ASGITransport(app=up.app),
        limits=limits,
    )
    client = TestClient(app)

    def visit(address: str = "203.0.113.5") -> TestClient:
        """Читатель открыл страницу продукта и получил токен."""
        c = TestClient(app, headers={**UA, "X-Forwarded-For": address})
        assert c.get("/read").status_code == 200
        assert c.cookies.get(PAGE_COOKIE)
        return c

    def ask(c: TestClient) -> list[dict]:
        response = c.post("/api/assistant/v1/ask", json={"question": "что такое опыт?"})
        return [json.loads(line) for line in response.text.splitlines() if line.strip()]

    return type(
        "GW",
        (),
        {
            "up": up,
            "client": client,
            "visit": staticmethod(visit),
            "ask": staticmethod(ask),
            "limits": limits,
            "tick": tick,
            "clock": clock,
            "app": app,
        },
    )


@req(AP, "Лимит платных операций на посетителя")
def test_paid_operations_limited_per_hour_and_day(gw):
    reader = gw.visit()
    assert gw.ask(reader) == [{"type": "done"}]
    assert gw.ask(reader) == [{"type": "done"}]
    refused = gw.ask(reader)[0]
    assert refused["type"] == "unavailable" and refused["reason"] == "visitor_limit"
    assert (
        0 < refused["retry_after_seconds"] <= 3600 and "Спросите снова через" in refused["message"]
    )
    assert gw.up.count("ask") == 2  # модель не вызывалась
    gw.clock.advance(hours=1, seconds=1)
    assert gw.ask(reader) == [{"type": "done"}]
    gw.clock.advance(hours=1, seconds=1)
    assert gw.ask(reader)[0]["reason"] == "visitor_limit"  # суточный предел — три
    # Другой посетитель не зависит от первого.
    assert gw.ask(gw.visit("198.51.100.7")) == [{"type": "done"}]
    # Описание карточки: сверх лимита — без вызова модели; без генерации не считается.
    for _ in range(3):
        reader.post("/api/knowledge/v1/entities/e1/description?generation=false")
    assert reader.post("/api/knowledge/v1/entities/e1/description").json()["type"] == "done"
    limited = reader.post("/api/knowledge/v1/entities/e1/description").text
    assert json.loads(limited) == {"type": "unavailable", "reason": "visitor_limit"}
    assert gw.up.count("description") == 4


@req(AP, "Бесплатное без ограничений платных")
def test_free_operations_after_limit(gw):
    reader = gw.visit()
    for _ in range(3):
        gw.ask(reader)
    assert gw.ask(reader)[0]["reason"] == "visitor_limit"
    assert reader.get("/api/v1/sources").status_code == 200
    assert reader.get("/api/knowledge/v1/entities/e1/card").json() == {"id": "e1"}
    graph = {"entity_id": "e1", "recipe": "genesis", "generation": True}
    reader.post("/api/knowledge/v1/graph/build", json=graph)
    second = json.loads(reader.post("/api/knowledge/v1/graph/build", json=graph).text)
    # Граф всё равно строится — из сохранённых связей, без достройки моделью.
    assert second["request"]["generation"] is False and second["request"]["visitor_limited"] is True
    assert gw.up.count("graph") == 2


@req(AP, "Общий лимит частоты")
def test_rate_limit_per_address(gw):
    gw.limits.settings = LimitSettings(rate_per_second=2.0, burst=3, trusted_proxy=True)
    bot = TestClient(gw.app, headers={**UA, "X-Forwarded-For": "192.0.2.1"})
    statuses = [bot.get("/api/v1/sources").status_code for _ in range(5)]
    assert statuses == [200, 200, 200, 429, 429]
    response = bot.get("/api/v1/sources")
    assert response.status_code == 429 and response.json()["kind"] == "rate_limited"
    assert int(response.headers["Retry-After"]) >= 1
    other = TestClient(gw.app, headers={**UA, "X-Forwarded-For": "192.0.2.2"})
    assert other.get("/api/v1/sources").status_code == 200  # сайт отвечает остальным
    gw.tick["now"] += 1.0  # через секунду корзина пополнилась
    assert bot.get("/api/v1/sources").status_code == 200


@req(AP, "Защита от автоматических запросов")
def test_paid_operation_requires_page_token(gw):
    script = TestClient(gw.app, headers=UA)
    response = script.post("/api/assistant/v1/ask", json={"question": "?"})
    assert response.status_code == 403 and response.json()["kind"] == "page_token_required"
    script.cookies.set(PAGE_COOKIE, "1700000000.forged")
    assert script.post("/api/assistant/v1/ask", json={"question": "?"}).status_code == 403
    reader = gw.visit()
    other_browser = TestClient(gw.app, headers={"User-Agent": "curl/8"})
    other_browser.cookies.set(PAGE_COOKIE, reader.cookies.get(PAGE_COOKIE))
    assert other_browser.post("/api/assistant/v1/ask", json={"question": "?"}).status_code == 403
    assert gw.up.count("ask") == 0
    assert gw.ask(reader) == [{"type": "done"}]
    gw.clock.advance(hours=13)  # токен устарел — нужно снова открыть страницу
    assert reader.post("/api/assistant/v1/ask", json={"question": "?"}).status_code == 403


@req(AP, "Журнал срабатываний")
def test_limit_events_without_personal_data(gw, events):
    reader = gw.visit("203.0.113.5")
    for _ in range(3):
        gw.ask(reader)
    (event,) = events.where("gateway.limit.triggered", kind="hourly")
    assert event["operation"] == "ask" and re.fullmatch(r"[0-9a-f]{20}", event["visitor"])
    assert "203.0.113.5" not in repr(events.of("gateway.limit.triggered"))
