"""entity-dating (add-wikidata-life-dates): «Даты жизни из Wikidata», «Подтверждение QID
персон и произведений»; ontology-extraction MODIFIED «Импорт из Wikidata».

По дельтам ``openspec/changes/add-wikidata-life-dates/specs``. Команда — ``LifeDates`` и CLI
``life_dates.main`` (``--from-file``); Wikidata — записи теста (``wd_records``), сеть
запрещена. Импорт — ``Filling.import_wikidata`` стенда извлечения. Вывод — база
(``primary.dates``, утверждения, внешние QID), манифест, отчёт и JSON CLI, код выхода, дамп
таблиц данных; журнал — ``knowledge.life_dates.*``, ``knowledge.import.skipped``. Ожидания
property-тестов — таблица точностей спецификации в ``strategies`` (без ``wikidata``/``dates``).
"""

from __future__ import annotations

import json

import pytest
from hypothesis import HealthCheck, assume, example, given, settings
from hypothesis import strategies as hst
from sqlalchemy import func, select

from philograph.knowledge import schema as t
from philograph.knowledge.dates import parse
from philograph.knowledge.life_dates import LifeDates, ManifestError, main
from philograph.knowledge.review import Review
from philograph.knowledge.statements import Attribution, Provenance
from philograph.knowledge.wikidata import wikidata_time
from philograph.operator.access import ActionLog

from ..conftest import PROFILES
from .dump import dump
from .extraction_stand import Stand
from .strategies import (
    expected_dating,
    manifests,
    sentinel,
    wd_bounds,
    wd_person_records,
    wd_times,
    wd_value,
)
from .wd_records import RecordFetch, no_network, record  # noqa: F401

req = pytest.mark.req
ED = "entity-dating"
LIFE = "Даты жизни из Wikidata"
QIDS = "Подтверждение QID персон и произведений"
EX = "ontology-extraction"
IMPORT = "Импорт из Wikidata"
HUMAN = ("Q5",)
PHILOSOPHER = "Q4964182"
SKIPPED = "knowledge.life_dates.skipped"
RUN = "knowledge.life_dates.run"
ROLLED = "knowledge.life_dates.rolled_back"
SUGGESTED = "knowledge.life_dates.suggested"
PROPOSED = "knowledge.entity.merge_proposed"
MERGED = "knowledge.entity.merged"
NOISE = {"request_id", "service", "run_id"}
KEYS = {
    SKIPPED: {"entity", "property", "reason"},
    RUN: {
        "entities",
        "externals",
        "lifespans",
        "datings",
        "roles",
        "unchanged",
        "conflicts",
        "skipped",
        "failed",
        "dry_run",
    },
    ROLLED: {"statements", "externals", "kept"},
    SUGGESTED: {"entities", "candidates", "auto"},
}
CI = settings(parent=PROFILES["ci"], suppress_health_check=[HealthCheck.function_scoped_fixture])


def check_keys(events) -> None:
    """Точное множество ключей всех событий команды (без полей контекста)."""
    for name, keys in KEYS.items():
        for e in events.of(name):
            assert set(e.fields) - NOISE == keys, (name, e.fields)


def no_token(events, token: str) -> None:
    for event in events.items:
        assert token not in repr(event.fields), event.name


def person(qid, ru=None, en=None, *, description=None, occupations=(), **times):
    return record(
        qid,
        ru=ru,
        en=en,
        description=description,
        classes=HUMAN,
        times=dict(times),
        items={"P106": list(occupations)} if occupations else None,
    )


def y(value: str) -> str:
    return value if "T" in value else f"{value}T00:00:00Z"


def create(onto, name, type_="person", qid=None, lang="ru"):
    external = {"wikidata": qid} if qid else None
    return onto.entities.create(type_, [(lang, name, "primary")], external=external)


def entry(entity, qid, decision="accepted"):
    return {"entity": entity, "wikidata": qid, "decision": decision, "candidates": []}


def dates_of(onto, entity_id):
    return onto.entities.get(entity_id)["primary"].get("dates")


def bounds(d) -> tuple:
    return (d["earliest_start"], d["latest_start"], d["earliest_end"], d["latest_end"])


def count_statements(onto) -> int:
    with onto.statements.engine.begin() as conn:
        return conn.scalar(select(func.count()).select_from(t.statements))


def review_of(onto, clock) -> Review:
    return Review(onto.statements, ActionLog(onto.statements.engine, clock))


def life(onto, fetch, review=None) -> LifeDates:
    return LifeDates(onto.statements, fetch, review)


def wipe(onto) -> None:
    with onto.statements.engine.begin() as conn:
        for table in (
            t.attributions,
            t.evidence,
            t.statements,
            t.statement_views,
            t.mentions,
            t.portraits,
            t.merges,
            t.run_actions,
            t.review_items,
            t.external_ids,
            t.names,
            t.entities,
        ):
            conn.execute(table.delete())


TOKEN = sentinel()
PLATO = person(
    "Q859",
    "Платон",
    "Plato",
    description=f"древнегреческий философ {TOKEN}",
    occupations=[PHILOSOPHER],
    P569=(y("-0427-00-00"), 9),
    P570=(y("-0347-00-00"), 9),
)


# =========================== Даты жизни из Wikidata =======================================


@req(ED, LIFE, scenario="Персона с QID")
def test_person_with_qid(onto, events, no_network):
    plato = create(onto, "Платон", qid="Q859")
    report = life(onto, RecordFetch({"Q859": PLATO})).apply({"entities": []}, linked=True)
    d = dates_of(onto, plato)
    assert bounds(d) == (-426, -426, -346, -346)
    assert (d["precision"], d["original"]) == ("year", "427 до н. э. – 347 до н. э.")
    [lifespan] = onto.statements.about(plato, types=["lifespan"])
    assert lifespan["status"] == "sourced"
    [who] = lifespan["attributions"]
    assert (who["who_kind"], who["who"]) == ("source", "wikidata:Q859")
    assert who["place"] == "https://www.wikidata.org/wiki/Q859"
    assert lifespan["provenance"]["method"] == "imported"
    assert lifespan["provenance"]["run_id"] == report.run_id
    roles = onto.statements.about(plato, types=["person_role"])
    assert [r["value"] for r in roles] == ["philosopher"]
    [run] = events.of(RUN)
    assert (run["lifespans"], run["roles"], run["dry_run"]) == (1, 1, False)
    assert run["run_id"] == report.run_id
    assert events.where("knowledge.statement.created", type="lifespan")
    check_keys(events)
    no_token(events, TOKEN)


