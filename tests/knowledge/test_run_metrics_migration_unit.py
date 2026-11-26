"""Юнит-тест миграции ``knowledge:10`` (метрики запусков) на SQLite: база до миграции."""

from __future__ import annotations

from sqlalchemy import inspect, text

from philograph.knowledge import schema
from philograph.platform.db import make_engine


def test_adds_columns_and_keeps_rows():
    engine = make_engine("sqlite://", ["knowledge"])
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE knowledge.filling_runs (run_id VARCHAR(64) PRIMARY KEY, "
                "kind VARCHAR(30) NOT NULL, target VARCHAR(100), model VARCHAR(100), "
                "template_version VARCHAR(40), started_at DATETIME NOT NULL, "
                "finished_at DATETIME, created INTEGER NOT NULL, dropped INTEGER NOT NULL, "
                "cost_usd JSON, status VARCHAR(20) NOT NULL)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO knowledge.filling_runs VALUES "
                "('r1', 'extraction', 'v1', 'main', NULL, '2026-11-01', NULL, 3, 4, NULL, 'done')"
            )
        )
        schema._run_metrics(conn)
        schema._run_metrics(conn)  # повтор ничего не ломает
        columns = {c["name"] for c in inspect(conn).get_columns("filling_runs", schema="knowledge")}
        row = conn.execute(text("SELECT * FROM knowledge.filling_runs")).mappings().one()
    assert {name for name, _ in schema.RUN_METRICS} <= columns
    assert set(schema.filling_runs.c.keys()) == columns
    assert (row["run_id"], row["created"], row["dropped"]) == ("r1", 3, 4)
    assert row["drop_reasons"] is None and row["extractor"] is None


def test_fresh_database_has_columns():
    engine = make_engine("sqlite://", ["knowledge"])
    schema.migrations.upgrade(engine)
    with engine.begin() as conn:
        columns = {c["name"] for c in inspect(conn).get_columns("filling_runs", schema="knowledge")}
    assert set(schema.filling_runs.c.keys()) == columns
