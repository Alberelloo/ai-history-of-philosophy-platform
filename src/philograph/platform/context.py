"""Контекст запроса: идентификатор запроса или запуска и сервис, подставляются в каждое событие."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_run_id: ContextVar[str | None] = ContextVar("run_id", default=None)
_service: ContextVar[str | None] = ContextVar("service", default=None)

REQUEST_ID_HEADER = "X-Request-Id"
RUN_ID_HEADER = "X-Run-Id"


def new_id() -> str:
    return uuid.uuid4().hex


def current() -> dict[str, str]:
    """Поля контекста, которые попадают в событие."""
    fields = {}
    if (rid := _request_id.get()) is not None:
        fields["request_id"] = rid
    if (run := _run_id.get()) is not None:
        fields["run_id"] = run
    if (svc := _service.get()) is not None:
        fields["service"] = svc
    return fields


def request_id() -> str | None:
    return _request_id.get()


def run_id() -> str | None:
    return _run_id.get()


def outgoing_headers() -> dict[str, str]:
    """Заголовки для вызова другого сервиса: идентификатор идёт дальше по цепочке."""
    headers = {}
    if (rid := _request_id.get()) is not None:
        headers[REQUEST_ID_HEADER] = rid
    if (run := _run_id.get()) is not None:
        headers[RUN_ID_HEADER] = run
    return headers


@contextmanager
def scope(
    *, service: str | None = None, request_id: str | None = None, run_id: str | None = None
) -> Iterator[None]:
    """Задаёт контекст на время блока; незаданные поля наследуются."""
    tokens = []
    if service is not None:
        tokens.append((_service, _service.set(service)))
    if request_id is not None:
        tokens.append((_request_id, _request_id.set(request_id)))
    if run_id is not None:
        tokens.append((_run_id, _run_id.set(run_id)))
    try:
        yield
    finally:
        for var, token in reversed(tokens):
            var.reset(token)
