"""Настоящий шлюз с поддельными сервисами: регион читателя (``regional-access``)."""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from philograph.gateway.app import build_app
from philograph.gateway.region import REGION_HEADER, RegionResolver, RegionSettings
from philograph.platform.metrics import metrics

req = pytest.mark.req
RA = "regional-access"


class Services:
    """Библиотека за шлюзом: запоминает заголовки, с которыми к ней пришли.

    Отвечает со своим ``Cache-Control``: настоящая библиотека кэширует список, и шлюз обязан
    заменить это значение, а не дописать второе.
    """

    def __init__(self) -> None:
        self.seen: list[dict[str, str]] = []
        app = FastAPI()

        @app.get("/library/api/v1/sources")
        def sources(request: Request):
            self.seen.append({k.lower(): v for k, v in request.headers.items()})
            return JSONResponse({"items": []}, headers={"Cache-Control": "public, max-age=300"})

        self.app = app


def gateway(settings: RegionSettings | None) -> tuple[TestClient, Services]:
    services = Services()
    app = build_app(
        {"library": "http://up/library", "assistant": "http://up/assistant"},
        transport=httpx.ASGITransport(app=services.app),
        regions=RegionResolver(settings) if settings is not None else None,
    )
    return TestClient(app), services


def region_seen(services: Services) -> str | None:
    return services.seen[-1].get(REGION_HEADER.lower())


@req(RA, "Регион читателя определяет шлюз")
def test_region_from_trusted_proxy():
    """Читатель из РФ за CDN: сервис получает X-Philograph-Region: RU."""
    client, services = gateway(RegionSettings(header="CF-IPCountry", trusted_proxy=True))
    response = client.get("/api/v1/sources", headers={"CF-IPCountry": "RU"})
    assert response.status_code == 200
    assert region_seen(services) == "RU"


@req(RA, "Регион читателя определяет шлюз")
def test_client_region_header_ignored():
    """Подделанный клиентом регион заменяется страной от CDN."""
    client, services = gateway(RegionSettings(header="CF-IPCountry", trusted_proxy=True))
    client.get(
        "/api/v1/sources",
        headers={"CF-IPCountry": "DE", REGION_HEADER: "RU"},
    )
    assert region_seen(services) == "DE"
    assert "cf-ipcountry" not in services.seen[-1]  # заголовок CDN сервису не нужен


@req(RA, "Регион читателя определяет шлюз")
def test_client_region_without_country():
    """Клиентский заголовок региона без страны от CDN не проходит: регион неизвестен."""
    client, services = gateway(RegionSettings(header="CF-IPCountry", trusted_proxy=True))
    client.get("/api/v1/sources", headers={REGION_HEADER: "RU"})
    assert region_seen(services) is None


@req(RA, "Неизвестный регион закрывает ограниченные источники")
def test_untrusted_proxy_ignores_country():
    """Запрос не от доверенного прокси: заголовок страны игнорируется, регион неизвестен."""
    client, services = gateway(RegionSettings(header="CF-IPCountry", trusted_proxy=False))
    client.get("/api/v1/sources", headers={"CF-IPCountry": "RU", REGION_HEADER: "RU"})
    assert region_seen(services) is None


@req(RA, "Неизвестный регион закрывает ограниченные источники")
def test_fallback_region_for_local_stand():
    """Стенд разработки: запасной регион RU вместо неизвестного, в том числе без прокси."""
    for trusted in (True, False):
        client, services = gateway(
            RegionSettings(header="CF-IPCountry", trusted_proxy=trusted, fallback="RU")
        )
        client.get("/api/v1/sources")
        assert region_seen(services) == "RU"


@req(RA, "Регион читателя определяет шлюз")
def test_api_response_is_private_and_varies():
    """Ответ API зависит от страны: Cache-Control: private и Vary на заголовок страны.

    Сервис отдаёт свой ``public, max-age=300``: шлюз обязан его заменить, а не дописать второй
    заголовок — иначе CDN кэширует ответ между странами.
    """
    client, _ = gateway(RegionSettings(header="CF-IPCountry", trusted_proxy=True))
    response = client.get("/api/v1/sources", headers={"CF-IPCountry": "RU"})
    assert response.headers.get_list("cache-control") == ["private"]
    assert "cf-ipcountry" in response.headers["vary"].lower()


@req(RA, "Регион читателя определяет шлюз")
def test_unknown_region_counted_without_country():
    """Доля неизвестных регионов видна счётчиком; кода страны в метриках нет."""
    client, _ = gateway(RegionSettings(header="CF-IPCountry", trusted_proxy=True))

    def counted() -> dict[str, float]:
        return {
            c["labels"].get("kind", "?"): c["value"]
            for c in metrics.snapshot()["counters"]
            if c["name"] == "gateway.region"
        }

    before = counted()
    client.get("/api/v1/sources", headers={"CF-IPCountry": "RU"})
    client.get("/api/v1/sources")
    after = counted()
    assert after.get("known", 0) - before.get("known", 0) == 1
    assert after.get("unknown", 0) - before.get("unknown", 0) == 1
    text = json.dumps(metrics.snapshot(), ensure_ascii=False)
    assert "CF-IPCountry" not in text and '"RU"' not in text


@req(RA, "Регион читателя определяет шлюз")
def test_gateway_without_settings_still_strips_client_region():
    """Шлюз без новых настроек ведёт себя как раньше, но клиентский регион не пропускает."""
    client, services = gateway(None)
    response = client.get("/api/v1/sources", headers={REGION_HEADER: "RU"})
    assert response.status_code == 200
    assert region_seen(services) is None
    assert response.headers["cache-control"] == "private"
