"""HTTP-интерфейс библиотеки для читателя, версия v1, и раздача веб-клиента."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from philograph import __version__
from philograph.library.reading import (
    ANONYMOUS,
    ChapterNotFound,
    Internal,
    NotVisible,
    Reader,
    Reading,
    parse_region,
)
from philograph.platform.health import Health
from philograph.platform.web import UserFacingError, create_app

# Заголовок ставит шлюз: клиентский регион отбрасывается и подделываться не может.
REGION_HEADER = "X-Philograph-Region"


def _reader(request: Request) -> Reader:
    """Читатель запроса: регион из заголовка шлюза; нет заголовка — регион неизвестен."""
    region = parse_region(request.headers.get(REGION_HEADER))
    return Reader(region=region) if region else ANONYMOUS


def build_app(
    reading: Reading,
    health: Health | None = None,
    web_root: Path | None = None,
    mounts: dict[str, FastAPI] | None = None,
) -> FastAPI:
    """``mounts`` — соседние сервисы под общим адресом (для разработки и тестов; в работе
    их объединяет шлюз)."""
    health = health or Health("library", __version__)
    app = create_app(
        "library", __version__, health, internal_error_message="Не удалось открыть главу"
    )
    router = APIRouter(prefix="/v1")

    @router.get("/sources")
    def sources(
        request: Request,
        kind: list[str] = Query(default=[]),
        lang: list[str] = Query(default=[]),
        q: str = "",
    ) -> dict[str, Any]:
        return reading.sources(
            _reader(request), kinds=kind or None, languages=lang or None, query=q
        )

    @router.get("/current")
    def current(request: Request, remembered: str | None = None) -> dict[str, Any]:
        return reading.resolve_current(remembered, _reader(request))

    @router.get("/sources/{source_id}/toc")
    def toc(source_id: str, request: Request) -> list[dict[str, Any]]:
        try:
            return reading.toc(source_id, _reader(request))
        except NotVisible as exc:
            raise UserFacingError(
                "Источник недоступен", status=404, kind="source_unavailable"
            ) from exc

    @router.get("/sources/{source_id}/chapters/{chapter_id}")
    def chapter(source_id: str, chapter_id: str, request: Request) -> dict[str, Any]:
        try:
            return reading.chapter(source_id, chapter_id, _reader(request))
        except NotVisible as exc:
            raise UserFacingError(
                "Источник недоступен", status=404, kind="source_unavailable"
            ) from exc
        except ChapterNotFound as exc:
            # Первая глава — чтобы клиент остался в книге, а не показывал ошибку.
            raise UserFacingError(
                "Глава не найдена",
                status=404,
                kind="chapter_not_found",
                details={"first_chapter_id": exc.first},
            ) from exc

    @router.get("/paragraphs/{paragraph_id}")
    def paragraph(paragraph_id: str, request: Request) -> dict[str, Any]:
        return reading.resolve_paragraph(paragraph_id, _reader(request))

    internal = Internal(reading.registry, reading)

    @router.get("/internal/versions/{version_id}/paragraphs")
    def version_paragraphs(version_id: str) -> dict[str, Any]:
        return internal.version_paragraphs(version_id)

    @router.get("/internal/paragraphs/{paragraph_id}")
    def paragraph_text(paragraph_id: str) -> dict[str, Any]:
        found = internal.paragraph_text(paragraph_id)
        if found is None:
            raise UserFacingError("Абзац не найден", status=404, kind="paragraph_not_found")
        return found

    @router.get("/internal/published")
    def published() -> list[dict[str, str]]:
        return internal.published()

    @router.get("/internal/access")
    def access(region: str | None = None) -> dict[str, Any]:
        return internal.access(region)

    app.include_router(router, prefix="/api")
    for path, sub in (mounts or {}).items():
        app.mount(path, sub)

    if web_root is not None and (web_root / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=web_root / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            # Клиент сам разбирает адрес: любая страница отдаёт index.html.
            return FileResponse(web_root / "index.html")

    return app
