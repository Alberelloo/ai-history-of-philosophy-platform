"""epoch-context: «Контекстные события из Wikidata» (изменение add-epoch-context, задача 6.3).

Сеть запрещена (``no_network``): Wikidata — файлы ``tests/knowledge/fixtures/wikidata``
(``FixtureFetch``). Эпоха «Просвещение» — ``Q910001``: P793 — революция ``Q910011`` (P585 1789,
P31 «революция», P276 «Париж» ``Q910021``), событие ``Q910012`` (P585 1755, класс не из таблицы),
событие ``Q910013`` без даты.
"""

from __future__ import annotations

import copy
import json

import pytest
import yaml
from sqlalchemy import func, select

from philograph.knowledge import schema
from philograph.knowledge.epoch_context import EpochContextImport, harvest, main

from .wd_records import no_network  # noqa: F401
from .wikidata_fixtures import FixtureFetch, read

req = pytest.mark.req
EC = "epoch-context"
WD = "Контекстные события из Wikidata"
EPOCH_QID = "Q910001"
REVOLUTION, QUAKE, UNDATED, PARIS = "Q910011", "Q910012", "Q910013", "Q910021"
EPOCHS_YAML = {"epochs": [{"ru": "Просвещение", "wikidata": EPOCH_QID}]}


def table_rows(onto) -> dict[str, int]:
    """Число строк во всех таблицах онтологии."""
    with onto.registry.engine.begin() as conn:
        return {
            table.name: conn.scalar(select(func.count()).select_from(table))
            for table in schema.metadata.sorted_tables
        }


@pytest.fixture
def enl(onto):
    return onto.thing("epoch", "Просвещение", "1680–1800")


@pytest.fixture
def importer(onto, enl):
    return EpochContextImport(onto.statements)


def harvested(fetch=None) -> dict:
    return harvest(EPOCHS_YAML, {"epochs": []}, fetch or FixtureFetch())


def decide(manifest: dict, **decisions: str) -> dict:
    """Копия манифеста с решениями человека: QID → решение."""
    result = copy.deepcopy(manifest)
    for candidate in result["epochs"][0]["candidates"]:
        if candidate["qid"] in decisions:
            candidate["decision"] = decisions[candidate["qid"]]
    return result


def out_rows(onto, entity):
    return [s for s in onto.statements.about(entity, derived=False) if s["direction"] == "out"]


def all_statement_types(onto) -> list[str]:
    with onto.registry.engine.begin() as conn:
        return list(conn.scalars(select(schema.statements.c.type)))


# --- сценарии --------------------------------------------------------------------------


@req(EC, WD, scenario="Кандидаты в манифест")
def test_harvest_candidates(onto, enl, events, no_network):
    before = table_rows(onto)
    fetch = FixtureFetch()
    manifest = harvested(fetch)
    [entry] = manifest["epochs"]
    assert entry["qid"] == EPOCH_QID and entry["epoch"] == "Просвещение"
    candidates = {c["qid"]: c for c in entry["candidates"]}
    assert set(candidates) == {REVOLUTION, QUAKE}  # события без даты нет
    revolution, quake = candidates[REVOLUTION], candidates[QUAKE]
    assert revolution["decision"] == "pending" and quake["decision"] == "pending"
    assert revolution["kind"] == "political"
    assert revolution["place"]["qid"] == PARIS and revolution["place"]["label"]["ru"] == "Париж"
    assert quake["kind"] is None
    assert table_rows(onto) == before
    [done] = events.of("knowledge.context_import.harvested")
    assert (done["epochs"], done["candidates"]) == (1, 2)
    assert all("wikidata.org" in url for url in fetch.calls)


