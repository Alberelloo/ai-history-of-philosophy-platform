"""Нечёткие даты: четыре границы, точность и исходная запись (ontology.md, раздел 9.1).

Годы до нашей эры — в астрономическом счёте: 1 год до н. э. = 0, 470 год до н. э. = −469.
Сравнение учитывает неопределённость и может ответить «не определено» (``None``).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

_ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}


def _roman(text: str) -> int:
    total, prev = 0, 0
    for ch in reversed(text.upper()):
        value = _ROMAN[ch]
        total += -value if value < prev else value
        prev = max(prev, value)
    return total


@dataclass(frozen=True)
class FuzzyDate:
    earliest_start: int
    latest_start: int
    earliest_end: int
    latest_end: int
    precision: str  # year | decade | century | approx
    original: str

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict) -> FuzzyDate:
        return cls(**data)

    def before(self, other: FuzzyDate) -> bool | None:
        """Раньше ли эта дата другой: да, нет или не определено."""
        if self.latest_end < other.earliest_start:
            return True
        if self.earliest_start > other.latest_end:
            return False
        return None


def _astro(year: int, bce: bool) -> int:
    return 1 - year if bce else year


def parse(text: str) -> FuzzyDate:
    """Разбирает «1781», «1739–1740», «ок. 470 до н. э.», «V в. до н. э.», «XVII в.»."""
    original = text.strip()
    s = original.lower().replace("—", "–").replace("-", "–")
    bce = bool(re.search(r"до\s*н\.?\s*э|bce|bc\b", s))
    approx = bool(re.search(r"\bок\.|около|circa|\bc\.", s))
    century = re.search(r"\b([ivxlc]+)\s*в\b", s)
    if century:
        n = _roman(century.group(1))
        if bce:
            start, end = _astro(n * 100, True), _astro((n - 1) * 100 + 1, True)
        else:
            start, end = (n - 1) * 100 + 1, n * 100
        return FuzzyDate(start, end, start, end, "century", original)
    years = [int(y) for y in re.findall(r"\d{1,4}", s)]
    if not years:
        raise ValueError(f"не дата: {original}")
    if len(years) >= 2:  # интервал «1739–1740»
        a, b = _astro(years[0], bce), _astro(years[1], bce)
        start, end = min(a, b), max(a, b)
        slack = 5 if approx else 0
        return FuzzyDate(
            start - slack,
            start + slack,
            end - slack,
            end + slack,
            "approx" if approx else "year",
            original,
        )
    year = _astro(years[0], bce)
    slack = 10 if approx else 0
    return FuzzyDate(
        year - slack,
        year + slack,
        year - slack,
        year + slack,
        "approx" if approx else "year",
        original,
    )


# Годы жизни через короткое тире без пробелов: 1724–1804 (docs/design/system/content.md).
LIFESPAN_DASH = "–"
OLD_LIFESPAN_DASH = " – "  # запись до миграции knowledge:5


def lifespan(birth: str, death: str) -> FuzzyDate:
    b, d = parse(birth), parse(death)
    return FuzzyDate(
        b.earliest_start,
        b.latest_start,
        d.earliest_end,
        d.latest_end,
        "year" if b.precision == d.precision == "year" else "approx",
        f"{birth}{LIFESPAN_DASH}{death}",
    )


# «Худшая» точность интервала при равной ширине неопределённости: век, десятилетие, прочее.
_PRECISION_RANK = {"century": 3, "decade": 2, "approx": 1, "year": 0}


def join_original(start: str, end: str) -> str:
    """Исходная запись интервала: «1685–1815»; если в частях есть пробелы — тире с пробелами:
    «VIII в. до н. э. – V в.»."""
    dash = " – " if " " in start or " " in end else LIFESPAN_DASH
    return f"{start}{dash}{end}"


def interval(start: FuzzyDate, end: FuzzyDate, original: str | None = None) -> FuzzyDate:
    """Интервал из двух нечётких дат: начала — из ``start``, концы — из ``end``.

    Точность — ``year``, если обе даты с точностью до года; иначе точность той, у которой
    неопределённость шире (при равной — ``century`` > ``decade`` > ``approx``). Исходная
    запись — ``original`` или части через тире (``join_original``)."""

    def width(d: FuzzyDate) -> int:
        return max(d.latest_start - d.earliest_start, d.latest_end - d.earliest_end)

    if start.precision == end.precision == "year":
        precision = "year"
    else:
        rough = [d for d in (start, end) if d.precision != "year"]
        precision = max(rough, key=lambda d: (width(d), _PRECISION_RANK.get(d.precision, 1)))
        precision = precision.precision
    return FuzzyDate(
        start.earliest_start,
        start.latest_start,
        end.earliest_end,
        end.latest_end,
        precision,
        original if original is not None else join_original(start.original, end.original),
    )


def span(d: Mapping[str, Any] | FuzzyDate) -> tuple[int, int]:
    """Начало и конец датировки: середина каждой нечёткой границы, округлённая до года.

    Одно правило для пролётов карты, принадлежности к эпохе и списков: «1679 или 1680» —
    1680 (``round`` — банковское округление, как было на карте: 1679,5 → 1680, 1680,5 → 1680).
    Годы до н. э. — в астрономическом счёте, округление то же."""
    if isinstance(d, FuzzyDate):
        d = d.to_json()
    return (
        round((d["earliest_start"] + d["latest_start"]) / 2),
        round((d["earliest_end"] + d["latest_end"]) / 2),
    )


def middle(d: Mapping[str, Any] | FuzzyDate) -> float:
    """Середина датировки (или жизни) — полусумма начала и конца ``span`` без округления."""
    start, end = span(d)
    return (start + end) / 2
