"""HTTP-интерфейс сервиса знаний, версия v1, и подписка на события библиотеки."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, FastAPI, Query

from philograph import __version__
from philograph.knowledge.registry import RegistryError
from philograph.knowledge.statements import Statements
from philograph.platform.client import ServiceClient
from philograph.platform.health import Health
from philograph.platform.queue import Job, Queue
from philograph.platform.web import UserFacingError, create_app

EVENTS = ("source.published", "source.unpublished", "source.deleted")


def library_paragraphs(client: ServiceClient):
    """Текст абзаца — только через интерфейс библиотеки."""

    def text(paragraph_id: str) -> str | None:
        response = client.get(f"internal/paragraphs/{paragraph_id}")
        return response.json()["text"] if response.status_code == 200 else None

    return text


def build_app(statements: Statements, health: Health | None = None) -> FastAPI:
    app = create_app("knowledge", __version__, health or Health("knowledge", __version__))
    router = APIRouter(prefix="/v1")
    entities = statements.entities

    @router.get("/entities")
    def find(name: str) -> list[dict[str, Any]]:
        return entities.find(name)

    @router.get("/entities/{entity_id}")
    def entity(entity_id: str) -> dict[str, Any]:
        return entities.get(entity_id)

    @router.get("/entities/{entity_id}/statements")
    def about(
        entity_id: str, family: list[str] = Query(default=[]), attributed_to: str | None = None
    ) -> list[dict[str, Any]]:
        return statements.about(entity_id, families=family or None, attributed_to=attributed_to)

    @router.get("/graph")
    def graph(
        recipe: str,
        start: list[str] = Query(),
        depth: int | None = None,
        attributed_to: str | None = None,
    ) -> dict[str, Any]:
        try:
            return statements.traverse(recipe, start, depth=depth, attributed_to=attributed_to)
        except RegistryError as exc:
            raise UserFacingError(str(exc), status=400, kind="recipe_not_applicable") from exc

    app.include_router(router)
    return app


def subscribe(queue: Queue, statements: Statements) -> None:
    for kind in EVENTS:

        def handle(job: Job, kind: str = kind) -> None:
            statements.handle_library_event(kind, job.payload)

        queue.handler(f"knowledge:{kind}")(handle)
