"""Юнит-тесты команды дат эпох (``knowledge/epoch_dates.py``) на фикстурах Wikidata."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import func, select

from philograph.knowledge import schema as t
from philograph.knowledge.dates import FuzzyDate
from philograph.knowledge.epoch_dates import (
    PERIOD_CLASSES,
    EpochDates,
    ManifestError,
    epoch_dating,
    main,
    suggest,
    validate,
)
from philograph.knowledge.statements import Attribution
from philograph.knowledge.wikidata import fetch_entity
from tests.knowledge.wikidata_fixtures import FixtureFetch, read


@pytest.fixture
def log(events):
    return events


def named(log, name):
    return [e.fields for e in log.of(name)]


def rows(onto) -> dict[str, int]:
    with onto.entities.engine.begin() as conn:
        return {
            table: conn.scalar(select(func.count()).select_from(getattr(t, table)))
            for table in ("entities", "names", "external_ids", "statements", "attributions")
        }


def datings(onto, epoch):
    return [
        s
        for s in onto.statements.about(epoch, types=["dating"], derived=False)
        if s["direction"] == "out"
    ]


def m(*entries):
    return {"epochs": list(entries)}


def test_epoch_dating_main_fallback_and_missing():
    fetch = FixtureFetch()
    d, props = epoch_dating(fetch_entity("Q12539", fetch))
    assert (d.earliest_start, d.latest_end, d.original, props) == (
        1685,
        1815,
        "1685–1815",
        ["P580", "P582"],
    )
    d, props = epoch_dating(fetch_entity("Q900001", fetch))
    assert (d.earliest_start, d.latest_end, props) == (1543, 1687, ["P571", "P576"])
    assert epoch_dating(fetch_entity("Q900002", fetch)) is None
    d, _ = epoch_dating(fetch_entity("Q900004", fetch))
    assert d.earliest_start == 1685
    d, _ = epoch_dating(fetch_entity("Q900005", fetch))
    assert (d.earliest_start, d.latest_start, d.precision) == (-799, -700, "century")
    assert d.original == "VIII в. до н. э. – 476"


def test_apply_linked_adds_then_unchanged(onto, log):
    epoch = onto.thing("epoch", "Просвещение")
    onto.entities.add_external(epoch, "wikidata", "Q12539")
    tool = EpochDates(onto.statements)
    report = tool.apply(m(), FixtureFetch(), linked=True)
    assert [e["result"] for e in report.epochs] == ["added"]
    [s] = datings(onto, epoch)
    assert s["status"] == "sourced"
    assert s["provenance"]["extra"] == {"wikidata": "Q12539", "properties": ["P580", "P582"]}
    assert [(a["who"], a["place"]) for a in s["attributions"]] == [
        ("wikidata:Q12539", "https://www.wikidata.org/wiki/Q12539")
    ]
    assert not any(st["type"] == "influenced_by" for st in onto.statements.about(epoch))
    assert named(log, "knowledge.epoch_dates.run")[-1]["checked"] == 1
    before = rows(onto)
    again = tool.apply(m(), FixtureFetch(), linked=True)
    assert [e["result"] for e in again.epochs] == ["unchanged"]
    assert again.totals()["skipped"] == 1
    assert rows(onto) == before


def test_dry_run_writes_nothing(onto, log):
    epoch = onto.thing("epoch", "Просвещение")
    onto.entities.add_external(epoch, "wikidata", "Q12539")
    before = rows(onto)
    manifest = m({"ru": "Возрождение", "en": "Renaissance", "wikidata": "Q4692"})
    report = EpochDates(onto.statements).apply(manifest, FixtureFetch(), linked=True, dry_run=True)
    assert [e["result"] for e in report.epochs] == ["created", "added"]
    assert rows(onto) == before
    run = named(log, "knowledge.epoch_dates.run")[-1]
    assert (run["mode"], run["added"], run["created"]) == ("dry_run", 1, 1)
    assert not named(log, "knowledge.statement.created")


def test_conflict_is_reported_not_written(onto):
    epoch = onto.thing("epoch", "Научная революция", "1543–1687")
    manifest = m({"ru": "Научная революция", "wikidata": "Q125928"})
    report = EpochDates(onto.statements).apply(manifest, FixtureFetch())
    [item] = report.epochs
    assert item["result"] == "conflict"
    assert (item["existing"]["earliest_start"], item["dating"]["earliest_start"]) == (1543, 1550)
    assert len(datings(onto, epoch)) == 1
    assert report.totals()["conflicts"] == 1


def test_created_ambiguous_no_qid_failed_duplicate(onto, log):
    onto.thing("epoch", "Новое время")
    onto.thing("epoch", "Новое время")
    onto.person("Кант", wikidata="Q125928")
    fetch = FixtureFetch(failing={"Q900001"})
    manifest = m(
        {"ru": "Возрождение", "en": "Renaissance", "wikidata": "Q4692"},
        {"ru": "Новое время", "wikidata": "Q12539"},
        {"ru": "Барокко", "wikidata": None},
        {"ru": "Сбой", "wikidata": "Q900001"},
        {"ru": "Чужой QID", "wikidata": "Q125928"},
        {"ru": "Без конца", "wikidata": "Q900002"},
    )
    report = EpochDates(onto.statements).apply(manifest, fetch)
    results = [e["result"] for e in report.epochs]
    assert results == [
        "created",
        "ambiguous",
        "no_qid",
        "fetch_failed",
        "duplicate_qid",
        "no_dates",
    ]
    assert report.epochs[1]["epoch_id"] is None
    created = report.epochs[0]["epoch_id"]
    names = onto.entities.get(created)["names"]
    assert {(n["lang"], n["text"], n["kind"]) for n in names} == {
        ("ru", "Возрождение", "primary"),
        ("en", "Renaissance", "variant"),
    }
    assert onto.entities.by_external("wikidata", "Q4692") == created
    assert [e["type"] for e in named(log, "knowledge.entity.created")][-1] == "epoch"
    assert onto.entities.find("Без конца") == []  # без дат эпоха не заводится
    totals = report.totals()
    assert totals == {"checked": 6, "added": 0, "created": 1, "conflicts": 0, "skipped": 5}
    checked = named(log, "knowledge.epoch_dates.checked")
    assert [e["result"] for e in checked] == results
    for e in checked:
        assert set(e) == {"epoch_id", "qid", "result"}
    # Повторный запуск: заведённая эпоха находится по названию, новых строк нет.
    before = rows(onto)
    again = EpochDates(onto.statements).apply(manifest, FixtureFetch(failing={"Q900001"}))
    assert again.epochs[0]["result"] == "unchanged"
    assert rows(onto) == before


def test_no_qid_does_not_fetch(onto):
    onto.thing("epoch", "Барокко")
    fetch = FixtureFetch()
    report = EpochDates(onto.statements).apply(m({"ru": "Барокко", "wikidata": None}), fetch)
    assert report.epochs[0]["result"] == "no_qid"
    assert fetch.calls == []


def test_existing_preferred_dating_compared(onto):
    epoch = onto.thing("epoch", "Просвещение", "1680–1800")
    s = onto.statements.add(
        epoch,
        "dating",
        value=FuzzyDate(1685, 1685, 1815, 1815, "year", "1685–1815").to_json(),
        attributions=[Attribution("common")],
    )
    onto.statements.set_rank(s, "preferred", "test")
    report = EpochDates(onto.statements).apply(
        m({"ru": "Просвещение", "wikidata": "Q12539"}), FixtureFetch()
    )
    assert report.epochs[0]["result"] == "unchanged"


@pytest.mark.parametrize(
    "manifest",
    [
        m({"ru": "Просвещение"}, {"ru": "Просвещение"}),
        m({"ru": "Просвещение", "wikidata": "Q1/../x"}),
        m({"ru": "Просвещение", "candidates": [{"qid": "Q1"}]}),
        m({"en": "No ru"}),
        {"epochs": "x"},
    ],
)
def test_bad_manifest_rejected_before_fetch(onto, log, manifest):
    assert validate(manifest)
    fetch = FixtureFetch()
    with pytest.raises(ManifestError):
        EpochDates(onto.statements).apply(manifest, fetch)
    with pytest.raises(ManifestError):
        suggest(manifest, fetch)
    assert fetch.calls == []
    assert not [e for e in log.items if e.name.startswith("knowledge.epoch_dates.")]


def test_suggest_filters_and_merges(log):
    manifest = m(
        {"ru": "Барокко", "en": "Baroque", "wikidata": None, "comment": "проверить"},
        {"ru": "Просвещение", "wikidata": "Q12539", "comment": "подтверждено"},
    )
    out = suggest(manifest, FixtureFetch())
    baroque = out["epochs"][0]
    assert [c["qid"] for c in baroque["candidates"]] == ["Q37853"]
    assert baroque["candidates"][0] == {
        "qid": "Q37853",
        "label": "барокко",
        "description": "период в искусстве",
        "start": "1600",
        "end": "1750",
    }
    assert baroque["wikidata"] is None and baroque["comment"] == "проверить"
    assert out["epochs"][1] == manifest["epochs"][1]
    assert "candidates" not in manifest["epochs"][0]  # вход не меняется
    assert named(log, "knowledge.epoch_dates.suggested")[-1] == {"epochs": 1, "candidates": 1}
    again = suggest(out, FixtureFetch())
    assert again["epochs"][0]["candidates"] == baroque["candidates"]  # объединение по qid
    out["epochs"][0]["wikidata"] = "Q37853"
    fetch = FixtureFetch()
    third = suggest(out, fetch)
    assert fetch.calls == []
    assert third["epochs"][0]["wikidata"] == "Q37853"
    assert named(log, "knowledge.epoch_dates.suggested")[-1]["epochs"] == 0


def test_period_classes_cover_fixture_periods():
    fetch = FixtureFetch()
    assert PERIOD_CLASSES & set(fetch_entity("Q12539", fetch).items("P31"))
    assert not PERIOD_CLASSES & set(fetch_entity("Q900003", fetch).items("P31"))  # фильм


def test_cli_rejects_bad_manifest_without_db(tmp_path, capsys):
    path = tmp_path / "epochs.yaml"
    path.write_text("epochs:\n  - ru: А\n  - ru: А\n", encoding="utf-8")

    def no_service():
        raise AssertionError("база не нужна")

    def no_fetch(url):
        raise AssertionError("сеть не нужна")

    assert main(["apply", "--manifest", str(path)], fetch=no_fetch, service=no_service) == 2
    assert "повтор ru" in capsys.readouterr().err


def test_cli_suggest_keeps_header(tmp_path, capsys):
    path = tmp_path / "epochs.yaml"
    path.write_text("# Шапка\nepochs:\n  - ru: Барокко\n    wikidata: null\n", encoding="utf-8")
    assert main(["suggest", "--manifest", str(path)], fetch=FixtureFetch()) == 0
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# Шапка\n") and "Q37853" in text
    assert json.loads(capsys.readouterr().out)["epochs"][0]["candidates"][0]["qid"] == "Q37853"


def test_cli_apply_prints_report(onto, tmp_path, capsys):
    path = tmp_path / "epochs.yaml"
    path.write_text("epochs:\n  - ru: Возрождение\n    wikidata: Q4692\n", encoding="utf-8")
    code = main(
        ["apply", "--manifest", str(path), "--dry-run"],
        fetch=FixtureFetch(),
        service=lambda: EpochDates(onto.statements),
    )
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["mode"] == "dry_run" and out["totals"]["created"] == 1
    assert read("entity_Q4692.json")  # фикстура на месте


def test_repository_manifest_is_valid_and_unconfirmed():
    from pathlib import Path

    from philograph.knowledge.epoch_dates import load_manifest

    manifest = load_manifest(Path(__file__).parents[2] / "sources" / "epochs.yaml")
    assert validate(manifest) == []
    assert all(e["wikidata"] is None for e in manifest["epochs"])  # QID подтверждает человек
