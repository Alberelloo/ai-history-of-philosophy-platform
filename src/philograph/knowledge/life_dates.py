"""Даты жизни, датировки произведений и роли из Wikidata; подтверждение QID манифестом.

Команда оператора (спецификация entity-dating, «Даты жизни из Wikidata» и «Подтверждение
QID персон и произведений»), не путь читателя.

- ``suggest`` подбирает кандидатов QID персонам и произведениям без QID поиском Wikidata по
  основному названию и вариантам (ru и en) и пишет их в манифест ``sources/person_qids.yaml``;
  в базу не пишет. Кандидат персоны — запись класса «человек» (P31 Q5), произведения — с P577.
  Кандидат, чей QID уже у другой действующей сущности того же типа, получает ``holder``, а
  пара ставится в очередь ``duplicate`` (``review:qid_candidate``). ``--auto-exact`` ставит
  QID сам (``decision: auto``) только при одном кандидате с точной подписью и непротиворечащими
  датами.
- ``apply`` обходит записи манифеста с ``accepted``/``auto`` по порядку (правило 1–4: свой
  QID — ничего, другой — ``qid_conflict``, занят — ``qid_taken``, иначе запись), затем — с
  ``--linked`` — все персоны и произведения базы с QID. По записи Wikidata пишет годы жизни
  (P569 + P570, только обе), датировку (P577) и роли (P106 по ``WIKIDATA_ROLES``).
  Существующая дата не перезаписывается (``unchanged``/``conflict``). Пары ``qid_taken`` с
  ``accepted`` сливает ``Dedupe`` как подтверждённые человеком, с ``auto`` — в очередь.
- ``rollback <run_id>`` отменяет слияния запуска, убирает его утверждения (кроме проверенных)
  и записанные им QID (кроме тех, на которые ссылается оставшееся утверждение — ``kept``).

Время, сеть и QID — только ``knowledge/wikidata.py``; правило противоречия дат — ``dedupe``.

    python -m philograph.knowledge.life_dates suggest [--manifest M] [--auto-exact] [--limit N] [--from-file F]
    python -m philograph.knowledge.life_dates apply [--manifest M] [--linked] [--dry-run] [--limit N] [--from-file F]
    python -m philograph.knowledge.life_dates rollback <run_id>
"""  # noqa: E501

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import and_, select

from philograph.knowledge import schema as t
from philograph.knowledge.dates import FuzzyDate, interval, span
from philograph.knowledge.dedupe import Dedupe, dates_conflict, duplicate_items, propose
from philograph.knowledge.entities import EntityNotFound
from philograph.knowledge.epoch_dates import (
    FETCH_ERRORS,
    ManifestError,
    load_manifest,
    save_manifest,
)
from philograph.knowledge.geo_enrich import file_fetch
from philograph.knowledge.naming import normalize
from philograph.knowledge.statements import Attribution, Provenance, StatementError, Statements
from philograph.knowledge.wikidata import (
    HUMAN,
    INSTANCE_OF,
    QID,
    WIKIDATA_ROLES,
    Fetch,
    WikidataRecord,
    claim_date,
    fetch_entity,
    format_original,
    http_fetch,
    page_url,
    search,
)
from philograph.platform import events

events.define(
    "knowledge.life_dates.suggested",
    "info",
    "Кандидаты QID персон и произведений подобраны",
    required=("entities", "candidates", "auto"),
)
events.define(
    "knowledge.life_dates.run",
    "info",
    "Импорт дат жизни из Wikidata завершён",
    required=(
        "run_id",
        "entities",
        "externals",
        "lifespans",
        "datings",
        "roles",
        "unchanged",
        "conflicts",
        "skipped",
        "failed",
        "dry_run",
    ),
)
events.define(
    "knowledge.life_dates.skipped",
    "warning",
    "Запись Wikidata о датах пропущена",
    required=("entity", "property", "reason"),
)
events.define(
    "knowledge.life_dates.rolled_back",
    "info",
    "Запуск импорта дат жизни откачен",
    required=("run_id", "statements", "externals", "kept"),
)

