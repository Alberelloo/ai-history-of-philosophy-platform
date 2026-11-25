"""Миграция существующей онтологии (спецификация ontology-migration): язык, мусор, русские
названия, дубли персон — без удаления сущностей и утверждений, с откатом по запуску.

Шаги — данные ``STEPS``, по порядку спецификации. У каждого шага есть планировщик
``plan(view) → [Action]`` над проекцией ``View`` (сущности, названия, QID, снятые — в памяти)
и запись действия в базу. Сухой прогон (``plan``) применяет действия только к проекции:
база не меняется, модель не вызывается (кроме одной пробы ``--estimate``). Настоящий запуск
(``run``) выполняет те же действия и пишет каждое в журнал действий запуска ``run_actions``;
``rollback`` отменяет их в обратном порядке.

1. ``manifest_qids`` — решения манифеста QID (``LifeDates.apply`` с общим ``run_id``); пары
   ``qid_taken`` с ``accepted`` — шагу ``dedupe`` как подтверждённые, ``pending`` с держателем
   — в очередь ``review:qid_candidate``.
2. ``lang_fix`` — язык названия по письменности (``naming.lang_for``).
3. ``retire`` — снятие сущности (кроме источников), чья подпись не проходит правило названий.
4. ``wikidata_labels`` — подпись ``ru`` записи Wikidata основным названием.
5. ``translate`` — перевод моделью пакетами, только при ``translate="model"``.
6. ``dedupe`` — слияние вариантов персон (``dedupe.plan``); совпадения основных названий у
   не-персон одного типа — в очередь (``review:same_name``).
7. ``verify`` — ``integrity.compare``: потеря — аварийный откат (код 1).

В событиях — только идентификаторы, коды и числа; названия видны лишь в отчёте JSON.

    python -m philograph.knowledge.ontology_migrate plan [--manifest M] [--from-file WD] [--estimate] [--batch 50] [--limit N]
    python -m philograph.knowledge.ontology_migrate run [--manifest M] [--translate off|model] [--from-file WD] [--batch 50] [--limit N]
    python -m philograph.knowledge.ontology_migrate rollback <run_id>
"""  # noqa: E501

from __future__ import annotations

import argparse
import copy
import json
import math
import os
import sys
import time
import uuid
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial
from itertools import combinations
from pathlib import Path
from typing import Any

import httpx
import yaml
from sqlalchemy import and_, delete, select, update

from philograph.knowledge import dedupe, integrity, run_actions
from philograph.knowledge import schema as t
from philograph.knowledge.epoch_dates import ManifestError, load_manifest
from philograph.knowledge.geo_enrich import file_fetch
from philograph.knowledge.life_dates import LifeDates, check_manifest
from philograph.knowledge.naming import check_name, is_russian, lang_for, normalize, script_of
from philograph.knowledge.snapshot import label_of
from philograph.knowledge.statements import Statements
from philograph.knowledge.wikidata import Fetch, WikidataError, fetch_entity, http_fetch
from philograph.platform import context, events
from philograph.platform.client import ServiceClient, ServiceUnavailable

events.define(
    "knowledge.migration.step",
    "info",
    "Шаг миграции онтологии",
    required=("run_id", "step", "actions", "dry_run"),
)
events.define(
    "knowledge.migration.translated",
    "info",
    "Пакет перевода названий проверен",
    required=("run_id", "batch", "accepted", "rejected"),
)
events.define(
    "knowledge.migration.run",
    "info",
    "Миграция онтологии завершена",
    required=(
        "run_id",
        "dry_run",
        "translate",
        "retired",
        "renamed_wikidata",
        "renamed_model",
        "merged",
        "folded",
        "review",
        "statements_before",
        "statements_after",
        "lost",
        "a1_before",
        "a1_after",
    ),
)
events.define(
    "knowledge.migration.aborted",
    "error",
    "Миграция потеряла утверждения и откачена",
    required=("run_id", "lost", "lost_attributions"),
)
events.define(
    "knowledge.migration.rolled_back",
    "info",
    "Запуск миграции откачен",
    required=("run_id", "actions", "merges_undone", "restored", "kept"),
)
events.define(
    "knowledge.entity.retired",
    "info",
    "Сущность снята миграцией",
    required=("entity_id", "type", "reason", "run_id"),
)
events.define(
    "knowledge.entity.restored",
    "info",
    "Снятая сущность возвращена",
    required=("entity_id", "run_id"),
)

