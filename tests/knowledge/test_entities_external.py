"""Юнит-тесты ``Entities.add_external`` и ``Entities.externals``."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from philograph.knowledge import schema as t
from philograph.knowledge.entities import DuplicateEntity, EntityNotFound


def count(onto) -> int:
    with onto.entities.engine.begin() as conn:
        return conn.scalar(select(func.count()).select_from(t.external_ids))


def test_add_external(onto):
    epoch = onto.thing("epoch", "Просвещение")
    assert onto.entities.add_external(epoch, "wikidata", "Q12539") is True
    assert onto.entities.by_external("wikidata", "Q12539") == epoch
    assert onto.entities.add_external(epoch, "wikidata", "Q12539") is False  # повтор — без записи
    assert count(onto) == 1
    assert onto.entities.externals("wikidata") == {epoch: "Q12539"}


def test_add_external_duplicate(onto):
    kant = onto.person("Кант", wikidata="Q9312")
    epoch = onto.thing("epoch", "Просвещение")
    before = count(onto)
    with pytest.raises(DuplicateEntity) as exc:
        onto.entities.add_external(epoch, "wikidata", "Q9312")
    assert exc.value.existing == kant
    assert count(onto) == before


def test_add_external_unknown_entity(onto):
    with pytest.raises(EntityNotFound):
        onto.entities.add_external("e_missing", "wikidata", "Q1")


def test_add_external_follows_merge(onto):
    a = onto.thing("epoch", "Просвещение")
    b = onto.thing("epoch", "Эпоха Просвещения")
    onto.entities.merge(a, b)
    onto.entities.add_external(b, "wikidata", "Q12539")
    assert onto.entities.by_external("wikidata", "Q12539") == a
    assert onto.entities.externals("wikidata") == {a: "Q12539"}
