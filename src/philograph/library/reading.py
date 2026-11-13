"""Чтение: что видит читатель. Только опубликованные версии, только видимые источники.

Глава — единица чтения: раздел верхнего уровня (внутри тома — раздел под томом) со всеми
вложенными подразделами. Переход к подразделу открывает его главу с прокруткой к нему.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from sqlalchemy import Engine, and_, select

from philograph.library import schema as t
from philograph.library.lang import normalize_word, words
from philograph.library.model import Document, Section
from philograph.library.registry import (
    PUBLIC,
    Registry,
    effective_permissions,
    effective_regions,
)
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


class ChapterNotFound(KeyError):
    """Такой главы или раздела нет в опубликованной версии; ``first`` — первая глава."""

    def __init__(self, chapter_id: str, first: str | None) -> None:
        super().__init__(chapter_id)
        self.first = first


def _norm(text: str) -> str:
    return " ".join(normalize_word(w) for w in words(text))


def parse_region(value: str | None) -> str | None:
    """Код региона из заголовка: две латинские буквы в верхнем регистре.

    Всё прочее (пусто, ``XX``, ``T1``, кириллица) — неизвестный регион: источники с
    ограничением регионов такому читателю закрыты. ``XX`` — служебное «страна не определена»
    у CDN, поэтому он не считается кодом страны.
    """
    if not value:
        return None
    code = value.strip().upper()
    if code in {"XX", "T1"}:
        return None
    if len(code) == 2 and code.isascii() and code.isalpha():
        return code
    return None


@dataclass
class Reader:
    """Кто читает: в первой версии общая видимость и регион; позже — пользователь и группы."""

    scopes: frozenset[str] = frozenset({PUBLIC})
    region: str | None = None
    # Служебный регион для внутренних интерфейсов индексации: видит ограниченные источники.
    # Клиенту такое значение не приходит.
    ALL_REGIONS: ClassVar[str] = "*"


ANONYMOUS = Reader()


class Reading:
    def __init__(self, registry: Registry, engine: Engine) -> None:
        self.registry = registry
        self.engine = engine

    # --- список источников ---

    def _rows(self, reader: Reader) -> list[dict[str, Any]]:
        """Опубликованные источники общей видимости, которые лицензия разрешает показывать.

        Регионы здесь не отсекаются: закрытый по региону источник остаётся в списке строкой
        «доступен в РФ», поэтому решение об открытости принимается отдельно (``_open``).
        """
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
        kinds = self.registry.license_kinds()
        result = []
        for row in rows:
            if row["scope"] not in reader.scopes:
                continue
            license_json = row["license"] or {}
            if license_json.get("blocked"):
                continue
            kind = kinds.get(license_json.get("kind")) or {"permissions": {}}
            regions = effective_regions(kind.get("regions"), row["regions"])
            permissions = effective_permissions(
                kind["permissions"], license_json.get("narrowed") or {}, regions
            )
            if not permissions["display"]:
                continue
            result.append({**dict(row), "effective_regions": regions})
        return result

    @staticmethod
    def _open(row: dict[str, Any], reader: Reader) -> bool:
        regions = row["effective_regions"]
        if regions is None or reader.region == Reader.ALL_REGIONS:
            return True
        return reader.region in regions

    def _visible_rows(self, reader: Reader) -> list[dict[str, Any]]:
        return [row for row in self._rows(reader) if self._open(row, reader)]

    def _restricted_rows(self, reader: Reader) -> list[dict[str, Any]]:
        return [row for row in self._rows(reader) if not self._open(row, reader)]

    def closed_source_ids(self, region: str | None) -> list[str]:
        """Идентификаторы опубликованных источников, закрытых для региона (для индексации)."""
        return [row["id"] for row in self._restricted_rows(Reader(frozenset({PUBLIC}), region))]

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

    @staticmethod
    def _restricted(row: dict[str, Any]) -> dict[str, Any]:
        """Строка источника, закрытого для региона: название, авторы и пометка, больше ничего."""
        regions = row["effective_regions"]
        return {
            "id": row["id"],
            "title": row["title"],
            "authors": row["authors"],
            "restricted": True,
            "regions": sorted(regions or []),
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
        rows = self._rows(reader)
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
            found.append(self._describe(row) if self._open(row, reader) else self._restricted(row))
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
        visible = [s for s in doc.sections if s.visible]

        def size(section: Section) -> int:
            return len(section.blocks) + sum(size(c) for c in section.children)

        # Весь текст под одним заголовком (название книги): главы — разделы под ним.
        wrappers = [s for s in visible if s.children]
        total = sum(size(s) for s in visible) or 1
        wrapper = wrappers[0] if len(wrappers) == 1 and size(wrappers[0]) >= 0.8 * total else None
        for section in visible:
            if (section.level == 0 or section is wrapper) and section.children:
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
        anchor = None
        if index is None:
            # Раздел внутри главы: отдаём его главу и место, куда прокрутить.
            owner = self.chapter_of(doc, chapter_id)
            if owner is None:
                raise ChapterNotFound(chapter_id, chapters[0].id if chapters else None)
            index = next(i for i, c in enumerate(chapters) if c.id == owner)
            anchor = chapter_id
        chapter = chapters[index]
        chapter_id = chapter.id
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
                        "detail_code": block.detail_code,
                        "page": block.page,
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
            "anchor": anchor,
        }

    def chapter_of(self, doc: Document, section_id: str) -> str | None:
        for chapter in self.chapters(doc):
            if any(s.id == section_id for s in chapter.walk()):
                return chapter.id
        return None

    def resolve_paragraph(self, paragraph_id: str, reader: Reader = ANONYMOUS) -> dict[str, Any]:
        resolved = self.registry.resolve_paragraph(paragraph_id)
        status = resolved["status"]
        closed_by_region = False
        if status in ("found", "removed"):
            try:
                _, doc = self._document(resolved["source_id"], reader)
            except NotVisible:
                status = "source_unavailable"
                closed_by_region = any(
                    row["id"] == resolved["source_id"] for row in self._restricted_rows(reader)
                )
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
            if closed_by_region:
                # Источник закрыт регионом: называем его как в списке, без текста и главы.
                source = self.registry.get(resolved["source_id"])
                result = {
                    "status": status,
                    "reason": "region",
                    "source": {"id": source.id, "title": source.title, "authors": source.authors},
                }
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
        chapter_titles = {}
        for chapter in self.reading.chapters(doc):
            chapter_titles[chapter.id] = chapter.title
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
        # Упоминания ищутся и в заголовках, и в сносках, не только в абзацах.
        headings = [
            {"id": s.id, "text": s.title, "chapter_id": chapter_of.get(s.id)}
            for s in doc.walk()
            if s.title and s.visible
        ]
        footnotes = [
            {"id": n.id, "text": n.text, "chapter_id": chapter_of.get(sec.id)}
            for sec, n in doc.footnotes()
        ]
        permissions = self.registry.permissions(source.id)
        regions = self.registry.regions(source.id)
        return {
            "source_id": source.id,
            "source_title": source.title,
            "chapters": chapter_titles,
            "version_id": version_id,
            "scope": source.scope,
            "published": source.published_version == version_id and source.status == "active",
            "permissions": permissions,
            "external_processing": permissions["external_processing"],
            "regions": sorted(regions) if regions is not None else None,
            "paragraphs": paragraphs,
            "headings": headings,
            "footnotes": footnotes,
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
        """Все опубликованные источники, включая закрытые по региону: индексация без фильтра."""
        return [
            {"source_id": r["id"], "version_id": r["published_version"]}
            for r in self.reading._visible_rows(Reader(frozenset({PUBLIC}), Reader.ALL_REGIONS))
        ]

    def access(self, region: str | None) -> dict[str, Any]:
        """Идентификаторы источников, закрытых для региона: их скрывает сервис знаний."""
        code = parse_region(region)
        return {"region": code, "closed": self.reading.closed_source_ids(code)}
