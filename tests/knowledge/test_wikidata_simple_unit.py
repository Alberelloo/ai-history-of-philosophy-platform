"""Юнит-тесты ``wikidata.simple_time``, ``WIKIDATA_ROLES``, ``HUMAN`` (add-wikidata-life-dates,
задача 2.2). Сценарные и нормативные тесты требований — у тестировщика."""

from __future__ import annotations

import pytest

from philograph.knowledge.dates import span
from philograph.knowledge.wikidata import HUMAN, WIKIDATA_ROLES, simple_time, wikidata_time


@pytest.mark.parametrize(
    ("value", "expected", "original"),
    [
        ("+1724-04-22", (1724, 1724), "1724"),
        ("-0427-00-00T00:00:00Z", (-426, -426), "427 до н. э."),
        ("-0427-00-00", (-426, -426), "427 до н. э."),
        ("+1781-00-00T00:00:00Z", (1781, 1781), "1781"),
    ],
)
def test_simple_time_sign_is_era(value, expected, original):
    found = simple_time(value)
    assert found is not None
    assert span(found) == expected
    assert (found.precision, found.original) == ("year", original)


@pytest.mark.parametrize("value", ["+0000-00-00", "1724", "+1724", "+1724-4-22", None, 1724, ""])
def test_simple_time_rejects_bad_values(value):
    assert simple_time(value) is None


def test_simple_time_equals_year_precision_rule():
    assert simple_time("-0347-01-01") == wikidata_time("-0347-01-01T00:00:00Z", 9)


def test_roles_table_and_human():
    assert HUMAN == "Q5"
    assert WIKIDATA_ROLES["Q4964182"] == "philosopher"
    assert set(WIKIDATA_ROLES.values()) == {
        "philosopher",
        "scientist",
        "writer",
        "theologian",
        "ruler",
        "translator",
    }
