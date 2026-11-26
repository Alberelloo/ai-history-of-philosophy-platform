"""Обогащение мест из Wikidata (geo-timeline): координаты мест и места в биографиях.

Команда оператора, не путь читателя. Обрабатываются только сущности, у которых уже есть
внешний идентификатор ``wikidata`` по шаблону ``^Q\\d+$``: персоны, события (и явления)
и места. Читаются только свойства таблицы ``PROPERTIES``:

- P19, P20 — «жил в» с видом ``birth``/``death``, время — дата рождения/смерти записи (P569,
  P570); P937 — «жил в» с видом ``activity``, время — уточнители P580–P582;
- P276 — «произошло в» у события;
- P625 — координаты места (``{latitude, longitude}`` → ``{lat, lon}``).

Место, которого ещё нет, ищется по внешнему id ``wikidata`` (места контекста эпох уже
могут быть) и только потом создаётся — с этим id и названиями записи. Новых персон и
событий обогащение не создаёт. Каждая запись — через ``Statements.add`` с атрибуцией
``wikidata:<QID>`` (ссылка — ``page_url``), статусом «по источникам» и происхождением
«импорт» с номером запуска. Повтор на тех же данных утверждений не добавляет: что уже
есть, находится ``Statements.find`` до записи.

Пропуски: ``bad_qid`` (значение — не QID), ``bad_value`` (нет или неразборчивое
значение), ``refused`` (сервер отклонил утверждение) → ``skipped``; ``fetch_failed``
(запись не загружена) → ``failed``. Каждый пропуск — событие ``knowledge.geo.skipped``
с id сущности, обрабатываемой в этот момент, и свойством; запуск идёт дальше.

Загрузка, проверка QID, разбор записи и времени — только ``knowledge/wikidata.py``; сеть —
``wikidata.http_fetch`` (CLI), из файла — ``--from-file``.

    python -m philograph.knowledge.geo_enrich run [--limit N] [--dry-run] [--from-file F]
    python -m philograph.knowledge.geo_enrich rollback <run_id>
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select

from philograph.knowledge import schema as t
from philograph.knowledge.dates import FuzzyDate, interval
from philograph.knowledge.entities import Entities
from philograph.knowledge.naming import invalid_primary, reject
from philograph.knowledge.statements import Attribution, Provenance, StatementError, Statements
from philograph.knowledge.wikidata import (
    ENTITY_URL,
    QID,
    Claim,
    Fetch,
    WikidataError,
    WikidataRecord,
    check_qid,
    claim_date,
    fetch_entity,
    format_original,
    http_fetch,
    page_url,
    wikidata_time,
)
from philograph.platform import events

events.define(
    "knowledge.geo.enriched",
    "info",
    "Обогащение мест из Wikidata завершено",
    required=(
        "run_id",
        "entities",
        "coordinates",
        "placements",
        "places_created",
        "skipped",
        "failed",
        "dry_run",
    ),
)
events.define(
    "knowledge.geo.skipped",
    "warning",
    "Запись Wikidata о месте пропущена",
    required=("entity", "property", "reason"),
)
events.define(
    "knowledge.geo.rolled_back",
    "info",
    "Запуск обогащения мест откачен",
    required=("run_id", "statements", "places_kept"),
)

SYSTEM = "wikidata"
PLACE = "place"
FETCH_ERRORS = (WikidataError, httpx.HTTPError)


@dataclass(frozen=True)
class Property:
    relation: str
    role: str | None = None  # вид места (уточнитель ``place_role``)
    time: str | None = None  # ``"P569"`` — дата свойства записи; ``"qualifiers"`` — P580–P582
    subjects: str = "person"  # person | event | place


# Прочие свойства не читаются: влияния (P737), гражданство (P27) и всё остальное.
PROPERTIES: dict[str, Property] = {
    "P19": Property("lived_in", "birth", "P569"),
    "P20": Property("lived_in", "death", "P570"),
    "P937": Property("lived_in", "activity", "qualifiers"),
    "P276": Property("happened_in", subjects="event"),
    "P625": Property("coordinates", subjects="place"),
}


class Skip(Exception):
    """Значение свойства не принято: ``reason`` — код пропуска."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class Report:
    run_id: str
    dry_run: bool
    entities: int = 0
    coordinates: int = 0
    placements: int = 0
    places_created: int = 0
    skipped: int = 0
    failed: int = 0
    # Места, которые сухой прогон «создал»: второе упоминание их не считает заново.
    planned: set[str] = field(default_factory=set)

    def to_json(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "entities": self.entities,
            "coordinates": self.coordinates,
            "placements": self.placements,
            "places_created": self.places_created,
            "skipped": self.skipped,
            "failed": self.failed,
            "dry_run": self.dry_run,
        }


