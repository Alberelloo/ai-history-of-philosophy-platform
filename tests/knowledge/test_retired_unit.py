"""Юнит-тесты снятия сущностей (migrate-ontology-quality, задача 2.1): схема ``knowledge:9``,
условие ``schema.active`` и фильтр показа. Сценарные и нормативные тесты — у тестировщика."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import func, inspect, select, update

from philograph.knowledge import schema as ks
from philograph.knowledge.app import build_app
from philograph.knowledge.cards import Cards
from philograph.knowledge.snapshot import fingerprint, load
from philograph.knowledge.statements import Attribution
from philograph.platform.db import make_engine


def retire(onto, entity_id, reason="number", run_id="mig_1"):
    with onto.entities.engine.begin() as conn:
        conn.execute(
            update(ks.entities)
            .where(ks.entities.c.id == entity_id)
            .values(retired_run=run_id, retired_reason=reason)
        )


def snapshot(onto):
    engine = onto.entities.engine
    return load(engine, fingerprint(engine), datetime(2026, 1, 1, tzinfo=UTC))


def test_migration_9_adds_columns_to_old_entities(tmp_path):
    engine = make_engine(f"sqlite:///{(tmp_path / 'r.db').as_posix()}", [ks.SCHEMA])
    with engine.begin() as conn:
        ks.migrations._version_table.create(conn, checkfirst=True)
        for version in range(1, 9):
            conn.execute(
                ks.migrations._version_table.insert().values(version=version, name=f"v{version}")
            )
        conn.exec_driver_sql(
            f"CREATE TABLE {ks.SCHEMA}.entities (id VARCHAR(40) PRIMARY KEY, type VARCHAR(50),"
            ' "primary" JSON, redirect_to VARCHAR(40))'
        )
        conn.exec_driver_sql(
            f"INSERT INTO {ks.SCHEMA}.entities VALUES ('e_old', 'person', '{{}}', NULL)"
        )
    assert ks.migrations.upgrade(engine) == [9, 10]  # 10 — метрики запусков
    with engine.begin() as conn:
        columns = {c["name"] for c in inspect(conn).get_columns("entities", schema=ks.SCHEMA)}
        active = conn.scalar(select(func.count()).select_from(ks.entities).where(ks.active()))
    assert {"retired_run", "retired_reason"} <= columns
    assert active == 1


def test_retired_hidden_from_snapshot_about_find_externals(onto):
    kant = onto.entities.create("person", [("ru", "Кант", "primary")], external={"wikidata": "Q1"})
    junk = onto.entities.create(
        "position", [("ru", "Мусор", "primary")], external={"wikidata": "Q2"}
    )
    lord = onto.entities.create("person", [("ru", "Лорд", "primary")])
    idea = onto.entities.create("position", [("ru", "Идея", "primary")])
    src = [Attribution("source", "s1")]
    to_junk = onto.statements.add(kant, "holds", obj=junk, attributions=src)
    by_lord = onto.statements.add(
        kant, "holds", obj=idea, attributions=[Attribution("entity", lord)]
    )
    exp = onto.entities.create("position", [("ru", "Опыт", "primary")])
    both = onto.statements.add(
        kant, "holds", obj=exp, attributions=[Attribution("entity", lord), *src]
    )
    retire(onto, junk)
    retire(onto, lord, "not_a_name")
    snap = snapshot(onto)
    assert junk not in snap.entities and lord not in snap.entities
    shown = {s["id"]: s for s in snap.statements}
    assert to_junk not in shown and by_lord not in shown
    assert [a["who"] for a in shown[both]["attributions"]] == ["s1"]
    about = {s["id"]: s for s in onto.statements.about(kant)}
    assert set(about) == {both}
    assert [a["who"] for a in about[both]["attributions"]] == ["s1"]
    assert onto.entities.find("Мусор") == []
    assert onto.entities.externals("wikidata") == {kant: "Q1"}
    assert onto.entities.get(junk)["retired"] == {"run_id": "mig_1", "reason": "number"}
    assert "retired" not in onto.entities.get(kant)
    # Строки в базе целы.
    with onto.entities.engine.begin() as conn:
        assert conn.scalar(select(func.count()).select_from(ks.statements)) == 3


def test_retire_changes_fingerprint(onto):
    junk = onto.entities.create("position", [("ru", "Мусор", "primary")])
    before = fingerprint(onto.entities.engine)
    retire(onto, junk)
    assert fingerprint(onto.entities.engine) != before


def test_card_of_retired_is_404(onto):
    junk = onto.entities.create("position", [("ru", "Мусор", "primary")])
    retire(onto, junk)
    cards = Cards(onto.statements, None, None)
    client = TestClient(build_app(onto.statements, cards=cards))
    response = client.get(f"/v1/entities/{junk}/card")
    assert response.status_code == 404
    assert response.json()["kind"] == "entity_not_found"
