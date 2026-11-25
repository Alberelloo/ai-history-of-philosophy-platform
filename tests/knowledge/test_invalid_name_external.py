"""Пути из внешних данных при отказе названия (improve-extraction-naming, дельты MODIFIED):
epochs «Даты эпох из Wikidata», epoch-context «Контекстные события из Wikidata»,
geo-timeline «Места и координаты из Wikidata».

Wikidata — фикстуры и записи теста, сеть запрещена (``no_network`` и автофикстура пакета).
Вывод — отчёт команды и база; журнал — событие пропуска пути и ``knowledge.entity.rejected``.
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, example, given, settings
from sqlalchemy import select

from philograph.knowledge import schema as t
from philograph.knowledge.epoch_context import EpochContextImport
from philograph.knowledge.epoch_dates import EpochDates
from philograph.knowledge.geo_enrich import PlaceEnrichment

from ..conftest import PROFILES
from .extraction_stand import Stand
from .strategies import LONG_LIMIT_TYPES, PERSON, expected_label, name_of, names_with_reason
from .test_epoch_context_import import PARIS, QUAKE, REVOLUTION, decide, harvested
from .test_epoch_dates import Operator, entry
from .test_geo_enrich import Fetch, person_record, place_record
from .wd_records import RecordFetch, dated, no_network, year  # noqa: F401
from .wikidata_fixtures import FixtureFetch

req = pytest.mark.req
CTX = {"request_id", "run_id", "service"}
REJECTED = "knowledge.entity.rejected"
EPOCH_CHECKED = "knowledge.epoch_dates.checked"
CONTEXT_CHECKED = "knowledge.context_import.checked"
GEO_SKIPPED = "knowledge.geo.skipped"
HEAVY = settings(
    parent=PROFILES["heavy"], suppress_health_check=[HealthCheck.function_scoped_fixture]
)
pytestmark = pytest.mark.usefixtures("no_network")


def fields(event) -> dict:
    return {k: v for k, v in event.fields.items() if k not in CTX}


def ids_by_text(onto, text: str) -> list[str]:
    with onto.statements.engine.begin() as conn:
        return sorted(set(conn.scalars(select(t.names.c.entity_id).where(t.names.c.text == text))))


# Пустая подпись во внешних данных — это отсутствие подписи, а не название: манифест эпох
# отвергает запись без ``ru`` (``ManifestError``), импорт берёт другую подпись записи. Поэтому
# класс ``empty`` в этих инвариантах не участвует; он проверен на ``Entities.create``.


def default_limit(case) -> bool:
    """Классы названий, причина которых у эпохи и места та же, что у типа стратегии."""
    (type_, _raw), reason = case
    return (
        type_ != PERSON
        and type_ not in LONG_LIMIT_TYPES
        and type_ != "source"
        and reason != "empty"
    )


def long_limit(case) -> bool:
    (type_, _raw), reason = case
    return type_ in LONG_LIMIT_TYPES and reason != "empty"


# =========================== epochs ======================================================


@req("epochs", "Даты эпох из Wikidata", scenario="Название эпохи не прошло проверку")
def test_epoch_name_rejected(onto, events, tmp_path, capsys):
    op = Operator(onto, tmp_path, capsys)
    op.manifest(entry("20.1", wikidata="Q4692"), entry("Научная революция", wikidata="Q900001"))
    fetch = RecordFetch(
        {
            "Q4692": dated("Q4692", year(1543), year(1687)),
            "Q900001": dated("Q900001", year(1543), year(1687)),
        }
    )
    code, report, _err = op.run(fetch, "apply")
    assert code == 0
    assert ids_by_text(onto, "20.1") == []
    assert onto.entities.by_external("wikidata", "Q4692") is None
    assert [(e["qid"], e["result"]) for e in events.of(EPOCH_CHECKED)] == [
        ("Q4692", "invalid_name"),
        ("Q900001", "created"),
    ]
    run = fields(events.one("knowledge.epoch_dates.run"))
    assert (run["checked"], run["created"], run["skipped"]) == (2, 1, 1)
    assert run["checked"] == run["added"] + run["created"] + run["conflicts"] + run["skipped"]
    assert [fields(e) for e in events.of(REJECTED)] == [
        {"type": "epoch", "label": "20.1", "reason": "number"}
    ]
    assert report is not None


@req(
    "epochs",
    "Даты эпох из Wikidata",
    invariant="Эпоха заводится тогда и только тогда, когда название прошло правило",
)
@HEAVY
@given(names_with_reason().filter(default_limit))
@example((("concept", "20.1"), "number"))
@example((("concept", "your Lordship"), "stopword"))
@example((("concept", "Б" * 81), "sentence"))
@example((("concept", "Эпоха Б"), None))
def test_epoch_created_iff_name_valid(onto, events, case):
    _wipe(onto)
    (_type, raw), reason = case
    raw = raw.strip()
    events.clear()
    report = EpochDates(onto.statements).apply(
        {"epochs": [{"ru": raw, "wikidata": "Q4692"}]},
        RecordFetch({"Q4692": dated("Q4692", year(1543), year(1687))}),
    )
    [result] = [e["result"] for e in report.epochs]
    epoch = onto.entities.by_external("wikidata", "Q4692")
    if reason is None:
        assert result == "created"
        assert onto.entities.label(epoch) == name_of(raw)
        events.assert_none(REJECTED)
    else:
        assert result == "invalid_name"
        assert epoch is None
        [rejected] = events.of(REJECTED)
        assert fields(rejected) == {"type": "epoch", "label": expected_label(raw), "reason": reason}
    assert [e["result"] for e in events.of(EPOCH_CHECKED)] == [result]


def _wipe(onto) -> None:
    by_name = {tb.name: tb for tb in t.metadata.sorted_tables}
    with onto.statements.engine.begin() as conn:
        for name in Stand.RESET_TABLES:
            conn.execute(by_name[name].delete())


# =========================== epoch-context ===============================================


@req(
    "epoch-context",
    "Контекстные события из Wikidata",
    scenario="Название события не прошло проверку",
)
def test_context_event_name_rejected(onto, events):
    enl = onto.thing("epoch", "Просвещение", "1680–1800")
    manifest = decide(harvested(), **{REVOLUTION: "accepted", QUAKE: "accepted"})
    for candidate in manifest["epochs"][0]["candidates"]:
        if candidate["qid"] == REVOLUTION:
            candidate["label"] = {**candidate.get("label", {}), "ru": "your Lordship"}
    statements_before = len(onto.statements.about(enl, derived=False))
    events.clear()
    report = EpochContextImport(onto.statements).apply(manifest, FixtureFetch())
    results = {c["qid"]: c["result"] for c in report.candidates}
    assert results == {REVOLUTION: "invalid_name", QUAKE: "created"}
    assert onto.entities.by_external("wikidata", REVOLUTION) is None
    assert onto.entities.by_external("wikidata", PARIS) is None
    assert ids_by_text(onto, "your Lordship") == []
    quake = onto.entities.by_external("wikidata", QUAKE)
    assert quake is not None
    # утверждения добавились только у принятого и записанного кандидата
    assert len(onto.statements.about(enl, derived=False)) == statements_before + 1
    assert {(e["qid"], e["result"]) for e in events.of(CONTEXT_CHECKED)} == {
        (REVOLUTION, "invalid_name"),
        (QUAKE, "created"),
    }
    assert [fields(e) for e in events.of(REJECTED)] == [
        {"type": "event", "label": "your Lordship", "reason": "stopword"}
    ]


@req(
    "epoch-context",
    "Контекстные события из Wikidata",
    invariant="Кандидат с непригодным названием не пишется целиком",
)
@HEAVY
@given(names_with_reason().filter(long_limit))
@example((("event", "your Lordship"), "stopword"))
@example((("event", " ".join(["Слово"] * 13)), "sentence"))
@example((("event", "Французская революция"), None))
def test_context_candidate_written_iff_name_valid(onto, events, case):
    _wipe(onto)
    (_type, raw), reason = case
    raw = raw.strip()
    onto.thing("epoch", "Просвещение", "1680–1800")
    manifest = decide(harvested(), **{REVOLUTION: "accepted"})
    manifest["epochs"][0]["candidates"] = [
        c for c in manifest["epochs"][0]["candidates"] if c["qid"] == REVOLUTION
    ]
    manifest["epochs"][0]["candidates"][0]["label"] = {"ru": raw}
    events.clear()
    report = EpochContextImport(onto.statements).apply(manifest, FixtureFetch())
    [result] = [c["result"] for c in report.candidates]
    event = onto.entities.by_external("wikidata", REVOLUTION)
    if reason is None:
        assert result == "created"
        assert onto.entities.label(event) == name_of(raw)
        events.assert_none(REJECTED)
    else:
        assert result == "invalid_name"
        assert event is None and onto.entities.by_external("wikidata", PARIS) is None
        [rejected] = events.of(REJECTED)
        assert fields(rejected) == {"type": "event", "label": expected_label(raw), "reason": reason}
    assert [e["result"] for e in events.of(CONTEXT_CHECKED)] == [result]


# =========================== geo-timeline ================================================


@req("geo-timeline", "Места и координаты из Wikidata", scenario="Подпись места не прошла проверку")
def test_place_label_rejected(onto, events):
    hume = onto.person("Дэвид Юм", "1711", "1776", wikidata="Q37160")
    kant = onto.person("Иммануил Кант", "1724", "1804", wikidata="Q9312")
    records = {
        "Q37160": person_record("Q37160", "Дэвид Юм", born=1711, items={"P19": ["Q23436"]}),
        "Q23436": place_record("Q23436", "20.1", 55.95, -3.19),
        "Q9312": person_record("Q9312", "Иммануил Кант", born=1724, items={"P19": ["Q4120832"]}),
        "Q4120832": place_record("Q4120832", "Кёнигсберг", 54.71, 20.51),
    }
    events.clear()
    summary = PlaceEnrichment(onto.statements, Fetch(records)).run()
    assert onto.entities.by_external("wikidata", "Q23436") is None
    assert ids_by_text(onto, "20.1") == []
    lived = [s for s in onto.statements.about(hume, derived=False) if s["type"] == "lived_in"]
    assert lived == []
    konigsberg = onto.entities.by_external("wikidata", "Q4120832")
    assert konigsberg is not None
    kant_lived = [s for s in onto.statements.about(kant, derived=False) if s["type"] == "lived_in"]
    assert [s["object"] for s in kant_lived] == [konigsberg]
    skipped = [(e["entity"], e["reason"]) for e in events.of(GEO_SKIPPED)]
    assert skipped == [(hume, "refused")]
    assert [fields(e) for e in events.of(REJECTED)] == [
        {"type": "place", "label": "20.1", "reason": "number"}
    ]
    enriched = events.one("knowledge.geo.enriched")
    assert (enriched["places_created"], enriched["skipped"], enriched["failed"]) == (1, 1, 0)
    assert summary["skipped"] == 1


@req(
    "geo-timeline",
    "Места и координаты из Wikidata",
    invariant="Новое место создаётся тогда и только тогда, когда подпись прошла правило",
)
@HEAVY
@given(names_with_reason().filter(default_limit))
@example((("place", "20.1"), "number"))
@example((("place", "Эдинбург"), None))
@example((("place", "В" * 81), "sentence"))
def test_place_created_iff_label_valid(onto, events, case):
    _wipe(onto)
    (_type, raw), reason = case
    raw = raw.strip()
    hume = onto.person("Дэвид Юм", "1711", "1776", wikidata="Q37160")
    records = {
        "Q37160": person_record("Q37160", "Дэвид Юм", born=1711, items={"P19": ["Q23436"]}),
        "Q23436": place_record("Q23436", raw, 55.95, -3.19),
    }
    events.clear()
    PlaceEnrichment(onto.statements, Fetch(records)).run()
    place = onto.entities.by_external("wikidata", "Q23436")
    if reason is None:
        assert place is not None and onto.entities.label(place) == name_of(raw)
        events.assert_none(REJECTED)
        assert events.where(GEO_SKIPPED, entity=hume, reason="refused") == []
    else:
        assert place is None
        [rejected] = events.of(REJECTED)
        assert fields(rejected) == {"type": "place", "label": expected_label(raw), "reason": reason}
        assert [(e["entity"], e["reason"]) for e in events.of(GEO_SKIPPED)] == [(hume, "refused")]
    events.one("knowledge.geo.enriched")
