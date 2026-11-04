"""Клиент для вызова другого сервиса: версия интерфейса, таймаут, повтор безопасных операций.

Сервис получает данные соседа только так, а не из его таблиц. Идентификатор запроса и
запуска уходит дальше в заголовках, поэтому события всей цепочки связаны.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import httpx

from philograph.platform import context, events

events.define(
    "service.call.failed",
    "warning",
    "Вызов другого сервиса не удался",
    required=("target", "path", "reason", "attempts"),
)

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class ServiceUnavailable(Exception):
    def __init__(self, target: str, reason: str) -> None:
        super().__init__(f"{target}: {reason}")
        self.target = target
        self.reason = reason


class ServiceClient:
    def __init__(
        self,
        target: str,
        base_url: str,
        *,
        api_version: str = "v1",
        timeout: float = 5.0,
        retries: int = 1,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.target = target
        self.api_version = api_version
        self.retries = retries
        self._http = httpx.Client(base_url=base_url, timeout=timeout, transport=transport)

    def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        method = method.upper()
        url = f"/{self.api_version}/{path.lstrip('/')}"
        attempts = 1 + (self.retries if method in SAFE_METHODS else 0)
        headers = {**context.outgoing_headers(), **kwargs.pop("headers", {})}
        reason = ""
        for attempt in range(1, attempts + 1):
            try:
                response = self._http.request(method, url, headers=headers, **kwargs)
            except httpx.TimeoutException:
                reason = "таймаут"
            except httpx.TransportError as exc:
                reason = f"нет связи: {type(exc).__name__}"
            else:
                if response.status_code < 500:
                    return response
                reason = f"ответ {response.status_code}"
            if attempt == attempts:
                break
        events.emit(
            "service.call.failed", target=self.target, path=url, reason=reason, attempts=attempts
        )
        raise ServiceUnavailable(self.target, reason)

    def get(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("POST", path, **kwargs)

    @contextmanager
    def stream(self, method: str, path: str, **kwargs: Any) -> Iterator[httpx.Response]:
        """Потоковый ответ соседа. Таймаут и обрыв — ``ServiceUnavailable``, без повторов."""
        url = f"/{self.api_version}/{path.lstrip('/')}"
        headers = {**context.outgoing_headers(), **kwargs.pop("headers", {})}
        try:
            with self._http.stream(method.upper(), url, headers=headers, **kwargs) as response:
                yield response
        except httpx.TimeoutException:
            events.emit(
                "service.call.failed", target=self.target, path=url, reason="таймаут", attempts=1
            )
            raise ServiceUnavailable(self.target, "таймаут") from None
        except httpx.TransportError as exc:
            events.emit(
                "service.call.failed",
                target=self.target,
                path=url,
                reason=f"нет связи: {type(exc).__name__}",
                attempts=1,
            )
            raise ServiceUnavailable(self.target, "нет связи") from None
