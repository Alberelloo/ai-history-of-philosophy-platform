"""Географический слой карты ``GET /v1/map/places`` (geo-timeline, задача 7.3).

Тесты по требованию «Географический слой карты» дельты
``openspec/changes/add-geo-timeline/specs/geo-timeline/spec.md`` и контракту из ``design.md``.
Приложение сервиса знаний — настоящее (``build_app``), библиотека и модель — подменённые
транспорты, сеть запрещена. Событие ответа находится по ``request_id`` запроса.
"""

from __future__ import annotations

import json
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from philograph.knowledge.app import build_app
from philograph.knowledge.dates import parse
from philograph.knowledge.geo import PlaceLayer
from philograph.knowledge.map import MapSettings, SectionMap
from philograph.knowledge.snapshot import Snapshots
from philograph.knowledge.statements import Attribution, Evidence, Provenance
from philograph.platform.client import ServiceClient

from .conftest import TEXTBOOK_N
from .wd_records import no_network  # noqa: F401

req = pytest.mark.req
GEO = "geo-timeline"
LAYER = "Географический слой карты"
BUILT = "knowledge.geo.built"
MAP_BUILT = "knowledge.map.built"
WD = [Attribution("source", "wikidata:Q1", place="https://www.wikidata.org/wiki/Q1")]
IMPORTED = {
    "attributions": WD,
    "provenance": Provenance("imported", run_id="geo_t"),
    "status": "sourced",
}
PLACEMENT_KEYS = {"entity", "place", "role", "from", "to", "status", "generated", "statement"}
PLACE_KEYS = {"id", "label", "lat", "lon", "status"}


class Layer:
    """Сервис знаний с картой и слоем мест на одном снимке; ``max_entities`` — предел карты."""

    def __init__(self, onto, clock, *, max_entities: int = 400, cache_size: int = 32) -> None:
        self.onto = onto
        self.library_calls: list[str] = []
        self.llm_calls: list[str] = []

        def library(request: httpx.Request) -> httpx.Response:
            self.library_calls.append(request.url.path)
            if request.url.path.endswith("/internal/access"):
                return httpx.Response(200, json={"closed": [], "hidden": []})
            return httpx.Response(404, json={"detail": "Not Found"})

        snapshots = Snapshots(onto.statements.engine, clock)
        section_map = SectionMap(
            onto.statements, settings=MapSettings(max_entities=max_entities), snapshots=snapshots
        )
        self.layer = PlaceLayer(section_map, snapshots, cache_size=cache_size)
        app = build_app(
            onto.statements,
            section_map=section_map,
            place_layer=self.layer,
            library=ServiceClient(
                "library", "http://library/api", transport=httpx.MockTransport(library)
            ),
        )
        self.client = TestClient(app, raise_server_exceptions=False)

    def get(self, path: str, **params) -> tuple[dict, str]:
        rid = f"rid-{uuid.uuid4().hex[:10]}"
        response = self.client.get(path, params=params or None, headers={"X-Request-Id": rid})
        assert response.status_code == 200, response.text
        return response.json(), rid


def built(events, rid: str):
    found = events.where(BUILT, request_id=rid)
    assert len(found) == 1, (rid, events.names())
    assert events.where(MAP_BUILT, request_id=rid) == []
    return found[0]


def place(onto, name: str, lat=None, lon=None) -> str:
    entity = onto.entities.create("place", [("ru", name, "primary")])
    if lat is not None:
        onto.statements.add(entity, "coordinates", value={"lat": lat, "lon": lon}, **IMPORTED)
    return entity


def lived(onto, who: str, where: str, role=None, when=None, **kw) -> str:
    qualifiers = {}
    if role:
        qualifiers["place_role"] = role
    if when:
        qualifiers["time"] = parse(when).to_json()
    return onto.statements.add(
        who, "lived_in", obj=where, qualifiers=qualifiers, **{**IMPORTED, **kw}
    )


def kant_and_hume(onto) -> dict[str, str]:
    ids = {
        "kant": onto.person("Иммануил Кант", "1724", "1804"),
        "hume": onto.person("Дэвид Юм", "1711", "1776"),
        "konigsberg": place(onto, "Кёнигсберг", 54.71, 20.51),
        "edinburgh": place(onto, "Эдинбург"),
    }
    lived(onto, ids["kant"], ids["konigsberg"], "birth", "1724")
    lived(onto, ids["kant"], ids["konigsberg"], "activity")
    lived(onto, ids["kant"], ids["konigsberg"], "death", "1804")
    lived(onto, ids["hume"], ids["edinburgh"])
    return ids


def triples(body) -> list[tuple]:
    return sorted(
        (p["entity"], p["place"], p["role"], p["from"], p["to"]) for p in body["placements"]
    )


# --- сценарии ----------------------------------------------------------------------------


