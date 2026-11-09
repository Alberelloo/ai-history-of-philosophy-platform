"""Связь ассистента с соседями по HTTP: поиск и сервис LLM."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from philograph.platform.client import ServiceClient, ServiceUnavailable


class LlmUnavailable(Exception):
    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind  # budget_exhausted | provider_unavailable | ...


class SearchHttp:
    def __init__(self, client: ServiceClient) -> None:
        self.client = client

    def search(self, **query: Any) -> dict[str, Any]:
        return self.client.post("search", json=query).json()


class LibraryHttp:
    """Названия глав для подсказок ссылок (N4): оглавление источника из библиотеки.

    Поиск хранит у абзаца только заголовок раздела, а подсказке ссылки нужно название главы.
    Оглавление запоминается на источник (оно меняется только с новой версией источника);
    недоступная библиотека не мешает ответу — название главы просто не приходит.
    """

    def __init__(self, client: ServiceClient, max_sources: int = 200) -> None:
        self.client = client
        self.max_sources = max_sources
        self._titles: dict[str, dict[str, str]] = {}

    def chapter_titles(self, source_id: str) -> dict[str, str]:
        if source_id in self._titles:
            return self._titles[source_id]
        try:
            response = self.client.get(f"sources/{source_id}/toc")
            items = response.json() if response.status_code == 200 else []
        except (ServiceUnavailable, ValueError):  # сеть или испорченный ответ: без названий
            return {}
        titles: dict[str, str] = {}

        def walk(nodes: list[dict[str, Any]]) -> None:
            for node in nodes:
                if node.get("id") and node.get("id") == node.get("chapter_id"):
                    titles.setdefault(node["id"], node.get("title") or "")
                walk(node.get("children") or [])

        walk(items if isinstance(items, list) else [])
        if len(self._titles) >= self.max_sources:
            self._titles.pop(next(iter(self._titles)))
        self._titles[source_id] = titles
        return titles


class LlmHttp:
    def __init__(self, client: ServiceClient) -> None:
        self.client = client

    def _call(
        self,
        role: str,
        template: str,
        data: dict[str, str],
        operation: str,
        history: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        return {
            "role": role,
            "template": template,
            "caller": "assistant",
            "operation": operation,
            "budget": "site",
            "data": data,
            "history": history or [],
        }

    def structured(
        self, role: str, template: str, data: dict[str, str], schema: dict, operation: str
    ) -> dict[str, Any]:
        response = self.client.post(
            "structured",
            json={**self._call(role, template, data, operation), "json_schema": schema},
        )
        if response.status_code != 200:
            raise LlmUnavailable(response.json().get("kind", "error"))
        return response.json()["value"]

    def stream(
        self, role: str, template: str, data: dict[str, str], operation: str
    ) -> Iterator[dict[str, Any]]:
        with self.client.stream(
            "POST", "stream", json=self._call(role, template, data, operation)
        ) as response:
            if response.status_code != 200:
                response.read()
                raise LlmUnavailable(response.json().get("kind", "error"))
            for line in response.iter_lines():
                if line.strip():
                    yield json.loads(line)
