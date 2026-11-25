"""Координаты места и вид места в биографии (geo-timeline, задача 7.1).

Тесты написаны по дельте ``openspec/changes/add-geo-timeline/specs/geo-timeline/spec.md``:
требования «Координаты места» и «Вид места в биографии». Данные задаёт каждый тест сам через
``Entities``/``Statements`` (фикстура ``onto``); журнал — фикстура ``events``.
"""

from __future__ import annotations

import math

import pytest
from sqlalchemy import delete, select, update

from philograph.knowledge import schema as t
from philograph.knowledge.dates import parse
from philograph.knowledge.registry import OntologyRegistry
from philograph.knowledge.statements import Attribution, Evidence, Provenance, StatementError

req = pytest.mark.req
GEO = "geo-timeline"
COORDS = "Координаты места"
ROLE = "Вид места в биографии"
REFUSED = "knowledge.statement.refused"
WIKIDATA = [
    Attribution("source", "wikidata:Q4120832", place="https://www.wikidata.org/wiki/Q4120832")
]


def place(onto, name: str = "Кёнигсберг") -> str:
    return onto.entities.create("place", [("ru", name, "primary")])


def coords(onto, entity: str, lat, lon, attributions=WIKIDATA, **kw) -> str:
    return onto.statements.add(
        entity, "coordinates", value={"lat": lat, "lon": lon}, attributions=attributions, **kw
    )


def count(onto, type_: str) -> int:
    with onto.statements.engine.begin() as conn:
        return len(
            conn.execute(select(t.statements.c.id).where(t.statements.c.type == type_)).all()
        )


# --- Координаты места -----------------------------------------------------------------


@req(GEO, COORDS, scenario="Координаты Кёнигсберга")
def test_konigsberg_coordinates_rounded_and_same_key(onto, events):
    k = place(onto)
    first = coords(onto, k, 54.7104, 20.5101)
    assert onto.statements.get(first)["value"] == {"lat": 54.71, "lon": 20.51}
    again = coords(onto, k, 54.71, 20.51)
    assert again == first
    assert count(onto, "coordinates") == 1
    events.assert_none(REFUSED)


BAD = [
    ((90.001, 0), "geo_out_of_range"),
    ((0, -180.5), "geo_out_of_range"),
    (("54", 20), "geo_not_number"),
    ((True, 20), "geo_not_number"),
    ((math.nan, 0), "geo_not_number"),
    ((math.inf, 0), "geo_not_number"),
]


@req(GEO, COORDS, scenario="Границы и мусор")
def test_bounds_and_garbage(onto, events):
    k = place(onto)
    for lat, lon in ((90, 180), (-90, -180)):
        sid = coords(onto, k, lat, lon)
        assert onto.statements.get(sid)["value"] == {"lat": lat, "lon": lon}
    events.assert_none(REFUSED)
    for (lat, lon), code in BAD:
        events.clear()
        with pytest.raises(StatementError) as exc:
            coords(onto, k, lat, lon)
        assert exc.value.code == code, (lat, lon)
        [refused] = events.of(REFUSED)
        assert refused.get("type") == "coordinates"
        assert refused.get("code") == code
        assert isinstance(refused.get("reason"), str) and refused.get("reason")
    assert count(onto, "coordinates") == 2


@req(GEO, COORDS, scenario="Без атрибуции")
def test_without_attribution_refused(onto, events):
    k = place(onto)
    with pytest.raises(StatementError) as exc:
        coords(onto, k, 54.71, 20.51, attributions=[])
    assert exc.value.code == "attribution_required"
    refused = events.one(REFUSED)
    assert refused.get("type") == "coordinates"
    assert refused.get("code") == "attribution_required"
    assert count(onto, "coordinates") == 0


@req(GEO, COORDS, scenario="Не для модели")
def test_coordinates_not_in_model_output_schema(onto, events):
    families = sorted(
        {f for s in onto.registry._load()["relations"].values() for f in s.get("families") or []}
    )
    assert "context" in families
    for fam in [None, families, *([f] for f in families)]:
        schema = onto.registry.output_schema(fam)
        allowed = schema["properties"]["statements"]["items"]["properties"]["type"]["enum"]
        assert "coordinates" not in allowed, fam
        assert "lived_in" in allowed or fam is not None  # схема не пустая по всем семействам
    # Сама связь в реестре есть — исключена именно из схемы для модели.
    assert onto.registry.relation("coordinates")["value_kind"] == "geo"
    events.assert_none(REFUSED)


