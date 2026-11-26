"""Контекстные события эпох из Wikidata — команда оператора (возможность ``epoch-context``).

    python -m philograph.knowledge.epoch_context harvest [--epochs sources/epochs.yaml]
                                                         [--manifest sources/epoch_context.yaml]
    python -m philograph.knowledge.epoch_context apply   [--manifest sources/epoch_context.yaml]
                                                         [--dry-run]

База — ``PHILOGRAPH_DATABASE_URL``, как у сервиса знаний.

- ``harvest`` берёт у эпох с подтверждённым QID (поле ``wikidata`` в ``sources/epochs.yaml``
  и внешний идентификатор эпохи в базе) «значимые события» (P793). У события — дата (момент
  P585, иначе начало и конец P580/P582), вид по таблице классов P31 (``EVENT_CLASSES``; класс
  не из таблицы — вида нет), первое место (P276). Кандидат без даты не предлагается.
  Кандидаты пишутся в манифест с решением ``pending``; уже записанные кандидаты (их решения
  и поля, которые правил человек) не трогаются, новые дописываются. В базу не пишет.
- ``apply`` записывает только кандидатов с решением ``accepted``: событие (найденное по
  внешнему идентификатору или новое), датировку (дата загружается заново и должна
  разбираться), вид (из манифеста, только значение списка реестра), принадлежность
  к эпохе (``membership_basis=historians``) и место (по QID или новое). Все утверждения —
  «по источникам», атрибуция ``wikidata:<QID события>`` со ссылкой, происхождение «импорт».
  Связей «стимулировало», механизма и влияния Wikidata не даёт и команда их не пишет.
  Есть ли строка, проверяется до записи (``Statements.find``): повторный запуск ничего
  не добавляет. QID события или места, занятый сущностью другого типа, — ``duplicate_qid``
  (ничего не пишется, решает человек). ``--dry-run`` считает то же без записи.

Сеть — только ``wikidata.http_fetch``; функции модуля получают загрузку ``fetch`` извне.
Своего разбора времени и проверки QID здесь нет — общий модуль ``knowledge/wikidata.py``.
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
from philograph.knowledge.entities import Entities
from philograph.knowledge.epoch_dates import ManifestError, load_manifest, save_manifest
from philograph.knowledge.naming import invalid_primary, reject
from philograph.knowledge.statements import Attribution, Provenance, Statements
from philograph.knowledge.wikidata import (
    QID,
    Claim,
    Fetch,
    WikidataError,
    WikidataRecord,
    fetch_entity,
    format_original,
    http_fetch,
    page_url,
    wikidata_time,
)
from philograph.platform import events

events.define(
    "knowledge.context_import.harvested",
    "info",
    "Подобраны контекстные события эпох из Wikidata",
    required=("epochs", "candidates"),
)
events.define(
    "knowledge.context_import.checked",
    "info",
    "Проверен кандидат контекстного события",
    required=("qid", "result"),
)
events.define(
    "knowledge.context_import.run",
    "info",
    "Завершён импорт контекстных событий",
    required=("mode", "created", "statements", "places_created", "skipped"),
)

DEFAULT_EPOCHS = Path("sources/epochs.yaml")
DEFAULT_MANIFEST = Path("sources/epoch_context.yaml")
SYSTEM = "wikidata"
SIGNIFICANT_EVENT = "P793"
POINT_IN_TIME = "P585"
START, END = "P580", "P582"
INSTANCE_OF = "P31"
LOCATION = "P276"
EPOCH, EVENT, PLACE = "epoch", "event", "place"
DECISIONS = ("pending", "accepted", "rejected")
RESULTS = (
    "created",
    "exists",
    "pending",
    "rejected",
    "no_date",
    "fetch_failed",
    "duplicate_qid",
)
# Класс записи Wikidata (P31) → вид события реестра (``event_kind``). Данные модуля, как
# ``PERIOD_CLASSES`` в ``epoch_dates``: дополняются здесь и проверяются тестом на фикстурах.
# Класс не из таблицы — вид не записывается (событие попадёт в «Прочее»). QID классов
# сверяет Lead по ``harvest`` на своих данных.
EVENT_CLASSES: dict[str, str] = {
    "Q10931": "political",  # revolution — революция
    "Q124734": "political",  # rebellion — восстание
    "Q198": "political",  # war — война
    "Q178561": "political",  # battle — сражение
    "Q131569": "political",  # treaty — договор
    "Q290178": "economic",  # economic crisis — экономический кризис
    "Q44512": "social",  # epidemic — эпидемия
    "Q12184": "social",  # pandemic — пандемия
}
# Сбой загрузки или разбора ответа — по типу, без ``except Exception``.
FETCH_ERRORS = (WikidataError, httpx.HTTPError, KeyError, ValueError, TypeError)


# --- манифест -------------------------------------------------------------------------


def validate(manifest: dict[str, Any]) -> list[str]:
    """Проблемы манифеста: эпоха без названия или QID, кандидат с QID не по шаблону,
    решение вне списка, место не по форме."""
    entries = manifest.get("epochs")
    if entries is None:
        return []
    if not isinstance(entries, list):
        return ["epochs — не список"]
    problems: list[str] = []
    for i, entry in enumerate(entries):
        where = f"epochs[{i}]"
        if not isinstance(entry, dict):
            problems.append(f"{where}: не словарь")
            continue
        if not isinstance(entry.get("epoch"), str) or not entry["epoch"].strip():
            problems.append(f"{where}: нет названия эпохи")
        if not (isinstance(entry.get("qid"), str) and QID.fullmatch(entry["qid"])):
            problems.append(f"{where}: qid эпохи не по шаблону Q<число>")
        candidates = entry.get("candidates") or []
        if not isinstance(candidates, list):
            problems.append(f"{where}: candidates — не список")
            continue
        for j, c in enumerate(candidates):
            at = f"{where}.candidates[{j}]"
            if not isinstance(c, dict):
                problems.append(f"{at}: не словарь")
                continue
            if not (isinstance(c.get("qid"), str) and QID.fullmatch(c["qid"])):
                problems.append(f"{at}: qid не по шаблону")
            if c.get("decision") not in DECISIONS:
                problems.append(f"{at}: decision — pending, accepted или rejected")
            if c.get("kind") is not None and not isinstance(c.get("kind"), str):
                problems.append(f"{at}: kind — не строка")
            label = c.get("label")
            if label is not None and not isinstance(label, dict):
                problems.append(f"{at}: label — не словарь языков")
            place = c.get("place")
            if place is not None and not (
                isinstance(place, dict)
                and isinstance(place.get("qid"), str)
                and QID.fullmatch(place["qid"])
            ):
                problems.append(f"{at}: place.qid не по шаблону")
    return problems


def check_manifest(manifest: dict[str, Any]) -> None:
    problems = validate(manifest)
    if problems:
        raise ManifestError(problems)


# --- разбор записи события --------------------------------------------------------------


def _time(claim: Claim | None) -> tuple[str, int] | None:
    if claim is None or not isinstance(claim.value, dict):
        return None
    value, precision = claim.value.get("time"), claim.value.get("precision")
    if not isinstance(value, str) or isinstance(precision, bool) or not isinstance(precision, int):
        return None
    return value, precision


def raw_dates(record: WikidataRecord) -> dict[str, Any] | None:
    """Дата события как в манифесте (значения времени Wikidata) или ``None``: момент P585,
    иначе начало и конец P580/P582 (оба). Неразбираемое значение — нет даты."""
    point = _time(record.best(POINT_IN_TIME))
    if point is not None:
        raw = {"start": point[0], "start_precision": point[1]}
    else:
        start, end = _time(record.best(START)), _time(record.best(END))
        if start is None or end is None:
            return None
        raw = {
            "start": start[0],
            "start_precision": start[1],
            "end": end[0],
            "end_precision": end[1],
        }
    return raw if event_dating(raw) is not None else None


def event_dating(raw: dict[str, Any] | None) -> FuzzyDate | None:
    """Датировка в формате ``FuzzyDate.to_json`` с ``original`` из ``format_original``:
    одинаковые данные Wikidata дают одинаковый ключ утверждения (повторный ``apply``)."""
    if not isinstance(raw, dict):
        return None
    start = wikidata_time(raw.get("start"), raw.get("start_precision"))
    if start is None:
        return None
    if raw.get("end") is None:
        return start
    end = wikidata_time(raw.get("end"), raw.get("end_precision"))
    if end is None or start.earliest_start > end.latest_end:
        return None
    return interval(start, end, format_original(start, end))


def event_kind(classes: list[str]) -> str | None:
    """Вид события по первому классу P31 из таблицы; нет такого — ``None``."""
    return next((EVENT_CLASSES[c] for c in classes if c in EVENT_CLASSES), None)


def _labels(record: WikidataRecord) -> dict[str, str]:
    return {lang: record.labels[lang] for lang in ("ru", "en") if record.labels.get(lang)}


def _candidate(record: WikidataRecord, fetch: Fetch) -> dict[str, Any] | None:
    dates = raw_dates(record)
    if dates is None:
        return None
    classes = record.items(INSTANCE_OF)
    places = record.items(LOCATION)
    place = None
    if places:
        try:
            place_labels = _labels(fetch_entity(places[0], fetch))
        except FETCH_ERRORS:
            place_labels = {}
        place = {"qid": places[0], "label": place_labels}
    return {
        "qid": record.qid,
        "label": _labels(record),
        "dates": dates,
        "classes": classes,
        "kind": event_kind(classes),
        "place": place,
        "decision": "pending",
    }


# --- подбор ---------------------------------------------------------------------------


def harvest(
    epochs_manifest: dict[str, Any],
    manifest: dict[str, Any],
    fetch: Fetch,
    linked: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Манифест с новыми кандидатами. ``epochs_manifest`` — ``sources/epochs.yaml``
    (эпохи с подтверждённым ``wikidata``); ``linked`` — эпохи базы: название → QID."""
    check_manifest(manifest)
    result = copy.deepcopy(manifest)
    result.setdefault("epochs", [])
    result["epochs"] = result["epochs"] or []
    sources: dict[str, str] = {}
    for entry in epochs_manifest.get("epochs") or []:
        qid = entry.get("wikidata") if isinstance(entry, dict) else None
        if isinstance(qid, str) and QID.fullmatch(qid) and isinstance(entry.get("ru"), str):
            sources.setdefault(qid, entry["ru"].strip())
    for label, qid in (linked or {}).items():
        if isinstance(qid, str) and QID.fullmatch(qid):
            sources.setdefault(qid, label)
    by_qid = {e["qid"]: e for e in result["epochs"]}
    for epoch_qid, label in sources.items():
        entry = by_qid.get(epoch_qid)
        if entry is None:
            entry = {"epoch": label, "qid": epoch_qid, "candidates": []}
            result["epochs"].append(entry)
            by_qid[epoch_qid] = entry
        entry["candidates"] = entry.get("candidates") or []
        known = {c["qid"] for c in entry["candidates"]}
        try:
            epoch = fetch_entity(epoch_qid, fetch)
        except FETCH_ERRORS:
            continue  # эпоха без записи — кандидатов нет; ``checked`` пишет только ``apply``
        for qid in epoch.items(SIGNIFICANT_EVENT):
            if qid in known:
                continue  # решение и поля человека не трогаются
            try:
                record = fetch_entity(qid, fetch)
            except FETCH_ERRORS:
                continue
            candidate = _candidate(record, fetch)
            if candidate is None:
                continue  # без даты не предлагается
            entry["candidates"].append(candidate)
            known.add(qid)
    total = sum(len(e.get("candidates") or []) for e in result["epochs"])
    events.emit("knowledge.context_import.harvested", epochs=len(sources), candidates=total)
    return result


