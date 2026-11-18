"""Требование «Проверка вида карты» (knowledge-graph, изменение assistant-map-view)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from philograph.knowledge.app import build_app
from philograph.knowledge.map import MapViews, SectionMap, map_href

from .test_map import common, mx  # noqa: F401 — данные карты из тестов карты

req = pytest.mark.req
KG = "knowledge-graph"
PAIRS = json.loads((Path(__file__).parents[1] / "fixtures" / "map_views.json").read_text())


def empty(**kw):
    view = {
        "sel": None,
        "from": None,
        "to": None,
        "groups": [],
        "roles": [],
        "kinds": [],
        "ekinds": [],
        "verified": False,
        "lens": [],
    }
    return {**view, **kw}


@pytest.fixture
def views(onto, mx):
    return MapViews(SectionMap(onto.statements))


@req(KG, "Проверка вида карты")
@pytest.mark.parametrize("pair", PAIRS, ids=[p["note"] for p in PAIRS])
def test_href_matches_client(pair):
    """Адрес вида — тот же, что пишет клиент: набор пар общий с браузерным тестом."""
    assert map_href(pair["view"]) == pair["href"]


@req(KG, "Проверка вида карты")
def test_unknown_group_dropped(views, mx):
    result = views.normalize(empty(groups=[mx["empiricism"], "e_nope"], sel=mx["kant"]))
    assert result["view"]["groups"] == [mx["empiricism"]]
    assert result["view"]["sel"] == mx["kant"]
    assert result["dropped"] == [
        {"field": "groups", "value": "e_nope", "reason": "not_on_map", "label": "e_nope"}
    ]
    assert "e_nope" not in result["href"]
    assert result["href"] == f"/graph/{mx['kant']}?groups={mx['empiricism']}&via=assistant"
    # Локк и Юм — эмпиристы; их труды на карте не размечены, у Канта два труда не видны.
    assert result["shown"] == {"people": 2, "works": 0}


@req(KG, "Проверка вида карты")
def test_empty_result_relaxes_years(views, mx, events):
    """Эмпиристы Локк (1632–1704) и Юм (1711–1776) — в 1780–1800 никого: годы снимаются."""
    result = views.normalize(empty(groups=[mx["empiricism"]], **{"from": 1780, "to": 1800}))
    assert result["view"]["groups"] == [mx["empiricism"]]
    assert result["view"]["from"] is None and result["view"]["to"] is None
    assert [(d["field"], d["value"], d["reason"]) for d in result["dropped"]] == [
        ("from", 1780, "empty_result"),
        ("to", 1800, "empty_result"),
    ]
    assert result["shown"]["people"] == 2
    logged = events.where("knowledge.map_view.normalized")[-1]
    assert logged["dropped"] == {"empty_result": 2}
    assert logged["relaxed"] == ["from", "to"] and logged["shown"] == result["shown"]


@req(KG, "Проверка вида карты")
def test_relax_order_codes_before_groups(views, mx):
    """Пустую карту ослабляют по порядку: виды событий, виды трудов, роли, годы, группы."""
    result = views.normalize(
        empty(groups=[mx["empiricism"]], roles=["scientist"], **{"from": 1780})
    )
    # Сначала роль (эмпиристов-учёных нет) — карты всё ещё нет; затем годы — появляются люди.
    assert [d["field"] for d in result["dropped"]] == ["roles", "from"]
    assert result["view"]["groups"] == [mx["empiricism"]]
    assert result["shown"]["people"] == 2


@req(KG, "Проверка вида карты")
def test_sel_codes_years_and_lens(views, mx):
    result = views.normalize(
        empty(
            sel=mx["place"],  # места на карту не попадают
            roles=["philosopher", "astronaut"],
            kinds=["work", "poem"],
            ekinds=["intellectual", "sport"],
            lens=["events", "eras", "people", "works"],
            **{"from": 1500, "to": 1790},
        )
    )
    view = result["view"]
    assert view["sel"] is None
    assert view["roles"] == ["philosopher"] and view["kinds"] == ["work"]
    assert view["ekinds"] == ["intellectual"]
    # Граница до начала раздела ничего не ограничивает — её нет и в адресе, это не отброс.
    assert view["from"] is None and view["to"] == 1790
    assert view["lens"] == []  # все страты свернуть нельзя
    reasons = {(d["field"], d["value"]): d["reason"] for d in result["dropped"]}
    assert reasons == {
        ("sel", mx["place"]): "not_on_map",
        ("roles", "astronaut"): "unknown_code",
        ("kinds", "poem"): "unknown_code",
        ("ekinds", "sport"): "unknown_code",
        ("lens", "events"): "all_strata",
        ("lens", "eras"): "all_strata",
        ("lens", "people"): "all_strata",
        ("lens", "works"): "all_strata",
    }
    assert next(d for d in result["dropped"] if d["field"] == "sel")["label"] == "Кёнигсберг"


@req(KG, "Проверка вида карты")
def test_years_outside_or_reversed(views, mx):
    out = views.normalize(empty(**{"from": 1900, "to": 1500}))
    assert out["view"]["from"] is None and out["view"]["to"] is None
    assert {(d["field"], d["reason"]) for d in out["dropped"]} == {
        ("from", "out_of_range"),
        ("to", "out_of_range"),
    }
    # Ровно на границах раздела (1596–1814) — без ограничения и без отброса, как на клиенте.
    edges = views.normalize(empty(**{"from": 1596, "to": 1814}))
    assert edges["view"]["from"] is None and edges["view"]["to"] is None
    assert edges["dropped"] == [] and edges["href"] == "/graph?via=assistant"
    reversed_ = views.normalize(empty(**{"from": 1780, "to": 1700}))
    assert reversed_["view"]["from"] is None and reversed_["view"]["to"] is None
    assert len(reversed_["dropped"]) == 2


@req(KG, "Проверка вида карты")
def test_view_route_and_options(onto, mx):
    client = TestClient(build_app(onto.statements, section_map=SectionMap(onto.statements)))
    response = client.post(
        "/v1/map/view",
        json={"groups": [mx["empiricism"]], "from": 1690, "to": 1800, "lens": ["events"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["href"] == (
        f"/graph?from=1690&to=1800&groups={mx['empiricism']}&lens=events&via=assistant"
    )
    assert set(body) == {"view", "href", "dropped", "shown"}
    # Строки вместо чисел и чужие типы не роняют проверку: значение просто отбрасывается.
    odd = client.post("/v1/map/view", json={"from": "1700", "groups": [1, mx["empiricism"]]})
    assert odd.status_code == 200
    assert odd.json()["view"]["from"] is None
    assert odd.json()["view"]["groups"] == [mx["empiricism"]]

    options = client.post(
        "/v1/internal/assistant/map-options",
        json={"entities": [mx["empiricism"], mx["kant"], mx["place"], mx["critique"]]},
    ).json()
    by = {c["id"]: c for c in options["candidates"]}
    assert set(by) == {mx["empiricism"], mx["kant"], mx["critique"]}  # места на карте нет
    assert by[mx["empiricism"]] == {
        "id": mx["empiricism"],
        "label": "Эмпиризм",
        "kind": "group",
        "from": 1632,
        "to": 1776,
    }
    assert by[mx["kant"]]["kind"] == "person" and by[mx["critique"]]["from"] == 1781
    assert options["range"] == [1596, 1814]
    assert options["codes"] == {
        "roles": ["philosopher", "scientist"],
        "kinds": ["work", "concept"],
        "ekinds": ["intellectual"],
    }
