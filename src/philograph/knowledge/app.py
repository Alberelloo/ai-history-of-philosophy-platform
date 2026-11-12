"""HTTP-интерфейс сервиса знаний, версия v1, и подписка на события библиотеки."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from philograph import __version__
from philograph.knowledge.assist import STEPS, AssistantKnowledge
from philograph.knowledge.cards import Cards
from philograph.knowledge.entities import EntityNotFound
from philograph.knowledge.graph import Graphs, RecipeNotApplicable, hidden_by_region, ndjson
from philograph.knowledge.mentions import Mentions
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
from philograph.platform.client import ServiceClient, ServiceUnavailable
from philograph.platform.health import Health
from philograph.platform.queue import Job, Queue
from philograph.platform.web import UserFacingError, create_app

EVENTS = ("source.published", "source.unpublished", "source.deleted")
REGION_HEADER = "X-Philograph-Region"


def closed_sources(client: ServiceClient, region: str | None) -> frozenset[str]:
    """Идентификаторы источников, закрытых для региона, из ``GET /internal/access``.

    Регион приходит заголовком ``X-Philograph-Region`` от шлюза или в теле запроса ассистента.
    Библиотека сама нормализует значение; без региона она считает его неизвестным и закрывает
    все ограниченные источники. Недоступная библиотека поднимает ``ServiceUnavailable``.
    """
    params = {"region": region} if region else None
    response = client.get("internal/access", params=params)
    return frozenset(response.json().get("closed", []))


def library_paragraphs(client: ServiceClient):
    """Текст абзаца — только через интерфейс библиотеки."""

    def text(paragraph_id: str) -> str | None:
        response = client.get(f"internal/paragraphs/{paragraph_id}")
        return response.json()["text"] if response.status_code == 200 else None

    return text


def without_closed(statement: dict[str, Any], closed: frozenset[str]) -> dict[str, Any]:
    """Утверждение без подтверждений и атрибуций закрытых источников.

    Сырые маршруты (``/entities/{id}/statements`` и ``/graph``) отдают утверждения как есть;
    через шлюз они доступны читателю, поэтому цитаты, ссылки на абзацы и атрибуция источников
    закрытых для региона источников снимаются так же, как в карточке и графе.
    """
    if not closed:
        return statement
    return {
        **statement,
        "evidence": [e for e in statement.get("evidence", []) if e.get("source_id") not in closed],
        "attributions": [
            a for a in statement.get("attributions", []) if not hidden_by_region(a, closed)
        ],
    }


class Login(BaseModel):
    password: str


class Decision(BaseModel):
    decision: str
    changes: dict[str, Any] | None = None


class GraphRequest(BaseModel):
    entity_id: str
    recipe: str
    depth: int | None = None
    textbook: str | None = None  # выбранный учебник читателя
    only_textbook: bool = False  # переключатель «только выбранный учебник»
    generation: bool = True
    visitor_limited: bool = False  # ставит шлюз, когда посетитель исчерпал лимит


class AssistantContextRequest(BaseModel):
    text: str
    names: list[str] = []
    paragraphs: list[str] = []  # абзацы выделенного фрагмента
    steps: list[str] = list(STEPS)
    recipe: str | None = None
    textbook: str | None = None  # режим «только выбранный учебник»
    region: str | None = None  # регион читателя от ассистента (вызов сервис-сервис)


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
    cards: Cards | None = None,
    mentions: Mentions | None = None,
    graphs: Graphs | None = None,
    assistant: AssistantKnowledge | None = None,
    library: ServiceClient | None = None,
) -> FastAPI:
    app = create_app("knowledge", __version__, health or Health("knowledge", __version__))
    router = APIRouter(prefix="/v1")
    entities = statements.entities

    def _closed_for(region: str | None) -> frozenset[str]:
        """Множество закрытых источников для запроса; без библиотеки фильтр выключен."""
        if library is None:
            return frozenset()
        try:
            return closed_sources(library, region)
        except ServiceUnavailable as exc:
            raise UserFacingError(
                "Сервис знаний временно недоступен",
                status=503,
                kind="knowledge_unavailable",
            ) from exc

    def region_closed(request: Request) -> frozenset[str]:
        return _closed_for(request.headers.get(REGION_HEADER))

    @router.get("/entities")
    def find(name: str) -> list[dict[str, Any]]:
        return entities.find(name)

    @router.get("/entities/{entity_id}")
    def entity(entity_id: str) -> dict[str, Any]:
        return entities.get(entity_id)

    @router.get("/entities/{entity_id}/statements")
    def about(
        entity_id: str,
        family: list[str] = Query(default=[]),
        attributed_to: str | None = None,
        closed: frozenset[str] = Depends(region_closed),
    ) -> list[dict[str, Any]]:
        rows = statements.about(entity_id, families=family or None, attributed_to=attributed_to)
        return [without_closed(row, closed) for row in rows]

    @router.get("/graph")
    def graph(
        recipe: str,
        start: list[str] = Query(),
        depth: int | None = None,
        attributed_to: str | None = None,
        closed: frozenset[str] = Depends(region_closed),
    ) -> dict[str, Any]:
        try:
            result = statements.traverse(recipe, start, depth=depth, attributed_to=attributed_to)
        except RegistryError as exc:
            raise UserFacingError(str(exc), status=400, kind="recipe_not_applicable") from exc
        return {
            **result,
            "edges": [without_closed(edge, closed) for edge in result["edges"]],
        }

    if assistant is not None:

        @router.post("/internal/assistant/context")
        def assistant_context(body: AssistantContextRequest) -> dict[str, Any]:
            """Только для ассистента: шлюз внутренние адреса наружу не пропускает."""
            return assistant.context(
                text=body.text[:4000],
                names=body.names[:10],
                paragraphs=body.paragraphs[:50],
                steps=[s for s in body.steps if s in STEPS],
                recipe=body.recipe,
                textbook=body.textbook,
                closed=_closed_for(body.region),
            )

    if graphs is not None:

        @router.get("/entities/{entity_id}/recipes")
        def recipes(entity_id: str) -> list[dict[str, Any]]:
            return graphs.recipes_for(entity_id)

        @router.post("/graph/build")
        def build(
            body: GraphRequest, closed: frozenset[str] = Depends(region_closed)
        ) -> StreamingResponse:
            """Поток графа: сохранённое сразу, достроенное моделью — по мере появления."""
            try:
                graphs.check_recipe(body.entity_id, body.recipe)
            except RecipeNotApplicable as exc:
                raise UserFacingError(
                    "Этот рецепт не подходит сущности, выберите другой",
                    status=400,
                    kind="recipe_not_applicable",
                    details={"suggestions": exc.suggestions},
                ) from exc
            except RegistryError as exc:
                raise UserFacingError(str(exc), status=400, kind="unknown_recipe") from exc
            items = graphs.build(
                body.entity_id,
                body.recipe,
                depth=body.depth,
                textbook=body.textbook,
                only_textbook=body.only_textbook,
                generation=body.generation,
                visitor_limited=body.visitor_limited,
                closed=closed,
            )
            return StreamingResponse(ndjson(items), media_type="application/x-ndjson")

    if mentions is not None:

        @router.get("/mentions")
        def mentions_of(
            targets: str, closed: frozenset[str] = Depends(region_closed)
        ) -> list[dict[str, Any]]:
            """Упоминания для абзацев главы; без онтологии клиент показывает текст без них."""
            return mentions.for_targets([x for x in targets.split(",") if x][:500], closed)

        @router.get("/entities/{entity_id}/where")
        def where(
            entity_id: str, closed: frozenset[str] = Depends(region_closed)
        ) -> list[dict[str, Any]]:
            return mentions.where_to_read(entity_id, closed)

    if cards is not None:

        @router.get("/entities/{entity_id}/card")
        def card(
            entity_id: str,
            attributed_to: str | None = None,
            generation: bool = True,
            textbook: str | None = None,
            closed: frozenset[str] = Depends(region_closed),
        ) -> dict[str, Any]:
            try:
                return cards.card(
                    entity_id,
                    attributed_to=attributed_to,
                    generation=generation,
                    textbook=textbook,
                    closed=closed,
                )
            except EntityNotFound as exc:
                raise UserFacingError(
                    "Карточка не найдена", status=404, kind="entity_not_found"
                ) from exc

        @router.post("/entities/{entity_id}/description")
        def describe(entity_id: str, generation: bool = True) -> StreamingResponse:
            def lines():
                for item in cards.describe(entity_id, generation=generation):
                    yield json.dumps(item, ensure_ascii=False) + "\n"

            return StreamingResponse(lines(), media_type="application/x-ndjson")

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


def subscribe(queue: Queue, statements: Statements, filling=None, mentions=None) -> None:
    """Подписка на события библиотеки: подтверждения обновляются всегда, извлечение — если
    подключено наполнение (публикация запускает его для добавленных и изменённых абзацев)."""
    for kind in EVENTS:

        def handle(job: Job, kind: str = kind) -> None:
            statements.handle_library_event(kind, job.payload)
            if filling is not None and kind == "source.published":
                filling.handle_published(job.payload)
            if mentions is not None and kind == "source.published":
                mentions.handle_published(job.payload)
                created = list(getattr(filling, "created_entities", []))
                if filling is not None:
                    filling.created_entities.clear()
                for entity_id in created:  # новые сущности — пересчёт их названий везде
                    mentions.recompute_entity(entity_id)

        queue.handler(f"knowledge:{kind}")(handle)
