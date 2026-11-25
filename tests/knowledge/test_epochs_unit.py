"""Юнит-тесты модуля принадлежности к эпохе (``knowledge/epochs.py``)."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from philograph.knowledge import schema as t
from philograph.knowledge.dates import FuzzyDate
from philograph.knowledge.epochs import EpochMembership, membership
from philograph.knowledge.snapshot import Snapshots
from philograph.knowledge.statements import Attribution

COMMON = [Attribution("common")]


@pytest.fixture
def world(onto):
    w = {
        "sci": onto.thing("epoch", "Научная революция", "1543–1687"),
        "enl": onto.thing("epoch", "Просвещение", "1680–1800"),
        "locke": onto.person("Локк", "1632", "1704"),
        "berkeley": onto.person("Беркли", "1685", "1753"),
    }
    return w


def build(onto, clock) -> EpochMembership:
    snap, _ = Snapshots(onto.statements.engine, clock).get()
    return EpochMembership(snap, onto.registry)


def belongs(onto, subject, epoch):
    return onto.statements.add(subject, "belongs_to_epoch", obj=epoch, attributions=COMMON)


def test_middle_of_life(onto, clock, world):
    m = build(onto, clock)
    assert m.of(world["locke"]) == [(world["sci"], "dates")]  # середина 1668
    assert m.of(world["berkeley"]) == [(world["enl"], "dates")]  # середина 1719


def test_explicit_wins_over_dates(onto, clock, world):
    belongs(onto, world["locke"], world["enl"])
    m = build(onto, clock)
    assert m.of(world["locke"]) == [(world["enl"], "explicit")]
    assert (world["locke"], "explicit") in m.members(world["enl"])
    assert all(e != world["locke"] for e, _ in m.members(world["sci"]))


def test_rejected_and_deprecated_explicit_ignored(onto, clock, world):
    onto.statements.reject(belongs(onto, world["locke"], world["enl"]), "operator")
    onto.statements.set_rank(belongs(onto, world["berkeley"], world["sci"]), "deprecated", "op")
    m = build(onto, clock)
    assert m.of(world["locke"]) == [(world["sci"], "dates")]
    assert m.of(world["berkeley"]) == [(world["enl"], "dates")]


def test_overlap_and_half_open_end(onto, clock, world):
    nantes = onto.thing("event", "Отмена Нантского эдикта", "1685")
    principia = onto.thing("idea_event", "Выход «Начал» Ньютона", "1687")
    start = onto.thing("event", "Начало", "1543")
    m = build(onto, clock)
    assert m.of(nantes) == [(world["sci"], "dates"), (world["enl"], "dates")]
    assert m.of(principia) == [(world["enl"], "dates")]  # 1687 — конец, не входит
    assert m.of(start) == [(world["sci"], "dates")]  # начало входит


def test_rounded_fuzzy_epoch_start(onto, clock):
    epoch = onto.entities.create("epoch", [("ru", "Эпоха", "primary")])
    fuzzy = FuzzyDate(1679, 1680, 1800, 1800, "approx", "1679/1680–1800").to_json()
    onto.statements.add(epoch, "dating", value=fuzzy, attributions=COMMON)
    before = onto.thing("event", "Событие 1679", "1679")
    on = onto.thing("event", "Событие 1680", "1680")
    m = build(onto, clock)
    assert m.span(epoch) == (1680, 1800)
    assert m.of(before) == [] and m.of(on) == [(epoch, "dates")]


def test_undated_groups_ideas_only_explicit(onto, clock, world):
    anon = onto.person("Анонимный схоласт")
    empiricism = onto.thing("group", "Эмпиризм")
    onto.statements.add(world["locke"], "member_of", obj=empiricism, attributions=COMMON)
    experience = onto.thing("concept", "Опыт")
    essay = onto.thing("work", "Опыт о человеческом разумении", "1690")
    onto.statements.add(essay, "discusses", obj=experience, attributions=COMMON)
    baroque = onto.thing("epoch", "Барокко")
    term = onto.thing("term", "tabula rasa")
    m = build(onto, clock)
    for entity in (anon, empiricism, experience, baroque, term, world["enl"]):
        assert m.of(entity) == []
    assert m.members(baroque) == []
    assert m.of(essay) == [(world["enl"], "dates")]  # труд — по датам, идея из него — нет
    belongs(onto, empiricism, baroque)
    m = build(onto, clock)
    assert m.of(empiricism) == [(baroque, "explicit")]
    assert m.members(baroque) == [(empiricism, "explicit")]


def test_several_explicit_ordered_undated_last(onto, clock, world):
    baroque = onto.thing("epoch", "Барокко")
    for epoch in (baroque, world["enl"], world["sci"]):
        belongs(onto, world["locke"], epoch)
    m = build(onto, clock)
    assert m.of(world["locke"]) == [
        (world["sci"], "explicit"),
        (world["enl"], "explicit"),
        (baroque, "explicit"),
    ]
    assert m.epochs() == [world["sci"], world["enl"], baroque]


def test_derived_once_and_nothing_written(onto, clock, world):
    def count():
        with onto.statements.engine.begin() as conn:
            return conn.scalar(select(func.count()).select_from(t.statements))

    before = count()
    snap, _ = Snapshots(onto.statements.engine, clock).get()
    assert membership(snap, onto.registry) is membership(snap, onto.registry)
    assert count() == before
