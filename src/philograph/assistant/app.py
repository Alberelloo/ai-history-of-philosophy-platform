"""HTTP-интерфейс ассистента, версия v1: ответ — поток событий NDJSON."""

from __future__ import annotations

import json
import os
from collections.abc import Iterator

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from philograph import __version__
from philograph.assistant.service import AskRequest, Assistant
from philograph.platform.health import Health
from philograph.platform.privacy import visitor_hash
from philograph.platform.web import create_app


class Turn(BaseModel):
    question: str
    answer: str = ""


class AskBody(BaseModel):
    question: str = ""
    selection: str | None = None
    selection_paragraphs: list[str] = Field(default_factory=list, max_length=50)
    source_id: str | None = None
    history: list[Turn] = Field(default_factory=list, max_length=50)
    sources_only: bool = False
    generation: bool = True
    scope: str = Field(default="all", pattern="^(all|current)$")


def build_app(assistant: Assistant, health: Health | None = None) -> FastAPI:
    app = create_app("assistant", __version__, health or Health("assistant", __version__))
    router = APIRouter(prefix="/v1")
    secret = os.environ.get("PHILOGRAPH_VISITOR_SECRET", "dev-secret")

    @router.post("/ask")
    def ask(body: AskBody, request: Request) -> StreamingResponse:
        address = request.headers.get(
            "X-Forwarded-For", request.client.host if request.client else "unknown"
        )
        visitor = visitor_hash(
            address, request.headers.get("User-Agent", ""), assistant.clock.now(), secret
        )
        events = assistant.ask(
            AskRequest(
                question=body.question,
                visitor=visitor,
                selection=body.selection,
                selection_paragraphs=body.selection_paragraphs,
                source_id=body.source_id,
                history=[t.model_dump() for t in body.history],
                sources_only=body.sources_only,
                generation=body.generation,
                scope=body.scope,
            )
        )

        def lines() -> Iterator[str]:
            for event in events:
                yield json.dumps(event, ensure_ascii=False) + "\n"

        return StreamingResponse(lines(), media_type="application/x-ndjson")

    app.include_router(router)
    return app
