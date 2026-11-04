"""Требования спецификации operator-access."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient

from philograph.operator.access import (
    ROLE_PERMISSIONS,
    SESSION_COOKIE,
    ActionLog,
    InvalidPassword,
    LoginLocked,
    OperatorAuth,
    Session,
    hash_password,
    migrations,
    require,
)
from philograph.platform.health import Health
from philograph.platform.web import create_app

req = pytest.mark.req
SRC = Path(__file__).resolve().parents[2] / "src" / "philograph"


@pytest.fixture
def auth(clock) -> OperatorAuth:
    return OperatorAuth(hash_password("верный пароль", iterations=1000), clock=clock)


def _app(auth: OperatorAuth):
    app = create_app("review", "0.1.0", Health("review", "0.1.0"))

    @app.get("/internal/review")
    def review(session: Session = Depends(require(auth, "review_ontology"))) -> dict:
        return {"queue": [], "actor": session.actor}

    return TestClient(app)


@req("operator-access", "Вход оператора")
def test_internal_pages_hidden_until_login(auth, events):
    client = _app(auth)
    anonymous = client.get("/internal/review")
    missing = client.get("/no/such/page")
    assert anonymous.status_code == missing.status_code == 404
    assert anonymous.json() == missing.json()  # не отличить от несуществующей страницы
    assert events.where("operator.access.denied", reason="no_session")
    assert "верный пароль" not in auth.password_hash

    token = auth.login("верный пароль", "203.0.113.5")
    client.cookies.set(SESSION_COOKIE, token)
    ok = client.get("/internal/review")
    assert ok.status_code == 200 and ok.json()["actor"] == "operator"
    events.one("operator.login.succeeded")


@req("operator-access", "Защита от подбора пароля")
def test_lockout_after_repeated_failures(auth, events, clock):
    for _ in range(5):
        with pytest.raises(InvalidPassword):
            auth.login("не тот", "198.51.100.7")
    lock = events.one("operator.login.locked")
    assert "198.51.100.7" not in str(lock.fields)  # адрес только хешем
    with pytest.raises(LoginLocked):
        auth.login("верный пароль", "198.51.100.7")
    auth.login("верный пароль", "192.0.2.1")  # другой адрес не заблокирован
    clock.advance(minutes=16)
    auth.login("верный пароль", "198.51.100.7")


@req("operator-access", "Срок и завершение сессии оператора")
def test_session_expiry_logout_and_password_change(auth, clock):
    token = auth.login("верный пароль", "a")
    clock.advance(minutes=29)
    assert auth.session(token) is not None
    clock.advance(minutes=31)
    assert auth.session(token) is None

    token = auth.login("верный пароль", "a")
    auth.logout(token)
    assert auth.session(token) is None

    token = auth.login("верный пароль", "a")
    auth.change_password(hash_password("новый пароль", iterations=1000))
    assert auth.session(token) is None


@req("operator-access", "Журнал действий оператора")
def test_operator_actions_are_recorded(auth, engine_for, clock, events):
    log = ActionLog(engine_for(migrations), clock)
    session = auth.session(auth.login("верный пароль", "a"))
    log.record(session, "reject_statement", "statement:42", {"reason": "нет в источнике"})
    entry = log.entries()[0]
    assert (entry["actor"], entry["action"], entry["target"]) == (
        "operator",
        "reject_statement",
        "statement:42",
    )
    assert entry["time"] is not None
    assert events.one("operator.action")["target"] == "statement:42"


@req("operator-access", "Роли на будущее")
def test_permissions_checked_by_role(auth, events):
    session = auth.session(auth.login("верный пароль", "a"))
    assert session.can("publish_source") and not session.can("delete_everything")
    session.role = "teacher"  # роли без права не пускают
    client = _app(auth)
    client.cookies.set(SESSION_COOKIE, next(iter(auth._sessions)))
    assert client.get("/internal/review").status_code == 404
    assert events.where("operator.access.denied", reason="no_permission")
    assert set(ROLE_PERMISSIONS) == {"operator"}

    # Обработчики спрашивают право, а не факт входа: проверки ``require`` всегда с правом.
    for path in SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "require":
                assert len(node.args) == 2, f"{path.name}: require без права"
