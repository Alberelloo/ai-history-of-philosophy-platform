"""Замер качества онтологии А1–А8 (спецификация ontology-migration, «Замер качества
онтологии»). Только чтение: соединение на чтение (SQLite ``mode=ro``, Postgres
``default_transaction_read_only``), миграции схемы не выполняются, работает и на схеме до
``knowledge:9`` (снятых там нет) — чтобы сохранить базу сравнения до миграции.

А6 и А7 считаются теми же объектами сервиса знаний, что отвечают на ``/map`` и
``/catalog``: ``SectionMap.result(textbook=None)`` и ``Catalog.list`` (все страницы).

    python -m philograph.knowledge.quality_report [--save before.json] [--baseline before.json] [--json]

Код выхода: 0 — все пороги выполнены, 1 — нет, 2 — ошибка базы или аргументов.
"""  # noqa: E501

from __future__ import annotations

import argparse
import json
import operator
import os
import sqlite3
import sys
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from philograph.knowledge import integrity
from philograph.knowledge import schema as t
from philograph.knowledge.catalog import Catalog
from philograph.knowledge.dedupe import duplicate_items
from philograph.knowledge.entities import Entities
from philograph.knowledge.map import SectionMap
from philograph.knowledge.naming import check_name, is_russian, normalize
from philograph.knowledge.registry import OntologyRegistry
from philograph.knowledge.snapshot import Snapshots, label_of
from philograph.knowledge.statements import Statements
from philograph.platform import events

events.define(
    "knowledge.quality.measured",
    "info",
    "Замер качества онтологии",
    required=("a1", "a2", "a3", "a4", "a5", "a6", "a7", "a8", "passed", "failed"),
)

SOURCE, PERSON, PHILOSOPHER = "source", "person", "philosopher"


@dataclass(frozen=True)
class Criterion:
    number: int
    name: str
    threshold: float
    compare: Callable[[float, float], bool]
    sign: str


CRITERIA = (
    Criterion(1, "доля русских названий (кроме источников)", 0.90, operator.ge, "≥"),
    Criterion(2, "названия-номера (кроме источников)", 0, operator.eq, "="),
    Criterion(3, "персоны с названием не по правилу", 0, operator.eq, "="),
    Criterion(4, "пары возможных дублей персон", 0, operator.eq, "="),
    Criterion(5, "персоны с основной датой", 20, operator.ge, "≥"),
    Criterion(6, "философы на карте всей библиотеки", 10, operator.ge, "≥"),
    Criterion(7, "элементы справочника с названием не по правилу", 0, operator.eq, "="),
    Criterion(8, "потерянные утверждения и атрибуции", 0, operator.eq, "="),
)


# --- соединение на чтение ------------------------------------------------------------


def read_only_engine(url: str) -> Engine:
    """Подключение, через которое база не даёт писать; схема не создаётся и не мигрирует."""
    if url.startswith("sqlite:///"):
        path = Path(url.removeprefix("sqlite:///"))
        target = path.with_suffix(f".{t.SCHEMA}.db")
        for f in (path, target):
            if not f.exists():
                raise FileNotFoundError(f"нет файла базы {f}")

        def connect() -> sqlite3.Connection:
            conn = sqlite3.connect(
                f"{path.resolve().as_uri()}?mode=ro", uri=True, check_same_thread=False
            )
            conn.execute(f"ATTACH DATABASE '{target.resolve().as_uri()}?mode=ro' AS {t.SCHEMA}")
            return conn

        return create_engine("sqlite://", creator=connect)
    if url.startswith("sqlite"):
        raise ValueError("замер на чтение — только файловая база SQLite")
    engine = create_engine(url, connect_args={"options": "-c default_transaction_read_only=on"})

    @event.listens_for(engine, "connect")
    def _read_only(dbapi_conn, _record) -> None:  # pragma: no cover - Postgres
        cur = dbapi_conn.cursor()
        cur.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
        cur.close()

    return engine


# --- критерии -------------------------------------------------------------------------


def _entities(engine: Engine) -> list[dict[str, Any]]:
    with engine.begin() as conn:
        e = t.entities.c  # столбцы явно: на схеме до knowledge:9 столбцов снятия нет
        rows = (
            conn.execute(select(e.id, e.type, e.primary).where(t.active_in(conn))).mappings().all()
        )
        names: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in conn.execute(select(t.names).order_by(t.names.c.id)).mappings():
            names[r["entity_id"]].append(dict(r))
    return [
        {
            "id": r["id"],
            "type": r["type"],
            "dates": (r["primary"] or {}).get("dates"),
            "names": names.get(r["id"], []),
            "label": label_of(names.get(r["id"], []), r["id"]),
        }
        for r in rows
    ]


