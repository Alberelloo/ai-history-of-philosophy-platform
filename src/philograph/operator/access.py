"""Вход оператора, сессии, роли и журнал действий.

Пароль хранится только хешем PBKDF2-SHA256. В сессии запоминается «эпоха» пароля — отпечаток
его хеша, поэтому после смены пароля все прежние сессии недействительны. Без доступа сервис
отвечает 404, как на несуществующую страницу, чтобы не выдавать наличие внутренних страниц.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException, Request
from sqlalchemy import JSON, Column, DateTime, Engine, Integer, MetaData, String, Table, select

from philograph.platform import events
from philograph.platform.clock import Clock, SystemClock
from philograph.platform.db import Migrations

ITERATIONS = 390_000
SESSION_COOKIE = "philograph_operator"

# Права ролей. Новая роль добавляется сюда, проверки в обработчиках не меняются.
ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "operator": frozenset(
        {
            "publish_source",
            "manage_sources",
            "review_quality",
            "edit_structure",
            "review_ontology",
            "review_portraits",
            "manage_budget",
            "view_spend",
            "run_evaluation",
        }
    ),
}

events.define("operator.login.succeeded", "info", "Оператор вошёл", required=("actor",))
events.define(
    "operator.login.failed",
    "warning",
    "Неверный пароль оператора",
    required=("address_hash", "failures"),
)
events.define(
    "operator.login.locked",
    "warning",
    "Попытки входа с адреса временно заблокированы",
    required=("address_hash", "until"),
)
events.define(
    "operator.access.denied",
    "warning",
    "Запрос к внутренней странице без права",
    required=("permission", "reason"),
)
events.define(
    "operator.action",
    "info",
    "Действие оператора, меняющее данные",
    required=("actor", "action", "target"),
    optional=("details",),
)


def hash_password(password: str, *, salt: bytes | None = None, iterations: int = ITERATIONS) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt_hex, digest_hex = stored.split("$")
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
    )
    return hmac.compare_digest(digest.hex(), digest_hex)


def _address_hash(address: str) -> str:
    return hashlib.sha256(address.encode("utf-8")).hexdigest()[:16]


class LoginLocked(Exception):
    def __init__(self, until: datetime) -> None:
        super().__init__(f"вход заблокирован до {until.isoformat()}")
        self.until = until


class InvalidPassword(Exception):
    pass


@dataclass
class Session:
    actor: str
    role: str
    epoch: str
    last_seen: datetime

    def can(self, permission: str) -> bool:
        return permission in ROLE_PERMISSIONS.get(self.role, frozenset())


@dataclass
class _Failures:
    count: int = 0
    locked_until: datetime | None = None


@dataclass
class OperatorAuth:
    password_hash: str
    clock: Clock = field(default_factory=SystemClock)
    max_failures: int = 5
    lockout: timedelta = timedelta(minutes=15)
    idle_timeout: timedelta = timedelta(minutes=30)
    _sessions: dict[str, Session] = field(default_factory=dict)
    _failures: dict[str, _Failures] = field(default_factory=dict)

    @property
    def epoch(self) -> str:
        return hashlib.sha256(self.password_hash.encode("utf-8")).hexdigest()[:16]

    def login(self, password: str, address: str, actor: str = "operator") -> str:
        now = self.clock.now()
        key = _address_hash(address)
        state = self._failures.setdefault(key, _Failures())
        if state.locked_until is not None and now < state.locked_until:
            raise LoginLocked(state.locked_until)
        if not verify_password(password, self.password_hash):
            state.count += 1
            events.emit("operator.login.failed", address_hash=key, failures=state.count)
            if state.count >= self.max_failures:
                state.locked_until = now + self.lockout
                state.count = 0
                events.emit(
                    "operator.login.locked", address_hash=key, until=state.locked_until.isoformat()
                )
            raise InvalidPassword()
        self._failures.pop(key, None)
        token = secrets.token_urlsafe(32)
        self._sessions[token] = Session(actor, "operator", self.epoch, now)
        events.emit("operator.login.succeeded", actor=actor)
        return token

    def session(self, token: str | None) -> Session | None:
        if not token:
            return None
        session = self._sessions.get(token)
        if session is None:
            return None
        now = self.clock.now()
        if session.epoch != self.epoch or now - session.last_seen > self.idle_timeout:
            self._sessions.pop(token, None)
            return None
        session.last_seen = now
        return session

    def logout(self, token: str) -> None:
        self._sessions.pop(token, None)

    def change_password(self, new_hash: str) -> None:
        """Как перезапуск с новым паролем в настройке: все сессии становятся недействительны."""
        self.password_hash = new_hash


def require(auth: OperatorAuth, permission: str) -> Callable[[Request], Session]:
    """Зависимость FastAPI: пускает только с правом ``permission``, иначе 404."""

    def dependency(request: Request) -> Session:
        token = request.cookies.get(SESSION_COOKIE) or request.headers.get("X-Operator-Token")
        session = auth.session(token)
        if session is None:
            events.emit("operator.access.denied", permission=permission, reason="no_session")
            raise HTTPException(status_code=404, detail="Not Found")
        if not session.can(permission):
            events.emit("operator.access.denied", permission=permission, reason="no_permission")
            raise HTTPException(status_code=404, detail="Not Found")
        return session

    return dependency


# --- журнал действий оператора --------------------------------------------------------

SCHEMA = "operator"
metadata = MetaData()
actions = Table(
    "actions",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("time", DateTime(timezone=True), nullable=False),
    Column("actor", String(100), nullable=False),
    Column("action", String(100), nullable=False),
    Column("target", String(200), nullable=False),
    Column("details", JSON),
    schema=SCHEMA,
)
migrations = Migrations(SCHEMA, metadata)
migrations.add(1, "журнал действий")(migrations.create_tables("actions"))


class ActionLog:
    def __init__(self, engine: Engine, clock: Clock | None = None) -> None:
        self.engine = engine
        self.clock = clock or SystemClock()

    def record(
        self,
        actor: Session | str,
        action: str,
        target: str,
        details: dict[str, Any] | None = None,
        *,
        conn: Any = None,
    ) -> None:
        """Записывает действие. ``conn`` — чтобы попасть в ту же транзакцию, что и само действие."""
        name = actor.actor if isinstance(actor, Session) else actor
        values = {
            "time": self.clock.now(),
            "actor": name,
            "action": action,
            "target": target,
            "details": details,
        }
        if conn is not None:
            conn.execute(actions.insert().values(**values))
        else:
            with self.engine.begin() as own:
                own.execute(actions.insert().values(**values))
        events.emit("operator.action", actor=name, action=action, target=target, details=details)

    def entries(self) -> list[dict[str, Any]]:
        with self.engine.begin() as conn:
            return [
                dict(r) for r in conn.execute(select(actions).order_by(actions.c.id)).mappings()
            ]
