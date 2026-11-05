"""Восстановление производных данных: индексы строятся заново из библиотеки."""

from __future__ import annotations

import pytest

req = pytest.mark.req


@req("backup-and-recovery", "Восстановление производных данных")
def test_reindex_after_vector_store_loss(rig, events):
    rig.publish("ru")
    rig.indexer.vectors.client.delete_collection(rig.indexer.active_collection)  # база потеряна
    lexical = rig.search("привычка ума")
    assert lexical["results"] and lexical["semantic_used"] is False  # по словам работает
    totals = rig.indexer.reindex()
    assert totals["versions"] == 1 and totals["indexed"] > 0 and totals["embedded"] > 0
    assert events.one("search.index.rebuilt")["embedded"] == totals["embedded"]
    semantic = rig.search("из прошлого нельзя вывести будущее")
    assert semantic["semantic_used"] is True and semantic["results"]
