"""Юнит-тесты ``knowledge.extraction_codes`` и ``Skip.code``; сценарии «Коды причин
отбраковки» — у тестировщика."""

from __future__ import annotations

import pytest

from philograph.knowledge import extraction_codes as codes
from philograph.knowledge.entity_items import EntityItems, Skip


@pytest.mark.parametrize(
    ("reason", "code"),
    [
        ("entity:type", "entity_type"),
        ("entity:no_type", "entity_no_type"),
        ("entity:ambiguous", "entity_ambiguous"),
        ("entity:number", "entity_invalid"),
        ("entity:stopword", "entity_invalid"),
        ("dating:quote", "dating_quote"),
        ("dating:unresolved", "dating_unresolved"),
        ("dating:что-то", "statement_refused"),
        ("quote_not_found", "quote_not_found"),
        ("тип объекта work недопустим", "statement_refused"),
    ],
)
def test_code_for(reason, code):
    assert codes.code_for(reason) == code
    assert code in codes.CODES


def test_skip_code():
    assert Skip("entity:ambiguous").code == "entity_ambiguous"
    assert Skip("ссылка на абзац вне фрагмента", codes.PARAGRAPH_OUT_OF_WINDOW).code == (
        "paragraph_out_of_window"
    )


def test_index_nulls_and_drop_callback(onto):
    items = EntityItems(onto.entities, onto.statements)
    dropped: list[tuple[str, str]] = []
    index = items.index(
        [
            {"name": "Кант", "type": "person", "ru": None, "en": "Kant", "dating": None},
            {"name": "Зевс", "type": "deity"},
            {"name": None, "type": "person"},
            "мусор",
        ],
        "run1",
        on_drop=lambda reason, code: dropped.append((reason, code)),
    )
    assert index == {"Кант": {"name": "Кант", "type": "person", "en": "Kant"}}
    assert dropped == [("entity:type", "entity_type")]


def test_index_not_a_list(onto):
    items = EntityItems(onto.entities, onto.statements)
    assert items.index({"name": "Кант"}, "run1") == {}