@req(GEO, LAYER, scenario="Кант и Юм")
def test_kant_and_hume(onto, clock, events, no_network):
    svc = Layer(onto, clock)
    w = kant_and_hume(onto)
    body, rid = svc.get("/v1/map/places")
    assert set(body) == {"places", "placements", "unplaced", "truncated", "limit"}
    [k] = body["places"]
    assert (k["id"], k["label"], k["lat"], k["lon"]) == (
        w["konigsberg"],
        "Кёнигсберг",
        54.71,
        20.51,
    )
    assert triples(body) == sorted(
        [
            (w["kant"], w["konigsberg"], "birth", 1724, 1724),
            (w["kant"], w["konigsberg"], "activity", None, None),
            (w["kant"], w["konigsberg"], "death", 1804, 1804),
        ]
    )
    for p in body["placements"]:
        assert set(p) == PLACEMENT_KEYS
        assert (p["status"], p["generated"]) == ("sourced", False)
    assert body["unplaced"] == [w["hume"]]
    assert (body["truncated"], body["limit"]) == (False, 400)
    e = built(events, rid)
    assert {k: e.get(k) for k in ("entities", "places", "placements", "unplaced", "cached")} == {
        "entities": 2,
        "places": 1,
        "placements": 3,
        "unplaced": 1,
        "cached": False,
    }
    assert e.get("truncated") is False
    events.assert_none(MAP_BUILT)
    assert svc.llm_calls == []


@req(GEO, LAYER, scenario="Кэш и его сброс")
def test_cache_and_reset(onto, clock, events, no_network):
    svc = Layer(onto, clock)
    w = kant_and_hume(onto)
    first, rid1 = svc.get("/v1/map/places")
    second, rid2 = svc.get("/v1/map/places")
    assert second == first
    assert built(events, rid1).get("cached") is False
    assert built(events, rid2).get("cached") is True
    onto.statements.add(
        w["edinburgh"], "coordinates", value={"lat": 55.95, "lon": -3.19}, **IMPORTED
    )
    third, rid3 = svc.get("/v1/map/places")
    e = built(events, rid3)
    assert (e.get("cached"), e.get("places"), e.get("unplaced")) == (False, 2, 0)
    assert len(third["places"]) == 2 and third["unplaced"] == []
    assert (w["hume"], w["edinburgh"], None, None, None) in triples(third)


@req(GEO, LAYER, scenario="Сущность вне карты")
def test_entity_outside_map(onto, clock, events, no_network):
    svc = Layer(onto, clock, max_entities=2)
    w = kant_and_hume(onto)
    # Вес — число утверждений в области: у Канта и Юма больше, чем у X.
    onto.statements.add(
        w["kant"],
        "influenced_by",
        obj=w["hume"],
        attributions=WD,
        evidence=[Evidence("p2", "Кант испытал влияние Юма", source_id="s_textbook")],
        provenance=Provenance("extracted"),
    )
    berlin = place(onto, "Берлин", 52.52, 13.4)
    lived(onto, w["hume"], berlin, "activity")
    x = onto.person("Персона X", "1730", "1790")
    lived(onto, x, berlin, "birth", "1730")
    body, rid = svc.get("/v1/map/places")
    map_body, _ = svc.get("/v1/map")
    assert x not in {p["id"] for p in map_body["people"]}
    assert x not in {p["entity"] for p in body["placements"]}
    assert x not in body["unplaced"]
    assert (body["truncated"], body["limit"]) == (True, 2)
    e = built(events, rid)
    assert (e.get("truncated"), e.get("entities")) == (True, 2)


@req(GEO, LAYER, scenario="Запись без вида и с видом")
def test_role_record_displaces_plain(onto, clock, events, no_network):
    svc = Layer(onto, clock)
    kant = onto.person("Иммануил Кант", "1724", "1804")
    k = place(onto, "Кёнигсберг", 54.71, 20.51)
    lived(onto, kant, k)
    lived(onto, kant, k, "birth")
    body, rid = svc.get("/v1/map/places")
    pair = [p for p in body["placements"] if (p["entity"], p["place"]) == (kant, k)]
    assert [p["role"] for p in pair] == ["birth"]
    assert built(events, rid).get("placements") == 1


@req(GEO, LAYER, scenario="Только без вида")
def test_only_plain_record(onto, clock, events, no_network):
    svc = Layer(onto, clock)
    hume = onto.person("Дэвид Юм", "1711", "1776")
    ed = place(onto, "Эдинбург", 55.95, -3.19)
    lived(onto, hume, ed)
    body, rid = svc.get("/v1/map/places")
    assert [(p["place"], p["role"], p["from"], p["to"]) for p in body["placements"]] == [
        (ed, None, None, None)
    ]
    assert body["unplaced"] == []
    e = built(events, rid)
    assert (e.get("placements"), e.get("unplaced"), e.get("places")) == (1, 0, 1)


