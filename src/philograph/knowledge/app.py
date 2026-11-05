"""HTTP-интерфейс сервиса знаний, версия v1, и подписка на события библиотеки."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Query, Request, Response
from pydantic import BaseModel

from philograph import __version__
from philograph.knowledge.registry import RegistryError
from philograph.knowledge.review import Review
from philograph.knowledge.statements import Statements
from philograph.operator.access import (
    SESSION_COOKIE,
    InvalidPassword,
    LoginLocked,
    OperatorAuth,
    Session,
    require,
)
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


class Login(BaseModel):
    password: str


class Decision(BaseModel):
    decision: str
    changes: dict[str, Any] | None = None


class SampleRequest(BaseModel):
    relation: str
    size: int = 20
    seed: int | None = None


def build_app(
    statements: Statements,
    health: Health | None = None,
    *,
    review: Review | None = None,
    auth: OperatorAuth | None = None,
) -> FastAPI:
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

    if review is not None and auth is not None:
        _review_routes(router, review, auth)
    app.include_router(router)
    return app


def _review_routes(router: APIRouter, review: Review, auth: OperatorAuth) -> None:
    """Страница проверки: только оператор с правом «проверять онтологию», иначе 404."""
    guard = Depends(require(auth, "review_ontology"))

    @router.post("/operator/login")
    def login(body: Login, request: Request, response: Response) -> dict[str, str]:
        address = request.headers.get(
            "X-Forwarded-For", request.client.host if request.client else "?"
        )
        try:
            token = auth.login(body.password, address)
        except LoginLocked as exc:
            raise UserFacingError(
                "Слишком много попыток, попробуйте позже", status=429, kind="locked"
            ) from exc
        except InvalidPassword as exc:
            raise UserFacingError("Неверный пароль", status=401, kind="invalid") from exc
        response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="strict")
        return {"status": "ok"}

    @router.get("/review/queue")
    def queue(
        kind: str | None = None,
        relation: str | None = None,
        source: str | None = None,
        status: str | None = None,
        session: Session = guard,
    ) -> list[dict[str, Any]]:
        review.refresh_duplicates()
        return review.queue(kind=kind, relation=relation, source=source, status=status)

    @router.get("/review/statements/{statement_id}")
    def statement(statement_id: str, session: Session = guard) -> dict[str, Any]:
        return review.context(statement_id)

    @router.post("/review/statements/{statement_id}")
    def decide(statement_id: str, body: Decision, session: Session = guard) -> dict[str, str]:
        review.decide(statement_id, body.decision, session.actor, body.changes)
        return {"status": "ok"}

    @router.post("/review/items/{item_id}/link")
    def link(item_id: int, entity_id: str, session: Session = guard) -> dict[str, str]:
        review.resolve_link(item_id, entity_id, session.actor)
        return {"status": "ok"}

    @router.post("/review/items/{item_id}/duplicate")
    def duplicate(item_id: int, merge: bool, session: Session = guard) -> dict[str, str]:
        review.resolve_duplicate(item_id, merge, session.actor)
        return {"status": "ok"}

    @router.post("/review/proposals/{proposal_id}")
    def proposal(proposal_id: int, accept: bool, session: Session = guard) -> dict[str, str]:
        review.resolve_proposal(proposal_id, accept, session.actor)
        return {"status": "ok"}

    @router.post("/review/samples")
    def sample(body: SampleRequest, session: Session = guard) -> dict[str, Any]:
        sample_id = review.sample(body.relation, body.size, body.seed)
        return {"sample": sample_id, "items": review.sample_items(sample_id)}

    @router.post("/review/samples/{sample_id}/{statement_id}")
    def sample_decision(
        sample_id: str, statement_id: str, correct: bool, session: Session = guard
    ) -> dict[str, str]:
        review.decide_sample(sample_id, statement_id, correct, session.actor)
        return {"status": "ok"}

    @router.get("/review/samples/{sample_id}/export")
    def export(sample_id: str, session: Session = guard) -> list[dict[str, Any]]:
        return review.export_sample(sample_id)


def subscribe(queue: Queue, statements: Statements, filling=None) -> None:
    """Подписка на события библиотеки: подтверждения обновляются всегда, извлечение — если
    подключено наполнение (публикация запускает его для добавленных и изменённых абзацев)."""
    for kind in EVENTS:

        def handle(job: Job, kind: str = kind) -> None:
            statements.handle_library_event(kind, job.payload)
            if filling is not None and kind == "source.published":
                filling.handle_published(job.payload)

        queue.handler(f"knowledge:{kind}")(handle)
