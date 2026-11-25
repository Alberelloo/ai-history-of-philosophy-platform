"""Даты эпох из Wikidata — команда оператора (возможность ``epochs``).

    python -m philograph.knowledge.epoch_dates suggest [--manifest sources/epochs.yaml]
    python -m philograph.knowledge.epoch_dates apply   [--manifest sources/epochs.yaml]
                                                       [--linked] [--dry-run]

База — ``PHILOGRAPH_DATABASE_URL``, как у сервиса знаний.

- ``suggest`` ищет для эпох манифеста без ``wikidata`` кандидатов по названию, оставляет
  записи классов исторических периодов (``PERIOD_CLASSES``) с датой начала или конца и
  записывает их в ``candidates``; поле ``wikidata`` заполняет только человек. В базу не пишет.
- ``apply`` дописывает датировку эпохам без действующей датировки (P580/P582, если нет
  обоих — P571/P576) и заводит эпохи манифеста, которых нет в онтологии. Существующая
  датировка не перезаписывается: совпадение — ``unchanged``, расхождение — ``conflict``
  в отчёте. ``--dry-run`` считает те же результаты без записи. ``--linked`` дополнительно
  обходит эпохи базы с внешним идентификатором Wikidata.

Сеть — только ``wikidata.http_fetch``; функции модуля получают загрузку ``fetch`` извне.
Связи влияния и прочие свойства записи не импортируются: берутся только даты.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Any

import httpx
import yaml

from philograph.knowledge.dates import FuzzyDate, interval
from philograph.knowledge.entities import DuplicateEntity, Entities
from philograph.knowledge.statements import Attribution, Provenance, Statements
from philograph.knowledge.wikidata import (
    QID,
    Fetch,
    WikidataError,
    WikidataRecord,
    claim_date,
    fetch_entity,
    http_fetch,
    page_url,
    search,
)
from philograph.platform import events

events.define(
    "knowledge.epoch_dates.checked",
    "info",
    "Проверена датировка эпохи по Wikidata",
    required=("epoch_id", "qid", "result"),
)
events.define(
    "knowledge.epoch_dates.run",
    "info",
    "Завершён запуск дат эпох из Wikidata",
    required=("mode", "checked", "added", "created", "conflicts", "skipped"),
)
events.define(
    "knowledge.epoch_dates.suggested",
    "info",
    "Подобраны кандидаты Wikidata для эпох манифеста",
    required=("epochs", "candidates"),
)

DEFAULT_MANIFEST = Path("sources/epochs.yaml")
EPOCH = "epoch"
SYSTEM = "wikidata"
MAIN = ("P580", "P582")  # время начала и окончания
FALLBACK = ("P571", "P576")  # дата основания и прекращения
INSTANCE_OF = "P31"
# Классы записей, которые годятся в кандидаты эпох (значения P31). Список — данные модуля:
# дополняется здесь, проверяется тестом на фикстурах, а не по сети.
PERIOD_CLASSES = frozenset(
    {
        "Q11514315",  # historical period — исторический период
        "Q6428674",  # era — эра
        "Q968159",  # art movement — направление в искусстве (барокко, романтизм)
    }
)
RESULTS = (
    "added",
    "created",
    "unchanged",
    "conflict",
    "no_dates",
    "no_qid",
    "fetch_failed",
    "ambiguous",
    "duplicate_qid",
)
# Сбой загрузки или разбора ответа — по типу, без ``except Exception``.
FETCH_ERRORS = (WikidataError, httpx.HTTPError, KeyError, ValueError, TypeError)


class ManifestError(Exception):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


# --- манифест -------------------------------------------------------------------------


def load_manifest(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ManifestError(["манифест — не словарь"])
    return data


def _header(path: Path) -> str:
    """Комментарии в начале файла: ``save_manifest`` их сохраняет."""
    if not path.exists():
        return ""
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("#"):
            break
        lines.append(line)
    return "\n".join(lines) + "\n" if lines else ""


def save_manifest(manifest: dict[str, Any], path: Path) -> None:
    header = _header(path)
    body = yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True, default_flow_style=False)
    path.write_text(header + body, encoding="utf-8")


def validate(manifest: dict[str, Any]) -> list[str]:
    """Проблемы манифеста: повтор ``ru``, QID не по шаблону, кандидаты без дат."""
    problems: list[str] = []
    entries = manifest.get("epochs")
    if not isinstance(entries, list):
        return ["нет списка epochs"]
    seen: set[str] = set()
    for i, entry in enumerate(entries):
        where = f"epochs[{i}]"
        if not isinstance(entry, dict):
            problems.append(f"{where}: не словарь")
            continue
        ru = entry.get("ru")
        if not isinstance(ru, str) or not ru.strip():
            problems.append(f"{where}: нет названия ru")
        elif ru.strip() in seen:
            problems.append(f"{where}: повтор ru «{ru.strip()}»")
        else:
            seen.add(ru.strip())
        en = entry.get("en")
        if en is not None and (not isinstance(en, str) or not en.strip()):
            problems.append(f"{where}: en — не строка")
        qid = entry.get("wikidata")
        if qid is not None and not (isinstance(qid, str) and QID.fullmatch(qid)):
            problems.append(f"{where}: wikidata не по шаблону Q<число>")
        candidates = entry.get("candidates", [])
        if candidates is None:
            continue
        if not isinstance(candidates, list):
            problems.append(f"{where}: candidates — не список")
            continue
        for j, c in enumerate(candidates):
            if not isinstance(c, dict) or not (
                isinstance(c.get("qid"), str) and QID.fullmatch(c["qid"])
            ):
                problems.append(f"{where}.candidates[{j}]: qid не по шаблону")
            elif c.get("start") is None and c.get("end") is None:
                problems.append(f"{where}.candidates[{j}]: кандидат без дат")
    return problems


def check_manifest(manifest: dict[str, Any]) -> None:
    problems = validate(manifest)
    if problems:
        raise ManifestError(problems)


# --- датировка ------------------------------------------------------------------------


def epoch_dating(record: WikidataRecord) -> tuple[FuzzyDate, list[str]] | None:
    """Датировка из записи и использованные свойства; ``None`` — нет начала или конца.

    P580/P582; если нет обоих — P571/P576. Только начало или только конец, неразбираемые
    значения и начало позже конца — ``None``."""
    props = MAIN
    if record.best(MAIN[0]) is None and record.best(MAIN[1]) is None:
        props = FALLBACK
    start, end = (claim_date(record.best(p)) for p in props)
    if start is None or end is None or start.earliest_start > end.latest_end:
        return None
    return interval(start, end), list(props)


def _bounds(value: dict[str, Any]) -> tuple[int, int, int, int]:
    return (
        value["earliest_start"],
        value["latest_start"],
        value["earliest_end"],
        value["latest_end"],
    )


# --- применение -----------------------------------------------------------------------


@dataclass
class Report:
    mode: str
    epochs: list[dict[str, Any]] = field(default_factory=list)

    def totals(self) -> dict[str, int]:
        results = [e["result"] for e in self.epochs]
        added = results.count("added")
        created = results.count("created")
        conflicts = results.count("conflict")
        return {
            "checked": len(results),
            "added": added,
            "created": created,
            "conflicts": conflicts,
            "skipped": len(results) - added - created - conflicts,
        }

    def to_json(self) -> dict[str, Any]:
        return {"mode": self.mode, "epochs": self.epochs, "totals": self.totals()}


class EpochDates:
    def __init__(self, statements: Statements, entities: Entities | None = None) -> None:
        self.statements = statements
        self.entities = entities or statements.entities
        self.registry = statements.registry

    def _is_epoch(self, entity_id: str) -> bool:
        return self.registry.is_a(self.entities.get(entity_id)["type"], [EPOCH])

    def _by_name(self, *names: str | None) -> list[str]:
        found: list[str] = []
        for name in names:
            if not name:
                continue
            for entity in self.entities.find(name):
                if self.registry.is_a(entity["type"], [EPOCH]) and entity["id"] not in found:
                    found.append(entity["id"])
        return found

    def _datings(self, epoch_id: str) -> list[dict[str, Any]]:
        """Действующие датировки эпохи; основная (как в ``primary.dates``) — первой."""
        rows = [
            s
            for s in self.statements.about(epoch_id, types=["dating"], derived=False)
            if s["direction"] == "out"
        ]
        primary = self.entities.get(epoch_id)["primary"].get("dates")
        return sorted(rows, key=lambda s: (s["value"] != primary, s["rank"] != "preferred"))

    def apply(
        self,
        manifest: dict[str, Any],
        fetch: Fetch,
        *,
        dry_run: bool = False,
        linked: bool = False,
    ) -> Report:
        check_manifest(manifest)  # до базы и сети
        report = Report("dry_run" if dry_run else "apply")
        done: set[str] = set()
        known = self.entities.externals(SYSTEM)  # один раз на запуск: сущность → QID
        for entry in manifest["epochs"]:
            item = self._entry(entry, known, fetch, dry_run)
            if item["epoch_id"]:
                done.add(item["epoch_id"])
            self._record(report, item)
        if linked:
            for epoch_id, qid in known.items():
                if epoch_id in done or not self._is_epoch(epoch_id):
                    continue
                done.add(epoch_id)
                item = self._date(epoch_id, self.entities.label(epoch_id), qid, fetch, dry_run)
                self._record(report, item)
        totals = report.totals()
        events.emit("knowledge.epoch_dates.run", mode=report.mode, **totals)
        return report

    @staticmethod
    def _record(report: Report, item: dict[str, Any]) -> None:
        events.emit(
            "knowledge.epoch_dates.checked",
            epoch_id=item["epoch_id"],
            qid=item["qid"],
            result=item["result"],
        )
        report.epochs.append(item)

    def _entry(
        self, entry: dict[str, Any], known: dict[str, str], fetch: Fetch, dry_run: bool
    ) -> dict[str, Any]:
        ru = entry["ru"].strip()
        en = (entry.get("en") or "").strip() or None
        qid = entry.get("wikidata")
        matches = self._by_name(ru, en)
        if len(matches) > 1:
            return {"epoch_id": None, "label": ru, "qid": qid, "result": "ambiguous"}
        epoch_id = matches[0] if matches else None
        own = known.get(epoch_id) if epoch_id is not None else None
        if qid is None:
            qid = own
        elif own is not None and own != qid:
            # У эпохи уже другой QID: второй не записывается, решает человек.
            return {"epoch_id": epoch_id, "label": ru, "qid": qid, "result": "duplicate_qid"}
        if qid is None:
            return {"epoch_id": epoch_id, "label": ru, "qid": None, "result": "no_qid"}
        owner = self.entities.by_external(SYSTEM, qid)
        if epoch_id is None and owner is not None and self._is_epoch(owner):
            epoch_id = owner  # та же эпоха под другим названием — по подтверждённому QID
        if owner is not None and owner != epoch_id:
            return {"epoch_id": epoch_id, "label": ru, "qid": qid, "result": "duplicate_qid"}
        if epoch_id is not None:
            return self._date(epoch_id, ru, qid, fetch, dry_run)
        found = self._fetch(qid, fetch)
        if isinstance(found, str):
            return {"epoch_id": None, "label": ru, "qid": qid, "result": found}
        dating, props = found
        new_id = None
        if not dry_run:
            names = [("ru", ru, "primary")] + ([("en", en, "variant")] if en else [])
            new_id = self.entities.create(EPOCH, names, external={SYSTEM: qid})
            self._write(new_id, qid, dating, props)
        return {
            "epoch_id": new_id,
            "label": ru,
            "qid": qid,
            "result": "created",
            "dating": self._dating_json(dating, props),
        }

    def _fetch(self, qid: str, fetch: Fetch) -> tuple[FuzzyDate, list[str]] | str:
        try:
            record = fetch_entity(qid, fetch)
        except FETCH_ERRORS:
            return "fetch_failed"
        found = epoch_dating(record)
        return "no_dates" if found is None else found

    @staticmethod
    def _dating_json(dating: FuzzyDate, props: list[str]) -> dict[str, Any]:
        return {**dating.to_json(), "properties": props}

    def _date(
        self, epoch_id: str, label: str, qid: str, fetch: Fetch, dry_run: bool
    ) -> dict[str, Any]:
        item: dict[str, Any] = {"epoch_id": epoch_id, "label": label, "qid": qid}
        found = self._fetch(qid, fetch)
        if isinstance(found, str):
            return {**item, "result": found}
        dating, props = found
        item["dating"] = self._dating_json(dating, props)
        existing = self._datings(epoch_id)
        if existing:
            main = existing[0]["value"]
            same = _bounds(main) == _bounds(dating.to_json())
            if not same:
                item["existing"] = main
            return {**item, "result": "unchanged" if same else "conflict"}
        if not dry_run:
            try:
                self.entities.add_external(epoch_id, SYSTEM, qid)
            except DuplicateEntity:
                return {**item, "result": "duplicate_qid"}
            self._write(epoch_id, qid, dating, props)
        return {**item, "result": "added"}

    def _write(self, epoch_id: str, qid: str, dating: FuzzyDate, props: list[str]) -> None:
        self.statements.add(
            epoch_id,
            "dating",
            value=dating.to_json(),
            attributions=[Attribution("source", f"{SYSTEM}:{qid}", place=page_url(qid))],
            provenance=Provenance("imported", extra={"wikidata": qid, "properties": props}),
            status="sourced",
        )


# --- подбор ---------------------------------------------------------------------------


def _candidate(record: WikidataRecord, hit: dict[str, Any]) -> dict[str, Any] | None:
    if not PERIOD_CLASSES.intersection(record.items(INSTANCE_OF)):
        return None
    dates = {}
    for key, props in (("start", (MAIN[0], FALLBACK[0])), ("end", (MAIN[1], FALLBACK[1]))):
        found = next((d for p in props if (d := claim_date(record.best(p)))), None)
        dates[key] = found.original if found else None
    if dates["start"] is None and dates["end"] is None:
        return None
    labels = record.labels
    descriptions = record.descriptions
    return {
        "qid": record.qid,
        "label": labels.get("ru") or labels.get("en") or hit.get("label"),
        "description": descriptions.get("ru") or descriptions.get("en") or hit.get("description"),
        **dates,
    }


def suggest(manifest: dict[str, Any], fetch: Fetch) -> dict[str, Any]:
    """Манифест с кандидатами для эпох без ``wikidata``; прочие поля не меняются."""
    check_manifest(manifest)
    result = copy.deepcopy(manifest)
    searched = 0
    for entry in result["epochs"]:
        if entry.get("wikidata"):
            continue
        searched += 1
        hits: dict[str, dict[str, Any]] = {}
        for lang, name in (("ru", entry.get("ru")), ("en", entry.get("en"))):
            if not name:
                continue
            try:
                for hit in search(name.strip(), lang, fetch):
                    hits.setdefault(hit["id"], hit)
            except FETCH_ERRORS:
                continue
        found = []
        for qid, hit in hits.items():
            try:
                record = fetch_entity(qid, fetch)
            except FETCH_ERRORS:
                continue
            candidate = _candidate(record, hit)
            if candidate is not None:
                found.append(candidate)
        merged = list(entry.get("candidates") or [])
        index = {c.get("qid"): i for i, c in enumerate(merged) if isinstance(c, dict)}
        for candidate in found:
            if candidate["qid"] in index:
                merged[index[candidate["qid"]]] = candidate
            else:
                index[candidate["qid"]] = len(merged)
                merged.append(candidate)
        entry["candidates"] = merged
    total = sum(len(e.get("candidates") or []) for e in result["epochs"])
    events.emit("knowledge.epoch_dates.suggested", epochs=searched, candidates=total)
    return result


# --- CLI ------------------------------------------------------------------------------


def _service() -> EpochDates:
    from philograph.knowledge import schema
    from philograph.knowledge.registry import OntologyRegistry
    from philograph.platform.db import make_engine

    engine = make_engine(os.environ["PHILOGRAPH_DATABASE_URL"], [schema.SCHEMA])
    schema.migrations.upgrade(engine)
    registry = OntologyRegistry(engine)
    registry.load_defaults()
    entities = Entities(engine, registry)
    # Команда пишет только даты с атрибуцией Wikidata: цитат нет, абзацы не нужны.
    return EpochDates(Statements(engine, registry, entities, lambda _: None), entities)


def main(
    argv: list[str] | None = None,
    *,
    fetch: Fetch | None = None,
    service: Callable[[], EpochDates] = _service,
) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        prog="python -m philograph.knowledge.epoch_dates",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("suggest", help="подобрать кандидатов QID в манифест")
    p.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    p = sub.add_parser("apply", help="дописать даты эпохам без датировки")
    p.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    p.add_argument("--linked", action="store_true", help="и все эпохи базы с QID")
    p.add_argument("--dry-run", action="store_true", help="без записи в базу")
    args = parser.parse_args(argv)

    try:
        manifest = load_manifest(args.manifest)
        check_manifest(manifest)  # до базы и сети
    except (ManifestError, yaml.YAMLError, OSError) as exc:
        print(f"манифест {args.manifest}: {exc}", file=sys.stderr)
        return 2
    fetch = fetch or partial(http_fetch, wait=time.sleep)
    if args.command == "suggest":
        updated = suggest(manifest, fetch)
        save_manifest(updated, args.manifest)
        print(json.dumps({"epochs": updated["epochs"]}, ensure_ascii=False, indent=2))
        return 0
    report = service().apply(manifest, fetch, dry_run=args.dry_run, linked=args.linked)
    print(json.dumps(report.to_json(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