STEPS = ("manifest_qids", "lang_fix", "retire", "wikidata_labels", "translate", "dedupe", "verify")
SOURCE = "source"
PERSON = "person"
QID_SYSTEM = "wikidata"
SAME_NAME = "review:same_name"  # совпали основные названия у не-персон одного типа
DEFAULT_BATCH = 50
FETCH_ERRORS = (WikidataError, httpx.HTTPError, KeyError, ValueError, TypeError)
REASONS = ("unknown_item", "duplicate_item", "not_russian")
TRANSLATION_SCHEMA = {
    "type": "object",
    "required": ["translations"],
    "properties": {
        "translations": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["n", "ru"],
                "properties": {"n": {"type": "integer"}, "ru": {"type": "string"}},
            },
        }
    },
}


class Aborted(Exception):
    """Проверка сохранности нашла потери: запуск откачен."""

    def __init__(self, report: Report) -> None:
        super().__init__("потеряны утверждения или атрибуции")
        self.report = report


@dataclass(frozen=True)
class Action:
    step: str
    kind: str
    payload: dict[str, Any]

    def to_json(self) -> dict[str, Any]:
        return {"step": self.step, "kind": self.kind, **self.payload}


# --- проекция -------------------------------------------------------------------------


@dataclass
class View:
    """Проекция онтологии в памяти: действующие сущности с названиями, QID и датами."""

    entities: dict[str, dict[str, Any]]  # id → {type, names: [строки names], qid, dates}
    retired: dict[str, str] = field(default_factory=dict)  # id → причина
    redirect: dict[str, str] = field(default_factory=dict)  # слито: removed → kept

    @classmethod
    def load(cls, engine: Any) -> View:
        with engine.begin() as conn:
            rows = conn.execute(select(t.entities).where(t.active())).mappings().all()
            names: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for r in conn.execute(select(t.names).order_by(t.names.c.id)).mappings():
                names[r["entity_id"]].append(dict(r))
            qids = dict(
                conn.execute(
                    select(t.external_ids.c.entity_id, t.external_ids.c.value)
                    .where(t.external_ids.c.system == QID_SYSTEM)
                    .order_by(t.external_ids.c.value.desc())
                ).all()
            )
        return cls(
            entities={
                r["id"]: {
                    "type": r["type"],
                    "names": names.get(r["id"], []),
                    "qid": qids.get(r["id"]),
                    "dates": (r["primary"] or {}).get("dates"),
                }
                for r in rows
            }
        )

    def active(self) -> list[str]:
        return sorted(e for e in self.entities if e not in self.retired and e not in self.redirect)

    def label(self, entity_id: str) -> str:
        return label_of(self.entities[entity_id]["names"], entity_id)

    def apply(self, action: Action) -> None:
        p = action.payload
        if action.kind == "lang":
            for n in self.entities[p["entity"]]["names"]:
                if n["id"] == p["name_id"]:
                    n["lang"] = p["lang"]
        elif action.kind == "retire":
            self.retired[p["entity"]] = p["reason"]
        elif action.kind == "rename":
            _rename_names(self.entities[p["entity"]]["names"], p["lang"], p["text"])
        elif action.kind == "external":
            self.entities[p["entity"]]["qid"] = p["qid"]
        elif action.kind == "merge":
            kept, removed = self.entities[p["kept"]], self.entities[p["removed"]]
            # Правило ``Entities.merge``: названия удалённой переходят оставшейся, основное
            # одно — русское основное любой из сторон (сначала оставшейся), иначе оставшейся.
            primaries = [n for n in kept["names"] + removed["names"] if n["kind"] == "primary"]
            chosen = ([n for n in primaries if is_russian(n["text"])] or primaries or [None])[0]
            seen = {(n["lang"], normalize(n["text"])) for n in kept["names"]}
            moved = []
            for n in removed["names"]:
                n = dict(n)
                if (n["lang"], normalize(n["text"])) in seen and n is not chosen:
                    n["kind"] = "variant"
                moved.append(n)
            if chosen is not None and chosen in removed["names"]:
                chosen = moved[removed["names"].index(chosen)]
            for n in kept["names"] + moved:
                if n["kind"] == "primary" and n is not chosen:
                    n["kind"] = "variant"
            kept["names"] = kept["names"] + moved
            kept["qid"] = kept["qid"] or removed["qid"]
            kept["dates"] = kept["dates"] or removed["dates"]
            self.redirect[p["removed"]] = p["kept"]

    def persons(self) -> list[dedupe.Entity]:
        return [
            dedupe.Entity(
                id=e,
                type=self.entities[e]["type"],
                names=tuple(
                    sorted((n["kind"], normalize(n["text"])) for n in self.entities[e]["names"])
                ),
                dates=self.entities[e]["dates"],
                qid=self.entities[e]["qid"],
            )
            for e in self.active()
            if self.entities[e]["type"] == PERSON
        ]