@req(ED, LIFE, scenario="Кант с днями")
def test_kant_with_days(onto, events, no_network):
    kant = create(onto, "Кант", qid="Q9312")
    rec = person("Q9312", "Кант", P569=(y("+1724-04-22"), 11), P570=(y("+1804-02-12"), 11))
    life(onto, RecordFetch({"Q9312": rec})).apply({"entities": []}, linked=True)
    d = dates_of(onto, kant)
    assert bounds(d) == (1724, 1724, 1804, 1804)
    assert (d["precision"], d["original"]) == ("year", "1724–1804")
    assert events.one(RUN)["lifespans"] == 1
    check_keys(events)


@req(ED, LIFE, scenario="Год произведения")
def test_work_year(onto, events, no_network):
    work = create(onto, "Критика чистого разума", type_="work", qid="Q99")
    rec = record("Q99", ru="Критика", classes=(), times={"P577": (y("+1781-00-00"), 9)})
    life(onto, RecordFetch({"Q99": rec})).apply({"entities": []}, linked=True)
    d = dates_of(onto, work)
    assert bounds(d) == (1781, 1781, 1781, 1781)
    assert [s["type"] for s in onto.statements.about(work)] == ["dating"]
    assert events.one(RUN)["datings"] == 1
    check_keys(events)


@req(ED, LIFE, scenario="Точность десятилетия, века и дня")
def test_decade_century(onto, events, no_network):
    rough = create(onto, "Грубо", qid="Q3")
    rec = person("Q3", "Грубо", P569=(y("+1680-00-00"), 8), P570=(y("+1801-00-00"), 7))
    life(onto, RecordFetch({"Q3": rec})).apply({"entities": []}, linked=True)
    d = dates_of(onto, rough)
    assert bounds(d) == (1680, 1689, 1801, 1900)
    assert d["precision"] == "century"
    assert events.one(RUN)["lifespans"] == 1
    check_keys(events)


@req(ED, LIFE, scenario="Год 0000 и малая точность")
def test_year_zero_and_low_precision(onto, events, no_network):
    zero = create(onto, "Ноль", qid="Q2")
    low = create(onto, "Грубая", qid="Q4")
    fetch = RecordFetch(
        {
            "Q2": person("Q2", "Ноль", P569=(y("+0000-00-00"), 9), P570=(y("+1700-00-00"), 9)),
            "Q4": person("Q4", "Грубая", P569=(y("+1600-00-00"), 5), P570=(y("+1650-00-00"), 9)),
        }
    )
    life(onto, fetch).apply({"entities": []}, linked=True)
    assert dates_of(onto, zero) is None and dates_of(onto, low) is None
    skipped = sorted((e["entity"], e["property"], e["reason"]) for e in events.of(SKIPPED))
    assert skipped == sorted([(zero, "P569", "bad_value"), (low, "P569", "bad_value")])
    check_keys(events)


@req(ED, LIFE, scenario="Одна дата")
def test_one_date(onto, events, no_network):
    one = create(onto, "Один", qid="Q1")
    rec = person("Q1", "Один", P569=(y("+1600-00-00"), 9))
    life(onto, RecordFetch({"Q1": rec})).apply({"entities": []}, linked=True)
    assert dates_of(onto, one) is None
    assert onto.statements.about(one, types=["lifespan"]) == []
    assert [(e["property"], e["reason"]) for e in events.of(SKIPPED)] == [("P570", "partial")]
    check_keys(events)


@req(ED, LIFE, scenario="Дата уже есть")
def test_existing_dates(onto, events, no_network):
    kant = create(onto, "Кант", qid="Q9312")
    other = create(onto, "Другой", qid="Q7")
    src = [Attribution("source", "s1")]
    for entity_id, text in ((kant, "1724–1804"), (other, "1600–1650")):
        onto.statements.add(entity_id, "lifespan", value=parse(text).to_json(), attributions=src)
    before = {e: dates_of(onto, e) for e in (kant, other)}
    fetch = RecordFetch(
        {
            "Q9312": person(
                "Q9312", "Кант", P569=(y("+1724-04-22"), 11), P570=(y("+1804-02-12"), 11)
            ),
            "Q7": person("Q7", "Другой", P569=(y("+1601-00-00"), 9), P570=(y("+1660-00-00"), 9)),
        }
    )
    life(onto, fetch).apply({"entities": []}, linked=True)
    assert {e: dates_of(onto, e) for e in (kant, other)} == before
    for e in (kant, other):
        assert len(onto.statements.about(e, types=["lifespan"])) == 1
    run = events.one(RUN)
    assert (run["unchanged"], run["conflicts"], run["lifespans"]) == (1, 1, 0)
    assert [(e["entity"], e["reason"]) for e in events.of(SKIPPED)] == [(other, "conflict")]
    check_keys(events)