# --- применение -----------------------------------------------------------------------


@dataclass
class Report:
    mode: str
    candidates: list[dict[str, Any]] = field(default_factory=list)
    statements: int = 0
    places_created: int = 0

    def totals(self) -> dict[str, int]:
        results = [c["result"] for c in self.candidates]
        return {
            "created": results.count("created"),
            "statements": self.statements,
            "places_created": self.places_created,
            "skipped": len(results) - results.count("created") - results.count("exists"),
        }

    def to_json(self) -> dict[str, Any]:
        return {"mode": self.mode, "candidates": self.candidates, "totals": self.totals()}


class EpochContextImport:
    def __init__(self, statements: Statements, entities: Entities | None = None) -> None:
        self.statements = statements
        self.entities = entities or statements.entities
        self.registry = statements.registry

    def _of_type(self, entity_id: str | None, type_: str) -> bool:
        if entity_id is None:
            return False
        return self.registry.is_a(self.entities.get(entity_id)["type"], [type_])

    def _epoch(self, entry: dict[str, Any]) -> str | None:
        """Эпоха манифеста в базе: по подтверждённому QID, иначе по единственному названию."""
        owner = self.entities.by_external(SYSTEM, entry["qid"])
        if self._of_type(owner, EPOCH):
            return owner
        found = [
            e["id"]
            for e in self.entities.find(entry["epoch"].strip())
            if self.registry.is_a(e["type"], [EPOCH])
        ]
        return found[0] if len(found) == 1 else None

    def _preflight(self, manifest: dict[str, Any]) -> dict[int, str]:
        """До записи и сети: эпохи с принятыми кандидатами есть в базе, виды — из реестра."""
        kinds = set(self.registry.relation("event_kind").get("values") or [])
        problems: list[str] = []
        epochs: dict[int, str] = {}
        for i, entry in enumerate(manifest.get("epochs") or []):
            accepted = [c for c in entry.get("candidates") or [] if c["decision"] == "accepted"]
            if not accepted:
                continue
            epoch_id = self._epoch(entry)
            if epoch_id is None:
                problems.append(
                    f"epochs[{i}]: эпохи «{entry['epoch']}» нет в онтологии"
                    " (сначала epoch_dates apply)"
                )
            else:
                epochs[i] = epoch_id
            for c in accepted:
                if c.get("kind") is not None and c["kind"] not in kinds:
                    problems.append(f"epochs[{i}] {c['qid']}: вид {c['kind']!r} не из реестра")
        if problems:
            raise ManifestError(problems)
        return epochs

    def apply(self, manifest: dict[str, Any], fetch: Fetch, *, dry_run: bool = False) -> Report:
        check_manifest(manifest)
        epochs = self._preflight(manifest)
        report = Report("dry_run" if dry_run else "apply")
        for i, entry in enumerate(manifest.get("epochs") or []):
            for candidate in entry.get("candidates") or []:
                item = {"qid": candidate["qid"]}
                if candidate["decision"] != "accepted":
                    item["result"] = candidate["decision"]
                else:
                    item.update(self._accepted(entry, epochs[i], candidate, fetch, dry_run, report))
                events.emit(
                    "knowledge.context_import.checked", qid=item["qid"], result=item["result"]
                )
                report.candidates.append(item)
        events.emit("knowledge.context_import.run", mode=report.mode, **report.totals())
        return report

    def _accepted(
        self,
        entry: dict[str, Any],
        epoch_id: str,
        candidate: dict[str, Any],
        fetch: Fetch,
        dry_run: bool,
        report: Report,
    ) -> dict[str, Any]:
        qid = candidate["qid"]
        try:
            record = fetch_entity(qid, fetch)
        except FETCH_ERRORS:
            return {"result": "fetch_failed"}
        dating = event_dating(raw_dates(record))
        if dating is None:
            return {"result": "no_date"}
        event_id = self.entities.by_external(SYSTEM, qid)
        if event_id is not None and not self._of_type(event_id, EVENT):
            return {"result": "duplicate_qid"}  # QID занят сущностью другого типа
        names = _names(candidate.get("label") or {}, _labels(record), qid)
        place = candidate.get("place")
        place_id = self.entities.by_external(SYSTEM, place["qid"]) if place else None
        new_place = place is not None and place_id is None
        if place_id is not None and not self._of_type(place_id, PLACE):
            return {"result": "duplicate_qid"}  # QID места занят не местом: решает человек
        # Названия новых сущностей — до записи: кандидат не пишется наполовину.
        new = ([(EVENT, names)] if event_id is None else []) + (
            [(PLACE, _names(place.get("label") or {}, {}, place["qid"]))] if new_place else []
        )
        for type_, new_names in new:
            bad = invalid_primary(type_, new_names)
            if bad is not None:
                reject(type_, *bad)
                return {"result": "invalid_name"}
        attribution = [Attribution("source", f"{SYSTEM}:{qid}", place=page_url(qid))]
        provenance = Provenance(
            "imported", extra={"wikidata": qid, "from": SIGNIFICANT_EVENT, "epoch": entry["qid"]}
        )
        # (тип, объект, значение, уточнители); объект места — ``None``, пока его нет.
        planned: list[tuple[str, str | None, Any, dict[str, Any]]] = [
            ("dating", None, dating.to_json(), {}),
        ]
        if candidate.get("kind"):
            planned.append(("event_kind", None, candidate["kind"], {}))
        planned.append(("belongs_to_epoch", epoch_id, None, {"membership_basis": "historians"}))
        if place is not None:
            planned.append(("happened_in", place_id, None, {}))
        missing = [
            p
            for p in planned
            if event_id is None
            or (p[0] == "happened_in" and p[1] is None)
            or self.statements.find(event_id, p[0], obj=p[1], value=p[2], qualifiers=p[3]) is None
        ]
        if event_id is not None and not missing:
            return {"result": "exists", "event_id": event_id}
        report.statements += len(missing)
        report.places_created += int(new_place)
        if dry_run:
            return {"result": "created", "event_id": event_id, "statements": len(missing)}
        if event_id is None:
            event_id = self.entities.create(EVENT, names, external={SYSTEM: qid})
        if new_place:
            place_names = _names(place.get("label") or {}, {}, place["qid"])
            place_id = self.entities.create(PLACE, place_names, external={SYSTEM: place["qid"]})
        for type_, obj, value, qualifiers in missing:
            self.statements.add(
                event_id,
                type_,
                obj=place_id if type_ == "happened_in" else obj,
                value=value,
                qualifiers=qualifiers,
                attributions=attribution,
                provenance=provenance,
                status="sourced",
            )
        return {"result": "created", "event_id": event_id, "statements": len(missing)}


