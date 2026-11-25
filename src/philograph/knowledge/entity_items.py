"""Привязка сущностей из ответа модели по всем написаниям (элементы ``entities``).

Модель называет сущность в утверждениях строкой (``subject``, ``object``, ``attributed_to``) и
может прислать элемент ``entities`` с русским, английским и оригинальным написанием и
датировкой. Здесь — привязка к существующей сущности по любому написанию, создание новой по
правилам названий (``naming``) и запись проверенной датировки (``dating``). Неоднозначная
привязка не угадывается, а уходит на проверку.
"""

from __future__ import annotations

from typing import Any

from philograph.knowledge import dating
from philograph.knowledge import schema as t
from philograph.knowledge.entities import Entities
from philograph.knowledge.naming import (
    InvalidName,
    check_name,
    is_russian,
    names_for,
    reject,
)
from philograph.knowledge.statements import Attribution, Evidence, Provenance, Statements
from philograph.platform import events

ENTITY_TYPE_DROPPED = "entity:type"


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

    # --- элементы ответа ---

    def index(self, items: list[dict[str, Any]] | None, run_id: str) -> dict[str, dict[str, Any]]:
        """Элементы ``entities`` по ``name``. Элемент с типом вне реестра не используется:
        сервер проверяет сам и не полагается на схему шлюза."""
        known = set(self.registry._load()["entity_types"])
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
        type_ = type_ or (item or {}).get("type")
        candidates: dict[str, dict[str, Any]] = {}
        for spelling in _spellings(name, item):
            for c in self.entities.find(spelling):
                candidates.setdefault(c["id"], c)
        found = list(candidates.values())
        if type_:
            found = [c for c in found if self.registry.is_a(c["type"], [type_])]
        if len(found) == 1:
            resolved[name] = found[0]["id"]
            if item:
                self._russian_primary(found[0], item)
            return resolved[name]
        if len(found) > 1:
            return self._ambiguous(name, found, resolved)
        if not type_:
            raise Skip(f"новая сущность «{name}» без типа")
        names = names_for(type_, item) if item else [("ru", name, "primary")]
        try:
            resolved[name] = self.entities.create(type_, names)
        except InvalidName as exc:
            raise Skip(str(exc)) from exc
        self.created.append(resolved[name])
        return resolved[name]

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
        raise Skip(f"неоднозначное название «{name}»")

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
            "lifespan" if is_person else "dating",
            value=result.to_json(),
            evidence=[Evidence(paragraph["id"], spec["quote"], source_id=source_id)],
            attributions=[Attribution("source", source_id)],
            provenance=Provenance(
                "extracted", run_id=run_id, model="main", template="ontology.extract"
            ),
        )
