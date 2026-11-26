"""Юнит-проверки: пути, создающие сущности из внешних данных, пропускают название, не
прошедшее правило названий, своим событием пропуска и не падают (improve-extraction-naming)."""

from __future__ import annotations

import subprocess
import sys

from philograph.knowledge.epoch_context import EpochContextImport
from philograph.knowledge.epoch_dates import EpochDates
from philograph.knowledge.geo_enrich import PlaceEnrichment

from .test_epoch_context_import import EPOCH_QID, PARIS, REVOLUTION, decide, harvested
from .test_geo_enrich import Fetch, person_record, place_record
from .wd_records import no_network  # noqa: F401
from .wikidata_fixtures import FixtureFetch


def test_geo_place_with_invalid_label_skipped(onto, events, no_network):
    hume = onto.person("Дэвид Юм", "1711", "1776", wikidata="Q37160")
    records = {
        "Q37160": person_record("Q37160", "Дэвид Юм", items={"P19": ["Q23436"]}),
        "Q23436": place_record("Q23436", "20.1", 55.95, -3.19),
    }
    summary = PlaceEnrichment(onto.statements, Fetch(records)).run()
    skipped = [(e.get("entity"), e.get("reason")) for e in events.of("knowledge.geo.skipped")]
    assert (hume, "refused") in skipped
    assert onto.entities.by_external("wikidata", "Q23436") is None
    assert [e.get("reason") for e in events.of("knowledge.entity.rejected")] == ["number"]
    assert summary["skipped"] >= 1


def test_epoch_with_invalid_name_skipped(onto, events):
    manifest = {"epochs": [{"ru": "20.1", "wikidata": "Q4692"}]}
    report = EpochDates(onto.statements).apply(manifest, FixtureFetch())
    assert [e["result"] for e in report.epochs] == ["invalid_name"]
    assert report.totals()["skipped"] == 1
    assert onto.entities.by_external("wikidata", "Q4692") is None
    assert [e.get("reason") for e in events.of("knowledge.entity.rejected")] == ["number"]


def test_context_event_with_invalid_name_skipped(onto, events, no_network):
    onto.thing("epoch", "Просвещение", "1680–1800")
    manifest = decide(harvested(), **{REVOLUTION: "accepted"})
    for candidate in manifest["epochs"][0]["candidates"]:
        if candidate["qid"] == REVOLUTION:
            candidate["label"] = {"ru": "your Lordship"}  # стоп-слово
    report = EpochContextImport(onto.statements).apply(manifest, FixtureFetch())
    results = {c["qid"]: c["result"] for c in report.candidates}
    assert results[REVOLUTION] == "invalid_name"
    assert onto.entities.by_external("wikidata", REVOLUTION) is None
    assert onto.entities.by_external("wikidata", PARIS) is None  # кандидат не записан наполовину
    assert EPOCH_QID  # эпоха из фикстуры та же


def test_extraction_events_registered_without_filling():
    # Описания событий живут в entity_items: путь без Filling (миграция) пишет их тоже.
    code = (
        "import sys; from philograph.knowledge import entity_items; "
        "from philograph.platform import events as ev; "
        "assert 'philograph.knowledge.filling' not in sys.modules; "
        "assert ev._CATALOG.get('knowledge.extraction.dropped') is not None; "
        "assert ev._CATALOG.get('knowledge.extraction.ambiguous') is not None"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
