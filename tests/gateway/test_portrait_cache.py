"""Портреты через шлюз: файл неизменяемый и не зависит от региона, кеш не подменяется."""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response
from fastapi.testclient import TestClient

from philograph.gateway.app import build_app
from philograph.gateway.region import RegionResolver, RegionSettings

req = pytest.mark.req
RA = "entity-portraits"


def knowledge_app() -> FastAPI:
    """Сервис знаний: портрет отдаёт долгий кеш, карточка — обычный ответ API."""
    app = FastAPI()

    @app.get("/v1/portraits/{portrait_id}")
    def portrait(portrait_id: int):
        return Response(
            content=b"\x89PNG\r\n\x1a\n",
            media_type="image/png",
            headers={
                "ETag": "abc",
                "Cache-Control": "public, max-age=31536000, immutable",
            },
        )

    @app.get("/v1/entities/{entity_id}/card")
    def card(entity_id: str):
        return JSONResponse({"id": entity_id}, headers={"Cache-Control": "public, max-age=300"})

    return app


def gateway() -> TestClient:
    app = build_app(
        {"library": "http://library", "knowledge": "http://knowledge"},
        transport=httpx.ASGITransport(app=knowledge_app()),
        regions=RegionResolver(RegionSettings(header="CF-IPCountry", trusted_proxy=True)),
    )
    return TestClient(app)


@req(RA, "Хранение и раздача изображений")
def test_portrait_keeps_long_cache_through_gateway():
    """Шлюз не подменяет Cache-Control портрета на private: файл неизменяемый."""
    response = gateway().get("/api/knowledge/v1/portraits/7", headers={"CF-IPCountry": "RU"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert response.headers["etag"] == "abc"
    assert response.headers["content-type"] == "image/png"


@req(RA, "Регион читателя определяет шлюз")
def test_other_knowledge_responses_stay_private():
    """Остальные ответы знаний по-прежнему private и с Vary на заголовок страны."""
    response = gateway().get("/api/knowledge/v1/entities/e1/card", headers={"CF-IPCountry": "RU"})
    assert response.headers["cache-control"] == "private"
    assert "cf-ipcountry" in response.headers["vary"].lower()
