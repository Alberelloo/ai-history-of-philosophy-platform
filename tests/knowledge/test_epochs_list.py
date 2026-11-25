"""epochs — «Список эпох» (add-epochs, задача 5.3): ``GET /v1/epochs`` сервиса знаний.

Сервис — ``CatalogService`` (``conftest.py``): приложение знаний со справочником на одном
снимке, поддельные библиотека и шлюз моделей (вызов модели записывается). Данные — через
``World``. Вывод — ответ маршрута; журнал — ``knowledge.epochs.listed`` с ``request_id``.
"""

from __future__ import annotations

import pytest

from philograph.knowledge.dates import FuzzyDate
from philograph.knowledge.epoch_dates import EpochDates
from philograph.knowledge.statements import Attribution, Provenance

from .wd_records import RecordFetch, dated, no_network, year  # noqa: F401  (фикстура)
from .world import World

req = pytest.mark.req
EP = "epochs"
LIST = "Список эпох"
LISTED = "knowledge.epochs.listed"
COUNT_KINDS = {"people", "works", "ideas", "events", "groups"}

pytestmark = pytest.mark.usefixtures("no_network")


@pytest.fixture
def world(svc) -> World:
    return svc.world


def epochs(svc) -> tuple[dict, str]:
    response, rid = svc.get("/v1/epochs")
    assert response.status_code == 200, response.text
    return response.json(), rid


def listed(events, rid: str):
    found = events.where(LISTED, request_id=rid)
    assert len(found) == 1, events.names()
    return found[0]


def scenario_world(world: World) -> dict[str, str]:
    """Данные сценария «Список эпох»."""
    ids = {
        "sci": world.thing("epoch", "Научная революция", "1543–1687"),
        "enl": world.thing("epoch", "Просвещение", "1680–1800"),
        "baroque": world.thing("epoch", "Барокко"),
        "descartes": world.person("Рене Декарт", "1596", "1650"),
        "locke": world.person("Джон Локк", "1632", "1704"),
        "hume": world.person("Дэвид Юм", "1711", "1776"),
        "kant": world.person("Иммануил Кант", "1724", "1804"),
        "leibniz": world.person("Готфрид Лейбниц"),
    }
    world.belongs(ids["leibniz"], ids["baroque"])
    return ids


@req(EP, LIST, scenario="Список эпох")
def test_epochs_list(svc, world, events):
    w = scenario_world(world)
    data, rid = epochs(svc)
    assert [e["label"] for e in data["epochs"]] == ["Научная революция", "Просвещение"]
    sci, enl = data["epochs"]
    assert (sci["id"], enl["id"]) == (w["sci"], w["enl"])
    assert sci["counts"]["people"] == 2 and enl["counts"]["people"] == 2
    for item in (sci, enl):
        assert set(item["counts"]) == COUNT_KINDS
        catalog, _ = svc.catalog_ok({"epoch": item["id"]})
        assert catalog["facets"]["types"].get("person", 0) == item["counts"]["people"]
    people_sci, _ = svc.catalog_ok({"epoch": w["sci"], "type": "person"})
    assert {i["id"] for i in people_sci["items"]} == {w["descartes"], w["locke"]}
    people_enl, _ = svc.catalog_ok({"epoch": w["enl"], "type": "person"})
    assert {i["id"] for i in people_enl["items"]} == {w["hume"], w["kant"]}
    assert data["undated"] == [
        {
            "id": w["baroque"],
            "label": "Барокко",
            "counts": {"people": 1, "works": 0, "ideas": 0, "events": 0, "groups": 0},
        }
    ]
    assert data["truncated"] is False
    event = listed(events, rid)
    assert (event["epochs"], event["undated"], event["truncated"]) == (2, 1, False)
    assert svc.llm_calls == []


@req(EP, LIST, scenario="Источник датировки")
def test_dating_source(svc, world, onto, events):
    enl = onto.entities.create("epoch", [("ru", "Просвещение", "primary")])
    onto.entities.add_external(enl, "wikidata", "Q12539")
    EpochDates(onto.statements, onto.entities).apply(
        {"epochs": []},
        RecordFetch({"Q12539": dated("Q12539", year(1685), year(1815))}),
        linked=True,
    )
    world.thing("epoch", "Научная революция", "1543–1687")  # общее мнение
    data, rid = epochs(svc)
    items = {e["label"]: e for e in data["epochs"]}
    assert items["Просвещение"]["dating"]["source"] == "wikidata"
    assert items["Просвещение"]["dating"]["wikidata"] == "Q12539"
    assert items["Научная революция"]["dating"]["source"] == "common"
    assert items["Научная революция"]["dating"]["wikidata"] is None
    assert listed(events, rid)["epochs"] == 2


