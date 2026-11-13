"""Шлюз не переносит сессию оператора между посетителями (F1 раунда 1 portrait-sourcing)."""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from philograph.gateway.app import build_app
from philograph.operator.access import SESSION_COOKIE, OperatorAuth, hash_password


@pytest.fixture
def knowledge() -> tuple[FastAPI, dict]:
    """Сервис знаний с настоящей проверкой оператора и фиктивной очередью портретов."""
    app = FastAPI()
    auth = OperatorAuth(hash_password("пароль", iterations=1000))
    state: dict = {"hidden": False}

    def allowed(request: Request) -> bool:
        token = request.cookies.get(SESSION_COOKIE) or request.headers.get("X-Operator-Token")
        return auth.session(token) is not None

    @app.post("/v1/operator/login")
    def login(payload: dict):
        token = auth.login(payload["password"], "127.0.0.1")
        out = JSONResponse({"status": "ok"})
        out.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="strict")
        return out

    @app.get("/v1/review/portraits")
    def queue(request: Request):
        # Как в knowledge/app.py: без сессии — 404, как на несуществующую страницу.
        if not allowed(request):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        return [{"id": 10, "label": "Кант"}]

    @app.post("/v1/review/portraits/{portrait_id}")
    def decide(portrait_id: int, action: str, request: Request):
        if not allowed(request):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        state["hidden"] = action == "hide"
        return {"status": "ok"}

    return app, state


def gateway_app(knowledge: FastAPI) -> FastAPI:
    """Один шлюз на процесс — именно его общий клиент и проверяем."""
    return build_app(
        {"knowledge": "http://knowledge"}, transport=httpx.ASGITransport(app=knowledge)
    )


@pytest.mark.req("operator-access", "Вход оператора")
def test_operator_session_is_not_shared_between_requests(knowledge):
    """Вход через шлюз не даёт доступа запросам без cookie: очередь и действия — 404."""
    service, state = knowledge
    shared = gateway_app(service)
    operator = TestClient(shared)
    assert (
        operator.post("/api/knowledge/v1/operator/login", json={"password": "пароль"}).status_code
        == 200
    )
    assert operator.get("/api/knowledge/v1/review/portraits").status_code == 200

    # Тот же шлюз, но другой посетитель без своего cookie: общий cookie-jar не должен
    # подставить ему сессию оператора.
    stranger = TestClient(shared)
    assert stranger.get("/api/knowledge/v1/review/portraits").status_code == 404
    assert stranger.post("/api/knowledge/v1/review/portraits/10?action=hide").status_code == 404
    assert state["hidden"] is False  # действие не выполнено

    # Сессия оператора продолжает работать: его Cookie пересылается шлюзом.
    assert operator.post("/api/knowledge/v1/review/portraits/10?action=hide").status_code == 200
    assert state["hidden"] is True


@pytest.mark.req("operator-access", "Вход оператора")
def test_login_cookie_reaches_browser_and_is_forwarded(knowledge):
    """Set-Cookie доходит до посетителя, а его Cookie пересылается сервису знаний."""
    service, _ = knowledge
    client = TestClient(gateway_app(service))
    response = client.post("/api/knowledge/v1/operator/login", json={"password": "пароль"})
    assert SESSION_COOKIE in response.cookies
    assert client.get("/api/knowledge/v1/review/portraits").status_code == 200
