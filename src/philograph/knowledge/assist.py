"""Онтология для ассистента (ontology.md, раздел 11.3).

Один запрос ассистента получает всё, что ему нужно от онтологии, и только для включённых шагов:

- сущности вопроса: упоминания выделенных абзацев, названия в тексте вопроса и названия от
  маршрутизатора; неоднозначные — все кандидаты с весом 0.5;
- расширение запроса: названия, варианты, переводы и соседи по связям из настройки;
- приоритет: абзацы, где упомянуты найденные сущности;
- контекст: утверждения о сущностях с идентификаторами, атрибуцией и статусом;
- рецепт: линия графа по времени с подтверждающими абзацами;
- проверка: проверенные даты сущностей, по которым ассистент сверяет ответ.
"""

from __future__ import annotations

from typing import Any

from philograph.knowledge.graph import attribution_label
from philograph.knowledge.mentions import Mentions
from philograph.knowledge.registry import RegistryError
from philograph.knowledge.statements import STRENGTH, Statements
from philograph.platform import events

events.define(
    "knowledge.assistant.context",
    "info",
    "Онтология подготовила контекст для ассистента",
    required=("entities", "terms", "priority", "statements", "facts"),
)

STEPS = ("entities", "expansion", "priority", "context", "recipes", "verification")
EXPANSION_RELATIONS = ("translated_as", "denotes", "similar_to", "narrower")
DATED = ("lifespan", "dating")


