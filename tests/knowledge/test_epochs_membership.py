"""epochs, «Принадлежность к эпохе»: правило видно в ответе справочника и карты.

Сценарии из дельты ``openspec/changes/add-reference-catalog/specs/epochs``. Принадлежность
читается так, как её получает читатель: поле ``epochs`` записи справочника (``GET /v1/catalog``)
и фильтр ``epoch``; для пролёта эпохи — ответ карты ``/v1/map``. Каждый тест проверяет и
событие ``knowledge.catalog.listed`` (или ``knowledge.map.built``) этого запроса.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from philograph.knowledge import schema as t
from philograph.knowledge.dates import FuzzyDate

req = pytest.mark.req
EP = "epochs"
RULE = "Принадлежность к эпохе"
LISTED = "knowledge.catalog.listed"


def listed(events, rid):
    found = events.where(LISTED, request_id=rid)
    assert len(found) == 1, events.names()
    return found[0]


def epochs_of(svc, events, entity: str) -> list[tuple[str, str]]:
    """Эпохи сущности по ответу справочника: [(id эпохи, основание)]."""
    body, rid = svc.catalog_ok({"limit": "60"})
    listed(events, rid)
    item = next(i for i in body["items"] if i["id"] == entity)
    return [(e["id"], e["basis"]) for e in item["epochs"]]


def members(svc, events, epoch: str) -> set[str]:
    body, rid = svc.catalog_ok({"epoch": epoch, "limit": "60"})
    assert listed(events, rid)["filters"] == ["epoch"]
    return {i["id"] for i in body["items"]}


@pytest.fixture
def world(svc):
    w = svc.world
    return {
        "sci": w.thing("epoch", "Научная революция", "1543–1687"),
        "enl": w.thing("epoch", "Просвещение", "1680–1800"),
        "locke": w.person("Джон Локк", "1632", "1704"),
        "berkeley": w.person("Джордж Беркли", "1685", "1753"),
    }


@req(EP, RULE, scenario="По середине жизни")
def test_middle_of_life(svc, events, world):
    assert epochs_of(svc, events, world["locke"]) == [(world["sci"], "dates")]
    assert world["locke"] not in members(svc, events, world["enl"])


@req(EP, RULE, scenario="Явное важнее дат")
def test_explicit_over_dates(svc, events, world):
    svc.world.belongs(world["locke"], world["enl"])
    assert epochs_of(svc, events, world["locke"]) == [(world["enl"], "explicit")]
    assert world["locke"] in members(svc, events, world["enl"])
    assert world["locke"] not in members(svc, events, world["sci"])


@req(EP, RULE, scenario="Отклонённое и отвергнутое явное не действует")
def test_rejected_and_deprecated_explicit(svc, events, world):
    st = svc.world.belongs(world["locke"], world["enl"])
    svc.onto.statements.reject(st, "operator")
    dep = svc.world.belongs(world["berkeley"], world["enl"])
    svc.onto.statements.set_rank(dep, "deprecated", "operator")
    assert epochs_of(svc, events, world["locke"]) == [(world["sci"], "dates")]
    assert epochs_of(svc, events, world["berkeley"]) == [(world["enl"], "dates")]


@req(EP, RULE, invariant="отвергнутое явное не перекрывает даты даже к другой эпохе")
def test_deprecated_to_other_epoch_ignored(svc, events, world):
    dep = svc.world.belongs(world["berkeley"], world["sci"])
    svc.onto.statements.set_rank(dep, "deprecated", "operator")
    assert epochs_of(svc, events, world["berkeley"]) == [(world["enl"], "dates")]
    assert world["berkeley"] not in members(svc, events, world["sci"])


@req(EP, RULE, scenario="Пересекающиеся эпохи")
def test_overlapping_epochs(svc, events, world):
    nantes = svc.world.thing("event", "Отмена Нантского эдикта", "1685")
    assert sorted(epochs_of(svc, events, nantes)) == sorted(
        [(world["sci"], "dates"), (world["enl"], "dates")]
    )


@req(EP, RULE, scenario="Конец эпохи не включается")
def test_epoch_end_excluded(svc, events, world):
    principia = svc.world.thing("event", "Выход «Начал» Ньютона", "1687")
    assert epochs_of(svc, events, principia) == [(world["enl"], "dates")]
    assert principia not in members(svc, events, world["sci"])


YEARS = [
    (1542, set()),
    (1543, {"sci"}),
    (1679, {"sci"}),
    (1680, {"sci", "enl"}),
    (1686, {"sci", "enl"}),
    (1687, {"enl"}),
    (1799, {"enl"}),
    (1800, set()),
]


@pytest.mark.parametrize(("year", "expected"), YEARS)
@pytest.mark.parametrize("kind", ["event", "idea_event", "work", "phenomenon"])
@req(EP, RULE, invariant="пролёт эпохи [начало, конец)")
def test_half_open_span(svc, events, world, kind, year, expected):
    thing = svc.world.thing(kind, f"Предмет {year}", str(year))
    got = epochs_of(svc, events, thing)
    assert {e for e, _ in got} == {world[k] for k in expected}
    assert all(basis == "dates" for _, basis in got)


@pytest.mark.parametrize(
    ("birth", "death", "expected"),
    [
        ("1600", "1686", {"sci"}),  # середина 1643
        ("1640", "1720", {"sci", "enl"}),  # середина 1680 — оба пролёта
        ("1660", "1714", {"enl"}),  # середина 1687 — год конца «Научной революции», не входит
        ("1650", "1709", {"sci"}),  # середина 1679,5: с округлением было бы 1680 и оба пролёта
        ("1750", "1849", {"enl"}),  # середина 1799,5: с округлением было бы 1800 — ни одной
        ("1700", "1901", set()),  # середина 1800,5 — за концом «Просвещения»
    ],
)
@req(EP, RULE, invariant="персона — по середине жизни без округления")
def test_person_middle_of_life_unrounded(svc, events, world, birth, death, expected):
    person = svc.world.person(f"Персона {birth}", birth, death)
    got = epochs_of(svc, events, person)
    assert {e for e, _ in got} == {world[k] for k in expected}


@req(EP, RULE, scenario="Округление нечёткой границы")
def test_fuzzy_boundary_rounding(svc, events):
    fuzzy = FuzzyDate(1679, 1680, 1800, 1800, "approx", "1679/1680–1800").to_json()
    epoch = svc.world.dated("epoch", "Эпоха с нечётким началом", fuzzy)
    event = svc.world.thing("event", "Событие 1679", "1679")
    svc.world.relate(svc.world.person("Свидетель", "1650", "1720"), "participated", event)
    assert epochs_of(svc, events, event) == []
    assert event not in members(svc, events, epoch)
    response, rid = svc.get("/v1/map")
    assert response.status_code == 200
    era = next(e for e in response.json()["eras"] if e["id"] == epoch)
    assert era["from"] == 1680
    assert events.where("knowledge.map.built", request_id=rid)


@req(EP, RULE, scenario="Без датировки и группы")
def test_undated_and_groups(svc, events, world):
    w = svc.world
    anon = w.person("Анонимный схоласт")
    empiricism = w.thing("group", "Эмпиризм")
    w.relate(world["locke"], "member_of", empiricism)
    w.relate(world["berkeley"], "member_of", empiricism)
    experience = w.thing("concept", "Опыт")
    essay = w.thing("work", "Опыт о человеческом разумении", "1690")
    w.relate(essay, "discusses", experience)
    baroque = w.thing("epoch", "Барокко")
    w.relate(world["locke"], "influenced_by", experience)
    for entity in (anon, empiricism, experience, baroque):
        assert epochs_of(svc, events, entity) == [], entity
    assert members(svc, events, baroque) == set()
    assert epochs_of(svc, events, essay) == [(world["enl"], "dates")]  # труд — по датам


@pytest.mark.parametrize("kind", ["group", "concept", "conception", "doctrine", "term", "place"])
@req(EP, RULE, invariant="идеи и группы — только по явным утверждениям")
def test_ideas_and_groups_only_explicit(svc, events, world, kind):
    w = svc.world
    thing = w.thing(kind, f"Сущность {kind}")
    work = w.thing("work", "Труд 1700", "1700")
    w.relate(work, "discusses", thing)
    if kind == "group":
        w.relate(world["berkeley"], "member_of", thing)
    assert epochs_of(svc, events, thing) == []
    w.belongs(thing, world["sci"])
    svc.clock.advance(seconds=15)
    assert epochs_of(svc, events, thing) == [(world["sci"], "explicit")]


@req(EP, RULE, invariant="эпоха не относится к себе")
def test_epoch_not_member_of_itself(svc, events, world):
    w = svc.world
    nested = w.thing("epoch", "Раннее Просвещение", "1680–1720")
    assert world["enl"] not in {e for e, _ in epochs_of(svc, events, world["enl"])}
    assert world["enl"] not in members(svc, events, world["enl"])
    assert nested not in members(svc, events, nested)


@req(EP, RULE, invariant="несколько явных утверждений — несколько эпох")
def test_several_explicit(svc, events, world):
    w = svc.world
    w.belongs(world["locke"], world["sci"])
    w.belongs(world["locke"], world["enl"])
    assert sorted(epochs_of(svc, events, world["locke"])) == sorted(
        [(world["sci"], "explicit"), (world["enl"], "explicit")]
    )


@req(EP, RULE, scenario="Вывод не хранится")
def test_derived_not_stored(svc, events, world):
    def count() -> int:
        with svc.onto.statements.engine.begin() as conn:
            return conn.scalar(
                select(func.count())
                .select_from(t.statements)
                .where(t.statements.c.type == "belongs_to_epoch")
            )

    before = count()
    events.clear()
    body, rid = svc.catalog_ok({"epoch": world["enl"]})
    assert world["berkeley"] in {i["id"] for i in body["items"]}
    assert listed(events, rid)["filters"] == ["epoch"]
    assert count() == before
    events.assert_none("knowledge.statement.created")