# Нормативные: порядок проверок и коды.

ORDER = [
    # (значение, код): сначала «число», затем «пределы» — по исходному значению.
    (("abc", 500), "geo_not_number"),  # и не число, и вне пределов → первое правило
    ((math.nan, 500), "geo_not_number"),
    ((False, 0), "geo_not_number"),
    ((None, 0), "geo_not_number"),
    ((0, None), "geo_not_number"),
    (([1], 0), "geo_not_number"),
    ((-math.inf, 0), "geo_not_number"),
    ((0, math.inf), "geo_not_number"),
    ((90.004, 0), "geo_out_of_range"),  # round(90.004, 2) = 90.0, но исходное вне пределов
    ((-90.004, 0), "geo_out_of_range"),
    ((0, 180.004), "geo_out_of_range"),
    ((0, -180.001), "geo_out_of_range"),
    ((1e308, 0), "geo_out_of_range"),
]


@req(GEO, COORDS, invariant="порядок проверок и коды code")
@pytest.mark.parametrize(("value", "code"), ORDER, ids=[repr(v) for v, _ in ORDER])
def test_check_order_and_codes(onto, events, value, code):
    k = place(onto)
    with pytest.raises(StatementError) as exc:
        coords(onto, k, *value)
    assert exc.value.code == code
    refused = events.one(REFUSED)
    assert (refused.get("type"), refused.get("code")) == ("coordinates", code)
    assert count(onto, "coordinates") == 0


@req(GEO, COORDS, invariant="значение без полей lat/lon отклоняется кодом geo_not_number")
@pytest.mark.parametrize("value", [None, "54,20", [54.71, 20.51], {"lat": 54.71}, {}])
def test_malformed_value_refused(onto, events, value):
    k = place(onto)
    with pytest.raises(StatementError) as exc:
        onto.statements.add(k, "coordinates", value=value, attributions=WIKIDATA)
    refused = events.one(REFUSED)
    assert refused.get("type") == "coordinates"
    assert exc.value.code == refused.get("code")
    assert refused.get("code") in (None, "geo_not_number")
    assert count(onto, "coordinates") == 0


ROUNDING = [
    ((54.7104, 20.5101), {"lat": 54.71, "lon": 20.51}),
    ((54.715, 20.505), {"lat": round(54.715, 2), "lon": round(20.505, 2)}),
    ((89.996, -179.996), {"lat": round(89.996, 2), "lon": round(-179.996, 2)}),
    ((-0.004, 0.004), {"lat": round(-0.004, 2), "lon": round(0.004, 2)}),
    ((48, 2), {"lat": 48, "lon": 2}),
]


@req(GEO, COORDS, invariant="хранится только округлённое")
@pytest.mark.parametrize(("raw", "stored"), ROUNDING, ids=[repr(r) for r, _ in ROUNDING])
def test_only_rounded_value_stored(onto, events, raw, stored):
    k = place(onto)
    sid = coords(onto, k, *raw)
    value = onto.statements.get(sid)["value"]
    assert value == stored
    assert set(value) == {"lat", "lon"}
    # Ключ — по округлённому: запись уже округлённого значения — то же утверждение.
    assert coords(onto, k, stored["lat"], stored["lon"]) == sid
    assert onto.statements.find(k, "coordinates", value={"lat": raw[0], "lon": raw[1]}) == sid
    assert count(onto, "coordinates") == 1
    events.assert_none(REFUSED)


@req(GEO, COORDS, invariant="без атрибуции не принимается никогда")
@pytest.mark.parametrize(
    "kw",
    [
        {},
        {"status": "verified"},
        {"status": "generated", "provenance": Provenance("generated")},
        {"provenance": Provenance("imported", run_id="geo_000000000000")},
        {"provenance": Provenance("manual"), "rank": "preferred"},
        {"evidence": [Evidence("p2", "Кант испытал влияние Юма", source_id="s_textbook")]},
    ],
    ids=["plain", "verified", "generated", "imported", "preferred", "evidence-only"],
)
@pytest.mark.parametrize("value", [(54.71, 20.51), (0, 0), (90, 180)])
def test_never_without_attribution(onto, events, kw, value):
    k = place(onto)
    with pytest.raises(StatementError) as exc:
        coords(onto, k, *value, attributions=[], **kw)
    assert exc.value.code == "attribution_required"
    refused = events.one(REFUSED)
    assert (refused.get("type"), refused.get("code")) == ("coordinates", "attribution_required")
    assert count(onto, "coordinates") == 0