class AssistantKnowledge:
    def __init__(
        self,
        statements: Statements,
        mentions: Mentions,
        *,
        expansion_relations: tuple[str, ...] = EXPANSION_RELATIONS,
        max_entities: int = 5,
        max_statements: int = 12,
        max_terms: int = 20,
    ) -> None:
        self.statements = statements
        self.entities = statements.entities
        self.registry = statements.registry
        self.mentions = mentions
        self.expansion_relations = expansion_relations
        self.max_entities = max_entities
        self.max_statements = max_statements
        self.max_terms = max_terms

    # --- сущности вопроса ---

    def resolve(self, text: str, names: list[str], paragraphs: list[str]) -> list[dict[str, Any]]:
        chapter = self.mentions.chapter_entities(paragraphs) if paragraphs else set()
        weights: dict[str, float] = {}
        how: dict[str, str] = {}

        def add(entity_id: str, weight: float, way: str) -> None:
            entity_id = self.entities.resolve(entity_id)
            if weight > weights.get(entity_id, 0):
                weights[entity_id], how[entity_id] = weight, way

        for m in self.mentions.for_targets(paragraphs) if paragraphs else []:
            add(m["entity_id"], 1.0, "selection")
        for source, way in [(text, "question"), *[(n, "router") for n in names]]:
            for m in self.mentions.find_in_text(source, chapter):
                add(m["entity_id"], 0.5 if m["method"] == "ambiguous" else 1.0, way)
        found = []
        for entity_id, weight in sorted(weights.items(), key=lambda x: -x[1]):
            entity = self.entities.get(entity_id)
            found.append(
                {
                    "id": entity_id,
                    "label": self.entities.label(entity_id),
                    "type": entity["type"],
                    "weight": weight,
                    "how": how[entity_id],
                }
            )
        return found

    # --- вид утверждения для модели ---

    def describe(self, s: dict[str, Any]) -> dict[str, Any]:
        spec = self.registry.relation(s["type"])
        value = s.get("value")
        if s["object"]:
            other = self.entities.label(s["object"])
        elif isinstance(value, dict):
            other = str(value.get("original", value))
        else:
            other = str(value)
        visible = [a for a in s["attributions"] if not a["hidden"]]
        sources = [a["who"] for a in visible if a["who_kind"] == "source" and a["who"]]
        sources += [e["source_id"] for e in s["evidence"] if e["source_id"] and not e["lost"]]
        return {
            "id": s["id"],
            "text": f"{self.entities.label(s['subject'])} — {spec['title']} — {other}",
            "type": s["type"],
            "status": s["status"],
            "attributed_to": list(
                dict.fromkeys(attribution_label(self.statements, a) for a in visible)
            ),
            "sources": list(dict.fromkeys(sources)),
            "evidence": [
                {"paragraph_id": e["paragraph_id"], "source_id": e["source_id"]}
                for e in s["evidence"]
                if not e["lost"]
            ],
            "year": self._year(s),
        }

    def _year(self, s: dict[str, Any]) -> float | None:
        years = []
        for end in (s["subject"], s["object"]):
            dates = self.entities.get(end)["primary"].get("dates") if end else None
            if dates:
                years.append(dates["earliest_start"])
        return min(years) if years else None

    # --- контекст ---

    def context(
        self,
        *,
        text: str,
        names: list[str],
        paragraphs: list[str],
        steps: list[str],
        recipe: str | None = None,
        textbook: str | None = None,
    ) -> dict[str, Any]:
        found = self.resolve(text, names, paragraphs)
        top = [e for e in found if e["weight"] >= 1.0][: self.max_entities] or found[
            : self.max_entities
        ]
        ids = [e["id"] for e in top]
        result: dict[str, Any] = {
            "entities": found,
            "terms": [],
            "priority": [],
            "statements": [],
            "paragraphs": [],
            "facts": [],
            "graph": None,
        }
        if "expansion" in steps:
            result["terms"] = self._terms([e["id"] for e in found], text)
        if "priority" in steps and found:
            result["priority"] = self.mentions.paragraphs_of([e["id"] for e in found])
        if "recipes" in steps and recipe and top:
            line, graph = self._line(top, recipe, textbook)
            result["statements"] += line
            result["graph"] = graph
            result["paragraphs"] = self._paragraphs(line)
        if "context" in steps:
            seen = {s["id"] for s in result["statements"]}
            about = []
            for entity_id in ids:
                for s in self.statements.about(entity_id, attributed_to=textbook, derived=False):
                    if s["id"] not in seen and s["type"] != "description":
                        seen.add(s["id"])
                        about.append(s)
            about.sort(key=lambda s: -STRENGTH[s["status"]])
            result["statements"] += [self.describe(s) for s in about[: self.max_statements]]
        if "verification" in steps:
            ends = set(ids)
            for s in result["statements"]:
                original = self.statements.get(s["id"])
                ends |= {e for e in (original["subject"], original["object"]) if e}
            result["facts"] = self._facts(sorted(ends))
        events.emit(
            "knowledge.assistant.context",
            entities=len(found),
            terms=len(result["terms"]),
            priority=len(result["priority"]),
            statements=len(result["statements"]),
            facts=len(result["facts"]),
        )
        return result

    def _terms(self, ids: list[str], text: str) -> list[str]:
        """Названия, варианты, переводы и соседи по связям из настройки, кроме уже написанного."""
        terms: list[str] = []
        lowered = text.lower()
        for entity_id in ids:
            names = [n["text"] for n in self.entities.get(entity_id)["names"]]
            for s in self.statements.about(entity_id, types=list(self.expansion_relations)):
                other = s["object"] if s["subject"] == entity_id else s["subject"]
                if other:
                    names += [n["text"] for n in self.entities.get(other)["names"]]
            terms += [n for n in names if n.lower() not in lowered]
        return list(dict.fromkeys(terms))[: self.max_terms]

    def _line(
        self, top: list[dict[str, Any]], recipe: str, textbook: str | None
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        """Линия по рецепту от главной сущности вопроса, по времени."""
        for entity in top:
            for code in (recipe, "context"):
                spec = self.registry.recipe(code)
                if not self.registry.is_a(entity["type"], spec["start_types"]):
                    continue
                try:
                    found = self.statements.traverse(code, [entity["id"]], attributed_to=textbook)
                except RegistryError:
                    continue
                line = [self.describe(s) for s in found["edges"] if not s.get("derived")]
                line.sort(key=lambda s: s["year"] if s["year"] is not None else float("inf"))
                graph = {
                    "entity_id": entity["id"],
                    "recipe": code,
                    "label": entity["label"],  # клиент собирает подпись на языке интерфейса
                    "title": f"Открыть граф: {spec['title'].lower()} — {entity['label']}",
                }
                return line[: self.max_statements], graph
        return [], None

    def _paragraphs(self, line: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Подтверждающие абзацы линии — модель получает их текст рядом с утверждениями."""
        result, seen = [], set()
        for s in line:
            for e in s["evidence"]:
                if e["paragraph_id"] in seen:
                    continue
                text = self.statements.paragraph_text(e["paragraph_id"])
                if text:
                    seen.add(e["paragraph_id"])
                    result.append(
                        {
                            "paragraph_id": e["paragraph_id"],
                            "source_id": e["source_id"],
                            "text": text,
                        }
                    )
        return result

    def _facts(self, ids: list[str]) -> list[dict[str, Any]]:
        """Проверенные человеком даты: только они служат основанием пометить ответ."""
        facts = []
        for entity_id in ids:
            entity = self.entities.get(entity_id)
            for s in self.statements.about(entity_id, types=list(DATED), derived=False):
                if s["status"] != "verified" or s["subject"] != entity_id:
                    continue
                value = s["value"] or {}
                facts.append(
                    {
                        "entity_id": entity_id,
                        "type": entity["type"],
                        "names": [n["text"] for n in entity["names"]],
                        "kind": s["type"],
                        "start": value.get("earliest_start"),
                        "end": value.get("latest_end"),
                        "original": value.get("original"),
                        "statement_id": s["id"],
                    }
                )
        return facts
