"""Привязка сущностей из ответа модели по всем написаниям (элементы ``entities``).

Модель называет сущность в утверждениях строкой (``subject``, ``object``, ``attributed_to``) и
может прислать элемент ``entities`` с русским, английским и оригинальным написанием и
датировкой. Здесь — привязка к существующей сущности по любому написанию, создание новой по
правилам названий (``naming``) и запись проверенной датировки (``dating``). Неоднозначная
привязка не угадывается, а уходит на проверку.
"""

from __future__ import annotations

from itertools import combinations
from typing import Any

from philograph.knowledge import dating, dedupe
from philograph.knowledge import schema as t
from philograph.knowledge.entities import Entities
from philograph.knowledge.naming import (
    InvalidName,
    check_name,
    is_russian,
    names_for,
    normalize,
    reject,
)
from philograph.knowledge.statements import Attribution, Evidence, Provenance, Statements
from philograph.platform import events

# События извлечения описаны здесь: их пишут и ``EntityItems``, и ``Filling`` (он импортирует
# этот модуль), поэтому они зарегистрированы при любом пути, в том числе из миграции.
events.define(
    "knowledge.extraction.dropped",
    "warning",
    "Утверждение модели отброшено",
    required=("run_id", "reason"),
)
events.define(
    "knowledge.extraction.ambiguous",
    "info",
    "Неоднозначная привязка — на проверку",
    required=("name", "candidates"),
)

# Причины отказа элемента — коды без названия (О17, О18): название, если нужно, есть в
# ``knowledge.entity.rejected`` с обрезкой; отклонённое название — ``entity:<naming.REASONS>``.
ENTITY_TYPE_DROPPED = "entity:type"
ENTITY_NO_TYPE = "entity:no_type"
ENTITY_AMBIGUOUS = "entity:ambiguous"


class Skip(Exception):
    """Утверждение (или датировка) отбрасывается с причиной; запуск продолжается."""


def _spellings(name: str, item: dict[str, Any] | None) -> list[str]:
    found = [name]
    if item:
        found += [item.get("ru"), item.get("en"), (item.get("original") or {}).get("text")]
    return list(dict.fromkeys(s for s in found if s))


