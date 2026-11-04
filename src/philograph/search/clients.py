"""Связь поиска с соседями: библиотека (абзацы) и сервис LLM (эмбеддинги) — по HTTP."""

from __future__ import annotations

from typing import Any

from philograph.platform.client import ServiceClient


class LibraryHttp:
    def __init__(self, client: ServiceClient) -> None:
        self.client = client

    def version_paragraphs(self, version_id: str) -> dict[str, Any]:
        return self.client.get(f"internal/versions/{version_id}/paragraphs").json()

    def published(self) -> list[dict[str, str]]:
        return self.client.get("internal/published").json()


class EmbeddingError(Exception):
    pass


class LlmEmbedder:
    """Эмбеддинги через сервис LLM: расходы индексации — «наполнение», запросов — «сайт»."""

    def __init__(self, client: ServiceClient, model: str, dimension: int) -> None:
        self.client = client
        self.model = model
        self.dimension = dimension

    def embed(self, texts: list[str], *, budget: str) -> list[list[float]]:
        operation = "index" if budget == "filling" else "query"
        response = self.client.post(
            "embed",
            json={"texts": texts, "caller": "search", "operation": operation, "budget": budget},
        )
        if response.status_code != 200:
            raise EmbeddingError(response.json().get("kind", str(response.status_code)))
        return response.json()["vectors"]