def _names(own: dict[str, Any], fetched: dict[str, str], qid: str) -> list[tuple[str, str, str]]:
    """Названия RU/EN: из манифеста (правка человека), иначе из записи; нет — QID."""
    names = []
    for lang in ("ru", "en"):
        text = own.get(lang) if isinstance(own.get(lang), str) else fetched.get(lang)
        if text and text.strip():
            names.append((lang, text.strip(), "primary"))
    return names or [("en", qid, "primary")]


# --- CLI ------------------------------------------------------------------------------


def _service() -> EpochContextImport:
    from philograph.knowledge import schema
    from philograph.knowledge.registry import OntologyRegistry
    from philograph.platform.db import make_engine

    engine = make_engine(os.environ["PHILOGRAPH_DATABASE_URL"], [schema.SCHEMA])
    schema.migrations.upgrade(engine)
    registry = OntologyRegistry(engine)
    registry.load_defaults()
    entities = Entities(engine, registry)
    # Импорт пишет только факты с атрибуцией Wikidata: цитат нет, абзацы не нужны.
    return EpochContextImport(Statements(engine, registry, entities, lambda _: None), entities)


def linked_epochs(service: EpochContextImport) -> dict[str, str]:
    """Эпохи базы с внешним идентификатором Wikidata: название → QID (только чтение)."""
    found = {}
    for entity_id, qid in service.entities.externals(SYSTEM).items():
        if service._of_type(entity_id, EPOCH):
            found[service.entities.label(entity_id)] = qid
    return found


