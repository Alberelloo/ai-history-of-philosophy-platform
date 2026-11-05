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


def topnav(page):
    """Навигация верхней панели: библиотека, текущий источник, настройки."""
    return page.get_by_role("navigation", name="Разделы")


# Версия уведомления при первом входе (web/src/Notice.tsx). Браузерные сценарии, кроме самих
# сценариев уведомления, идут от читателя, который его уже закрыл.
NOTICE_VERSION = "2026-11"
STORAGE_KEY = "philograph:v2"
_ACCEPTED = f"""
if (!localStorage.getItem("{STORAGE_KEY}")) {{
  localStorage.setItem("{STORAGE_KEY}", JSON.stringify({{version: 2, notice: "{NOTICE_VERSION}"}}));
}}
"""


def reader_context(browser, *, accepted: bool = True, **options):
    """Контекст браузера читателя; ``accepted`` — уведомление при первом входе уже закрыто.

    Язык интерфейса по умолчанию берётся из языка браузера, поэтому прежние сценарии идут
    с русской локалью.
    """
    options.setdefault("locale", "ru-RU")
    context = browser.new_context(**options)
    if accepted:
        context.add_init_script(_ACCEPTED)
    return context
