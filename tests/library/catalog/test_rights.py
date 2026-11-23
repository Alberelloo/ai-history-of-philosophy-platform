"""Требование source-catalog «Классификация правового статуса»."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from philograph.library.catalog.rights import classify_tier

req = pytest.mark.req
SC = "source-catalog"


@dataclass
class Harvest:
    metadata: dict
    license_hint: str | None = None


def harvest(authors=None, hint=None, translator=None) -> Harvest:
    meta = {"authors": authors or []}
    if translator:
        meta["translator"] = translator
    return Harvest(meta, hint)


@req(SC, "Классификация правового статуса")
def test_public_domain_by_death_years():
    h = harvest([{"name": "Кант", "death_year": 1804}], hint="Public domain in the USA.")
    rights = classify_tier(h, 2026)
    assert rights["rights_tier"] == "public_domain"


@req(SC, "Классификация правового статуса")
def test_in_copyright_when_recent_death():
    h = harvest([{"name": "Автор", "death_year": 1990}], hint="Public domain in the USA.")
    assert classify_tier(h, 2026)["rights_tier"] == "in_copyright"


@req(SC, "Классификация правового статуса")
def test_unknown_without_data():
    h = harvest([{"name": "Автор", "death_year": None}])
    assert classify_tier(h, 2026)["rights_tier"] == "unknown"


@req(SC, "Классификация правового статуса")
def test_translation_counts_as_author():
    h = harvest(
        [{"name": "Кант", "death_year": 1804}],
        hint="Public domain.",
        translator={"name": "Пер.", "death_year": 1990},
    )
    assert classify_tier(h, 2026)["rights_tier"] == "in_copyright"