@req(GEO, COORDS, invariant="требование атрибуции задаётся флагом типа связи в реестре")
def test_attribution_rule_is_registry_flag(onto, events):
    # Новый тип оператора с флагом — тоже требует атрибуции, хотя код типа другой.
    onto.registry.add_relation(
        "operator",
        {
            "code": "observatory_at",
            "title": "обсерватория",
            "subject_types": ["place"],
            "object_types": [],
            "value_kind": "text",
            "requires_attribution": True,
        },
    )
    k = place(onto)
    with pytest.raises(StatementError) as exc:
        onto.statements.add(k, "observatory_at", value="башня")
    assert exc.value.code == "attribution_required"
    assert events.one(REFUSED).get("type") == "observatory_at"
    # Снятый флаг у coordinates — запись без атрибуции принимается: решает флаг, не код типа.
    with onto.statements.engine.begin() as conn:
        spec = conn.scalar(
            select(t.relation_types.c.spec).where(t.relation_types.c.code == "coordinates")
        )
        conn.execute(
            update(t.relation_types)
            .where(t.relation_types.c.code == "coordinates")
            .values(spec={**spec, "requires_attribution": False})
        )
    fresh = OntologyRegistry(onto.registry.engine)
    onto.statements.registry = fresh
    events.clear()
    sid = coords(onto, k, 54.71, 20.51, attributions=[])
    assert onto.statements.get(sid)["value"] == {"lat": 54.71, "lon": 20.51}
    events.assert_none(REFUSED)


def _place_layer(onto, clock):
    from philograph.knowledge.geo import PlaceLayer
    from philograph.knowledge.map import SectionMap
    from philograph.knowledge.snapshot import Snapshots

    snapshots = Snapshots(onto.statements.engine, clock)
    return PlaceLayer(SectionMap(onto.statements, snapshots=snapshots), snapshots)


@req(
    GEO,
    COORDS,
    invariant="одна координата: предпочтённая, по статусу, раньше записанная",
)
def test_one_coordinate_chosen(onto, events, clock):
    kant = onto.person("Иммануил Кант", "1724", "1804")
    k = place(onto)
    onto.statements.add(kant, "lived_in", obj=k, attributions=WIKIDATA)
    layer = _place_layer(onto, clock)

    def chosen():
        events.clear()
        [p] = layer.build()["places"]
        assert events.one("knowledge.geo.built").get("places") == 1
        return p["lat"], p["lon"]

    imported = {"provenance": Provenance("imported", run_id="geo_1"), "status": "sourced"}
    coords(onto, k, 10, 10, **imported)
    coords(onto, k, 20, 20, **imported)
    assert chosen() == (10, 10)  # равные по рангу и статусу → раньше записанная
    coords(onto, k, 30, 30, status="verified")
    assert chosen() == (30, 30)  # сильнее по статусу
    coords(
        onto, k, 40, 40, rank="preferred", status="generated", provenance=Provenance("generated")
    )
    assert chosen() == (40, 40)  # предпочтённая важнее статуса


# --- Вид места в биографии ------------------------------------------------------------


@req(GEO, ROLE, scenario="Место деятельности со временем")
def test_activity_with_time(onto, events):
    descartes = onto.person("Рене Декарт", "1596", "1650")
    amsterdam = place(onto, "Амстердам")
    time = parse("1628–1649").to_json()
    sid = onto.statements.add(
        descartes,
        "lived_in",
        obj=amsterdam,
        qualifiers={"place_role": "activity", "time": time},
        attributions=WIKIDATA,
    )
    stored = onto.statements.get(sid)
    assert stored["qualifiers"] == {"place_role": "activity", "time": time}
    assert stored["object"] == amsterdam
    events.assert_none(REFUSED)


