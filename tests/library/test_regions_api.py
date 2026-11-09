"""HTTP-слой библиотеки и служебные интерфейсы: регион читателя из заголовка шлюза."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from philograph.library.app import REGION_HEADER, build_app
from philograph.library.reading import Reading
from philograph.library.registry import License

req = pytest.mark.req
RA = "regional-access"
CR = "chapter-reading"
RU_KIND = "public-domain-ru"


def ru_license() -> License:
    return License(RU_KIND, "public_domain", author_death_years=[1804])


@pytest.fixture
def api(lib):
    lib.registry.add_license_kind(
        RU_KIND,
        "Общественное достояние по праву РФ",
        None,
        {"display": True, "external_processing": True, "quoting": True},
        regions=["RU"],
    )
    open_id = lib.register(title="Открытая книга")
    restricted_id = lib.register(title="Русская книга", license=ru_license())
    lib.publish_new(open_id)
    version_id = lib.publish_new(restricted_id)
    reading = Reading(lib.registry, lib.registry.engine)
    client = TestClient(build_app(reading))
    paragraph = next(b.id for _, b in lib.registry.load_document(version_id).blocks())
    return lib, client, open_id, restricted_id, paragraph


def rows(client, headers=None) -> dict[str, dict]:
    response = client.get("/api/v1/sources", headers=headers or {})
    assert response.status_code == 200
    return {s["id"]: s for s in response.json()["sources"]}


@req(RA, "Библиотека закрывает текст ограниченных источников")
def test_sources_list_by_region(api):
    _, client, open_id, restricted_id, _ = api
    opened = rows(client, {REGION_HEADER: "RU"})
    assert "restricted" not in opened[open_id]
    assert "restricted" not in opened[restricted_id]

    closed = rows(client, {REGION_HEADER: "DE"})
    assert closed[restricted_id] == {
        "id": restricted_id,
        "title": "Русская книга",
        "authors": ["И. Кант"],
        "restricted": True,
        "regions": ["RU"],
    }
    assert "restricted" not in closed[open_id]

    unknown = rows(client)  # заголовка нет — регион неизвестен
    assert unknown[restricted_id]["restricted"] is True


@req(RA, "Библиотека закрывает текст ограниченных источников")
def test_toc_and_chapter_closed_for_other_region(api):
    _, client, _, restricted_id, _ = api
    toc = client.get(f"/api/v1/sources/{restricted_id}/toc", headers={REGION_HEADER: "DE"})
    assert toc.status_code == 404
    assert toc.json()["kind"] == "source_unavailable"

    allowed = client.get(f"/api/v1/sources/{restricted_id}/toc", headers={REGION_HEADER: "RU"})
    assert allowed.status_code == 200 and allowed.json()
    chapter_id = allowed.json()[0]["id"]
    chapter = client.get(
        f"/api/v1/sources/{restricted_id}/chapters/{chapter_id}", headers={REGION_HEADER: "DE"}
    )
    assert chapter.status_code == 404 and chapter.json()["kind"] == "source_unavailable"


@req(CR, "Устойчивость ссылок на абзацы")
def test_paragraph_from_other_region(api):
    _, client, _, restricted_id, paragraph = api
    closed = client.get(f"/api/v1/paragraphs/{paragraph}", headers={REGION_HEADER: "DE"}).json()
    assert closed == {
        "status": "source_unavailable",
        "reason": "region",
        "source": {"id": restricted_id, "title": "Русская книга", "authors": ["И. Кант"]},
    }

    allowed = client.get(f"/api/v1/paragraphs/{paragraph}", headers={REGION_HEADER: "RU"}).json()
    assert allowed["status"] == "found"
    assert allowed["source_id"] == restricted_id


@req(RA, "Внутренние интерфейсы не фильтруют по региону")
def test_internal_published_keeps_restricted(api):
    _, client, open_id, restricted_id, _ = api
    published = {row["source_id"] for row in client.get("/api/v1/internal/published").json()}
    assert {open_id, restricted_id} <= published


@req(RA, "Внутренние интерфейсы не фильтруют по региону")
def test_internal_access_lists_closed(api):
    _, client, _, restricted_id, _ = api
    closed = client.get("/api/v1/internal/access?region=DE").json()
    assert closed == {"region": "DE", "closed": [restricted_id]}
    assert client.get("/api/v1/internal/access?region=RU").json()["closed"] == []
    # прочее значение региона — неизвестный регион
    assert client.get("/api/v1/internal/access?region=T1").json()["closed"] == [restricted_id]
    assert client.get("/api/v1/internal/access").json()["closed"] == [restricted_id]


@req(RA, "Внешняя обработка закрытых источников")
def test_version_payload_has_access_fields(api):
    lib, client, _, restricted_id, _ = api
    version_id = lib.registry.get(restricted_id).published_version
    body = client.get(f"/api/v1/internal/versions/{version_id}/paragraphs").json()
    assert body["regions"] == ["RU"]
    assert body["external_processing"] is True
    assert body["permissions"]["display"] is True