def a4_pairs(persons: list[dict[str, Any]], engine: Engine) -> set[frozenset[str]]:
    """Пары возможных дублей (А4): совпало основное одной с любым названием другой ∪ открытые
    пункты ``duplicate`` — минус закрытые решением «разные»."""
    ids = {p["id"] for p in persons}
    by_name: dict[str, set[str]] = defaultdict(set)
    for p in persons:
        for n in p["names"]:
            if normalize(n["text"]):
                by_name[normalize(n["text"])].add(p["id"])
    pairs: set[frozenset[str]] = set()
    for p in persons:
        for n in p["names"]:
            if n["kind"] == "primary":
                for other in by_name.get(normalize(n["text"]), ()):
                    if other != p["id"]:
                        pairs.add(frozenset((p["id"], other)))
    open_, distinct = duplicate_items(engine)
    pairs |= {frozenset(pair) for pair in open_ if set(pair) <= ids and pair[0] != pair[1]}
    return pairs - {frozenset(pair) for pair in distinct}


def _services(engine: Engine) -> tuple[SectionMap, Catalog]:
    registry = OntologyRegistry(engine)  # только чтение реестра: load_defaults не вызывается
    entities = Entities(engine, registry)
    statements = Statements(engine, registry, entities, lambda _: None)
    snapshots = Snapshots(engine)
    return SectionMap(statements, snapshots=snapshots), Catalog(snapshots, registry, entities)


def a6(engine: Engine) -> int:
    section_map, _ = _services(engine)
    result, _ = section_map.result(textbook=None)
    return sum(PHILOSOPHER in (p.get("roles") or []) for p in result["people"])


def catalog_items(engine: Engine) -> list[dict[str, Any]]:
    _, catalog = _services(engine)
    items: list[dict[str, Any]] = []
    page = 1
    while True:
        result = catalog.list(lang="ru", page=str(page), limit="60")
        items.extend(result["items"])
        if not result["items"] or len(items) >= result["total"]:
            return items
        page += 1


def measure(engine: Engine, baseline: integrity.Baseline | None = None) -> dict[str, Any]:
    entities = _entities(engine)
    named = [e for e in entities if e["type"] != SOURCE]
    persons = [e for e in entities if e["type"] == PERSON]
    values: dict[int, float | None] = {
        1: round(sum(is_russian(e["label"]) for e in named) / len(named), 4) if named else 1.0,
        2: sum(check_name(e["type"], e["label"]) == "number" for e in named),
        3: sum(check_name(PERSON, p["label"]) is not None for p in persons),
        4: len(a4_pairs(persons, engine)),
        5: sum(p["dates"] is not None for p in persons),
        6: a6(engine),
        7: sum(check_name(i["type"], i["label"]) is not None for i in catalog_items(engine)),
        8: None,
    }
    if baseline is not None:
        lost = integrity.compare(baseline, engine)
        values[8] = len(lost["lost"]) + len(lost["lost_attributions"])
    rows = []
    for c in CRITERIA:
        value = values[c.number]
        ok = value is not None and c.compare(value, c.threshold)
        rows.append(
            {
                "criterion": f"А{c.number}",
                "name": c.name,
                "value": value,
                "threshold": f"{c.sign} {c.threshold:g}",
                "passed": ok,
            }
        )
    failed = [c.number for c, r in zip(CRITERIA, rows, strict=True) if not r["passed"]]
    result = {"criteria": rows, "passed": not failed, "failed": failed}
    events.emit(
        "knowledge.quality.measured",
        **{f"a{n}": values[n] for n in range(1, 9)},
        passed=not failed,
        failed=failed,
    )
    return result


def table(result: dict[str, Any]) -> str:
    lines = ["критерий | значение | порог | итог"]
    for r in result["criteria"]:
        value = "не измерено" if r["value"] is None else f"{r['value']:g}"
        verdict = "выполнен" if r["passed"] else "не выполнен"
        lines.append(f"{r['criterion']} {r['name']} | {value} | {r['threshold']} | {verdict}")
    lines.append("итог: " + ("выполнен" if result["passed"] else "не выполнен"))
    return "\n".join(lines)


def main(argv: list[str] | None = None, *, url: str | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        prog="python -m philograph.knowledge.quality_report",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--save", type=Path, default=None, help="сохранить базу сравнения")
    parser.add_argument("--baseline", type=Path, default=None, help="база сравнения для А8")
    parser.add_argument("--json", action="store_true", help="результат в JSON")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    try:
        engine = read_only_engine(url or os.environ["PHILOGRAPH_DATABASE_URL"])
        base = integrity.load(args.baseline) if args.baseline else None
        result = measure(engine, base)
        if args.save is not None:
            integrity.save(integrity.baseline(engine), args.save)
    except (SQLAlchemyError, OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
        print(f"замер: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else table(result))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
