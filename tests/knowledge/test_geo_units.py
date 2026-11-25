"""Юнит-тесты разработчика add-geo-timeline: реестр, координаты, слой мест, обогащение.

Сценарные и нормативные тесты по спецификации ``geo-timeline`` пишет тестировщик; здесь —
проверки модулей на синтетических записях. QID в фикстурах — только метки.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select, update

from philograph.knowledge import schema as t
from philograph.knowledge.statements import Attribution, Provenance, StatementError

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


# --- 2.3: координаты в утверждениях -------------------------------------------------------

WD = [Attribution("source", "wikidata:Q1", place="https://www.wikidata.org/wiki/Q1")]
IMPORTED = Provenance("imported", run_id="geo_test")


def coords(onto, place, lat, lon, attributions=WD):
    return onto.statements.add(
        place,
        "coordinates",
        value={"lat": lat, "lon": lon},
        attributions=attributions,
        provenance=IMPORTED,
        status="sourced",
    )


def test_coordinates_rounded_before_key(onto, events):
    place = onto.thing("place", "Кёнигсберг")
    first = coords(onto, place, 54.7104, 20.5101)
    assert onto.statements.get(first)["value"] == {"lat": 54.71, "lon": 20.51}
    assert coords(onto, place, 54.71, 20.51) == first
    assert onto.statements.find(place, "coordinates", value={"lat": 54.7149, "lon": 20.51}) == first
    assert len(events.of("knowledge.statement.created")) == 1


@pytest.mark.parametrize(
    ("lat", "lon", "code"),
    [
        (90.001, 0, "geo_out_of_range"),
        (0, -180.5, "geo_out_of_range"),
        ("54", 20, "geo_not_number"),
        (True, 20, "geo_not_number"),
        (float("nan"), 0, "geo_not_number"),
        (float("inf"), 0, "geo_not_number"),
        (54, None, "geo_not_number"),
    ],
)
def test_coordinates_refused_with_code(onto, events, lat, lon, code):
    place = onto.thing("place", "Место")
    events.clear()
    with pytest.raises(StatementError) as err:
        coords(onto, place, lat, lon)
    assert err.value.code == code
    [refused] = events.of("knowledge.statement.refused")
    assert refused["type"] == "coordinates" and refused["code"] == code


def test_coordinates_bounds_inclusive(onto):
    place = onto.thing("place", "Край")
    assert coords(onto, place, 90, 180) != coords(onto, place, -90, -180)


def test_coordinates_need_attribution(onto, events):
    place = onto.thing("place", "Место")
    events.clear()
    with pytest.raises(StatementError) as err:
        coords(onto, place, 10, 10, attributions=[])
    assert err.value.code == "attribution_required"
    [refused] = events.of("knowledge.statement.refused")
    assert refused["code"] == "attribution_required"


def test_registry_error_keeps_code_and_old_refusals_have_none(onto, events):
    kant = onto.person("Кант", "1724", "1804")
    place = onto.thing("place", "Кёнигсберг")
    events.clear()
    with pytest.raises(StatementError) as err:
        onto.statements.add(
            kant, "lived_in", obj=place, qualifiers={"place_role": "отпуск"}, attributions=WD
        )
    assert err.value.code is None
    [refused] = events.of("knowledge.statement.refused")
    assert "code" not in refused.fields and "place_role" in refused["reason"]


def test_check_value_without_entity(onto, events):
    assert onto.statements.check_value(
        "coordinates", {"lat": 1.234, "lon": 5.678}, attributions=WD
    ) == {"lat": 1.23, "lon": 5.68}
    with pytest.raises(StatementError) as err:
        onto.statements.check_value("coordinates", {"lat": 95, "lon": 0}, attributions=WD)
    assert err.value.code == "geo_out_of_range"
    with pytest.raises(StatementError):
        onto.statements.check_value("lived_in", qualifiers={"place_role": "отпуск"})
    onto.statements.check_value("lived_in", qualifiers={"place_role": "birth"})
    assert not events.of("knowledge.statement.refused")  # сухая проверка событий не пишет


# --- 2.4: координаты не для модели ---------------------------------------------------------


def test_output_schema_has_no_coordinates(onto):
    reg = onto.registry
    families = sorted({f for spec in reg._load()["relations"].values() for f in spec["families"]})
    for schema in (
        reg.output_schema(),
        reg.output_schema(families),
        reg.output_schema(["context"]),
    ):
        assert (
            "coordinates"
            not in schema["properties"]["statements"]["items"]["properties"]["type"]["enum"]
        )
        assert "coordinates" not in schema["x-relations"]
    assert "lived_in" in reg.output_schema(["biography"])["x-relations"]