def main(
    argv: list[str] | None = None,
    *,
    fetch: Fetch | None = None,
    service: Callable[[], EpochContextImport] = _service,
) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        prog="python -m philograph.knowledge.epoch_context",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("harvest", help="подобрать кандидатов событий эпох в манифест")
    p.add_argument("--epochs", type=Path, default=DEFAULT_EPOCHS)
    p.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    p = sub.add_parser("apply", help="записать принятых кандидатов")
    p.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    p.add_argument("--dry-run", action="store_true", help="без записи в базу")
    args = parser.parse_args(argv)

    try:
        manifest = load_manifest(args.manifest)
        check_manifest(manifest)  # до базы и сети
        epochs_manifest = load_manifest(args.epochs) if args.command == "harvest" else {}
    except (ManifestError, yaml.YAMLError, OSError) as exc:
        print(f"манифест: {exc}", file=sys.stderr)
        return 2
    fetch = fetch or partial(http_fetch, wait=time.sleep)
    if args.command == "harvest":
        updated = harvest(epochs_manifest, manifest, fetch, linked_epochs(service()))
        save_manifest(updated, args.manifest)
        print(json.dumps({"epochs": updated["epochs"]}, ensure_ascii=False, indent=2))
        return 0
    try:
        report = service().apply(manifest, fetch, dry_run=args.dry_run)
    except ManifestError as exc:
        print(f"манифест {args.manifest}: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report.to_json(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    # Журнал подключается только при запуске командой: stdout занят отчётом, события
    # идут в stderr. Вызов main() из тестов оставляет приёмник фикстуры как есть.
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    events.configure(sinks=[events.json_sink(sys.stderr)])
    sys.exit(main())
