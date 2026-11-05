"""Сущности онтологии: идентичность, названия, внешние идентификаторы, слияние дублей.

Всё, кроме идентичности, — утверждения. У сущности хранится только копия основных значений
(годы жизни, датировка, описание) для сортировки и быстрого показа.
"""

from __future__ import annotations

import re
import uuid
from itertools import combinations
from typing import Any

from sqlalchemy import Engine, and_, select, update

from philograph.knowledge import schema as t
from philograph.knowledge.registry import OntologyRegistry
from philograph.platform import events

events.define(
    "knowledge.entity.created", "info", "Создана сущность онтологии", required=("entity_id", "type")
)
events.define(
    "knowledge.entity.merged",
    "info",
    "Сущности слиты с перенаправлением",
    required=("kept", "removed"),
)
events.define(
    "knowledge.entity.merge_undone",
    "info",
    "Слияние сущностей отменено",
    required=("kept", "removed"),
)


class DuplicateEntity(Exception):
    def __init__(self, existing: str) -> None:
        super().__init__(f"уже есть сущность {existing} с тем же внешним идентификатором")
        self.existing = existing


def normalize(name: str) -> str:
    name = name.lower().replace("ё", "е")
    name = re.sub(r"[^\w\s]", " ", name)
    return re.sub(r"\s+", " ", name).strip()


