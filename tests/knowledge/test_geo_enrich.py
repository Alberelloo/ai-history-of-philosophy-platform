"""Места и координаты из Wikidata (geo-timeline, задача 7.2).

Тесты по требованию «Места и координаты из Wikidata» дельты
``openspec/specs/geo-timeline/spec.md``. Записи Wikidata задаёт сам
тест (``wd_records.record`` и свои значения P625/P937), сеть запрещена (``no_network``).
QID — только метки синтетических записей. Оператор запускает обогащение командой
``python -m philograph.knowledge.geo_enrich`` (``main``) с записями из файла.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
from sqlalchemy import func, select

from philograph.knowledge import geo_enrich
from philograph.knowledge import schema as t
from philograph.knowledge.dates import FuzzyDate, span
from philograph.knowledge.geo_enrich import PlaceEnrichment
from philograph.knowledge.wikidata import Claim, claim_date

from .wd_records import claim, item_value, no_network, record, year  # noqa: F401

req = pytest.mark.req
GEO = "geo-timeline"
WD = "Места и координаты из Wikidata"
ENRICHED = "knowledge.geo.enriched"
SKIPPED = "knowledge.geo.skipped"
ROLLED = "knowledge.geo.rolled_back"
KANT_Q = "Q9312"
KONIGSBERG_Q = "Q4120832"
ENTITY = "https://www.wikidata.org/wiki/Special:EntityData/{}.json"


# --- записи -----------------------------------------------------------------------------


def geo(lat: float, lon: float) -> dict[str, Any]:
    return {
        "type": "globecoordinate",
        "value": {
            "latitude": lat,
            "longitude": lon,
            "altitude": None,
            "precision": 0.0001,
            "globe": "http://www.wikidata.org/entity/Q2",
        },
    }


def time_snak(prop: str, y: int) -> dict[str, Any]:
    return {
        "snaktype": "value",
        "property": prop,
        "datavalue": {
            "type": "time",
            "value": {
                "time": year(y),
                "timezone": 0,
                "before": 0,
                "after": 0,
                "precision": 9,
                "calendarmodel": "http://www.wikidata.org/entity/Q1985727",
            },
        },
    }


def person_record(qid: str, name: str, *, born=None, died=None, items=None, extra=None):
    times = {}
    if born:
        times["P569"] = (year(born), 9)
    if died:
        times["P570"] = (year(died), 9)
    data = record(qid, ru=name, classes=("Q5",), times=times, items=items or {})
    claims = data["entities"][qid]["claims"]
    for prop, values in (extra or {}).items():
        claims[prop] = values
    return data


def place_record(qid: str, name: str, lat=None, lon=None):
    data = record(qid, ru=name, classes=("Q515",))
    if lat is not None:
        data["entities"][qid]["claims"]["P625"] = [claim("P625", geo(lat, lon))]
    return data


def kant_records() -> dict[str, Any]:
    return {
        KANT_Q: person_record(
            KANT_Q,
            "Иммануил Кант",
            born=1724,
            died=1804,
            items={"P19": [KONIGSBERG_Q], "P20": [KONIGSBERG_Q]},
        ),
        KONIGSBERG_Q: place_record(KONIGSBERG_Q, "Кёнигсберг", 54.71, 20.51),
    }


class Fetch:
    """Записи теста по адресу ``Special:EntityData``; QID из ``failing`` и отсутствующие —
    сбой загрузки. Все адреса — в ``calls``."""

    def __init__(self, records: dict[str, Any], failing=()) -> None:
        self.records = records
        self.failing = set(failing)
        self.calls: list[str] = []

    def __call__(self, url: str) -> dict[str, Any]:
        from philograph.knowledge.wikidata import WikidataError

        self.calls.append(url)
        m = re.fullmatch(r"https://www\.wikidata\.org/wiki/Special:EntityData/(Q\d+)\.json", url)
        assert m, f"неожиданный адрес {url}"
        if m.group(1) in self.failing or m.group(1) not in self.records:
            raise WikidataError("сбой загрузки (тест)")
        return self.records[m.group(1)]


# --- состояние базы ----------------------------------------------------------------------


def statements_count(onto) -> int:
    with onto.statements.engine.begin() as conn:
        return conn.scalar(select(func.count()).select_from(t.statements))


def entities_by_type(onto) -> dict[str, int]:
    with onto.statements.engine.begin() as conn:
        rows = conn.execute(
            select(t.entities.c.type, func.count()).group_by(t.entities.c.type)
        ).all()
    return dict(rows)


def rows_of(onto, type_: str) -> list[dict[str, Any]]:
    with onto.statements.engine.begin() as conn:
        ids = conn.scalars(select(t.statements.c.id).where(t.statements.c.type == type_)).all()
    return [onto.statements.get(i) for i in ids]


def place_by_qid(onto, qid: str) -> str | None:
    return onto.entities.by_external("wikidata", qid)


def cli(onto, tmp_path, records: dict[str, Any], *args: str, capsys) -> dict[str, Any]:
    """Команда оператора с записями из файла (без сети); итог — JSON на stdout."""
    path = tmp_path / "records.json"
    path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    code = geo_enrich.main(
        ["run", "--from-file", str(path), *args],
        service=lambda fetch: PlaceEnrichment(onto.statements, fetch),
    )
    assert code == 0
    out = capsys.readouterr().out
    return json.loads(out)


def date_json(y: int) -> dict:
    """Формат нечёткой даты, общий для импортов Wikidata (``wikidata.claim_date``)."""
    return claim_date(Claim({"time": year(y), "precision": 9}, "normal", {})).to_json()


# --- сценарии ----------------------------------------------------------------------------


@req(GEO, WD, scenario="Кант из Wikidata")
def test_kant_from_wikidata(onto, events, tmp_path, capsys, no_network):
    kant = onto.person("Иммануил Кант", "1724", "1804", wikidata=KANT_Q)
    summary = cli(onto, tmp_path, kant_records(), capsys=capsys)

    k = place_by_qid(onto, KONIGSBERG_Q)
    assert k is not None and onto.entities.get(k)["type"] == "place"
    lived = [s for s in rows_of(onto, "lived_in") if s["subject"] == kant]
    assert len(lived) == 2
    by_role = {s["qualifiers"]["place_role"]: s for s in lived}
    assert set(by_role) == {"birth", "death"}
    assert all(s["object"] == k for s in lived)
    assert by_role["birth"]["qualifiers"]["time"] == date_json(1724)
    assert span(by_role["birth"]["qualifiers"]["time"]) == (1724, 1724)
    assert by_role["death"]["qualifiers"]["time"] == date_json(1804)
    assert span(by_role["death"]["qualifiers"]["time"]) == (1804, 1804)
    [c] = rows_of(onto, "coordinates")
    assert c["subject"] == k and c["value"] == {"lat": 54.71, "lon": 20.51}
    for s, qid in ((by_role["birth"], KANT_Q), (by_role["death"], KANT_Q), (c, KONIGSBERG_Q)):
        [a] = s["attributions"]
        assert a["who_kind"] == "source"
        assert a["who"] == f"wikidata:{qid}"
        assert a["place"] == f"https://www.wikidata.org/wiki/{qid}"
        assert s["status"] == "sourced"
        assert s["provenance"]["method"] == "imported"
        assert s["provenance"]["run_id"] == summary["run_id"]

    e = events.one(ENRICHED)
    expected = {
        "coordinates": 1,
        "placements": 2,
        "places_created": 1,
        "skipped": 0,
        "failed": 0,
        "dry_run": False,
    }
    for key, value in expected.items():
        assert e.get(key) == value, key
        assert summary[key] == value, key
    assert e.get("run_id") == summary["run_id"]
    events.assert_none(SKIPPED)


@req(GEO, WD, scenario="Повторный запуск")
def test_rerun_adds_nothing(onto, events, tmp_path, capsys, no_network):
    onto.person("Иммануил Кант", "1724", "1804", wikidata=KANT_Q)
    cli(onto, tmp_path, kant_records(), capsys=capsys)
    before, types_before = statements_count(onto), entities_by_type(onto)
    events.clear()
    summary = cli(onto, tmp_path, kant_records(), capsys=capsys)
    assert statements_count(onto) == before
    assert entities_by_type(onto) == types_before
    e = events.one(ENRICHED)
    for key in ("coordinates", "placements", "places_created"):
        assert e.get(key) == 0, key
        assert summary[key] == 0
    assert e.get("dry_run") is False


@req(GEO, WD, scenario="Влияние и чужие свойства не импортируются")
def test_influence_and_foreign_properties_not_imported(onto, events, tmp_path, capsys, no_network):
    kant = onto.person("Иммануил Кант", "1724", "1804", wikidata=KANT_Q)
    hume = onto.person("Дэвид Юм", "1711", "1776", wikidata="Q37160")
    records = kant_records()
    records[KANT_Q] = person_record(
        KANT_Q,
        "Иммануил Кант",
        born=1724,
        died=1804,
        items={"P19": [KONIGSBERG_Q], "P737": ["Q37160"], "P27": ["Q27306"]},
    )
    records["Q37160"] = person_record("Q37160", "Дэвид Юм", born=1711, died=1776)
    records["Q27306"] = place_record("Q27306", "Пруссия", 52.5, 13.4)
    cli(onto, tmp_path, records, capsys=capsys)
    types = {s["type"] for s in rows_of(onto, "influenced_by") + rows_of(onto, "citizenship")}
    assert types == set()
    with onto.statements.engine.begin() as conn:
        between = conn.execute(
            select(t.statements.c.type).where(
                t.statements.c.subject.in_([kant, hume]), t.statements.c.object.in_([kant, hume])
            )
        ).all()
    assert between == []
    assert place_by_qid(onto, "Q27306") is None  # гражданство не создало места
    assert [e for e in events.of(SKIPPED) if e.get("property") in ("P737", "P27")] == []
    assert events.one(ENRICHED).get("placements") == 1


@req(GEO, WD, scenario="Сухой прогон")
def test_dry_run_writes_nothing(onto, events, tmp_path, capsys, no_network):
    onto.person("Иммануил Кант", "1724", "1804", wikidata=KANT_Q)
    before, types_before = statements_count(onto), entities_by_type(onto)
    assert "place" not in types_before
    summary = cli(onto, tmp_path, kant_records(), "--dry-run", capsys=capsys)
    assert statements_count(onto) == before
    assert entities_by_type(onto) == types_before
    e = events.one(ENRICHED)
    for key, value in {
        "dry_run": True,
        "coordinates": 1,
        "placements": 2,
        "places_created": 1,
    }.items():
        assert e.get(key) == value, key
        assert summary[key] == value
    events.assert_none(SKIPPED)


@req(GEO, WD, scenario="Пропуски")
def test_skips_reasons_and_counters(onto, events, no_network):
    descartes = onto.person("Рене Декарт", "1596", "1650", wikidata="Q9191")
    hume = onto.person("Дэвид Юм", "1711", "1776", wikidata="Q37160")
    bad = person_record("Q9191", "Рене Декарт", born=1596, died=1650, items={"P20": ["Q1754"]})
    bad["entities"]["Q9191"]["claims"]["P19"] = [
        claim(
            "P19", {"type": "wikibase-entityid", "value": {"entity-type": "item", "id": "<script>"}}
        )
    ]
    records = {
        "Q9191": bad,
        "Q37160": person_record(
            "Q37160", "Дэвид Юм", born=1711, died=1776, items={"P19": ["Q23436"]}
        ),
        "Q23436": place_record("Q23436", "Эдинбург", 95, 0),
        # Q1754 (Стокгольм) — запись не загружается.
    }
    fetch = Fetch(records, failing={"Q1754"})
    summary = PlaceEnrichment(onto.statements, fetch).run()
    skipped = [(e.get("entity"), e.get("reason")) for e in events.of(SKIPPED)]
    assert (descartes, "bad_qid") in skipped
    assert (hume, "refused") in skipped
    fetch_failed = events.where(SKIPPED, reason="fetch_failed")
    assert len(fetch_failed) == 1
    assert fetch_failed[0].get("entity") == descartes
    assert fetch_failed[0].get("property") == "P20"
    assert sorted(skipped) == sorted(
        [(descartes, "bad_qid"), (hume, "refused"), (descartes, "fetch_failed")]
    )
    e = events.one(ENRICHED)
    assert (e.get("skipped"), e.get("failed")) == (2, 1)
    assert (summary["skipped"], summary["failed"]) == (2, 1)
    # Запуск дошёл до конца: Юм обработан, хотя у Декарта были пропуски.
    assert e.get("entities") == 2
    assert not any("<script>" in c for c in fetch.calls)
    assert rows_of(onto, "coordinates") == []


@req(GEO, WD, scenario="Откат")
def test_rollback_keeps_verified_and_places(onto, events, no_network):
    onto.person("Иммануил Кант", "1724", "1804", wikidata=KANT_Q)
    enrichment = PlaceEnrichment(onto.statements, Fetch(kant_records()))
    summary = enrichment.run()
    written = [
        s
        for s in rows_of(onto, "lived_in") + rows_of(onto, "coordinates")
        if s["provenance"].get("run_id") == summary["run_id"]
    ]
    assert len(written) == 3 and summary["places_created"] == 1
    checked = written[0]["id"]
    onto.statements.confirm(checked, "operator")
    events.clear()
    result = enrichment.rollback(summary["run_id"])
    left = rows_of(onto, "lived_in") + rows_of(onto, "coordinates")
    assert [s["id"] for s in left] == [checked]
    assert place_by_qid(onto, KONIGSBERG_Q) is not None
    e = events.one(ROLLED)
    assert (e.get("run_id"), e.get("statements"), e.get("places_kept")) == (summary["run_id"], 2, 1)
    assert (result["statements"], result["places_kept"]) == (2, 1)


@req(GEO, WD, scenario="Не из пути читателя")
def test_not_from_reader_path(svc, events, monkeypatch, no_network):
    from philograph.knowledge import wikidata

    calls: list[str] = []
    fetch = Fetch(kant_records())
    PlaceEnrichment(svc.onto.statements, fetch)  # внедрён, но не запускается читателем
    for name in ("fetch_entity", "http_fetch"):
        original = getattr(wikidata, name)

        def spy(*a, _name=name, _orig=original, **kw):
            calls.append(_name)
            return _orig(*a, **kw)

        monkeypatch.setattr(wikidata, name, spy)
        monkeypatch.setattr(geo_enrich, name, spy)
    monkeypatch.setattr(PlaceEnrichment, "run", lambda *a, **k: calls.append("run"))
    w = svc.world
    kant = w.person("Иммануил Кант", "1724", "1804")
    k = svc.onto.entities.create(
        "place", [("ru", "Кёнигсберг", "primary")], external={"wikidata": KONIGSBERG_Q}
    )
    w.relate(kant, "lived_in", k, qualifiers={"place_role": "birth"})
    for path in ("/v1/map/places", "/v1/map", "/v1/map/places"):
        response, _rid = svc.get(path)
        assert response.status_code == 200, response.text
    assert len(events.of("knowledge.geo.built")) == 2
    assert fetch.calls == []
    assert calls == []
    assert svc.llm_calls == []


# --- нормативные ------------------------------------------------------------------------


@req(GEO, WD, invariant="новых персон и событий не создаётся")
def test_no_new_people_or_events(onto, events, no_network):
    onto.person("Иммануил Кант", "1724", "1804", wikidata=KANT_Q)
    event = onto.entities.create(
        "event", [("ru", "Событие", "primary")], external={"wikidata": "Q100"}
    )
    records = kant_records()
    # Значения, указывающие на персону и событие, которых нет в базе, — не повод их создавать.
    records[KANT_Q]["entities"][KANT_Q]["claims"]["P737"] = [claim("P737", item_value("Q37160"))]
    records["Q37160"] = person_record(
        "Q37160", "Дэвид Юм", born=1711, died=1776, items={"P19": ["Q23436"]}
    )
    records["Q23436"] = place_record("Q23436", "Эдинбург", 55.95, -3.19)
    records["Q100"] = record(
        "Q100", ru="Событие", classes=("Q1190554",), items={"P276": ["Q90"], "P710": ["Q37160"]}
    )
    records["Q90"] = place_record("Q90", "Париж", 48.86, 2.35)
    before = entities_by_type(onto)
    summary = PlaceEnrichment(onto.statements, Fetch(records)).run()
    after = entities_by_type(onto)
    assert after["person"] == before["person"]
    assert after.get("event", 0) == before.get("event", 0)
    assert after["place"] == 2  # Кёнигсберг и Париж; Эдинбург — только через Юма, которого нет
    assert onto.entities.by_external("wikidata", "Q37160") is None
    [h] = rows_of(onto, "happened_in")
    assert (h["subject"], h["object"]) == (event, place_by_qid(onto, "Q90"))
    assert events.one(ENRICHED).get("places_created") == summary["places_created"] == 2


PROPS_OUTSIDE = ["P737", "P27", "P106", "P39", "P551", "P1066", "P802", "P69", "P108"]


@req(GEO, WD, invariant="только свойства таблицы")
def test_only_table_properties(onto, events, no_network):
    kant = onto.person("Иммануил Кант", "1724", "1804", wikidata=KANT_Q)
    records = kant_records()
    items = {p: ["Q777"] for p in PROPS_OUTSIDE}
    rec = person_record(KANT_Q, "Иммануил Кант", born=1724, died=1804, items=items)
    records[KANT_Q] = rec
    records["Q777"] = place_record("Q777", "Чужое место", 1, 1)
    fetch = Fetch(records)
    summary = PlaceEnrichment(onto.statements, fetch).run()
    with onto.statements.engine.begin() as conn:
        types = set(conn.scalars(select(t.statements.c.type).where(t.statements.c.subject == kant)))
    assert types == {"lifespan"}
    assert ENTITY.format("Q777") not in fetch.calls
    assert place_by_qid(onto, "Q777") is None
    assert (summary["placements"], summary["coordinates"]) == (0, 0)
    assert events.of(SKIPPED) == []


@req(GEO, WD, invariant="P937 — место деятельности со временем P580–P582")
def test_activity_from_p937(onto, events, no_network):
    descartes = onto.person("Рене Декарт", "1596", "1650", wikidata="Q9191")
    rec = person_record("Q9191", "Рене Декарт", born=1596, died=1650)
    work = claim("P937", item_value("Q727"))
    work["qualifiers"] = {"P580": [time_snak("P580", 1628)], "P582": [time_snak("P582", 1649)]}
    rec["entities"]["Q9191"]["claims"]["P937"] = [work]
    records = {"Q9191": rec, "Q727": place_record("Q727", "Амстердам", 52.37, 4.89)}
    PlaceEnrichment(onto.statements, Fetch(records)).run()
    [s] = [s for s in rows_of(onto, "lived_in") if s["subject"] == descartes]
    assert s["qualifiers"]["place_role"] == "activity"
    assert span(s["qualifiers"]["time"]) == (1628, 1649)
    FuzzyDate.from_json(s["qualifiers"]["time"])
    assert events.one(ENRICHED).get("placements") == 1


BAD_EXTERNAL = ["q9312", "Q9312x", "Q", "P19", " Q9312", "Q-1", "../Q1", "Q12/../Q1", "<script>"]


@req(GEO, WD, invariant="QID только ^Q\\d+$")
@pytest.mark.parametrize("external", BAD_EXTERNAL)
def test_bad_external_id_never_fetched(onto, events, no_network, external):
    onto.person("Иммануил Кант", "1724", "1804", wikidata=external)
    fetch = Fetch(kant_records())
    summary = PlaceEnrichment(onto.statements, fetch).run()
    assert fetch.calls == []
    assert summary["entities"] == 0
    assert rows_of(onto, "lived_in") == []
    assert events.one(ENRICHED).get("entities") == 0


BAD_VALUE_IDS = [
    "<script>",
    "q4120832",
    "Q4120832/../Q1",
    "https://evil.example/Q1",
    "Q",
    "Q1 ",
    "P19",
]


@req(
    GEO,
    WD,
    invariant="QID в значении не по ^Q\\d+$ не запрашивается и не пишется",
)
@pytest.mark.parametrize("bad", BAD_VALUE_IDS)
def test_bad_value_id_not_fetched_or_written(onto, events, no_network, bad):
    kant = onto.person("Иммануил Кант", "1724", "1804", wikidata=KANT_Q)
    rec = person_record(KANT_Q, "Иммануил Кант", born=1724, died=1804)
    rec["entities"][KANT_Q]["claims"]["P19"] = [
        claim("P19", {"type": "wikibase-entityid", "value": {"entity-type": "item", "id": bad}})
    ]
    fetch = Fetch({KANT_Q: rec})
    PlaceEnrichment(onto.statements, fetch).run()
    assert fetch.calls == [ENTITY.format(KANT_Q)]
    assert rows_of(onto, "lived_in") == []
    assert entities_by_type(onto).get("place", 0) == 0
    [skip] = events.of(SKIPPED)
    assert (skip.get("entity"), skip.get("property"), skip.get("reason")) == (
        kant,
        "P19",
        "bad_qid",
    )


@req(GEO, WD, invariant="у каждой записи атрибуция с page_url и run_id")
def test_every_record_attributed(onto, events, no_network):
    onto.person("Иммануил Кант", "1724", "1804", wikidata=KANT_Q)
    descartes = onto.person("Рене Декарт", "1596", "1650", wikidata="Q9191")
    event = onto.entities.create(
        "event", [("ru", "Событие", "primary")], external={"wikidata": "Q100"}
    )
    records = kant_records()
    rec = person_record("Q9191", "Рене Декарт", born=1596, died=1650, items={"P19": ["Q1"]})
    work = claim("P937", item_value("Q727"))
    rec["entities"]["Q9191"]["claims"]["P937"] = [work]
    records.update(
        {
            "Q9191": rec,
            "Q1": place_record("Q1", "Ла-Э", 47.0, 0.7),
            "Q727": place_record("Q727", "Амстердам", 52.37, 4.89),
            "Q100": record("Q100", ru="Событие", classes=("Q1190554",), items={"P276": ["Q727"]}),
        }
    )
    summary = PlaceEnrichment(onto.statements, Fetch(records)).run()
    written = [s for typ in ("lived_in", "happened_in", "coordinates") for s in rows_of(onto, typ)]
    assert len(written) == summary["placements"] + summary["coordinates"] == 5 + 3
    for s in written:
        [a] = s["attributions"]
        qid = a["who"].removeprefix("wikidata:")
        assert re.fullmatch(r"Q\d+", qid), a
        assert a["who_kind"] == "source"
        assert a["place"] == f"https://www.wikidata.org/wiki/{qid}"
        assert s["status"] == "sourced"
        assert s["provenance"]["method"] == "imported"
        assert s["provenance"]["run_id"] == summary["run_id"]
        assert re.fullmatch(r"geo_[0-9a-f]{12}", summary["run_id"])
    assert {s["subject"] for s in rows_of(onto, "happened_in")} == {event}
    assert descartes in {s["subject"] for s in rows_of(onto, "lived_in")}
    events.assert_none(SKIPPED)


FIELDS = {
    ENRICHED: {
        "run_id",
        "entities",
        "coordinates",
        "placements",
        "places_created",
        "skipped",
        "failed",
        "dry_run",
    },
    SKIPPED: {"entity", "property", "reason"},
    ROLLED: {"run_id", "statements", "places_kept"},
}


@req(GEO, WD, invariant="поля трёх событий — только id, коды, числа")
def test_event_fields_only_ids_codes_numbers(onto, events, no_network):
    kant = onto.person("Иммануил Кант", "1724", "1804", wikidata=KANT_Q)
    records = kant_records()
    records[KANT_Q]["entities"][KANT_Q]["claims"]["P20"] = [
        claim(
            "P20",
            {
                "type": "wikibase-entityid",
                "value": {"entity-type": "item", "id": "<b>Иммануил</b>"},
            },
        )
    ]
    enrichment = PlaceEnrichment(onto.statements, Fetch(records))
    summary = enrichment.run()
    enrichment.rollback(summary["run_id"])
    names = ("Кант", "Кёнигсберг", "Иммануил", "<b>", "wikidata.org")
    seen = set()
    for event in events.items:
        if event.name not in FIELDS:
            continue
        seen.add(event.name)
        fields = {k: v for k, v in event.fields.items() if k not in ("request_id",)}
        assert set(fields) == FIELDS[event.name], (event.name, fields)
        for key, value in fields.items():
            assert isinstance(value, (int, bool, str)), (key, value)
            if isinstance(value, str):
                assert not any(n in value for n in names), (key, value)
                assert re.fullmatch(r"[A-Za-z0-9_]+", value), (key, value)
    assert seen == set(FIELDS)
    assert events.one(SKIPPED).get("entity") == kant


@req(GEO, WD, invariant="запуск с записями из файла работает без сети")
def test_file_run_without_network(onto, events, tmp_path, capsys, no_network):
    onto.person("Иммануил Кант", "1724", "1804", wikidata=KANT_Q)
    # Ключи файла — адреса EntityData, как у Special:EntityData.
    records = {ENTITY.format(q): r for q, r in kant_records().items()}
    summary = cli(onto, tmp_path, records, capsys=capsys)
    assert (summary["placements"], summary["coordinates"], summary["failed"]) == (2, 1, 0)
    assert events.one(ENRICHED).get("failed") == 0


@req(
    GEO,
    WD,
    invariant="место создаётся с внешним id, существующее не дублируется",
)
def test_existing_place_reused(onto, events, no_network):
    onto.person("Иммануил Кант", "1724", "1804", wikidata=KANT_Q)
    existing = onto.entities.create(
        "place", [("ru", "Кёнигсберг", "primary")], external={"wikidata": KONIGSBERG_Q}
    )
    summary = PlaceEnrichment(onto.statements, Fetch(kant_records())).run()
    assert entities_by_type(onto)["place"] == 1
    assert {s["object"] for s in rows_of(onto, "lived_in")} == {existing}
    e = events.one(ENRICHED)
    assert (e.get("places_created"), e.get("placements"), e.get("coordinates")) == (0, 2, 1)
    assert summary["places_created"] == 0


# --- отказ координат при обогащении (ревью: «при каждом отказе — refused») -----------------

REFUSED = "knowledge.statement.refused"
HUME_Q = "Q37160"
EDINBURGH_Q = "Q23436"


def hume_records(lat, lon) -> dict[str, Any]:
    return {
        HUME_Q: person_record(
            HUME_Q, "Дэвид Юм", born=1711, died=1776, items={"P19": [EDINBURGH_Q]}
        ),
        EDINBURGH_Q: place_record(EDINBURGH_Q, "Эдинбург", lat, lon),
    }


@req(GEO, "Координаты места", invariant="при каждом отказе — knowledge.statement.refused")
@pytest.mark.parametrize(
    ("lat", "lon", "code"),
    [
        (95, 0, "geo_out_of_range"),
        (10**400, 0, "geo_not_number"),
        (0, -(10**400), "geo_not_number"),
    ],
    ids=["95,0", "lat=10**400", "lon=-10**400"],
)
@pytest.mark.parametrize("dry_run", [False, True], ids=["run", "dry-run"])
def test_enrich_refusal_writes_one_event(onto, events, no_network, lat, lon, code, dry_run):
    onto.person("Дэвид Юм", "1711", "1776", wikidata=HUME_Q)
    summary = PlaceEnrichment(onto.statements, Fetch(hume_records(lat, lon))).run(dry_run=dry_run)
    refused = events.of(REFUSED)
    assert len(refused) == 1, refused
    assert (refused[0].get("type"), refused[0].get("code")) == ("coordinates", code)
    assert isinstance(refused[0].get("reason"), str) and refused[0].get("reason")
    assert len(events.where(SKIPPED, reason="refused")) == 1
    e = events.one(ENRICHED)
    assert e.get("dry_run") is dry_run
    assert e.get("coordinates") == 0 and summary["coordinates"] == 0
    assert rows_of(onto, "coordinates") == []


@req(GEO, WD, scenario="Откат")
def test_rollback_leaves_other_run(onto, events, no_network):
    onto.person("Иммануил Кант", "1724", "1804", wikidata=KANT_Q)
    first = PlaceEnrichment(onto.statements, Fetch(kant_records())).run()
    onto.person("Дэвид Юм", "1711", "1776", wikidata=HUME_Q)
    second_enrichment = PlaceEnrichment(
        onto.statements, Fetch({**kant_records(), **hume_records(55.95, -3.19)})
    )
    second = second_enrichment.run()
    assert first["run_id"] != second["run_id"]

    def by_run(run_id):
        return sorted(
            s["id"]
            for s in rows_of(onto, "lived_in") + rows_of(onto, "coordinates")
            if s["provenance"].get("run_id") == run_id
        )

    first_ids, second_ids = by_run(first["run_id"]), by_run(second["run_id"])
    assert len(first_ids) == 3 and len(second_ids) == 2
    events.clear()
    result = second_enrichment.rollback(first["run_id"])
    assert by_run(first["run_id"]) == []
    assert by_run(second["run_id"]) == second_ids
    e = events.one(ROLLED)
    assert (e.get("run_id"), e.get("statements")) == (first["run_id"], 3)
    assert result["statements"] == 3
