"""Чтение: что видит читатель. Только опубликованные версии, только видимые источники.

Глава — единица чтения: раздел верхнего уровня (внутри тома — раздел под томом) со всеми
вложенными подразделами. Переход к подразделу открывает его главу с прокруткой к нему.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine, and_, select

from philograph.library import schema as t
from philograph.library.lang import normalize_word, words
from philograph.library.model import Document, Section
from philograph.library.registry import PUBLIC, Registry
from philograph.library.schema import defaults
from philograph.platform import events

KINDS = ("textbook", "primary", "reference")

events.define(
    "library.sources.listed",
    "info",
    "Отдан список источников",
    required=("count",),
    optional=("kinds", "languages", "query_length"),
)
events.define(
    "library.chapter.served", "info", "Отдана глава", required=("source_id", "chapter_id", "blocks")
)
events.define(
    "library.paragraph.resolved",
    "info",
    "Разрешена ссылка на абзац",
    required=("paragraph_id", "status"),
)
events.define(
    "library.default.changed", "info", "Назначен учебник по умолчанию", required=("source_id",)
)


class NotVisible(Exception):
    """Источник не опубликован или не виден читателю."""


def _norm(text: str) -> str:
    return " ".join(normalize_word(w) for w in words(text))


@dataclass
class Reader:
    """Кто читает: в первой версии только общая видимость; позже — пользователь и группы."""

    scopes: frozenset[str] = frozenset({PUBLIC})


ANONYMOUS = Reader()


class Reading:
    def __init__(self, registry: Registry, engine: Engine) -> None:
        self.registry = registry
        self.engine = engine

    # --- список источников ---

    def _visible_rows(self, reader: Reader) -> list[dict[str, Any]]:
        with self.engine.begin() as conn:
            rows = (
                conn.execute(
                    select(t.sources).where(
                        and_(
                            t.sources.c.status == "active",
                            t.sources.c.published_version.is_not(None),
                        )
                    )
                )
                .mappings()
                .all()
            )
        visible = []
        for row in rows:
            if row["scope"] not in reader.scopes:
                continue
            if row["license"].get("blocked") or not self.registry.permissions(row["id"])["display"]:
                continue
            visible.append(dict(row))
        return visible

    def _describe(self, row: dict[str, Any]) -> dict[str, Any]:
        kind = self.registry.license_kind(row["license"]["kind"]) or {}
        return {
            "id": row["id"],
            "title": row["title"],
            "authors": row["authors"],
            "year": row["year"],
            "language": row["language"],
            "kind": row["kind"],
            "license": {"title": kind.get("title"), "url": kind.get("url")},
            "translator": row["translator"],
            "edition": row["edition"],
        }

    def sources(
        self,
        reader: Reader = ANONYMOUS,
        *,
        kinds: list[str] | None = None,
        languages: list[str] | None = None,
        query: str = "",
    ) -> dict[str, Any]:
        """Видимые источники с фильтрами и поиском; языки — только те, что есть в библиотеке."""
        rows = self._visible_rows(reader)
        available = sorted({r["language"] for r in rows})
        needle = _norm(query)
        found = []
        for row in rows:
            if kinds and row["kind"] not in kinds:
                continue
            if languages and row["language"] not in languages:
                continue
            if needle:
                hay = _norm(row["title"] + " " + " ".join(row["authors"]))
                if needle not in hay:
                    continue
            found.append(self._describe(row))
        found.sort(key=lambda s: s["title"])
        events.emit(
            "library.sources.listed",
            count=len(found),
            kinds=kinds or [],
            languages=languages or [],
            query_length=len(query),
        )
        return {
            "sources": found,
            "languages": available,
            "default_source_id": self.default_source(reader),
        }

    # --- учебник по умолчанию ---

    def set_default(self, actor: str, source_id: str) -> None:
        source = self.registry.get(source_id)
        if source.kind != "textbook" or not source.published_version:
            raise ValueError("по умолчанию можно назначить только опубликованный учебник")
        with self.engine.begin() as conn:
            conn.execute(defaults.delete())
            conn.execute(defaults.insert().values(key="default_source", value=source_id))
            self.registry.actions.record(actor, "set_default_source", source_id, conn=conn)
        events.emit("library.default.changed", source_id=source_id)

    def default_source(self, reader: Reader = ANONYMOUS) -> str | None:
        with self.engine.begin() as conn:
            value = conn.scalar(select(defaults.c.value).where(defaults.c.key == "default_source"))
        visible = {r["id"] for r in self._visible_rows(reader)}
        return value if value in visible else None

    def resolve_current(self, remembered: str | None, reader: Reader = ANONYMOUS) -> dict[str, Any]:
        """Какой источник открыть: запомненный, если он ещё виден, иначе учебник по умолчанию."""
        visible = {r["id"] for r in self._visible_rows(reader)}
        if remembered and remembered in visible:
            return {"source_id": remembered, "notice": None}
        notice = "previous_unavailable" if remembered else None
        return {"source_id": self.default_source(reader), "notice": notice}

    # --- оглавление и главы ---

    def _document(self, source_id: str, reader: Reader) -> tuple[str, Document]:
        visible = {r["id"]: r for r in self._visible_rows(reader)}
        if source_id not in visible:
            raise NotVisible(source_id)
        version_id = visible[source_id]["published_version"]
        return version_id, self.registry.load_document(version_id)

    @staticmethod
    def chapters(doc: Document) -> list[Section]:
        result: list[Section] = []
        for section in doc.sections:
            if not section.visible:
                continue
            if section.level == 0 and section.children:
                result.extend(c for c in section.children if c.visible)
                if section.blocks:
                    result.insert(len(result) - len(section.children), section)
            else:
                result.append(section)
        return result

    def toc(self, source_id: str, reader: Reader = ANONYMOUS) -> list[dict[str, Any]]:
        _, doc = self._document(source_id, reader)
        chapter_ids = {c.id for c in self.chapters(doc)}

        def item(section: Section, chapter: str | None) -> dict[str, Any]:
            own_chapter = section.id if section.id in chapter_ids else chapter
            return {
                "id": section.id,
                "title": section.title or "Начало",
                "level": section.level,
                "chapter_id": own_chapter,
                "children": [item(c, own_chapter) for c in section.children if c.visible],
            }

        return [item(s, None) for s in doc.sections if s.visible]

    def chapter(
        self, source_id: str, chapter_id: str, reader: Reader = ANONYMOUS
    ) -> dict[str, Any]:
        _, doc = self._document(source_id, reader)
        chapters = self.chapters(doc)
        index = next((i for i, c in enumerate(chapters) if c.id == chapter_id), None)
        if index is None:
            raise KeyError(chapter_id)
        chapter = chapters[index]
        blocks: list[dict[str, Any]] = []
        footnotes: dict[str, dict[str, Any]] = {}

        def walk(section: Section, depth: int) -> None:
            if not section.visible:
                return
            if depth > 0:
                blocks.append(
                    {
                        "type": "heading",
                        "section_id": section.id,
                        "text": section.title,
                        "level": section.level,
                    }
                )
            for block in section.blocks:
                blocks.append(
                    {
                        "type": "block",
                        "id": block.id,
                        "kind": block.kind,
                        "text": block.text,
                        "lang": block.lang,
                        "pages": [[m.offset, m.label] for m in block.pages if m.label is not None],
                        "notes": [[r.offset, r.footnote_id] for r in block.notes],
                        "detail": block.detail,
                    }
                )
            for note in section.footnotes:
                footnotes[note.id] = {
                    "marker": note.marker,
                    "text": note.text,
                    "linked": note.linked,
                }
            for child in section.children:
                walk(child, depth + 1)

        walk(chapter, 0)
        events.emit(
            "library.chapter.served",
            source_id=source_id,
            chapter_id=chapter_id,
            blocks=sum(1 for b in blocks if b["type"] == "block"),
        )
        return {
            "source_id": source_id,
            "chapter_id": chapter_id,
            "title": chapter.title or "Начало",
            "blocks": blocks,
            "footnotes": footnotes,
            "unlinked_notes": [n for n in footnotes.values() if not n["linked"]],
            "previous": chapters[index - 1].id if index > 0 else None,
            "next": chapters[index + 1].id if index + 1 < len(chapters) else None,
            "first": chapters[0].id,
        }

    def chapter_of(self, doc: Document, section_id: str) -> str | None:
        for chapter in self.chapters(doc):
            if any(s.id == section_id for s in chapter.walk()):
                return chapter.id
        return None

    def resolve_paragraph(self, paragraph_id: str, reader: Reader = ANONYMOUS) -> dict[str, Any]:
        resolved = self.registry.resolve_paragraph(paragraph_id)
        status = resolved["status"]
        if status in ("found", "removed"):
            try:
                _, doc = self._document(resolved["source_id"], reader)
            except NotVisible:
                status = "source_unavailable"
            else:
                section = resolved.get("section_id")
                chapter = self.chapter_of(doc, section) if section else None
                if status == "removed" and chapter is None:
                    # Раздел пропал вместе с абзацем: ищем главу с тем же названием.
                    title = resolved.get("section_title")
                    match = next(
                        (
                            c
                            for c in self.chapters(doc)
                            if title and any(s.title == title for s in c.walk())
                        ),
                        None,
                    )
                    chapter = match.id if match else None
                resolved = {**resolved, "chapter_id": chapter}
        result = {**resolved, "status": status}
        if status == "source_unavailable":
            result = {"status": status}
        events.emit("library.paragraph.resolved", paragraph_id=paragraph_id, status=status)
        return result


class Internal:
    """Интерфейс библиотеки для других сервисов: абзацы версии и разрешения источника.

    Поиск и онтология получают текст только так, а не из таблиц библиотеки.
    """

    def __init__(self, registry: Registry, reading: Reading) -> None:
        self.registry = registry
        self.reading = reading

    def version_paragraphs(self, version_id: str) -> dict[str, Any]:
        version = self.registry.version(version_id)
        source = self.registry.get(version["source_id"])
        doc = self.registry.load_document(version_id)
        chapter_of = {}
        for chapter in self.reading.chapters(doc):
            for section in chapter.walk():
                chapter_of[section.id] = chapter.id
        paragraphs = []
        order = 0
        for section in doc.walk():
            for block in section.blocks:
                order += 1
                paragraphs.append(
                    {
                        "id": block.id,
                        "text": block.text,
                        "lang": block.lang,
                        "ord": order,
                        "section_id": section.id,
                        "section_title": section.title,
                        "chapter_id": chapter_of.get(section.id),
                        "searchable": section.searchable and block.kind != "unrendered",
                    }
                )
        return {
            "source_id": source.id,
            "version_id": version_id,
            "scope": source.scope,
            "published": source.published_version == version_id and source.status == "active",
            "permissions": self.registry.permissions(source.id),
            "paragraphs": paragraphs,
        }

    def paragraph_text(self, paragraph_id: str) -> dict[str, Any] | None:
        """Текст абзаца опубликованной версии: онтология сверяет с ним цитаты."""
        resolved = self.registry.resolve_paragraph(paragraph_id)
        if resolved["status"] != "found":
            return None
        version = self.registry.get(resolved["source_id"]).published_version
        for _, block in self.registry.load_document(version).blocks():
            if block.id == resolved["paragraph_id"]:
                return {
                    "paragraph_id": block.id,
                    "source_id": resolved["source_id"],
                    "text": block.text,
                }
        return None

    def published(self) -> list[dict[str, str]]:
        return [
            {"source_id": r["id"], "version_id": r["published_version"]}
            for r in self.reading._visible_rows(Reader(frozenset({PUBLIC})))
        ]
