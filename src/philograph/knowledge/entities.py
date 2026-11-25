"""Сущности онтологии: идентичность, названия, внешние идентификаторы, слияние дублей.

Всё, кроме идентичности, — утверждения. У сущности хранится только копия основных значений
(годы жизни, датировка, описание) для сортировки и быстрого показа.
"""

from __future__ import annotations

import uuid
from itertools import combinations
from typing import Any

from sqlalchemy import Engine, and_, delete, select, update

from philograph.knowledge import schema as t
from philograph.knowledge.naming import (
    InvalidName,
    check_name,
    is_russian,
    lang_for,
    normalize,
    reject,
)
from philograph.knowledge.registry import OntologyRegistry
from philograph.platform import events

__all__ = ["DuplicateEntity", "Entities", "EntityNotFound", "InvalidName", "normalize"]

events.define(
    "knowledge.entity.created", "info", "Создана сущность онтологии", required=("entity_id", "type")
)
events.define(
    "knowledge.entity.merged",
    "info",
    "Сущности слиты с перенаправлением",
    required=("kept", "removed"),
    optional=("reason", "statements", "attributions", "folded", "loops"),
)
events.define(
    "knowledge.entity.renamed",
    "info",
    "Сменилось основное название сущности",
    required=("entity_id", "lang", "previous_lang"),
)
events.define(
    "knowledge.entity.merge_undone",
    "info",
    "Слияние сущностей отменено",
    required=("kept", "removed"),
    optional=("restored",),
)


class DuplicateEntity(Exception):
    def __init__(self, existing: str) -> None:
        super().__init__(f"уже есть сущность {existing} с тем же внешним идентификатором")
        self.existing = existing


