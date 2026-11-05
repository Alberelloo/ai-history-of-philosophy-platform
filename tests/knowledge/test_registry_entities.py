"""Требования спецификаций ontology-registry и ontology-entities."""

from __future__ import annotations

import pytest

from philograph.knowledge.dates import parse
from philograph.knowledge.entities import DuplicateEntity
from philograph.knowledge.registry import RegistryError
from philograph.knowledge.statements import Attribution, StatementError

req = pytest.mark.req
OR = "ontology-registry"
OE = "ontology-entities"


@req(OR, "Типы сущностей в реестре")
def test_entity_types(onto):
    codes = set(onto.registry._load()["entity_types"])
    assert {
        "term",
        "concept",
        "conception",
        "doctrine",
        "problem",
        "position",
        "argument",
        "person",
        "group",
        "work",
        "event",
        "idea_event",
        "phenomenon",
        "epoch",
        "place",
    } <= codes
    assert onto.registry.entity_subtypes("event") == {"event", "idea_event"}


@req(OR, "Типы связей в реестре")
def test_relation_types_with_inverse(onto):
    spec = onto.registry.relation("influenced_by")
    assert spec["title"] == "испытал влияние" and spec["inverse_title"] == "повлиял на"
    for key in (
        "subject_types",
        "object_types",
        "parent",
        "symmetric",
        "transitive",
        "families",
        "qualifiers",
        "v0",
    ):
        assert key in spec
    kant, hume = onto.person("Кант"), onto.person("Юм")
    onto.sourced(kant, "influenced_by", hume)
    seen_from_hume = onto.statements.about(hume)[0]
    assert seen_from_hume["direction"] == "in"  # с его стороны читается как «повлиял на»


@req(OR, "Иерархия связей")
def test_relation_hierarchy(onto):
    kant, hume, leibniz = onto.person("Кант"), onto.person("Юм"), onto.person("Лейбниц")
    onto.sourced(kant, "criticizes", hume)
    onto.statements.add(kant, "develops", obj=leibniz, attributions=[Attribution("common")])
    found = onto.statements.about(kant, types=["influenced_by"], derived=False)
    assert {s["type"] for s in found} == {"criticizes", "develops"}
    assert {
        "studied_with",
        "borrows",
        "develops",
        "reinterprets",
        "criticizes",
        "defends",
        "synthesizes",
        "written_in_response",
    } < onto.registry.relation_subtypes("influenced_by")


@req(OR, "Уточнители в реестре")
def test_qualifiers(onto):
    democracy = onto.thing("phenomenon", "Афинская демократия")
    sophists = onto.entities.create("group", [("ru", "Софисты", "primary")])
    onto.statements.add(
        democracy,
        "stimulated",
        obj=sophists,
        qualifiers={"mechanism": "economic"},
        attributions=[Attribution("common")],
    )
    with pytest.raises(StatementError):
        onto.statements.add(
            democracy,
            "stimulated",
            obj=sophists,
            qualifiers={"mechanism": "магический"},
            attributions=[Attribution("common")],
        )
    assert "mechanism" in onto.registry._load()["qualifiers"]


@req(OR, "Рецепты обхода в реестре")
def test_recipes(onto):
    genesis = onto.registry.recipe("genesis")
    assert genesis["direction"] == "backward" and genesis["depth"] == 3
    assert genesis["order"] == "time" and "genesis" in genesis["families"]
    assert {
        "genesis",
        "consequences",
        "polemic",
        "context",
        "answers",
        "conceptions",
        "path",
    } == set(onto.registry._load()["recipes"])


@req(OR, "Добавление типа без изменения кода")
def test_new_type_without_code(onto, events):
    onto.registry.add_relation(
        "operator",
        {
            "code": "patronized",
            "title": "покровительствовал",
            "inverse_title": "под покровительством",
            "subject_types": ["person", "group"],
            "object_types": ["person"],
            "families": ["biography"],
        },
    )
    christina, descartes = onto.person("Кристина Шведская"), onto.person("Декарт")
    onto.statements.add(
        christina, "patronized", obj=descartes, attributions=[Attribution("common")]
    )
    with pytest.raises(StatementError):
        onto.statements.add(
            descartes,
            "patronized",
            obj=onto.thing("concept", "Опыт"),
            attributions=[Attribution("common")],
        )
    onto.registry.propose("relation", {"code": "inspired_dream", "title": "вдохновил во сне"})
    assert onto.registry.proposals()[0]["payload"]["code"] == "inspired_dream"
    with pytest.raises(RegistryError):
        onto.registry.relation("inspired_dream")  # предложение не применено само
    events.one("knowledge.registry.proposal")


