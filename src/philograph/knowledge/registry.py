"""Реестр онтологии как данные: типы сущностей, связей, уточнители, рецепты обхода.

Проверки, запросы, извлечение и показ берут типы отсюда. Новый тип — запись в реестре, а
не код. Тип, которым пользуются утверждения, нельзя удалить — только пометить устаревшим.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, Engine, func, select, update

from philograph.knowledge import registry_data as data
from philograph.knowledge import schema as t
from philograph.platform import events
from philograph.platform.clock import Clock, SystemClock
from philograph.platform.db import advisory_lock

events.define(
    "knowledge.registry.changed",
    "info",
    "Реестр онтологии изменился",
    required=("version", "change"),
)
events.define(
    "knowledge.registry.proposal",
    "info",
    "Предложен новый тип, ждёт проверки",
    required=("kind", "code"),
)


class RegistryError(Exception):
    pass


class OntologyRegistry:
    def __init__(self, engine: Engine, clock: Clock | None = None) -> None:
        self.engine = engine
        self.clock = clock or SystemClock()
        self._cache: dict[str, Any] | None = None

    # --- загрузка и версии ---

    def load_defaults(self, actor: str = "system") -> None:
        """Начальный реестр. Сервисы и заполнение демо стартуют одновременно: проверка и
        запись идут в одной транзакции под блокировкой, второй процесс увидит готовый реестр."""
        with self.engine.begin() as conn:
            advisory_lock(conn, "philograph-ontology-registry")
            if conn.scalar(select(func.count()).select_from(t.entity_types)):
                return
            conn.execute(
                t.entity_types.insert(),
                [
                    {"code": c, "title": title, "parent": parent}
                    for c, title, parent in data.ENTITY_TYPES
                ],
            )
            conn.execute(
                t.qualifiers.insert(),
                [
                    {"code": c, "title": title, "value_kind": kind, "allowed": allowed}
                    for c, title, kind, allowed in data.QUALIFIERS
                ],
            )
            conn.execute(
                t.relation_types.insert(), [{"code": r["code"], "spec": r} for r in data.RELATIONS]
            )
            conn.execute(
                t.recipes.insert(),
                [
                    {
                        "code": c,
                        "spec": {
                            "code": c,
                            "title": title,
                            "start_types": starts,
                            "families": families,
                            "direction": direction,
                            "depth": depth,
                            "order": order,
                        },
                    }
                    for c, title, starts, families, direction, depth, order in data.RECIPES
                ],
            )
            self._bump(actor, "начальный реестр", conn)

    def _bump(self, actor: str, change: str, conn: Connection | None = None) -> int:
        if conn is None:
            with self.engine.begin() as own:
                return self._bump(actor, change, own)
        advisory_lock(conn, "philograph-ontology-registry")
        version = (conn.scalar(select(func.max(t.registry_versions.c.version))) or 0) + 1
        conn.execute(
            t.registry_versions.insert().values(
                version=version, time=self.clock.now(), actor=actor, change=change
            )
        )
        self._cache = None
        events.emit("knowledge.registry.changed", version=version, change=change)
        return version

    def version(self) -> int:
        with self.engine.begin() as conn:
            return conn.scalar(select(func.max(t.registry_versions.c.version))) or 0

    def _load(self) -> dict[str, Any]:
        if self._cache is None:
            with self.engine.begin() as conn:
                self._cache = {
                    "entity_types": {
                        r.code: dict(r._mapping) for r in conn.execute(select(t.entity_types))
                    },
                    "relations": {
                        r.code: {**r.spec, "deprecated_by": r.deprecated_by}
                        for r in conn.execute(select(t.relation_types))
                    },
                    "qualifiers": {
                        r.code: dict(r._mapping) for r in conn.execute(select(t.qualifiers))
                    },
                    "recipes": {r.code: r.spec for r in conn.execute(select(t.recipes))},
                }
        return self._cache

    # --- типы сущностей ---

    def entity_type(self, code: str) -> dict[str, Any]:
        try:
            return self._load()["entity_types"][code]
        except KeyError:
            raise RegistryError(f"нет типа сущности {code}") from None

    def entity_subtypes(self, code: str) -> set[str]:
        types = self._load()["entity_types"]
        found = {code}
        changed = True
        while changed:
            changed = False
            for c, row in types.items():
                if row["parent"] in found and c not in found:
                    found.add(c)
                    changed = True
        return found

    def is_a(self, entity_type: str, allowed: list[str]) -> bool:
        """Тип подходит, если он сам или его предок есть в списке допустимых."""
        current: str | None = entity_type
        types = self._load()["entity_types"]
        while current is not None:
            if current in allowed:
                return True
            current = types.get(current, {}).get("parent")
        return False

    # --- типы связей ---

    def relation(self, code: str) -> dict[str, Any]:
        try:
            return self._load()["relations"][code]
        except KeyError:
            raise RegistryError(f"нет типа связи {code}") from None

    def relation_subtypes(self, code: str) -> set[str]:
        relations = self._load()["relations"]
        found = {code}
        changed = True
        while changed:
            changed = False
            for c, spec in relations.items():
                if spec.get("parent") in found and c not in found:
                    found.add(c)
                    changed = True
        return found

    def relations_in(self, families: list[str]) -> set[str]:
        return {
            c
            for c, s in self._load()["relations"].items()
            if set(s.get("families", [])) & set(families) and not s.get("deprecated_by")
        }

    def check_qualifiers(self, relation: str, values: dict[str, Any]) -> None:
        spec = self.relation(relation)
        known = self._load()["qualifiers"]
        for code, value in values.items():
            if code not in spec.get("qualifiers", []):
                raise RegistryError(f"уточнитель {code} недопустим для {relation}")
            q = known[code]
            if q["value_kind"] == "enum" and value not in (q["allowed"] or []):
                raise RegistryError(f"значение {value!r} недопустимо для уточнителя {code}")

    def recipes(self) -> dict[str, dict[str, Any]]:
        return dict(self._load()["recipes"])

    def recipe(self, code: str) -> dict[str, Any]:
        try:
            return self._load()["recipes"][code]
        except KeyError:
            raise RegistryError(f"нет рецепта {code}") from None

    # --- изменение реестра ---

    def add_relation(self, actor: str, spec: dict[str, Any]) -> int:
        """Новый тип связи — запись в реестре; проверки и запросы видят его сразу."""
        spec = {
            "inverse_title": None,
            "parent": None,
            "symmetric": False,
            "transitive": False,
            "families": [],
            "qualifiers": [],
            "v0": True,
            "value_kind": None,
            **spec,
        }
        with self.engine.begin() as conn:
            conn.execute(t.relation_types.insert().values(code=spec["code"], spec=spec))
        return self._bump(actor, f"тип связи {spec['code']}")

    def add_entity_type(self, actor: str, code: str, title: str, parent: str | None = None) -> int:
        with self.engine.begin() as conn:
            conn.execute(t.entity_types.insert().values(code=code, title=title, parent=parent))
        return self._bump(actor, f"тип сущности {code}")

    def deprecate_relation(self, actor: str, code: str, replacement: str) -> int:
        self.relation(replacement)
        with self.engine.begin() as conn:
            conn.execute(
                update(t.relation_types)
                .where(t.relation_types.c.code == code)
                .values(deprecated_by=replacement)
            )
        return self._bump(actor, f"{code} устарел, замена {replacement}")

    def delete_relation(self, actor: str, code: str) -> None:
        with self.engine.begin() as conn:
            used = conn.scalar(
                select(func.count()).select_from(t.statements).where(t.statements.c.type == code)
            )
            if used:
                raise RegistryError(
                    f"тип {code} используется в {used} утверждениях: его "
                    "можно только пометить устаревшим"
                )
            conn.execute(t.relation_types.delete().where(t.relation_types.c.code == code))
        self._bump(actor, f"удалён тип связи {code}")

    def propose(self, kind: str, payload: dict[str, Any]) -> int:
        """Предложение модели не применяется само: оно ждёт проверки человеком."""
        with self.engine.begin() as conn:
            pid = conn.execute(
                t.proposals.insert().values(kind=kind, payload=payload, status="pending")
            ).inserted_primary_key[0]
        events.emit("knowledge.registry.proposal", kind=kind, code=payload.get("code", "?"))
        return pid

    def proposals(self, status: str = "pending") -> list[dict[str, Any]]:
        with self.engine.begin() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    select(t.proposals).where(t.proposals.c.status == status)
                ).mappings()
            ]

    # --- схема вывода для LLM ---

    def output_schema(self, families: list[str] | None = None) -> dict[str, Any]:
        """JSON Schema структурированного вывода: только допустимые типы и уточнители."""
        relations = (
            self.relations_in(families)
            if families
            else {
                c
                for c, s in self._load()["relations"].items()
                if not s.get("deprecated_by") and s.get("v0", True)
            }
        )
        relations = sorted(r for r in relations if not self.relation(r).get("value_kind"))
        return {
            "type": "object",
            "required": ["statements"],
            "properties": {
                "statements": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["subject", "type", "object", "paragraph", "quote"],
                        "properties": {
                            "subject": {"type": "string"},
                            "type": {"enum": relations},
                            "object": {"type": "string"},
                            "qualifiers": {"type": "object"},
                            "paragraph": {"type": "integer"},
                            "quote": {"type": "string"},
                            "stance": {"enum": ["asserts", "disputes", "mentions"]},
                            "attributed_to": {"type": "string"},
                        },
                    },
                }
            },
            "x-relations": {
                r: {
                    "title": self.relation(r)["title"],
                    "subjects": self.relation(r)["subject_types"],
                    "objects": self.relation(r)["object_types"],
                }
                for r in relations
            },
        }
