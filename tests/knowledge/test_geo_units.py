"""Юнит-тесты разработчика add-geo-timeline: реестр, координаты, слой мест, обогащение.

Сценарные и нормативные тесты по спецификации ``geo-timeline`` пишет тестировщик; здесь —
проверки модулей на синтетических записях. QID в фикстурах — только метки.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select, update

from philograph.knowledge import schema as t
from philograph.knowledge.dates import parse
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


# --- 3.2: слой мест ------------------------------------------------------------------------


def _layer(onto, clock, max_entities=400, cache_size=32):
    from philograph.knowledge.geo import PlaceLayer
    from philograph.knowledge.map import MapSettings, SectionMap
    from philograph.knowledge.snapshot import Snapshots

    snaps = Snapshots(onto.statements.engine, clock)
    section_map = SectionMap(onto.statements, MapSettings(max_entities=max_entities), snaps)
    return PlaceLayer(section_map, snaps, cache_size=cache_size)


def lived(onto, person, place, role=None, time=None, status="sourced", run_id=None):
    qualifiers = {}
    if role:
        qualifiers["place_role"] = role
    if time:
        qualifiers["time"] = parse(time).to_json()
    return onto.statements.add(
        person,
        "lived_in",
        obj=place,
        qualifiers=qualifiers,
        attributions=WD,
        provenance=Provenance("generated" if status == "generated" else "imported", run_id),
        status=status,
    )


@pytest.fixture
def geo_world(onto):
    w = {
        "kant": onto.person("Кант", "1724", "1804"),
        "hume": onto.person("Юм", "1711", "1776"),
        "konigsberg": onto.thing("place", "Кёнигсберг"),
        "edinburgh": onto.thing("place", "Эдинбург"),
    }
    coords(onto, w["konigsberg"], 54.7104, 20.5101)
    lived(onto, w["kant"], w["konigsberg"], "birth", "1724")
    lived(onto, w["kant"], w["konigsberg"], "activity")
    lived(onto, w["kant"], w["konigsberg"], "death", "1804")
    lived(onto, w["hume"], w["edinburgh"])
    return w


def test_layer_kant_and_hume(onto, clock, events, geo_world):
    w = geo_world
    layer = _layer(onto, clock)
    events.clear()
    out = layer.build()
    assert out["places"] == [
        {
            "id": w["konigsberg"],
            "label": "Кёнигсберг",
            "lat": 54.71,
            "lon": 20.51,
            "status": "sourced",
        }
    ]
    assert [(p["role"], p["from"], p["to"]) for p in out["placements"]] == [
        ("activity", None, None),
        ("birth", 1724, 1724),
        ("death", 1804, 1804),
    ]
    assert out["unplaced"] == [w["hume"]]
    assert (out["truncated"], out["limit"]) == (False, 400)
    [built] = events.of("knowledge.geo.built")
    assert built.fields == {
        "entities": 2,
        "places": 1,
        "placements": 3,
        "unplaced": 1,
        "truncated": False,
        "cached": False,
    }
    assert not events.of("knowledge.map.built")


def test_layer_cache_and_reset(onto, clock, events, geo_world):
    layer = _layer(onto, clock)
    first = layer.build()
    events.clear()
    assert layer.build() == first
    assert events.of("knowledge.geo.built")[0]["cached"] is True
    coords(onto, geo_world["edinburgh"], 55.95, -3.19)
    events.clear()
    third = layer.build()
    built = events.of("knowledge.geo.built")[0]
    assert (built["cached"], built["places"], built["unplaced"]) == (False, 2, 0)
    assert third["unplaced"] == []


def test_layer_role_beats_no_role_and_lone_no_role(onto, clock, geo_world):
    w = geo_world
    lived(onto, w["kant"], w["konigsberg"])  # без вида рядом с видом
    coords(onto, w["edinburgh"], 55.95, -3.19)
    out = _layer(onto, clock).build()
    kant = [p for p in out["placements"] if p["entity"] == w["kant"]]
    assert None not in {p["role"] for p in kant} and len(kant) == 3
    [hume] = [p for p in out["placements"] if p["entity"] == w["hume"]]
    assert (hume["place"], hume["role"], hume["from"], hume["to"]) == (
        w["edinburgh"],
        None,
        None,
        None,
    )


def test_layer_only_map_entities(onto, clock, geo_world):
    w = geo_world
    x = onto.person("Икс", "1700", "1750")
    lived(onto, x, w["konigsberg"], "birth")
    for _ in range(3):  # вес Канта и Юма больше, чем у X
        other = onto.thing("work", "Труд", "1781")
        onto.statements.add(other, "author", obj=w["kant"], attributions=WD)
        other = onto.thing("work", "Трактат", "1739")
        onto.statements.add(other, "author", obj=w["hume"], attributions=WD)
    data = _layer(onto, clock, max_entities=2).build()
    ids = {p["entity"] for p in data["placements"]} | set(data["unplaced"])
    assert x not in ids and data["truncated"] is True and data["limit"] == 2


def test_layer_event_and_rejected(onto, clock, geo_world):
    w = geo_world
    event = onto.thing("event", "Выход «Критики»", "1781")
    onto.statements.add(event, "happened_in", obj=w["konigsberg"], attributions=WD)
    rejected = lived(onto, w["hume"], w["konigsberg"], "residence", "1750")
    onto.statements.reject(rejected, "operator")
    out = _layer(onto, clock).build()
    [ev] = [p for p in out["placements"] if p["entity"] == event]
    assert (ev["role"], ev["from"], ev["to"]) == ("event", 1781, 1781)
    assert rejected not in {p["statement"] for p in out["placements"]}


def test_layer_one_coordinate_per_place(onto, clock, geo_world):
    w = geo_world
    later = coords(onto, w["konigsberg"], 54.0, 20.0)
    out = _layer(onto, clock).build()
    assert (out["places"][0]["lat"], out["places"][0]["lon"]) == (54.71, 20.51)  # раньше записанная
    onto.statements.set_rank(later, "preferred", "operator")
    out = _layer(onto, clock).build()
    assert (out["places"][0]["lat"], out["places"][0]["lon"]) == (54.0, 20.0)


def test_layer_cache_bounded(onto, clock, geo_world):
    layer = _layer(onto, clock, cache_size=4)
    for i in range(20):
        out = layer.build(textbook=f"s_none_{i}", only_textbook=True)
        assert out["places"] == [] and out["placements"] == [] and out["unplaced"] == []
    assert layer.cached_scopes() == 4


def test_layer_has_no_quotes_or_paragraphs(onto, clock, geo_world):
    import json

    text = json.dumps(_layer(onto, clock).build(), ensure_ascii=False)
    for word in ("quote", "paragraph", "evidence", "attributions", "wikidata.org"):
        assert word not in text


# --- 3.3: маршрут и шлюз -------------------------------------------------------------------


def test_places_route(onto, clock, events, geo_world):
    from fastapi.testclient import TestClient

    from philograph.knowledge.app import build_app
    from philograph.knowledge.map import SectionMap
    from philograph.knowledge.snapshot import Snapshots

    snaps = Snapshots(onto.statements.engine, clock)
    app = build_app(onto.statements, section_map=SectionMap(onto.statements, snapshots=snaps))
    events.clear()
    response = TestClient(app).get("/v1/map/places")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"places", "placements", "unplaced", "truncated", "limit"}
    assert [p["label"] for p in body["places"]] == ["Кёнигсберг"]
    assert len(events.of("knowledge.geo.built")) == 1 and not events.of("knowledge.map.built")


def test_gateway_counts_places_as_map_without_page_token():
    from philograph.gateway.limits import WITHOUT_PAGE_TOKEN, paid_operation

    assert paid_operation("GET", "/api/knowledge/v1/map/places") == "map"
    assert "map" in WITHOUT_PAGE_TOKEN
