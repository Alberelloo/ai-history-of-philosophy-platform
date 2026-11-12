"""Онтология в ответах ассистента (ontology.md, раздел 11.3).

Шаги включаются по отдельности, чтобы оценка могла измерить вклад каждого:

- ``entities`` — сущности вопроса; без них остальные шаги не работают, поэтому распознавание
  идёт, если включён любой шаг;
- ``expansion`` — расширение поискового запроса;
- ``priority`` — приоритет абзацам с упоминаниями;
- ``context`` — утверждения онтологии в контексте модели;
- ``recipes`` — линия графа для цепочки «генезис и контекст»;
- ``verification`` — сверка дат и связей ответа с проверенными утверждениями.

Если сервис знаний недоступен, ассистент отвечает только по поиску, а в журнале остаётся
отметка, что онтология не использовалась.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from philograph.platform import events
from philograph.platform.client import ServiceClient, ServiceUnavailable
from philograph.platform.morphology import forms

STEPS = ("entities", "expansion", "priority", "context", "recipes", "verification")

events.define(
    "assistant.ontology.used",
    "info",
    "Ассистент использовал онтологию",
    required=("steps", "entities", "terms", "priority", "statements", "facts"),
)
events.define(
    "assistant.ontology.expanded",
    "info",
    "Поисковый запрос расширен по онтологии",
    required=("terms",),
)
events.define(
    "assistant.ontology.skipped",
    "warning",
    "Ответ построен без онтологии",
    required=("reason",),
    optional=("error",),
)
events.define(
    "assistant.ontology.contradiction",
    "warning",
    "Фрагмент ответа противоречит проверенному утверждению",
    required=("kind", "statement_id", "expected", "found"),
)

# Год в тексте: «1781», «1781 г.», «в 1781 году», «384 г. до н. э.».
YEAR_RE = re.compile(
    r"(?<![\d.,])(\d{3,4})(?![\d.,]\d)(?:\s*(?:г\.|год[ауом]*))?(\s*до\s*н\.\s*э\.)?"
)
INFLUENCED_RE = re.compile(r"\b(?:повлиял\w*|влиял\w*)\s+на\b", re.IGNORECASE)
INFLUENCED_BY_RE = re.compile(r"\bиспытал\w*\s+влияни\w*", re.IGNORECASE)


@dataclass(frozen=True)
class OntologySteps:
    enabled: frozenset[str] = frozenset(STEPS)

    @classmethod
    def parse(cls, value: str | None) -> OntologySteps:
        """``None`` или ``all`` — все шаги, ``none`` или пусто — ни одного, иначе через запятую."""
        if value is None or value.strip() == "all":
            return cls()
        names = {v.strip() for v in value.split(",") if v.strip() and v.strip() != "none"}
        unknown = names - set(STEPS)
        if unknown:
            raise ValueError(f"неизвестные шаги онтологии: {', '.join(sorted(unknown))}")
        return cls(frozenset(names))

    def __contains__(self, step: str) -> bool:
        return step in self.enabled


@dataclass
class OntologyContext:
    entities: list[dict[str, Any]] = field(default_factory=list)
    terms: list[str] = field(default_factory=list)
    priority: list[str] = field(default_factory=list)
    statements: list[dict[str, Any]] = field(default_factory=list)
    paragraphs: list[dict[str, Any]] = field(default_factory=list)
    facts: list[dict[str, Any]] = field(default_factory=list)
    graph: dict[str, Any] | None = None


class KnowledgeHttp:
    def __init__(self, client: ServiceClient) -> None:
        self.client = client

    def context(self, **body: Any) -> dict[str, Any]:
        response = self.client.post("internal/assistant/context", json=body)
        if response.status_code != 200:
            raise ServiceUnavailable("knowledge", f"ответ {response.status_code}")
        return response.json()


class Ontology:
    def __init__(self, knowledge: KnowledgeHttp, steps: OntologySteps | None = None) -> None:
        self.knowledge = knowledge
        self.steps = steps or OntologySteps()

    def prepare(
        self,
        *,
        text: str,
        names: list[str],
        paragraphs: list[str],
        recipe: str | None,
        textbook: str | None,
        region: str | None = None,
    ) -> OntologyContext | None:
        if not self.steps.enabled:
            events.emit("assistant.ontology.skipped", reason="steps_off")
            return None
        try:
            data = self.knowledge.context(
                text=text,
                names=names,
                paragraphs=paragraphs,
                steps=sorted(self.steps.enabled),
                recipe=recipe if "recipes" in self.steps else None,
                textbook=textbook,
                region=region,
            )
        except ServiceUnavailable as exc:
            events.emit(
                "assistant.ontology.skipped", reason="knowledge_unavailable", error=exc.reason
            )
            return None
        ctx = OntologyContext(
            entities=data["entities"],
            terms=data["terms"] if "expansion" in self.steps else [],
            priority=data["priority"] if "priority" in self.steps else [],
            statements=data["statements"] if {"context", "recipes"} & self.steps.enabled else [],
            paragraphs=data["paragraphs"] if "recipes" in self.steps else [],
            facts=data["facts"] if "verification" in self.steps else [],
            graph=data["graph"] if "recipes" in self.steps else None,
        )
        if ctx.terms:
            events.emit("assistant.ontology.expanded", terms=ctx.terms)
        events.emit(
            "assistant.ontology.used",
            steps=sorted(self.steps.enabled),
            entities=[e["label"] for e in ctx.entities],
            terms=len(ctx.terms),
            priority=len(ctx.priority),
            statements=len(ctx.statements),
            facts=len(ctx.facts),
        )
        return ctx

    # --- проверка ответа ---

    def check(self, text: str, ctx: OntologyContext) -> list[dict[str, Any]]:
        """Противоречия фрагмента проверенным датам: неверный год, влияние против времени."""
        if not ctx.facts:
            return []
        found = _mentioned(text, ctx.facts)
        problems = self._dates(text, found) + self._influence(text, found)
        for p in problems:
            events.emit(
                "assistant.ontology.contradiction",
                kind=p["kind"],
                statement_id=p["statement_id"],
                expected=p["expected"],
                found=p["found"],
            )
        return problems

    @staticmethod
    def _dates(text: str, found: list[tuple[int, dict[str, Any]]]) -> list[dict[str, Any]]:
        years = [
            1 - int(m.group(1)) if m.group(2) else int(m.group(1)) for m in YEAR_RE.finditer(text)
        ]
        dated = {f["entity_id"]: f for _, f in found if f["kind"] == "dating"}
        # Год рождения или смерти упомянутого человека — не дата произведения.
        life = {y for _, f in found if f["kind"] == "lifespan" for y in (f["start"], f["end"])}
        years = [y for y in years if y not in life]
        if len(dated) != 1 or not years:
            return []  # несколько датированных сущностей — не угадываем, к какой год
        fact = next(iter(dated.values()))
        if any(fact["start"] <= y <= fact["end"] for y in years):
            return []
        return [
            {
                "kind": "date",
                "statement_id": fact["statement_id"],
                "entity": fact["names"][0],
                "expected": fact["original"],
                "found": str(years[0]),
            }
        ]

    @staticmethod
    def _influence(text: str, found: list[tuple[int, dict[str, Any]]]) -> list[dict[str, Any]]:
        people = [(pos, f) for pos, f in found if f["kind"] == "lifespan"]
        problems = []
        for pattern, influencer_first in ((INFLUENCED_RE, True), (INFLUENCED_BY_RE, False)):
            for m in pattern.finditer(text):
                before = [f for pos, f in people if pos < m.start()]
                after = [f for pos, f in people if pos >= m.end()]
                if not before or not after:
                    continue
                first, second = before[-1], after[0]
                source, target = (first, second) if influencer_first else (second, first)
                # Повлиять мог только тот, кто родился до смерти того, на кого повлиял.
                if source["start"] > target["end"]:
                    problems.append(
                        {
                            "kind": "influence_against_time",
                            "statement_id": source["statement_id"],
                            "entity": source["names"][0],
                            "expected": f"{source['names'][0]}: {source['original']}, "
                            f"{target['names'][0]}: {target['original']}",
                            "found": m.group(0),
                        }
                    )
        return problems


def _mentioned(text: str, facts: list[dict[str, Any]]) -> list[tuple[int, dict[str, Any]]]:
    """Где во фрагменте упомянуты сущности с проверенными датами: (позиция, факт)."""
    words = forms(text)
    found = []
    for fact in facts:
        for name in fact["names"]:
            keys = [set(k) for k, _, _ in forms(name)]
            if not keys:
                continue
            for i in range(len(words) - len(keys) + 1):
                if all(keys[j] & set(words[i + j][0]) for j in range(len(keys))):
                    found.append((words[i][1], fact))
                    break
            else:
                continue
            break
    return sorted(found, key=lambda x: x[0])