@req(EC, WD, scenario="Принятый кандидат")
def test_accepted_candidate(onto, importer, enl, events, no_network):
    manifest = decide(harvested(), **{REVOLUTION: "accepted"})
    before = table_rows(onto)
    events.clear()
    report = importer.apply(manifest, FixtureFetch())
    assert report.totals() == {"created": 1, "statements": 4, "places_created": 1, "skipped": 1}
    # ``skipped=1`` — второй кандидат манифеста остался ``pending``; сценарий без него ниже.
    event = onto.entities.by_external("wikidata", REVOLUTION)
    paris = onto.entities.by_external("wikidata", PARIS)
    assert event and paris
    assert onto.entities.label(event) == "Французская революция"
    assert onto.entities.get(event)["type"] == "event"
    assert onto.entities.label(paris) == "Париж" and onto.entities.get(paris)["type"] == "place"
    rows = {s["type"]: s for s in out_rows(onto, event)}
    assert sorted(rows) == ["belongs_to_epoch", "dating", "event_kind", "happened_in"]
    assert rows["dating"]["value"]["earliest_start"] == 1789
    assert rows["event_kind"]["value"] == "political"
    assert rows["belongs_to_epoch"]["object"] == enl
    assert rows["belongs_to_epoch"]["qualifiers"] == {"membership_basis": "historians"}
    assert rows["happened_in"]["object"] == paris
    for row in rows.values():
        assert row["status"] == "sourced", row
        [attribution] = row["attributions"]
        assert attribution["who"] == f"wikidata:{REVOLUTION}"
        assert attribution["place"] == f"https://www.wikidata.org/wiki/{REVOLUTION}"  # ссылка
        assert row["provenance"]["method"] == "imported", row["provenance"]
    assert "stimulated" not in all_statement_types(onto)
    assert table_rows(onto)["entities"] == before["entities"] + 2
    assert events.where("knowledge.context_import.checked", qid=REVOLUTION, result="created")
    run = events.one("knowledge.context_import.run")
    assert run["mode"] == "apply"
    assert (run["created"], run["statements"], run["places_created"]) == (1, 4, 1)


@req(EC, WD, scenario="Принятый кандидат")
def test_accepted_only_candidate_skipped_zero(onto, importer, events, no_network):
    """Тот же сценарий, в манифесте только принятый кандидат: ``skipped=0``."""
    manifest = decide(harvested(), **{REVOLUTION: "accepted"})
    manifest["epochs"][0]["candidates"] = [
        c for c in manifest["epochs"][0]["candidates"] if c["qid"] == REVOLUTION
    ]
    events.clear()
    importer.apply(manifest, FixtureFetch())
    run = events.one("knowledge.context_import.run")
    assert (run["mode"], run["created"], run["statements"]) == ("apply", 1, 4)
    assert (run["places_created"], run["skipped"]) == (1, 0)
    [checked] = events.of("knowledge.context_import.checked")
    assert (checked["qid"], checked["result"]) == (REVOLUTION, "created")


@req(EC, WD, scenario="Ожидающий и отклонённый")
def test_pending_and_rejected(onto, importer, events, no_network):
    manifest = decide(harvested(), **{REVOLUTION: "pending", QUAKE: "rejected"})
    before = table_rows(onto)
    events.clear()
    importer.apply(manifest, FixtureFetch())
    assert table_rows(onto) == before
    assert onto.entities.by_external("wikidata", REVOLUTION) is None
    results = {e["qid"]: e["result"] for e in events.of("knowledge.context_import.checked")}
    assert results == {REVOLUTION: "pending", QUAKE: "rejected"}
    run = events.one("knowledge.context_import.run")
    assert run["skipped"] == 2 and run["created"] == 0 and run["statements"] == 0


@req(EC, WD, scenario="Повторный запуск и проверка")
def test_repeat_apply_and_dry_run(onto, importer, events, no_network):
    manifest = decide(harvested(), **{REVOLUTION: "accepted"})
    importer.apply(manifest, FixtureFetch())
    before = table_rows(onto)
    events.clear()
    importer.apply(manifest, FixtureFetch())
    assert table_rows(onto) == before
    assert events.where("knowledge.context_import.checked", qid=REVOLUTION, result="exists")
    run = events.one("knowledge.context_import.run")
    assert (run["created"], run["statements"], run["places_created"]) == (0, 0, 0)
    # --dry-run с новым принятым кандидатом (событие 1755).
    events.clear()
    fresh = decide(manifest, **{QUAKE: "accepted"})
    importer.apply(fresh, FixtureFetch(), dry_run=True)
    assert table_rows(onto) == before
    assert onto.entities.by_external("wikidata", QUAKE) is None
    run = events.one("knowledge.context_import.run")
    assert run["mode"] == "dry_run" and run["created"] == 1
    assert events.where("knowledge.context_import.checked", qid=QUAKE, result="created")


@req(EC, WD, scenario="Повторный подбор не сбрасывает решения")
def test_repeat_harvest_keeps_decisions(onto, enl, events, no_network):
    manifest = decide(harvested(), **{REVOLUTION: "accepted", QUAKE: "rejected"})
    events.clear()
    again = harvest(EPOCHS_YAML, manifest, FixtureFetch())
    candidates = again["epochs"][0]["candidates"]
    assert sorted(c["qid"] for c in candidates) == [REVOLUTION, QUAKE]  # не задвоены
    decisions = {c["qid"]: c["decision"] for c in candidates}
    assert decisions == {REVOLUTION: "accepted", QUAKE: "rejected"}
    assert len(again["epochs"]) == 1
    assert events.one("knowledge.context_import.harvested")["candidates"] == 2