SYSTEM = "wikidata"
PERSON, WORK = "person", "work"
DEFAULT_MANIFEST = Path("sources/person_qids.yaml")
DECISIONS = ("pending", "accepted", "auto", "rejected")
CONFIRMED = ("accepted", "auto")
# Читаются только эти свойства; влияния (P737) и всё прочее — нет.
PROPERTIES = {"P569": "birth", "P570": "death", "P577": "published", "P106": "occupation"}
LANGS = ("ru", "en")


# --- манифест -------------------------------------------------------------------------


def validate(manifest: dict[str, Any]) -> list[str]:
    """Проблемы формы манифеста: проверка до базы и сети."""
    entries = manifest.get("entities")
    if not isinstance(entries, list):
        return ["нет списка entities"]
    problems: list[str] = []
    seen: set[str] = set()
    for i, entry in enumerate(entries):
        where = f"entities[{i}]"
        if not isinstance(entry, dict):
            problems.append(f"{where}: не словарь")
            continue
        entity = entry.get("entity")
        if not isinstance(entity, str) or not entity.strip():
            problems.append(f"{where}: нет entity")
        elif entity in seen:
            problems.append(f"{where}: повтор entity {entity}")
        else:
            seen.add(entity)
        qid = entry.get("wikidata")
        if qid is not None and not (isinstance(qid, str) and QID.fullmatch(qid)):
            problems.append(f"{where}: wikidata не по шаблону Q<число>")
        decision = entry.get("decision", "pending")
        if decision not in DECISIONS:
            problems.append(f"{where}: decision не из {', '.join(DECISIONS)}")
        elif decision in CONFIRMED and qid is None:
            problems.append(f"{where}: decision {decision} без wikidata")
        candidates = entry.get("candidates") or []
        if not isinstance(candidates, list):
            problems.append(f"{where}: candidates — не список")
            continue
        for j, c in enumerate(candidates):
            if not isinstance(c, dict) or not (
                isinstance(c.get("qid"), str) and QID.fullmatch(c["qid"])
            ):
                problems.append(f"{where}.candidates[{j}]: qid не по шаблону")
            elif "holder" in c and not (isinstance(c["holder"], str) and c["holder"].strip()):
                problems.append(f"{where}.candidates[{j}]: holder — не id сущности")
    return problems


def check_manifest(manifest: dict[str, Any]) -> None:
    problems = validate(manifest)
    if problems:
        raise ManifestError(problems)


# --- даты записи ----------------------------------------------------------------------


class Skip(Exception):
    def __init__(self, prop: str, reason: str) -> None:
        super().__init__(reason)
        self.prop, self.reason = prop, reason


def record_dates(record: WikidataRecord, kind: str) -> FuzzyDate:
    """Годы жизни (персона) или датировка (произведение) по таблице точностей; иначе ``Skip``
    с первым неразборчивым свойством (``bad_value``), отсутствующим (``partial``) или
    ``no_dates``."""
    props = ("P569", "P570") if kind == PERSON else ("P577",)
    claims = {p: record.best(p) for p in props}
    found = {p: claim_date(c) for p, c in claims.items()}
    for p in props:
        if claims[p] is not None and found[p] is None:
            raise Skip(p, "bad_value")
    if all(found[p] is None for p in props):
        raise Skip(props[0], "no_dates")
    if kind != PERSON:
        return found["P577"]  # type: ignore[return-value]
    birth, death = found["P569"], found["P570"]
    if birth is None or death is None:
        raise Skip("P569" if birth is None else "P570", "partial")
    return interval(birth, death, format_original(birth, death))


def candidate_dates(candidate: dict[str, Any]) -> dict[str, Any] | None:
    """Датировка кандидата для сравнения с датами сущности (хранится в нём как JSON)."""
    return candidate.get("dates")


# --- отчёт ----------------------------------------------------------------------------


@dataclass
class Report:
    run_id: str
    dry_run: bool
    entities: int = 0
    externals: int = 0
    lifespans: int = 0
    datings: int = 0
    roles: int = 0
    unchanged: int = 0
    conflicts: int = 0
    skipped: int = 0
    failed: int = 0

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