class EntityItems:
    def __init__(
        self, entities: Entities, statements: Statements, created: list[str] | None = None
    ) -> None:
        self.entities = entities
        self.statements = statements
        self.registry = statements.registry
        self.created = created if created is not None else []
        # Названия фрагмента, которые не удалось привязать: датировка их не привязывает снова
        # (второго пункта ``ambiguous_link`` нет). Сбрасывается в ``index`` — начале фрагмента.
        self.unresolved: set[str] = set()

    # --- элементы ответа ---

    def index(self, items: list[dict[str, Any]] | None, run_id: str) -> dict[str, dict[str, Any]]:
        """Элементы ``entities`` по ``name``. Элемент с типом вне реестра не используется:
        сервер проверяет сам и не полагается на схему шлюза."""
        self.unresolved = set()
        known = self.registry.entity_types()
        index: dict[str, dict[str, Any]] = {}
        for item in items or []:
            if not isinstance(item, dict) or not item.get("name"):
                continue
            if item.get("type") not in known:
                events.emit(
                    "knowledge.extraction.dropped", run_id=run_id, reason=ENTITY_TYPE_DROPPED
                )
                continue
            index.setdefault(item["name"], item)
        return index

    # --- привязка ---

    def resolve(
        self,
        name: str,
        type_: str | None,
        item: dict[str, Any] | None,
        resolved: dict[str, str],
    ) -> str:
        """Существующая сущность по любому написанию; новая — если нет; неоднозначная — на
        проверку (пункт ``ambiguous_link``, утверждение отбрасывается)."""
        if name in resolved:
            return resolved[name]
        try:
            return self._resolve(name, type_, item, resolved)
        except Skip:
            self.unresolved.add(name)
            raise

    def _resolve(
        self,
        name: str,
        type_: str | None,
        item: dict[str, Any] | None,
        resolved: dict[str, str],
    ) -> str:
        type_ = type_ or (item or {}).get("type")
        candidates: dict[str, dict[str, Any]] = {}
        hits: dict[str, set[str]] = {}
        for spelling in _spellings(name, item):
            for c in self.entities.find(spelling):
                candidates.setdefault(c["id"], c)
                hits.setdefault(c["id"], set()).add(normalize(spelling))
        found = list(candidates.values())
        if type_:
            found = [c for c in found if self.registry.is_a(c["type"], [type_])]
        if len(found) == 1:
            resolved[name] = found[0]["id"]
            if item:
                self._russian_primary(found[0], item)
            return resolved[name]
        if len(found) > 1 and item:
            kept = self._merge_variants(found, hits)
            if kept is not None:
                resolved[name] = kept
                self._russian_primary(self.entities.get(kept), item)
                return kept
        if len(found) > 1:
            return self._ambiguous(name, found, resolved)
        if not type_:
            raise Skip(ENTITY_NO_TYPE)
        names = names_for(type_, item) if item else [("ru", name, "primary")]
        try:
            resolved[name] = self.entities.create(type_, names)
        except InvalidName as exc:
            # Только код: название уже в ``knowledge.entity.rejected`` с обрезкой (О17).
            raise Skip(f"entity:{exc.reason}") from exc
        self.created.append(resolved[name])
        return resolved[name]

    def _merge_variants(self, found: list[dict[str, Any]], hits: dict[str, set[str]]) -> str | None:
        """Разные написания одного элемента нашли разных персон: правило слияния вариантов с
        парой от модели. Все пары — ``merge`` → слияние, привязка к оставшейся; есть ``review``
        → пункт очереди ``duplicate``, дальше прежняя неоднозначность; ``apart`` — она же."""
        ids = [c["id"] for c in found]
        if any(c["type"] != dedupe.PERSON for c in found):
            return None
        if any(not hits[a].isdisjoint(hits[b]) for a, b in combinations(ids, 2)):
            return None  # одно написание нашло нескольких — это неоднозначность, не варианты
        persons = {e.id: e for e in dedupe.load_persons(self.statements.engine, ids)}
        open_, distinct = dedupe.duplicate_items(self.statements.engine)
        verdicts = {
            (a, b): dedupe.same_person(
                persons[a],
                persons[b],
                paired_by_model=True,
                decided_apart=dedupe.pair_key(a, b) in distinct,
            )
            for a, b in combinations(sorted(ids), 2)
        }
        if all(v.kind == "merge" for v in verdicts.values()):
            counts = dedupe.link_counts(self.statements.engine, ids)
            kept = dedupe.choose_kept(persons.values(), counts)
            for other in sorted(x for x in ids if x != kept):
                reason = verdicts[dedupe.pair_key(kept, other)].reason
                self.statements.merge_entities(kept, other, reason=reason)
            return kept
        for (a, b), v in verdicts.items():
            if v.kind == "review":
                dedupe.propose(self.statements.engine, a, b, v.reason, open_)
        return None

    def _ambiguous(self, name: str, candidates: list[dict[str, Any]], resolved: dict[str, str]):
        # Контекст фрагмента: кандидат, уже связанный с найденными здесь сущностями.
        linked = [
            c
            for c in candidates
            if any(
                s["object"] in resolved.values() or s["subject"] in resolved.values()
                for s in self.statements.about(c["id"], derived=False)
            )
        ]
        if len(linked) == 1:
            resolved[name] = linked[0]["id"]
            return resolved[name]
        with self.statements.engine.begin() as conn:
            conn.execute(
                t.review_items.insert().values(
                    kind="ambiguous_link",
                    status="open",
                    resolution=None,
                    payload={"name": name, "candidates": [c["id"] for c in candidates]},
                )
            )
        events.emit("knowledge.extraction.ambiguous", name=name, candidates=len(candidates))
        raise Skip(ENTITY_AMBIGUOUS)

    def _russian_primary(self, entity: dict[str, Any], item: dict[str, Any]) -> None:
        """У найденной сущности нет русского основного, а элемент дал русское написание,
        прошедшее проверку, — оно становится основным; прежнее основное — вариант."""
        ru = item.get("ru")
        if not ru or any(n["kind"] == "primary" and is_russian(n["text"]) for n in entity["names"]):
            return
        reason = check_name(entity["type"], ru)
        if reason is not None:
            reject(entity["type"], ru, reason)
            return
        if is_russian(ru):
            self.entities.set_primary_name(entity["id"], "ru", ru)

    # --- датировка ---

    def date_item(
        self,
        name: str,
        item: dict[str, Any],
        resolved: dict[str, str],
        window: list[dict[str, Any]],
        source_id: str,
        run_id: str,
    ) -> str:
        """Датировка элемента ``entities``: привязка (или создание) сущности и ``date``.
        Сущность не определена — название отклонено, неоднозначно, без типа, в том числе уже
        в утверждениях фрагмента — ``Skip(dating.UNRESOLVED)``, повторной привязки нет."""
        if name in self.unresolved:
            raise Skip(dating.UNRESOLVED)
        try:
            entity_id = self.resolve(name, item["type"], item, resolved)
        except Skip as exc:
            raise Skip(dating.UNRESOLVED) from exc
        return self.date(entity_id, item, window, source_id, run_id)

    def date(
        self,
        entity_id: str,
        item: dict[str, Any],
        window: list[dict[str, Any]],
        source_id: str,
        run_id: str,
    ) -> str:
        """Проверенная датировка элемента — утверждение ``lifespan`` (персона) или ``dating``.
        Отказ — ``Skip`` с причиной ``dating:<код>``."""
        spec = item.get("dating") or {}
        entity_type = self.entities.get(entity_id)["type"]
        is_person = self.registry.is_a(entity_type, ["person"])
        relation = "lifespan" if is_person else "dating"
        if not self.registry.is_a(entity_type, self.registry.relation(relation)["subject_types"]):
            raise Skip(dating.TYPE)  # датировка типа, которому реестр её не разрешает
        result = dating.check(
            spec.get("text") or "",
            spec.get("quote") or "",
            spec.get("paragraph"),
            [p["text"] for p in window],
            is_person=is_person,
        )
        if isinstance(result, str):
            raise Skip(result)
        paragraph = window[spec["paragraph"] - 1]
        return self.statements.add(
            entity_id,
            relation,
            value=result.to_json(),
            evidence=[Evidence(paragraph["id"], spec["quote"], source_id=source_id)],
            attributions=[Attribution("source", source_id)],
            provenance=Provenance(
                "extracted", run_id=run_id, model="main", template="ontology.extract"
            ),
        )