# --- инварианты ------------------------------------------------------------------------


@req(EC, WD, invariant="повторный harvest не меняет полей, заполненных человеком")
def test_repeat_harvest_keeps_human_fields(onto, enl, events, no_network):
    manifest = decide(harvested(), **{REVOLUTION: "accepted"})
    revolution = manifest["epochs"][0]["candidates"][0]
    assert revolution["qid"] == REVOLUTION
    revolution["kind"] = "social"
    revolution["label"] = {"ru": "Великая французская революция"}
    revolution["place"] = None
    revolution["note"] = "проверил Lead"
    snapshot = copy.deepcopy(revolution)
    again = harvest(EPOCHS_YAML, manifest, FixtureFetch())
    kept = next(c for c in again["epochs"][0]["candidates"] if c["qid"] == REVOLUTION)
    assert kept == snapshot
    assert events.of("knowledge.context_import.harvested")


@req(
    EC,
    WD,
    invariant="из Wikidata никогда не пишутся «стимулировало», механизм и связи влияния",
)
def test_never_writes_stimulated_mechanism_influence(onto, importer, events, no_network):
    record = read(f"entity_{REVOLUTION}.json")
    claims = record["entities"][REVOLUTION]["claims"]
    item = copy.deepcopy(claims["P276"][0])
    for prop in ("P737", "P1542", "P828"):  # «под влиянием», «следствие», «причина»
        claim = copy.deepcopy(item)
        claim["mainsnak"]["property"] = prop
        claims[prop] = [claim]
    fetch = FixtureFetch(extra={REVOLUTION: record})
    manifest = decide(harvest(EPOCHS_YAML, {"epochs": []}, fetch), **{REVOLUTION: "accepted"})
    revolution = manifest["epochs"][0]["candidates"][0]
    revolution["mechanism"] = "political"  # лишнее поле в манифесте
    revolution["qualifiers"] = {"mechanism": "political"}
    importer.apply(manifest, fetch)
    types = all_statement_types(onto)
    for forbidden in ("stimulated", "influenced_by", "circumstance", "participated"):
        assert forbidden not in types, (forbidden, types)
    with onto.registry.engine.begin() as conn:
        qualifiers = list(conn.scalars(select(schema.statements.c.qualifiers)))
    assert not any("mechanism" in json.dumps(q or {}) for q in qualifiers)
    assert events.one("knowledge.context_import.run")["statements"] == 4


@req(EC, WD, invariant="класс P31 не из таблицы — вид события не пишется")
def test_unknown_class_no_kind(onto, importer, events, no_network):
    manifest = decide(harvested(), **{QUAKE: "accepted"})
    importer.apply(manifest, FixtureFetch())
    event = onto.entities.by_external("wikidata", QUAKE)
    types = sorted(s["type"] for s in out_rows(onto, event))
    assert types == ["belongs_to_epoch", "dating"]
    run = events.one("knowledge.context_import.run")
    assert (run["created"], run["statements"], run["places_created"]) == (1, 2, 0)


@req(EC, WD, invariant="кандидат без даты не предлагается")
def test_undated_never_offered(onto, enl, events, no_network):
    manifest = harvested()
    assert UNDATED not in json.dumps(manifest)


@req(EC, WD, invariant="событие и место находятся по QID: точные statements и places_created")
def test_found_by_qid(onto, importer, events, no_network):
    paris = onto.entities.create(
        "place", [("ru", "Париж", "primary")], external={"wikidata": PARIS}
    )
    event = onto.entities.create(
        "event", [("ru", "Революция 1789 года", "primary")], external={"wikidata": REVOLUTION}
    )
    before = table_rows(onto)
    events.clear()
    importer.apply(decide(harvested(), **{REVOLUTION: "accepted"}), FixtureFetch())
    assert onto.entities.by_external("wikidata", REVOLUTION) == event
    assert table_rows(onto)["entities"] == before["entities"]
    [place] = [s for s in out_rows(onto, event) if s["type"] == "happened_in"]
    assert place["object"] == paris
    run = events.one("knowledge.context_import.run")
    assert (run["created"], run["statements"], run["places_created"]) == (1, 4, 0)
    assert events.where("knowledge.context_import.checked", qid=REVOLUTION, result="created")


