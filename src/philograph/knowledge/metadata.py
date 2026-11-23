"""Метаданные охраняемых произведений: сущности и связи без полного текста.

Событие ``source.metadata_registered`` несёт title, authors, year, abstract, toc, citations.
Из него строятся производные факты онтологии: персоны (авторы), произведения и связи
«кто на кого ссылается». Полный текст нигде не хранится.
"""

from __future__ import annotations

from typing import Any

from philograph.platform import events

events.define(
    "knowledge.metadata.ingested",
    "info",
    "Из метаданных источника созданы производные факты",
    required=("source_id", "statements"),
)


class MetadataIngest:
    def __init__(self, statements: Any) -> None:
        self.statements = statements
        self.entities = statements.entities

    def _person(self, name: str) -> str:
        found = self.entities.find(name)
        if found:
            return found[0]["id"]
        return self.entities.create("person", [("en", name, "primary"), ("ru", name, "variant")])

    def _work(self, title: str) -> str:
        found = self.entities.find(title)
        if found:
            return found[0]["id"]
        return self.entities.create("work", [("en", title, "primary")])

    def handle(self, payload: dict[str, Any]) -> dict[str, int]:
        """Создаёт произведение, персон-авторов и связи цитирования; повторный вызов безопасен."""
        source_id = payload["source_id"]
        work = self._work(payload["title"])
        created = 0
        for name in payload.get("authors", []):
            person = self._person(name)
            self.statements.add(work, "author", obj=person)
            created += 1
        for cited in payload.get("citations", []):
            cited_work = self._work(cited)
            self.statements.add(work, "cites", obj=cited_work)
            created += 1
        events.emit("knowledge.metadata.ingested", source_id=source_id, statements=created)
        return {"statements": created}
