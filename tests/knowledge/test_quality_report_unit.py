"""Юнит-тесты ``knowledge.quality_report`` (migrate-ontology-quality, задача 2.5).
Сценарные и нормативные тесты — у тестировщика."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from philograph.knowledge import schema as ks
from philograph.knowledge.entities import Entities
from philograph.knowledge.quality_report import a4_pairs, main, measure, read_only_engine
from philograph.knowledge.registry import OntologyRegistry
from philograph.platform.db import make_engine


@pytest.fixture
def db(tmp_path):
    url = f"sqlite:///{(tmp_path / 'q.db').as_posix()}"
    engine = make_engine(url, [ks.SCHEMA])
    ks.migrations.upgrade(engine)
    registry = OntologyRegistry(engine)
    registry.load_defaults()
    return url, engine, Entities(engine, registry)


def test_read_only_connection_refuses_writes(db, tmp_path):
    url, _, entities = db
    entities.create("person", [("ru", "Кант", "primary")])
    path = tmp_path / "q.knowledge.db"
    mtime = path.stat().st_mtime_ns
    engine = read_only_engine(url)
    with pytest.raises(OperationalError), engine.begin() as conn:
        conn.execute(text(f"DELETE FROM {ks.SCHEMA}.entities"))
    measure(engine)
    assert path.stat().st_mtime_ns == mtime


def test_a4_union_and_distinct(db, events):
    url, engine, entities = db
    bacon = entities.create("person", [("ru", "Бэкон", "primary")])
    francis = entities.create(
        "person", [("ru", "Фрэнсис Бэкон", "primary"), ("ru", "Бэкон", "variant")]
    )
    roger = entities.create(
        "person", [("ru", "Роджер Бэкон", "primary"), ("ru", "Бэкон", "variant")]
    )
    with engine.begin() as conn:
        for pair, status, resolution in (
            ([bacon, francis], "open", None),
            ([bacon, roger], "resolved", {"merge": False}),
        ):
            conn.execute(
                ks.review_items.insert().values(
                    kind="duplicate",
                    status=status,
                    resolution=resolution,
                    payload={"pair": pair, "reason": "review:single_name"},
                )
            )
    ro = read_only_engine(url)
    from philograph.knowledge.quality_report import _entities

    persons = [e for e in _entities(ro) if e["type"] == "person"]
    assert a4_pairs(persons, ro) == {frozenset((bacon, francis))}


def test_without_baseline_a8_not_measured_exit_1(db, capsys, events):
    url, _, entities = db
    entities.create("person", [("ru", "Кант", "primary")])
    assert main(["--json"], url=url) == 1
    result = json.loads(capsys.readouterr().out)
    assert len(result["criteria"]) == 8
    assert result["criteria"][7]["value"] is None and 8 in result["failed"]
    measured = events.where("knowledge.quality.measured")[-1]
    assert measured["a8"] is None and measured["passed"] is False


def test_save_then_baseline_on_old_schema(tmp_path, capsys, events):
    url = f"sqlite:///{(tmp_path / 'old.db').as_posix()}"
    engine = make_engine(url, [ks.SCHEMA])
    with engine.begin() as conn:
        ks.migrations._version_table.create(conn, checkfirst=True)
    # Схема до knowledge:9: миграции 1–8 без столбцов снятия.
    for m in ks.migrations._items:
        if m.version <= 8:
            with engine.begin() as conn:
                m.apply(conn)
                conn.execute(
                    ks.migrations._version_table.insert().values(version=m.version, name=m.name)
                )
    with engine.begin() as conn:
        columns = [r[1] for r in conn.exec_driver_sql(f"PRAGMA {ks.SCHEMA}.table_info(entities)")]
    if "retired_run" in columns:  # create_all создала столбцы из метаданных: убираем
        with engine.begin() as conn:
            conn.exec_driver_sql(f"ALTER TABLE {ks.SCHEMA}.entities DROP COLUMN retired_run")
            conn.exec_driver_sql(f"ALTER TABLE {ks.SCHEMA}.entities DROP COLUMN retired_reason")
    registry = OntologyRegistry(engine)
    registry.load_defaults()
    with engine.begin() as conn:
        conn.exec_driver_sql(
            f'INSERT INTO {ks.SCHEMA}.entities (id, type, "primary")'
            " VALUES ('e1', 'person', '{}')"
        )
    ks._HAS_RETIRED.clear()
    base = tmp_path / "before.json"
    assert main(["--save", str(base)], url=url) == 1
    assert base.exists()
    assert main(["--baseline", str(base), "--json"], url=url) == 1
    out = capsys.readouterr().out
    assert json.loads(out[out.index("{") :])["criteria"][7]["value"] == 0
    assert ks.migrations.pending(engine)  # схема не мигрировала


def test_bad_database_exit_2(tmp_path, capsys):
    assert main([], url=f"sqlite:///{(tmp_path / 'none.db').as_posix()}") == 2
