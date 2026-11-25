"""Юнит-тест миграции ``knowledge:8`` (add-wikidata-life-dates, задача 2.1) на SQLite.
Сценарные и нормативные тесты требований — у тестировщика."""

from __future__ import annotations

from sqlalchemy import inspect, select

from philograph.knowledge import schema as ks
from philograph.platform.db import make_engine


def test_migration_8_adds_run_actions_and_keeps_old_data(tmp_path):
    engine = make_engine(f"sqlite:///{(tmp_path / 'r.db').as_posix()}", [ks.SCHEMA])
    with engine.begin() as conn:
        ks.migrations._version_table.create(conn, checkfirst=True)
        for version in range(1, 8):
            conn.execute(
                ks.migrations._version_table.insert().values(version=version, name=f"v{version}")
            )
        ks.metadata.create_all(conn, tables=[ks.entities])
        conn.execute(
            ks.entities.insert().values(id="e_old", type="person", primary={}, redirect_to=None)
        )
    assert ks.migrations.upgrade(engine) == [8, 9]
    assert ks.migrations.upgrade(engine) == []
    with engine.begin() as conn:
        columns = {c["name"] for c in inspect(conn).get_columns("run_actions", schema=ks.SCHEMA)}
        indexed = {
            tuple(i["column_names"]) for i in inspect(conn).get_indexes("run_actions", ks.SCHEMA)
        }
        old = conn.execute(select(ks.entities.c.id)).scalars().all()
    assert columns == {"id", "run_id", "seq", "kind", "payload", "created_at"}
    assert ("run_id",) in indexed
    assert old == ["e_old"]
