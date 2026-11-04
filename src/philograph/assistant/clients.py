"""Связь ассистента с соседями по HTTP: поиск и сервис LLM."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from philograph.platform.client import ServiceClient


class LlmUnavailable(Exception):
    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind  # budget_exhausted | provider_unavailable | ...


class SearchHttp:
    def __init__(self, client: ServiceClient) -> None:
        self.client = client

    def search(self, **query: Any) -> dict[str, Any]:
        return self.client.post("search", json=query).json()


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
