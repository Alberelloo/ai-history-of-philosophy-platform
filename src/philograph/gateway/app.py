"""API-шлюз: единственный сервис, который виден снаружи.

Отдаёт веб-клиент, проксирует ``/api/assistant/*`` в ассистента, ``/api/*`` — в библиотеку.
Ответы идут потоком, без буферизации: первое слово ассистента не ждёт конца ответа.
Внутренние интерфейсы сервисов (``/api/v1/internal/*``) снаружи недоступны. Позже здесь же
лимиты запросов (``abuse-protection``) и, когда появятся, аккаунты.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

from philograph import __version__
from philograph.platform import context, events
from philograph.platform.health import Health
from philograph.platform.web import create_app

events.define(
    "gateway.proxy.failed", "warning", "Сервис за шлюзом не ответил", required=("target", "reason")
)
events.define(
    "gateway.internal.blocked", "warning", "Запрос к внутреннему адресу снаружи", required=("path",)
)

HOP_HEADERS = {
    "connection",
    "keep-alive",
    "transfer-encoding",
    "te",
    "upgrade",
    "proxy-authorization",
    "proxy-authenticate",
    "host",
    "content-length",
}


def build_app(
    upstreams: dict[str, str],
    web_root: Path | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    """``upstreams``: ``{"library": url, "assistant": url}``."""
    health = Health("gateway", __version__)
    app = create_app("gateway", __version__, health)
    client = httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=120.0), transport=transport)

    async def proxy(request: Request, target: str, path: str) -> Response:
        url = f"{upstreams[target].rstrip('/')}/{path}"
        headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_HEADERS}
        headers["X-Forwarded-For"] = request.client.host if request.client else "unknown"
        headers[context.REQUEST_ID_HEADER] = context.request_id() or context.new_id()
        upstream = client.build_request(
            request.method,
            url,
            params=request.query_params,
            headers=headers,
            content=await request.body(),
        )
        try:
            response = await client.send(upstream, stream=True)
        except httpx.TransportError as exc:
            events.emit("gateway.proxy.failed", target=target, reason=type(exc).__name__)
            return JSONResponse(
                {"error": "Сервис временно недоступен", "request_id": context.request_id()},
                status_code=503,
            )
        out_headers = {k: v for k, v in response.headers.items() if k.lower() not in HOP_HEADERS}
        return StreamingResponse(
            response.aiter_raw(),
            status_code=response.status_code,
            headers=out_headers,
            background=BackgroundTask(response.aclose),
        )

    @app.api_route("/api/assistant/{path:path}", methods=["GET", "POST"])
    async def assistant(path: str, request: Request) -> Response:
        return await proxy(request, "assistant", path)

    @app.api_route("/api/knowledge/{path:path}", methods=["GET", "POST"])
    async def knowledge(path: str, request: Request) -> Response:
        if "knowledge" not in upstreams or path.startswith(("v1/internal", "internal")):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        return await proxy(request, "knowledge", path)

    @app.api_route("/api/{path:path}", methods=["GET", "POST"])
    async def library(path: str, request: Request) -> Response:
        if path.startswith(("v1/internal", "internal")):
            events.emit("gateway.internal.blocked", path=f"/api/{path}")
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        return await proxy(request, "library", f"api/{path}")

    if web_root is not None and (web_root / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=web_root / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            return FileResponse(web_root / "index.html")

    return app


if os.environ.get("PHILOGRAPH_LIBRARY_URL") and os.environ.get("PHILOGRAPH_ASSISTANT_URL"):
    events.configure(sinks=[events.json_sink()])
    _root = os.environ.get("PHILOGRAPH_WEB_ROOT")
    _upstreams = {
        "library": os.environ["PHILOGRAPH_LIBRARY_URL"],
        "assistant": os.environ["PHILOGRAPH_ASSISTANT_URL"],
    }
    if os.environ.get("PHILOGRAPH_KNOWLEDGE_URL"):
        _upstreams["knowledge"] = os.environ["PHILOGRAPH_KNOWLEDGE_URL"]
    app = build_app(_upstreams, Path(_root) if _root else None)
