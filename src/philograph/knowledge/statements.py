"""Утверждения: связи и значения с атрибуцией, подтверждениями, согласием, статусом.

Ошибки целостности не допускаются в базу, предупреждения ставят утверждение в очередь
проверки (поле ``warnings``). Повтор того же утверждения не создаёт записи, а добавляет
атрибуции и подтверждения. Выведенное не хранится, а считается при запросе.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlalchemy import Engine, and_, delete, or_, select, update

from philograph.knowledge import schema as t
from philograph.knowledge.dates import FuzzyDate
from philograph.knowledge.entities import Entities
from philograph.knowledge.registry import OntologyRegistry, RegistryError
from philograph.platform import events
from philograph.platform.clock import Clock, SystemClock

Status = Literal["verified", "sourced", "generated", "rejected"]
STRENGTH = {"verified": 3, "sourced": 2, "generated": 1, "rejected": 0}
INFLUENCE = "influenced_by"

events.define(
    "knowledge.statement.created",
    "info",
    "Записано утверждение",
    required=("statement_id", "type", "status"),
)
events.define(
    "knowledge.statement.merged", "info", "Повтор утверждения объединён", required=("statement_id",)
)
events.define(
    "knowledge.statement.refused",
    "warning",
    "Утверждение не записано: ошибка",
    required=("type", "reason"),
)
events.define(
    "knowledge.statement.warning",
    "warning",
    "Предупреждение целостности, утверждение в очереди проверки",
    required=("statement_id", "warning"),
)
events.define(
    "knowledge.statement.status",
    "info",
    "Статус утверждения изменился",
    required=("statement_id", "old", "new", "reason"),
)
events.define(
    "knowledge.statement.rejected_repeat",
    "info",
    "Повтор отклонённого утверждения не показывается",
    required=("statement_id",),
)
events.define(
    "knowledge.run.rolled_back",
    "info",
    "Запуск наполнения откачен",
    required=("run_id", "statements", "attributions", "evidence"),
)
events.define(
    "knowledge.library.event",
    "info",
    "Онтология обработала событие библиотеки",
    required=("event_id", "kind", "lost", "moved", "rechecked"),
)


class StatementError(Exception):
    pass


@dataclass
class Attribution:
    who_kind: Literal["entity", "source", "common"]
    who: str | None = None
    stance: Literal["asserts", "disputes", "mentions"] = "asserts"
    place: str | None = None


@dataclass
class Evidence:
    paragraph_id: str
    quote: str
    source_id: str | None = None
    supports: bool = True


@dataclass
class Provenance:
    method: Literal["manual", "extracted", "imported", "generated", "derived"]
    run_id: str | None = None
    model: str | None = None
    template: str | None = None
    actor: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


ParagraphText = Callable[[str], str | None]


def _norm_quote(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("ё", "е")).strip().lower()


class Statements:
    def __init__(
        self,
        engine: Engine,
        registry: OntologyRegistry,
        entities: Entities,
        paragraph_text: ParagraphText,
        clock: Clock | None = None,
    ) -> None:
        self.engine = engine
        self.registry = registry
        self.entities = entities
        self.paragraph_text = paragraph_text
        self.clock = clock or SystemClock()

    # --- запись ---

    def _key(
        self, subject: str, type_: str, obj: str | None, value: Any, qualifiers: dict[str, Any]
    ) -> str:
        spec = self.registry.relation(type_)
        ends = [subject, obj]
        if spec.get("symmetric") and obj is not None:
            ends = sorted(ends)  # симметричная связь хранится один раз
        payload = json.dumps(
            [ends, type_, value, qualifiers], sort_keys=True, ensure_ascii=False, default=str
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def _check(
        self,
        subject: str,
        type_: str,
        obj: str | None,
        value: Any,
        qualifiers: dict[str, Any],
        attributions: list[Attribution],
        evidence: list[Evidence],
    ) -> None:
        spec = self.registry.relation(type_)
        if spec.get("deprecated_by"):
            raise StatementError(f"тип {type_} устарел, используйте {spec['deprecated_by']}")
        subject_type = self.entities.get(subject)["type"]
        if not self.registry.is_a(subject_type, spec["subject_types"]):
            raise StatementError(f"тип субъекта {subject_type} недопустим для {type_}")
        if spec.get("value_kind"):
            if value is None:
                raise StatementError(f"у {type_} должно быть значение")
            if type_ == "definition" and not attributions:
                raise StatementError("у определения обязательна атрибуция")
        else:
            if obj is None:
                raise StatementError(f"у {type_} должен быть объект")
            object_type = self.entities.get(obj)["type"]
            if not self.registry.is_a(object_type, spec["object_types"]):
                raise StatementError(f"тип объекта {object_type} недопустим для {type_}")
        self.registry.check_qualifiers(type_, qualifiers)
        for ev in evidence:
            text = self.paragraph_text(ev.paragraph_id)
            if text is None or _norm_quote(ev.quote) not in _norm_quote(text):
                raise StatementError(f"цитата не найдена в абзаце {ev.paragraph_id}")

    def add(
        self,
        subject: str,
        type_: str,
        *,
        obj: str | None = None,
        value: Any = None,
        qualifiers: dict[str, Any] | None = None,
        attributions: list[Attribution] | None = None,
        evidence: list[Evidence] | None = None,
        provenance: Provenance | None = None,
        scope: str = "public",
        rank: str = "normal",
        status: Status | None = None,
    ) -> str:
        qualifiers = qualifiers or {}
        attributions = attributions or []
        evidence = evidence or []
        provenance = provenance or Provenance("manual")
        subject = self.entities.resolve(subject)
        obj = self.entities.resolve(obj) if obj else None
        try:
            self._check(subject, type_, obj, value, qualifiers, attributions, evidence)
        except (StatementError, RegistryError) as exc:
            events.emit("knowledge.statement.refused", type=type_, reason=str(exc))
            raise StatementError(str(exc)) from exc
        key = self._key(subject, type_, obj, value, qualifiers)
        with self.engine.begin() as conn:
            existing = (
                conn.execute(
                    select(t.statements).where(
                        and_(t.statements.c.key == key, t.statements.c.scope == scope)
                    )
                )
                .mappings()
                .first()
            )
        if existing is not None:
            self._attach(existing["id"], attributions, evidence, provenance)
            if existing["status"] == "rejected":
                events.emit("knowledge.statement.rejected_repeat", statement_id=existing["id"])
            else:
                events.emit("knowledge.statement.merged", statement_id=existing["id"])
            return existing["id"]
        if status is None:
            status = (
                "verified"
                if provenance.method == "manual" and not evidence
                else "sourced"
                if evidence
                else "generated"
                if provenance.method == "generated"
                else "sourced"
            )
        if status == "sourced" and not evidence and provenance.method != "imported":
            raise StatementError("у утверждения «по источникам» должно быть подтверждение")
        statement_id = f"st_{uuid.uuid4().hex[:12]}"
        with self.engine.begin() as conn:
            conn.execute(
                t.statements.insert().values(
                    id=statement_id,
                    subject=subject,
                    type=type_,
                    object=obj,
                    value=value,
                    qualifiers=qualifiers,
                    key=key,
                    status=status,
                    consensus="unknown",
                    consensus_manual=False,
                    rank=rank,
                    scope=scope,
                    warnings=[],
                    provenance={**provenance.__dict__},
                )
            )
        self._attach(statement_id, attributions, evidence, provenance, new=True)
        self._journal(
            statement_id,
            provenance.actor or provenance.method,
            {"created": type_, "status": status},
        )
        events.emit(
            "knowledge.statement.created", statement_id=statement_id, type=type_, status=status
        )
        for warning in self._integrity(subject, type_, obj):
            self._warn(statement_id, warning)
        self._update_primary(subject, type_)
        return statement_id

    def _attach(
        self,
        statement_id: str,
        attributions: list[Attribution],
        evidence: list[Evidence],
        provenance: Provenance,
        new: bool = False,
    ) -> None:
        with self.engine.begin() as conn:
            for a in attributions:
                conn.execute(
                    t.attributions.insert().values(
                        statement_id=statement_id,
                        who_kind=a.who_kind,
                        who=a.who,
                        stance=a.stance,
                        place=a.place,
                        run_id=provenance.run_id,
                        hidden=False,
                    )
                )
            for ev in evidence:
                conn.execute(
                    t.evidence.insert().values(
                        statement_id=statement_id,
                        paragraph_id=ev.paragraph_id,
                        source_id=ev.source_id,
                        quote=ev.quote,
                        supports=ev.supports,
                        lost=False,
                        run_id=provenance.run_id,
                    )
                )
        self._recompute_consensus(statement_id)
        if evidence and not new:
            self._promote(statement_id, "найдено подтверждение")

    def _promote(self, statement_id: str, reason: str) -> None:
        current = self.get(statement_id)
        if current["status"] == "generated":
            self._set_status(statement_id, "sourced", reason)

    def _set_status(
        self, statement_id: str, new: Status, reason: str, actor: str = "system"
    ) -> None:
        old = self.get(statement_id)["status"]
        if old == new:
            return
        with self.engine.begin() as conn:
            conn.execute(
                update(t.statements).where(t.statements.c.id == statement_id).values(status=new)
            )
        self._journal(statement_id, actor, {"status": [old, new], "reason": reason})
        events.emit(
            "knowledge.statement.status", statement_id=statement_id, old=old, new=new, reason=reason
        )

    def _journal(self, statement_id: str, actor: str, change: dict[str, Any]) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                t.journal.insert().values(
                    statement_id=statement_id, time=self.clock.now(), actor=actor, change=change
                )
            )

    def _warn(self, statement_id: str, warning: str) -> None:
        current = self.get(statement_id)
        if warning in current["warnings"]:
            return
        with self.engine.begin() as conn:
            conn.execute(
                update(t.statements)
                .where(t.statements.c.id == statement_id)
                .values(warnings=[*current["warnings"], warning])
            )
        events.emit("knowledge.statement.warning", statement_id=statement_id, warning=warning)

    # --- целостность ---

    def _date(self, entity_id: str, key: str) -> FuzzyDate | None:
        raw = self.entities.get(entity_id)["primary"].get(key)
        return FuzzyDate.from_json(raw) if raw else None

    def _integrity(self, subject: str, type_: str, obj: str | None) -> list[str]:
        warnings = []
        if obj is None:
            return warnings
        if type_ in self.registry.relation_subtypes(INFLUENCE):
            life = self._date(subject, "dates")
            available = self._date(obj, "dates")
            if life and available and life.before(available):
                warnings.append("influence_against_time")
        if type_ == "studied_with":
            a, b = self._date(subject, "dates"), self._date(obj, "dates")
            if a and b and (a.before(b) or b.before(a)):
                warnings.append("lives_do_not_overlap")
        if type_ == "source_material":
            event, material = self._date(subject, "dates"), self._date(obj, "dates")
            if event and material and event.before(material):
                warnings.append("source_after_event")
        if type_ == "author":
            work, life = self._date(subject, "dates"), self._date(obj, "dates")
            if work and life and (work.before(life) or life.before(work)):
                warnings.append("work_outside_life")
        return warnings

    def _update_primary(self, entity_id: str, type_: str) -> None:
        """Копия основного значения у сущности: годы жизни, датировка, описание."""
        key = {"lifespan": "dates", "dating": "dates", "description": "description"}.get(type_)
        if key is None:
            return
        rows = [
            s
            for s in self._raw(entity_id, side="subject")
            if s["type"] == type_ and s["status"] != "rejected" and s["rank"] != "deprecated"
        ]
        if rows:
            best = sorted(rows, key=lambda s: s["rank"] != "preferred")[0]
            self.entities.set_primary(entity_id, key, best["value"])

    # --- согласие, ранг, решения ---

    def _recompute_consensus(self, statement_id: str) -> None:
        current = self.get(statement_id)
        if current["consensus_manual"]:
            return
        visible = [a for a in current["attributions"] if not a["hidden"]]
        asserts = {(a["who_kind"], a["who"]) for a in visible if a["stance"] == "asserts"}
        disputes = {(a["who_kind"], a["who"]) for a in visible if a["stance"] == "disputes"}
        if disputes and asserts:
            consensus = "prevailing" if len(asserts) >= 3 * len(disputes) else "disputed"
        elif disputes:
            consensus = "marginal"
        elif len(asserts) >= 3:
            consensus = "accepted"
        elif asserts:
            consensus = "prevailing"
        else:
            consensus = "unknown"
        with self.engine.begin() as conn:
            conn.execute(
                update(t.statements)
                .where(t.statements.c.id == statement_id)
                .values(consensus=consensus)
            )

    def set_consensus(self, statement_id: str, consensus: str, actor: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                update(t.statements)
                .where(t.statements.c.id == statement_id)
                .values(consensus=consensus, consensus_manual=True)
            )
        self._journal(statement_id, actor, {"consensus": consensus})

    def set_rank(self, statement_id: str, rank: str, actor: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                update(t.statements).where(t.statements.c.id == statement_id).values(rank=rank)
            )
        self._journal(statement_id, actor, {"rank": rank})
        s = self.get(statement_id)
        self._update_primary(s["subject"], s["type"])

    def confirm(self, statement_id: str, actor: str) -> None:
        self._set_status(statement_id, "verified", "подтвердил человек", actor)

    def reject(self, statement_id: str, actor: str) -> None:
        self._set_status(statement_id, "rejected", "отклонил человек", actor)

    # --- чтение ---

    def get(self, statement_id: str) -> dict[str, Any]:
        with self.engine.begin() as conn:
            row = (
                conn.execute(select(t.statements).where(t.statements.c.id == statement_id))
                .mappings()
                .one()
            )
            attrs = (
                conn.execute(
                    select(t.attributions).where(t.attributions.c.statement_id == statement_id)
                )
                .mappings()
                .all()
            )
            evs = (
                conn.execute(select(t.evidence).where(t.evidence.c.statement_id == statement_id))
                .mappings()
                .all()
            )
        return {
            **dict(row),
            "attributions": [dict(a) for a in attrs],
            "evidence": [dict(e) for e in evs],
        }

    def journal(self, statement_id: str) -> list[dict[str, Any]]:
        with self.engine.begin() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    select(t.journal)
                    .where(t.journal.c.statement_id == statement_id)
                    .order_by(t.journal.c.id)
                ).mappings()
            ]

    def _raw(self, entity_id: str, side: str = "both") -> list[dict[str, Any]]:
        cond = {
            "subject": t.statements.c.subject == entity_id,
            "object": t.statements.c.object == entity_id,
            "both": or_(t.statements.c.subject == entity_id, t.statements.c.object == entity_id),
        }[side]
        with self.engine.begin() as conn:
            ids = list(conn.scalars(select(t.statements.c.id).where(cond)))
        return [self.get(i) for i in ids]

    def about(
        self,
        entity_id: str,
        *,
        families: list[str] | None = None,
        types: list[str] | None = None,
        statuses: list[str] | None = None,
        attributed_to: str | None = None,
        scopes: tuple[str, ...] = ("public",),
        include_deprecated: bool = False,
        derived: bool = True,
    ) -> list[dict[str, Any]]:
        """Утверждения о сущности с обеих сторон связи; отклонённые и отвергнутые скрыты."""
        entity_id = self.entities.resolve(entity_id)
        allowed_types: set[str] | None = None
        if types:
            allowed_types = set().union(*(self.registry.relation_subtypes(x) for x in types))
        if families:
            fam = self.registry.relations_in(families)
            allowed_types = fam if allowed_types is None else allowed_types & fam
        result = []
        for s in self._raw(entity_id):
            if s["scope"] not in scopes or s["status"] == "rejected":
                continue
            if s["rank"] == "deprecated" and not include_deprecated:
                continue
            if allowed_types is not None and s["type"] not in allowed_types:
                continue
            if statuses and s["status"] not in statuses:
                continue
            if attributed_to and not self._attributed(s, attributed_to):
                continue
            if s["attributions"] and all(a["hidden"] for a in s["attributions"]):
                continue  # основано только на снятом источнике
            result.append(
                {**s, "derived": False, "direction": "out" if s["subject"] == entity_id else "in"}
            )
        if derived and (allowed_types is None or INFLUENCE in allowed_types):
            result.extend(self._derived_influences(entity_id, scopes))
        return result

    @staticmethod
    def _attributed(s: dict[str, Any], source_id: str) -> bool:
        return any(a["who"] == source_id and not a["hidden"] for a in s["attributions"]) or any(
            e["source_id"] == source_id and not e["lost"] for e in s["evidence"]
        )

    def _derived_influences(self, person: str, scopes: tuple[str, ...]) -> list[dict[str, Any]]:
        """Участник идейного события испытал влияние его исходного материала."""
        derived = []
        for p in self._raw(person, side="subject"):
            if p["type"] != "participated" or p["status"] == "rejected" or p["scope"] not in scopes:
                continue
            for m in self._raw(p["object"], side="subject"):
                if m["type"] != "source_material" or m["status"] == "rejected":
                    continue
                weakest = min((p["status"], m["status"]), key=STRENGTH.__getitem__)
                derived.append(
                    {
                        "id": f"derived:{p['id']}:{m['id']}",
                        "subject": person,
                        "type": INFLUENCE,
                        "object": m["object"],
                        "status": weakest,
                        "derived": True,
                        "direction": "out",
                        "attributions": [],
                        "evidence": [],
                        "qualifiers": {},
                        "rank": "normal",
                        "consensus": "unknown",
                        "premises": [p["id"], m["id"]],
                    }
                )
        return derived

    def contemporaries(self, a: str, b: str) -> bool | None:
        da, db = self._date(a, "dates"), self._date(b, "dates")
        if not da or not db:
            return None
        before = da.before(db)
        after = db.before(da)
        if before is None or after is None:
            return None
        return not before and not after

    # --- обход по рецепту ---

    def traverse(
        self,
        recipe_code: str,
        start: list[str],
        *,
        depth: int | None = None,
        max_nodes: int = 60,
        scopes: tuple[str, ...] = ("public",),
        attributed_to: str | None = None,
    ) -> dict[str, Any]:
        recipe = self.registry.recipe(recipe_code)
        depth = min(depth or recipe["depth"], recipe["depth"])
        start = [self.entities.resolve(s) for s in start]
        for s in start:
            entity_type = self.entities.get(s)["type"]
            if not self.registry.is_a(entity_type, recipe["start_types"]):
                raise RegistryError(f"рецепт {recipe_code} не подходит типу {entity_type}")
        nodes: dict[str, int] = {s: 0 for s in start}
        edges: dict[str, dict[str, Any]] = {}
        queue = deque(start)
        truncated = False
        while queue:
            current = queue.popleft()
            if nodes[current] >= depth:
                continue
            for s in self.about(
                current, families=recipe["families"], scopes=scopes, attributed_to=attributed_to
            ):
                outward = s["direction"] == "out"
                if (
                    recipe["direction"] == "backward"
                    and not outward
                    and not self.registry.relation(s["type"]).get("symmetric")
                ):
                    continue
                if (
                    recipe["direction"] == "forward"
                    and outward
                    and not self.registry.relation(s["type"]).get("symmetric")
                ):
                    continue
                other = s["object"] if s["subject"] == current else s["subject"]
                if other is None:
                    continue
                edges.setdefault(s["id"], s)
                if other not in nodes:
                    if len(nodes) >= max_nodes:
                        truncated = True
                        continue
                    nodes[other] = nodes[current] + 1
                    queue.append(other)
        ordered = list(nodes)
        if recipe.get("order") == "time":

            def start_year(entity_id: str) -> float:
                d = self._date(entity_id, "dates")
                return d.earliest_start if d else float("inf")

            ordered.sort(key=start_year)
        return {
            "nodes": [{"id": n, "depth": nodes[n]} for n in ordered],
            "edges": list(edges.values()),
            "truncated": truncated,
        }

    # --- откат запуска и события библиотеки ---

    def rollback_run(self, run_id: str) -> dict[str, int]:
        """Убирает всё, что добавил запуск, кроме проверенного человеком."""
        with self.engine.begin() as conn:
            attrs = conn.execute(
                delete(t.attributions).where(t.attributions.c.run_id == run_id)
            ).rowcount
            evs = conn.execute(delete(t.evidence).where(t.evidence.c.run_id == run_id)).rowcount
            candidates = (
                conn.execute(select(t.statements).where(t.statements.c.status != "verified"))
                .mappings()
                .all()
            )
        removed = 0
        for s in candidates:
            if s["provenance"].get("run_id") != run_id:
                continue
            full = self.get(s["id"])
            if not full["attributions"] and not full["evidence"]:
                with self.engine.begin() as conn:
                    conn.execute(delete(t.statements).where(t.statements.c.id == s["id"]))
                removed += 1
        events.emit(
            "knowledge.run.rolled_back",
            run_id=run_id,
            statements=removed,
            attributions=attrs,
            evidence=evs,
        )
        return {"statements": removed, "attributions": attrs, "evidence": evs}

    def handle_library_event(self, kind: str, payload: dict[str, Any]) -> dict[str, int]:
        event_id = payload["event_id"]
        with self.engine.begin() as conn:
            if conn.scalar(
                select(t.processed.c.event_id).where(t.processed.c.event_id == event_id)
            ):
                return {"lost": 0, "moved": 0, "rechecked": 0}
        counts = {"lost": 0, "moved": 0, "rechecked": 0}
        if kind == "source.published":
            for old, new in (payload.get("redirected") or {}).items():
                with self.engine.begin() as conn:
                    counts["moved"] += conn.execute(
                        update(t.evidence)
                        .where(t.evidence.c.paragraph_id == old)
                        .values(paragraph_id=new)
                    ).rowcount
            for pid in payload.get("removed", []):
                counts["lost"] += self._lose_evidence(pid, "абзац удалён")
            for pid in payload.get("changed", []):
                counts["rechecked"] += 1
                text = self.paragraph_text(pid)
                with self.engine.begin() as conn:
                    rows = (
                        conn.execute(
                            select(t.evidence).where(
                                and_(t.evidence.c.paragraph_id == pid, t.evidence.c.lost.is_(False))
                            )
                        )
                        .mappings()
                        .all()
                    )
                for ev in rows:
                    if text is None or _norm_quote(ev["quote"]) not in _norm_quote(text):
                        counts["lost"] += self._lose_evidence(
                            pid, "цитата не найдена", only=ev["id"]
                        )
            self._set_source_hidden(payload["source_id"], False)
        elif kind in ("source.unpublished", "source.deleted"):
            self._set_source_hidden(payload["source_id"], True)
        with self.engine.begin() as conn:
            conn.execute(t.processed.insert().values(event_id=event_id))
        events.emit("knowledge.library.event", event_id=event_id, kind=kind, **counts)
        return counts

    def _lose_evidence(self, paragraph_id: str, reason: str, only: int | None = None) -> int:
        cond = and_(t.evidence.c.paragraph_id == paragraph_id, t.evidence.c.lost.is_(False))
        if only is not None:
            cond = and_(cond, t.evidence.c.id == only)
        with self.engine.begin() as conn:
            affected = list(conn.scalars(select(t.evidence.c.statement_id).where(cond)))
            conn.execute(update(t.evidence).where(cond).values(lost=True))
        for statement_id in set(affected):
            s = self.get(statement_id)
            if not [e for e in s["evidence"] if not e["lost"]] and s["status"] == "sourced":
                self._set_status(statement_id, "generated", reason)
            self._warn(statement_id, "evidence_lost")
        return len(affected)

    def _set_source_hidden(self, source_id: str, hidden: bool) -> None:
        with self.engine.begin() as conn:
            ids = list(
                conn.scalars(
                    select(t.attributions.c.statement_id).where(t.attributions.c.who == source_id)
                )
            )
            conn.execute(
                update(t.attributions)
                .where(t.attributions.c.who == source_id)
                .values(hidden=hidden)
            )
        for statement_id in set(ids):
            self._recompute_consensus(statement_id)