def _rename_names(names: list[dict[str, Any]], lang: str, text: str) -> None:
    """Правило ``Entities.set_primary_name`` в проекции: прежние основные — варианты."""
    key = normalize(text)
    for n in names:
        if n["kind"] == "primary":
            n["kind"], n["lang"] = "variant", lang_for(n["text"], n["lang"])
    same = next((n for n in names if n["normalized"] == key), None)
    if same is not None:
        same.update(kind="primary", lang=lang_for(text, lang), text=text)
    else:
        names.append(
            {
                "id": None,
                "lang": lang_for(text, lang),
                "text": text,
                "normalized": key,
                "kind": "primary",
            }
        )


def a1(view: View) -> float:
    """Доля действующих сущностей, кроме источников, с русской подписью (А1)."""
    ids = [e for e in view.active() if view.entities[e]["type"] != SOURCE]
    if not ids:
        return 1.0
    return round(sum(is_russian(view.label(e)) for e in ids) / len(ids), 4)


# --- отчёт ----------------------------------------------------------------------------


@dataclass
class Report:
    run_id: str
    dry_run: bool
    translate: str
    lang_fixed: int = 0
    retired: Counter[str] = field(default_factory=Counter)
    retired_list: list[dict[str, Any]] = field(default_factory=list)
    renamed: Counter[str] = field(default_factory=lambda: Counter({"wikidata": 0, "model": 0}))
    renamed_list: list[dict[str, Any]] = field(default_factory=list)
    untranslated: Counter[str] = field(default_factory=Counter)
    to_translate: int = 0
    batches: int = 0
    failed_batches: int = 0
    externals: int = 0
    merged: int = 0
    folded: int = 0
    review: int = 0
    statements: dict[str, int] = field(default_factory=dict)
    attributions: dict[str, int] = field(default_factory=dict)
    a1: dict[str, float] = field(default_factory=dict)
    estimate_usd: float | None = None
    steps: dict[str, int] = field(default_factory=dict)
    actions: list[Action] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "dry_run": self.dry_run,
            "translate": self.translate,
            "steps": {s: self.steps.get(s, 0) for s in STEPS},
            "lang_fixed": self.lang_fixed,
            "retired": dict(sorted(self.retired.items())),
            "retired_list": self.retired_list,
            "renamed": dict(self.renamed),
            "renamed_list": self.renamed_list,
            "untranslated": dict(sorted(self.untranslated.items())),
            "to_translate": self.to_translate,
            "batches": self.batches,
            "failed_batches": self.failed_batches,
            "externals": self.externals,
            "merged": self.merged,
            "folded": self.folded,
            "review": self.review,
            "statements": self.statements,
            "attributions": self.attributions,
            "a1": self.a1,
            "estimate_usd": self.estimate_usd,
        }


# --- миграция -------------------------------------------------------------------------