class EntityNotFound(Exception):
    def __init__(self, entity_id: str) -> None:
        super().__init__(f"сущность {entity_id} не найдена")
        self.entity_id = entity_id


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
        """``names``: (язык, текст, вид: primary | variant | original).

        Язык каждого названия ставится по письменности (``naming.lang_for``): переданный
        сохраняется, только если совпадает с ней. Основное название проверяется правилом
        названий; отказ — событие ``knowledge.entity.rejected`` и ``InvalidName``."""
        self.registry.entity_type(type_)
        names = [(lang_for(text, lang), text, kind) for lang, text, kind in names]
        for _, text, kind in names:
            if kind == "primary":
                self._check(type_, text)
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
                .one_or_none()
            )
            if row is None:
                raise EntityNotFound(entity_id)
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

    def types(self, entity_ids: list[str]) -> dict[str, str]:
        """Типы сущностей по идентификаторам (после перенаправлений слитых дублей)."""
        resolved = {eid: self.resolve(eid) for eid in dict.fromkeys(entity_ids)}
        if not resolved:
            return {}
        with self.engine.begin() as conn:
            rows = (
                conn.execute(
                    select(t.entities.c.id, t.entities.c.type).where(
                        t.entities.c.id.in_(list(resolved.values()))
                    )
                )
                .mappings()
                .all()
            )
        by_id = {r["id"]: r["type"] for r in rows}
        return {eid: by_id[rid] for eid, rid in resolved.items() if rid in by_id}

    def set_primary(self, entity_id: str, key: str, value: Any) -> None:
        """Копия основного значения; ``None`` — копии больше нет (ключ снимается)."""
        entity = self.get(entity_id)
        primary = {**entity["primary"], key: value}
        if value is None:
            del primary[key]
        with self.engine.begin() as conn:
            conn.execute(
                update(t.entities).where(t.entities.c.id == entity["id"]).values(primary=primary)
            )

    @staticmethod
    def _check(type_: str, text: str) -> None:
        reason = check_name(type_, text)
        if reason is not None:
            raise reject(type_, text, reason)

    def add_name(self, entity_id: str, lang: str, text: str, kind: str = "variant") -> None:
        """Язык — по письменности; основное название проверяется, как в ``create``."""
        entity_id = self.resolve(entity_id)
        if kind == "primary":
            self._check(self.get(entity_id)["type"], text)
        with self.engine.begin() as conn:
            conn.execute(
                t.names.insert().values(
                    entity_id=entity_id,
                    lang=lang_for(text, lang),
                    text=text,
                    normalized=normalize(text),
                    kind=kind,
                )
            )

    def set_primary_name(self, entity_id: str, lang: str, text: str) -> None:
        """Новое основное название той же сущности: прежние основные становятся вариантами
        (язык по письменности), идентификатор и всё, что на него ссылается, не меняются.
        Название, уже бывшее вариантом, повышается, а не дублируется."""
        entity = self.get(entity_id)
        self._check(entity["type"], text)
        lang = lang_for(text, lang)
        key = normalize(text)
        with self.engine.begin() as conn:
            rows = (
                conn.execute(select(t.names).where(t.names.c.entity_id == entity["id"]))
                .mappings()
                .all()
            )
            previous = [r for r in rows if r["kind"] == "primary"]
            for row in previous:
                conn.execute(
                    update(t.names)
                    .where(t.names.c.id == row["id"])
                    .values(kind="variant", lang=lang_for(row["text"], row["lang"]))
                )
            same = next((r for r in rows if r["normalized"] == key), None)
            if same is not None:
                conn.execute(
                    update(t.names)
                    .where(t.names.c.id == same["id"])
                    .values(kind="primary", lang=lang, text=text)
                )
            else:
                conn.execute(
                    t.names.insert().values(
                        entity_id=entity["id"], lang=lang, text=text, normalized=key, kind="primary"
                    )
                )
        previous_lang = lang_for(previous[0]["text"], previous[0]["lang"]) if previous else None
        events.emit(
            "knowledge.entity.renamed",
            entity_id=entity["id"],
            lang=lang,
            previous_lang=previous_lang,
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

    def add_external(self, entity_id: str, system: str, value: str) -> bool:
        """Внешний идентификатор существующей сущности. ``True`` — записан, ``False`` — уже
        был у неё же; у другой сущности — ``DuplicateEntity`` без записи."""
        entity_id = self.get(entity_id)["id"]  # перенаправление; нет сущности — EntityNotFound
        existing = self.by_external(system, value)
        if existing == entity_id:
            return False
        if existing is not None:
            raise DuplicateEntity(existing)
        with self.engine.begin() as conn:
            conn.execute(
                t.external_ids.insert().values(entity_id=entity_id, system=system, value=value)
            )
        return True

    def remove_external(self, entity_id: str, system: str, value: str) -> bool:
        """Снять внешний идентификатор (откат запуска). ``True`` — снят, ``False`` — его не
        было у этой сущности."""
        entity_id = self.resolve(entity_id)
        with self.engine.begin() as conn:
            return bool(
                conn.execute(
                    delete(t.external_ids).where(
                        and_(
                            t.external_ids.c.entity_id == entity_id,
                            t.external_ids.c.system == system,
                            t.external_ids.c.value == value,
                        )
                    )
                ).rowcount
            )

    def external_of(self, entity_id: str, system: str) -> str | None:
        """Внешний идентификатор системы у сущности (после перенаправлений)."""
        entity_id = self.resolve(entity_id)
        with self.engine.begin() as conn:
            return conn.scalar(
                select(t.external_ids.c.value)
                .where(
                    and_(t.external_ids.c.entity_id == entity_id, t.external_ids.c.system == system)
                )
                .order_by(t.external_ids.c.value)
            )

    def externals(self, system: str) -> dict[str, str]:
        """Сущность → значение внешнего идентификатора системы (по действующим сущностям)."""
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(t.external_ids.c.entity_id, t.external_ids.c.value)
                .where(t.external_ids.c.system == system)
                .order_by(t.external_ids.c.value)
            ).all()
        found: dict[str, str] = {}
        for entity_id, value in rows:
            found.setdefault(self.resolve(entity_id), value)
        return found

    def source_entity(self, source_id: str, title: str) -> str:
        """Источник библиотеки как сущность: на него ссылаются атрибуции и связь «издание»."""
        existing = self.by_external("library", source_id)
        return existing or self.create(
            "source", [("ru", title, "primary")], external={"library": source_id}
        )

    # --- дубли ---

    def duplicate_candidates(self) -> list[tuple[str, str]]:
        """Кандидаты в дубли одного типа — по индексу названий, без перебора всех пар:
        совпадает последнее слово названия и основные даты, или основное название одной
        совпадает с любым названием другой."""
        with self.engine.begin() as conn:
            rows = (
                conn.execute(select(t.entities).where(t.entities.c.redirect_to.is_(None)))
                .mappings()
                .all()
            )
            all_names = conn.execute(select(t.names)).mappings().all()
        position = {r["id"]: i for i, r in enumerate(rows)}
        by_id = {r["id"]: r for r in rows}
        last_words: dict[tuple[str, str], set[str]] = {}
        full: dict[tuple[str, str], set[str]] = {}
        primaries: dict[str, set[str]] = {}
        for n in all_names:
            entity = by_id.get(n["entity_id"])
            if entity is None:
                continue
            words = n["normalized"].split()
            last = words[-1] if words else ""
            last_words.setdefault((entity["type"], last), set()).add(entity["id"])
            full.setdefault((entity["type"], n["normalized"]), set()).add(entity["id"])
            if n["kind"] == "primary" and n["normalized"]:
                primaries.setdefault(entity["id"], set()).add(n["normalized"])
        pairs: set[tuple[str, str]] = set()
        for group in last_words.values():
            for a, b in combinations(sorted(group, key=position.get), 2):
                if by_id[a]["primary"].get("dates") == by_id[b]["primary"].get("dates"):
                    pairs.add((a, b))
        for entity_id, names in primaries.items():
            for name in names:
                for other in full.get((by_id[entity_id]["type"], name), ()):
                    if other != entity_id:
                        a, b = sorted((entity_id, other), key=position.get)
                        pairs.add((a, b))
        return sorted(pairs, key=lambda p: (position[p[0]], position[p[1]]))

    def merge(self, kept: str, removed: str, *, emit: bool = True) -> int:
        """Переносит названия, утверждения, внешние идентификаторы, упоминания, атрибуции-автора
        и портреты; старый идентификатор становится перенаправлением. Всё перенесённое пишется
        в ``merges.moved`` для отмены. Ключи утверждений и свёртку повторов пересчитывает
        ``Statements.merge_entities``."""
        kept, removed = self.resolve(kept), self.resolve(removed)
        with self.engine.begin() as conn:
            all_names = (
                conn.execute(select(t.names).where(t.names.c.entity_id.in_([kept, removed])))
                .mappings()
                .all()
            )
            kinds = _merged_kinds(kept, removed, all_names)
            for name_id, kind in kinds.items():
                conn.execute(update(t.names).where(t.names.c.id == name_id).values(kind=kind))
            moved_names = [n["id"] for n in all_names if n["entity_id"] == removed]
            moved_subject = list(
                conn.scalars(select(t.statements.c.id).where(t.statements.c.subject == removed))
            )
            moved_object = list(
                conn.scalars(select(t.statements.c.id).where(t.statements.c.object == removed))
            )
            moved_externals = [
                [r.system, r.value]
                for r in conn.execute(
                    select(t.external_ids).where(t.external_ids.c.entity_id == removed)
                )
            ]
            moved_who = list(
                conn.scalars(
                    select(t.attributions.c.id).where(
                        and_(t.attributions.c.who_kind == "entity", t.attributions.c.who == removed)
                    )
                )
            )
            kept_phash = set(
                conn.scalars(select(t.portraits.c.phash).where(t.portraits.c.entity_id == kept))
            )
            portraits = conn.execute(
                select(t.portraits.c.id, t.portraits.c.phash).where(
                    t.portraits.c.entity_id == removed
                )
            ).all()
            moved_portraits = [pid for pid, phash in portraits if phash not in kept_phash]
            portraits_kept = [pid for pid, phash in portraits if phash in kept_phash]
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
            moved_mentions = list(
                conn.scalars(select(t.mentions.c.id).where(t.mentions.c.entity_id == removed))
            )
            conn.execute(
                update(t.mentions).where(t.mentions.c.entity_id == removed).values(entity_id=kept)
            )
            if moved_who:
                conn.execute(
                    update(t.attributions)
                    .where(t.attributions.c.id.in_(moved_who))
                    .values(who=kept)
                )
            if moved_portraits:
                conn.execute(
                    update(t.portraits)
                    .where(t.portraits.c.id.in_(moved_portraits))
                    .values(entity_id=kept)
                )
            conn.execute(
                t.graph_extensions.delete().where(t.graph_extensions.c.entity_id == removed)
            )
            conn.execute(
                update(t.entities).where(t.entities.c.id == removed).values(redirect_to=kept)
            )
            merge_id = conn.execute(
                t.merges.insert().values(
                    kept=kept,
                    removed=removed,
                    undone=False,
                    moved={
                        "names": moved_names,
                        "subject": moved_subject,
                        "object": moved_object,
                        "mentions": moved_mentions,
                        "kinds": {str(n["id"]): n["kind"] for n in all_names if n["id"] in kinds},
                        "externals": moved_externals,
                        "attributions_who": moved_who,
                        "portraits": moved_portraits,
                        "portraits_kept": portraits_kept,
                    },
                )
            ).inserted_primary_key[0]
        if emit:
            events.emit("knowledge.entity.merged", kept=kept, removed=removed)
        return merge_id

    def undo_merge(self, merge_id: int, *, emit: bool = True) -> dict[str, Any]:
        """Возвращает перенесённое удалённой сущности; записи старого формата — с умолчаниями."""
        with self.engine.begin() as conn:
            m = conn.execute(select(t.merges).where(t.merges.c.id == merge_id)).mappings().one()
            moved = m["moved"]
            conn.execute(
                update(t.names)
                .where(t.names.c.id.in_(moved["names"]))
                .values(entity_id=m["removed"])
            )
            for name_id, kind in (moved.get("kinds") or {}).items():
                conn.execute(update(t.names).where(t.names.c.id == int(name_id)).values(kind=kind))
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
                update(t.mentions)
                .where(t.mentions.c.id.in_(moved.get("mentions", [])))
                .values(entity_id=m["removed"])
            )
            for system, value in moved.get("externals", []):
                conn.execute(
                    update(t.external_ids)
                    .where(and_(t.external_ids.c.system == system, t.external_ids.c.value == value))
                    .values(entity_id=m["removed"])
                )
            if moved.get("attributions_who"):
                conn.execute(
                    update(t.attributions)
                    .where(t.attributions.c.id.in_(moved["attributions_who"]))
                    .values(who=m["removed"])
                )
            if moved.get("portraits"):
                conn.execute(
                    update(t.portraits)
                    .where(t.portraits.c.id.in_(moved["portraits"]))
                    .values(entity_id=m["removed"])
                )
            conn.execute(
                update(t.entities).where(t.entities.c.id == m["removed"]).values(redirect_to=None)
            )
            conn.execute(update(t.merges).where(t.merges.c.id == merge_id).values(undone=True))
        if emit:
            events.emit("knowledge.entity.merge_undone", kept=m["kept"], removed=m["removed"])
        return dict(m)


def _merged_kinds(kept: str, removed: str, names: Any) -> dict[int, str]:
    """Новые виды названий после слияния: ровно одно основное — русское основное любой из
    сторон (сначала оставшейся), иначе основное оставшейся (иначе удалённой); прочие бывшие
    основные и точные повторы названий оставшейся — варианты. Только изменённые строки."""
    primaries = [n for n in names if n["kind"] == "primary"]
    order = sorted(primaries, key=lambda n: (n["entity_id"] != kept, n["id"]))
    russian = [n for n in order if is_russian(n["text"])]
    chosen = (russian or order or [None])[0]
    seen = {(n["lang"], n["normalized"]) for n in names if n["entity_id"] == kept}
    kinds: dict[int, str] = {}
    for n in names:
        new = n["kind"]
        if n["kind"] == "primary" and n is not chosen:
            new = "variant"
        if n["entity_id"] == removed and n is not chosen and (n["lang"], n["normalized"]) in seen:
            new = "variant"
        if new != n["kind"]:
            kinds[n["id"]] = new
    return kinds