class Entities:
    def __init__(self, engine: Engine, registry: OntologyRegistry) -> None:
        self.engine = engine
        self.registry = registry

    def create(
        self,
        type_: str,
        names: list[tuple[str, str, str]],
        *,
        external: dict[str, str] | None = None,
        entity_id: str | None = None,
    ) -> str:
        """``names``: (язык, текст, вид: primary | variant | original)."""
        self.registry.entity_type(type_)
        for system, value in (external or {}).items():
            with self.engine.begin() as conn:
                existing = conn.scalar(
                    select(t.external_ids.c.entity_id).where(
                        and_(t.external_ids.c.system == system, t.external_ids.c.value == value)
                    )
                )
            if existing:
                raise DuplicateEntity(self.resolve(existing))
        entity_id = entity_id or f"e_{uuid.uuid4().hex[:12]}"
        with self.engine.begin() as conn:
            conn.execute(
                t.entities.insert().values(id=entity_id, type=type_, primary={}, redirect_to=None)
            )
            conn.execute(
                t.names.insert(),
                [
                    {
                        "entity_id": entity_id,
                        "lang": lang,
                        "text": text,
                        "normalized": normalize(text),
                        "kind": kind,
                    }
                    for lang, text, kind in names
                ],
            )
            for system, value in (external or {}).items():
                conn.execute(
                    t.external_ids.insert().values(entity_id=entity_id, system=system, value=value)
                )
        events.emit("knowledge.entity.created", entity_id=entity_id, type=type_)
        return entity_id

    def resolve(self, entity_id: str) -> str:
        """Идентификатор слитой сущности ведёт на оставшуюся."""
        seen = set()
        with self.engine.begin() as conn:
            while entity_id not in seen:
                seen.add(entity_id)
                target = conn.scalar(
                    select(t.entities.c.redirect_to).where(t.entities.c.id == entity_id)
                )
                if not target:
                    return entity_id
                entity_id = target
        return entity_id

    def get(self, entity_id: str) -> dict[str, Any]:
        entity_id = self.resolve(entity_id)
        with self.engine.begin() as conn:
            row = (
                conn.execute(select(t.entities).where(t.entities.c.id == entity_id))
                .mappings()
                .one()
            )
            names_rows = (
                conn.execute(select(t.names).where(t.names.c.entity_id == entity_id))
                .mappings()
                .all()
            )
        return {
            "id": row["id"],
            "type": row["type"],
            "primary": dict(row["primary"]),
            "names": [
                {"lang": n["lang"], "text": n["text"], "kind": n["kind"]} for n in names_rows
            ],
        }

    def label(self, entity_id: str, lang: str = "ru") -> str:
        names = self.get(entity_id)["names"]
        for n in names:
            if n["kind"] == "primary" and n["lang"] == lang:
                return n["text"]
        return names[0]["text"] if names else entity_id

    def set_primary(self, entity_id: str, key: str, value: Any) -> None:
        entity = self.get(entity_id)
        with self.engine.begin() as conn:
            conn.execute(
                update(t.entities)
                .where(t.entities.c.id == entity["id"])
                .values(primary={**entity["primary"], key: value})
            )

    def add_name(self, entity_id: str, lang: str, text: str, kind: str = "variant") -> None:
        with self.engine.begin() as conn:
            conn.execute(
                t.names.insert().values(
                    entity_id=self.resolve(entity_id),
                    lang=lang,
                    text=text,
                    normalized=normalize(text),
                    kind=kind,
                )
            )

    def find(self, name: str) -> list[dict[str, Any]]:
        """Все сущности с таким названием или вариантом: выбор не делается молча."""
        with self.engine.begin() as conn:
            ids = list(
                dict.fromkeys(
                    conn.scalars(
                        select(t.names.c.entity_id).where(t.names.c.normalized == normalize(name))
                    )
                )
            )
        candidates = []
        for entity_id in ids:
            entity = self.get(entity_id)
            if entity["id"] == entity_id:
                candidates.append(entity)
        return candidates

    def by_external(self, system: str, value: str) -> str | None:
        with self.engine.begin() as conn:
            found = conn.scalar(
                select(t.external_ids.c.entity_id).where(
                    and_(t.external_ids.c.system == system, t.external_ids.c.value == value)
                )
            )
        return self.resolve(found) if found else None

    def source_entity(self, source_id: str, title: str) -> str:
        """Источник библиотеки как сущность: на него ссылаются атрибуции и связь «издание»."""
        existing = self.by_external("library", source_id)
        return existing or self.create(
            "source", [("ru", title, "primary")], external={"library": source_id}
        )

    # --- дубли ---

    def duplicate_candidates(self) -> list[tuple[str, str]]:
        """Кандидаты: одинаковый тип, совпадает последнее слово названия и основные даты."""
        with self.engine.begin() as conn:
            rows = (
                conn.execute(select(t.entities).where(t.entities.c.redirect_to.is_(None)))
                .mappings()
                .all()
            )
            all_names = conn.execute(select(t.names)).mappings().all()
        names_of: dict[str, set[str]] = {}
        for n in all_names:
            names_of.setdefault(n["entity_id"], set()).add(
                n["normalized"].split()[-1] if n["normalized"] else ""
            )
        pairs = []
        for a, b in combinations(rows, 2):
            if a["type"] != b["type"]:
                continue
            same_name = names_of.get(a["id"], set()) & names_of.get(b["id"], set())
            dates_a, dates_b = a["primary"].get("dates"), b["primary"].get("dates")
            if same_name and (dates_a == dates_b):
                pairs.append((a["id"], b["id"]))
        return pairs

    def merge(self, kept: str, removed: str) -> int:
        """Переносит названия и утверждения, старый идентификатор становится перенаправлением."""
        kept, removed = self.resolve(kept), self.resolve(removed)
        with self.engine.begin() as conn:
            moved_names = list(
                conn.scalars(select(t.names.c.id).where(t.names.c.entity_id == removed))
            )
            moved_subject = list(
                conn.scalars(select(t.statements.c.id).where(t.statements.c.subject == removed))
            )
            moved_object = list(
                conn.scalars(select(t.statements.c.id).where(t.statements.c.object == removed))
            )
            conn.execute(
                update(t.names).where(t.names.c.entity_id == removed).values(entity_id=kept)
            )
            conn.execute(
                update(t.statements).where(t.statements.c.subject == removed).values(subject=kept)
            )
            conn.execute(
                update(t.statements).where(t.statements.c.object == removed).values(object=kept)
            )
            conn.execute(
                update(t.external_ids)
                .where(t.external_ids.c.entity_id == removed)
                .values(entity_id=kept)
            )
            conn.execute(
                update(t.entities).where(t.entities.c.id == removed).values(redirect_to=kept)
            )
            merge_id = conn.execute(
                t.merges.insert().values(
                    kept=kept,
                    removed=removed,
                    undone=False,
                    moved={"names": moved_names, "subject": moved_subject, "object": moved_object},
                )
            ).inserted_primary_key[0]
        events.emit("knowledge.entity.merged", kept=kept, removed=removed)
        return merge_id

    def undo_merge(self, merge_id: int) -> None:
        with self.engine.begin() as conn:
            m = conn.execute(select(t.merges).where(t.merges.c.id == merge_id)).mappings().one()
            moved = m["moved"]
            conn.execute(
                update(t.names)
                .where(t.names.c.id.in_(moved["names"]))
                .values(entity_id=m["removed"])
            )
            conn.execute(
                update(t.statements)
                .where(t.statements.c.id.in_(moved["subject"]))
                .values(subject=m["removed"])
            )
            conn.execute(
                update(t.statements)
                .where(t.statements.c.id.in_(moved["object"]))
                .values(object=m["removed"])
            )
            conn.execute(
                update(t.entities).where(t.entities.c.id == m["removed"]).values(redirect_to=None)
            )
            conn.execute(update(t.merges).where(t.merges.c.id == merge_id).values(undone=True))
        events.emit("knowledge.entity.merge_undone", kept=m["kept"], removed=m["removed"])