@req(ED, LIFE, scenario="Сухой прогон и откат")
def test_dry_run_and_rollback_cli(onto, events, tmp_path, capsys, no_network):
    plato = create(onto, "Платон")
    records = tmp_path / "records.json"
    records.write_text(json.dumps({"Q859": PLATO}), encoding="utf-8")
    manifest = tmp_path / "person_qids.yaml"
    manifest.write_text(
        f"# шапка\nentities:\n- entity: {plato}\n  wikidata: Q859\n  decision: accepted\n",
        encoding="utf-8",
    )

    def service(fetch):
        return LifeDates(onto.statements, fetch)

    base = ["--manifest", str(manifest), "--from-file", str(records)]
    before = dump(onto.statements.engine)
    assert main(["apply", "--dry-run", *base], service=service) == 0
    dry = json.loads(capsys.readouterr().out)
    assert dump(onto.statements.engine) == before
    assert main(["apply", *base], service=service) == 0
    real = json.loads(capsys.readouterr().out)
    strip = {"run_id", "dry_run"}
    assert {k: v for k, v in dry.items() if k not in strip} == {
        k: v for k, v in real.items() if k not in strip
    }
    assert (dry["dry_run"], real["dry_run"], real["externals"], real["lifespans"]) == (
        True,
        False,
        1,
        1,
    )
    assert dump(onto.statements.engine) != before
    assert main(["rollback", real["run_id"]], service=service) == 0
    rolled = json.loads(capsys.readouterr().out)
    assert dump(onto.statements.engine) == before
    assert rolled["run_id"] == real["run_id"] and rolled["kept"] == 0
    runs = events.of(RUN)
    assert [r["dry_run"] for r in runs] == [True, False]
    assert runs[1]["run_id"] == real["run_id"]
    assert events.one(ROLLED)["run_id"] == real["run_id"]
    check_keys(events)
    no_token(events, TOKEN)


@req(ED, LIFE, scenario="Откат с проверенным утверждением")
def test_rollback_keeps_verified(onto, events, no_network):
    plato = create(onto, "Платон")
    report = life(onto, RecordFetch({"Q859": PLATO})).apply({"entities": [entry(plato, "Q859")]})
    [lifespan] = onto.statements.about(plato, types=["lifespan"])
    onto.statements.confirm(lifespan["id"], "operator")
    assert onto.statements.get(lifespan["id"])["status"] == "verified"
    life(onto, RecordFetch()).rollback(report.run_id)
    assert [s["id"] for s in onto.statements.about(plato, types=["lifespan"])] == [lifespan["id"]]
    assert onto.entities.external_of(plato, "wikidata") == "Q859"
    assert onto.statements.about(plato, types=["person_role"]) == []  # прочие удалены
    rolled = events.one(ROLLED)
    assert rolled["kept"] == 1 and rolled["run_id"] == report.run_id
    check_keys(events)


@req(ED, LIFE, scenario="Откат с проверенным утверждением")
def test_rollback_verified_keeps_attribution(onto, events, no_network):
    """Проверенное утверждение запуска откат не убирает — вместе с его атрибуцией
    ``wikidata:<QID>`` (на неё ссылается правило «QID остаётся и попадает в kept»)."""
    plato = create(onto, "Платон")
    report = life(onto, RecordFetch({"Q859": PLATO})).apply({"entities": [entry(plato, "Q859")]})
    [lifespan] = onto.statements.about(plato, types=["lifespan"])
    onto.statements.confirm(lifespan["id"], "operator")
    life(onto, RecordFetch()).rollback(report.run_id)
    kept = onto.statements.get(lifespan["id"])
    assert [(a["who_kind"], a["who"]) for a in kept["attributions"]] == [
        ("source", "wikidata:Q859")
    ]
    assert kept["status"] == "verified"


# --- инварианты «Даты жизни» ---------------------------------------------------------------


def _build_records(onto, cases):
    ids, records = {}, {}
    for i, case in enumerate(cases):
        ids[i] = create(onto, case["name"], type_=case["type"], qid=case["qid"])
        if case["existing"]:
            onto.statements.add(
                ids[i],
                "lifespan" if case["type"] == "person" else "dating",
                value=parse(case["existing"]).to_json(),
                attributions=[Attribution("source", "s1")],
            )
        records[case["qid"]] = record(
            case["qid"],
            ru=case["name"],
            classes=HUMAN if case["type"] == "person" else (),
            times={p: v for p, v in case["times"].items()},
            items={"P106": case["occupations"]} if case["occupations"] else None,
        )
    return ids, records


def _records_strategy():
    return hst.integers(1, 4).flatmap(
        lambda n: hst.tuples(*(wd_person_records(i) for i in range(n)))
    )


PLATO_CASE = {
    "qid": "Q700000",
    "type": "person",
    "name": "Лицо 0",
    "times": {"P569": [(y("-0427-00-00"), 9, "normal")], "P570": [(y("-0347-00-00"), 9, "normal")]},
    "chosen": {"P569": ("value", (-426, -426, "year")), "P570": ("value", (-346, -346, "year"))},
    "occupations": [PHILOSOPHER, "Q193391"],
    "roles": {"philosopher"},
    "existing": None,
}
DECADE_CENTURY_CASE = {
    **PLATO_CASE,
    "times": {"P569": [(y("+1680-00-00"), 8, "normal")], "P570": [(y("+1801-00-00"), 7, "normal")]},
    "chosen": {
        "P569": ("value", (1680, 1689, "decade")),
        "P570": ("value", (1801, 1900, "century")),
    },
    "occupations": [],
    "roles": set(),
}
RANKED_CASE = {
    **PLATO_CASE,
    "times": {
        "P569": [
            (y("+1500-00-00"), 9, "deprecated"),
            (y("+1600-00-00"), 9, "normal"),
            (y("+1601-00-00"), 9, "preferred"),
        ],
        "P570": [(y("+1650-00-00"), 9, "normal"), (y("+1660-00-00"), 9, "normal")],
    },
    "chosen": {"P569": ("value", (1601, 1601, "year")), "P570": ("value", (1650, 1650, "year"))},
    "occupations": [],
    "roles": set(),
}


