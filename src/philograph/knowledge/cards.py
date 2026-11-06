"""Карточки сущностей (ontology.md, раздел 11.1).

Каждая строка карточки — утверждение, поэтому у каждой видны атрибуция, подтверждающий абзац
и природа знания: проверено, по источникам или сгенерировано. Пустые разделы не показываются.
Описание модель пишет только если его нет, генерация включена и модель доступна; написанное
сохраняется со статусом «сгенерировано» и второй раз не запрашивается.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from philograph.knowledge.graph import attribution_label, recipes_for
from philograph.knowledge.mentions import Mentions
from philograph.knowledge.statements import Attribution, Provenance, Statements
from philograph.platform import events
from philograph.platform.client import ServiceClient, ServiceUnavailable

events.define(
    "knowledge.card.served",
    "info",
    "Отдана карточка сущности",
    required=("entity_id", "type", "sections", "rows"),
)
events.define(
    "knowledge.card.description", "info", "Описание карточки", required=("entity_id", "result")
)

INFLUENCE_FAMILY = "influenced_by"

# Разделы по типам: (код, заголовок, типы связей, направление: out | in | both)
SECTIONS: dict[str, list[tuple[str, str, list[str], str]]] = {
    "concept": [
        ("definitions", "Определения", ["definition"], "out"),
        ("words", "Происхождение слова", ["denotes"], "in"),
        ("conceptions", "История: концепции", ["conception_of"], "in"),
        (
            "related",
            "Связанные понятия",
            ["narrower", "opposed_to", "similar_to", "presupposes"],
            "both",
        ),
        ("problems", "Проблемы", ["answers", "part_of"], "both"),
    ],
    "person": [
        ("life", "Годы и места жизни", ["lifespan", "lived_in"], "out"),
        ("biography", "Биография", ["participated", "worked_at"], "out"),
        ("teachers", "Учителя и ученики", ["studied_with"], "both"),
        ("influence", "Влияния", [INFLUENCE_FAMILY], "both"),
        ("works", "Произведения", ["author"], "in"),
        ("schools", "Школы и направления", ["member_of", "founded"], "out"),
        ("positions", "Позиции и учения", ["holds"], "out"),
        ("epoch", "Контекст эпохи", ["belongs_to_epoch"], "out"),
    ],
    "event": [
        ("when", "Дата и место", ["dating", "happened_in"], "out"),
        ("effects", "На что повлияло", ["stimulated"], "out"),
    ],
    "doctrine": [
        ("parts", "Состав", ["part_of"], "in"),
        ("answers", "Ответы и сторонники", ["answers", "holds"], "both"),
        ("arguments", "Аргументы за и против", ["supports", "attacks"], "in"),
    ],
}
# Раздел «что часто путают» собирается отдельно (_misconceptions).
MISCONCEPTIONS_TITLE = "Часто считают, но…"
SECTIONS["phenomenon"] = SECTIONS["event"]
SECTIONS["idea_event"] = SECTIONS["event"]
for _type in ("problem", "position", "argument", "conception"):
    SECTIONS[_type] = SECTIONS["doctrine"]


class Cards:
    def __init__(
        self,
        statements: Statements,
        mentions: Mentions | None = None,
        llm: ServiceClient | None = None,
        on_view=None,
    ) -> None:
        self.statements = statements
        self.entities = statements.entities
        self.registry = statements.registry
        self.mentions = mentions
        self.llm = llm
        self.on_view = on_view  # приоритет очереди проверки: что чаще видят читатели

    def _row(
        self, s: dict[str, Any], entity_id: str, textbook: str | None = None
    ) -> dict[str, Any]:
        spec = self.registry.relation(s["type"])
        outward = s["subject"] == entity_id
        other = s["object"] if outward else s["subject"]
        visible = [a for a in s["attributions"] if not a["hidden"]]
        who = list(dict.fromkeys(attribution_label(self.statements, a) for a in visible))
        disputers = [
            attribution_label(self.statements, a) for a in visible if a["stance"] == "disputes"
        ]
        return {
            "statement_id": s["id"],
            "type": s["type"],
            "relation": spec["title"]
            if outward or spec.get("symmetric")
            else spec.get("inverse_title") or spec["title"],
            # Коды для перевода на клиенте: связь читается от другого конца (обратная подпись).
            "inverse": not outward and not spec.get("symmetric"),
            "entity_id": other,
            "label": self.entities.label(other) if other else None,
            "value": s.get("value"),
            "status": s["status"],
            "consensus": s["consensus"],
            "disputed": s["consensus"] == "disputed",
            "disputed_by": disputers,
            "generated": s["status"] == "generated",
            "derived": s.get("derived", False),
            # Есть ли строка в выбранном учебнике: для сравнения «как у меня и у других».
            "in_textbook": self.statements._attributed(s, textbook) if textbook else None,
            "attributed_to": who,
            "attributions": [
                {
                    "who": attribution_label(self.statements, a),
                    "kind": a["who_kind"],
                    "stance": a["stance"],
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
        }

    def card(
        self,
        entity_id: str,
        *,
        attributed_to: str | None = None,
        generation: bool = True,
        textbook: str | None = None,
    ) -> dict[str, Any]:
        """``attributed_to`` — режим «только выбранный учебник», ``textbook`` — пометка строк,
        которые есть в выбранном учебнике, в режиме «все источники»."""
        entity = self.entities.get(entity_id)
        entity_id = entity["id"]  # перенаправление слитой сущности
        statements = self.statements.about(entity_id, attributed_to=attributed_to)
        sections = []
        shown: list[str] = []
        for code, title, types, direction in SECTIONS.get(entity["type"], []):
            allowed = set().union(*(self.registry.relation_subtypes(x) for x in types))
            rows = [
                self._row(s, entity_id, textbook)
                for s in statements
                if s["type"] in allowed
                and (
                    direction == "both"
                    or (direction == "out") == (s["direction"] == "out")
                    or self.registry.relation(s["type"]).get("symmetric")
                )
            ]
            if code == "influence":
                rows = [r for r in rows if r["type"] != "studied_with"]
            if rows:  # пустой раздел не показывается заголовком
                sections.append({"code": code, "title": title, "rows": rows})
                shown += [r["statement_id"] for r in rows if not r["derived"]]
        description = next(
            (s for s in statements if s["type"] == "description" and s["direction"] == "out"), None
        )
        myths = self._misconceptions(entity_id)
        if myths:
            sections.append(
                {"code": "misconceptions", "title": MISCONCEPTIONS_TITLE, "rows": myths}
            )
        where = self.mentions.where_to_read(entity_id) if self.mentions else []
        if self.on_view and shown:
            self.on_view(shown)
        result = {
            "id": entity_id,
            "type": entity["type"],
            "title": self.entities.label(entity_id),
            "names": entity["names"],
            "dates": entity["primary"].get("dates"),
            "description": self._row(description, entity_id) if description else None,
            "description_pending": description is None
            and generation
            and self.llm is not None
            and attributed_to is None,
            "sections": sections,
            "where_to_read": where[:10],
            "recipes": recipes_for(self.registry, entity["type"]),
        }
        events.emit(
            "knowledge.card.served",
            entity_id=entity_id,
            type=entity["type"],
            sections=len(sections),
            rows=sum(len(s["rows"]) for s in sections),
        )
        return result

    def _misconceptions(self, entity_id: str) -> list[dict[str, Any]]:
        """Отвергнутые утверждения с атрибуцией «распространённое мнение»."""
        rows = []
        for s in self.statements.about(entity_id, include_deprecated=True, derived=False):
            if s["rank"] != "deprecated":
                continue
            if any(
                a["who_kind"] == "common" and a["stance"] == "asserts" for a in s["attributions"]
            ):
                rows.append(self._row(s, entity_id))
        return rows

    def describe(self, entity_id: str, *, generation: bool = True) -> Iterator[dict[str, Any]]:
        """Поток описания от модели; сохранённое описание отдаётся без вызова модели."""
        entity_id = self.entities.resolve(entity_id)
        existing = next(
            (
                s
                for s in self.statements.about(entity_id, derived=False)
                if s["type"] == "description" and s["direction"] == "out"
            ),
            None,
        )
        if existing is not None:
            events.emit("knowledge.card.description", entity_id=entity_id, result="stored")
            yield {
                "type": "done",
                "text": existing["value"],
                "generated": existing["status"] == "generated",
            }
            return
        if not generation or self.llm is None:
            events.emit("knowledge.card.description", entity_id=entity_id, result="disabled")
            yield {"type": "unavailable", "reason": "generation_disabled"}
            return
        entity = self.entities.get(entity_id)
        body = {
            "role": "main",
            "template": "card.description",
            "caller": "knowledge",
            "operation": "card_description",
            "budget": "site",
            "data": {"name": self.entities.label(entity_id), "type": entity["type"]},
        }
        text = ""
        try:
            with self.llm.stream("POST", "stream", json=body) as response:
                if response.status_code != 200:
                    response.read()
                    reason = response.json().get("kind", "error")
                    events.emit("knowledge.card.description", entity_id=entity_id, result=reason)
                    yield {"type": "unavailable", "reason": reason}
                    return
                for line in response.iter_lines():
                    if not line.strip():
                        continue
                    item = json.loads(line)
                    if item["type"] == "delta":
                        text += item["text"]
                        yield {"type": "delta", "text": item["text"]}
                    elif item["type"] == "error":
                        yield {"type": "unavailable", "reason": "stream_broken"}
                        return
        except ServiceUnavailable:
            events.emit("knowledge.card.description", entity_id=entity_id, result="unavailable")
            yield {"type": "unavailable", "reason": "llm_unavailable"}
            return
        self.statements.add(
            entity_id,
            "description",
            value=text.strip(),
            attributions=[Attribution("common", stance="mentions")],
            provenance=Provenance("generated", model="main", template="card.description"),
        )
        events.emit("knowledge.card.description", entity_id=entity_id, result="generated")
        yield {"type": "done", "text": text.strip(), "generated": True}