class Migration:
    def __init__(
        self,
        statements: Statements,
        review: Any = None,
        fetch: Fetch | None = None,
        llm: ServiceClient | None = None,
    ) -> None:
        self.statements = statements
        self.entities = statements.entities
        self.engine = statements.engine
        self.review = review
        self.fetch = fetch
        self.llm = llm

    # --- общий проход ---

    def plan(
        self,
        *,
        manifest: dict[str, Any] | None = None,
        estimate: bool = False,
        batch: int = DEFAULT_BATCH,
        limit: int | None = None,
    ) -> Report:
        """Сухой прогон: тот же отчёт без записи в базу и без модели (кроме ``estimate``)."""
        return self._pass(
            dry_run=True,
            translate="off",
            manifest=manifest,
            batch=batch,
            limit=limit,
            estimate=estimate,
        )

    def run(
        self,
        *,
        manifest: dict[str, Any] | None = None,
        translate: str = "off",
        batch: int = DEFAULT_BATCH,
        limit: int | None = None,
    ) -> Report:
        """Запуск; потеря утверждений или атрибуций — откат и ``Aborted``."""
        if translate not in ("off", "model"):
            raise ValueError("translate: off | model")
        return self._pass(
            dry_run=False, translate=translate, manifest=manifest, batch=batch, limit=limit
        )

    def _pass(
        self,
        *,
        dry_run: bool,
        translate: str,
        manifest: dict[str, Any] | None,
        batch: int,
        limit: int | None,
        estimate: bool = False,
    ) -> Report:
        if manifest is not None:
            check_manifest(manifest)
        if batch < 1:
            raise ValueError("batch ≥ 1")
        report = Report(run_id=f"mig_{uuid.uuid4().hex[:12]}", dry_run=dry_run, translate=translate)
        base = integrity.baseline(self.engine)
        view = View.load(self.engine)
        report.statements = {"before": len(base.statements)}
        report.attributions = {"before": sum(sum(c.values()) for c in base.attributions.values())}
        report.a1["before"] = a1(view)
        confirmed: list[tuple[str, str]] = []
        for step in STEPS:
            if step == "verify":
                continue
            found = getattr(self, f"_step_{step}")(
                view,
                report,
                manifest=manifest,
                translate=translate,
                batch=batch,
                limit=limit,
                estimate=estimate,
                confirmed=confirmed,
            )
            for action in found:
                view.apply(action)
            report.steps[step] = len(found)
            report.actions.extend(found)
            events.emit(
                "knowledge.migration.step",
                run_id=report.run_id,
                step=step,
                actions=len(found),
                dry_run=dry_run,
            )
        self._verify(report, base, view)
        report.steps["verify"] = 0
        events.emit(
            "knowledge.migration.step",
            run_id=report.run_id,
            step="verify",
            actions=0,
            dry_run=dry_run,
        )
        if report.statements.get("lost") or report.attributions.get("lost"):
            self._abort(report)
        self._emit_run(report)
        return report

    def _emit_run(self, report: Report) -> None:
        events.emit(
            "knowledge.migration.run",
            run_id=report.run_id,
            dry_run=report.dry_run,
            translate=report.translate,
            retired=sum(report.retired.values()),
            renamed_wikidata=report.renamed["wikidata"],
            renamed_model=report.renamed["model"],
            merged=report.merged,
            folded=report.folded,
            review=report.review,
            statements_before=report.statements["before"],
            statements_after=report.statements["after"],
            lost=report.statements["lost"],
            a1_before=report.a1["before"],
            a1_after=report.a1["after"],
        )

    def _record(self, report: Report, action: Action) -> None:
        if not report.dry_run:
            run_actions.record(self.engine, report.run_id, action.kind, action.to_json())

    # --- шаги ---

    def _step_manifest_qids(
        self, view: View, report: Report, *, manifest, confirmed, **_: Any
    ) -> list[Action]:
        if manifest is None:
            return []
        life = LifeDates(self.statements, self.fetch or _no_fetch, self.review)
        result = life.apply(manifest, dry_run=report.dry_run, run_id=report.run_id, merge=False)
        confirmed.extend(result.confirmed)
        report.externals = result.externals
        found = [Action("manifest_qids", "external", dict(x)) for x in result.externals_list]
        # Записи без решения, у кандидата которых есть держатель, — в очередь.
        open_, distinct = dedupe.duplicate_items(self.engine)
        for entry in manifest["entities"]:
            if entry.get("decision", "pending") != "pending":
                continue
            for c in entry.get("candidates") or []:
                holder = c.get("holder")
                if (
                    not holder
                    or holder not in view.entities
                    or entry["entity"] not in view.entities
                ):
                    continue
                pair = tuple(sorted((entry["entity"], holder)))
                if pair in open_ or pair in distinct:
                    continue
                report.review += 1
                if report.dry_run:
                    open_.add(pair)
                else:
                    dedupe.propose(
                        self.engine,
                        entry["entity"],
                        holder,
                        "review:qid_candidate",
                        open_,
                        run_id=report.run_id,
                    )
        return found

    def _step_lang_fix(self, view: View, report: Report, **_: Any) -> list[Action]:
        found = []
        for entity_id in view.active():
            for n in view.entities[entity_id]["names"]:
                lang = lang_for(n["text"], n["lang"])
                if script_of(n["text"]) is None or lang == n["lang"]:
                    continue
                action = Action(
                    "lang_fix",
                    "lang",
                    {"entity": entity_id, "name_id": n["id"], "old_lang": n["lang"], "lang": lang},
                )
                if not report.dry_run:
                    with self.engine.begin() as conn:
                        conn.execute(
                            update(t.names).where(t.names.c.id == n["id"]).values(lang=lang)
                        )
                self._record(report, action)
                found.append(action)
        report.lang_fixed = len(found)
        return found

    def _step_retire(self, view: View, report: Report, **_: Any) -> list[Action]:
        found = []
        for entity_id in view.active():
            type_ = view.entities[entity_id]["type"]
            if type_ == SOURCE:
                continue
            label = view.label(entity_id)
            reason = check_name(type_, label)
            if reason is None:
                continue
            action = Action(
                "retire", "retire", {"entity": entity_id, "type": type_, "reason": reason}
            )
            if not report.dry_run:
                with self.engine.begin() as conn:
                    conn.execute(
                        update(t.entities)
                        .where(t.entities.c.id == entity_id)
                        .values(retired_run=report.run_id, retired_reason=reason)
                    )
                events.emit(
                    "knowledge.entity.retired",
                    entity_id=entity_id,
                    type=type_,
                    reason=reason,
                    run_id=report.run_id,
                )
            self._record(report, action)
            report.retired[reason] += 1
            report.retired_list.append(
                {"id": entity_id, "type": type_, "label": label, "reason": reason}
            )
            found.append(action)
        return found

    def _not_russian(self, view: View) -> list[str]:
        return [
            e
            for e in view.active()
            if view.entities[e]["type"] != SOURCE and not is_russian(view.label(e))
        ]

    def _rename(
        self, view: View, report: Report, step: str, entity_id: str, text: str, by: str
    ) -> Action:
        before = [dict(n) for n in view.entities[entity_id]["names"]]
        old = view.label(entity_id)
        if not report.dry_run:
            with self.engine.begin() as conn:
                before = [
                    dict(r)
                    for r in conn.execute(
                        select(t.names)
                        .where(t.names.c.entity_id == entity_id)
                        .order_by(t.names.c.id)
                    ).mappings()
                ]
            self.entities.set_primary_name(entity_id, "ru", text)
        action = Action(step, "rename", {"entity": entity_id, "lang": "ru", "text": text, "by": by})
        if not report.dry_run:
            run_actions.record(
                self.engine,
                report.run_id,
                action.kind,
                {**action.to_json(), "names_before": [_name_json(n) for n in before]},
            )
        report.renamed[by] += 1
        report.renamed_list.append({"id": entity_id, "from": old, "to": text, "by": by})
        return action

    def _step_wikidata_labels(self, view: View, report: Report, **_: Any) -> list[Action]:
        if self.fetch is None:
            return []
        found = []
        for entity_id in self._not_russian(view):
            qid = view.entities[entity_id]["qid"]
            if not qid:
                continue
            try:
                record = fetch_entity(qid, self.fetch)
            except FETCH_ERRORS:
                continue
            ru = (record.labels.get("ru") or "").strip()
            type_ = view.entities[entity_id]["type"]
            if not ru or not is_russian(ru) or check_name(type_, ru) is not None:
                continue
            found.append(self._rename(view, report, "wikidata_labels", entity_id, ru, "wikidata"))
        return found

    def _step_translate(
        self, view: View, report: Report, *, translate, batch, limit, estimate, **_: Any
    ) -> list[Action]:
        todo = self._not_russian(view)
        if limit is not None:
            todo = todo[:limit]
        report.to_translate = len(todo)
        report.batches = math.ceil(len(todo) / batch) if todo else 0
        packs = [todo[i : i + batch] for i in range(0, len(todo), batch)]
        if estimate and packs and self.llm is not None:
            reply = self._ask(report, 1, packs[0], view)
            cost = self._run_cost(report.run_id)
            report.estimate_usd = round(cost * report.batches, 6) if reply is not None else None
            if reply is not None:
                self._check(report, 1, packs[0], view, reply)  # счёт причин; не записывается
            return []
        if translate != "model" or self.llm is None or report.dry_run:
            return []
        found = []
        for number, pack in enumerate(packs, start=1):
            reply = self._ask(report, number, pack, view)
            if reply is None:
                report.failed_batches += 1
                continue
            for entity_id, ru in self._check(report, number, pack, view, reply):
                found.append(self._rename(view, report, "translate", entity_id, ru, "model"))
        return found

    def _ask(self, report: Report, number: int, pack: list[str], view: View) -> list | None:
        items = [
            {"n": i, "type": view.entities[e]["type"], "label": view.label(e)}
            for i, e in enumerate(pack, start=1)
        ]
        assert self.llm is not None
        try:
            with context.scope(run_id=report.run_id):
                response = self.llm.post(
                    "structured",
                    json={
                        "role": "main",
                        "template": "ontology.translate_names",
                        "caller": "knowledge",
                        "operation": "translate_names",
                        "budget": "filling",
                        "json_schema": TRANSLATION_SCHEMA,
                        "data": {"items": json.dumps(items, ensure_ascii=False)},
                    },
                )
        except ServiceUnavailable:
            return None
        if response.status_code != 200:
            return None
        value = response.json().get("value") or {}
        translations = value.get("translations")
        return translations if isinstance(translations, list) else None

    def _check(
        self, report: Report, number: int, pack: list[str], view: View, reply: list
    ) -> list[tuple[str, str]]:
        """Проверка ответа по порядку спецификации; принятые (сущность, название)."""
        counts = Counter(p.get("n") for p in reply if isinstance(p, dict))
        accepted: list[tuple[str, str]] = []
        rejected = 0
        proposed: set[int] = set()
        for p in reply:
            n = p.get("n") if isinstance(p, dict) else None
            ru = p.get("ru") if isinstance(p, dict) else None
            if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= len(pack):
                reason = "unknown_item"
            else:
                proposed.add(n)
                type_ = view.entities[pack[n - 1]]["type"]
                if counts[n] > 1:
                    reason = "duplicate_item"
                elif not isinstance(ru, str) or not is_russian(ru):
                    reason = "not_russian"
                elif (bad := check_name(type_, ru)) is not None:
                    reason = f"invalid:{bad}"
                else:
                    accepted.append((pack[n - 1], ru.strip()))
                    continue
            report.untranslated[reason] += 1
            rejected += 1
        report.untranslated["missing"] += len(pack) - len(proposed)
        events.emit(
            "knowledge.migration.translated",
            run_id=report.run_id,
            batch=number,
            accepted=len(accepted),
            rejected=rejected,
        )
        return accepted

    def _run_cost(self, run_id: str) -> float:
        assert self.llm is not None
        try:
            response = self.llm.get("spend", params={"days": 3650, "group_by": "run_id"})
        except ServiceUnavailable:
            return 0.0
        if response.status_code != 200:
            return 0.0
        return round(
            sum(r.get("cost_usd") or 0 for r in response.json() if r.get("run_id") == run_id), 6
        )

    def _step_dedupe(self, view: View, report: Report, *, confirmed, **_: Any) -> list[Action]:
        confirmed = [(view.redirect.get(a, a), view.redirect.get(b, b)) for a, b in confirmed]
        open_, distinct = dedupe.duplicate_items(self.engine)
        persons = view.persons()
        counts = dedupe.link_counts(self.engine, [p.id for p in persons])
        result = dedupe.plan(persons, confirmed=confirmed, distinct=distinct, counts=counts)
        found = []
        for kept, removed, reason in result.merges:
            for other in removed:
                action = Action(
                    "dedupe", "merge", {"kept": kept, "removed": other, "reason": reason}
                )
                if not report.dry_run:
                    self.statements.merge_entities(kept, other, reason=reason, run_id=report.run_id)
                self._record(report, action)
                found.append(action)
                report.merged += 1
        queue = [(a, b, r) for a, b, r in result.review]
        queue += self._same_name_pairs(view)
        for a, b, reason in queue:
            pair = tuple(sorted((a, b)))
            if pair in open_ or pair in distinct:
                continue
            report.review += 1
            if report.dry_run:
                open_.add(pair)
            else:
                dedupe.propose(self.engine, a, b, reason, open_, run_id=report.run_id)
        return found

    @staticmethod
    def _same_name_pairs(view: View) -> list[tuple[str, str, str]]:
        groups: dict[tuple[str, str], set[str]] = defaultdict(set)
        for e in view.active():
            row = view.entities[e]
            if row["type"] in (PERSON, SOURCE):
                continue
            for n in row["names"]:
                if n["kind"] == "primary" and normalize(n["text"]):
                    groups[(row["type"], normalize(n["text"]))].add(e)
        pairs = {(a, b) for members in groups.values() for a, b in combinations(sorted(members), 2)}
        return [(a, b, SAME_NAME) for a, b in sorted(pairs)]

    # --- проверка ---

    def _verify(self, report: Report, base: integrity.Baseline, view: View) -> None:
        if report.dry_run:
            folded = self._predicted_folds(view)
            garbage = sum(
                1
                for s in base.statements.values()
                if _end(view, s["subject"]) in view.retired
                or (s["object"] and _end(view, s["object"]) in view.retired)
            )
            report.folded = folded
            report.statements.update(
                after=report.statements["before"] - folded,
                folded=folded,
                dropped_garbage=garbage,
                lost=0,
            )
            report.attributions["lost"] = 0
            report.a1["after"] = a1(view)
            return
        result = integrity.compare(base, self.engine)
        live = integrity.baseline(self.engine)
        report.folded = result["folded"]
        report.statements.update(
            after=len(live.statements),
            folded=result["folded"],
            dropped_garbage=result["dropped_garbage"],
            lost=len(result["lost"]),
        )
        report.attributions["lost"] = len(result["lost_attributions"])
        report.a1["after"] = a1(View.load(self.engine))

    def _predicted_folds(self, view: View) -> int:
        """Свёртки слияний плана: утверждения, чей ключ после перенаправления концов совпал
        с ключом другого (правило ``Statements.merge_entities``)."""
        if not view.redirect:
            return 0
        with self.engine.begin() as conn:
            rows = conn.execute(select(t.statements)).mappings().all()
        keys: Counter[tuple[str, str]] = Counter()
        touched: set[tuple[str, str]] = set()
        for r in rows:
            subject, obj = (
                _end(view, r["subject"]),
                _end(view, r["object"]) if r["object"] else None,
            )
            key = self.statements._key(subject, r["type"], obj, r["value"], r["qualifiers"])
            keys[(key, r["scope"])] += 1
            if subject != r["subject"] or obj != r["object"]:
                touched.add((key, r["scope"]))
        return sum(keys[k] - 1 for k in touched if keys[k] > 1)

    def _abort(self, report: Report) -> None:
        events.emit(
            "knowledge.migration.aborted",
            error_kind="integrity_lost",
            run_id=report.run_id,
            lost=report.statements["lost"],
            lost_attributions=report.attributions["lost"],
        )
        self.rollback(report.run_id)
        raise Aborted(report)

    # --- откат ---

    def rollback(self, run_id: str) -> dict[str, Any]:
        done = run_actions.actions(self.engine, run_id, reverse=True)
        with self.engine.begin() as conn:
            merges = conn.execute(
                select(t.merges.c.id, t.merges.c.moved)
                .where(t.merges.c.undone.is_(False))
                .order_by(t.merges.c.id.desc())
            ).all()
        merges_undone = 0
        for merge_id, moved in merges:
            if (moved or {}).get("run_id") == run_id:
                self.statements.undo_merge(merge_id)
                merges_undone += 1
        restored = kept = 0
        externals: list[dict[str, Any]] = []
        for item in done:
            p, kind = item["payload"], item["kind"]
            if kind == "rename":
                kept += 0 if self._undo_rename(p) else 1
            elif kind == "retire":
                with self.engine.begin() as conn:
                    changed = conn.execute(
                        update(t.entities)
                        .where(
                            and_(t.entities.c.id == p["entity"], t.entities.c.retired_run == run_id)
                        )
                        .values(retired_run=None, retired_reason=None)
                    ).rowcount
                if changed:
                    restored += 1
                    events.emit("knowledge.entity.restored", entity_id=p["entity"], run_id=run_id)
            elif kind == "lang":
                with self.engine.begin() as conn:
                    conn.execute(
                        update(t.names)
                        .where(and_(t.names.c.id == p["name_id"], t.names.c.lang == p["lang"]))
                        .values(lang=p["old_lang"])
                    )
            elif kind == "external":
                externals.append(p)
        # Шаг QID из манифеста: утверждения запуска (кроме проверенных) и записанные QID.
        self.statements.rollback_run(run_id)
        for p in externals:
            self.entities.remove_external(p["entity"], QID_SYSTEM, p["qid"])
        self._close_review(run_id)
        summary = {
            "run_id": run_id,
            "actions": len(done),
            "merges_undone": merges_undone,
            "restored": restored,
            "kept": kept,
        }
        events.emit("knowledge.migration.rolled_back", **summary)
        return summary

    def _undo_rename(self, p: dict[str, Any]) -> bool:
        """Названия до переименования; если основное с тех пор сменили — не трогается."""
        entity_id = p["entity"]
        with self.engine.begin() as conn:
            rows = (
                conn.execute(select(t.names).where(t.names.c.entity_id == entity_id))
                .mappings()
                .all()
            )
            primary = [r for r in rows if r["kind"] == "primary"]
            if not any(r["text"] == p["text"] for r in primary):
                return False  # переименовали после запуска: чужое изменение
            before = {n["id"]: n for n in p["names_before"]}
            for r in rows:
                if r["id"] not in before:
                    conn.execute(delete(t.names).where(t.names.c.id == r["id"]))
            for n in before.values():
                conn.execute(
                    update(t.names)
                    .where(t.names.c.id == n["id"])
                    .values(
                        lang=n["lang"], text=n["text"], normalized=n["normalized"], kind=n["kind"]
                    )
                )
        return True

    def _close_review(self, run_id: str) -> None:
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(t.review_items.c.id, t.review_items.c.payload).where(
                    and_(t.review_items.c.kind == "duplicate", t.review_items.c.status == "open")
                )
            ).all()
            for item_id, payload in rows:
                if (payload or {}).get("run_id") == run_id:
                    conn.execute(
                        update(t.review_items)
                        .where(t.review_items.c.id == item_id)
                        .values(status="rolled_back")
                    )