@req(ED, LIFE, scenario="Инвариант импорта дат")
@req(ED, LIFE, invariant="Границы по таблице, «−» ⇒ ≤ 0, без перезаписи, сухой прогон, повтор")
@CI
@given(_records_strategy())
@example((PLATO_CASE,))
@example((DECADE_CENTURY_CASE,))
@example((RANKED_CASE,))
def test_life_dates_invariant(onto, events, cases):
    wipe(onto)
    ids, records = _build_records(onto, cases)
    fetch = RecordFetch(records)
    start = dump(onto.statements.engine)
    existing = {i: dates_of(onto, ids[i]) for i, c in enumerate(cases) if c["existing"]}
    events.clear()
    dry = life(onto, fetch).apply({"entities": []}, linked=True, dry_run=True)
    assert dump(onto.statements.engine) == start
    real = life(onto, fetch).apply({"entities": []}, linked=True)
    strip = ("run_id", "dry_run")
    assert {k: v for k, v in dry.to_json().items() if k not in strip} == {
        k: v for k, v in real.to_json().items() if k not in strip
    }
    for i, case in enumerate(cases):
        entity = ids[i]
        outcome, expected = expected_dating(case)
        reasons = {(e["property"], e["reason"]) for e in events.where(SKIPPED, entity=entity)} - {
            (p, "conflict") for p in ("P569", "P570", "P577", "item")
        }
        kind = "lifespan" if case["type"] == "person" else "dating"
        if case["existing"]:
            assert dates_of(onto, entity) == existing[i]
            assert len(onto.statements.about(entity, types=[kind])) == 1
        elif outcome == "write":
            if any(r == "refused" for _p, r in reasons):
                # порядок: конец раньше начала — отказ проверки значения
                assert expected["latest_end"] < expected["earliest_start"], (case, reasons)
                continue
            d = dates_of(onto, entity)
            assert d is not None, (case, reasons)
            assert {k: d[k] for k in expected} == expected, case
            [written] = onto.statements.about(entity, types=[kind])
            assert written["status"] == "sourced"
            assert written["attributions"][0]["who"] == f"wikidata:{case['qid']}"
        else:
            assert dates_of(onto, entity) is None
            assert onto.statements.about(entity, types=[kind]) == []
            assert reasons, case
            assert reasons <= expected or reasons & expected, (case, reasons, expected)
        roles = {r["value"] for r in onto.statements.about(entity, types=["person_role"])}
        assert roles == case["roles"], case
    # «−» ⇒ ≤ 0: каждая записанная граница с минусом в выбранном значении
    for i, case in enumerate(cases):
        d = dates_of(onto, ids[i])
        if d is None or case["existing"]:
            continue
        for prop, pick in case["chosen"].items():
            if pick and pick[1] is not None and _chosen_negative(case, prop):
                lo, hi = (
                    (d["earliest_start"], d["latest_start"])
                    if prop in ("P569", "P577")
                    else (d["earliest_end"], d["latest_end"])
                )
                assert lo <= 0 and hi <= 0, case
    # повтор не добавляет утверждений
    count = count_statements(onto)
    again = life(onto, fetch).apply({"entities": []}, linked=True)
    assert count_statements(onto) == count
    assert (again.lifespans, again.datings, again.roles) == (0, 0, 0)
    check_keys(events)


def _chosen_negative(case, prop) -> bool:
    values = case["times"].get(prop) or []
    preferred = [v for v in values if v[2] == "preferred"]
    normal = [v for v in values if v[2] == "normal"]
    chosen = (preferred or normal or [None])[0]
    return bool(chosen) and chosen[0].startswith("-")


@req(ED, LIFE, invariant="Откат без проверенных возвращает дамп к исходному")
@CI
@given(_records_strategy())
@example((PLATO_CASE,))
def test_rollback_without_verified_restores_dump(onto, events, cases):
    wipe(onto)
    ids, records = _build_records(onto, cases)
    # половина — через манифест: QID пишет запуск, откат его убирает
    manifest = []
    for i, case in enumerate(cases):
        if i % 2:
            onto.entities.remove_external(ids[i], "wikidata", case["qid"])
            manifest.append(entry(ids[i], case["qid"]))
    start = dump(onto.statements.engine)
    report = life(onto, RecordFetch(records)).apply({"entities": manifest}, linked=True)
    summary = life(onto, RecordFetch(records)).rollback(report.run_id)
    assert dump(onto.statements.engine) == start
    assert summary["kept"] == 0
    assert summary["externals"] == len(manifest)


@req(ED, LIFE, invariant="Откат сохраняет проверенные утверждения запуска и их QID")
@CI
@given(_records_strategy(), hst.data())
@example((PLATO_CASE,), None)
def test_rollback_keeps_verified_and_qid(onto, events, cases, data):
    wipe(onto)
    ids, records = _build_records(onto, cases)
    manifest = []
    for i, case in enumerate(cases):
        onto.entities.remove_external(ids[i], "wikidata", case["qid"])
        manifest.append(entry(ids[i], case["qid"]))
    report = life(onto, RecordFetch(records)).apply({"entities": manifest})
    with onto.statements.engine.begin() as conn:
        written = sorted(
            r[0]
            for r in conn.execute(
                select(t.statements.c.id).where(
                    t.statements.c.provenance["run_id"].as_string() == report.run_id
                )
            )
        )
    assume(written)
    chosen = (
        data.draw(hst.lists(hst.sampled_from(written), min_size=1, unique=True))
        if data is not None
        else written[:1]
    )
    for sid in chosen:
        onto.statements.confirm(sid, "operator")
    events.clear()
    owners = {onto.statements.get(s)["subject"] for s in chosen}
    life(onto, RecordFetch(records)).rollback(report.run_id)
    for sid in chosen:
        kept = onto.statements.get(sid)
        assert kept["status"] == "verified"
        # атрибуция wikidata:<QID> проверенного — отдельный тест (дефект Д1, verification.md)
    for sid in set(written) - set(chosen):
        with onto.statements.engine.begin() as conn:
            assert conn.scalar(select(t.statements.c.id).where(t.statements.c.id == sid)) is None
    qid_of = {ids[i]: c["qid"] for i, c in enumerate(cases)}
    for entity in ids.values():
        expected = qid_of[entity] if entity in owners else None
        assert onto.entities.external_of(entity, "wikidata") == expected
    assert events.one(ROLLED)["kept"] == len(owners)


