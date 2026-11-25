"""Юнит-тесты общей функции границ датировки (``dates.span``/``dates.middle``)."""

from __future__ import annotations

import pytest

from philograph.knowledge.dates import FuzzyDate, lifespan, middle, parse, span


def fuzzy(es: int, ls: int, ee: int, le: int) -> dict:
    return FuzzyDate(es, ls, ee, le, "approx", "?").to_json()


@pytest.mark.parametrize(
    ("dates", "expected"),
    [
        (fuzzy(1679, 1680, 1800, 1800), (1680, 1800)),  # 1679,5 → 1680
        (fuzzy(1680, 1681, 1799, 1800), (1680, 1800)),  # 1680,5 → 1680, 1799,5 → 1800
        (fuzzy(1050, 1150, 1400, 1500), (1100, 1450)),
        (fuzzy(-470, -469, -399, -399), (-470, -399)),  # −469,5 → −470 (до н. э.)
        (fuzzy(-468, -467, -399, -398), (-468, -398)),  # −467,5 → −468, −398,5 → −398
    ],
)
def test_span_rounds_fuzzy_bounds(dates, expected):
    assert span(dates) == expected


def test_span_accepts_fuzzy_date_and_json_alike():
    d = lifespan("1724", "1804")
    assert span(d) == span(d.to_json()) == (1724, 1804)


def test_span_before_common_era():
    # «ок. 470 до н. э.» — 470 до н. э. = −469 в астрономическом счёте, ± 10.
    assert span(parse("ок. 470 до н. э.")) == (-469, -469)
    # Век — граница от −499 до −400: середина −449,5 округляется к чётному, −450.
    assert span(parse("V в. до н. э.")) == (-450, -450)


def test_middle_is_not_rounded():
    assert middle(lifespan("1632", "1704")) == 1668.0
    assert middle(lifespan("1685", "1753")) == 1719.0
    assert middle(lifespan("1711", "1776")) == 1743.5
    assert middle(parse("1687")) == 1687.0


def test_middle_uses_rounded_span():
    assert middle(fuzzy(1679, 1680, 1681, 1682)) == (1680 + 1682) / 2