@req(GEO, LAYER, scenario="Ограниченный кэш")
def test_cache_is_bounded(onto, clock, events, no_network):
    svc = Layer(onto, clock, cache_size=8)
    kant_and_hume(onto)
    for i in range(100):
        body, rid = svc.get("/v1/map/places", textbook=f"s_missing_{i}", only_textbook="true")
        assert (body["places"], body["placements"], body["unplaced"]) == ([], [], []), i
        e = built(events, rid)
        assert (e.get("places"), e.get("placements"), e.get("unplaced")) == (0, 0, 0)
        assert e.get("cached") is False
        assert svc.layer.cached_scopes() <= 8
    assert svc.layer.cached_scopes() == 8


# --- нормативные ------------------------------------------------------------------------


def scope_world(onto) -> dict[str, str]:
    ids = kant_and_hume(onto)
    paris = place(onto, "Париж", 48.86, 2.35)
    ids["paris"] = paris
    for i in range(6):
        p = onto.person(f"Философ {i}", str(1600 + 10 * i), str(1660 + 10 * i))
        ids[f"p{i}"] = p
        if i % 2 == 0:
            lived(onto, p, paris, "activity", f"{1620 + 10 * i}")
        for _ in range(i):  # разный вес
            lived(onto, p, ids["edinburgh"], "residence")
    ev = onto.thing("event", "Основание академии", "1666")
    onto.statements.add(ev, "happened_in", obj=paris, **IMPORTED)
    ids["event"] = ev
    onto.thing("event", "Событие без места", "1700")
    for key in ("kant", "p0", "p3", "event"):
        with onto.statements.engine.begin() as conn:
            from philograph.knowledge import schema as t

            conn.execute(
                t.mentions.insert().values(
                    target_id="p1",
                    target_kind="paragraph",
                    source_id=TEXTBOOK_N,
                    entity_id=ids[key],
                    start=0,
                    end=4,
                    method="name",
                )
            )
    return ids


@req(GEO, LAYER, invariant="сущности слоя ⊆ сущности /map той же области при любом пределе")
@pytest.mark.parametrize("limit", [1, 2, 3, 5, 8, 400])
@pytest.mark.parametrize(
    "scope",
    [{}, {"textbook": TEXTBOOK_N}, {"textbook": TEXTBOOK_N, "only_textbook": "true"}],
    ids=["all", "textbook", "only_textbook"],
)
def test_layer_subset_of_map(onto, clock, events, no_network, limit, scope):
    svc = Layer(onto, clock, max_entities=limit)
    scope_world(onto)
    body, rid = svc.get("/v1/map/places", **scope)
    map_body, _ = svc.get("/v1/map", **scope)
    on_map = {p["id"] for p in map_body["people"]} | {e["id"] for e in map_body["events"]}
    in_layer = {p["entity"] for p in body["placements"]} | set(body["unplaced"])
    assert in_layer <= on_map
    assert in_layer == on_map  # каждая сущность карты — либо размещена, либо «без места»
    assert {p["place"] for p in body["placements"]} == {p["id"] for p in body["places"]}
    assert (body["truncated"], body["limit"]) == (map_body["truncated"], map_body["limit"])
    assert built(events, rid).get("entities") == len(on_map)


@req(GEO, LAYER, invariant="событие размещается с видом event и годом события")
def test_event_placement(onto, clock, events, no_network):
    svc = Layer(onto, clock)
    ids = scope_world(onto)
    body, rid = svc.get("/v1/map/places")
    [e] = [p for p in body["placements"] if p["entity"] == ids["event"]]
    assert (e["place"], e["role"], e["from"], e["to"]) == (ids["paris"], "event", 1666, 1666)
    assert built(events, rid).get("placements") == len(body["placements"])


@req(GEO, LAYER, invariant="отклонённые не попадают")
@pytest.mark.parametrize("what", ["placement", "coordinates", "deprecated"])
def test_rejected_not_in_layer(onto, clock, events, no_network, what):
    svc = Layer(onto, clock)
    kant = onto.person("Иммануил Кант", "1724", "1804")
    k = onto.entities.create("place", [("ru", "Кёнигсберг", "primary")])
    c = onto.statements.add(k, "coordinates", value={"lat": 54.71, "lon": 20.51}, **IMPORTED)
    s = lived(onto, kant, k, "birth")
    if what == "placement":
        onto.statements.reject(s, "operator")
    elif what == "coordinates":
        onto.statements.reject(c, "operator")
    else:
        onto.statements.set_rank(s, "deprecated", "operator")
    body, rid = svc.get("/v1/map/places")
    assert body["placements"] == []
    assert body["places"] == []
    assert body["unplaced"] == [kant]
    e = built(events, rid)
    assert (e.get("placements"), e.get("places"), e.get("unplaced")) == (0, 0, 1)