# =========================== Подтверждение QID ===========================================


def _plato_fetch():
    not_human = record("Q1234567", ru="Платон", classes=("Q4167410",))
    return RecordFetch(
        {"Q859": PLATO, "Q1234567": not_human},
        searches={("Платон", "ru"): [{"id": "Q859"}, {"id": "Q1234567"}]},
    )


@req(ED, QIDS, scenario="Кандидаты для персоны")
def test_candidates_for_person(onto, events, no_network):
    plato = create(onto, "Платон")
    before = dump(onto.statements.engine)
    manifest = life(onto, _plato_fetch()).suggest({"entities": []})
    assert dump(onto.statements.engine) == before
    [e] = [x for x in manifest["entities"] if x["entity"] == plato]
    assert (e["wikidata"], e["decision"]) == (None, "pending")
    [c] = e["candidates"]
    assert c["qid"] == "Q859"
    assert c["label"] == {"ru": "Платон", "en": "Plato"}
    assert c["description"].startswith("древнегреческий философ")
    assert (c["birth"], c["death"]) == ("427 до н. э.", "347 до н. э.")
    s = events.one(SUGGESTED)
    assert (s["candidates"], s["auto"]) == (1, 0)
    check_keys(events)


@req(ED, QIDS, scenario="Кандидат уже у другой персоны")
def test_candidate_held_by_other(onto, events, clock, no_network):
    homer = create(onto, "Гомер", qid="Q6691")
    omir = create(onto, "Омир")
    fetch = RecordFetch(
        {"Q6691": person("Q6691", "Гомер", "Homer")},
        searches={("Омир", "ru"): [{"id": "Q6691"}]},
    )
    review = review_of(onto, clock)
    manifest = life(onto, fetch, review).suggest({"entities": []})
    [e] = [x for x in manifest["entities"] if x["entity"] == omir]
    assert e["decision"] == "pending" and e["candidates"][0]["holder"] == homer
    items = review.queue(kind="duplicate")
    assert [set(i["payload"]["pair"]) for i in items] == [{homer, omir}]
    life(onto, fetch, review).suggest(manifest)
    assert len(review.queue(kind="duplicate")) == 1
    proposed = events.of(PROPOSED)
    assert [p["reason"] for p in proposed] == ["review:qid_candidate"]
    check_keys(events)


@req(ED, QIDS, scenario="Точное совпадение с флагом")
def test_exact_with_flag(onto, events, no_network):
    plato = create(onto, "Платон")
    manifest = life(onto, _plato_fetch()).suggest({"entities": []}, auto_exact=True)
    [e] = [x for x in manifest["entities"] if x["entity"] == plato]
    assert (e["wikidata"], e["decision"]) == ("Q859", "auto")
    assert events.one(SUGGESTED)["auto"] == 1
    check_keys(events)


@req(ED, QIDS, scenario="Два кандидата")
def test_two_candidates(onto, events, no_network):
    bacon = create(onto, "Бэкон")
    fetch = RecordFetch(
        {"Q37388": person("Q37388", "Бэкон"), "Q192010": person("Q192010", "Бэкон")},
        searches={("Бэкон", "ru"): [{"id": "Q37388"}, {"id": "Q192010"}]},
    )
    manifest = life(onto, fetch).suggest({"entities": []}, auto_exact=True)
    [e] = [x for x in manifest["entities"] if x["entity"] == bacon]
    assert sorted(c["qid"] for c in e["candidates"]) == ["Q192010", "Q37388"]
    assert (e["wikidata"], e["decision"]) == (None, "pending")
    assert events.one(SUGGESTED)["auto"] == 0
    check_keys(events)


@req(ED, QIDS, invariant="Кандидат произведения — запись с P577")
def test_work_candidate_needs_publication_date(onto, events, no_network):
    work = create(onto, "Критика чистого разума", type_="work")
    with_date = record(
        "Q1", ru="Критика чистого разума", classes=(), times={"P577": (y("+1781-00-00"), 9)}
    )
    without = record("Q2", ru="Критика чистого разума", classes=())
    fetch = RecordFetch(
        {"Q1": with_date, "Q2": without},
        searches={("Критика чистого разума", "ru"): [{"id": "Q1"}, {"id": "Q2"}]},
    )
    manifest = life(onto, fetch).suggest({"entities": []})
    [e] = [x for x in manifest["entities"] if x["entity"] == work]
    assert [c["qid"] for c in e["candidates"]] == ["Q1"]
    assert events.one(SUGGESTED)["candidates"] == 1


@req(ED, QIDS, invariant="auto: даты кандидата не противоречат датам сущности")
def test_auto_exact_needs_compatible_dates(onto, events, no_network):
    from philograph.knowledge.dates import lifespan

    kant = create(onto, "Кант")
    onto.statements.add(
        kant,
        "lifespan",
        value=lifespan("1724", "1804").to_json(),
        attributions=[Attribution("common")],
        provenance=Provenance("manual", actor="tester"),
    )
    far = person("Q1", "Кант", "Kant", P569=(y("+1824-00-00"), 9), P570=(y("+1904-00-00"), 9))
    near = person("Q2", "Кант", "Kant", P569=(y("+1724-04-22"), 11), P570=(y("+1804-02-12"), 11))
    for qid, record_ in (("Q1", far), ("Q2", near)):
        manifest = life(
            onto, RecordFetch({qid: record_}, searches={("Кант", "ru"): [{"id": qid}]})
        ).suggest({"entities": []}, auto_exact=True)
        [e] = [x for x in manifest["entities"] if x["entity"] == kant]
        expected = (None, "pending") if qid == "Q1" else ("Q2", "auto")
        assert (e["wikidata"], e["decision"]) == expected, qid


