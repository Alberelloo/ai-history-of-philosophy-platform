"""Журнал команд оператора при настоящем запуске (О35, Д4-mig; правило судьи).

Каждая команда запускается отдельным процессом ``python -m philograph.knowledge.<команда>``
на синтетической SQLite. События спецификации ждём в stderr (строки JSON журнала), stdout —
отчёт, который разбирается как JSON. Фикстура ``events`` здесь не участвует: приёмник
журнала подключает сама команда.

Сеть закрыта: команды с ``--from-file`` читают записи из файла, остальным процесс подменяет
``wikidata.http_fetch`` до запуска модуля (``runpy``), а ``__main__`` модуля исполняется
как при запуске командой.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from philograph.knowledge.statements import Attribution

from .migration_world import add_statement, raw_entity
from .test_epoch_context_import import EPOCHS_YAML, REVOLUTION
from .test_geo_enrich import KANT_Q, kant_records
from .test_life_dates import PLATO

req = pytest.mark.req
ROOT = Path(__file__).resolve().parents[2]
OM, MIG, RB, QM = (
    "ontology-migration",
    "Миграция существующей онтологии",
    "Откат миграции",
    "Замер качества онтологии",
)

# Подмена сети в процессе команды: ``FETCH`` — выражение, дающее загрузку ``url → ответ``.
NO_NET = "lambda url: (_ for _ in ()).throw(WikidataError('сеть закрыта в тесте'))"
PRELUDE = """
import runpy, sys
import philograph.knowledge.wikidata as _w
from philograph.knowledge.wikidata import WikidataError
{setup}
_fetch = {fetch}
_w.http_fetch = lambda url, **_k: _fetch(url)
sys.argv = [{module!r}, *{argv!r}]
runpy.run_module({module!r}, run_name="__main__", alter_sys=True)
"""


def command(
    module: str, argv: list[str], database_url: str, *, fetch: str = NO_NET, setup: str = ""
) -> tuple[int, str, list[dict[str, Any]], str]:
    """Код, stdout, события журнала из stderr и прочий stderr."""
    code = PRELUDE.format(
        setup=setup, fetch=fetch, module=f"philograph.knowledge.{module}", argv=argv
    )
    env = {
        **os.environ,
        "PHILOGRAPH_DATABASE_URL": database_url,
        "PYTHONPATH": os.pathsep.join([str(ROOT / "src"), str(ROOT)]),
    }
    r = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
    )
    journal, other = [], []
    for line in r.stderr.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            other.append(line)
            continue
        if isinstance(row, dict) and "event" in row:
            journal.append(row)
        else:
            other.append(line)
    return r.returncode, r.stdout, journal, "\n".join(other)


def names(journal: list[dict[str, Any]]) -> list[str]:
    return [e["event"] for e in journal]


def one(journal: list[dict[str, Any]], name: str) -> dict[str, Any]:
    found = [e for e in journal if e["event"] == name]
    assert len(found) == 1, (name, names(journal))
    return found[0]


def report_of(stdout: str) -> dict[str, Any]:
    """stdout — ровно JSON отчёта: ни строк журнала, ни другого текста."""
    return json.loads(stdout)


# --- ontology_migrate -------------------------------------------------------------------


STEPS = [
    "normalize_names",
    "manifest_qids",
    "lang_fix",
    "retire",
    "wikidata_labels",
    "translate",
    "dedupe",
    "verify",
]


def _seed_migration(onto) -> dict[str, str]:
    garbage = raw_entity(onto, "concept", [("en", "20.1", "primary")])
    b1 = raw_entity(onto, "person", [("en", "Berkeley", "primary")])
    b2 = raw_entity(onto, "person", [("en", "Berkeley", "primary")])
    kant = raw_entity(onto, "person", [("ru", "Кант", "primary")])
    add_statement(onto, kant, "studied_with", b1, [Attribution("source", "s_only")])
    return {"garbage": garbage, "b1": b1, "b2": b2, "kant": kant}


@req(OM, MIG, invariant="Команда пишет журнал: plan и run — step по шагам и run, stdout — JSON")
def test_migrate_plan_and_run_journal(onto, database_url):
    ids = _seed_migration(onto)
    code, out, journal, err = command("ontology_migrate", ["plan"], database_url)
    assert code == 0, err
    plan = report_of(out)
    steps = [e for e in journal if e["event"] == "knowledge.migration.step"]
    assert [e["step"] for e in steps] == STEPS, names(journal)
    assert all(e["dry_run"] is True and e["run_id"] == plan["run_id"] for e in steps)
    assert one(journal, "knowledge.migration.run")["dry_run"] is True

    code, out, journal, err = command("ontology_migrate", ["run"], database_url)
    assert code == 0, err
    run = report_of(out)
    steps = [e for e in journal if e["event"] == "knowledge.migration.step"]
    assert [e["step"] for e in steps] == STEPS, names(journal)
    assert one(journal, "knowledge.migration.run")["run_id"] == run["run_id"]
    retired = one(journal, "knowledge.entity.retired")
    assert (retired["entity_id"], retired["reason"]) == (ids["garbage"], "number")
    assert "knowledge.entity.merged" in names(journal)

    code, out, journal, err = command("ontology_migrate", ["rollback", run["run_id"]], database_url)
    assert code == 0, err
    report_of(out)
    assert one(journal, "knowledge.migration.rolled_back")["run_id"] == run["run_id"]
    assert one(journal, "knowledge.entity.restored")["entity_id"] == ids["garbage"]


LOSSY = """
from sqlalchemy import delete, select
from philograph.knowledge import schema as _t
from philograph.knowledge.statements import Statements as _S
_orig = _S.merge_entities
def _lossy(self, kept, removed, **kw):
    result = _orig(self, kept, removed, **kw)
    with self.engine.begin() as conn:
        row = conn.execute(select(_t.attributions).where(_t.attributions.c.who == "s_only")).first()
        if row is not None:
            conn.execute(delete(_t.attributions).where(_t.attributions.c.id == row.id))
    return result
