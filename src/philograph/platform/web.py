"""Общее для HTTP-приложений сервисов: контекст запроса, понятные ошибки, проверки состояния."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from philograph.platform import context, events
from philograph.platform.health import Health
from philograph.platform.metrics import metrics

events.define(
    "http.request.completed",
    "info",
    "Сервис ответил на запрос",
    required=("method", "route", "status", "duration_ms"),
)
events.define(
    "http.request.failed",
    "error",
    "Внутренняя ошибка при обработке запроса",
    required=("method", "route", "detail"),
)
events.define("service.started", "info", "Сервис запущен", required=("version",))


class UserFacingError(Exception):
    """Ошибка с сообщением, которое можно показать пользователю."""

    def __init__(self, message: str, *, status: int = 400, kind: str = "user_error") -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.kind = kind


def create_app(
    service: str,
    version: str,
    health: Health,
    *,
    internal_error_message: str = "Не удалось выполнить запрос",
) -> FastAPI:
    app = FastAPI(title=f"philograph-{service}", version=version)

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        rid = request.headers.get(context.REQUEST_ID_HEADER) or context.new_id()
        run = request.headers.get(context.RUN_ID_HEADER)
        started = time.perf_counter()
        with context.scope(service=service, request_id=rid, run_id=run):
            try:
                response = await call_next(request)
            except Exception as exc:
                route = request.scope.get("route")
                events.emit(
                    "http.request.failed",
                    method=request.method,
                    route=getattr(route, "path", request.url.path),
                    detail=f"{type(exc).__name__}: {exc}",
                    error_kind="internal",
                )
                response = JSONResponse(
                    {"error": internal_error_message, "request_id": rid}, status_code=500
                )
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            route = request.scope.get("route")
            route_path = getattr(route, "path", request.url.path)
            events.emit(
                "http.request.completed",
                method=request.method,
                route=route_path,
                status=response.status_code,
                duration_ms=duration_ms,
            )
            metrics.inc("http.requests", route=route_path, status=str(response.status_code))
            metrics.observe("http.duration_ms", duration_ms, route=route_path)
            response.headers[context.REQUEST_ID_HEADER] = rid
            return response

    @app.exception_handler(UserFacingError)
    async def user_error(request: Request, exc: UserFacingError) -> JSONResponse:
        return JSONResponse(
            {"error": exc.message, "kind": exc.kind, "request_id": context.request_id()},
            status_code=exc.status,
        )

    @app.get("/health/live")
    def live() -> dict[str, str]:
        return health.live()

    @app.get("/health/ready")
    def ready() -> JSONResponse:
        report = health.check()
        body = {
            "ready": report.ready,
            "service": service,
            "version": report.version,
            "problems": report.problems,
            "degraded": report.degraded,
        }
        return JSONResponse(body, status_code=200 if report.ready else 503)

    with context.scope(service=service):
        events.emit("service.started", version=version)
    return app
