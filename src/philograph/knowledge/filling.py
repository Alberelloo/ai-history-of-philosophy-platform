"""Наполнение онтологии: извлечение из библиотеки, ядро вручную, простые факты Wikidata.

Извлечение — основной источник утверждений (ontology.md, раздел 12). Модель получает фрагмент
главы из нескольких абзацев и возвращает утверждения по схеме из реестра; каждое — с цитатой,
которую код сверяет с абзацем. Неоднозначная привязка сущности не угадывается, а уходит на
проверку. Всё, что сделал запуск, можно откатить.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy import select, update

from philograph.knowledge import schema as t
from philograph.knowledge.dates import FuzzyDate, lifespan, parse
from philograph.knowledge.registry import RegistryError
from philograph.knowledge.statements import (
    INFLUENCE,
    Attribution,
    Evidence,
    Provenance,
    StatementError,
    Statements,
)
from philograph.platform import context, events
from philograph.platform.client import ServiceClient, ServiceUnavailable
from philograph.platform.clock import Clock, SystemClock

events.define(
    "knowledge.extraction.fragment",
    "info",
    "Фрагмент главы обработан моделью",
    required=("run_id", "paragraphs", "created", "dropped"),
)
events.define(
    "knowledge.extraction.dropped",
    "warning",
    "Утверждение модели отброшено",
    required=("run_id", "reason"),
)
events.define(
    "knowledge.extraction.skipped",
    "info",
    "Источник пропущен извлечением",
    required=("source_id", "reason"),
)
events.define(
    "knowledge.extraction.ambiguous",
    "info",
    "Неоднозначная привязка — на проверку",
    required=("name", "candidates"),
)
events.define(
    "knowledge.run.started", "info", "Запуск наполнения начат", required=("run_id", "kind")
)
events.define(
    "knowledge.run.finished",
    "info",
    "Запуск наполнения завершён",
    required=("run_id", "kind", "created", "dropped"),
)
events.define(
    "knowledge.import.skipped",
    "debug",
    "Свойство внешней базы не импортируется",
    required=("property", "reason"),
)

FRAGMENT = 4  # абзацев во фрагменте; соседние фрагменты перекрываются на один абзац
# Wikidata: только простые факты. Влияние (P737) не берём: там нет обоснований.
WIKIDATA_SIMPLE = {
    "P569": "birth",
    "P570": "death",
    "P19": "place",
    "P50": "author",
    "P1066": "teacher",
    "P577": "published",
}
WIKIDATA_SKIPPED = {"P737": "связи влияния только из библиотеки или достройкой"}


class Filling:
    def __init__(
        self,
        statements: Statements,
        llm: ServiceClient,
        library: ServiceClient,
        *,
        clock: Clock | None = None,
        fragment_size: int = FRAGMENT,
    ) -> None:
        self.statements = statements
        self.entities = statements.entities
        self.registry = statements.registry
        self.llm = llm
        self.library = library
        self.clock = clock or SystemClock()
        self.fragment_size = fragment_size
        self.created_entities: list[str] = []  # для пересчёта упоминаний новых сущностей

    # --- запуски ---

    def start_run(self, kind: str, target: str | None = None) -> str:
        run_id = context.run_id() or f"fill_{uuid.uuid4().hex[:12]}"
        with self.statements.engine.begin() as conn:
            conn.execute(
                t.filling_runs.insert().values(
                    run_id=run_id,
                    kind=kind,
                    target=target,
                    model="main",
                    template_version=None,
                    started_at=self.clock.now(),
                    created=0,
                    dropped=0,
                    status="running",
                )
            )
        events.emit("knowledge.run.started", run_id=run_id, kind=kind)
        return run_id

    def _count(self, run_id: str, created: int = 0, dropped: int = 0) -> None:
        with self.statements.engine.begin() as conn:
            row = (
                conn.execute(select(t.filling_runs).where(t.filling_runs.c.run_id == run_id))
                .mappings()
                .one()
            )
            conn.execute(
                update(t.filling_runs)
                .where(t.filling_runs.c.run_id == run_id)
                .values(created=row["created"] + created, dropped=row["dropped"] + dropped)
            )

    def finish_run(self, run_id: str) -> dict[str, Any]:
        cost = self._run_cost(run_id)
        with self.statements.engine.begin() as conn:
            conn.execute(
                update(t.filling_runs)
                .where(t.filling_runs.c.run_id == run_id)
                .values(finished_at=self.clock.now(), status="done", cost_usd=cost)
            )
            row = dict(
                conn.execute(select(t.filling_runs).where(t.filling_runs.c.run_id == run_id))
                .mappings()
                .one()
            )
        events.emit(
            "knowledge.run.finished",
            run_id=run_id,
            kind=row["kind"],
            created=row["created"],
            dropped=row["dropped"],
        )
        return row

    def _run_cost(self, run_id: str) -> float:
        response = self.llm.get("spend", params={"days": 3650, "group_by": "run_id"})
        if response.status_code != 200:
            return 0.0
        return round(
            sum(r["cost_usd"] or 0 for r in response.json() if r.get("run_id") == run_id), 6
        )

    def runs(self) -> list[dict[str, Any]]:
        with self.statements.engine.begin() as conn:
            return [dict(r) for r in conn.execute(select(t.filling_runs)).mappings()]

    def rollback(self, run_id: str) -> dict[str, int]:
        result = self.statements.rollback_run(run_id)
        with self.statements.engine.begin() as conn:
            conn.execute(
                update(t.filling_runs)
                .where(t.filling_runs.c.run_id == run_id)
                .values(status="rolled_back")
            )
        return result

    # --- извлечение ---

    def _schema(self) -> dict[str, Any]:
        schema = self.registry.output_schema()
        item = schema["properties"]["statements"]["items"]["properties"]
        types = sorted(self.registry._load()["entity_types"])
        item["subject_type"] = {"enum": types}
        item["object_type"] = {"enum": types}
        item["proposed_type"] = {"type": "string"}
        return schema

    def fragments(
        self, paragraphs: list[dict[str, Any]], changed: set[str] | None
    ) -> list[list[dict[str, Any]]]:
        by_chapter: dict[str | None, list[dict[str, Any]]] = {}
        for p in paragraphs:
            by_chapter.setdefault(p["chapter_id"], []).append(p)
        result = []
        step = max(1, self.fragment_size - 1)
        for chapter in by_chapter.values():
            for start in range(0, len(chapter), step):
                window = chapter[start : start + self.fragment_size]
                if changed is None or {p["id"] for p in window} & changed:
                    result.append(window)
                if start + self.fragment_size >= len(chapter):
                    break
        return result

    def extract_version(
        self,
        version_id: str,
        *,
        changed: list[str] | None = None,
        limit: int | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        data = self.library.get(f"internal/versions/{version_id}/paragraphs").json()
        if not data["permissions"].get("external_processing"):
            events.emit(
                "knowledge.extraction.skipped",
                source_id=data["source_id"],
                reason="external_processing_forbidden",
            )
            return {"skipped": True}
        run_id = run_id or self.start_run("extraction", version_id)
        source = self.entities.source_entity(
            data["source_id"], data.get("source_title") or data["source_id"]
        )
        paragraphs = [p for p in data["paragraphs"] if p["searchable"]]
        fragments = self.fragments(paragraphs, set(changed) if changed is not None else None)
        if limit is not None:
            fragments = fragments[:limit]
        schema = self._schema()
        with context.scope(run_id=run_id):
            for window in fragments:
                self._extract_fragment(window, data, source, schema, run_id)
        return self.finish_run(run_id)

    def _extract_fragment(
        self,
        window: list[dict[str, Any]],
        data: dict[str, Any],
        source: str,
        schema: dict[str, Any],
        run_id: str,
    ) -> None:
        passages = "\n\n".join(f"[{i + 1}] {p['text']}" for i, p in enumerate(window))
        try:
            response = self.llm.post(
                "structured",
                json={
                    "role": "main",
                    "template": "ontology.extract",
                    "caller": "knowledge",
                    "operation": "extract",
                    "budget": "filling",
                    "json_schema": schema,
                    "data": {
                        "passages": passages,
                        "section": window[0].get("section_title") or "",
                        "relations": str(schema["x-relations"]),
                        "entity_types": ", ".join(
                            schema["properties"]["statements"]["items"]["properties"][
                                "subject_type"
                            ]["enum"]
                        ),
                    },
                },
            )
        except ServiceUnavailable as exc:
            # Ответ модели не по схеме или сбой: отбрасываем фрагмент, а не весь запуск.
            self._drop(run_id, f"модель: {exc.reason}")
            self._count(run_id, dropped=1)
            return
        if response.status_code != 200:
            self._drop(run_id, f"модель: {response.json().get('kind', response.status_code)}")
            return
        created = dropped = 0
        resolved: dict[str, str] = {}
        for item in response.json()["value"]["statements"]:
            try:
                self._store(item, window, data, source, run_id, resolved)
                created += 1
            except (StatementError, RegistryError, _Skip) as exc:
                self._drop(run_id, str(exc))
                dropped += 1
        self._count(run_id, created=created, dropped=dropped)
        events.emit(
            "knowledge.extraction.fragment",
            run_id=run_id,
            paragraphs=len(window),
            created=created,
            dropped=dropped,
        )

    def _drop(self, run_id: str, reason: str) -> None:
        events.emit("knowledge.extraction.dropped", run_id=run_id, reason=reason[:300])

    def _store(
        self,
        item: dict[str, Any],
        window: list[dict[str, Any]],
        data: dict[str, Any],
        source: str,
        run_id: str,
        resolved: dict[str, str],
    ) -> str:
        number = item.get("paragraph", 0)
        if not 1 <= number <= len(window):
            raise _Skip("ссылка на абзац вне фрагмента")
        paragraph = window[number - 1]
        subject = self._resolve(item["subject"], item.get("subject_type"), resolved)
        obj = self._resolve(item["object"], item.get("object_type"), resolved)
        relation = item["type"]
        if item.get("proposed_type"):
            self.registry.propose(
                "relation", {"code": item["proposed_type"], "example": item.get("quote", "")}
            )
            relation = INFLUENCE
        relation = self._fit(relation, subject, obj)
        attributions = [Attribution("source", data["source_id"], stance="asserts")]
        if item.get("attributed_to"):
            author = self._resolve(item["attributed_to"], "person", resolved)
            attributions = [
                Attribution("entity", author, stance=item.get("stance", "asserts")),
                Attribution("source", data["source_id"], stance="mentions"),
            ]
        elif item.get("stance") in ("disputes", "mentions"):
            attributions = [Attribution("source", data["source_id"], stance=item["stance"])]
        return self.statements.add(
            subject,
            relation,
            obj=obj,
            qualifiers=item.get("qualifiers") or {},
            attributions=attributions,
            scope=data["scope"],
            evidence=[Evidence(paragraph["id"], item["quote"], source_id=data["source_id"])],
            provenance=Provenance(
                "extracted",
                run_id=run_id,
                model="main",
                template="ontology.extract",
                extra={"source": source},
            ),
        )

    def _fit(self, relation: str, subject: str, obj: str) -> str:
        """Если частный тип не подходит концам, берётся родительский — общий тип иерархии."""
        current: str | None = relation
        s_type = self.entities.get(subject)["type"]
        o_type = self.entities.get(obj)["type"]
        while current is not None:
            spec = self.registry.relation(current)
            if (
                not spec.get("deprecated_by")
                and self.registry.is_a(s_type, spec["subject_types"])
                and self.registry.is_a(o_type, spec["object_types"])
            ):
                return current
            current = spec.get("parent")
        raise _Skip(f"тип {relation} не подходит концам {s_type} → {o_type}")

    def _resolve(self, name: str, type_: str | None, resolved: dict[str, str]) -> str:
        """Существующая сущность по названию; новая — если нет; неоднозначная — на проверку."""
        if name in resolved:
            return resolved[name]
        candidates = self.entities.find(name)
        if type_:
            candidates = [c for c in candidates if self.registry.is_a(c["type"], [type_])]
        if len(candidates) == 1:
            resolved[name] = candidates[0]["id"]
            return resolved[name]
        if len(candidates) > 1:
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
            raise _Skip(f"неоднозначное название «{name}»")
        if not type_:
            raise _Skip(f"новая сущность «{name}» без типа")
        resolved[name] = self.entities.create(type_, [("ru", name, "primary")])
        self.created_entities.append(resolved[name])
        return resolved[name]

    def handle_published(self, payload: dict[str, Any]) -> None:
        """По событию публикации: извлечение только из добавленных и изменённых абзацев."""
        if not payload.get("external_processing", True):
            events.emit(
                "knowledge.extraction.skipped",
                source_id=payload["source_id"],
                reason="external_processing_forbidden",
            )
            return
        changed = list(payload.get("added", [])) + list(payload.get("changed", []))
        first = payload.get("previous_version_id") is None
        self.extract_version(payload["version_id"], changed=None if first else changed)

    def estimate(self, version_id: str, sample_fragments: int = 2) -> dict[str, Any]:
        """Проба на нескольких фрагментах: стоимость пробы и оценка полного прохода."""
        data = self.library.get(f"internal/versions/{version_id}/paragraphs").json()
        total = len(self.fragments([p for p in data["paragraphs"] if p["searchable"]], None))
        run = self.extract_version(version_id, limit=sample_fragments)
        sample_cost = float(run.get("cost_usd") or 0.0)
        per_fragment = sample_cost / max(1, min(sample_fragments, total))
        return {
            "run_id": run.get("run_id"),
            "sample_cost_usd": sample_cost,
            "fragments": total,
            "estimate_usd": round(per_fragment * total, 6),
        }

    # --- ядро вручную ---

    def propose_core(self, topic: str) -> list[dict[str, Any]]:
        types = sorted(self.registry._load()["entity_types"])
        response = self.llm.post(
            "structured",
            json={
                "role": "main",
                "template": "ontology.core_draft",
                "caller": "knowledge",
                "operation": "core_draft",
                "budget": "filling",
                "data": {"topic": topic, "entity_types": ", ".join(types)},
                "json_schema": {
                    "type": "object",
                    "required": ["items"],
                    "properties": {
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": ["name", "type"],
                                "properties": {
                                    "name": {"type": "string"},
                                    "type": {"enum": types},
                                    "note": {"type": "string"},
                                },
                            },
                        }
                    },
                },
            },
        )
        response.raise_for_status()
        return response.json()["value"]["items"]

    def accept_core(self, items: list[dict[str, Any]], actor: str) -> list[str]:
        """Принятое из черновика создаётся как ручное, с отметкой, что был черновик модели."""
        created = []
        for item in items:
            entity = self.entities.create(item["type"], [("ru", item["name"], "primary")])
            if item.get("note"):
                self.statements.add(
                    entity,
                    "description",
                    value=item["note"],
                    attributions=[Attribution("common")],
                    provenance=Provenance("manual", actor=actor, extra={"draft": "model"}),
                )
            created.append(entity)
        return created

    # --- Wikidata ---

    def import_wikidata(self, qid: str, fetch: Callable[[str], dict[str, Any]]) -> list[str]:
        """Простые факты: даты, места, авторство, учителя — со ссылкой на запись."""
        record = fetch(qid)
        label = record["labels"].get("ru") or record["labels"].get("en") or qid
        kind = "work" if "P50" in record["claims"] else "person"
        entity = self.entities.by_external("wikidata", qid) or self.entities.create(
            kind, [("ru", label, "primary")], external={"wikidata": qid}
        )
        url = f"https://www.wikidata.org/wiki/{qid}"
        attribution = [Attribution("source", f"wikidata:{qid}", place=url)]
        imported = Provenance("imported", extra={"wikidata": qid})
        created = []
        for prop in record["claims"]:
            if prop in WIKIDATA_SKIPPED:
                events.emit(
                    "knowledge.import.skipped", property=prop, reason=WIKIDATA_SKIPPED[prop]
                )
        claims = record["claims"]
        if "P569" in claims and "P570" in claims:
            span = lifespan(claims["P569"][0][1:5], claims["P570"][0][1:5])
            created.append(
                self.statements.add(
                    entity,
                    "lifespan",
                    value=span.to_json(),
                    attributions=attribution,
                    provenance=imported,
                    status="sourced",
                )
            )
        if "P577" in claims:
            dating: FuzzyDate = parse(claims["P577"][0][1:5])
            created.append(
                self.statements.add(
                    entity,
                    "dating",
                    value=dating.to_json(),
                    attributions=attribution,
                    provenance=imported,
                    status="sourced",
                )
            )
        for prop, relation, target_type in (
            ("P19", "lived_in", "place"),
            ("P1066", "studied_with", "person"),
            ("P50", "author", "person"),
        ):
            for target in claims.get(prop, []):
                target_label = fetch(target)["labels"].get("ru") or target
                other = self.entities.by_external("wikidata", target) or self.entities.create(
                    target_type, [("ru", target_label, "primary")], external={"wikidata": target}
                )
                created.append(
                    self.statements.add(
                        entity,
                        relation,
                        obj=other,
                        attributions=attribution,
                        provenance=imported,
                        status="sourced",
                    )
                )
        return created


class _Skip(Exception):
    pass
