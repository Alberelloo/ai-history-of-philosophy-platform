"""chapter-reading «Запоминание места чтения»: устаревшая глава или раздел не выбрасывают из книги.

Сервер отдаёт главу по идентификатору раздела внутри неё (с местом для прокрутки), а на
неизвестную главу отвечает 404 с первой главой книги. Абзац с тем же текстом после повторной
обработки находится в новой главе — по нему клиент возвращает читателя на место.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from philograph.library.app import build_app
from philograph.library.reading import Reading

from .builders import epub

req = pytest.mark.req
CR = "chapter-reading"


def book(second_title: str) -> bytes:
    return epub(
        [
            ("Глава 1. Опыт", "<p>Всякое знание начинается с опыта, говорит Кант.</p>"),
            (
                second_title,
                "<p>Рассудок даёт правила явлениям.</p><h2>Схематизм</h2>"
                "<p>Схема связывает категории и созерцания.</p>",
            ),
        ]
    )


@pytest.fixture
def reading(lib):
    lib.files["book.epub"] = book("Глава 2. Рассудок")
    source_id = lib.register(files=[{"name": "book", "path": "book.epub"}])
    lib.publish_new(source_id)
    reading = Reading(lib.registry, lib.registry.engine)
    client = TestClient(build_app(reading))
    return lib, reading, client, source_id


def toc_ids(client, source_id) -> dict[str, dict]:
    def walk(items):
        for item in items:
            yield item
            yield from walk(item["children"])

    toc = client.get(f"/api/v1/sources/{source_id}/toc").json()
    return {item["title"]: item for item in walk(toc)}


@req(CR, "Запоминание места чтения")
def test_section_id_opens_its_chapter_with_anchor(reading):
    _, _, client, source_id = reading
    items = toc_ids(client, source_id)
    section = items["Схематизм"]
    assert section["chapter_id"] != section["id"]  # раздел внутри главы, не глава
    response = client.get(f"/api/v1/sources/{source_id}/chapters/{section['id']}")
    assert response.status_code == 200
    body = response.json()
    assert body["chapter_id"] == section["chapter_id"]
    assert body["title"] == "Глава 2. Рассудок"
    assert body["anchor"] == section["id"]
    chapter = client.get(f"/api/v1/sources/{source_id}/chapters/{section['chapter_id']}").json()
    assert chapter["anchor"] is None


@req(CR, "Запоминание места чтения")
def test_renamed_chapter_answers_with_first_chapter_and_paragraph_survives(reading):
    lib, reading_, client, source_id = reading
    before = toc_ids(client, source_id)
    old_chapter = before["Глава 2. Рассудок"]["id"]
    first = before["Глава 1. Опыт"]["id"]
    saved = client.get(f"/api/v1/sources/{source_id}/chapters/{old_chapter}").json()
    paragraph = next(b["id"] for b in saved["blocks"] if b["type"] == "block")

    # Повторная обработка: глава переименована, её прежнего идентификатора больше нет.
    lib.files["book.epub"] = book("Глава 2. Рассудок и его правила")
    lib.registry.update_settings("operator", source_id, note="v2")
    lib.publish_new(source_id)
    after = toc_ids(client, source_id)
    assert old_chapter not in {item["id"] for item in after.values()}

    response = client.get(f"/api/v1/sources/{source_id}/chapters/{old_chapter}")
    assert response.status_code == 404
    body = response.json()
    assert body["kind"] == "chapter_not_found"
    assert body["first_chapter_id"] == after["Глава 1. Опыт"]["id"] == first

    # Абзац с тем же текстом ведёт в новую главу: туда клиент и вернёт читателя.
    resolved = client.get(f"/api/v1/paragraphs/{paragraph}").json()
    assert resolved["status"] == "found"
    assert resolved["chapter_id"] == after["Глава 2. Рассудок и его правила"]["id"]
    assert reading_.resolve_paragraph(paragraph)["paragraph_id"] == resolved["paragraph_id"]