@req(EC, WD, invariant="no_date и fetch_failed — пропуск без записи")
def test_no_date_and_fetch_failed(onto, importer, events, no_network):
    manifest = decide(harvested(), **{REVOLUTION: "accepted", QUAKE: "accepted"})
    # При повторной загрузке у QUAKE дата пропала; REVOLUTION не загружается.
    record = read(f"entity_{QUAKE}.json")
    record["entities"][QUAKE]["claims"].pop("P585", None)
    before = table_rows(onto)
    events.clear()
    importer.apply(manifest, FixtureFetch(extra={QUAKE: record}, failing={REVOLUTION}))
    assert table_rows(onto) == before
    results = {e["qid"]: e["result"] for e in events.of("knowledge.context_import.checked")}
    assert results == {REVOLUTION: "fetch_failed", QUAKE: "no_date"}
    run = events.one("knowledge.context_import.run")
    assert (run["created"], run["skipped"]) == (0, 2)


@req(EC, WD, invariant="--dry-run не меняет таблиц (CLI)")
def test_cli_dry_run_changes_nothing(tmp_path, onto, enl, events, no_network):
    manifest = decide(harvested(), **{REVOLUTION: "accepted", QUAKE: "accepted"})
    path = tmp_path / "epoch_context.yaml"
    path.write_text(yaml.safe_dump(manifest, allow_unicode=True), encoding="utf-8")
    before = table_rows(onto)
    events.clear()
    service = lambda: EpochContextImport(onto.statements)  # noqa: E731
    code = main(
        ["apply", "--manifest", str(path), "--dry-run"], fetch=FixtureFetch(), service=service
    )
    assert code == 0
    assert table_rows(onto) == before
    run = events.one("knowledge.context_import.run")
    assert run["mode"] == "dry_run" and run["created"] == 2 and run["places_created"] == 1
    code = main(["apply", "--manifest", str(path)], fetch=FixtureFetch(), service=service)
    assert code == 0 and table_rows(onto) != before
    assert events.of("knowledge.context_import.run")[-1]["mode"] == "apply"


@req(EC, WD, invariant="события журнала импорта — только QID, коды и числа")
def test_import_events_only_codes(onto, importer, events, no_network):
    manifest = decide(harvested(), **{REVOLUTION: "accepted", QUAKE: "rejected"})
    importer.apply(manifest, FixtureFetch())
    ours = [e for e in events.items if e.name.startswith("knowledge.context_import")]
    assert {e.name for e in ours} == {
        "knowledge.context_import.harvested",
        "knowledge.context_import.checked",
        "knowledge.context_import.run",
    }
    logged = json.dumps([e.fields for e in ours], ensure_ascii=False, default=str)
    for needle in ("Французская", "Париж", "Просвещение", "Paris"):
        assert needle not in logged, needle


# --- после ревью, круг 1: duplicate_qid (таблица result дельты) --------------------------------


@req(
    EC,
    WD,
    invariant="duplicate_qid: QID события или места у сущности другого типа — ничего не записано, "
    "пропущен",
)
@pytest.mark.parametrize("taken", ["event", "place"])
def test_duplicate_qid_other_type(onto, importer, events, no_network, taken):
    if taken == "event":  # QID события занят местом
        onto.entities.create(
            "place", [("ru", "Не событие", "primary")], external={"wikidata": REVOLUTION}
        )
    else:  # QID места занят событием
        onto.entities.create("event", [("ru", "Не место", "primary")], external={"wikidata": PARIS})
    manifest = decide(harvested(), **{REVOLUTION: "accepted"})
    before = table_rows(onto)
    events.clear()
    importer.apply(manifest, FixtureFetch())
    assert table_rows(onto) == before
    results = {e["qid"]: e["result"] for e in events.of("knowledge.context_import.checked")}
    assert results[REVOLUTION] == "duplicate_qid"
    run = events.one("knowledge.context_import.run")
    assert (run["created"], run["statements"], run["places_created"]) == (0, 0, 0)
    assert run["skipped"] == 2  # duplicate_qid и второй кандидат pending


@req(EC, WD, invariant="Название события проверяется правилом типа event: 8 слов в пределе 12 (J8)")
def test_event_label_checked_by_event_rule(onto, importer, enl, events, no_network):
    manifest = decide(harvested(), **{REVOLUTION: "accepted"})
    revolution = manifest["epochs"][0]["candidates"][0]
    long_label = "Великая французская революция и падение старого порядка во Франции"  # 9 слов
    revolution["label"] = {"ru": long_label}
    report = importer.apply(manifest, FixtureFetch())
    assert report.totals()["created"] == 1
    event = onto.entities.by_external("wikidata", REVOLUTION)
    assert onto.entities.label(event) == long_label
    events.assert_none("knowledge.entity.rejected")