def geo_value(claim: Claim | None) -> dict[str, Any]:
    """P625 → ``{lat, lon}``: переименование полей, проверку делает ``Statements``."""
    value = claim.value if claim is not None else None
    if not isinstance(value, dict) or "latitude" not in value or "longitude" not in value:
        raise Skip("bad_value")
    return {"lat": value["latitude"], "lon": value["longitude"]}


def _date(raw: Any) -> FuzzyDate | None:
    if not isinstance(raw, dict):
        return None
    return wikidata_time(raw.get("time"), raw.get("precision"))


def claim_time(record: WikidataRecord, claim: Claim, source: str | None) -> dict | None:
    """Уточнитель ``time`` — ``FuzzyDate.to_json()``, как у всех импортов Wikidata."""
    if source is None:
        return None
    if source != "qualifiers":
        found = claim_date(record.best(source))
        return found.to_json() if found else None
    start = next((d for v in claim.qualifiers.get("P580", []) if (d := _date(v))), None)
    end = next((d for v in claim.qualifiers.get("P582", []) if (d := _date(v))), None)
    if start and end:
        return interval(start, end, format_original(start, end)).to_json()
    found = start or end
    return found.to_json() if found else None


def place_qid(claim: Claim) -> str:
    value = claim.value
    if not isinstance(value, dict) or value.get("id") is None:
        raise Skip("bad_value")
    try:
        return check_qid(value["id"])
    except WikidataError:
        raise Skip("bad_qid") from None


