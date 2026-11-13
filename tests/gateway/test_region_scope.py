"""8.3: регион читателя через настоящий шлюз.

Шлюз, библиотека и ассистент (с настоящим поиском за ним) поднимаются в одном процессе, но
через штатные HTTP-интерфейсы: клиент ходит только в шлюз, а шлюз передаёт регион сервисам
заголовком. Проверяется, что читатель из РФ получает библиотеку, главу и абзацы закрытого
источника, а читатель из другой страны — нет.
"""

from __future__ import annotations

import json
import re

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from philograph.assistant.app import build_app as assistant_app
from philograph.gateway.app import build_app as gateway_app
from philograph.gateway.region import REGION_HEADER, RegionResolver, RegionSettings
from philograph.library.app import build_app as library_app
from philograph.library.reading import Reading
from philograph.library.registry import License

from ..assistant.conftest import bot  # noqa: F401 — стенд ассистента с настоящим поиском
from ..search.conftest import rig as search_rig  # noqa: F401 — стенд поиска для этой фикстуры

req = pytest.mark.req
RA = "regional-access"

RESTRICTED_TEXT = "Глава 1\n\nЗЕТА-9 — признак рассудка, разум даёт принципы познания.\n"


def add_restricted(bot) -> str:
    """Источник только для РФ: регистрируется и публикуется как настоящий, проходит индексацию."""
    rig = bot.rig
    rig.registry.add_license_kind(
        "ru-only",
        "Только РФ",
        None,
        {"display": True, "external_processing": True, "quoting": True},
        regions=["RU"],
    )
    lic = License("ru-only", "public_domain", author_death_years=[1900])
    source_id = rig.registry.register(
        "operator",
        title="Доступный в РФ",
        authors=["А"],
        language="ru",
        kind="textbook",
        license=lic,
        scope="public",
        files=[{"name": "r", "path": "restricted.txt"}],
    )
    rig.files["restricted.txt"] = RESTRICTED_TEXT.encode()
    rig.ids["restricted"] = source_id
    return source_id


class _ByHost(httpx.AsyncBaseTransport):
    """Один транспорт шлюза поверх нескольких приложений: маршрут по имени хоста в upstream."""

    def __init__(self, apps: dict[str, FastAPI]) -> None:
        self._clients = {host: httpx.ASGITransport(app=app) for host, app in apps.items()}

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return await self._clients[request.url.host].handle_async_request(request)


def gateway(bot, *, trusted: bool = True, fallback: str | None = None) -> TestClient:
    apps = {
        "library": library_app(Reading(bot.rig.registry, bot.rig.registry.engine)),
        "assistant": assistant_app(bot.assistant),
    }
    app = gateway_app(
        {"library": "http://library", "assistant": "http://assistant"},
        transport=_ByHost(apps),
        regions=RegionResolver(
            RegionSettings(header="CF-IPCountry", trusted_proxy=trusted, fallback=fallback)
        ),
    )
    return TestClient(app)


def chapter_text(client: TestClient, source_id: str, country: str) -> tuple[int, str]:
    """Оглавление и первая глава источника через шлюз; ``country`` — страна от CDN."""
    headers = {"CF-IPCountry": country}
    toc = client.get(f"/api/v1/sources/{source_id}/toc", headers=headers)
    if toc.status_code != 200:
        return toc.status_code, ""
    chapter_id = toc.json()[0]["id"]
    chapter = client.get(f"/api/v1/sources/{source_id}/chapters/{chapter_id}", headers=headers)
    return chapter.status_code, json.dumps(chapter.json(), ensure_ascii=False)


def ask(client: TestClient, country: str) -> list[dict]:
    """Вопрос ассистенту через шлюз; возвращает события потока."""
    response = client.post(
        "/api/assistant/v1/ask",
        json={"question": "ЗЕТА-9"},
        headers={"CF-IPCountry": country},
    )
    assert response.status_code == 200
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


@req(RA, "Регион читателя определяет шлюз")
def test_region_from_cdn_opens_library_and_chapter(bot):
    """Читатель из РФ через шлюз открывает библиотеку, оглавление и главу закрытого источника."""
    restricted = add_restricted(bot)
    bot.rig.publish("restricted")
    client = gateway(bot)

    ru = client.get("/api/v1/sources", headers={"CF-IPCountry": "RU"})
    row = next(s for s in ru.json()["sources"] if s["id"] == restricted)
    assert "restricted" not in row  # источник открыт читателю РФ
    status, text = chapter_text(client, restricted, "RU")
    assert status == 200 and "ЗЕТА-9" in text


@req(RA, "Библиотека закрывает текст ограниченных источников")
def test_other_country_gets_restricted_row_and_no_chapter(bot):
    """Читатель вне РФ видит строку «доступен в РФ», но не главу."""
    restricted = add_restricted(bot)
    bot.rig.publish("restricted")
    client = gateway(bot)

    de = client.get("/api/v1/sources", headers={"CF-IPCountry": "DE"})
    row = next(s for s in de.json()["sources"] if s["id"] == restricted)
    assert row["restricted"] is True and row["regions"] == ["RU"]
    status, text = chapter_text(client, restricted, "DE")
    assert status == 404 and "ЗЕТА-9" not in text


@req(RA, "Ассистент не использует закрытые источники")
def test_assistant_search_uses_gateway_region(bot):
    """Поиск внутри ассистента видит закрытый источник только читателю РФ."""
    add_restricted(bot)
    bot.rig.publish("restricted")

    for country, expected in (("RU", True), ("DE", False)):
        bot.model.routes.append({"type": "knowledge", "confidence": 0.9, "names": []})
        bot.model.answers.append(["Ответ по источникам [1]. "])
        items = ask(gateway(bot), country)
        # Регион дошёл до шлюза → ассистента → поиска: в блоке passages (то, что видит модель)
        # есть текст закрытого источника только у читателя из РФ; вопрос тот же и в него не входит.
        prompt_text = bot.model.requests[-1].messages[-1].content
        passages = re.search(r'<data name="passages">\n(.*?)\n</data>', prompt_text, re.S)
        assert ("ЗЕТА-9" in (passages.group(1) if passages else "")) is expected
        cited = {
            citation["source_id"]
            for item in items
            if item["type"] == "fragment"
            for citation in item["citations"]
        }
        assert cited  # ответ опирается на найденное, а не на закрытый источник напрямую


@req(RA, "Неизвестный регион закрывает ограниченные источники")
def test_client_header_does_not_substitute_cdn_country(bot):
    """Клиентский X-Philograph-Region без страны от CDN не открывает источник."""
    restricted = add_restricted(bot)
    bot.rig.publish("restricted")
    client = gateway(bot)

    spoofed = client.get("/api/v1/sources", headers={REGION_HEADER: "RU"}).json()["sources"]
    row = next(s for s in spoofed if s["id"] == restricted)
    assert row["restricted"] is True


@req(RA, "Неизвестный регион закрывает ограниченные источники")
def test_untrusted_proxy_and_fallback(bot):
    """Недоверенный прокси не даёт регион; запасной регион стенда подставляет RU."""
    restricted = add_restricted(bot)
    bot.rig.publish("restricted")

    untrusted = gateway(bot, trusted=False)
    row = next(
        s
        for s in untrusted.get("/api/v1/sources", headers={"CF-IPCountry": "RU"}).json()["sources"]
        if s["id"] == restricted
    )
    assert row["restricted"] is True

    local = gateway(bot, fallback="RU")
    row = next(s for s in local.get("/api/v1/sources").json()["sources"] if s["id"] == restricted)
    assert "restricted" not in row
