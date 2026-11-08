"""Подмена ответа ассистента в браузере (reader-panels.md, 14.1).

Ответы — готовые строки NDJSON через ``page.route``: так проверяются пометки, ошибки и переходы,
а не модель. Ответ ``HOLD`` не отдаётся сразу: запрос висит (поток идёт), пока тест не вызовет
``release``; так моделируется долгий ответ.
"""

from __future__ import annotations

import contextlib
import json
from collections import deque

HOLD = object()
STORAGE = "philograph:v4"


def ndjson(*events: dict) -> str:
    return "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events)


def fragment(text: str, *citations: dict, grounded: bool | None = None) -> dict:
    return {
        "type": "fragment",
        "text": text,
        "grounded": bool(citations) if grounded is None else grounded,
        "unverified_quotes": [],
        "contradicts": [],
        "citations": list(citations),
    }


def cite(source_id: str, chapter_id: str, paragraph_id: str, **extra) -> dict:
    return {
        "kind": "paragraph",
        "paragraph_id": paragraph_id,
        "statement_id": None,
        "entity_id": None,
        "source_id": source_id,
        "chapter_id": chapter_id,
        "title": extra.get("title", "Раздел"),
        "source_title": extra.get("source_title"),
        "chapter_title": extra.get("chapter_title"),
        "paragraph_start": extra.get("paragraph_start"),
    }


DONE = {"type": "done", "answer_language": "русский"}


def answer(*events: dict) -> str:
    return ndjson(
        {"type": "stage", "name": "searching"},
        {"type": "stage", "name": "composing", "found": 2},
        *events,
        DONE,
    )


class AskStub:
    """Подмена ``/api/assistant/v1/ask``: очередь ответов и запись запросов."""

    def __init__(self, target) -> None:
        self.requests: list[dict] = []
        self.replies: deque = deque()
        self.held: list = []
        target.route("**/api/assistant/v1/ask", self._handle)

    def reply(self, *bodies) -> AskStub:
        self.replies.extend(bodies)
        return self

    def _handle(self, route, request) -> None:
        self.requests.append(request.post_data_json)
        body = (
            self.replies.popleft() if self.replies else answer(fragment("Ответ.", grounded=False))
        )
        if body is HOLD:
            self.held.append(route)
            return
        if isinstance(body, tuple):  # (статус, JSON) — ошибка до потока
            status, data = body
            route.fulfill(status=status, content_type="application/json", body=json.dumps(data))
            return
        route.fulfill(status=200, content_type="application/x-ndjson", body=body)

    def release(self, body: str) -> None:
        route = self.held.pop(0)
        # Запрос мог быть уже отменён клиентом (тайм-аут, удаление сессии).
        with contextlib.suppress(Exception):
            route.fulfill(status=200, content_type="application/x-ndjson", body=body)


def stored(page) -> dict:
    return json.loads(page.evaluate(f"localStorage.getItem('{STORAGE}')") or "{}")


def panel(page):
    return page.get_by_role("complementary", name="Ассистент")


def ask(box, text: str) -> None:
    """Вопрос в панели или на странице раздела (``box`` — их область)."""
    box.get_by_label("Вопрос ассистенту").fill(text)
    box.get_by_role("button", name="Спросить", exact=True).click()


def new_session(box) -> None:
    box.get_by_role("button", name="Новая сессия", exact=True).click()


def open_assistant(page) -> None:
    page.locator(".toc__assistant").click()
    panel(page).wait_for()


def go(page, path: str) -> None:
    """Переход внутри приложения (как щелчок по ссылке): панель остаётся открытой."""
    page.evaluate(
        "path => { history.pushState(null, '', path);"
        " dispatchEvent(new PopStateEvent('popstate')); }",
        path,
    )