@req(EP, LIST, invariant="источник датировки по атрибуции основной датировки")
@pytest.mark.parametrize(
    "attributions,expected",
    [
        (
            [Attribution("source", "wikidata:Q1", place="https://www.wikidata.org/wiki/Q1")],
            "wikidata",
        ),
        ([Attribution("source", "s_textbook_n")], "source"),
        ([Attribution("common")], "common"),
        ([], "manual"),
    ],
    ids=["wikidata", "library", "common", "manual"],
)
def test_dating_source_rule(svc, onto, events, attributions, expected):
    e = onto.entities.create("epoch", [("ru", "Эпоха", "primary")])
    onto.statements.add(
        e,
        "dating",
        value=FuzzyDate(1600, 1600, 1700, 1700, "year", "1600–1700").to_json(),
        attributions=attributions,
        provenance=Provenance("manual", actor="operator") if not attributions else None,
    )
    data, rid = epochs(svc)
    [item] = data["epochs"]
    assert item["dating"]["source"] == expected
    assert listed(events, rid)["epochs"] == 1


@req(EP, LIST, invariant="порядок: начало пролёта, затем название, затем идентификатор")
def test_order(svc, world, events):
    late = world.thing("epoch", "Романтизм", "1790–1850")
    b = world.thing("epoch", "Барокко", "1600–1750")
    a = world.thing("epoch", "Античное наследие", "1600–1700")
    twins = sorted([world.thing("epoch", "Маньеризм", "1600–1650") for _ in range(2)])
    early = world.thing("epoch", "Схоластика", "1100–1400")
    data, rid = epochs(svc)
    assert [e["id"] for e in data["epochs"]] == [early, a, b, *twins, late]
    assert listed(events, rid)["epochs"] == 6


@req(EP, LIST, invariant="не больше 500 эпох, с truncated")
def test_limit_500(svc, onto, events):
    value = FuzzyDate(1600, 1600, 1700, 1700, "year", "1600–1700").to_json()
    for n in range(501):
        e = onto.entities.create("epoch", [("ru", f"Эпоха {n:03d}", "primary")])
        onto.statements.add(e, "dating", value=value, attributions=[Attribution("common")])
    data, rid = epochs(svc)
    assert len(data["epochs"]) + len(data["undated"]) == 500
    assert data["truncated"] is True
    event = listed(events, rid)
    assert (event["epochs"], event["truncated"]) == (500, True)


@req(EP, LIST, invariant="краткое описание с пометкой «сгенерировано»; модель не вызывается")
@pytest.mark.parametrize("generated", [True, False])
def test_summary_mark_without_model(svc, world, events, generated):
    e = world.thing("epoch", "Просвещение", "1680–1800")
    world.describe(e, "Интеллектуальное движение XVIII века.", generated=generated)
    data, rid = epochs(svc)
    [item] = data["epochs"]
    assert item["summary"]["text"] == "Интеллектуальное движение XVIII века."
    assert item["summary"]["generated"] is generated
    assert svc.llm_calls == []
    assert listed(events, rid)["epochs"] == 1


@req(EP, LIST, invariant="чёткая граница — значения пары равны; эпохи без датировки отдельно")
def test_fuzzy_pairs_and_empty(svc, world, events):
    data, rid = epochs(svc)
    assert data == {"epochs": [], "undated": [], "truncated": False}
    assert (listed(events, rid)["epochs"], listed(events, rid)["undated"]) == (0, 0)
    world.thing("epoch", "Просвещение", "1680–1800")
    svc.clock.advance(seconds=60)  # окно устарелости снимка
    data, rid = epochs(svc)
    [item] = data["epochs"]
    assert item["fuzzy"] == {"from": [1680, 1680], "to": [1800, 1800]}
    assert listed(events, rid)["epochs"] == 1
