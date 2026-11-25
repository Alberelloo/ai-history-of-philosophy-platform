"""Требования спецификаций knowledge-graph (карта раздела) и ontology-registry."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from philograph.knowledge import schema
from philograph.knowledge.app import build_app
from philograph.knowledge.map import MapSettings, SectionMap
from philograph.knowledge.statements import Attribution, Provenance

req = pytest.mark.req
KG = "knowledge-graph"
OR = "ontology-registry"
TEXTBOOK = "s_textbook"


def common(onto, subject, type_, **kw):
    return onto.statements.add(subject, type_, attributions=[Attribution("common")], **kw)


def mention(onto, entity_id: str, source_id: str = TEXTBOOK) -> None:
    with onto.statements.engine.begin() as conn:
        conn.execute(
            schema.mentions.insert().values(
                target_id="p1",
                target_kind="paragraph",
                source_id=source_id,
                entity_id=entity_id,
                start=0,
                end=3,
                method="name",
            )
        )


@pytest.fixture
def mx(onto):
    ids = {
        "descartes": onto.person("Рене Декарт", "1596", "1650"),
        "locke": onto.person("Джон Локк", "1632", "1704"),
        "hume": onto.person("Дэвид Юм", "1711", "1776"),
        "kant": onto.person("Иммануил Кант", "1724", "1804"),
        "fichte": onto.person("Иоганн Готлиб Фихте", "1762", "1814"),
        "critique": onto.thing("work", "Критика чистого разума", "1781"),
        "prolegomena": onto.thing("work", "Пролегомены", "1783"),
        "causality": onto.thing("concept", "Причинность"),
        "experience": onto.thing("concept", "Опыт"),
        "enlightenment": onto.thing("epoch", "Просвещение", "1680–1800"),
        "encyclopedia": onto.thing("event", "Энциклопедия", "1751"),
        "empiricism": onto.thing("group", "Эмпиризм"),
        "place": onto.thing("place", "Кёнигсберг"),
    }
    onto.entities.source_entity(TEXTBOOK, "Учебник N")
    for work in ("critique", "prolegomena"):
        common(onto, ids[work], "author", obj=ids["kant"])
    # Причинность рассматривается в обоих трудах — на карте она на году более раннего.
    common(onto, ids["prolegomena"], "discusses", obj=ids["causality"])
    common(onto, ids["critique"], "discusses", obj=ids["causality"])
    common(onto, ids["encyclopedia"], "event_kind", value="intellectual")
    common(onto, ids["empiricism"], "group_kind", value="direction")
    for member in ("locke", "hume"):
        common(onto, ids[member], "member_of", obj=ids["empiricism"])
    for role in ("philosopher", "scientist"):
        common(onto, ids["kant"], "person_role", value=role)
    ids["kant_hume"] = onto.sourced(ids["kant"], "influenced_by", ids["hume"])
    ids["fichte_kant"] = onto.statements.add(
        ids["fichte"],
        "influenced_by",
        obj=ids["kant"],
        attributions=[Attribution("common")],
        provenance=Provenance("generated"),
    )
    ids["hume_locke"] = common(onto, ids["hume"], "influenced_by", obj=ids["locke"])
    ids["kant_descartes"] = common(onto, ids["kant"], "criticizes", obj=ids["descartes"])
    onto.statements.reject(ids["kant_descartes"], "operator")
    ids["kant_experience"] = common(onto, ids["kant"], "influenced_by", obj=ids["experience"])
    return ids


def by_id(items):
    return {item["id"]: item for item in items}


def placed(data):
    """Все сущности ответа: на оси, группы и «без даты»."""
    sections = ("people", "works", "events", "eras", "groups", "undated")
    return [item for section in sections for item in data[section]]


@req(KG, "Карта раздела")
def test_contemporaries_on_time_axis(onto, mx):
    data = SectionMap(onto.statements).build()
    people = by_id(data["people"])
    hume, kant, descartes = people[mx["hume"]], people[mx["kant"]], people[mx["descartes"]]
    assert hume["birth"] < kant["death"] and kant["birth"] < hume["death"]  # перекрываются
    assert descartes["death"] < kant["birth"]
    assert kant == {
        "id": mx["kant"],
        "label": "Иммануил Кант",
        "short": "Кант",
        "birth": 1724,
        "death": 1804,
        "precision": "year",
        "roles": ["philosopher", "scientist"],
        "weight": kant["weight"],
        # add-epochs, «Карта раздела»: эпохи персоны (середина жизни 1764 — Просвещение).
        "epochs": [mx["enlightenment"]],
    }
    assert kant["weight"] > people[mx["descartes"]]["weight"]
    assert [p["id"] for p in data["people"]][:2] == [mx["descartes"], mx["locke"]]  # по году
    assert data["range"] == [1596, 1814]
    assert data["truncated"] is False and data["limit"] == 400
    # add-epochs, «Карта раздела»: у эпохи — нечёткие границы (у чётких значения равны),
    # у события — эпохи, к которым оно относится (1751 — Просвещение).
    assert data["eras"] == [
        {
            "id": mx["enlightenment"],
            "label": "Просвещение",
            "from": 1680,
            "to": 1800,
            "fuzzy": {"from": [1680, 1680], "to": [1800, 1800]},
        }
    ]
    assert data["events"] == [
        {
            "id": mx["encyclopedia"],
            "label": "Энциклопедия",
            "year": 1751,
            "kind": "intellectual",
            "epochs": [mx["enlightenment"]],
        }
    ]
    # Места, источники и термины на карту не попадают.
    assert mx["place"] not in {x["id"] for x in placed(data)}


@req(KG, "Карта раздела")
def test_work_and_idea_on_year(onto, mx):
    data = SectionMap(onto.statements).build()
    works = by_id(data["works"])
    critique = works[mx["critique"]]
    assert {k: critique[k] for k in ("type", "kind", "year", "author", "epochs")} == {
        "type": "work",
        "kind": "work",
        "year": 1781,
        "author": mx["kant"],
        "epochs": [mx["enlightenment"]],  # add-epochs: труд 1781 — Просвещение по дате
    }
    causality = works[mx["causality"]]
    assert (causality["kind"], causality["year"], causality["author"]) == (
        "concept",
        1781,
        mx["kant"],
    )
    # add-epochs: у идеи есть поле ``epochs``; идея без явной принадлежности — пусто
    # («Принадлежность к эпохе»: идеи относятся к эпохе только явно).
    assert set(causality) == {"id", "label", "type", "kind", "year", "author", "weight", "epochs"}
    assert causality["epochs"] == []
    # Без датировки и без датированного труда — не на оси, а в «без даты».
    assert mx["experience"] not in works
    assert {"id": mx["experience"], "label": "Опыт", "type": "concept"} in data["undated"]


@req(KG, "Карта раздела")
def test_links_only_between_people_without_rejected(onto, mx):
    data = SectionMap(onto.statements).build()
    links = by_id(data["links"])
    assert set(links) == {mx["kant_hume"], mx["fichte_kant"], mx["hume_locke"]}
    assert mx["kant_descartes"] not in links  # отклонённая не отдаётся
    assert mx["kant_experience"] not in links  # линии только между людьми
    assert links[mx["fichte_kant"]]["generated"] is True
    assert links[mx["kant_hume"]] == {
        "id": mx["kant_hume"],
        "subject": mx["kant"],
        "object": mx["hume"],
        "type": "influenced_by",
        "status": "sourced",
        "generated": False,
        "in_textbook": None,
    }
    marked = by_id(SectionMap(onto.statements).build(textbook=TEXTBOOK)["links"])
    assert marked[mx["kant_hume"]]["in_textbook"] is True
    assert marked[mx["hume_locke"]]["in_textbook"] is False
    # Отвергнутое (ранг «устаревшее») скрыто, как в обходе.
    onto.statements.set_rank(mx["hume_locke"], "deprecated", "operator")
    assert mx["hume_locke"] not in by_id(SectionMap(onto.statements).build()["links"])


@req(KG, "Карта раздела")
def test_textbook_scope(onto, mx):
    mention(onto, mx["enlightenment"])
    mention(onto, mx["kant"], source_id="s_other")
    data = SectionMap(onto.statements).build(textbook=TEXTBOOK, only_textbook=True)
    # Кант и Юм — по атрибуции учебника, Просвещение — по упоминанию в нём.
    assert {p["id"] for p in data["people"]} == {mx["kant"], mx["hume"]}
    assert [e["id"] for e in data["eras"]] == [mx["enlightenment"]]
    assert data["works"] == [] and data["events"] == [] and data["groups"] == []
    assert [link["id"] for link in data["links"]] == [mx["kant_hume"]]
    # Факты о сущностях — из всей библиотеки: годы жизни не из учебника, но известны.
    assert by_id(data["people"])[mx["kant"]]["birth"] == 1724


@req(KG, "Ограничение размера")
def test_limit_keeps_heaviest(onto, mx):
    data = SectionMap(onto.statements, MapSettings(max_entities=3)).build()
    kept = placed(data)
    assert len(kept) == 3 and data["truncated"] is True and data["limit"] == 3
    assert mx["kant"] in {p["id"] for p in data["people"]}  # самый весомый
    people = {p["id"] for p in data["people"]}
    assert all(link["subject"] in people and link["object"] in people for link in data["links"])
    groups = data["groups"]
    assert all(set(g["members"]) <= people for g in groups)


@req(OR, "Виды групп, роли персон и виды событий")
def test_group_kind_on_map(onto, mx):
    data = SectionMap(onto.statements).build()
    assert data["groups"] == [
        {
            "id": mx["empiricism"],
            "label": "Эмпиризм",
            "kind": "direction",
            "members": sorted([mx["locke"], mx["hume"]]),
        }
    ]


@req(OR, "Типы сущностей в реестре")
def test_epoch_span_on_map(onto):
    epoch = onto.thing("epoch", "Схоластика")
    assert SectionMap(onto.statements).build()["undated"] == [
        {"id": epoch, "label": "Схоластика", "type": "epoch"}
    ]
    onto.statements.add(
        epoch,
        "dating",
        value={
            "earliest_start": 1050,
            "latest_start": 1150,
            "earliest_end": 1400,
            "latest_end": 1500,
            "precision": "approx",
            "original": "XI–XV вв.",
        },
        attributions=[Attribution("common")],
    )
    data = SectionMap(onto.statements).build()
    assert data["eras"] == [
        {
            "id": epoch,
            "label": "Схоластика",
            "from": 1100,
            "to": 1450,
            "fuzzy": {"from": [1050, 1150], "to": [1400, 1500]},  # add-epochs
        }
    ]
    assert data["range"] == [1100, 1450]


@req(KG, "Карта раздела")
def test_map_route_and_cache(onto, mx, events):
    section_map = SectionMap(onto.statements)
    client = TestClient(build_app(onto.statements, section_map=section_map))
    first = client.get("/v1/map", params={"textbook": TEXTBOOK}).json()
    assert set(first) == {
        "range",
        "truncated",
        "limit",
        "people",
        "works",
        "events",
        "eras",
        "groups",
        "links",
        "undated",
    }
    again = client.get("/v1/map", params={"textbook": TEXTBOOK}).json()
    assert again == first
    built = events.where("knowledge.map.built")
    assert [e["cached"] for e in built] == [False, True]
    # Новое утверждение меняет отпечаток базы — карта пересобирается.
    common(onto, mx["fichte"], "studied_with", obj=mx["kant"])
    fresh = client.get("/v1/map", params={"textbook": TEXTBOOK}).json()
    assert len(fresh["links"]) == len(first["links"]) + 1
    assert events.where("knowledge.map.built")[-1]["cached"] is False
    # Отклонение тоже меняет отпечаток (журнал статусов).
    onto.statements.reject(mx["fichte_kant"], "operator")
    assert mx["fichte_kant"] not in by_id(client.get("/v1/map").json()["links"])


@req(KG, "Карта раздела")
def test_empty_map(onto):
    data = SectionMap(onto.statements).build()
    assert data["range"] is None and data["people"] == [] and data["truncated"] is False
