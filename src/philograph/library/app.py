"""HTTP-интерфейс библиотеки для читателя, версия v1, и раздача веб-клиента."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from philograph import __version__
from philograph.library.reading import NotVisible, Reading
from philograph.platform.health import Health
from philograph.platform.web import UserFacingError, create_app


def build_app(
    reading: Reading, health: Health | None = None, web_root: Path | None = None
) -> FastAPI:
    health = health or Health("library", __version__)
    app = create_app(
        "library", __version__, health, internal_error_message="Не удалось открыть главу"
    )
    router = APIRouter(prefix="/v1")

    @router.get("/sources")
    def sources(
        kind: list[str] = Query(default=[]), lang: list[str] = Query(default=[]), q: str = ""
    ) -> dict[str, Any]:
        return reading.sources(kinds=kind or None, languages=lang or None, query=q)

    @router.get("/current")
    def current(remembered: str | None = None) -> dict[str, Any]:
        return reading.resolve_current(remembered)

    @router.get("/sources/{source_id}/toc")
    def toc(source_id: str) -> list[dict[str, Any]]:
        try:
            return reading.toc(source_id)
        except NotVisible as exc:
            raise UserFacingError(
                "Источник недоступен", status=404, kind="source_unavailable"
            ) from exc

    @router.get("/sources/{source_id}/chapters/{chapter_id}")
    def chapter(source_id: str, chapter_id: str) -> dict[str, Any]:
        try:
            return reading.chapter(source_id, chapter_id)
        except NotVisible as exc:
            raise UserFacingError(
                "Источник недоступен", status=404, kind="source_unavailable"
            ) from exc
        except KeyError as exc:
            raise UserFacingError("Глава не найдена", status=404, kind="chapter_not_found") from exc

    @router.get("/paragraphs/{paragraph_id}")
    def paragraph(paragraph_id: str) -> dict[str, Any]:
        return reading.resolve_paragraph(paragraph_id)

    app.include_router(router, prefix="/api")

    if web_root is not None and (web_root / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=web_root / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            # Клиент сам разбирает адрес: любая страница отдаёт index.html.
            return FileResponse(web_root / "index.html")

    return app
