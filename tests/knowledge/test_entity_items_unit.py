"""Юнит-тесты привязки по всем написаниям (``knowledge/entity_items.py``). Сценарии требований
«Нормализация сущностей», «Язык названий» и «Извлечение дат» — у тестировщика."""

from __future__ import annotations

import pytest

import philograph.knowledge.filling  # noqa: F401  — события извлечения описаны там
from philograph.knowledge.dates import span
from philograph.knowledge.entity_items import EntityItems, Skip


@pytest.fixture
def items(onto):
    return EntityItems(onto.entities, onto.statements)


def _names(onto, entity_id):
    return {(n["lang"], n["text"], n["kind"]) for n in onto.entities.get(entity_id)["names"]}


def test_index_drops_unknown_type(items, events):
    index = items.index(
        [{"name": "Зевс", "type": "deity"}, {"name": "Кант", "type": "person"}], "run1"
    )
    assert list(index) == ["Кант"]
    assert [e.fields["reason"] for e in events.of("knowledge.extraction.dropped")] == [
        "entity:type"
    ]


def test_resolve_by_english_spelling_renames(onto, items, events):
    locke = onto.entities.create("person", [("en", "Locke", "primary")])
    item = {"name": "Локк", "type": "person", "ru": "Локк", "en": "Locke"}
    assert items.resolve("Локк", "person", item, {}) == locke
    assert _names(onto, locke) == {("ru", "Локк", "primary"), ("en", "Locke", "variant")}
    assert len(events.of("knowledge.entity.renamed")) == 1
    assert items.created == []


def test_rejected_russian_spelling_keeps_primary(onto, items, events):
    plato = onto.entities.create("person", [("en", "Plato", "primary")])
    item = {"name": "Plato", "type": "person", "ru": "поэт"}
    assert items.resolve("Plato", "person", item, {}) == plato
    assert _names(onto, plato) == {("en", "Plato", "primary")}
    assert [e.fields["label"] for e in events.of("knowledge.entity.rejected")] == ["поэт"]
    assert events.of("knowledge.entity.renamed") == []


def test_spellings_found_different_entities(onto, items, events):
    onto.entities.create("concept", [("en", "Substance", "primary")])
    onto.entities.create("concept", [("ru", "Субстанция", "primary")])
    item = {"name": "Субстанция", "type": "concept", "ru": "Субстанция", "en": "Substance"}
    with pytest.raises(Skip):
        items.resolve("Субстанция", "concept", item, {})
    assert events.of("knowledge.extraction.ambiguous")[0].fields["candidates"] == 2


def test_create_with_variants(onto, items):
    item = {"name": "Платон", "type": "person", "ru": "Платон", "en": "Plato"}
    entity = items.resolve("Платон", "person", item, {})
    assert _names(onto, entity) == {("ru", "Платон", "primary"), ("en", "Plato", "variant")}
    assert items.created == [entity]


def test_create_without_item_lang_by_script(onto, items):
    entity = items.resolve("Ding an sich", "concept", None, {})
    assert _names(onto, entity) == {("en", "Ding an sich", "primary")}


def test_invalid_new_name_is_skip(items, events):
    with pytest.raises(Skip):
        items.resolve("20.1", "concept", None, {})
    assert events.of("knowledge.entity.rejected")[0].fields["reason"] == "number"


def test_date_lifespan(onto, items):
    onto.paragraphs["pk"] = "Кант (1724–1804) родился в Кёнигсберге."
    kant = onto.entities.create("person", [("ru", "Кант", "primary")])
    item = {"dating": {"text": "1724–1804", "paragraph": 1, "quote": "Кант (1724–1804)"}}
    window = [{"id": "pk", "text": onto.paragraphs["pk"]}]
    items.date(kant, item, window, "s_textbook", "run1")
    assert span(onto.entities.get(kant)["primary"]["dates"]) == (1724, 1804)


def test_date_rejected_reason(onto, items):
    kant = onto.entities.create("person", [("ru", "Кант", "primary")])
    item = {"dating": {"text": "1724", "paragraph": 1, "quote": "в 1724 году"}}
    with pytest.raises(Skip, match="dating:single_year"):
        items.date(kant, item, [{"id": "px", "text": "в 1724 году"}], "s_textbook", "run1")


def test_date_type_not_allowed_is_code(onto, items):
    """Датировка у типа, которому реестр её не разрешает (понятие), — код ``dating:type`` (О15)."""
    idea = onto.entities.create("concept", [("ru", "Идея", "primary")])
    item = {"dating": {"text": "1781", "paragraph": 1, "quote": "в 1781 году"}}
    with pytest.raises(Skip, match="^dating:type$"):
        items.date(idea, item, [{"id": "px", "text": "в 1781 году"}], "s_textbook", "run1")


def test_spellings_found_two_persons_merge(onto, items, events):
    locke = onto.entities.create(
        "person", [("en", "Locke", "primary")], external={"wikidata": "Q9353"}
    )
    lokk = onto.entities.create("person", [("ru", "Локк", "primary")])
    item = {"name": "Локк", "type": "person", "ru": "Локк", "en": "Locke"}
    assert items.resolve("Локк", "person", item, {}) == locke
    assert onto.entities.resolve(lokk) == locke
    assert events.one("knowledge.entity.merged").fields["reason"] == "merge:model_pair"
    assert {(n["lang"], n["text"], n["kind"]) for n in onto.entities.get(locke)["names"]} == {
        ("ru", "Локк", "primary"),
        ("en", "Locke", "variant"),
    }


def test_spellings_found_two_persons_with_conflicting_dates(onto, items, events):
    onto.person("Berkeley", "1685", "1753")
    onto.person("Беркли", "1885", "1953")
    item = {"name": "Беркли", "type": "person", "ru": "Беркли", "en": "Berkeley"}
    with pytest.raises(Skip):
        items.resolve("Беркли", "person", item, {})
    assert events.one("knowledge.entity.merge_proposed").fields["reason"] == "review:dates"
    assert events.of("knowledge.entity.merged") == []
    assert len(events.of("knowledge.extraction.ambiguous")) == 1