@req(ED, QIDS, invariant="suggest ищет по основному названию и вариантам")
def test_suggest_searches_variants(onto, events, no_network):
    plato = onto.entities.create(
        "person", [("ru", "Платон", "primary"), ("en", "Plato", "variant")]
    )
    fetch = RecordFetch(
        {"Q859": person("Q859", "Платон", "Plato")},
        searches={("Plato", "en"): [{"id": "Q859"}]},  # только по варианту
    )
    manifest = life(onto, fetch).suggest({"entities": []})
    [e] = [x for x in manifest["entities"] if x["entity"] == plato]
    assert [c["qid"] for c in e["candidates"]] == ["Q859"]


@req(ED, QIDS, invariant="Решение человека подбор не меняет: auto не перезаписывает accepted")
def test_suggest_keeps_human_decision(onto, events, no_network):
    plato = create(onto, "Платон")
    manifest = {
        "entities": [{"entity": plato, "wikidata": "Q1", "decision": "accepted", "candidates": []}]
    }
    out = life(onto, _plato_fetch()).suggest(manifest, auto_exact=True)
    [e] = [x for x in out["entities"] if x["entity"] == plato]
    assert (e["wikidata"], e["decision"], e["candidates"]) == ("Q1", "accepted", [])
    assert events.one(SUGGESTED)["entities"] == 0


@req(ED, QIDS, invariant="Держатель QID другого вида (произведение) не становится holder")
def test_holder_of_other_kind_ignored(onto, events, clock, no_network):
    create(onto, "Платон", type_="work", qid="Q859")
    plato = create(onto, "Платон")
    fetch = RecordFetch(
        {"Q859": person("Q859", "Платон", "Plato")}, searches={("Платон", "ru"): [{"id": "Q859"}]}
    )
    review = review_of(onto, clock)
    manifest = life(onto, fetch, review).suggest({"entities": []})
    [e] = [x for x in manifest["entities"] if x["entity"] == plato]
    assert [c.get("holder") for c in e["candidates"]] == [None]
    assert review.queue(kind="duplicate") == []
    events.assert_none(PROPOSED)


@req(ED, QIDS, invariant="Пара с решением «разные» повторно в очередь не ставится")
def test_holder_pair_decided_apart_not_requeued(onto, events, clock, no_network):
    homer = create(onto, "Гомер", qid="Q6691")
    omir = create(onto, "Омир")
    fetch = RecordFetch(
        {"Q6691": person("Q6691", "Гомер", "Homer")},
        searches={("Омир", "ru"): [{"id": "Q6691"}]},
    )
    review = review_of(onto, clock)
    life(onto, fetch, review).suggest({"entities": []})
    [item] = review.queue(kind="duplicate")
    review.resolve_duplicate(item["item_id"], False, "operator")
    events.clear()
    manifest = life(onto, fetch, review).suggest({"entities": []})
    [e] = [x for x in manifest["entities"] if x["entity"] == omir]
    assert e["candidates"][0]["holder"] == homer  # держатель записан в кандидата
    assert review.queue(kind="duplicate") == []  # решённая пара не вернулась в очередь
    events.assert_none(PROPOSED)


@req(ED, LIFE, invariant="Режим --linked: QID не по шаблону — bad_qid без обращения к сети")
def test_linked_bad_qid_skipped_without_fetch(onto, events, no_network):
    kant = onto.entities.create("person", [("ru", "Кант", "primary")], external={"wikidata": "x1"})
    fetch = RecordFetch()
    life(onto, fetch).apply({"entities": []}, linked=True)
    assert [(e["entity"], e["property"], e["reason"]) for e in events.of(SKIPPED)] == [
        (kant, "item", "bad_qid")
    ]
    assert fetch.entity_calls() == []
    assert events.one(RUN)["skipped"] == 1


@req(ED, LIFE, invariant="Запись не получена — fetch_failed считается в failed, не в skipped")
def test_fetch_failed_counted_as_failed(onto, events, no_network):
    kant = create(onto, "Кант", qid="Q9312")
    fetch = RecordFetch(failing={"Q9312"})
    life(onto, fetch).apply({"entities": []}, linked=True)
    assert [(e["entity"], e["reason"]) for e in events.of(SKIPPED)] == [(kant, "fetch_failed")]
    run = events.one(RUN)
    assert (run["failed"], run["skipped"]) == (1, 0)
    assert dates_of(onto, kant) is None


@req(ED, QIDS, scenario="QID занят")
def test_qid_taken(onto, events, clock, no_network):
    hume = create(onto, "Hume", qid="Q41568", lang="en")
    yum = create(onto, "Юм")
    life(onto, RecordFetch(), review_of(onto, clock)).apply({"entities": [entry(yum, "Q41568")]})
    assert onto.entities.resolve(yum) == onto.entities.resolve(hume)
    kept = onto.entities.resolve(hume)
    assert onto.entities.externals("wikidata") == {kept: "Q41568"}
    assert [(e["entity"], e["reason"]) for e in events.of(SKIPPED)] == [(yum, "qid_taken")]
    assert [e["reason"] for e in events.of(MERGED)] == ["merge:qid_confirmed"]
    check_keys(events)


@req(ED, QIDS, scenario="Два подтверждения одного QID")
def test_two_confirmations(onto, events, clock, no_network):
    plato = create(onto, "Платон")
    plato_en = create(onto, "Plato", lang="en")
    report = life(onto, RecordFetch({"Q859": PLATO}), review_of(onto, clock)).apply(
        {"entities": [entry(plato, "Q859"), entry(plato_en, "Q859")]}
    )
    assert onto.entities.by_external("wikidata", "Q859") == onto.entities.resolve(plato)
    assert onto.entities.external_of(plato, "wikidata") == "Q859"
    assert [(e["entity"], e["reason"]) for e in events.of(SKIPPED)] == [(plato_en, "qid_taken")]
    # пара передана слиянию вариантов: «Plato» слита в «Платон» (или ждёт в очереди)
    merged = onto.entities.resolve(plato_en) == onto.entities.resolve(plato)
    assert merged or events.of(PROPOSED)
    assert report.externals == 1
    check_keys(events)