_S.merge_entities = _lossy
"""

BROKEN = """
from philograph.knowledge.statements import Statements as _S
def _broken(self, kept, removed, **kw):
    raise RuntimeError("сбой слияния (тест)")
_S.merge_entities = _broken
"""


@req(OM, MIG, invariant="Команда пишет журнал: aborted уровня error в stderr, stdout — JSON отчёта")
def test_migrate_aborted_journal(onto, database_url):
    _seed_migration(onto)
    code, out, journal, err = command("ontology_migrate", ["run"], database_url, setup=LOSSY)
    assert code == 1, err
    report = report_of(out)
    aborted = one(journal, "knowledge.migration.aborted")
    assert aborted["level"] == "error" and aborted["error_kind"] == "integrity_lost"
    assert aborted["run_id"] == report["run_id"] and aborted["lost_attributions"] >= 1
    assert one(journal, "knowledge.migration.rolled_back")["run_id"] == report["run_id"]


@req(OM, MIG, invariant="Команда пишет журнал: failed уровня error в stderr с run_id")
def test_migrate_failed_journal(onto, database_url):
    _seed_migration(onto)
    code, out, journal, err = command("ontology_migrate", ["run"], database_url, setup=BROKEN)
    assert code == 1
    assert out.strip() == ""  # отчёта нет: запуск прервался
    failed = one(journal, "knowledge.migration.failed")
    assert failed["level"] == "error" and failed["error_kind"] == "exception"
    assert failed["run_id"] in err and f"rollback {failed['run_id']}" in err


# --- quality_report ---------------------------------------------------------------------


@req(OM, QM, invariant="Команда замера пишет knowledge.quality.measured, stdout — JSON (--json)")
def test_quality_report_journal(onto, database_url):
    raw_entity(onto, "concept", [("en", "20.1", "primary")])
    code, out, journal, err = command("quality_report", ["--json"], database_url)
    assert code == 1, err  # А2 = 1: критерий не выполнен
    result = report_of(out)
    measured = one(journal, "knowledge.quality.measured")
    assert measured["a2"] == 1 and measured["passed"] is result["passed"] is False


# --- life_dates -------------------------------------------------------------------------


LD = ("entity-dating", "Даты жизни из Wikidata")


@req(*LD, invariant="Команда life_dates пишет run и rolled_back в stderr, stdout — JSON")
def test_life_dates_journal(onto, database_url, tmp_path):
    plato = onto.entities.create("person", [("ru", "Платон", "primary")])
    records = tmp_path / "records.json"
    records.write_text(json.dumps({"Q859": PLATO}), encoding="utf-8")
    manifest = tmp_path / "person_qids.yaml"
    manifest.write_text(
        f"entities:\n- entity: {plato}\n  wikidata: Q859\n  decision: accepted\n",
        encoding="utf-8",
    )
    base = ["--manifest", str(manifest), "--from-file", str(records)]
    code, out, journal, err = command("life_dates", ["apply", *base], database_url)
    assert code == 0, err
    report = report_of(out)
    run = one(journal, "knowledge.life_dates.run")
    assert run["run_id"] == report["run_id"] and run["dry_run"] is False
    code, out, journal, err = command("life_dates", ["rollback", report["run_id"]], database_url)
    assert code == 0, err
    report_of(out)
    assert one(journal, "knowledge.life_dates.rolled_back")["run_id"] == report["run_id"]


# --- geo_enrich -------------------------------------------------------------------------


GEO = ("geo-timeline", "Места и координаты из Wikidata")


@req(*GEO, invariant="Команда geo_enrich пишет enriched и rolled_back в stderr, stdout — JSON")
def test_geo_enrich_journal(onto, database_url, tmp_path):
    onto.person("Иммануил Кант", "1724", "1804", wikidata=KANT_Q)
    records = tmp_path / "records.json"
    records.write_text(json.dumps(kant_records(), ensure_ascii=False), encoding="utf-8")
    code, out, journal, err = command(
        "geo_enrich", ["run", "--from-file", str(records)], database_url
    )
    assert code == 0, err
    summary = report_of(out)
    enriched = one(journal, "knowledge.geo.enriched")
    assert enriched["run_id"] == summary["run_id"] and enriched["placements"] == 2
    code, out, journal, err = command("geo_enrich", ["rollback", summary["run_id"]], database_url)
    assert code == 0, err
    report_of(out)
    assert one(journal, "knowledge.geo.rolled_back")["run_id"] == summary["run_id"]


# --- epoch_dates ------------------------------------------------------------------------


ED = ("epochs", "Даты эпох из Wikidata")
ENL_FETCH = "__import__('tests.knowledge.test_epoch_dates', fromlist=['x']).enlightenment_record()"


@req(*ED, invariant="Команда epoch_dates пишет checked и run в stderr, stdout — JSON")
def test_epoch_dates_journal(onto, database_url, tmp_path):
    enl = onto.entities.create("epoch", [("ru", "Просвещение", "primary")])
    onto.entities.add_external(enl, "wikidata", "Q12539")
    manifest = tmp_path / "epochs.yaml"
    manifest.write_text("epochs: []\n", encoding="utf-8")
    code, out, journal, err = command(
        "epoch_dates",
        ["apply", "--manifest", str(manifest), "--linked"],
        database_url,
        fetch=ENL_FETCH,
    )
    assert code == 0, err
    report = report_of(out)
    checked = one(journal, "knowledge.epoch_dates.checked")
    assert (checked["epoch_id"], checked["result"]) == (enl, "added")
    assert "knowledge.epoch_dates.run" in names(journal)
    assert report["epochs"][0]["result"] == "added"


# --- epoch_context ----------------------------------------------------------------------


EC = ("epoch-context", "Контекстные события из Wikidata")
FIXTURE_FETCH = "__import__('tests.knowledge.wikidata_fixtures', fromlist=['x']).FixtureFetch()"


@req(*EC, invariant="Команда epoch_context пишет harvested, checked и run в stderr, stdout — JSON")
def test_epoch_context_journal(onto, database_url, tmp_path):
    onto.thing("epoch", "Просвещение", "1680–1800")
    epochs = tmp_path / "epochs.yaml"
    epochs.write_text(yaml.safe_dump(EPOCHS_YAML, allow_unicode=True), encoding="utf-8")
    manifest = tmp_path / "context.yaml"
    manifest.write_text("epochs: []\n", encoding="utf-8")
    argv = ["harvest", "--epochs", str(epochs), "--manifest", str(manifest)]
    code, out, journal, err = command("epoch_context", argv, database_url, fetch=FIXTURE_FETCH)
    assert code == 0, err
    report_of(out)
    assert "knowledge.context_import.harvested" in names(journal)
    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    for c in data["epochs"][0]["candidates"]:
        if c["qid"] == REVOLUTION:
            c["decision"] = "accepted"
    manifest.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    code, out, journal, err = command(
        "epoch_context", ["apply", "--manifest", str(manifest)], database_url, fetch=FIXTURE_FETCH
    )
    assert code == 0, err
    report_of(out)
    checked = [e for e in journal if e["event"] == "knowledge.context_import.checked"]
    assert any(e["qid"] == REVOLUTION and e["result"] == "created" for e in checked), checked
    assert one(journal, "knowledge.context_import.run")["mode"] == "apply"
