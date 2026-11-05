"""Проверка онтологии человеком: очередь по приоритету, решения, выборки для метрик."""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, update

from philograph.knowledge import schema as t
from philograph.knowledge.statements import Statements
from philograph.operator.access import ActionLog
from philograph.platform import events

events.define(
    "knowledge.review.decided",
    "info",
    "Решение по элементу очереди проверки",
    required=("target", "decision", "actor"),
)


@dataclass(frozen=True)
class Priority:
    """Вес признаков в приоритете очереди — настройка, а не код."""

    views: float = 1.0
    disputed: float = 20.0
    warning: float = 30.0
    generated: float = 10.0


class Review:
    def __init__(
        self, statements: Statements, actions: ActionLog, priority: Priority | None = None
    ) -> None:
        self.statements = statements
        self.entities = statements.entities
        self.registry = statements.registry
        self.actions = actions
        self.priority = priority or Priority()

    # --- показы для приоритета ---

    def record_views(self, statement_ids: list[str]) -> None:
        with self.statements.engine.begin() as conn:
            for sid in statement_ids:
                current = conn.scalar(
                    select(t.statement_views.c.views).where(t.statement_views.c.statement_id == sid)
                )
                if current is None:
                    conn.execute(t.statement_views.insert().values(statement_id=sid, views=1))
                else:
                    conn.execute(
                        update(t.statement_views)
                        .where(t.statement_views.c.statement_id == sid)
                        .values(views=current + 1)
                    )

    def _views(self) -> dict[str, int]:
        with self.statements.engine.begin() as conn:
            return dict(
                conn.execute(
                    select(t.statement_views.c.statement_id, t.statement_views.c.views)
                ).all()
            )

    # --- очередь ---

    def refresh_duplicates(self) -> int:
        with self.statements.engine.begin() as conn:
            known = {
                tuple(sorted(r.payload["pair"]))
                for r in conn.execute(
                    select(t.review_items).where(t.review_items.c.kind == "duplicate")
                )
            }
        added = 0
        for pair in self.entities.duplicate_candidates():
            if tuple(sorted(pair)) not in known:
                with self.statements.engine.begin() as conn:
                    conn.execute(
                        t.review_items.insert().values(
                            kind="duplicate", status="open", payload={"pair": list(pair)}
                        )
                    )
                added += 1
        return added

    def queue(
        self,
        *,
        kind: str | None = None,
        relation: str | None = None,
        source: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        views = self._views()
        items: list[dict[str, Any]] = []
        with self.statements.engine.begin() as conn:
            rows = (
                conn.execute(select(t.statements.c.id).where(t.statements.c.status != "rejected"))
                .scalars()
                .all()
            )
        for sid in rows:
            s = self.statements.get(sid)
            lost = any(e["lost"] for e in s["evidence"])
            if not s["warnings"] and not lost and s["status"] != "generated":
                continue
            item_kind = "lost_evidence" if lost else "warning" if s["warnings"] else "generated"
            if kind and item_kind != kind:
                continue
            if relation and s["type"] not in self.registry.relation_subtypes(relation):
                continue
            if status and s["status"] != status:
                continue
            if source and not any(a["who"] == source for a in s["attributions"]):
                continue
            score = (
                views.get(sid, 0) * self.priority.views
                + (s["consensus"] == "disputed") * self.priority.disputed
                + bool(s["warnings"] or lost) * self.priority.warning
                + (s["status"] == "generated") * self.priority.generated
            )
            items.append(
                {
                    "kind": item_kind,
                    "statement_id": sid,
                    "type": s["type"],
                    "score": score,
                    "warnings": s["warnings"],
                }
            )
        with self.statements.engine.begin() as conn:
            others = (
                conn.execute(select(t.review_items).where(t.review_items.c.status == "open"))
                .mappings()
                .all()
            )
        for r in others:
            if kind and r["kind"] != kind:
                continue
            if relation or status or source:
                continue
            items.append(
                {
                    "kind": r["kind"],
                    "item_id": r["id"],
                    "payload": r["payload"],
                    "score": self.priority.warning,
                }
            )
        for proposal in self.registry.proposals():
            if (kind in (None, "proposal")) and not (relation or status or source):
                items.append(
                    {
                        "kind": "proposal",
                        "proposal_id": proposal["id"],
                        "payload": proposal["payload"],
                        "score": self.priority.warning,
                    }
                )
        return sorted(items, key=lambda i: -i["score"])

    # --- контекст ---

    def context(self, statement_id: str) -> dict[str, Any]:
        s = self.statements.get(statement_id)
        evidence = []
        for e in s["evidence"]:
            text = self.statements.paragraph_text(e["paragraph_id"]) or ""
            start = text.lower().replace("ё", "е").find(e["quote"].lower().replace("ё", "е"))
            evidence.append(
                {
                    **e,
                    "paragraph_text": text,
                    "highlight": [start, start + len(e["quote"])] if start >= 0 else None,
                    "link": f"/p/{e['paragraph_id']}",
                }
            )
        spec = self.registry.relation(s["type"])
        return {
            "statement": s,
            "relation": spec["title"],
            "subject": self.entities.label(s["subject"]),
            "object": self.entities.label(s["object"]) if s["object"] else None,
            "evidence": evidence,
            "warnings": s["warnings"],
            "provenance": s["provenance"],
        }

    # --- решения по утверждениям ---

    def decide(
        self, statement_id: str, decision: str, actor: str, changes: dict[str, Any] | None = None
    ) -> None:
        if decision == "confirm":
            self.statements.confirm(statement_id, actor)
        elif decision == "reject":
            self.statements.reject(statement_id, actor)
        elif decision == "edit":
            before = self.statements.get(statement_id)
            values = {k: v for k, v in (changes or {}).items() if k in ("type", "qualifiers")}
            if "type" in values:
                self.registry.relation(values["type"])
            with self.statements.engine.begin() as conn:
                conn.execute(
                    update(t.statements)
                    .where(t.statements.c.id == statement_id)
                    .values(**values, warnings=[])
                )
            self.statements._journal(
                statement_id,
                actor,
                {
                    "edit": values,
                    "before": {"type": before["type"], "qualifiers": before["qualifiers"]},
                },
            )
            self.statements.confirm(statement_id, actor)
        else:
            raise ValueError("решение: confirm, edit, reject")
        self.actions.record(actor, f"statement_{decision}", statement_id, changes)
        events.emit("knowledge.review.decided", target=statement_id, decision=decision, actor=actor)

    # --- решения по сущностям и типам ---

    def _close(self, item_id: int, resolution: dict[str, Any]) -> dict[str, Any]:
        with self.statements.engine.begin() as conn:
            row = (
                conn.execute(select(t.review_items).where(t.review_items.c.id == item_id))
                .mappings()
                .one()
            )
            conn.execute(
                update(t.review_items)
                .where(t.review_items.c.id == item_id)
                .values(status="resolved", resolution=resolution)
            )
        return dict(row)

    def resolve_link(self, item_id: int, entity_id: str, actor: str) -> None:
        self._close(item_id, {"entity": entity_id})
        self.actions.record(actor, "resolve_link", str(item_id), {"entity": entity_id})
        events.emit(
            "knowledge.review.decided", target=f"item:{item_id}", decision="link", actor=actor
        )

    def resolve_duplicate(self, item_id: int, merge: bool, actor: str) -> None:
        row = self._close(item_id, {"merge": merge})
        if merge:
            kept, removed = row["payload"]["pair"]
            self.entities.merge(kept, removed)
        self.actions.record(actor, "merge" if merge else "keep_apart", str(item_id))
        events.emit(
            "knowledge.review.decided",
            target=f"item:{item_id}",
            decision="merge" if merge else "keep_apart",
            actor=actor,
        )

    def resolve_proposal(
        self, proposal_id: int, accept: bool, actor: str, spec: dict[str, Any] | None = None
    ) -> None:
        with self.statements.engine.begin() as conn:
            conn.execute(
                update(t.proposals)
                .where(t.proposals.c.id == proposal_id)
                .values(status="accepted" if accept else "rejected")
            )
        if accept and spec:
            self.registry.add_relation(actor, spec)
        self.actions.record(
            actor, "proposal_accept" if accept else "proposal_reject", str(proposal_id)
        )
        events.emit(
            "knowledge.review.decided",
            target=f"proposal:{proposal_id}",
            decision="accept" if accept else "reject",
            actor=actor,
        )

    # --- выборка для метрик ---

    def sample(self, relation: str, size: int, seed: int | None = None) -> str:
        types = self.registry.relation_subtypes(relation)
        with self.statements.engine.begin() as conn:
            ids = sorted(
                conn.execute(select(t.statements.c.id).where(and_types(types))).scalars().all()
            )
        chosen = random.Random(seed).sample(ids, min(size, len(ids)))
        sample_id = f"sample_{uuid.uuid4().hex[:10]}"
        with self.statements.engine.begin() as conn:
            if chosen:
                conn.execute(
                    t.review_samples.insert(),
                    [
                        {"sample": sample_id, "statement_id": sid, "decision": None}
                        for sid in chosen
                    ],
                )
        return sample_id

    def sample_items(self, sample_id: str) -> list[dict[str, Any]]:
        with self.statements.engine.begin() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    select(t.review_samples).where(t.review_samples.c.sample == sample_id)
                ).mappings()
            ]

    def decide_sample(self, sample_id: str, statement_id: str, correct: bool, actor: str) -> None:
        with self.statements.engine.begin() as conn:
            conn.execute(
                update(t.review_samples)
                .where(
                    (t.review_samples.c.sample == sample_id)
                    & (t.review_samples.c.statement_id == statement_id)
                )
                .values(decision="correct" if correct else "wrong")
            )
        self.actions.record(actor, "sample_decision", statement_id, {"correct": correct})

    def export_sample(self, sample_id: str) -> list[dict[str, Any]]:
        """Решённые элементы выборки в формате набора «statements» оценки качества."""
        exported = []
        for row in self.sample_items(sample_id):
            if row["decision"] is None:
                continue
            s = self.statements.get(row["statement_id"])
            exported.append(
                {
                    "item_id": row["statement_id"],
                    "type": s["type"],
                    "correct": row["decision"] == "correct",
                    "quote_supported": any(not e["lost"] for e in s["evidence"]),
                    "violation": bool(s["warnings"]),
                }
            )
        return exported


def and_types(types: set[str]):
    return t.statements.c.type.in_(sorted(types)) & (t.statements.c.status != "rejected")