@req(ED, QIDS, scenario="У сущности другой QID")
def test_entity_has_other_qid(onto, events, no_network):
    kant = create(onto, "Кант", qid="Q9312")
    life(onto, RecordFetch()).apply({"entities": [entry(kant, "Q1")]})
    assert onto.entities.external_of(kant, "wikidata") == "Q9312"
    assert onto.entities.by_external("wikidata", "Q1") is None
    assert [(e["entity"], e["reason"]) for e in events.of(SKIPPED)] == [(kant, "qid_conflict")]
    check_keys(events)


@req(ED, QIDS, scenario="Неверный манифест")
def test_bad_manifest(tmp_path, capsys, events):
    path = tmp_path / "m.yaml"
    path.write_text("entities:\n- entity: e1\n  wikidata: null\n  decision: accepted\n")

    def service(_fetch):
        raise AssertionError("база и сеть до проверки формы")

    assert main(["apply", "--manifest", str(path)], service=service) == 2
    err = capsys.readouterr().err
    assert str(path) in err and "entities[0]" in err
    events.assert_none(RUN)


@pytest.mark.parametrize(
    "bad",
    [
        {"entity": "e1", "wikidata": "X1", "decision": "pending"},
        {"entity": "e1", "wikidata": None, "decision": "maybe"},
        {"entity": "e1", "wikidata": None, "decision": "auto"},
    ],
)
@req(ED, QIDS, invariant="Форма манифеста проверяется до базы — код 2")
def test_bad_manifest_forms(onto, bad):
    before = dump(onto.statements.engine)
    with pytest.raises(ManifestError):
        life(onto, RecordFetch()).apply({"entities": [bad]})
    duplicate = [entry("e1", None, "pending"), entry("e1", None, "pending")]
    with pytest.raises(ManifestError):
        life(onto, RecordFetch()).apply({"entities": duplicate})
    assert dump(onto.statements.engine) == before


@req(ED, QIDS, scenario="Инвариант подтверждения")
@req(ED, QIDS, invariant="QID только при accepted/auto, первое по порядку, не два у одного")
@CI
@given(manifests())
@example(
    {
        "n": 3,
        "held": {},
        "entries": [
            {"index": 0, "wikidata": "Q11", "decision": "accepted"},
            {"index": 1, "wikidata": "Q11", "decision": "accepted"},
            {"index": 2, "wikidata": "Q12", "decision": "pending"},
        ],
        "written": {0: "Q11"},
        "skipped": [(1, "qid_taken")],
    }
)
@example(
    {
        "n": 2,
        "held": {0: "Q11"},
        "entries": [
            {"index": 0, "wikidata": "Q12", "decision": "accepted"},
            {"index": 1, "wikidata": "Q11", "decision": "auto"},
        ],
        "written": {},
        "skipped": [(0, "qid_conflict"), (1, "qid_taken")],
    }
)
def test_qid_confirmation_invariant(onto, events, clock, case):
    wipe(onto)
    ids = {
        i: create(onto, f"Лицо {i} {'бвгде'[i]}", qid=case["held"].get(i)) for i in range(case["n"])
    }
    manifest = {
        "entities": [
            {**entry(ids[e["index"]], e["wikidata"], e["decision"])} for e in case["entries"]
        ]
    }
    events.clear()
    life(onto, RecordFetch(), review_of(onto, clock)).apply(manifest)
    externals = onto.entities.externals("wikidata")
    assert len(set(externals.values())) == len(externals)  # нет двух сущностей с одним QID
    expected = {**case["held"], **case["written"]}
    got = {}
    for i, entity in ids.items():
        q = onto.entities.external_of(onto.entities.resolve(entity), "wikidata")
        got[i] = q
    for i, q in expected.items():
        assert got[i] == q, (i, case)
    for i in set(ids) - set(expected):
        # без QID: если не слита с держателем по подтверждению человека
        resolved = onto.entities.resolve(ids[i])
        if resolved == ids[i]:
            assert onto.entities.external_of(ids[i], "wikidata") is None, (i, case)
    skipped = sorted(
        (next(i for i, e in ids.items() if e == ev["entity"]), ev["reason"])
        for ev in events.of(SKIPPED)
        if ev["reason"] in ("qid_conflict", "qid_taken")  # записи Wikidata в тесте нет
    )
    assert skipped == sorted(case["skipped"])
    check_keys(events)


NAMES = ("Платон", "Гомер", "Бэкон", "Сократ")


@hst.composite
def suggest_cases(draw):
    """0–3 кандидата-человека на сущность; подпись совпадает или нет; иногда не человек."""
    out = []
    for i in range(draw(hst.integers(1, 3))):
        name = NAMES[i]
        cands = []
        for k in range(draw(hst.integers(0, 3))):
            exact = draw(hst.booleans())
            human = draw(hst.integers(0, 3)) > 0
            cands.append(
                {
                    "qid": f"Q{800000 + 10 * i + k}",
                    "label": name if exact else f"{name}ов",
                    "human": human,
                }
            )
        out.append({"name": name, "candidates": cands})
    return out, draw(hst.booleans())


