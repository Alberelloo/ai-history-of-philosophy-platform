"""epochs — «Датировка эпохи», «Даты эпох из Wikidata», «Подбор записи Wikidata», «Ядро эпох»
(add-epochs, задачи 5.1 и 5.2).

Команда оператора запускается как оператор: CLI ``main([...])`` с манифестом во временной
папке, внедрённой загрузкой (``RecordFetch`` — ответы Wikidata задаёт тест) и сервисом на базе
теста. Вывод — утверждения онтологии и отчёт JSON в stdout; журнал —
``knowledge.epoch_dates.*``. Сеть запрещена ловушкой ``no_network``. «Датировка эпохи»
проверяется через ``GET /v1/epochs`` (событие ``knowledge.epochs.listed``).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml
from sqlalchemy import func, select

from philograph.knowledge import schema as t
from philograph.knowledge.dates import FuzzyDate
from philograph.knowledge.epoch_dates import EpochDates, ManifestError, main
from philograph.knowledge.statements import Attribution, Provenance

from .wd_records import (  # noqa: F401  (фикстура no_network)
    FILM,
    PERIOD,
    RecordFetch,
    dated,
    no_network,
    record,
    year,
)

req = pytest.mark.req
EP = "epochs"
DATING = "Датировка эпохи"
FROM_WD = "Даты эпох из Wikidata"
SUGGEST = "Подбор записи Wikidata"
CORE = "Ядро эпох"
CHECKED = "knowledge.epoch_dates.checked"
RUN = "knowledge.epoch_dates.run"
SUGGESTED = "knowledge.epoch_dates.suggested"
LISTED = "knowledge.epochs.listed"
CONTEXT = {"request_id", "run_id", "service"}  # поля контекста, которые журнал добавляет сам

pytestmark = pytest.mark.usefixtures("no_network")


# --- помощники ----------------------------------------------------------------------------


class Operator:
    """Оператор у консоли: манифест в файле, команда ``python -m …epoch_dates``."""

    def __init__(self, onto, tmp_path: Path, capsys) -> None:
        self.onto = onto
        self.path = tmp_path / "epochs.yaml"
        self.capsys = capsys
        self.service_calls = 0

    def manifest(self, *entries: dict, header: str = "") -> None:
        body = yaml.safe_dump({"epochs": list(entries)}, allow_unicode=True, sort_keys=False)
        self.path.write_text(header + body, encoding="utf-8")

    def read(self) -> dict:
        return yaml.safe_load(self.path.read_text(encoding="utf-8"))

    def _service(self) -> EpochDates:
        self.service_calls += 1
        return EpochDates(self.onto.statements, self.onto.entities)

    def run(self, fetch, *args: str) -> tuple[int, dict | None, str]:
        self.capsys.readouterr()
        code = main(
            [args[0], "--manifest", str(self.path), *args[1:]], fetch=fetch, service=self._service
        )
        out, err = self.capsys.readouterr()
        return code, (json.loads(out) if out.strip() else None), err


@pytest.fixture
def op(onto, tmp_path, capsys) -> Operator:
    return Operator(onto, tmp_path, capsys)


def entry(ru: str, en: str | None = None, wikidata: str | None = None, **extra) -> dict:
    return {"ru": ru, "en": en, "wikidata": wikidata, "candidates": [], **extra}


def epoch(onto, name: str, en: str | None = None) -> str:
    names = [("ru", name, "primary")] + ([("en", en, "variant")] if en else [])
    return onto.entities.create("epoch", names)


def dating_of(onto, entity: str, value: dict, *, rank: str | None = None) -> str:
    sid = onto.statements.add(entity, "dating", value=value, attributions=[Attribution("common")])
    if rank:
        onto.statements.set_rank(sid, rank, "operator")
    return sid


def span(a: int, b: int, original: str | None = None) -> dict:
    return FuzzyDate(a, a, b, b, "year", original or f"{a}–{b}").to_json()


def datings(onto, entity: str) -> list[dict]:
    return [
        s
        for s in onto.statements.about(entity, types=["dating"], derived=False)
        if s["direction"] == "out"
    ]


def four(value: dict) -> tuple[int, int, int, int]:
    return (
        value["earliest_start"],
        value["latest_start"],
        value["earliest_end"],
        value["latest_end"],
    )


def rows(onto) -> dict[str, int]:
    """Число строк во всех таблицах онтологии."""
    tables = [tb for tb in t.metadata.sorted_tables if tb.schema == t.SCHEMA]
    with onto.statements.engine.begin() as conn:
        return {tb.name: conn.scalar(select(func.count()).select_from(tb)) for tb in tables}


def run_event(events) -> dict:
    fields = dict(events.one(RUN).fields)
    for key in CONTEXT:
        fields.pop(key, None)
    return fields


def results(events) -> list[str]:
    return [e["result"] for e in events.of(CHECKED)]


def enlightenment_linked(onto) -> str:
    """Данные сценария «Дата из Wikidata»: эпоха без датировки с внешним Q12539."""
    enl = epoch(onto, "Просвещение")
    onto.entities.add_external(enl, "wikidata", "Q12539")
    return enl


def enlightenment_record() -> RecordFetch:
    return RecordFetch({"Q12539": dated("Q12539", year(1685), year(1815), ru="Эпоха Просвещения")})


# --- Датировка эпохи ----------------------------------------------------------------------


def listed(svc) -> dict:
    response, rid = svc.get("/v1/epochs")
    assert response.status_code == 200, response.text
    return response.json(), rid


def by_label(items) -> dict:
    return {e["label"]: e for e in items}


@req(EP, DATING, scenario="Нечёткая граница")
def test_fuzzy_boundary(svc, onto, events):
    ant = epoch(onto, "Античность")
    dating_of(
        onto,
        ant,
        FuzzyDate(-799, -700, 401, 500, "century", "VIII в. до н. э. – V в.").to_json(),
    )
    data, rid = listed(svc)
    item = by_label(data["epochs"])["Античность"]
    assert item["fuzzy"] == {"from": [-799, -700], "to": [401, 500]}
    assert (item["from"], item["to"]) == (-750, 450)
    assert item["precision"] == "century"
    assert item["original"] == "VIII в. до н. э. – V в."
    assert events.where(LISTED, request_id=rid)[0]["epochs"] == 1


@req(EP, DATING, scenario="Предпочтённая датировка")
def test_preferred_dating(svc, onto, events):
    enl = epoch(onto, "Просвещение")
    onto.statements.add(
        enl, "dating", value=span(1680, 1800), attributions=[Attribution("source", "s_textbook")]
    )
    dating_of(onto, enl, span(1715, 1789), rank="preferred")
    data, rid = listed(svc)
    item = by_label(data["epochs"])["Просвещение"]
    assert (item["from"], item["to"]) == (1715, 1789)
    assert events.where(LISTED, request_id=rid)[0]["epochs"] == 1


@req(EP, DATING, scenario="Первая записанная")
def test_first_recorded_dating(svc, onto, events):
    bar = epoch(onto, "Барокко")
    dating_of(onto, bar, span(1600, 1750))
    dating_of(onto, bar, span(1580, 1730))
    data, rid = listed(svc)
    item = by_label(data["epochs"])["Барокко"]
    assert (item["from"], item["to"]) == (1600, 1750)
    assert events.where(LISTED, request_id=rid)[0]["epochs"] == 1


@req(EP, DATING, invariant="основная — первая записанная, а не самая сильная по статусу")
def test_first_recorded_not_strongest(svc, onto, events):
    bar = epoch(onto, "Барокко")
    onto.statements.add(
        bar,
        "dating",
        value=span(1600, 1750),
        attributions=[Attribution("common")],
        provenance=Provenance("generated"),
    )
    onto.statements.add(
        bar, "dating", value=span(1580, 1730), attributions=[Attribution("source", "s_textbook")]
    )
    statuses = [s["status"] for s in datings(onto, bar)]
    assert statuses[0] == "generated" and statuses[1] != "generated"
    data, rid = listed(svc)
    item = by_label(data["epochs"])["Барокко"]
    assert (item["from"], item["to"]) == (1600, 1750)
    assert events.where(LISTED, request_id=rid)[0]["epochs"] == 1


@req(EP, DATING, invariant="основная — предпочтённая, иначе первая из действующих")
@pytest.mark.parametrize("drop", ["reject", "deprecated"])
def test_main_dating_only_from_active(svc, onto, events, drop):
    bar = epoch(onto, "Барокко")
    first = dating_of(onto, bar, span(1600, 1750))
    dating_of(onto, bar, span(1580, 1730))
    if drop == "reject":
        onto.statements.reject(first, "operator")
    else:
        onto.statements.set_rank(first, "deprecated", "operator")
    data, rid = listed(svc)
    item = by_label(data["epochs"])["Барокко"]
    assert (item["from"], item["to"]) == (1580, 1730)
    assert events.where(LISTED, request_id=rid)[0]["epochs"] == 1


SPANS = [
    # границы → (from, to, fuzzy)
    ((1543, 1543, 1687, 1700), (1543, 1694, {"from": [1543, 1543], "to": [1687, 1700]})),
    ((1679, 1680, 1800, 1800), (1680, 1800, {"from": [1679, 1680], "to": [1800, 1800]})),
    ((-399, -300, 0, 99), (-350, 50, {"from": [-399, -300], "to": [0, 99]})),
    ((1600, 1600, 1750, 1750), (1600, 1750, {"from": [1600, 1600], "to": [1750, 1750]})),
]


@req(EP, DATING, invariant="пролёт — середины нечётких границ с округлением; равные — чёткая")
@pytest.mark.parametrize("raw,expected", SPANS, ids=["fuzzy-end", "half-up", "bce", "sharp"])
def test_span_is_rounded_middle(svc, onto, events, raw, expected):
    e = epoch(onto, "Эпоха")
    dating_of(onto, e, FuzzyDate(*raw, "approx", "…").to_json())
    data, rid = listed(svc)
    [item] = data["epochs"]
    assert (item["from"], item["to"], item["fuzzy"]) == expected
    assert events.where(LISTED, request_id=rid)[0]["epochs"] == 1


# --- Даты эпох из Wikidata ----------------------------------------------------------------


@req(EP, FROM_WD, scenario="Дата из Wikidata")
def test_date_from_wikidata(op, onto, events):
    enl = enlightenment_linked(onto)
    op.manifest()
    code, report, _ = op.run(enlightenment_record(), "apply", "--linked")
    assert code == 0
    [d] = datings(onto, enl)
    assert four(d["value"]) == (1685, 1685, 1815, 1815)
    assert d["status"] == "sourced"
    [attribution] = d["attributions"]
    assert (attribution["who_kind"], attribution["who"], attribution["place"]) == (
        "source",
        "wikidata:Q12539",
        "https://www.wikidata.org/wiki/Q12539",
    )
    assert d["provenance"]["method"] == "imported"
    assert d["provenance"]["extra"] == {"wikidata": "Q12539", "properties": ["P580", "P582"]}
    assert onto.entities.externals("wikidata") == {enl: "Q12539"}
    [item] = report["epochs"]
    assert (item["epoch_id"], item["qid"], item["result"]) == (enl, "Q12539", "added")
    checked = events.one(CHECKED)
    assert (checked["epoch_id"], checked["qid"], checked["result"]) == (enl, "Q12539", "added")
    assert run_event(events) == {
        "mode": "apply",
        "checked": 1,
        "added": 1,
        "created": 0,
        "conflicts": 0,
        "skipped": 0,
    }


@req(EP, FROM_WD, scenario="Запасные свойства")
def test_fallback_properties(op, onto, events):
    rev = epoch(onto, "Научная революция")
    fetch = RecordFetch(
        {"Q4692": record("Q4692", times={"P571": (year(1543), 9), "P576": (year(1687), 9)})}
    )
    op.manifest(entry("Научная революция", wikidata="Q4692"))
    code, report, _ = op.run(fetch, "apply")
    assert code == 0
    [d] = datings(onto, rev)
    assert four(d["value"]) == (1543, 1543, 1687, 1687)
    assert d["provenance"]["extra"]["properties"] == ["P571", "P576"]
    assert report["epochs"][0]["result"] == "added"
    assert events.one(CHECKED)["result"] == "added"


@req(EP, FROM_WD, invariant="P580/P582, если их нет — P571/P576; без начала или конца — no_dates")
@pytest.mark.parametrize(
    "times,expected",
    [
        ({"P580": (year(1600), 9), "P582": (year(1700), 9), "P571": (year(1), 9)}, (1600, 1700)),
        ({"P580": (year(1600), 9)}, None),
        ({"P582": (year(1700), 9)}, None),
        ({"P571": (year(1543), 9)}, None),
        ({}, None),
    ],
    ids=["main-wins", "start-only", "end-only", "founded-only", "none"],
)
def test_property_choice(op, onto, events, times, expected):
    rev = epoch(onto, "Научная революция")
    op.manifest(entry("Научная революция", wikidata="Q4692"))
    op.run(RecordFetch({"Q4692": record("Q4692", times=times)}), "apply")
    if expected is None:
        assert results(events) == ["no_dates"]
        assert datings(onto, rev) == []
    else:
        assert results(events) == ["added"]
        [d] = datings(onto, rev)
        assert (d["value"]["earliest_start"], d["value"]["latest_end"]) == expected
        assert d["provenance"]["extra"]["properties"] == ["P580", "P582"]


@req(EP, FROM_WD, scenario="Датировка уже есть")
def test_existing_dating_kept(op, onto, events):
    rev = epoch(onto, "Научная революция")
    onto.statements.add(
        rev, "dating", value=span(1543, 1687), attributions=[Attribution("source", "s_textbook")]
    )
    fetch = RecordFetch({"Q4692": dated("Q4692", year(1550), year(1700))})
    op.manifest(entry("Научная революция", wikidata="Q4692"))
    code, report, _ = op.run(fetch, "apply")
    assert code == 0
    [d] = datings(onto, rev)
    assert four(d["value"]) == (1543, 1543, 1687, 1687)
    [item] = report["epochs"]
    assert item["result"] == "conflict"
    shown = {four(v) for v in (item["existing"], item["dating"])}
    assert shown == {(1543, 1543, 1687, 1687), (1550, 1550, 1700, 1700)}
    assert events.one(CHECKED)["result"] == "conflict"
    assert run_event(events)["conflicts"] == 1


@req(EP, FROM_WD, scenario="Повторный запуск")
def test_repeated_run(op, onto, events):
    enl = enlightenment_linked(onto)
    op.manifest()
    op.run(enlightenment_record(), "apply", "--linked")
    before = rows(onto)
    events.clear()
    code, report, _ = op.run(enlightenment_record(), "apply", "--linked")
    assert code == 0
    assert rows(onto) == before
    assert len(datings(onto, enl)) == 1
    assert report["epochs"][0]["result"] == "unchanged"
    assert results(events) == ["unchanged"]
    assert run_event(events)["skipped"] == 1
    events.assert_none("knowledge.statement.created")
    events.assert_none("knowledge.entity.created")


@req(EP, FROM_WD, scenario="Проверка без записи")
def test_dry_run(op, onto, events):
    enl = enlightenment_linked(onto)
    op.manifest()
    before = rows(onto)
    events.clear()
    code, report, _ = op.run(enlightenment_record(), "apply", "--linked", "--dry-run")
    assert code == 0
    assert rows(onto) == before
    assert datings(onto, enl) == []
    assert report["epochs"][0]["result"] == "added"
    run = run_event(events)
    assert (run["mode"], run["added"]) == ("dry_run", 1)
    events.assert_none("knowledge.statement.created")


@req(EP, FROM_WD, invariant="--dry-run не меняет ни одной таблицы")
def test_dry_run_changes_no_table_for_any_result(op, onto, events):
    """Все виды результата в одном запуске проверки — ни одна таблица не изменилась."""
    data = mixed_world(onto)
    op.manifest(*data["manifest"])
    before = rows(onto)
    events.clear()
    code, report, _ = op.run(data["fetch"], "apply", "--linked", "--dry-run")
    assert code == 0
    assert rows(onto) == before
    assert sorted(results(events)) == sorted(data["expected"].values())
    events.assert_none("knowledge.statement.created")
    events.assert_none("knowledge.entity.created")
    assert run_event(events)["mode"] == "dry_run"
    assert {e["label"]: e["result"] for e in report["epochs"]} == data["expected"]


@req(EP, FROM_WD, scenario="Без QID")
def test_without_qid(op, onto, events):
    bar = epoch(onto, "Барокко")
    fetch = RecordFetch()
    op.manifest(entry("Барокко", "Baroque", None))
    code, report, _ = op.run(fetch, "apply")
    assert code == 0
    assert fetch.calls == []
    assert report["epochs"][0]["result"] == "no_qid"
    checked = events.one(CHECKED)
    assert (checked["epoch_id"], checked["qid"], checked["result"]) == (bar, None, "no_qid")


@req(EP, FROM_WD, invariant="без QID — ни одного вызова загрузки")
@pytest.mark.parametrize("linked", [False, True])
def test_no_qid_never_fetches(op, onto, events, linked):
    epoch(onto, "Барокко")
    epoch(onto, "Маньеризм")  # в базе, без внешнего идентификатора, не в манифесте
    events.clear()
    fetch = RecordFetch()
    op.manifest(entry("Барокко", None, None), entry("Рококо", "Rococo", None))
    op.run(fetch, "apply", *(["--linked"] if linked else []))
    assert fetch.calls == []
    assert results(events) == ["no_qid", "no_qid"]
    events.assert_none("knowledge.entity.created")  # «Рококо» без QID не заводится


@req(EP, FROM_WD, scenario="Сбой загрузки и одинаковый QID")
def test_fetch_failed_and_duplicate_qid(op, onto, events):
    epoch(onto, "Античность")
    epoch(onto, "Средние века")
    mid = epoch(onto, "Возрождение")
    person = onto.entities.create("person", [("ru", "Николай Кузанский", "primary")])
    onto.entities.add_external(person, "wikidata", "Q900002")
    fetch = RecordFetch(
        {
            "Q900002": dated("Q900002", year(500), year(1500)),
            "Q900003": dated("Q900003", year(1400), year(1600)),
        },
        failing={"Q900001"},
    )
    op.manifest(
        entry("Античность", wikidata="Q900001"),
        entry("Средние века", wikidata="Q900002"),
        entry("Возрождение", wikidata="Q900003"),
    )
    code, report, _ = op.run(fetch, "apply")
    assert code == 0
    assert [e["result"] for e in report["epochs"]] == ["fetch_failed", "duplicate_qid", "added"]
    assert results(events) == ["fetch_failed", "duplicate_qid", "added"]
    run = run_event(events)
    assert (run["checked"], run["added"], run["skipped"]) == (3, 1, 2)
    assert onto.entities.by_external("wikidata", "Q900002") == person  # не перенесён
    assert [four(d["value"]) for d in datings(onto, mid)] == [(1400, 1400, 1600, 1600)]


@req(
    EP,
    FROM_WD,
    invariant="added: сущность получает внешний идентификатор Wikidata, если его не было",
)
def test_added_from_manifest_gets_external_id(op, onto, events):
    mid = epoch(onto, "Возрождение")
    assert onto.entities.externals("wikidata") == {}
    fetch = RecordFetch({"Q900003": dated("Q900003", year(1400), year(1600))})
    op.manifest(entry("Возрождение", wikidata="Q900003"))
    code, report, _ = op.run(fetch, "apply")
    assert code == 0
    assert [e["result"] for e in report["epochs"]] == ["added"]
    assert onto.entities.by_external("wikidata", "Q900003") == mid
    assert [four(d["value"]) for d in datings(onto, mid)] == [(1400, 1400, 1600, 1600)]


def mixed_world(onto) -> dict:
    """По одной эпохе на каждый ``result`` таблицы требования."""
    added = epoch(onto, "Просвещение")
    unchanged = epoch(onto, "Научная революция")
    dating_of(onto, unchanged, FuzzyDate(1543, 1543, 1687, 1687, "year", "1543–1687").to_json())
    conflict = epoch(onto, "Барокко")
    dating_of(onto, conflict, span(1600, 1750))
    epoch(onto, "Схоластика")  # no_dates
    epoch(onto, "Античность")  # no_qid
    epoch(onto, "Средние века")  # fetch_failed
    epoch(onto, "Новое время")
    epoch(onto, "Новое время")  # ambiguous
    epoch(onto, "Возрождение")  # duplicate_qid
    person = onto.entities.create("person", [("ru", "Эразм", "primary")])
    onto.entities.add_external(person, "wikidata", "Q8")
    linked = epoch(onto, "Романтизм")  # --linked: в базе с QID, не в манифесте
    onto.entities.add_external(linked, "wikidata", "Q9")
    fetch = RecordFetch(
        {
            "Q1": dated("Q1", year(1685), year(1815)),
            "Q2": dated("Q2", year(1543), year(1687)),
            "Q3": dated("Q3", year(1580), year(1730)),
            "Q4": record("Q4", times={"P580": (year(1100), 9)}),
            "Q7": dated("Q7", year(1500), year(1800)),
            "Q8": dated("Q8", year(1400), year(1600)),
            "Q9": dated("Q9", year(1790), year(1850)),
            "Q10": dated("Q10", year(1789), year(1914)),
        },
        failing={"Q6"},
    )
    manifest = [
        entry("Просвещение", wikidata="Q1"),
        entry("Научная революция", wikidata="Q2"),
        entry("Барокко", wikidata="Q3"),
        entry("Схоластика", wikidata="Q4"),
        entry("Античность", wikidata=None),
        entry("Средние века", wikidata="Q6"),
        entry("Новое время", wikidata="Q7"),
        entry("Возрождение", wikidata="Q8"),
        entry("Долгий XIX век", "Long nineteenth century", "Q10"),  # created
    ]
    expected = {
        "Просвещение": "added",
        "Научная революция": "unchanged",
        "Барокко": "conflict",
        "Схоластика": "no_dates",
        "Античность": "no_qid",
        "Средние века": "fetch_failed",
        "Новое время": "ambiguous",
        "Возрождение": "duplicate_qid",
        "Долгий XIX век": "created",
        "Романтизм": "added",
    }
    return {"manifest": manifest, "fetch": fetch, "expected": expected, "added": added}


@req(
    EP, FROM_WD, invariant="каждый result таблицы; checked = added + created + conflicts + skipped"
)
def test_every_result_and_totals(op, onto, events):
    data = mixed_world(onto)
    op.manifest(*data["manifest"])
    code, report, _ = op.run(data["fetch"], "apply", "--linked")
    assert code == 0
    assert {e["label"]: e["result"] for e in report["epochs"]} == data["expected"]
    assert sorted(results(events)) == sorted(data["expected"].values())
    run = run_event(events)
    assert run == {
        "mode": "apply",
        "checked": 10,
        "added": 2,
        "created": 1,
        "conflicts": 1,
        "skipped": 6,
    }
    assert run["checked"] == run["added"] + run["created"] + run["conflicts"] + run["skipped"]
    ambiguous = events.where(CHECKED, result="ambiguous")[0]
    assert ambiguous["epoch_id"] is None


@req(EP, FROM_WD, invariant="существующая датировка никогда не перезаписывается")
@pytest.mark.parametrize(
    "existing,rank,expected",
    [
        ((1543, 1687), None, "conflict"),
        ((1550, 1700), None, "unchanged"),
        ((1543, 1687), "preferred", "conflict"),
    ],
    ids=["differs", "same", "preferred"],
)
def test_existing_never_overwritten(op, onto, events, existing, rank, expected):
    rev = epoch(onto, "Научная революция")
    sid = dating_of(onto, rev, span(*existing), rank=rank)
    before = onto.statements.get(sid)
    fetch = RecordFetch({"Q4692": dated("Q4692", year(1550), year(1700))})
    op.manifest(entry("Научная революция", wikidata="Q4692"))
    events.clear()
    op.run(fetch, "apply")
    op.run(fetch, "apply")  # и при повторе
    after = datings(onto, rev)
    assert [d["id"] for d in after] == [sid]
    assert onto.statements.get(sid)["value"] == before["value"]
    assert onto.statements.get(sid)["attributions"] == before["attributions"]
    assert onto.entities.get(rev)["primary"]["dates"] == before["value"]
    assert results(events) == [expected, expected]
    events.assert_none("knowledge.statement.created")


@req(EP, FROM_WD, invariant="только действующая датировка останавливает запись")
@pytest.mark.parametrize("drop", ["reject", "deprecated"])
def test_inactive_dating_does_not_block(op, onto, events, drop):
    rev = epoch(onto, "Научная революция")
    old = dating_of(onto, rev, span(1500, 1600))
    if drop == "reject":
        onto.statements.reject(old, "operator")
    else:
        onto.statements.set_rank(old, "deprecated", "operator")
    op.manifest(entry("Научная революция", wikidata="Q4692"))
    op.run(RecordFetch({"Q4692": dated("Q4692", year(1550), year(1700))}), "apply")
    assert results(events) == ["added"]
    assert [four(d["value"]) for d in datings(onto, rev)] == [(1550, 1550, 1700, 1700)]


@req(EP, FROM_WD, invariant="повторный apply не создаёт строк")
def test_repeated_apply_creates_no_rows(op, onto, events):
    data = mixed_world(onto)
    op.manifest(*data["manifest"])
    op.run(data["fetch"], "apply", "--linked")
    first = rows(onto)
    events.clear()
    op.run(data["fetch"], "apply", "--linked")
    assert rows(onto) == first
    events.assert_none("knowledge.statement.created")
    events.assert_none("knowledge.entity.created")
    again = {e["epoch_id"]: e["result"] for e in events.of(CHECKED) if e["epoch_id"]}
    assert "added" not in again.values() and "created" not in again.values()
    assert run_event(events)["added"] == 0 and run_event(events)["created"] == 0


@req(EP, FROM_WD, invariant="связи влияния из Wikidata не импортируются")
def test_influences_not_imported(op, onto, events):
    enlightenment_linked(onto)
    voltaire = onto.entities.create("person", [("ru", "Вольтер", "primary")])
    onto.entities.add_external(voltaire, "wikidata", "Q9068")
    locke = onto.entities.create("person", [("ru", "Локк", "primary")])
    onto.entities.add_external(locke, "wikidata", "Q9353")
    fetch = RecordFetch(
        {
            "Q12539": record(
                "Q12539",
                times={"P580": (year(1685), 9), "P582": (year(1815), 9)},
                items={"P737": ["Q9353"], "P710": ["Q9068"], "P1269": ["Q9068"]},
            )
        }
    )
    op.manifest()
    before = rows(onto)
    events.clear()
    op.run(fetch, "apply", "--linked")
    with onto.statements.engine.begin() as conn:
        types = list(conn.scalars(select(t.statements.c.type)))
    assert types == ["dating"]
    assert rows(onto)["entities"] == before["entities"]
    assert [c for c in fetch.calls if "Q9353" in c or "Q9068" in c] == []  # и не загружаются
    assert onto.statements.about(locke, derived=False) == []
    assert results(events) == ["added"]
    assert len(events.of("knowledge.statement.created")) == 1


ID = re.compile(r"^e_[0-9a-f]+$")
QID = re.compile(r"^Q\d+$")


def _only_ids_codes_numbers(event, spec: dict) -> None:
    fields = {k: v for k, v in event.fields.items() if k not in CONTEXT}
    assert set(fields) == set(spec), (event.name, fields)
    for key, kind in spec.items():
        value = fields[key]
        if kind == "id":
            assert value is None or (isinstance(value, str) and ID.fullmatch(value)), (key, value)
        elif kind == "qid":
            assert value is None or (isinstance(value, str) and QID.fullmatch(value)), (key, value)
        elif kind == "int":
            assert isinstance(value, int) and not isinstance(value, bool), (key, value)
        elif kind == "bool":
            assert isinstance(value, bool), (key, value)
        else:
            assert value in kind, (key, value)


@req(EP, FROM_WD, invariant="события knowledge.epoch_dates.* — только id, коды и числа")
def test_events_only_ids_codes_numbers(op, onto, events, svc):
    data = mixed_world(onto)
    op.manifest(*data["manifest"])
    op.run(data["fetch"], "apply", "--linked")
    results_codes = {
        "added",
        "created",
        "unchanged",
        "conflict",
        "no_dates",
        "no_qid",
        "fetch_failed",
        "ambiguous",
        "duplicate_qid",
    }
    checked = events.of(CHECKED)
    assert len(checked) == 10
    for e in checked:
        _only_ids_codes_numbers(e, {"epoch_id": "id", "qid": "qid", "result": results_codes})
    numbers = {k: "int" for k in ("checked", "added", "created", "conflicts", "skipped")}
    _only_ids_codes_numbers(events.one(RUN), {"mode": {"apply", "dry_run"}, **numbers})
    op.manifest(entry("Рококо", "Rococo", None))
    op.run(RecordFetch(), "suggest")
    _only_ids_codes_numbers(events.one(SUGGESTED), {"epochs": "int", "candidates": "int"})
    response, rid = svc.get("/v1/epochs")
    assert response.status_code == 200
    [listed_event] = events.where(LISTED, request_id=rid)
    fields = {k: v for k, v in listed_event.fields.items() if k not in CONTEXT}
    assert set(fields) == {"epochs", "undated", "truncated", "snapshot"}
    assert isinstance(fields["epochs"], int) and isinstance(fields["undated"], int)
    assert isinstance(fields["truncated"], bool)
    assert isinstance(fields["snapshot"], str) and re.fullmatch(r"[a-z_]+", fields["snapshot"])
    # Ни названия, ни текста записи Wikidata в журнале.
    dump = json.dumps([e.fields for e in events.items], ensure_ascii=False)
    for text in ("Просвещение", "Барокко", "Долгий XIX век", "Rococo"):
        assert text not in "".join(
            json.dumps(e.fields, ensure_ascii=False)
            for e in events.items
            if e.name.startswith("knowledge.epoch")
        ), text
    assert dump


# --- Подбор записи Wikidata ---------------------------------------------------------------


def baroque_search() -> RecordFetch:
    hits = [
        {"id": "Q37853", "label": "барокко", "description": "период в искусстве"},
        {"id": "Q900010", "label": "Барокко", "description": "фильм"},
    ]
    return RecordFetch(
        {
            "Q37853": record(
                "Q37853",
                ru="барокко",
                description="период в искусстве",
                times={"P580": (year(1600), 9), "P582": (year(1750), 9)},
            ),
            "Q900010": record(
                "Q900010",
                ru="Барокко",
                description="фильм",
                classes=(FILM,),
                times={"P577": (year(1999), 9)},
            ),
        },
        searches={("Барокко", "ru"): hits, ("Baroque", "en"): hits},
    )


@req(EP, SUGGEST, scenario="Кандидаты без применения")
def test_candidates_without_applying(op, onto, events):
    epoch(onto, "Барокко")
    op.manifest(entry("Барокко", "Baroque", None))
    before = rows(onto)
    events.clear()
    code, _out, _ = op.run(baroque_search(), "suggest")
    assert code == 0
    [bar] = op.read()["epochs"]
    assert bar["wikidata"] is None
    [candidate] = bar["candidates"]
    assert set(candidate) == {"qid", "label", "description", "start", "end"}
    assert candidate["qid"] == "Q37853"
    assert candidate["start"] and candidate["end"]
    assert rows(onto) == before
    assert op.service_calls == 0  # подбор не открывает базу
    event = events.one(SUGGESTED)
    assert (event["epochs"], event["candidates"]) == (1, 1)
    events.assert_none(CHECKED)


@req(EP, SUGGEST, scenario="Повторный подбор")
def test_repeated_suggest(op, onto, events):
    op.manifest(entry("Барокко", "Baroque", "Q37853", comment="подтвердил по статье"))
    fetch = baroque_search()
    code, _, _ = op.run(fetch, "suggest")
    assert code == 0
    assert fetch.calls == []  # «Барокко» не ищется
    [bar] = op.read()["epochs"]
    assert bar["wikidata"] == "Q37853"
    assert bar["comment"] == "подтвердил по статье"
    assert events.one(SUGGESTED)["epochs"] == 0


@req(EP, SUGGEST, invariant="кандидаты объединяются по qid, поля человека не меняются")
def test_suggest_merges_by_qid_and_keeps_fields(op, onto, events):
    old = {"qid": "Q37853", "label": "старое", "description": None, "start": "1601", "end": None}
    other = {"qid": "Q1", "label": "другое", "description": None, "start": "1600", "end": None}
    op.manifest(
        entry("Барокко", "Baroque", None, candidates=[old, other], note="проверить даты"),
        header="# Эпохи раздела.\n",
    )
    op.run(baroque_search(), "suggest")
    op.run(baroque_search(), "suggest")  # и повтор не дублирует
    [bar] = op.read()["epochs"]
    assert [c["qid"] for c in bar["candidates"]] == ["Q37853", "Q1"]
    assert bar["candidates"][1] == other
    assert (bar["ru"], bar["en"], bar["wikidata"], bar["note"]) == (
        "Барокко",
        "Baroque",
        None,
        "проверить даты",
    )
    assert [e["candidates"] for e in events.of(SUGGESTED)] == [2, 2]


@req(EP, SUGGEST, invariant="только классы периодов с датой начала или конца")
@pytest.mark.parametrize(
    "classes,times,kept",
    [
        ((PERIOD,), {"P580": (year(1600), 9)}, True),
        ((PERIOD,), {"P582": (year(1750), 9)}, True),
        ((PERIOD,), {"P571": (year(1600), 9)}, True),
        ((PERIOD,), {}, False),
        ((FILM,), {"P580": (year(1600), 9), "P582": (year(1750), 9)}, False),
        ((), {"P580": (year(1600), 9)}, False),
    ],
    ids=["start", "end", "founded", "no-dates", "film", "no-class"],
)
def test_candidate_filter(op, onto, events, classes, times, kept):
    fetch = RecordFetch(
        {"Q5": record("Q5", ru="барокко", classes=classes, times=times)},
        searches={("Барокко", "ru"): [{"id": "Q5", "label": "барокко", "description": ""}]},
    )
    op.manifest(entry("Барокко", None, None))
    before = rows(onto)
    op.run(fetch, "suggest")
    [bar] = op.read()["epochs"]
    assert [c["qid"] for c in bar["candidates"]] == (["Q5"] if kept else [])
    assert bar["wikidata"] is None
    assert rows(onto) == before
    assert events.one(SUGGESTED)["candidates"] == (1 if kept else 0)


@req(EP, SUGGEST, invariant="suggest не пишет в базу и не заполняет wikidata")
def test_suggest_never_writes(op, onto, events):
    epoch(onto, "Барокко")
    op.manifest(entry("Барокко", "Baroque", None))
    before = rows(onto)
    events.clear()
    op.run(baroque_search(), "suggest")
    assert rows(onto) == before
    assert op.service_calls == 0
    assert op.read()["epochs"][0]["wikidata"] is None  # и при единственном кандидате
    events.assert_none("knowledge.statement.created")
    events.assert_none("knowledge.entity.created")
    assert events.one(SUGGESTED)["candidates"] == 1


# --- Ядро эпох ----------------------------------------------------------------------------


@req(EP, CORE, scenario="Новая эпоха из манифеста")
def test_new_epoch_from_manifest(op, onto, events):
    fetch = RecordFetch({"Q4692": dated("Q4692", year(1400), year(1600))})
    op.manifest(entry("Возрождение", "Renaissance", "Q4692"))
    code, report, _ = op.run(fetch, "apply")
    assert code == 0
    found = [e for e in onto.entities.find("Возрождение") if e["type"] == "epoch"]
    assert len(found) == 1
    new = onto.entities.get(found[0]["id"])
    assert {(n["lang"], n["text"], n["kind"]) for n in new["names"]} == {
        ("ru", "Возрождение", "primary"),
        ("en", "Renaissance", "variant"),
    }
    assert onto.entities.externals("wikidata") == {new["id"]: "Q4692"}
    assert [four(d["value"]) for d in datings(onto, new["id"])] == [(1400, 1400, 1600, 1600)]
    created = events.one("knowledge.entity.created")
    assert (created["entity_id"], created["type"]) == (new["id"], "epoch")
    checked = events.one(CHECKED)
    assert (checked["epoch_id"], checked["result"]) == (new["id"], "created")
    assert report["epochs"][0]["result"] == "created"
    assert run_event(events)["created"] == 1


@req(EP, CORE, scenario="Две одноимённые эпохи")
def test_two_epochs_same_name(op, onto, events):
    a = epoch(onto, "Новое время")
    b = epoch(onto, "Новое время")
    op.manifest(entry("Новое время", "Modern era", "Q7"))
    before = rows(onto)
    op.run(RecordFetch({"Q7": dated("Q7", year(1500), year(1800))}), "apply")
    assert rows(onto) == before
    assert datings(onto, a) == [] and datings(onto, b) == []
    assert onto.entities.externals("wikidata") == {}
    checked = events.one(CHECKED)
    assert (checked["epoch_id"], checked["result"]) == (None, "ambiguous")


@req(EP, CORE, scenario="Неверный манифест")
def test_bad_manifest(op, onto, events):
    fetch = RecordFetch({"Q12539": dated("Q12539", year(1685), year(1815))})
    op.manifest(entry("Просвещение", wikidata="Q12539"), entry("Просвещение", wikidata=None))
    code, report, err = op.run(fetch, "apply")
    assert code != 0 and report is None and err.strip()
    assert fetch.calls == []
    assert op.service_calls == 0  # до обращения к базе
    assert [e for e in events.names() if e.startswith("knowledge.epoch_dates.")] == []
    with pytest.raises(ManifestError):
        EpochDates(onto.statements, onto.entities).apply(op.read(), fetch)
    assert fetch.calls == []
    assert [e for e in events.names() if e.startswith("knowledge.epoch_dates.")] == []


@req(EP, CORE, invariant="манифест с повтором ru или QID не по шаблону отклоняется до базы и сети")
@pytest.mark.parametrize(
    "entries",
    [
        [entry("Просвещение"), entry("Просвещение", "Enlightenment")],
        [entry("Просвещение"), entry(" Просвещение ")],
        [entry("Просвещение", wikidata="Q12539/../../w/api.php")],
        [entry("Просвещение", wikidata="12539")],
        [entry("Просвещение", wikidata="q12539")],
        [entry("Просвещение", wikidata="Q12539 ")],
        [entry("Просвещение", wikidata=12539)],
    ],
    ids=["ru-repeat", "ru-repeat-spaces", "path", "digits", "lower", "space", "int"],
)
@pytest.mark.parametrize("command", ["apply", "suggest"])
def test_bad_manifest_rejected_first(op, onto, events, entries, command):
    fetch = RecordFetch({"Q12539": dated("Q12539", year(1685), year(1815))})
    op.manifest(*entries)
    before_text = op.path.read_text(encoding="utf-8")
    code, out, err = op.run(fetch, command)
    assert code != 0 and out is None and err.strip()
    assert fetch.calls == [] and op.service_calls == 0
    assert op.path.read_text(encoding="utf-8") == before_text  # манифест не переписан
    assert [e for e in events.names() if e.startswith("knowledge.epoch_dates.")] == []


@req(EP, CORE, invariant="сопоставление с единственной эпохой по названию или варианту")
def test_match_by_variant_and_only_epochs(op, onto, events):
    enl = epoch(onto, "Эпоха Просвещения", en="Age of Enlightenment")
    group = onto.entities.create("group", [("ru", "Возрождение", "primary")])  # не эпоха
    fetch = RecordFetch(
        {
            "Q12539": dated("Q12539", year(1685), year(1815)),
            "Q4692": dated("Q4692", year(1400), year(1600)),
        }
    )
    op.manifest(
        entry("Просвещение", "Age of Enlightenment", "Q12539"),
        entry("Возрождение", "Renaissance", "Q4692"),
    )
    events.clear()
    op.run(fetch, "apply")
    assert results(events) == ["added", "created"]
    assert [four(d["value"]) for d in datings(onto, enl)] == [(1685, 1685, 1815, 1815)]
    assert datings(onto, group) == []
    created = events.one("knowledge.entity.created")
    assert created["type"] == "epoch" and created["entity_id"] != group


@req(EP, CORE, invariant="эпоха из манифеста без датировки Wikidata не заводится")
@pytest.mark.parametrize("failure", ["no_dates", "fetch_failed"])
def test_not_created_without_dating(op, onto, events, failure):
    fetch = RecordFetch(
        {"Q4692": record("Q4692", times={"P580": (year(1400), 9)})},
        failing={"Q4692"} if failure == "fetch_failed" else (),
    )
    op.manifest(entry("Возрождение", "Renaissance", "Q4692"))
    before = rows(onto)
    op.run(fetch, "apply")
    assert rows(onto) == before
    assert results(events) == [failure]
    events.assert_none("knowledge.entity.created")


@req(EP, FROM_WD, invariant="только подтверждённый QID; второй QID эпохе не записывается")
@pytest.mark.parametrize("dry", [False, True], ids=["apply", "dry_run"])
def test_manifest_qid_differs_from_epoch_qid(op, onto, events, dry):
    """У эпохи уже внешний QID, в манифесте — другой: ни датировки, ни второго QID;
    код результата — ``duplicate_qid`` (таблица ``result``: запись «нет»)."""
    enl = epoch(onto, "Просвещение")
    onto.entities.add_external(enl, "wikidata", "Q12539")
    fetch = RecordFetch(
        {
            "Q12539": dated("Q12539", year(1685), year(1815)),
            "Q999": dated("Q999", year(1700), year(1790)),
        }
    )
    op.manifest(entry("Просвещение", wikidata="Q999"))
    before = rows(onto)
    events.clear()
    code, report, _ = op.run(fetch, "apply", *(["--dry-run"] if dry else []))
    assert code == 0
    assert rows(onto) == before
    assert datings(onto, enl) == []
    assert onto.entities.externals("wikidata") == {enl: "Q12539"}
    assert onto.entities.by_external("wikidata", "Q999") is None
    [item] = report["epochs"]
    assert (item["epoch_id"], item["result"]) == (enl, "duplicate_qid")
    checked = events.one(CHECKED)
    assert (checked["epoch_id"], checked["qid"], checked["result"]) == (
        enl,
        "Q999",
        "duplicate_qid",
    )
    run = run_event(events)
    assert (run["checked"], run["added"], run["skipped"]) == (1, 0, 1)
    events.assert_none("knowledge.statement.created")
