"""Помощники тестов."""

from __future__ import annotations

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient


def asgi_transport(app: FastAPI) -> httpx.BaseTransport:
    """Синхронный транспорт httpx поверх приложения: вызов сервиса без сети."""
    test_client = TestClient(app, raise_server_exceptions=False)

    class Transport(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            response = test_client.request(
                request.method,
                str(request.url.raw_path, "ascii"),
                headers=dict(request.headers),
                content=request.read(),
            )
            return httpx.Response(
                response.status_code, headers=response.headers, content=response.content
            )

    return Transport()