@req(ED, QIDS, invariant="auto только с флагом и при одном точном кандидате-человеке")
@CI
@given(suggest_cases())
def test_suggest_auto_invariant(onto, events, case):
    cases, flag = case
    wipe(onto)
    records, searches, ids = {}, {}, {}
    for c in cases:
        ids[c["name"]] = create(onto, c["name"])
        searches[(c["name"], "ru")] = [{"id": x["qid"]} for x in c["candidates"]]
        for x in c["candidates"]:
            records[x["qid"]] = record(
                x["qid"], ru=x["label"], classes=HUMAN if x["human"] else ("Q4167410",)
            )
    before = dump(onto.statements.engine)
    events.clear()
    manifest = life(onto, RecordFetch(records, searches)).suggest({"entities": []}, auto_exact=flag)
    assert dump(onto.statements.engine) == before
    by_entity = {e["entity"]: e for e in manifest["entities"]}
    autos = 0
    for c in cases:
        e = by_entity[ids[c["name"]]]
        humans = [x for x in c["candidates"] if x["human"]]
        assert sorted(x["qid"] for x in e["candidates"]) == sorted(x["qid"] for x in humans)
        should = flag and len(humans) == 1 and humans[0]["label"] == c["name"]
        assert (e["decision"] == "auto") == should, (c, flag, e)
        assert e["wikidata"] == (humans[0]["qid"] if should else None)
        autos += should
    assert events.one(SUGGESTED)["auto"] == autos
    # применение: QID только у auto
    life(onto, RecordFetch(records)).apply(manifest)
    externals = onto.entities.externals("wikidata")
    assert set(externals) == {
        ids[c["name"]] for c in cases if by_entity[ids[c["name"]]]["wikidata"]
    }


# =========================== Импорт из Wikidata (ontology-extraction) =====================


@pytest.fixture
def stand(onto, engine_for, clock) -> Stand:
    return Stand(onto, engine_for, clock)


def simple_record(label, **claims):
    return {"labels": {"ru": label}, "claims": {k: v for k, v in claims.items()}}


@req(EX, IMPORT, scenario="Влияние не импортируется")
def test_influence_not_imported(stand, onto, events):
    records = {"Q9312": simple_record("Иммануил Кант", P737=["Q37160"])}
    stand.filling.import_wikidata("Q9312", records.__getitem__)
    kant = onto.entities.by_external("wikidata", "Q9312")
    assert onto.statements.about(kant, types=["influenced_by"]) == []
    assert onto.entities.by_external("wikidata", "Q37160") is None
    assert events.where("knowledge.import.skipped", property="P737")


@req(EX, IMPORT, scenario="Дата до нашей эры")
def test_import_bce(stand, onto, events):
    records = {
        "Q859": simple_record(
            "Платон", P569=["-0427-00-00T00:00:00Z"], P570=["-0347-00-00T00:00:00Z"]
        )
    }
    stand.filling.import_wikidata("Q859", records.__getitem__)
    plato = onto.entities.by_external("wikidata", "Q859")
    d = dates_of(onto, plato)
    assert (d["earliest_start"], d["latest_end"]) == (-426, -346)
    assert events.where("knowledge.statement.created", type="lifespan")


@req(EX, IMPORT, scenario="Одна дата при импорте")
def test_import_one_date(stand, onto, events):
    records = {"Q1": simple_record("Один Человек", P569=["+1600-00-00T00:00:00Z"])}
    stand.filling.import_wikidata("Q1", records.__getitem__)
    one = onto.entities.by_external("wikidata", "Q1")
    assert dates_of(onto, one) is None
    assert onto.statements.about(one, types=["lifespan"]) == []
    assert [
        (e["property"], e["reason"])
        for e in events.of("knowledge.import.skipped")
        if e["reason"] == "partial"
    ] == [("P570", "partial")]


@req(EX, IMPORT, invariant="«−» даёт до н. э.; годы жизни равны разбору общим правилом")
@settings(parent=PROFILES["pure"])
@given(wd_times())
@example(((y("-0427-00-00"), 9), (-426, -426, "year")))
@example(((y("+1724-04-22"), 11), (1724, 1724, "year")))
@example(((y("+1680-00-00"), 8), (1680, 1689, "decade")))
@example(((y("+1801-00-00"), 7), (1801, 1900, "century")))
@example(((y("-0427-00-00"), 7), (-499, -400, "century")))
@example(((y("+1600-00-00"), 6), (1001, 2000, "approx")))
@example(((y("+1600-00-00"), 5), None))
@example(((y("+0000-00-00"), 9), None))
@example((("1724-04-22", 9), None))
def test_time_rule_any_value(case):
    (value, precision), expected = case
    got = wikidata_time(value, precision)
    if expected is None:
        assert got is None, (value, precision)
        return
    assert got is not None, (value, precision)
    assert (got.earliest_start, got.latest_start, got.earliest_end, got.latest_end) == (
        expected[0],
        expected[1],
        expected[0],
        expected[1],
    )
    assert got.precision == expected[2]
    if value.startswith("-"):
        assert got.latest_end <= 0


@req(EX, IMPORT, invariant="Упрощённая запись: «−» ⇒ до н. э., одна дата ⇒ partial")
@CI
@given(
    hst.tuples(hst.sampled_from("+-"), hst.integers(1, 2000)),
    hst.one_of(hst.none(), hst.integers(1, 90)),
)
@example(("-", 427), 80)
@example(("+", 1724), None)
def test_import_invariant(stand, onto, events, birth, life_years):
    wipe(onto)
    events.clear()
    sign, year = birth
    astro_birth = 1 - year if sign == "-" else year
    claims = {"P569": [wd_value(sign, year)]}
    if life_years is not None:
        astro_death = astro_birth + life_years
        d_sign = "-" if astro_death <= 0 else "+"
        d_year = 1 - astro_death if astro_death <= 0 else astro_death
        assume(d_year != 0)
        claims["P570"] = [wd_value(d_sign, d_year)]
    stand.filling.import_wikidata(
        "Q5000", {"Q5000": simple_record("Некто Лицо", **claims)}.__getitem__
    )
    entity = onto.entities.by_external("wikidata", "Q5000")
    d = dates_of(onto, entity)
    partial = [e for e in events.of("knowledge.import.skipped") if e["reason"] == "partial"]
    if life_years is None:
        assert d is None and [e["property"] for e in partial] == ["P570"]
        return
    assert partial == []
    start = wd_bounds(sign, year, 9)[0]
    assert (d["earliest_start"], d["latest_end"]) == (start, astro_birth + life_years)
    if sign == "-":
        assert d["earliest_start"] <= 0