class LifeDates:
    def __init__(self, statements: Statements, fetch: Fetch, review: Any = None) -> None:
        self.statements = statements
        self.entities = statements.entities
        self.registry = statements.registry
        self.engine = statements.engine
        self.fetch = fetch
        self.review = review
        self._records: dict[str, WikidataRecord | None] = {}

    # --- общее ---

    def _kind(self, entity_type: str) -> str | None:
        if self.registry.is_a(entity_type, [PERSON]):
            return PERSON
        if self.registry.is_a(entity_type, [WORK]):
            return WORK
        return None

    def _record(self, qid: str) -> WikidataRecord | None:
        if qid not in self._records:
            try:
                self._records[qid] = fetch_entity(qid, self.fetch)
            except FETCH_ERRORS:
                self._records[qid] = None
        return self._records[qid]

    # --- подбор ---

    def _targets_without_qid(self) -> list[dict[str, Any]]:
        linked = set(self.entities.externals(SYSTEM))
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(t.entities.c.id, t.entities.c.type)
                .where(t.active())
                .order_by(t.entities.c.id)
            ).all()
        return [
            self.entities.get(entity_id)
            for entity_id, type_ in rows
            if entity_id not in linked and self._kind(type_)
        ]

    def _candidate(self, record: WikidataRecord, kind: str) -> dict[str, Any] | None:
        if kind == PERSON and HUMAN not in record.items(INSTANCE_OF):
            return None
        if kind == WORK and record.best("P577") is None:
            return None
        candidate: dict[str, Any] = {
            "qid": record.qid,
            "label": {lang: record.labels[lang] for lang in LANGS if record.labels.get(lang)},
            "description": next(
                (record.descriptions[lang] for lang in LANGS if record.descriptions.get(lang)),
                None,
            ),
        }
        props = ("P569", "P570") if kind == PERSON else ("P577",)
        for prop in props:
            found = claim_date(record.best(prop))
            candidate[PROPERTIES[prop]] = found.original if found else None
        try:
            candidate["dates"] = record_dates(record, kind).to_json()
        except Skip:
            candidate["dates"] = None
        return candidate

    def _search(self, entity: dict[str, Any], kind: str) -> list[dict[str, Any]]:
        hits: list[str] = []
        texts = list(dict.fromkeys(n["text"].strip() for n in entity["names"] if n["text"]))
        for text in texts:
            for lang in LANGS:
                try:
                    found = search(text, lang, self.fetch)
                except FETCH_ERRORS:
                    continue
                hits.extend(h["id"] for h in found if h["id"] not in hits)
        candidates = []
        for qid in hits:
            record = self._record(qid)
            if record is not None and (c := self._candidate(record, kind)) is not None:
                candidates.append(c)
        return candidates

    @staticmethod
    def _exact(entity: dict[str, Any], candidates: list[dict[str, Any]]) -> bool:
        """Правило ``--auto-exact``: один кандидат, подпись ru/en равна названию или варианту,
        даты не противоречат основным датам сущности (``dedupe.dates_conflict``)."""
        if len(candidates) != 1:
            return False
        names = {normalize(n["text"]) for n in entity["names"]}
        labels = {normalize(v) for v in candidates[0]["label"].values()}
        if not names & labels:
            return False
        return not dates_conflict(entity["primary"].get("dates"), candidate_dates(candidates[0]))

    def suggest(
        self, manifest: dict[str, Any], *, auto_exact: bool = False, limit: int | None = None
    ) -> dict[str, Any]:
        """Манифест с кандидатами для персон и произведений без QID; в базу не пишет (кроме
        пункта очереди о кандидате-держателе)."""
        check_manifest(manifest)
        result = copy.deepcopy(manifest)
        entries = result["entities"]
        index = {e["entity"]: e for e in entries}
        open_, distinct = duplicate_items(self.engine)
        processed = candidates_total = auto = 0
        for entity in self._targets_without_qid():
            if limit is not None and processed >= limit:
                break
            entry = index.get(entity["id"])
            if entry is not None and (entry.get("decision", "pending") != "pending"):
                continue  # решение уже принято: подбор его не трогает
            kind = self._kind(entity["type"])
            assert kind is not None
            processed += 1
            found = self._search(entity, kind)
            for c in found:
                holder = self.entities.by_external(SYSTEM, c["qid"])
                if holder is None or holder == entity["id"]:
                    continue
                if self._kind(self.entities.get(holder)["type"]) != kind:
                    continue
                c["holder"] = holder
                pair = tuple(sorted((entity["id"], holder)))
                if pair not in distinct:
                    propose(self.engine, entity["id"], holder, "review:qid_candidate", open_)
            if entry is None:
                entry = {
                    "entity": entity["id"],
                    "label": self.entities.label(entity["id"]),
                    "type": entity["type"],
                    "wikidata": None,
                    "decision": "pending",
                    "candidates": [],
                }
                entries.append(entry)
                index[entity["id"]] = entry
            entry["candidates"] = [{k: v for k, v in c.items() if k != "dates"} for c in found]
            candidates_total += len(found)
            if auto_exact and self._exact(entity, found):
                entry["wikidata"], entry["decision"] = found[0]["qid"], "auto"
                auto += 1
        events.emit(
            "knowledge.life_dates.suggested",
            entities=processed,
            candidates=candidates_total,
            auto=auto,
        )
        return result

    # --- применение ---

    def apply(
        self,
        manifest: dict[str, Any],
        *,
        linked: bool = False,
        dry_run: bool = False,
        limit: int | None = None,
    ) -> Report:
        check_manifest(manifest)
        report = Report(run_id=f"life_{uuid.uuid4().hex[:12]}", dry_run=dry_run)
        # QID, записанные (в сухом прогоне — «записанные») этим запуском: QID → сущность и
        # сущность → QID. Второе подтверждение того же QID видит первое (правило 3).
        planned: dict[str, str] = {}
        planned_own: dict[str, str] = {}
        confirmed: list[tuple[str, str]] = []
        proposals: list[tuple[str, str]] = []
        done: set[str] = set()
        seq = 0
        for entry in manifest["entities"]:
            if entry.get("decision") not in CONFIRMED or not entry.get("wikidata"):
                continue
            if limit is not None and report.entities >= limit:
                break
            qid = entry["wikidata"]
            try:
                entity_id = self.entities.get(entry["entity"])["id"]
            except EntityNotFound:
                self._skip(report, entry["entity"], SYSTEM, "refused")
                continue
            report.entities += 1
            done.add(entity_id)
            own = planned_own.get(entity_id) or self.entities.external_of(entity_id, SYSTEM)
            if own is not None and own != qid:
                self._skip(report, entity_id, SYSTEM, "qid_conflict")
                continue
            if own is None:
                holder = planned.get(qid) or self.entities.by_external(SYSTEM, qid)
                if holder is not None and holder != entity_id:
                    self._skip(report, entity_id, SYSTEM, "qid_taken")
                    pair = (entity_id, holder)
                    (confirmed if entry["decision"] == "accepted" else proposals).append(pair)
                    continue
                if not dry_run:
                    self.entities.add_external(entity_id, SYSTEM, qid)
                    seq += 1
                    self._action(report.run_id, seq, entity_id, qid)
                planned[qid], planned_own[entity_id] = entity_id, qid
                report.externals += 1
            self._import(report, entity_id, qid)
        if linked:
            for entity_id, qid in sorted(self.entities.externals(SYSTEM).items()):
                if limit is not None and report.entities >= limit:
                    break
                if entity_id in done:
                    continue
                kinds = self.entities.types([entity_id])
                if self._kind(kinds.get(entity_id, "")) is None:
                    continue
                report.entities += 1
                done.add(entity_id)
                if not QID.fullmatch(qid):
                    self._skip(report, entity_id, "item", "bad_qid")
                    continue
                self._import(report, entity_id, qid)
        self._settle(report, confirmed, proposals)
        summary = report.to_json()
        events.emit("knowledge.life_dates.run", **summary)
        return report

    def _settle(
        self,
        report: Report,
        confirmed: list[tuple[str, str]],
        proposals: list[tuple[str, str]],
    ) -> None:
        """Пары ``qid_taken``: подтверждённые человеком — слиянию вариантов
        (``merge:qid_confirmed``), прочие и не персоны — в очередь ``review:qid_taken``."""
        types = self.entities.types([x for pair in [*confirmed, *proposals] for x in pair])
        persons = [p for p in confirmed if all(types.get(x) == PERSON for x in p)]
        queued = proposals + [p for p in confirmed if p not in persons]
        if report.dry_run:
            if persons:
                Dedupe(self.statements, self.review).plan(persons, scope={*sum(persons, ())})
            return
        if persons:
            Dedupe(self.statements, self.review).run(
                confirmed=persons, run_id=report.run_id, scope={*sum(persons, ())}
            )
        open_, _ = duplicate_items(self.engine)
        for a, b in queued:
            propose(self.engine, a, b, "review:qid_taken", open_)

    def _action(self, run_id: str, seq: int, entity_id: str, qid: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                t.run_actions.insert().values(
                    run_id=run_id,
                    seq=seq,
                    kind="external",
                    payload={"kind": "external", "entity": entity_id, "qid": qid},
                    created_at=datetime.now(UTC),
                )
            )

    def _skip(self, report: Report, entity_id: str, prop: str, reason: str) -> None:
        if reason == "fetch_failed":
            report.failed += 1
        else:
            report.skipped += 1
        if reason == "conflict":
            report.conflicts += 1
        events.emit("knowledge.life_dates.skipped", entity=entity_id, property=prop, reason=reason)

    def _import(self, report: Report, entity_id: str, qid: str) -> None:
        record = self._record(qid)
        if record is None:
            self._skip(report, entity_id, "item", "fetch_failed")
            return
        kind = self._kind(self.entities.get(entity_id)["type"])
        assert kind is not None
        type_ = "lifespan" if kind == PERSON else "dating"
        prop = "P569,P570" if kind == PERSON else "P577"
        try:
            dates = record_dates(record, kind)
        except Skip as skip:
            self._skip(report, entity_id, skip.prop, skip.reason)
        else:
            self._dates(report, entity_id, record.qid, type_, prop, dates)
        if kind == PERSON:
            roles = sorted({WIKIDATA_ROLES[q] for q in record.items("P106") if q in WIKIDATA_ROLES})
            for role in roles:
                try:
                    written = self._write(
                        report, entity_id, "person_role", role, record.qid, "P106"
                    )
                except Skip as skip:
                    self._skip(report, entity_id, skip.prop, skip.reason)
                    continue
                report.roles += int(written)

    def _dates(
        self,
        report: Report,
        entity_id: str,
        qid: str,
        type_: str,
        prop: str,
        dates: FuzzyDate,
    ) -> None:
        existing = [
            s
            for s in self.statements.about(entity_id, types=[type_], derived=False)
            if s["type"] == type_ and s["subject"] == entity_id and isinstance(s["value"], dict)
        ]
        if existing:
            if any(span(s["value"]) == span(dates) for s in existing):
                report.unchanged += 1
            else:
                self._skip(report, entity_id, prop.split(",")[0], "conflict")
            return
        try:
            written = self._write(report, entity_id, type_, dates.to_json(), qid, prop)
        except Skip as skip:
            self._skip(report, entity_id, skip.prop, skip.reason)
            return
        if type_ == "lifespan":
            report.lifespans += int(written)
        else:
            report.datings += int(written)

    def _write(
        self, report: Report, entity_id: str, type_: str, value: Any, qid: str, prop: str
    ) -> bool:
        """Новое утверждение (``True``) или уже было (``False``); отказ — ``Skip(refused)``."""
        attributions = [Attribution("source", f"{SYSTEM}:{qid}", place=page_url(qid))]
        try:
            stored = self.statements.check_value(type_, value, {}, attributions, emit=True)
            if self.statements.find(entity_id, type_, value=stored, qualifiers={}):
                return False
            if not report.dry_run:
                self.statements.add(
                    entity_id,
                    type_,
                    value=value,
                    qualifiers={},
                    attributions=attributions,
                    provenance=Provenance(
                        "imported",
                        run_id=report.run_id,
                        extra={"wikidata": qid, "property": prop},
                    ),
                    status="sourced",
                )
        except StatementError:
            raise Skip(prop.split(",")[0], "refused") from None
        return True

    # --- откат ---

    def rollback(self, run_id: str) -> dict[str, Any]:
        with self.engine.begin() as conn:
            merges = conn.execute(
                select(t.merges.c.id, t.merges.c.moved)
                .where(t.merges.c.undone.is_(False))
                .order_by(t.merges.c.id.desc())
            ).all()
            actions = conn.execute(
                select(t.run_actions.c.payload)
                .where(and_(t.run_actions.c.run_id == run_id, t.run_actions.c.kind == "external"))
                .order_by(t.run_actions.c.seq.desc())
            ).all()
        for merge_id, moved in merges:
            if (moved or {}).get("run_id") == run_id:
                self.statements.undo_merge(merge_id)
        # QID, на который ссылается оставшееся утверждение (проверенное этого запуска или
        # любое другого), остаётся: считается до удаления атрибуций запуска.
        kept = {
            (a["entity"], a["qid"])
            for (a,) in actions
            if self._referenced(a["entity"], a["qid"], run_id)
        }
        removed = self.statements.rollback_run(run_id)["statements"]
        externals = 0
        for (a,) in actions:
            if (a["entity"], a["qid"]) in kept:
                continue
            externals += int(self.entities.remove_external(a["entity"], SYSTEM, a["qid"]))
        summary = {
            "run_id": run_id,
            "statements": removed,
            "externals": externals,
            "kept": len(kept),
        }
        events.emit("knowledge.life_dates.rolled_back", **summary)
        return summary

    def _referenced(self, entity_id: str, qid: str, run_id: str) -> bool:
        entity_id = self.entities.resolve(entity_id)
        s, a = t.statements, t.attributions
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(s.c.status, s.c.provenance)
                .join(a, a.c.statement_id == s.c.id)
                .where(and_(s.c.subject == entity_id, a.c.who == f"{SYSTEM}:{qid}"))
            ).all()
        return any(
            status == "verified" or (provenance or {}).get("run_id") != run_id
            for status, provenance in rows
        )


