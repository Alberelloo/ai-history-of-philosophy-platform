"""API-шлюз: единственный сервис, который виден снаружи.

Отдаёт веб-клиент, проксирует ``/api/assistant/*`` в ассистента, ``/api/*`` — в библиотеку.
Ответы идут потоком, без буферизации: первое слово ассистента не ждёт конца ответа.
Внутренние интерфейсы сервисов (``/api/v1/internal/*``) снаружи недоступны. Здесь же лимиты
запросов и защита бюджета (``gateway.limits``), регион читателя (``gateway.region``), а когда
появятся — аккаунты.
"""

from __future__ import annotations

import http.cookiejar
import json
import math
import os
from collections.abc import Iterator
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

from philograph import __version__
from philograph.gateway.limits import PAGE_COOKIE, Limits, LimitSettings, paid_operation
from philograph.gateway.region import REGION_HEADER, RegionResolver, RegionSettings
from philograph.platform import context, events
from philograph.platform.health import Health
from philograph.platform.metrics import metrics
from philograph.platform.web import create_app

events.define(
    "gateway.proxy.failed", "warning", "Сервис за шлюзом не ответил", required=("target", "reason")
)
events.define(
    "gateway.internal.blocked", "warning", "Запрос к внутреннему адресу снаружи", required=("path",)
)


class _NoStoreCookies(http.cookiejar.CookieJar):
    """Шлюз не хранит cookie сервисов: общий клиент не должен переносить сессии.

    Иначе `Set-Cookie` от ``/operator/login`` оседал бы в cookie-jar шлюза и подставлялся
    в запросы других посетителей — очередь проверки открывалась без входа. Cookie посетителя
    пересылается явно как обычный заголовок, а `Set-Cookie` доходит до браузера в ответе.
    """

    def set_cookie(self, cookie) -> None:
        return None


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


def _ndjson(*items: dict) -> StreamingResponse:
    def lines() -> Iterator[str]:
        for item in items:
            yield json.dumps(item, ensure_ascii=False) + "\n"

    return StreamingResponse(lines(), media_type="application/x-ndjson")


def _add_vary(headers: dict[str, str], name: str) -> None:
    """Добавить заголовок запроса в ``Vary``, не потеряв прежние значения сервиса."""
    key = next((k for k in headers if k.lower() == "vary"), None)
    existing = [v.strip() for v in headers.get(key, "").split(",") if v.strip()] if key else []
    if name.lower() not in {v.lower() for v in existing}:
        existing.append(name)
    if key is not None:
        headers.pop(key)
    headers["Vary"] = ", ".join(existing)


