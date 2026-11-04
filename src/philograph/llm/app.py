"""HTTP-интерфейс сервиса LLM, версия v1."""

from __future__ import annotations

import itertools
import json
from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from philograph import __version__
from philograph.llm.config import Budget
from philograph.llm.gateway import (
    BudgetExhausted,
    Call,
    LLMGateway,
    ProviderFailed,
    SchemaMismatch,
    UnknownRole,
)
from philograph.llm.providers import Message
from philograph.llm.templates import UnknownTemplate
from philograph.platform.health import Health
from philograph.platform.web import UserFacingError, create_app


class HistoryItem(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str


class CallBody(BaseModel):
    role: str
    template: str
    caller: str
    operation: str
    budget: Budget
    data: dict[str, str] = {}
    history: list[HistoryItem] = []
    temperature: float = 0.0
    use_cache: bool = True
    max_output_tokens: int | None = None

    def to_call(self) -> Call:
        return Call(
            role=self.role,
            template=self.template,
            caller=self.caller,
            operation=self.operation,
            budget=self.budget,
            data=self.data,
            history=tuple(Message(h.role, h.content) for h in self.history),
            temperature=self.temperature,
            use_cache=self.use_cache,
            max_output_tokens=self.max_output_tokens,
        )


class StructuredBody(CallBody):
    json_schema: dict[str, Any]


class EmbedBody(BaseModel):
    texts: list[str]
    caller: str
    operation: str
    budget: Budget


def _translate(exc: Exception) -> UserFacingError:
    if isinstance(exc, BudgetExhausted):
        kind = "budget_exhausted" if exc.scope == "day" else "run_limit_exhausted"
        return UserFacingError("лимит исчерпан", status=429, kind=kind)
    if isinstance(exc, UnknownRole):
        return UserFacingError("неизвестная роль", status=400, kind="unknown_role")
    if isinstance(exc, UnknownTemplate):
        return UserFacingError("инструкция не из шаблона", status=400, kind="unknown_template")
    if isinstance(exc, SchemaMismatch):
        return UserFacingError("ответ не соответствует схеме", status=502, kind="schema_mismatch")
    if isinstance(exc, ProviderFailed):
        return UserFacingError(
            "модель временно недоступна", status=503, kind="provider_unavailable"
        )
    raise exc


def build_app(gateway: LLMGateway, health: Health | None = None) -> FastAPI:
    health = health or Health("llm", __version__)
    app = create_app("llm", __version__, health)
    router = APIRouter(prefix="/v1")

    @router.post("/generate")
    def generate(body: CallBody) -> dict[str, Any]:
        try:
            result = gateway.generate(body.to_call())
        except Exception as exc:
            raise _translate(exc) from exc
        return {
            "text": result.text,
            "cost_usd": result.cost_usd,
            "cache_hit": result.cache_hit,
            "model": result.model,
            "template_version": result.template_version,
        }

    @router.post("/structured")
    def structured(body: StructuredBody) -> dict[str, Any]:
        try:
            return {"value": gateway.structured(body.to_call(), body.json_schema)}
        except Exception as exc:
            raise _translate(exc) from exc

    @router.post("/stream")
    def stream(body: CallBody) -> StreamingResponse:
        call = body.to_call()
        try:
            events = gateway.stream(call)
            first = next(events)
        except Exception as exc:
            raise _translate(exc) from exc

        def lines() -> Iterator[str]:
            # chain, а не [first, *events]: список прочитал бы весь поток до отправки.
            for event in itertools.chain([first], events):
                item: dict[str, Any] = {"type": event.type}
                if event.type == "delta":
                    item["text"] = event.text
                elif event.type == "done" and event.result is not None:
                    item["cost_usd"] = event.result.cost_usd
                else:
                    item["error"] = "поток прерван"
                yield json.dumps(item, ensure_ascii=False) + "\n"

        return StreamingResponse(lines(), media_type="application/x-ndjson")

    @router.post("/embed")
    def embed(body: EmbedBody) -> dict[str, Any]:
        try:
            vectors, cost = gateway.embed(
                body.texts, caller=body.caller, operation=body.operation, budget=body.budget
            )
        except Exception as exc:
            raise _translate(exc) from exc
        return {"vectors": vectors, "cost_usd": cost}

    @router.get("/spend")
    def spend(days: int = 1, group_by: str = "budget") -> list[dict[str, Any]]:
        try:
            return gateway.spend_summary(days, tuple(group_by.split(",")))
        except ValueError as exc:
            raise UserFacingError(str(exc)) from exc

    app.include_router(router)
    return app