def _end(view: View, entity_id: str | None) -> str | None:
    seen = set()
    while entity_id in view.redirect and entity_id not in seen:
        seen.add(entity_id)
        entity_id = view.redirect[entity_id]
    return entity_id


def _name_json(n: dict[str, Any]) -> dict[str, Any]:
    return {k: n[k] for k in ("id", "lang", "text", "normalized", "kind")}


def _no_fetch(url: str) -> dict[str, Any]:
    raise WikidataError("загрузка Wikidata не задана")


# --- CLI ------------------------------------------------------------------------------


def _llm_client() -> ServiceClient:
    """Шлюз моделей из настроек сервиса знаний, как в ``knowledge.main``."""
    return ServiceClient("llm", os.environ["PHILOGRAPH_LLM_URL"], timeout=120)


def _service(fetch: Fetch | None, llm: ServiceClient | None) -> Migration:
    from philograph.knowledge import schema
    from philograph.knowledge.entities import Entities
    from philograph.knowledge.registry import OntologyRegistry
    from philograph.platform.db import make_engine

    engine = make_engine(os.environ["PHILOGRAPH_DATABASE_URL"], [schema.SCHEMA])
    schema.migrations.upgrade(engine)
    registry = OntologyRegistry(engine)
    registry.load_defaults()
    entities = Entities(engine, registry)
    statements = Statements(engine, registry, entities, lambda _: None)
    return Migration(statements, None, fetch, llm)