def file_fetch(path: Path) -> Fetch:
    """Загрузка из файла: JSON «адрес → ответ ``Special:EntityData``» (ключ можно писать
    QID). Нет записи — ``WikidataError``, как у сбоя сети."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("файл записей: ожидается объект «адрес → запись»")
    data = {ENTITY_URL.format(qid=k) if QID.fullmatch(k) else k: v for k, v in raw.items()}

    def fetch(url: str) -> dict[str, Any]:
        if url not in data:
            raise WikidataError("записи нет в файле")
        return data[url]

    return fetch


class PlaceEnrichment:
    def __init__(self, statements: Statements, fetch: Fetch) -> None:
        self.statements = statements
        self.entities: Entities = statements.entities
        self.registry = statements.registry
        self.fetch = fetch

    # --- запуск ---

    def _kind(self, entity_type: str) -> str | None:
        if entity_type == "person":
            return "person"
        if entity_type == PLACE:
            return "place"
        if self.registry.is_a(entity_type, ["event", "phenomenon"]):
            return "event"
        return None

    def targets(self, limit: int | None = None) -> list[tuple[str, str, str]]:
        """(сущность, QID, вид) по порядку id; QID не по шаблону не обрабатывается."""
        linked = self.entities.externals(SYSTEM)
        kinds = self.entities.types(list(linked))
        found = [
            (entity_id, qid, kind)
            for entity_id, qid in sorted(linked.items())
            if QID.fullmatch(qid) and (kind := self._kind(kinds.get(entity_id, "")))
        ]
        return found[:limit] if limit is not None else found

    def run(self, *, limit: int | None = None, dry_run: bool = False) -> dict[str, Any]:
        report = Report(run_id=f"geo_{uuid.uuid4().hex[:12]}", dry_run=dry_run)
        records: dict[str, WikidataRecord | None] = {}
        for entity_id, qid, kind in self.targets(limit):
            report.entities += 1
            record = self._record(qid, records)
            if record is None:
                self._skip(report, entity_id, "item", "fetch_failed")
                continue
            for prop, spec in PROPERTIES.items():
                if spec.subjects != kind:
                    continue
                if prop == "P625":
                    self._coordinates(report, entity_id, entity_id, record)
                elif spec.relation == "lived_in" and prop == "P937":
                    claims = [c for c in record.claims.get(prop, []) if c.rank != "deprecated"]
                    for claim in claims:
                        self._placement(report, entity_id, record, prop, claim, records)
                elif (claim := record.best(prop)) is not None:
                    self._placement(report, entity_id, record, prop, claim, records)
        summary = report.to_json()
        events.emit("knowledge.geo.enriched", **summary)
        return summary

    def _record(self, qid: str, cache: dict[str, WikidataRecord | None]) -> WikidataRecord | None:
        if qid not in cache:
            try:
                cache[qid] = fetch_entity(qid, self.fetch)
            except FETCH_ERRORS:
                cache[qid] = None
        return cache[qid]

    def _skip(self, report: Report, entity_id: str, prop: str, reason: str) -> None:
        if reason == "fetch_failed":
            report.failed += 1
        else:
            report.skipped += 1
        events.emit("knowledge.geo.skipped", entity=entity_id, property=prop, reason=reason)

    @staticmethod
    def _source(qid: str, prop: str, run_id: str, **extra: Any) -> dict[str, Any]:
        return {
            "attributions": [Attribution("source", f"{SYSTEM}:{qid}", place=page_url(qid))],
            "provenance": Provenance(
                "imported", run_id=run_id, extra={"wikidata": qid, "property": prop, **extra}
            ),
            "status": "sourced",
        }

    def _write(
        self,
        report: Report,
        entity_id: str | None,
        type_: str,
        *,
        obj: str | None = None,
        value: Any = None,
        qualifiers: dict[str, Any],
        source: dict[str, Any],
    ) -> bool:
        """Новое утверждение (``True``) или уже было (``False``); отказ — ``Skip``."""
        try:
            # Отказ проверки — одно событие knowledge.statement.refused (и в сухом прогоне);
            # прошедшее проверку значение add уже не отклонит по значению.
            stored = self.statements.check_value(
                type_, value, qualifiers, source["attributions"], emit=True
            )
            if entity_id is not None and self.statements.find(
                entity_id, type_, obj=obj, value=stored, qualifiers=qualifiers
            ):
                return False
            if not report.dry_run:
                assert entity_id is not None
                self.statements.add(
                    entity_id, type_, obj=obj, value=value, qualifiers=qualifiers, **source
                )
        except StatementError:
            raise Skip("refused") from None
        return True

    def _coordinates(
        self, report: Report, owner: str, place_id: str | None, record: WikidataRecord
    ) -> None:
        """Координаты места ``place_id`` (``None`` — место будет создано в сухом прогоне);
        пропуск пишется на ``owner`` — сущность, обрабатываемую сейчас."""
        claim = record.best("P625")
        if claim is None:
            return
        try:
            written = self._write(
                report,
                place_id,
                "coordinates",
                value=geo_value(claim),
                qualifiers={},
                source=self._source(record.qid, "P625", report.run_id),
            )
        except Skip as skip:
            self._skip(report, owner, "P625", skip.reason)
            return
        report.coordinates += int(written)

    def _placement(
        self,
        report: Report,
        entity_id: str,
        record: WikidataRecord,
        prop: str,
        claim: Claim,
        records: dict[str, WikidataRecord | None],
    ) -> None:
        spec = PROPERTIES[prop]
        try:
            target = place_qid(claim)
        except Skip as skip:
            self._skip(report, entity_id, prop, skip.reason)
            return
        qualifiers: dict[str, Any] = {}
        if spec.role:
            qualifiers["place_role"] = spec.role
        when = claim_time(record, claim, spec.time)
        if when is not None:
            qualifiers["time"] = when
        place_id = self.entities.by_external(SYSTEM, target)
        place_record = None
        if place_id is None and target not in report.planned:
            # Нового места без записи не заводим: нет названия и координат.
            place_record = self._record(target, records)
            if place_record is None:
                self._skip(report, entity_id, prop, "fetch_failed")
                return
        source = self._source(record.qid, prop, report.run_id)
        try:
            self.statements.check_value(spec.relation, None, qualifiers, source["attributions"])
        except StatementError:
            self._skip(report, entity_id, prop, "refused")
            return
        if place_record is not None:
            bad = invalid_primary(PLACE, _names(place_record))
            if bad is not None:  # подпись места не прошла правило названий
                reject(PLACE, *bad)
                self._skip(report, entity_id, prop, "refused")
                return
        if place_id is None and not report.dry_run:
            place_id = self.entities.create(PLACE, _names(place_record), external={SYSTEM: target})
            # Пометка в происхождении: при откате место остаётся, и его можно посчитать.
            source = self._source(record.qid, prop, report.run_id, created_place=place_id)
        if place_record is not None:
            report.places_created += 1
            report.planned.add(target)
        try:
            written = self._write(
                report,
                entity_id if place_id is not None else None,
                spec.relation,
                obj=place_id,
                qualifiers=qualifiers,
                source=source,
            )
        except Skip as skip:
            self._skip(report, entity_id, prop, skip.reason)
            written = False
        report.placements += int(written)
        if place_record is not None:
            # Координаты нового места — в этом же проходе: своей итерации у него нет.
            self._coordinates(report, entity_id, place_id, place_record)

    # --- откат ---

    def rollback(self, run_id: str) -> dict[str, Any]:
        """Утверждения запуска удаляются (кроме проверенных человеком); созданные им места
        остаются: удаления сущностей в API нет, место без утверждений на глобус не попадает."""
        provenance = t.statements.c.provenance
        with self.statements.engine.begin() as conn:
            rows = (
                conn.execute(select(provenance).where(provenance["run_id"].as_string() == run_id))
                .scalars()
                .all()
            )
        kept = {
            p["extra"]["created_place"]
            for p in rows
            if p.get("run_id") == run_id and (p.get("extra") or {}).get("created_place")
        }
        removed = self.statements.rollback_run(run_id)["statements"]
        summary = {"run_id": run_id, "statements": removed, "places_kept": len(kept)}
        events.emit("knowledge.geo.rolled_back", **summary)
        return summary


def _names(record: WikidataRecord) -> list[tuple[str, str, str]]:
    """Названия места RU/EN из записи; нет — QID."""
    names = [
        (lang, record.labels[lang].strip(), "primary")
        for lang in ("ru", "en")
        if record.labels.get(lang, "").strip()
    ]
    return names or [("en", record.qid, "primary")]


# --- CLI ------------------------------------------------------------------------------


def _service(fetch: Fetch) -> PlaceEnrichment:
    from philograph.knowledge import schema
    from philograph.knowledge.registry import OntologyRegistry
    from philograph.platform.db import make_engine

    engine = make_engine(os.environ["PHILOGRAPH_DATABASE_URL"], [schema.SCHEMA])
    schema.migrations.upgrade(engine)
    registry = OntologyRegistry(engine)
    registry.load_defaults()
    entities = Entities(engine, registry)
    # Импорт пишет только факты с атрибуцией Wikidata: цитат нет, абзацы не нужны.
    return PlaceEnrichment(Statements(engine, registry, entities, lambda _: None), fetch)


def main(
    argv: list[str] | None = None,
    *,
    fetch: Fetch | None = None,
    service: Callable[[Fetch], PlaceEnrichment] = _service,
) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        prog="python -m philograph.knowledge.geo_enrich",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("run", help="записать места и координаты из Wikidata")
    p.add_argument("--limit", type=int, default=None, help="не больше N сущностей")
    p.add_argument("--dry-run", action="store_true", help="посчитать, ничего не записывая")
    p.add_argument("--from-file", type=Path, default=None, help="записи из файла, без сети")
    p = sub.add_parser("rollback", help="откатить запуск")
    p.add_argument("run_id")
    args = parser.parse_args(argv)

    if args.command == "run" and args.from_file is not None:
        try:
            fetch = file_fetch(args.from_file)
        except (OSError, ValueError) as exc:
            print(f"файл записей: {exc}", file=sys.stderr)
            return 2
    fetch = fetch or partial(http_fetch, wait=time.sleep)
    enrichment = service(fetch)
    if args.command == "run":
        summary = enrichment.run(limit=args.limit, dry_run=args.dry_run)
    else:
        summary = enrichment.rollback(args.run_id)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    # Журнал подключается только при запуске командой: stdout занят отчётом, события
    # идут в stderr. Вызов main() из тестов оставляет приёмник фикстуры как есть.
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    events.configure(sinks=[events.json_sink(sys.stderr)])
    sys.exit(main())
