"""Юнит-тесты слияния сущностей (improve-person-quality, задачи 2.2–2.3): перенос и отмена.
Сценарные и нормативные тесты требований — у тестировщика."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from philograph.knowledge import schema as t
from philograph.knowledge.statements import Attribution


def _names(onto, entity_id):
    return {(n["lang"], n["text"], n["kind"]) for n in onto.entities.get(entity_id)["names"]}


def _rows(onto, table):
    with onto.entities.engine.begin() as conn:
        return sorted(
            tuple(sorted((k, str(v)) for k, v in dict(r).items()))
            for r in conn.execute(select(table)).mappings()
        )


def _dump(onto):
    return {
        table.name: _rows(onto, table)
        for table in (
            t.entities,
            t.names,
            t.external_ids,
            t.statements,
            t.attributions,
            t.evidence,
            t.mentions,
            t.portraits,
        )
    }


def _portrait(onto, entity_id, phash):
    with onto.entities.engine.begin() as conn:
        return conn.execute(
            t.portraits.insert().values(
                entity_id=entity_id,
                file_id="f" * 64,
                width=1,
                height=1,
                license="cc0",
                source_url="https://example.org",
                origin="wikidata:Q1",
                phash=phash,
                position=0,
                status="draft",
                hidden=False,
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        ).inserted_primary_key[0]


def test_entities_merge_moves_everything_and_undo_restores(onto):
    locke = onto.entities.create(
        "person", [("en", "Locke", "primary")], external={"wikidata": "Q9353"}
    )
    lokk = onto.entities.create("person", [("ru", "Локк", "primary")], external={"viaf": "1"})
    work = onto.thing("work", "Опыт о человеческом разумении")
    holds = onto.statements.add(
        work,
        "author",
        obj=onto.thing("person", "Кто-то"),
        attributions=[Attribution("entity", lokk)],
    )
    same = _portrait(onto, locke, "aaaa")
    other = _portrait(onto, lokk, "aaaa")
    moved = _portrait(onto, lokk, "bbbb")
    before = _dump(onto)

    merge_id = onto.entities.merge(locke, lokk)

    assert _names(onto, locke) == {("ru", "Локк", "primary"), ("en", "Locke", "variant")}
    assert onto.entities.by_external("viaf", "1") == locke
    who = onto.statements.get(holds)["attributions"][0]
    assert (who["who_kind"], who["who"]) == ("entity", locke)
    with onto.entities.engine.begin() as conn:
        owner = dict(conn.execute(select(t.portraits.c.id, t.portraits.c.entity_id)).all())
    assert owner == {same: locke, other: lokk, moved: locke}

    onto.entities.undo_merge(merge_id)
    assert _dump(onto) == before


def test_merge_keeps_primary_of_kept_when_no_russian(onto):
    a = onto.entities.create("person", [("en", "Berkeley", "primary")])
    b = onto.entities.create("person", [("en", "George Berkeley", "primary")])
    onto.entities.merge(a, b)
    assert _names(onto, a) == {("en", "Berkeley", "primary"), ("en", "George Berkeley", "variant")}


def test_old_merge_record_undo_with_defaults(onto):
    a = onto.thing("concept", "Субстанция")
    b = onto.thing("concept", "Substance")
    merge_id = onto.entities.merge(a, b)
    with onto.entities.engine.begin() as conn:  # запись старого формата: только четыре ключа
        moved = conn.scalar(select(t.merges.c.moved).where(t.merges.c.id == merge_id))
        old = {k: moved[k] for k in ("names", "subject", "object", "mentions")}
        conn.execute(t.merges.update().where(t.merges.c.id == merge_id).values(moved=old))
    onto.entities.undo_merge(merge_id)
    assert onto.entities.get(b)["id"] == b