@req(GEO, ROLE, scenario="Вид вне списка")
def test_role_outside_list_refused(onto, events):
    descartes = onto.person("Рене Декарт", "1596", "1650")
    amsterdam = place(onto, "Амстердам")
    with pytest.raises(StatementError):
        onto.statements.add(
            descartes,
            "lived_in",
            obj=amsterdam,
            qualifiers={"place_role": "отпуск"},
            attributions=WIKIDATA,
        )
    refused = events.one(REFUSED)
    assert refused.get("type") == "lived_in"
    assert "place_role" in refused.get("reason")
    assert "отпуск" in refused.get("reason")
    assert count(onto, "lived_in") == 0


@req(
    GEO,
    ROLE,
    invariant="значения вида — только birth, death, activity, residence; без вида допустимо",
)
@pytest.mark.parametrize("role", ["birth", "death", "activity", "residence", None])
def test_roles_in_list_and_without_role(onto, events, role):
    kant = onto.person("Иммануил Кант", "1724", "1804")
    k = place(onto)
    qualifiers = {"place_role": role} if role else {}
    sid = onto.statements.add(kant, "lived_in", obj=k, qualifiers=qualifiers, attributions=WIKIDATA)
    assert onto.statements.get(sid)["qualifiers"] == qualifiers
    events.assert_none(REFUSED)


@req(GEO, ROLE, invariant="значение вне списка отклоняется")
@pytest.mark.parametrize("role", ["Birth", "event", "", "birth ", 1, "<script>"])
def test_roles_outside_list(onto, events, role):
    kant = onto.person("Иммануил Кант", "1724", "1804")
    k = place(onto)
    with pytest.raises(StatementError):
        onto.statements.add(
            kant, "lived_in", obj=k, qualifiers={"place_role": role}, attributions=WIKIDATA
        )
    refused = events.one(REFUSED)
    assert refused.get("type") == "lived_in"
    assert "place_role" in refused.get("reason")
    assert count(onto, "lived_in") == 0


def _previous_version(engine) -> None:
    """Реестр прежней версии: у ``lived_in`` только ``time``, уточнителя ``place_role`` нет;
    оператор добавил к связи свой тип конца ``settlement``."""
    with engine.begin() as conn:
        spec = dict(
            conn.scalar(
                select(t.relation_types.c.spec).where(t.relation_types.c.code == "lived_in")
            )
        )
        spec["qualifiers"] = ["time"]
        spec["object_types"] = [*spec["object_types"], "settlement"]
        conn.execute(
            update(t.relation_types).where(t.relation_types.c.code == "lived_in").values(spec=spec)
        )
        conn.execute(delete(t.qualifiers).where(t.qualifiers.c.code == "place_role"))


@req(GEO, ROLE, scenario="Заполненный реестр")
def test_filled_registry_gets_place_role(onto, events, clock):
    engine = onto.registry.engine
    onto.registry.add_entity_type("operator", "settlement", "поселение", parent="place")
    _previous_version(engine)
    old = OntologyRegistry(engine, clock)
    assert old.relation("lived_in")["qualifiers"] == ["time"]
    before = old.version()

    loaded = OntologyRegistry(engine, clock)
    loaded.load_defaults()
    spec = loaded.relation("lived_in")
    assert spec["qualifiers"] == ["time", "place_role"]
    assert "settlement" in spec["object_types"]
    assert loaded.version() == before + 1

    onto.statements.registry = loaded
    kant = onto.person("Иммануил Кант", "1724", "1804")
    k = place(onto)
    sid = onto.statements.add(
        kant, "lived_in", obj=k, qualifiers={"place_role": "birth"}, attributions=WIKIDATA
    )
    assert onto.statements.get(sid)["qualifiers"] == {"place_role": "birth"}
    events.assert_none(REFUSED)


@req(
    GEO,
    ROLE,
    invariant="заполненный реестр: повторная загрузка ничего не меняет",
)
def test_filled_registry_idempotent_and_keeps_operator(onto, events, clock):
    engine = onto.registry.engine
    onto.registry.add_entity_type("operator", "settlement", "поселение", parent="place")
    _previous_version(engine)
    first = OntologyRegistry(engine, clock)
    first.load_defaults()
    v1 = first.version()
    spec1 = first.relation("lived_in")
    second = OntologyRegistry(engine, clock)
    second.load_defaults()
    assert second.version() == v1
    assert second.relation("lived_in") == spec1
    assert spec1["object_types"][-1] == "settlement"
    events.assert_none(REFUSED)
