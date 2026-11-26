"""Юнит-тесты точек правила названий в ``Entities``: язык по письменности, отказ, смена
основного названия. Сценарии требований ``entity-naming`` — у тестировщика."""

from __future__ import annotations

import pytest

from philograph.knowledge.naming import InvalidName


def _names(onto, entity_id):
    return {(n["lang"], n["text"], n["kind"]) for n in onto.entities.get(entity_id)["names"]}


def test_create_sets_lang_by_script(onto):
    entity = onto.entities.create("person", [("ru", "Locke", "primary"), ("en", "Локк", "variant")])
    assert _names(onto, entity) == {("en", "Locke", "primary"), ("ru", "Локк", "variant")}


def test_create_rejects_primary(onto, events):
    before = len(events.of("knowledge.entity.created"))
    with pytest.raises(InvalidName) as exc:
        onto.entities.create("concept", [("ru", "20.1", "primary")])
    assert exc.value.reason == "number"
    assert [e.fields["reason"] for e in events.of("knowledge.entity.rejected")] == ["number"]
    assert len(events.of("knowledge.entity.created")) == before


def test_source_is_exempt(onto):
    entity = onto.entities.source_entity("src1", "20.1")
    assert _names(onto, entity) == {("und", "20.1", "primary")}


def test_add_name_lang_and_check(onto):
    entity = onto.entities.create("person", [("ru", "Кант", "primary")])
    onto.entities.add_name(entity, "ru", "Kant")
    assert ("en", "Kant", "variant") in _names(onto, entity)
    with pytest.raises(InvalidName):
        onto.entities.add_name(entity, "ru", "поэт", kind="primary")


def test_set_primary_name_keeps_id(onto, events):
    entity = onto.entities.create("person", [("en", "Plato", "primary")])
    onto.entities.set_primary_name(entity, "ru", "Платон")
    assert onto.entities.get(entity)["id"] == entity
    assert _names(onto, entity) == {("ru", "Платон", "primary"), ("en", "Plato", "variant")}
    (renamed,) = events.of("knowledge.entity.renamed")
    assert {k: renamed.fields[k] for k in ("entity_id", "lang", "previous_lang")} == {
        "entity_id": entity,
        "lang": "ru",
        "previous_lang": "en",
    }


def test_set_primary_name_promotes_variant(onto):
    entity = onto.entities.create(
        "person", [("ru", "Plato", "primary"), ("ru", "Платон", "variant")]
    )
    onto.entities.set_primary_name(entity, "ru", "Платон")
    assert _names(onto, entity) == {("ru", "Платон", "primary"), ("en", "Plato", "variant")}


def test_set_primary_name_rejected(onto, events):
    entity = onto.entities.create("person", [("en", "Plato", "primary")])
    with pytest.raises(InvalidName):
        onto.entities.set_primary_name(entity, "ru", "поэт")
    assert _names(onto, entity) == {("en", "Plato", "primary")}
    assert events.of("knowledge.entity.renamed") == []
