"""Группы типов справочника клиента (``web/src/reference/groups.json``) сверены с реестром."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from philograph.knowledge import registry_data

GROUPS = Path(__file__).resolve().parents[2] / "web" / "src" / "reference" / "groups.json"


def test_groups_cover_registry_types_once():
    groups = json.loads(GROUPS.read_text(encoding="utf-8"))
    codes = Counter(code for members in groups.values() for code in members)
    registry = {code for code, *_ in registry_data.ENTITY_TYPES}
    assert set(codes) <= registry, f"неизвестные реестру коды: {set(codes) - registry}"
    assert set(codes) == registry - {"source"}  # источник библиотеки в справочник не входит
    assert all(n == 1 for n in codes.values()), codes
    assert list(groups) == ["person", "ideas", "term", "work", "events", "epoch", "group", "place"]
