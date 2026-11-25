"""Юнит-тесты ``knowledge.integrity`` (migrate-ontology-quality, задача 2.2).
Сценарные и нормативные тесты — у тестировщика."""

from __future__ import annotations

from sqlalchemy import delete, update

from philograph.knowledge import integrity
from philograph.knowledge import schema as ks
from philograph.knowledge.statements import Attribution

SRC = [Attribution("source", "s1")]


def world(onto):
    e = onto.entities
    a = e.create("person", [("en", "Berkeley", "primary")])
    b = e.create("person", [("en", "Berkeley", "primary")])
    idea = e.create("position", [("ru", "Имматериализм", "primary")])
    junk = e.create("position", [("ru", "Мусор", "primary")])
    s1 = onto.statements.add(a, "holds", obj=idea, attributions=SRC)
    s2 = onto.statements.add(b, "holds", obj=idea, attributions=[Attribution("source", "s2")])
    s3 = onto.statements.add(a, "holds", obj=junk, attributions=SRC)
    loop = onto.statements.add(a, "studied_with", obj=b, attributions=SRC)
    return {"a": a, "b": b, "idea": idea, "junk": junk, "s1": s1, "s2": s2, "s3": s3, "loop": loop}


def test_unchanged_has_no_losses(onto):
    world(onto)
    base = integrity.baseline(onto.entities.engine)
    result = integrity.compare(base, onto.entities.engine)
    assert result == {
        "lost": [],
        "lost_attributions": [],
        "folded": 0,
        "dropped_garbage": 0,
        "loops": 0,
    }


def test_merge_fold_loop_and_garbage_are_not_losses(onto):
    w = world(onto)
    engine = onto.entities.engine
    base = integrity.baseline(engine)
    onto.statements.merge_entities(w["a"], w["b"], reason="merge:name")
    with engine.begin() as conn:
        conn.execute(
            update(ks.entities).where(ks.entities.c.id == w["junk"]).values(retired_run="mig_1")
        )
    result = integrity.compare(base, engine)
    assert result["lost"] == [] and result["lost_attributions"] == []
    assert (result["folded"], result["dropped_garbage"], result["loops"]) == (1, 1, 1)


def test_deleted_statement_and_attribution_are_losses(onto, tmp_path):
    w = world(onto)
    engine = onto.entities.engine
    path = tmp_path / "base.json"
    integrity.save(integrity.baseline(engine), path)
    base = integrity.load(path)
    with engine.begin() as conn:
        conn.execute(delete(ks.statements).where(ks.statements.c.id == w["s3"]))
        conn.execute(delete(ks.attributions).where(ks.attributions.c.statement_id == w["s2"]))
    result = integrity.compare(base, engine)
    assert result["lost"] == [w["s3"]]
    assert result["lost_attributions"] == [[w["s2"], "source", "s2", "asserts"]]


def test_rejected_statement_is_lost(onto):
    w = world(onto)
    engine = onto.entities.engine
    base = integrity.baseline(engine)
    with engine.begin() as conn:
        conn.execute(
            update(ks.statements).where(ks.statements.c.id == w["s1"]).values(status="rejected")
        )
    assert integrity.compare(base, engine)["lost"] == [w["s1"]]


def test_retired_author_attribution_is_not_lost(onto):
    w = world(onto)
    engine = onto.entities.engine
    other = onto.entities.create("position", [("ru", "Скептицизм", "primary")])
    s = onto.statements.add(
        w["a"], "holds", obj=other, attributions=[Attribution("entity", w["b"])]
    )
    base = integrity.baseline(engine)
    with engine.begin() as conn:
        conn.execute(update(ks.entities).where(ks.entities.c.id == w["b"]).values(retired_run="m"))
        conn.execute(delete(ks.attributions).where(ks.attributions.c.statement_id == s))
    assert integrity.compare(base, engine)["lost_attributions"] == []


def test_substituted_target_is_loss(onto):
    """О20: цель жива, но тип другой или концы — не образы исходных: потеря (ядро А8)."""
    w = world(onto)
    engine = onto.entities.engine
    base = integrity.baseline(engine)
    with engine.begin() as conn:
        conn.execute(
            update(ks.statements).where(ks.statements.c.id == w["s1"]).values(object=w["junk"])
        )
        conn.execute(
            update(ks.statements).where(ks.statements.c.id == w["s2"]).values(type="rejects")
        )
    assert sorted(integrity.compare(base, engine)["lost"]) == sorted([w["s1"], w["s2"]])


def test_has_retired_cached_per_engine(onto, monkeypatch):
    """О20: проверка схемы — один раз на движок."""
    import sqlalchemy

    engine = onto.entities.engine
    calls = []
    real = sqlalchemy.inspect
    monkeypatch.setattr(sqlalchemy, "inspect", lambda *a, **k: calls.append(a) or real(*a, **k))
    ks._HAS_RETIRED.discard(engine)
    for _ in range(3):
        with engine.begin() as conn:
            assert ks.has_retired(conn)
    assert len(calls) == 1


def test_symmetric_fold_with_swapped_ends_is_not_loss(onto):
    """Ревью О20: «Hume ↔ Кант» и «Кант ↔ Юм» (симметричная связь реестра) при слиянии
    Hume → Юм сворачиваются в одно; порядок концов у цели не тот — это не потеря."""
    e = onto.entities
    hume = e.create("person", [("en", "Hume", "primary")])
    yum = e.create("person", [("ru", "Юм", "primary")])
    kant = e.create("person", [("ru", "Кант", "primary")])
    assert onto.registry.relation("corresponded").get("symmetric")
    s1 = onto.statements.add(hume, "corresponded", obj=kant, attributions=SRC)
    s2 = onto.statements.add(
        kant, "corresponded", obj=yum, attributions=[Attribution("source", "s2")]
    )
    engine = e.engine
    base = integrity.baseline(engine)
    onto.statements.merge_entities(yum, hume, reason="merge:name")
    result = integrity.compare(base, engine)
    assert result["lost"] == [] and result["lost_attributions"] == []
    assert result["folded"] == 1
    assert {s1, s2} == set(base.statements)