def build_app(
    upstreams: dict[str, str],
    web_root: Path | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    limits: Limits | None = None,
    regions: RegionResolver | None = None,
) -> FastAPI:
    """``upstreams``: ``{"library": url, "assistant": url}``; ``limits`` — защита бюджета;
    ``regions`` — определение региона читателя (без него регион всегда неизвестен)."""
    health = Health("gateway", __version__)
    app = create_app("gateway", __version__, health)
    client = httpx.AsyncClient(
        timeout=httpx.Timeout(10.0, read=120.0),
        transport=transport,
        cookies=_NoStoreCookies(),
    )

    def who(request: Request) -> tuple[str, str]:
        address = limits.address(
            request.client.host if request.client else None,
            request.headers.get("X-Forwarded-For"),
        )
        return address, request.headers.get("User-Agent", "")

    if limits is not None:

        @app.middleware("http")
        async def rate(request: Request, call_next):
            """Общий лимит частоты с одного адреса — для всех запросов, включая статику."""
            address, user_agent = who(request)
            wait = limits.rate(address)
            if wait is None:
                return await call_next(request)
            seconds = max(1, math.ceil(wait))
            events.emit(
                "gateway.limit.triggered",
                kind="rate",
                visitor=limits.visitor(address, user_agent),
                retry_after_seconds=seconds,
            )
            return JSONResponse(
                {
                    "error": "Слишком много запросов, попробуйте чуть позже",
                    "kind": "rate_limited",
                    "retry_after_seconds": seconds,
                },
                status_code=429,
                headers={"Retry-After": str(seconds)},
            )

    async def guard(request: Request, body: bytes) -> Response | bytes:
        """Платные операции: токен страницы и лимит посетителя. Возвращает ответ отказа
        или тело запроса, которое уйдёт сервису (для графа — без достройки)."""
        operation = paid_operation(request.method, request.url.path)
        if limits is None or operation is None:
            return body
        address, user_agent = who(request)
        visitor = limits.visitor(address, user_agent)
        if not limits.check_token(request.cookies.get(PAGE_COOKIE), user_agent):
            events.emit(
                "gateway.limit.triggered", kind="page_token", visitor=visitor, operation=operation
            )
            return JSONResponse(
                {
                    "error": "Откройте страницу продукта, чтобы пользоваться этой возможностью",
                    "kind": "page_token_required",
                },
                status_code=403,
            )
        payload = json.loads(body or b"{}") if operation == "graph" else {}
        if operation == "graph" and not payload.get("generation", True):
            return body  # без достройки — бесплатно
        if operation == "description" and request.query_params.get("generation") == "false":
            return body
        refused = limits.paid(visitor, operation)
        if refused is None:
            return body
        kind, seconds = refused
        events.emit(
            "gateway.limit.triggered",
            kind=kind,
            visitor=visitor,
            operation=operation,
            retry_after_seconds=seconds,
        )
        if operation == "graph":
            # Граф из сохранённых связей бесплатен: строится, но без достройки моделью.
            return json.dumps({**payload, "generation": False, "visitor_limited": True}).encode()
        if operation == "description":
            return _ndjson({"type": "unavailable", "reason": "visitor_limit"})
        minutes = max(1, seconds // 60)
        return _ndjson(
            {
                "type": "unavailable",
                "reason": "visitor_limit",
                "retry_after_seconds": seconds,
                "message": f"Слишком много вопросов подряд. Спросите снова через {minutes} мин. "
                "Чтение и карточки работают.",
            }
        )

    async def proxy(request: Request, target: str, path: str) -> Response:
        # Строка запроса уходит как есть: разбор и сборка заново теряли повторяющиеся ключи
        # (kind=textbook&kind=primary превращалось в kind=primary).
        url = httpx.URL(f"{upstreams[target].rstrip('/')}/{path}").copy_with(
            query=request.scope["query_string"]
        )
        body = await guard(request, await request.body())
        if isinstance(body, Response):
            return body
        # Регион читателя: страна от CDN, иначе запасной. В счётчике только «известен /
        # неизвестен» — страны и посетителя в метриках нет (design.md, п. 1).
        region = regions.region(request.headers) if regions is not None else None
        metrics.inc("gateway.region", kind="known" if region else "unknown")
        dropped = regions.dropped_headers() if regions is not None else {REGION_HEADER.lower()}
        headers = {
            k: v
            for k, v in request.headers.items()
            if k.lower() not in HOP_HEADERS and k.lower() not in dropped
        }
        if region is not None:
            headers[REGION_HEADER] = region
        # Сервисам — адрес посетителя, а не обратного прокси перед шлюзом.
        headers["X-Forwarded-For"] = (
            who(request)[0]
            if limits is not None
            else (request.client.host if request.client else "unknown")
        )
        headers[context.REQUEST_ID_HEADER] = context.request_id() or context.new_id()
        upstream = client.build_request(
            request.method,
            url,
            headers=headers,
            content=body,
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
        # Портреты — неизменяемые файлы, не зависящие от региона: их кеш не трогаем, чтобы
        # читатель получал `public, max-age=31536000, immutable` от сервиса знаний.
        portrait = target == "knowledge" and path.startswith("v1/portraits/")
        if not portrait:
            # Ответ API зависит от региона читателя: CDN не должен кэшировать его между странами.
            # Прежние значения снимаем без учёта регистра: httpx отдаёт имена в нижнем регистре,
            # иначе в ответе остались бы два Cache-Control — «public» сервиса и «private» шлюза.
            for key in [k for k in out_headers if k.lower() == "cache-control"]:
                out_headers.pop(key)
            out_headers["Cache-Control"] = "private"
            vary = regions.vary() if regions is not None else None
            if vary:
                _add_vary(out_headers, vary)
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
        if path.startswith(("v1/internal", "internal")):
            events.emit("gateway.internal.blocked", path=f"/api/knowledge/{path}")
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        if "knowledge" not in upstreams:
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
        def spa(path: str, request: Request) -> FileResponse:
            response = FileResponse(web_root / "index.html")
            if limits is not None:
                # Токен страницы: платные операции доступны только со страницы продукта.
                response.set_cookie(
                    PAGE_COOKIE,
                    limits.page_token(request.headers.get("User-Agent", "")),
                    max_age=limits.settings.token_ttl_seconds,
                    httponly=True,
                    samesite="strict",
                    secure=request.headers.get("X-Forwarded-Proto") == "https",
                )
            return response

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
    _limits = Limits(
        LimitSettings.from_env(dict(os.environ)),
        os.environ.get("PHILOGRAPH_VISITOR_SECRET", "dev-secret"),
    )
    _regions = RegionResolver(RegionSettings.from_env(dict(os.environ)))
    app = build_app(_upstreams, Path(_root) if _root else None, limits=_limits, regions=_regions)
