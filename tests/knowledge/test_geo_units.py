"""Юнит-тесты разработчика add-geo-timeline: реестр, координаты, слой мест, обогащение.

Сценарные и нормативные тесты по спецификации ``geo-timeline`` пишет тестировщик; здесь —
проверки модулей на синтетических записях. QID в фикстурах — только метки.
"""

from __future__ import annotations

from sqlalchemy import select, update

from philograph.knowledge import schema as t

# --- 2.1: дозагрузка уточнителей существующей связи ------------------------------------


def _old_registry(onto, code: str, **spec_changes) -> None:
    """Реестр «прежней версии»: у связи ``code`` другие поля спецификации."""
    rt = t.relation_types
    with onto.registry.engine.begin() as conn:
        spec = conn.execute(select(rt.c.spec).where(rt.c.code == code)).scalar_one()
        conn.execute(update(rt).where(rt.c.code == code).values(spec={**spec, **spec_changes}))
    onto.registry._cache = None


def test_missing_qualifiers_are_appended_operator_changes_kept(onto, events):
    _old_registry(onto, "lived_in", qualifiers=["time"], object_types=["place", "group"])
    before = onto.registry.version()
    events.clear()

    onto.registry.load_defaults()

    spec = onto.registry.relation("lived_in")
    assert spec["qualifiers"][0] == "time"  # прежнее — на месте и первым
    assert set(spec["qualifiers"]) == {"time", "place_role"}
    assert spec["object_types"] == ["place", "group"]  # тип конца оператора сохранён
    assert onto.registry.version() == before + 1
    [changed] = events.of("knowledge.registry.changed")
    assert "lived_in" in changed["change"]
    onto.registry.load_defaults()
    assert onto.registry.version() == before + 1  # повторный старт ничего не меняет


def test_qualifier_added_by_operator_is_not_removed(onto):
    _old_registry(onto, "lived_in", qualifiers=["time", "role"])
    onto.registry.load_defaults()
    assert onto.registry.relation("lived_in")["qualifiers"] == ["time", "role", "place_role"]


# --- 2.2: реестр — вид места и координаты ------------------------------------------------


def test_registry_place_role_and_coordinates(onto):
    reg = onto.registry
    assert reg.relation("lived_in")["qualifiers"] == ["time", "place_role"]
    assert reg._load()["qualifiers"]["place_role"]["allowed"] == [
        "birth",
        "death",
        "activity",
        "residence",
    ]
    coords = reg.relation("coordinates")
    assert coords["value_kind"] == "geo"
    assert coords["subject_types"] == ["place"]
    assert coords["requires_attribution"] is True
    assert "requires_attribution" not in reg.relation("lived_in")  # флаг только где задан
    reg.check_qualifiers("lived_in", {"place_role": "birth", "time": {}})