@req(OR, "Версии реестра")
def test_registry_versions_and_deprecation(onto):
    before = onto.registry.version()
    kant, hume = onto.person("Кант"), onto.person("Юм")
    onto.sourced(kant, "borrows", hume)
    with pytest.raises(RegistryError):
        onto.registry.delete_relation("operator", "borrows")
    onto.registry.deprecate_relation("operator", "borrows", "influenced_by")
    assert onto.registry.version() == before + 1
    with pytest.raises(StatementError):
        onto.sourced(kant, "borrows", onto.person("Лейбниц"))
    assert onto.statements.about(kant, derived=False)  # прежние остаются


@req(OR, "Схема вывода для LLM из реестра")
def test_output_schema_from_registry(onto):
    polemic = onto.registry.output_schema(["polemic"])
    allowed = set(polemic["properties"]["statements"]["items"]["properties"]["type"]["enum"])
    assert "criticizes" in allowed and "lived_in" not in allowed
    onto.registry.add_relation(
        "operator",
        {
            "code": "ridiculed",
            "title": "высмеивал",
            "subject_types": ["person"],
            "object_types": ["person"],
            "families": ["polemic"],
        },
    )
    assert (
        "ridiculed"
        in onto.registry.output_schema(["polemic"])["properties"]["statements"]["items"][
            "properties"
        ]["type"]["enum"]
    )


@req(OE, "Идентичность сущности")
def test_identity_and_primary_copy(onto):
    kant = onto.person("Кант", "1724", "1804")
    assert onto.entities.get(kant)["primary"]["dates"]["earliest_start"] == 1724
    newer = onto.statements.add(
        kant, "lifespan", value=parse("1724–1805").to_json(), attributions=[Attribution("common")]
    )
    onto.statements.set_rank(newer, "preferred", "operator")
    assert onto.entities.get(kant)["primary"]["dates"]["latest_end"] == 1805


@req(OE, "Названия")
def test_names_and_variants(onto):
    hume = onto.person("Юм")
    onto.entities.add_name(hume, "ru", "Хьюм")
    onto.entities.add_name(hume, "en", "Hume", "primary")
    assert [c["id"] for c in onto.entities.find("хьюм")] == [hume]
    assert onto.entities.label(hume, "en") == "Hume"


@req(OE, "Внешние идентификаторы")
def test_external_ids(onto):
    kant = onto.person("Кант", wikidata="Q9312")
    with pytest.raises(DuplicateEntity) as info:
        onto.person("Иммануил Кант", wikidata="Q9312")
    assert info.value.existing == kant


@req(OE, "Нечёткие даты")
def test_fuzzy_dates():
    ancient = parse("ок. 470 до н. э.")
    assert ancient.original == "ок. 470 до н. э." and ancient.precision == "approx"
    assert ancient.earliest_start == -469 - 10 and ancient.latest_end == -469 + 10
    century = parse("V в. до н. э.")
    assert century.before(ancient) is None  # неопределённое сравнение
    assert parse("1739–1740").before(parse("1781")) is True
    assert parse("1781").before(parse("1739")) is False


@req(OE, "Неоднозначные названия")
def test_ambiguous_names(onto):
    roger = onto.person("Бэкон", "1214", "1292")
    francis = onto.person("Бэкон", "1561", "1626")
    candidates = onto.entities.find("Бэкон")
    assert {c["id"] for c in candidates} == {roger, francis}
    assert all(c["primary"]["dates"] for c in candidates)


@req(OE, "Поиск дублей")
def test_duplicate_candidates(onto):
    a = onto.person("Дж. Локк", "1632", "1704")
    b = onto.person("Джон Локк", "1632", "1704")
    onto.person("Локк-младший", "1700", "1760")
    assert (a, b) in onto.entities.duplicate_candidates()


@req(OE, "Слияние с перенаправлением")
def test_merge_redirect_and_undo(onto, events):
    a = onto.person("Дж. Локк", "1632", "1704")
    b = onto.person("Джон Локк", "1632", "1704")
    tabula = onto.thing("concept", "Чистая доска")
    onto.statements.add(
        tabula, "description", value="образ ума до опыта", attributions=[Attribution("common")]
    )
    statement = onto.statements.add(
        b, "holds", obj=onto.thing("position", "Всё из опыта"), attributions=[Attribution("common")]
    )
    merge = onto.entities.merge(a, b)
    assert onto.entities.get(b)["id"] == a  # старый идентификатор ведёт на оставшуюся
    assert onto.statements.get(statement)["subject"] == a
    events.one("knowledge.entity.merged")
    onto.entities.undo_merge(merge)
    assert onto.entities.get(b)["id"] == b
    assert onto.statements.get(statement)["subject"] == b


@req(OE, "Связь с источниками библиотеки")
def test_textbook_is_a_work_with_edition(onto):
    work = onto.thing("work", "Учебник N")
    source = onto.entities.source_entity("s_textbook", "Учебник N, издание 1950")
    onto.statements.add(source, "edition_of", obj=work, attributions=[Attribution("common")])
    assert onto.entities.source_entity("s_textbook", "дубль") == source
    edition = onto.statements.about(work)[0]
    assert edition["type"] == "edition_of" and edition["subject"] == source
