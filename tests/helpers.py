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


def sidenav(page):
    """Навигация боковой панели, раскрытой наведением: подписи и список открытых книг видны."""
    page.locator(".sidebar__brand").hover()
    page.locator('.sidebar[data-state="expanded"], .sidebar[data-state="pinned"]').wait_for()
    return page.get_by_role("navigation", name="Разделы")


def aside(page) -> None:
    """Уводит указатель в правый нижний угол: слева — боковая панель.

    Панель раскрывается наведением и перекрывает кнопки под собой. Указатель, оставшийся
    над ней после клика по пункту меню (или возвращённый в угол 0,0 прошлой страницей),
    раскрывает её, и следующий клик по тексту попадает в панель, а не в кнопку.
    """
    size = page.viewport_size or {"width": 1280, "height": 800}
    page.mouse.move(size["width"] - 5, size["height"] - 5)


def via_sidebar(page, name: str) -> None:
    """Переход по пункту боковой панели; указатель уходит, и панель сворачивается."""
    sidenav(page).get_by_role("link", name=name).first.click()
    aside(page)


# Версия уведомления при первом входе (web/src/Notice.tsx). Браузерные сценарии, кроме самих
# сценариев уведомления, идут от читателя, который его уже закрыл.
NOTICE_VERSION = "2026-11"
STORAGE_KEY = "philograph:v3"
_ACCEPTED = f"""
if (!localStorage.getItem("{STORAGE_KEY}")) {{
  localStorage.setItem("{STORAGE_KEY}", JSON.stringify({{version: 3, notice: "{NOTICE_VERSION}"}}));
}}
"""


def reader_context(browser, *, accepted: bool = True, **options):
    """Контекст браузера читателя; ``accepted`` — уведомление при первом входе уже закрыто.

    Язык интерфейса по умолчанию берётся из языка браузера, поэтому прежние сценарии идут
    с русской локалью.
    """
    options.setdefault("locale", "ru-RU")
    context = browser.new_context(**options)
    # Новая страница начинается с указателем в углу: иначе он достаётся от прошлой страницы
    # (браузер помнит положение мыши) и раскрывает боковую панель поверх кнопок.
    context.on("page", aside)
    if accepted:
        context.add_init_script(_ACCEPTED)
    return context
