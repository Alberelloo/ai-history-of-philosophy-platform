"""Юнит-тесты О18: причины отказа кодами без названия, датировка не привязывает элемент снова,
предел группы в ``duplicate_candidates``. Сценарии требований — у тестировщика."""

from __future__ import annotations

import pytest
from sqlalchemy import select

import philograph.knowledge.filling  # noqa: F401  — события извлечения
from philograph.knowledge import dating, dedupe, entities
from philograph.knowledge import schema as t
from philograph.knowledge.entity_items import ENTITY_AMBIGUOUS, ENTITY_NO_TYPE, EntityItems, Skip

WINDOW = [{"id": "p1", "text": "Юм (1711–1776) писал о причинности."}]
DATING = {"text": "1711–1776", "paragraph": 1, "quote": "Юм (1711–1776)"}


@pytest.fixture
def items(onto):
    return EntityItems(onto.entities, onto.statements)


def _ambiguous_links(onto) -> int:
    with onto.statements.engine.begin() as conn:
        rows = conn.execute(
            select(t.review_items).where(t.review_items.c.kind == "ambiguous_link")
        ).all()
    return len(rows)


def test_no_type_is_code(items):
    with pytest.raises(Skip) as exc:
        items.resolve("Нечто", None, None, {})
    assert str(exc.value) == ENTITY_NO_TYPE == "entity:no_type"


def test_ambiguous_is_code_without_name(onto, items):
    onto.entities.create("person", [("ru", "Юм", "primary")])
    onto.entities.create("person", [("en", "Юм", "variant"), ("ru", "Дэвид Юм", "primary")])
    with pytest.raises(Skip) as exc:
        items.resolve("Юм", "person", None, {})
    assert str(exc.value) == ENTITY_AMBIGUOUS == "entity:ambiguous"
    assert "Юм" not in str(exc.value)


def test_dating_after_failed_statement_does_not_resolve_again(onto, items):
    onto.entities.create("person", [("ru", "Юм", "primary")])
    onto.entities.create("person", [("en", "Юм", "variant"), ("ru", "Дэвид Юм", "primary")])
    item = {"name": "Юм", "type": "person", "dating": DATING}
    index = items.index([item], "run1")
    resolved: dict[str, str] = {}
    with pytest.raises(Skip):
        items.resolve("Юм", "person", index["Юм"], resolved)  # утверждение фрагмента
    with pytest.raises(Skip) as exc:
        items.date_item("Юм", index["Юм"], resolved, WINDOW, "src", "run1")
    assert str(exc.value) == dating.UNRESOLVED
    assert _ambiguous_links(onto) == 1


def test_dating_only_ambiguous_element_is_dating_code(onto, items):
    onto.entities.create("person", [("ru", "Юм", "primary")])
    onto.entities.create("person", [("en", "Юм", "variant"), ("ru", "Дэвид Юм", "primary")])
    item = {"name": "Юм", "type": "person", "dating": DATING}
    index = items.index([item], "run1")
    with pytest.raises(Skip) as exc:
        items.date_item("Юм", index["Юм"], {}, WINDOW, "src", "run1")
    assert str(exc.value) == dating.UNRESOLVED
    assert _ambiguous_links(onto) == 1


def test_index_resets_unresolved(onto, items):
    with pytest.raises(Skip):
        items.resolve("Нечто", None, None, {})
    assert items.unresolved == {"Нечто"}
    items.index([], "run2")
    assert items.unresolved == set()


def test_dating_of_resolved_element(onto, items):
    onto.paragraphs["p1"] = WINDOW[0]["text"]
    item = {"name": "Юм", "type": "person", "dating": DATING}
    index = items.index([item], "run1")
    resolved: dict[str, str] = {}
    hume = items.resolve("Юм", "person", index["Юм"], resolved)
    items.date_item("Юм", index["Юм"], resolved, WINDOW, "src", "run1")
    assert onto.entities.get(hume)["primary"]["dates"]


def test_pair_key_is_unordered():
    assert dedupe.pair_key("b", "a") == dedupe.pair_key("a", "b") == ("a", "b")


def test_registry_entity_types(onto):
    assert {"person", "concept"} <= onto.registry.entity_types()


def test_large_last_word_group_is_capped_with_event(onto, events, monkeypatch):
    monkeypatch.setattr(entities, "MAX_LAST_WORD_GROUP", 2)
    for name in ("Фрэнсис Бэкон", "Роджер Бэкон", "Энтони Бэкон"):
        onto.entities.create("person", [("ru", name, "primary")])
    assert onto.entities.duplicate_candidates() == []
    [capped] = events.of("knowledge.entity.duplicate_group_capped")
    assert {k: capped.fields[k] for k in ("type", "size", "limit")} == {
        "type": "person",
        "size": 3,
        "limit": 2,
    }
    assert "Бэкон" not in str(capped.fields)


def test_group_within_limit_has_no_event(onto, events):
    onto.entities.create("person", [("ru", "Фрэнсис Бэкон", "primary")])
    onto.entities.create("person", [("ru", "Роджер Бэкон", "primary")])
    assert onto.entities.duplicate_candidates()
    assert events.of("knowledge.entity.duplicate_group_capped") == []