def main(
    argv: list[str] | None = None,
    *,
    fetch: Fetch | None = None,
    llm: ServiceClient | None = None,
    service: Callable[[Fetch | None, ServiceClient | None], Migration] = _service,
) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        prog="python -m philograph.knowledge.ontology_migrate",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_ in (("plan", "сухой прогон"), ("run", "запуск миграции")):
        p = sub.add_parser(name, help=help_)
        p.add_argument("--manifest", type=Path, default=None, help="манифест QID (manifest_qids)")
        p.add_argument("--from-file", type=Path, default=None, help="записи Wikidata из файла")
        p.add_argument("--batch", type=int, default=DEFAULT_BATCH)
        p.add_argument("--limit", type=int, default=None, help="не больше N названий к переводу")
        if name == "plan":
            p.add_argument("--estimate", action="store_true", help="одна проба модели")
        else:
            p.add_argument("--translate", choices=("off", "model"), default="off")
    p = sub.add_parser("rollback", help="откатить запуск")
    p.add_argument("run_id")
    args = parser.parse_args(argv)

    manifest = None
    if args.command != "rollback":
        if args.batch < 1:
            print("--batch: не меньше 1", file=sys.stderr)
            return 2
        if args.manifest is not None:
            try:
                manifest = load_manifest(args.manifest)
                check_manifest(manifest)
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
    wants_model = (args.command == "run" and args.translate == "model") or (
        args.command == "plan" and args.estimate
    )
    if wants_model and llm is None:
        llm = _llm_client()
    migration = service(fetch, llm if wants_model else None)
    if args.command == "rollback":
        print(json.dumps(migration.rollback(args.run_id), ensure_ascii=False, indent=2))
        return 0
    try:
        if args.command == "plan":
            report = migration.plan(
                manifest=copy.deepcopy(manifest),
                estimate=args.estimate,
                batch=args.batch,
                limit=args.limit,
            )
        else:
            report = migration.run(
                manifest=manifest, translate=args.translate, batch=args.batch, limit=args.limit
            )
    except Aborted as exc:
        print(json.dumps(exc.report.to_json(), ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(report.to_json(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
