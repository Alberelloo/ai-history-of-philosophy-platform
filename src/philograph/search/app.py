"""HTTP-интерфейс поиска, версия v1, и подписка индексации на события библиотеки."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, FastAPI
from pydantic import BaseModel, Field

from philograph import __version__
from philograph.platform.health import Health
from philograph.platform.queue import Job, Queue
from philograph.platform.web import create_app
from philograph.search.indexing import Indexer
from philograph.search.searching import Query, Searcher

EVENTS = ("source.published", "source.unpublished", "source.deleted")


class SearchBody(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    sources: list[str] | None = None
    languages: list[str] | None = None
    exclude: list[str] = []
    exclude_sources: list[str] = []
    extra_terms: list[str] = []
    priority: list[str] = []
    neighbors: int = Field(default=0, ge=0, le=3)
    per_chapter: int = Field(default=3, ge=1, le=20)
    limit: int = Field(default=10, ge=1, le=50)


def build_app(searcher: Searcher, indexer: Indexer, health: Health | None = None) -> FastAPI:
    app = create_app("search", __version__, health or Health("search", __version__))
    router = APIRouter(prefix="/v1")

    @router.post("/search")
    def search(body: SearchBody) -> dict[str, Any]:
        return searcher.search(Query(text=body.query, **body.model_dump(exclude={"query"})))

    @router.post("/internal/reconcile")
    def reconcile() -> dict[str, int]:
        return indexer.reconcile()

    @router.get("/internal/estimate")
    def estimate() -> dict[str, float]:
        return indexer.estimate()

    app.include_router(router)
    return app


def subscribe(queue: Queue, indexer: Indexer) -> None:
    for kind in EVENTS:

        def handle(job: Job, kind: str = kind) -> None:
            indexer.handle(kind, job.payload)

        queue.handler(f"search:{kind}")(handle)
