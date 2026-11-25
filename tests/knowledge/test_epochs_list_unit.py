"""Юнит-тесты списка эпох (``knowledge/epochs.py:EpochList``, ``GET /v1/epochs``)."""

from __future__ import annotations

from philograph.knowledge.dates import FuzzyDate
from philograph.knowledge.epochs import dating_source
from philograph.knowledge.statements import Attribution, Provenance


def test_epochs_list(svc, events):
    onto = svc.onto
    sci = onto.thing("epoch", "Научная революция", "1543–1687")
    enl = onto.entities.create("epoch", [("ru", "Просвещение", "primary")])
    onto.statements.add(
        enl,
        "dating",
        value=FuzzyDate(1680, 1680, 1800, 1800, "year", "1680–1800").to_json(),
        attributions=[Attribution("source", "wikidata:Q12539", place="https://x")],
        provenance=Provenance("imported"),
        status="sourced",
    )
    baroque = onto.thing("epoch", "Барокко")
    leibniz = onto.person("Лейбниц", "1646", "1716")
    onto.statements.add(
        leibniz, "belongs_to_epoch", obj=baroque, attributions=[Attribution("common")]
    )
    onto.person("Декарт", "1596", "1650")
    onto.person("Юм", "1711", "1776")
    onto.thing("event", "Энциклопедия", "1751")
    response, _ = svc.get("/v1/epochs")
    assert response.status_code == 200
    data = response.json()
    assert [e["id"] for e in data["epochs"]] == [sci, enl]
    first, second = data["epochs"]
    assert (first["from"], first["to"], first["fuzzy"]) == (
        1543,
        1687,
        {"from": [1543, 1543], "to": [1687, 1687]},
    )
    assert first["dating"] == {"status": "verified", "source": "common", "wikidata": None}
    assert second["dating"]["source"] == "wikidata" and second["dating"]["wikidata"] == "Q12539"
    assert first["counts"] == {"people": 1, "works": 0, "ideas": 0, "events": 0, "groups": 0}
    assert second["counts"]["people"] == 1 and second["counts"]["events"] == 1
    assert data["undated"] == [
        {
            "id": baroque,
            "label": "Барокко",
            "counts": {"people": 1, "works": 0, "ideas": 0, "events": 0, "groups": 0},
        }
    ]
    assert data["truncated"] is False
    [event] = events.of("knowledge.epochs.listed")
    assert {k: event[k] for k in ("epochs", "undated", "truncated", "snapshot")} == {
        "epochs": 2,
        "undated": 1,
        "truncated": False,
        "snapshot": "fresh",
    }
    catalog, _ = svc.catalog_ok({"epoch": enl, "type": "person"})
    assert catalog["facets"]["types"]["person"] == second["counts"]["people"]
    assert svc.llm_calls == []


def test_epochs_list_limit(svc, events):
    for i in range(3):
        svc.onto.thing("epoch", f"Эпоха {i}", f"{1500 + i}–{1600 + i}")
    from philograph.knowledge.epochs import EpochList

    data = EpochList(svc.catalog, max_epochs=2).list()
    assert len(data["epochs"]) == 2 and data["truncated"] is True


def test_dating_source_rules():
    def st(attrs, evidence=()):
        return {"status": "sourced", "attributions": attrs, "evidence": list(evidence)}

    def a(kind, who=None, hidden=False):
        return {"who_kind": kind, "who": who, "hidden": hidden}

    assert dating_source(st([a("source", "wikidata:Q1")]))["source"] == "wikidata"
    assert dating_source(st([a("source", "wikidata:Q1/../x")]))["wikidata"] is None
    assert dating_source(st([a("source", "src_1")]))["source"] == "source"
    assert dating_source(st([], [{"lost": False}]))["source"] == "source"
    assert dating_source(st([a("common")]))["source"] == "common"
    assert dating_source(st([a("source", "src_1", hidden=True)]))["source"] == "manual"
    assert dating_source(None)["source"] == "manual"