# --- CLI ------------------------------------------------------------------------------


def _service(fetch: Fetch) -> LifeDates:
    from philograph.knowledge import schema
    from philograph.knowledge.entities import Entities
    from philograph.knowledge.registry import OntologyRegistry
    from philograph.platform.db import make_engine

    engine = make_engine(os.environ["PHILOGRAPH_DATABASE_URL"], [schema.SCHEMA])
    schema.migrations.upgrade(engine)
    registry = OntologyRegistry(engine)
    registry.load_defaults()
    entities = Entities(engine, registry)
    # Импорт пишет только факты с атрибуцией Wikidata: цитат нет, абзацы не нужны.
    return LifeDates(Statements(engine, registry, entities, lambda _: None), fetch)


def main(
    argv: list[str] | None = None,
    *,
    fetch: Fetch | None = None,
    service: Callable[[Fetch], LifeDates] = _service,
) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        prog="python -m philograph.knowledge.life_dates",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("suggest", help="подобрать кандидатов QID в манифест")
    p.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    p.add_argument("--auto-exact", action="store_true", help="ставить QID при точном совпадении")
    p.add_argument("--limit", type=int, default=None, help="не больше N сущностей")
    p.add_argument("--from-file", type=Path, default=None, help="записи из файла, без сети")
    p = sub.add_parser("apply", help="записать QID, даты и роли из Wikidata")
    p.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    p.add_argument("--linked", action="store_true", help="и все персоны и произведения с QID")
    p.add_argument("--dry-run", action="store_true", help="посчитать, ничего не записывая")
    p.add_argument("--limit", type=int, default=None, help="не больше N сущностей")
    p.add_argument("--from-file", type=Path, default=None, help="записи из файла, без сети")
    p = sub.add_parser("rollback", help="откатить запуск")
    p.add_argument("run_id")
    args = parser.parse_args(argv)

    manifest: dict[str, Any] = {}
    if args.command in ("suggest", "apply"):
        try:
            manifest = load_manifest(args.manifest)
            check_manifest(manifest)  # до базы и сети
        except (ManifestError, yaml.YAMLError, OSError) as exc:
            print(f"манифест {args.manifest}: {exc}", file=sys.stderr)
            return 2
        if args.from_file is not None:
            try:
                fetch = file_fetch(args.from_file)
            except (OSError, ValueError) as exc:
                print(f"файл записей: {exc}", file=sys.stderr)
                return 2
    fetch = fetch or partial(http_fetch, wait=time.sleep)
    command = service(fetch)
    if args.command == "suggest":
        updated = command.suggest(manifest, auto_exact=args.auto_exact, limit=args.limit)
        save_manifest(updated, args.manifest)
        print(json.dumps({"entities": updated["entities"]}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "apply":
        report = command.apply(manifest, linked=args.linked, dry_run=args.dry_run, limit=args.limit)
        print(json.dumps(report.to_json(), ensure_ascii=False, indent=2))
        return 0
    print(json.dumps(command.rollback(args.run_id), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
