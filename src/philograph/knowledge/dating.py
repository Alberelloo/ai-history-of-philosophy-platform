"""Проверка датировки, извлечённой моделью (спецификация entity-dating, «Извлечение дат»).

Модель предлагает текст даты, номер абзаца и цитату; код решает, записывать ли. Сначала текст
сверяется с белым списком форматов таблицы требования, и только потом разбирается общим
``dates.parse``: тот шире таблицы (смешанную эру и интервал веков он разбирает неверно), а
менять общий разбор ради извлечения не нужно.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from philograph.knowledge.dates import FuzzyDate, parse

PARAGRAPH = "dating:paragraph"
QUOTE = "dating:quote"
UNPARSED = "dating:unparsed"
NOT_IN_QUOTE = "dating:not_in_quote"
ERA = "dating:era"
SINGLE_YEAR = "dating:single_year"
TYPE = "dating:type"  # реестр не разрешает тип сущности для ``lifespan``/``dating``
UNRESOLVED = "dating:unresolved"  # сущность элемента не определена (отказ названия и т. п.)
REASONS = (PARAGRAPH, QUOTE, UNPARSED, NOT_IN_QUOTE, ERA, SINGLE_YEAR)

_DASH = r"\s*[-–—]\s*"
_YEAR = r"(\d{1,4})"
_APPROX = r"(?:ок\.|около|c\.|circa)\s*"
_ERA_TEXT = r"до\s+н\.\s?э\."
_ROMAN = r"([ivxlcdm]+)"

_YEARS_FORMAT = re.compile(
    rf"^(?P<approx>{_APPROX})?{_YEAR}(?:{_DASH}{_YEAR})?(?P<era>\s+{_ERA_TEXT})?$"
)
_CENTURY_FORMAT = re.compile(rf"^{_ROMAN}\s*в\.(?P<era>\s+{_ERA_TEXT})?$")

_ERA_IN_TEXT = re.compile(_ERA_TEXT)
_ERA_IN_QUOTE = re.compile(r"до\s+н\.\s?э\.|до\s+нашей\s+эры")
_NUMBER = re.compile(r"(?<!\d)\d{1,4}(?!\d)")

_ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
_ROMAN_CANON = re.compile(r"^(X{0,2})(IX|IV|V?I{0,3})$")
_EDGE = ".,;:!?()[]«»\"'„“”"
MAX_YEAR = 2100
MAX_CENTURY = 21


@dataclass(frozen=True)
class _Format:
    numbers: frozenset[int]
    roman: str | None
    single: bool  # один год или век


def _quote_key(text: str) -> str:
    """Правило цитат утверждений: пробелы схлопываются, «ё» → «е», нижний регистр."""
    return re.sub(r"\s+", " ", text.lower().replace("ё", "е")).strip()


def _roman_value(roman: str) -> int | None:
    roman = roman.upper()
    if not _ROMAN_CANON.match(roman):
        return None
    total, prev = 0, 0
    for ch in reversed(roman):
        value = _ROMAN_VALUES[ch]
        total += -value if value < prev else value
        prev = max(prev, value)
    return total if 1 <= total <= MAX_CENTURY else None


def _format(text: str) -> _Format | None:
    """Строка таблицы форматов, под которую подходит текст, или ``None``."""
    s = re.sub(r"\s+", " ", text.strip().lower())
    years = _YEARS_FORMAT.match(s)
    if years:
        first, second = years.group(2), years.group(3)
        values = [int(first)] + ([int(second)] if second else [])
        if any(not 1 <= v <= MAX_YEAR for v in values):
            return None
        if second and not years.group("era") and values[0] > values[1]:
            return None  # интервал нашей эры — начало не позже конца
        return _Format(frozenset(values), None, single=second is None)
    century = _CENTURY_FORMAT.match(s)
    if century and _roman_value(century.group(1)) is not None:
        return _Format(frozenset(), century.group(1).upper(), single=True)
    return None


def _quote_has_roman(quote: str, roman: str) -> bool:
    return any(word.strip(_EDGE).upper() == roman for word in quote.split())


def check(
    text: str,
    quote: str,
    paragraph: int,
    paragraphs: Sequence[str],
    *,
    is_person: bool,
) -> FuzzyDate | str:
    """Датировка или причина отказа — первая несработавшая проверка по порядку требования."""
    if isinstance(paragraph, bool) or not isinstance(paragraph, int):
        return PARAGRAPH
    if not 1 <= paragraph <= len(paragraphs):
        return PARAGRAPH
    key = _quote_key(quote or "")
    if not key or key not in _quote_key(paragraphs[paragraph - 1]):
        return QUOTE
    fmt = _format(text or "")
    if fmt is None:
        return UNPARSED
    in_quote = {int(n) for n in _NUMBER.findall(quote)}
    if not fmt.numbers <= in_quote:
        return NOT_IN_QUOTE
    if fmt.roman is not None and not _quote_has_roman(quote, fmt.roman):
        return NOT_IN_QUOTE
    era_text = bool(_ERA_IN_TEXT.search(text.lower()))
    era_quote = bool(_ERA_IN_QUOTE.search(_quote_key(quote)))
    if era_text != era_quote:
        return ERA
    if is_person and fmt.single:
        return SINGLE_YEAR
    return parse(text)