@req(GEO, LAYER, invariant="нет цитат, id абзацев и текстов утверждений")
def test_no_quotes_or_paragraphs(onto, clock, events, no_network):
    svc = Layer(onto, clock)
    kant = onto.person("Иммануил Кант", "1724", "1804")
    k = place(onto, "Кёнигсберг", 54.71, 20.51)
    quote = "Кант признавал, что именно Юм пробудил его"
    onto.statements.add(
        kant,
        "lived_in",
        obj=k,
        qualifiers={"place_role": "activity"},
        attributions=[Attribution("source", "s_textbook", place="с. 41")],
        evidence=[Evidence("p1", quote, source_id="s_textbook")],
        provenance=Provenance("extracted"),
    )
    body, rid = svc.get("/v1/map/places")
    text = json.dumps(body, ensure_ascii=False)
    for needle in (quote, "догматического", '"p1"', "s_textbook", "с. 41", "evidence", "quote"):
        assert needle not in text, needle
    for p in body["placements"]:
        assert set(p) == PLACEMENT_KEYS
    for p in body["places"]:
        assert set(p) == PLACE_KEYS
    assert built(events, rid).get("placements") == 1


@req(GEO, LAYER, invariant="достроенное моделью помечено generated")
def test_generated_marked(onto, clock, events, no_network):
    svc = Layer(onto, clock)
    locke = onto.person("Джон Локк", "1632", "1704")
    london = place(onto, "Лондон", 51.51, -0.13)
    lived(
        onto, locke, london, attributions=WD, provenance=Provenance("generated"), status="generated"
    )
    body, rid = svc.get("/v1/map/places")
    [p] = body["placements"]
    assert (p["status"], p["generated"]) == ("generated", True)
    assert built(events, rid).get("placements") == 1


@req(GEO, LAYER, invariant="нет вызова модели и внешних запросов")
def test_no_model_and_no_network(onto, clock, events, no_network, monkeypatch):
    from philograph.knowledge import wikidata

    svc = Layer(onto, clock)
    kant_and_hume(onto)
    outgoing: list[str] = []
    original = httpx.Client.send

    def trap(self, request, *a, **kw):
        outgoing.append(str(request.url))
        return original(self, request, *a, **kw)

    monkeypatch.setattr(httpx.Client, "send", trap)
    monkeypatch.setattr(wikidata, "http_fetch", lambda *a, **k: outgoing.append("wikidata"))
    for scope in ({}, {"textbook": TEXTBOOK_N}):
        _, rid = svc.get("/v1/map/places", **scope)
        built(events, rid)
    external = [u for u in outgoing if not u.startswith(("http://testserver", "http://library"))]
    assert external == []
    assert svc.llm_calls == []


@req(GEO, LAYER, invariant="нет knowledge.map.built от слоя")
def test_no_map_built_from_layer(onto, clock, events, no_network):
    svc = Layer(onto, clock)
    kant_and_hume(onto)
    for _ in range(3):
        _, rid = svc.get("/v1/map/places")
        built(events, rid)
    events.assert_none(MAP_BUILT)
    _, rid = svc.get("/v1/map")
    assert len(events.where(MAP_BUILT, request_id=rid)) == 1
    assert events.where(BUILT, request_id=rid) == []


@req(GEO, LAYER, invariant="поля knowledge.geo.built — только числа и признаки")
def test_built_fields_numbers_only(onto, clock, events, no_network):
    svc = Layer(onto, clock)
    kant_and_hume(onto)
    _, rid = svc.get("/v1/map/places")
    e = built(events, rid)
    fields = {k: v for k, v in e.fields.items() if k not in ("request_id", "service")}
    assert set(fields) == {"entities", "places", "placements", "unplaced", "truncated", "cached"}
    for key in ("entities", "places", "placements", "unplaced"):
        assert type(fields[key]) is int, key
    for key in ("truncated", "cached"):
        assert type(fields[key]) is bool, key


@req(GEO, LAYER, invariant="кэш ограничен")
def test_cache_evicts_least_recent(onto, clock, events, no_network):
    svc = Layer(onto, clock, cache_size=2)
    kant_and_hume(onto)
    svc.get("/v1/map/places", textbook="a")
    svc.get("/v1/map/places", textbook="b")
    _, rid = svc.get("/v1/map/places", textbook="a")  # «a» — недавно запрошенная
    assert built(events, rid).get("cached") is True
    svc.get("/v1/map/places", textbook="c")  # вытесняет «b»
    assert svc.layer.cached_scopes() == 2
    _, rid_a = svc.get("/v1/map/places", textbook="a")
    _, rid_b = svc.get("/v1/map/places", textbook="b")
    assert built(events, rid_a).get("cached") is True
    assert built(events, rid_b).get("cached") is False
