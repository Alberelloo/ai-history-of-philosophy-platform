"""Граф по запросу (ontology.md, раздел 11.2).

Сохранённые утверждения отдаются сразу и без модели. Если связей меньше порога, генерация
включена и выбран режим «все источники», модель предлагает недостающие связи только типами
из семейств рецепта. Предложение проходит проверки записи и целостности, совпадающее с
отклонённым не показывается. Показанные предложения сохраняются через очередь со статусом
«сгенерировано», а сам факт достройки запоминается: повторный запрос модель не вызывает.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from philograph.knowledge import schema as t
from philograph.knowledge.registry import OntologyRegistry, RegistryError
from philograph.knowledge.statements import Provenance, StatementError, Statements
from philograph.platform import events
from philograph.platform.client import ServiceClient, ServiceUnavailable
from philograph.platform.queue import Job, Queue

events.define(
    "knowledge.graph.built",
    "info",
    "Построен граф из сохранённых связей",
    required=("entity_id", "recipe", "nodes", "edges", "truncated", "extension"),
)
events.define(
    "knowledge.graph.extended",
    "info",
    "Граф достроен моделью",
    required=("entity_id", "recipe", "proposed", "dropped"),
)
events.define(
    "knowledge.graph.proposal_dropped",
    "info",
    "Предложение модели для графа отброшено",
    required=("relation", "reason"),
)
events.define(
    "knowledge.graph.saved",
    "info",
    "Достроенные связи сохранены",
    required=("entity_id", "recipe", "statements"),
)

SAVE_JOB = "knowledge:graph.save"

# Почему достройки нет или что с ней происходит — клиент показывает это читателю.
NOTICES = {
    "disabled": "Достройка моделью выключена в настройках.",
    "scope": "В режиме «только выбранный учебник» граф показывает только то, что есть в учебнике.",
    "unavailable": "Достройка временно недоступна, показаны сохранённые связи.",
    "limit": "Дневной лимит достройки исчерпан, показаны сохранённые связи.",
}


@dataclass(frozen=True)
class GraphSettings:
    min_edges: int = 5  # меньше связей — граф достраивается
    max_nodes: int = 60


def attribution_label(statements: Statements, a: dict[str, Any]) -> str:
    """Кто так считает, по-человечески: персона, источник библиотеки или общее мнение."""
    if a["who_kind"] == "common":
        return "распространённое мнение"
    if a["who_kind"] == "entity" and a["who"]:
        return statements.entities.label(a["who"])
    if a["who_kind"] == "source" and a["who"]:
        entity = statements.entities.by_external("library", a["who"])
        return statements.entities.label(entity) if entity else a["who"]
    return a["who"] or "?"


def recipes_for(registry: OntologyRegistry, entity_type: str) -> list[dict[str, Any]]:
    """Рецепты, которые подходят типу сущности; «путь» требует двух концов и здесь не нужен."""
    return [
        {"code": code, "title": spec["title"], "depth": spec["depth"]}
        for code, spec in registry.recipes().items()
        if code != "path" and registry.is_a(entity_type, spec["start_types"])
    ]


class Graphs:
    def __init__(
        self,
        statements: Statements,
        llm: ServiceClient | None = None,
        queue: Queue | None = None,
        settings: GraphSettings | None = None,
    ) -> None:
        self.statements = statements
        self.entities = statements.entities
        self.registry = statements.registry
        self.engine = statements.engine
        self.llm = llm
        self.queue = queue
        self.settings = settings or GraphSettings()
        if queue is not None:
            queue.handler(SAVE_JOB)(self._save)

    # --- рецепты ---

    def recipes_for(self, entity_id: str) -> list[dict[str, Any]]:
        return recipes_for(self.registry, self.entities.get(entity_id)["type"])

    def check_recipe(self, entity_id: str, recipe: str) -> None:
        """Неподходящий рецепт — ошибка с перечнем подходящих."""
        spec = self.registry.recipe(recipe)
        entity_type = self.entities.get(entity_id)["type"]
        if not self.registry.is_a(entity_type, spec["start_types"]):
            raise RecipeNotApplicable(recipe, entity_type, self.recipes_for(entity_id))

    # --- вид узлов и связей ---

    def _node(self, entity_id: str, depth: int) -> dict[str, Any]:
        entity = self.entities.get(entity_id)
        dates = entity["primary"].get("dates")
        return {
            "id": entity_id,
            "label": self.entities.label(entity_id),
            "type": entity["type"],
            "depth": depth,
            "year": dates["earliest_start"] if dates else None,
            "dates": dates["original"] if dates else None,
        }

    def _edge(self, s: dict[str, Any], textbook: str | None) -> dict[str, Any]:
        spec = self.registry.relation(s["type"])
        visible = [a for a in s["attributions"] if not a["hidden"]]
        return {
            "id": s["id"],
            "subject": s["subject"],
            "object": s["object"],
            "type": s["type"],
            "title": spec["title"],
            "status": s["status"],
            "generated": s["status"] == "generated",
            "derived": s.get("derived", False),
            "pending": False,
            "consensus": s["consensus"],
            "qualifiers": s.get("qualifiers") or {},
            "attributions": [
                {
                    "who": attribution_label(self.statements, a),
                    "stance": a["stance"],
                    "place": a["place"],
                }
                for a in visible
            ],
            "evidence": [
                {
                    "paragraph_id": e["paragraph_id"],
                    "quote": e["quote"],
                    "link": f"/p/{e['paragraph_id']}",
                }
                for e in s["evidence"]
                if not e["lost"]
            ],
            "in_textbook": self.statements._attributed(s, textbook) if textbook else None,
        }

    # --- построение ---

    def build(
        self,
        entity_id: str,
        recipe: str,
        *,
        depth: int | None = None,
        textbook: str | None = None,
        only_textbook: bool = False,
        generation: bool = True,
    ) -> Iterator[dict[str, Any]]:
        """Поток событий графа: сначала сохранённое, затем достроенное моделью."""
        entity_id = self.entities.resolve(entity_id)
        self.check_recipe(entity_id, recipe)
        spec = self.registry.recipe(recipe)
        attributed_to = textbook if only_textbook and textbook else None
        found = self.statements.traverse(
            recipe,
            [entity_id],
            depth=depth,
            max_nodes=self.settings.max_nodes,
            attributed_to=attributed_to,
        )
        nodes = {n["id"]: self._node(n["id"], n["depth"]) for n in found["nodes"]}
        edges = [self._edge(s, textbook) for s in found["edges"]]
        extension = self._extension(entity_id, recipe, len(edges), attributed_to, generation)
        events.emit(
            "knowledge.graph.built",
            entity_id=entity_id,
            recipe=recipe,
            nodes=len(nodes),
            edges=len(edges),
            truncated=found["truncated"],
            extension=extension,
        )
        yield {
            "type": "graph",
            "entity_id": entity_id,
            "recipe": {"code": recipe, "title": spec["title"], "order": spec.get("order")},
            "depth": min(depth or spec["depth"], spec["depth"]),
            "max_depth": spec["depth"],
            "nodes": list(nodes.values()),
            "edges": edges,
            "truncated": found["truncated"],
            "extension": extension,
            "notice": NOTICES.get(extension),
            "recipes": self.recipes_for(entity_id),
        }
        if extension == "pending":
            yield from self._extend(entity_id, recipe, nodes, edges)
        yield {"type": "done"}

    def _extension(
        self,
        entity_id: str,
        recipe: str,
        edges: int,
        attributed_to: str | None,
        generation: bool,
    ) -> str:
        if attributed_to:
            return "scope"  # режим учебника показывает учебник, а не модель
        if edges >= self.settings.min_edges:
            return "not_needed"
        if not generation:
            return "disabled"
        if self.llm is None:
            return "unavailable"
        with self.engine.begin() as conn:
            done = conn.scalar(
                select(t.graph_extensions.c.proposed).where(
                    (t.graph_extensions.c.entity_id == entity_id)
                    & (t.graph_extensions.c.recipe == recipe)
                )
            )
        return "done_before" if done is not None else "pending"

    def _extend(
        self,
        entity_id: str,
        recipe: str,
        nodes: dict[str, dict[str, Any]],
        edges: list[dict[str, Any]],
    ) -> Iterator[dict[str, Any]]:
        spec = self.registry.recipe(recipe)
        allowed = sorted(self.registry.relations_in(spec["families"]))
        known = [
            f"{nodes.get(e['subject'], {}).get('label', e['subject'])} — {e['title']} — "
            f"{nodes.get(e['object'], {}).get('label', e['object'])}"
            for e in edges
        ]
        body = {
            "role": "main",
            "template": "graph.extend",
            "caller": "knowledge",
            "operation": "graph_extend",
            "budget": "site",
            "json_schema": PROPOSALS_SCHEMA,
            "data": {
                "entity": self.entities.label(entity_id),
                "recipe": spec["title"],
                "relations": "; ".join(
                    f"{code} ({self.registry.relation(code)['title']})" for code in allowed
                ),
                "known": "\n".join(known) or "нет",
            },
        }
        try:
            response = self.llm.post("structured", json=body)
        except ServiceUnavailable:
            yield {"type": "notice", "extension": "unavailable", "message": NOTICES["unavailable"]}
            return
        if response.status_code != 200:
            kind = "limit" if response.json().get("kind") == "budget_exhausted" else "unavailable"
            yield {"type": "notice", "extension": kind, "message": NOTICES[kind]}
            return
        accepted: list[dict[str, str]] = []
        dropped = 0
        for item in response.json()["value"]["statements"]:
            reason, proposal = self._proposal(item, allowed)
            if not reason and proposal["subject"] not in nodes and proposal["object"] not in nodes:
                reason = "disconnected"  # граф остаётся связным: связь касается его узлов
            if reason:
                dropped += 1
                events.emit(
                    "knowledge.graph.proposal_dropped",
                    relation=str(item.get("relation")),
                    reason=reason,
                )
                continue
            if (proposal["subject"], proposal["type"], proposal["object"]) in {
                (p["subject"], p["type"], p["object"]) for p in accepted
            }:
                continue
            accepted.append(proposal)
            new_nodes = [
                self._node(end, max(n["depth"] for n in nodes.values()) + 1)
                for end in (proposal["subject"], proposal["object"])
                if end not in nodes
            ]
            for node in new_nodes:
                nodes[node["id"]] = node
            yield {
                "type": "edge",
                "edge": self._proposed_edge(proposal),
                "nodes": new_nodes,
            }
        with self.engine.begin() as conn:
            conn.execute(
                t.graph_extensions.insert().values(
                    entity_id=entity_id,
                    recipe=recipe,
                    proposed=len(accepted),
                    time=self.statements.clock.now(),
                )
            )
        if accepted and self.queue is not None:
            self.queue.enqueue(
                SAVE_JOB,
                {"entity_id": entity_id, "recipe": recipe, "statements": accepted},
                key=f"graph:{entity_id}:{recipe}",
            )
        events.emit(
            "knowledge.graph.extended",
            entity_id=entity_id,
            recipe=recipe,
            proposed=len(accepted),
            dropped=dropped,
        )

    def _proposal(
        self, item: dict[str, Any], allowed: list[str]
    ) -> tuple[str | None, dict[str, str]]:
        relation = item.get("relation")
        if relation not in allowed:
            return "outside_recipe", {}
        ends = []
        for name in (item.get("subject"), item.get("object")):
            candidates = self.entities.find(str(name or ""))
            if len(candidates) != 1:
                # Новых сущностей граф не заводит, неоднозначное название не угадывает.
                return "unknown_entity" if not candidates else "ambiguous_entity", {}
            ends.append(candidates[0]["id"])
        reason = self.statements.check_proposal(ends[0], relation, ends[1])
        return reason, {"subject": ends[0], "type": relation, "object": ends[1]}

    def _proposed_edge(self, p: dict[str, str]) -> dict[str, Any]:
        return {
            "id": f"proposed:{p['subject']}:{p['type']}:{p['object']}",
            "subject": p["subject"],
            "object": p["object"],
            "type": p["type"],
            "title": self.registry.relation(p["type"])["title"],
            "status": "generated",
            "generated": True,
            "derived": False,
            "pending": True,
            "consensus": "unknown",
            "qualifiers": {},
            "attributions": [],
            "evidence": [],
            "in_textbook": None,
        }

    def _save(self, job: Job) -> None:
        saved = 0
        for p in job.payload["statements"]:
            try:
                self.statements.add(
                    p["subject"],
                    p["type"],
                    obj=p["object"],
                    provenance=Provenance(
                        "generated", actor="graph", model="main", template="graph.extend"
                    ),
                )
                saved += 1
            except (StatementError, RegistryError):
                continue  # за время ожидания связь стала недопустимой
        events.emit(
            "knowledge.graph.saved",
            entity_id=job.payload["entity_id"],
            recipe=job.payload["recipe"],
            statements=saved,
        )


class RecipeNotApplicable(Exception):
    def __init__(self, recipe: str, entity_type: str, suggestions: list[dict[str, Any]]) -> None:
        super().__init__(f"рецепт {recipe} не подходит типу {entity_type}")
        self.suggestions = suggestions


PROPOSALS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "statements": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string"},
                    "relation": {"type": "string"},
                    "object": {"type": "string"},
                },
                "required": ["subject", "relation", "object"],
            },
        }
    },
    "required": ["statements"],
}


def ndjson(items: Iterator[dict[str, Any]]) -> Iterator[str]:
    for item in items:
        yield json.dumps(item, ensure_ascii=False) + "\n"
