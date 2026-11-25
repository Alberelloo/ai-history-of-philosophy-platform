"""Юнит-тесты проверки датировки извлечения (``knowledge/dating.py``) на опорных значениях.
Сценарии требования «Извлечение дат» — у тестировщика."""

from __future__ import annotations

import pytest

from philograph.knowledge import dating
from philograph.knowledge.dates import FuzzyDate, span


def _check(text, quote, paragraph=1, paragraphs=None, *, is_person=False):
    paragraphs = paragraphs if paragraphs is not None else [quote]
    return dating.check(text, quote, paragraph, paragraphs, is_person=is_person)


@pytest.mark.parametrize(
    ("text", "quote", "is_person", "expected_span", "precision"),
    [
        ("1724–1804", "Кант (1724–1804)", True, (1724, 1804), "year"),
        ("1724 - 1804", "Кант (1724 — 1804)", True, (1724, 1804), "year"),
        ("427–347 до н. э.", "Платон (427–347 до н. э.)", True, (-426, -346), "year"),
        ("427—347 до н.э.", "Платон (427–347 до нашей эры)", True, (-426, -346), "year"),
        ("1781", "„Критика чистого разума“ (1781)", False, (1781, 1781), "year"),
        ("ок. 1780", "около 1780 года", False, (1780, 1780), "approx"),
        ("circa 1780", "c. 1780", False, (1780, 1780), "approx"),
        ("ок. 1739–1740", "ок. 1739–1740", True, (1739, 1740), "approx"),
        ("ок. 470 до н. э.", "ок. 470 до н. э.", False, (-469, -469), "approx"),
        ("XVII в.", "в XVII в.", False, (1650, 1650), "century"),
        ("V в. до н. э.", "В V в. до н. э.", False, (-450, -450), "century"),
        ("XXI в.", "XXI в.", False, (2050, 2050), "century"),
    ],
)
def test_accepted(text, quote, is_person, expected_span, precision):
    result = _check(text, quote, is_person=is_person)
    assert isinstance(result, FuzzyDate)
    assert span(result) == expected_span
    assert result.precision == precision
    assert result.original == text


@pytest.mark.parametrize(
    ("text", "quote", "paragraph", "paragraphs", "is_person", "reason"),
    [
        ("1781", "1781", 0, ["1781"], False, dating.PARAGRAPH),
        ("1781", "1781", 2, ["1781"], False, dating.PARAGRAPH),
        ("1781", "1781", "1", ["1781"], False, dating.PARAGRAPH),
        ("1781", "1782", 1, ["в 1781"], False, dating.QUOTE),
        ("1781", "", 1, ["в 1781"], False, dating.QUOTE),
        ("в эпоху Просвещения", "в эпоху Просвещения", 1, None, False, dating.UNPARSED),
        ("4 до н. э. – 65", "4 до н. э. – 65", 1, None, False, dating.UNPARSED),
        ("XVIII в. – XIX в.", "XVIII в. – XIX в.", 1, None, False, dating.UNPARSED),
        ("0", "0", 1, None, False, dating.UNPARSED),
        ("2101", "2101", 1, None, False, dating.UNPARSED),
        ("1804–1724", "1804–1724", 1, None, False, dating.UNPARSED),
        ("XXII в.", "XXII в.", 1, None, False, dating.UNPARSED),
        ("IIII в.", "IIII в.", 1, None, False, dating.UNPARSED),
        ("22 апреля 1724", "22 апреля 1724", 1, None, False, dating.UNPARSED),
        ("1724", "в 17245 экземплярах", 1, None, False, dating.NOT_IN_QUOTE),
        ("1724–1804", "Кант родился в Кёнигсберге", 1, None, True, dating.NOT_IN_QUOTE),
        ("V в. до н. э.", "софисты учили за плату", 1, None, False, dating.NOT_IN_QUOTE),
        ("V в.", "в IV в.", 1, None, False, dating.NOT_IN_QUOTE),
        ("375", "(ок. 375 до н. э.)", 1, None, False, dating.ERA),
        ("375 до н. э.", "в 375 году", 1, None, False, dating.ERA),
        ("1724", "в 1724 году", 1, None, True, dating.SINGLE_YEAR),
        ("XVIII в.", "в XVIII в.", 1, None, True, dating.SINGLE_YEAR),
    ],
)
def test_rejected(text, quote, paragraph, paragraphs, is_person, reason):
    paragraphs = paragraphs if paragraphs is not None else [quote]
    assert dating.check(text, quote, paragraph, paragraphs, is_person=is_person) == reason


def test_quote_rule_like_statements():
    # Пробелы, регистр и «ё» не мешают найти цитату в абзаце.
    paragraph = "Кант  родился в Кёнигсберге (1724–1804)."
    assert isinstance(
        _check("1724–1804", "кант родился в кенигсберге (1724–1804)", 1, [paragraph]),
        FuzzyDate,
    )
