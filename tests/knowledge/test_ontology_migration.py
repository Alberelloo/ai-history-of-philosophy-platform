"""Сценарные и нормативные тесты migrate-ontology-quality (tasks.md 3.1–3.4).

Ожидания — из дельты ``specs/ontology-migration`` и design.md; оракулы — ``migration_world``
(без ``naming``/``dedupe``/``integrity``/``quality_report``). Модель — фейк с записью запросов,
Wikidata — записи теста, сеть запрещена фикстурой.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path

import pytest
import yaml
from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as hst
from sqlalchemy import delete, select, text

from philograph.knowledge import naming, run_actions
from philograph.knowledge import schema as t
from philograph.knowledge.dates import parse as dates_parse
from philograph.knowledge.ontology_migrate import STEPS, Migration, main
from philograph.knowledge.quality_report import main as quality_main
from philograph.knowledge.quality_report import read_only_engine
from philograph.knowledge.statements import Attribution

from ..conftest import PROFILES
from .dump import dump
from .migration_world import (
    GARBAGE,
    LATIN_CONCEPTS,
    SYMPTOMS_SPEC,
    THRESHOLDS,
    FakeLLM,
    State,
    Surface,
    a1,
    a2,
    a3,
    a4_pairs,
    a5,
    add_dates,
    add_role,
    add_statement,
    build,
    event_values,
    is_ru,
    langs_broken,
    losses,
    name_forms_broken,
    name_texts,
    old_form,
    ontologies,
    raw_entity,
    reason_of,
    shown,
    verified_dropped,
    wipe,
)
from .strategies import search_form, sentinel
from .wd_records import RecordFetch, record

req = pytest.mark.req
OM = "ontology-migration"
MIG = "Миграция существующей онтологии"
RET = "Снятие мусорных сущностей"
TR = "Перевод названий"
RB = "Откат миграции"
QM = "Замер качества онтологии"

NOISE = {"request_id", "service"}
KEYS = {
    "knowledge.migration.step": {"run_id", "step", "actions", "dry_run"},
    "knowledge.migration.translated": {"run_id", "batch", "accepted", "rejected"},
    "knowledge.migration.run": {
        "run_id",
        "dry_run",
        "translate",
        "retired",
        "renamed_wikidata",
        "renamed_model",
        "merged",
        "folded",
        "review",
        "statements_before",
        "statements_after",
        "lost",
        "a1_before",
        "a1_after",
    },
    "knowledge.migration.aborted": {"run_id", "lost", "lost_attributions", "error_kind"},
    "knowledge.migration.rolled_back": {"run_id", "actions", "merges_undone", "restored", "kept"},
    "knowledge.entity.retired": {"entity_id", "type", "reason", "run_id"},
    "knowledge.entity.restored": {"entity_id", "run_id"},
    "knowledge.quality.measured": {f"a{i}" for i in range(1, 9)} | {"passed", "failed"},
}
MARKER = "Zq7Marker"
SPEC_STEPS = (  # «Миграция существующей онтологии», шаги 1–8 по порядку (О24)
    "normalize_names",
    "manifest_qids",
    "lang_fix",
    "retire",
    "wikidata_labels",
    "translate",
    "dedupe",
    "verify",
)
HUMAN = ("Q5",)
WD = {
    "Q41568": record("Q41568", ru="Юм", en="Hume", classes=HUMAN),
    "Q6691": record("Q6691", ru="Гомер", en="Homer", classes=HUMAN),
}
TWO = {"causality": "Причинность", "substance": "Субстанция"}
DB_SETTINGS = dict(
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow]
)


def check_keys(events) -> None:
    """Точные множества ключей событий миграции (``run_id`` контекста допускается сверх)."""
    for e in events.items:
        if e.name in KEYS:
            got = set(e.fields) - NOISE
            assert got - {"run_id"} == KEYS[e.name] - {"run_id"}, (e.name, sorted(got))


def migration(onto, fetch=None, llm=None) -> Migration:
    return Migration(onto.statements, None, fetch or RecordFetch(WD), llm)


def cli(onto, capsys, argv, fetch=None, llm=None) -> tuple[int, dict | None]:
    capsys.readouterr()
    code = main(
        argv,
        fetch=fetch or RecordFetch(WD),
        llm=llm,
        service=lambda fetch_, llm_: Migration(onto.statements, None, fetch_, llm_),
    )
    out = capsys.readouterr().out
    return code, (json.loads(out[out.index("{") :]) if "{" in out else None)


def quality(capsys, url, *argv) -> tuple[int, dict]:
    capsys.readouterr()
    code = quality_main(["--json", *argv], url=url)
    out = capsys.readouterr().out
    return code, json.loads(out[out.index("{") :])


def values(result: dict) -> dict[str, object]:
    return {f"a{i + 1}": c["value"] for i, c in enumerate(result["criteria"])}


def write_manifest(tmp_path: Path, manifest: dict) -> str:
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump(manifest, allow_unicode=True), encoding="utf-8")
    return str(path)


def db_files(database_url: str) -> dict[str, str]:
    """md5 файлов SQLite базы теста (основной и схемы знаний)."""
    path = Path(database_url.removeprefix("sqlite:///"))
    return {
        p.name: hashlib.md5(p.read_bytes()).hexdigest()
        for p in sorted(path.parent.glob(f"{path.stem}*.db"))
    }


def dump_diff(a: dict, b: dict) -> dict:
    """Строки, которых нет в другом дампе, по таблицам — сообщение к падению сравнения."""
    out = {}
    for k in a:
        if a[k] != b[k]:
            gone, new = set(a[k]) - set(b[k]), set(b[k]) - set(a[k])
            cols = [c.name for c in getattr(t, k).columns]
            by_id = {r[0]: r for r in new}
            out[k] = [
                {
                    c: (x, by_id[r[0]][i])
                    for i, (c, x) in enumerate(zip(cols, r, strict=True))
                    if x != by_id[r[0]][i]
                }
                if r[0] in by_id
                else {"-": r}
                for r in sorted(gone, key=str)[:3]
            ]
    return out


def no_marker(events, marker: str) -> None:
    for e in events.items:
        assert marker not in repr(e.fields), e.name


# --- синтетическая онтология стенда (сценарий спецификации) -------------------------------


def stand(onto) -> dict[str, str]:
    def e(type_, label, lang="en", qid=None):
        return raw_entity(onto, type_, [(lang, label, "primary")], qid)

    ids = {
        "causality": e("concept", "causality", "ru"),
        "substance": e("concept", "substance", "ru"),
        "num": e("concept", "20.1"),
        "every": e("term", "Every"),
        "empty": e("term", "", "ru"),
        "lordship": e("person", "your Lordship"),
        "children": e("person", "children"),
        "blind": e("person", "blind mathematician"),
        "kepler": e("person", "Kepler and Des Cartes"),
        "b1": e("person", "Berkeley"),
        "b2": e("person", "Berkeley"),
        "b3": e("person", "Berkeley"),
        "hume": e("person", "Hume", qid="Q41568"),
        "yum": e("person", "Юм", "ru"),
        "homer": e("person", "Гомер", "ru", qid="Q6691"),
        "omir": e("person", "Омир", "ru"),
        "kant": e("person", "Кант", "ru"),
        "descartes": e("person", "Декарт", "ru"),
        "locke": e("person", "Локк", "ru"),
        "spinoza": e("person", "Спиноза", "ru"),
        "plato": e("person", "Платон", "ru"),
        "experience": e("concept", "Опыт", "ru"),
        "reason": e("concept", "Разум", "ru"),
        "empiricism": e("position", "Эмпиризм", "ru"),
    }

    def add(subject, rel, obj, attributions):
        return add_statement(onto, subject, rel, obj, attributions)

    src = [Attribution("source", "s_a")]
    add(ids["kant"], "studied_with", obj=ids["lordship"], attributions=src)
    add(ids["kant"], "influenced_by", obj=ids["num"], attributions=src)
    add(ids["descartes"], "studied_with", obj=ids["children"], attributions=src)
    add(
        ids["kant"],
        "influenced_by",
        obj=ids["spinoza"],
        attributions=[Attribution("entity", ids["lordship"]), Attribution("source", "s_b")],
    )
    add(ids["causality"], "opposed_to", obj=ids["substance"], attributions=src)
    add(ids["experience"], "influenced_by", obj=ids["locke"], attributions=[Attribution("common")])
    add(ids["reason"], "opposed_to", obj=ids["empiricism"], attributions=src)
    add(ids["causality"], "influenced_by", obj=ids["hume"], attributions=src)
    cluster = {"b1": 1, "b2": 1, "b3": 1, "hume": 2, "yum": 2, "homer": 3, "omir": 3}
    people = [
        "kant",
        "descartes",
        "locke",
        "spinoza",
        "plato",
        "b1",
        "b2",
        "b3",
        "hume",
        "yum",
        "homer",
        "omir",
    ]
    n = 8
    for i, a in enumerate(people):
        for b in people[i + 1 :]:
            if n == 40:
                break
            if cluster.get(a) and cluster.get(a) == cluster.get(b):
                continue
            attrs = [Attribution("source", "s_a" if n % 2 else "s_b")]
            if n % 3 == 0:
                attrs.append(Attribution("entity", ids["kant"], "disputes"))
            add(ids[a], "studied_with", obj=ids[b], attributions=attrs)
            n += 1
    assert State.read(onto.statements.engine).statements.__len__() == 40
    return ids


STAND_MANIFEST = lambda ids: {  # noqa: E731
    "entities": [
        {"entity": ids["omir"], "wikidata": "Q6691", "decision": "accepted", "candidates": []}
    ]
}


def run_stand(onto, capsys, tmp_path, manifest=None, llm=None):
    ids = stand(onto)
    path = write_manifest(tmp_path, manifest(ids) if manifest else STAND_MANIFEST(ids))
    llm = llm or FakeLLM.by_label(TWO)
    code, report = cli(onto, capsys, ["run", "--translate", "model", "--manifest", path], llm=llm)
    return ids, code, report, llm


# =========================== Миграция =====================================================


@req(OM, MIG, scenario="Синтетическая онтология стенда")
def test_stand_synthetic(onto, events, capsys, tmp_path):
    ids, code, report, _llm = run_stand(onto, capsys, tmp_path)
    assert code == 0, report
    after = State.read(onto.statements.engine)
    assert report["retired"] == {"empty": 1, "not_a_name": 4, "number": 1, "stopword": 1}
    retired = {k for k, v in ids.items() if after.retired(v)}
    assert retired == {"num", "every", "empty", "lordship", "children", "blind", "kepler"}
    berkeley = [p for p in after.active() if after.label(p) == "Berkeley"]
    assert len(berkeley) == 1 and berkeley[0] in {ids["b1"], ids["b2"], ids["b3"]}
    hume = after.resolve(ids["hume"])
    assert hume == after.resolve(ids["yum"])
    assert after.qids.get(hume) == {"Q41568"}
    assert after.name_set(hume) == {("ru", "Юм", "primary"), ("en", "Hume", "variant")}
    for key, ru, en in (
        ("causality", "Причинность", "causality"),
        ("substance", "Субстанция", "substance"),
    ):
        assert after.name_set(ids[key]) == {("ru", ru, "primary"), ("en", en, "variant")}
    homer = after.resolve(ids["omir"])
    assert homer == after.resolve(ids["homer"]) == ids["homer"]
    assert after.qids.get(homer) == {"Q6691"}
    assert after.name_set(homer) == {("ru", "Гомер", "primary"), ("ru", "Омир", "variant")}
    assert report["statements"]["lost"] == 0 and report["attributions"]["lost"] == 0
    assert report["statements"]["dropped_garbage"] == 3
    assert report["a1"]["after"] > report["a1"]["before"]
    # журнал
    # по одному step на каждый шаг спецификации, в её порядке (О24: восемь шагов; текст
    # сценария стенда всё ещё говорит «семи» — расхождение отмечено в verification.md)
    assert [e["step"] for e in events.of("knowledge.migration.step")] == list(SPEC_STEPS)
    assert tuple(STEPS) == SPEC_STEPS
    assert len(events.of("knowledge.entity.retired")) == 7
    merged = sorted(e["reason"] for e in events.of("knowledge.entity.merged"))
    assert merged == ["merge:name", "merge:name", "merge:name", "merge:qid_confirmed"]
    [run] = events.of("knowledge.migration.run")
    assert run["lost"] == 0 and run["dry_run"] is False
    check_keys(events)


@req(OM, MIG, scenario="Транслитерация без решения человека")
@req(
    OM,
    MIG,
    invariant="Очередь кандидатов: после пропущенных записей и кандидатов — следующие (О26)",
)
@pytest.mark.parametrize("after_skips", [False, True], ids=["plain", "after_skips"])
def test_transliteration_pending(onto, events, capsys, tmp_path, database_url, after_skips):
    def pending(ids):
        held = {"qid": "Q6691", "holder": ids["homer"]}
        omir = {
            "entity": ids["omir"],
            "wikidata": None,
            "decision": "pending",
            # О26: кандидат без держателя раньше кандидата с держателем
            "candidates": [{"qid": "Q999"}, held] if after_skips else [held],
        }
        # О26: запись с принятым решением раньше записи без решения
        first = {"entity": ids["causality"], "wikidata": None, "decision": "rejected"}
        return {"entities": [first, omir] if after_skips else [omir]}

    ids, code, _report, _ = run_stand(onto, capsys, tmp_path, manifest=pending)
    assert code == 0
    after = State.read(onto.statements.engine)
    assert after.resolve(ids["omir"]) == ids["omir"] and after.resolve(ids["homer"]) == ids["homer"]
    open_pairs = [
        frozenset(i["payload"]["pair"])
        for i in after.review
        if i["kind"] == "duplicate" and i["status"] == "open"
    ]
    assert frozenset((ids["homer"], ids["omir"])) in open_pairs
    qcode, result = quality(capsys, database_url)
    assert values(result)["a4"] == 1 == len(a4_pairs(after))
    assert result["passed"] is False and qcode == 1
    [proposed] = events.where("knowledge.entity.merge_proposed", reason="review:qid_candidate")
    assert (
        {proposed["a"], proposed["b"]} == {ids["homer"], ids["omir"]}
        if "a" in proposed.fields
        else True
    )
    assert events.of("knowledge.quality.measured")[-1]["a4"] == 1
    check_keys(events)


@req(OM, MIG, scenario="Сухой прогон")
def test_dry_run(onto, events, capsys, tmp_path):
    ids = stand(onto)
    before = dump(onto.statements.engine)
    llm = FakeLLM.by_label(TWO)
    plan = migration(onto, llm=llm).plan()
    assert dump(onto.statements.engine) == before and llm.calls == []
    code, run = cli(onto, capsys, ["run", "--translate", "off"])
    assert code == 0
    planned = plan.to_json()
    assert planned["retired_list"] == run["retired_list"]
    assert {x["id"] for x in planned["retired_list"]} == {
        ids[k] for k in ("num", "every", "empty", "lordship", "children", "blind", "kepler")
    }
    assert set(planned["retired_list"][0]) == {"id", "type", "label", "reason"}
    recorded = [a["payload"] for a in run_actions.actions(onto.statements.engine, run["run_id"])]
    recorded = [
        {k: v for k, v in a.items() if k != "names_before"} for a in recorded if "step" in a
    ]
    assert [a.to_json() for a in plan.actions] == recorded
    strip = lambda r: {k: v for k, v in r.items() if k not in ("run_id", "dry_run")}  # noqa: E731
    assert strip(planned) == strip(run)
    assert planned["to_translate"] >= 2 and planned["batches"] == 1
    runs = events.of("knowledge.migration.run")
    assert [r["dry_run"] for r in runs] == [True, False]
    check_keys(events)


@req(OM, MIG, scenario="Потеря — аварийный откат")
def test_loss_aborts(onto, events, capsys, monkeypatch):
    ids = stand(onto)
    # Атрибуция без двойника на других утверждениях: её исчезновение — потеря по определению.
    add_statement(onto, ids["kant"], "studied_with", ids["b1"], [Attribution("source", "s_only")])
    before = dump(onto.statements.engine)
    original = onto.statements.merge_entities

    deleted: list[int] = []
    owners: list[str] = []

    def lossy(kept, removed, **kw):
        result = original(kept, removed, **kw)
        if deleted:
            return result
        with onto.statements.engine.begin() as conn:  # сбой: слияние теряет одну атрибуцию
            row = conn.execute(
                select(t.attributions).where(t.attributions.c.who == "s_only")
            ).first()
            if row is not None:
                deleted.append(row.id)
                owners.append(row.statement_id)
                conn.execute(delete(t.attributions).where(t.attributions.c.id == row.id))
        return result

    monkeypatch.setattr(onto.statements, "merge_entities", lossy)
    code, report = cli(onto, capsys, ["run", "--translate", "off"])
    assert code == 1 and deleted
    monkeypatch.undo()
    # Строку, удалённую самой подменой, откат вернуть не может; всё остальное — как до запуска.
    # ``consensus`` утверждения без этой атрибуции пересчитан из оставшихся — тоже след подмены.
    consensus = [c.name for c in t.statements.columns].index("consensus")

    def plain(d):
        return {
            **d,
            "attributions": [r for r in d["attributions"] if r[0] not in deleted],
            "statements": [
                (*r[:consensus], None, *r[consensus + 1 :]) if r[0] in owners else r
                for r in d["statements"]
            ],
        }

    expected, got = plain(before), plain(dump(onto.statements.engine))
    assert got == expected, dump_diff(expected, got)
    [aborted] = events.of("knowledge.migration.aborted")
    assert aborted.level == "error" and aborted["error_kind"] == "integrity_lost"
    assert aborted["lost_attributions"] >= 1
    [rolled] = events.of("knowledge.migration.rolled_back")
    assert rolled["run_id"] == aborted["run_id"] == report["run_id"]
    check_keys(events)


@req(OM, MIG, scenario="Проверенное человеком не трогается")
def test_verified_untouched(onto, events, capsys):
    ids = stand(onto)
    [sid] = [
        s["id"]
        for s in State.read(onto.statements.engine).statements.values()
        if s["subject"] == ids["kant"] and s["object"] == ids["b2"]
    ]
    onto.statements.confirm(sid, "operator")
    code, report = cli(onto, capsys, ["run", "--translate", "off"])
    assert code == 0
    after = State.read(onto.statements.engine)
    kept = after.resolve(ids["b2"])
    verified = [s for s in after.statements.values() if s["status"] == "verified"]
    assert [(s["subject"], s["object"]) for s in verified] == [(ids["kant"], kept)]
    assert report["statements"]["lost"] == 0


@req(OM, MIG, scenario="В журнале нет названий")
def test_no_names_in_journal(onto, events):
    def e(type_, label, lang="en", qid=None):
        return raw_entity(onto, type_, [(lang, label, "primary")], qid)

    a = e("person", f"{MARKER} Berkeley")
    b = e("person", f"{MARKER} Berkeley")
    c = e("concept", f"causality {MARKER.lower()}", "ru")
    g = e("person", f"your {MARKER}")
    k = e("person", f"Кант {MARKER}", "ru")
    onto.statements.add(k, "studied_with", obj=a, attributions=[Attribution("entity", g)])
    onto.statements.add(k, "studied_with", obj=b, attributions=[Attribution("source", "s_a")])
    onto.statements.add(c, "influenced_by", obj=k, attributions=[Attribution("source", "s_a")])
    llm = FakeLLM(
        lambda items, _n: [
            {"n": i["n"], "ru": "Причинность"} for i in items if "causality" in i["label"]
        ]
    )
    m = migration(onto, llm=llm)
    m.plan()
    report = m.run(translate="model")
    m.rollback(report.run_id)
    assert llm.calls  # модель вызвана: перевод был
    for ev in events.items:
        assert MARKER not in json.dumps(ev.fields, ensure_ascii=False, default=str), ev.name
        assert (
            MARKER.lower() not in json.dumps(ev.fields, ensure_ascii=False, default=str).lower()
        ), ev.name
    events.assert_sequence(
        "knowledge.migration.run", "knowledge.migration.run", "knowledge.migration.rolled_back"
    )
    assert [r["dry_run"] for r in events.of("knowledge.migration.run")] == [True, False]
    check_keys(events)


def _expect_run(world, after: State) -> None:
    """Ожидания по построению входа: снятые, названия, слияния кластеров."""
    retired = {k for k, v in world.ids.items() if after.retired(v)}
    assert retired == set(world.garbage)
    for key, label in world.expect_label.items():
        assert after.label(after.resolve(world.ids[key])) == label, (
            key,
            after.name_set(after.resolve(world.ids[key])),
        )
    for cluster in world.clusters:
        assert len({after.resolve(world.ids[k]) for k in cluster}) == 1, cluster
    for e in after.active():  # ни одна действующая (кроме источников) не даёт причины
        assert reason_of(after.entities[e]["type"], after.label(e)) is None
    assert name_forms_broken(after) == []  # О24: текст strip+NFC, normalized по правилу
    # шаг 3: язык каждого названия с письменностью — по правилу (О26); без письменности — Д3-mig
    assert langs_broken(after, scripted_only=True) == []


@req(
    OM,
    MIG,
    invariant="Шаг 3: язык названия без письменности — und по правилу entity-naming (Д3-mig)",
)
def test_lang_fix_no_script(onto, events):
    """entity-naming п. 4–5: без письменности язык — ``und``, переданный не сохраняется.
    Источник библиотеки «3.1» не снимается, поэтому его название остаётся и должно
    получить ``und``."""
    source = raw_entity(onto, "source", [("en", "3.1", "primary")])
    concept = raw_entity(
        onto, "concept", [("ru", "Причинность", "primary"), ("ru", "§ 7", "variant")]
    )
    migration(onto).run()
    after = State.read(onto.statements.engine)
    assert {n["text"]: n["lang"] for n in after.names[source]} == {"3.1": "und"}
    assert {n["text"]: n["lang"] for n in after.names[concept]} == {
        "Причинность": "ru",
        "§ 7": "und",
    }


@req(OM, MIG, scenario="Форма названий")
def test_name_form(onto, events, clock):
    token = sentinel()
    nfd = unicodedata.normalize("NFD", "Йоганн")
    assert nfd != "Йоганн"
    raw, stale = old_form("Йоганн", True, "", "")
    johann = raw_entity(onto, "person", [("ru", raw, "primary", stale)])
    padded = raw_entity(onto, "person", [("ru", " Кант ", "primary", " кант ")])
    kant = raw_entity(onto, "person", [("ru", "Кант", "primary")])
    other = raw_entity(onto, "person", [("ru", f"Фихте {token}", "primary")])
    surface = Surface(onto, clock)
    assert johann not in surface.find("Йоганн").text
    assert padded not in surface.find("Кант").text
    before = dump(onto.statements.engine)
    report = migration(onto).run()
    after = State.read(onto.statements.engine)
    assert [n["text"] for n in after.names[johann]] == ["Йоганн"]
    assert after.names[johann][0]["normalized"] == "йоганн"  # NFC, нижний регистр
    assert johann in Surface(onto, clock).find("Йоганн").text
    assert after.resolve(padded) == after.resolve(kant)
    assert {n["text"] for n in after.names[after.resolve(padded)]} == {"Кант"}
    assert report.to_json()["names_normalized"] == 2
    [step] = events.where("knowledge.migration.step", step="normalize_names")
    assert step["actions"] == 2 and step["dry_run"] is False
    [merged] = events.of("knowledge.entity.merged")
    assert merged["reason"] == "merge:name"
    assert {merged["kept"], merged["removed"]} == {padded, kant}
    assert name_forms_broken(after) == []
    assert other in after.active()
    for e in events.items:  # тексты названий в событиях не появляются
        assert token not in json.dumps(e.fields, ensure_ascii=False, default=str), e.name
    check_keys(events)
    Migration(onto.statements, None, RecordFetch(WD), None).rollback(report.run_id)
    assert dump(onto.statements.engine) == before


@req(OM, MIG, scenario="Инвариант миграции")
@settings(PROFILES["heavy"], **DB_SETTINGS)
@given(spec=ontologies())
@example(spec=SYMPTOMS_SPEC)
def test_migration_invariant(onto, events, spec):
    wipe(onto)
    world = build(onto, spec)
    engine = onto.statements.engine
    before_dump, before = dump(engine), State.read(engine)
    fetch = RecordFetch(world.wd)
    llm = FakeLLM.by_label(world.llm_table)
    events.clear()
    plan = Migration(onto.statements, None, fetch, llm).plan(manifest=world.manifest)
    assert dump(engine) == before_dump and llm.calls == []  # оракул 1
    off = Migration(onto.statements, None, fetch, None).run(manifest=world.manifest)
    # Оракул 2: вид, сущность и значения; ``step`` — служебная метка строки журнала (запись
    # QID шага manifest_qids идёт правилом команды QID без неё), ``names_before`` — поле отката.
    service = {"step", "names_before"}
    recorded = [
        {k: v for k, v in a["payload"].items() if k not in service}
        for a in run_actions.actions(engine, off.run_id)
    ]
    assert [{k: v for k, v in a.to_json().items() if k not in service} for a in plan.actions] == (
        recorded
    )
    mid = State.read(engine)
    planned_retired = {a.payload["entity"] for a in plan.actions if a.step == "retire"}
    assert planned_retired == {e for e in mid.entities if mid.retired(e)}  # оракул 3
    planned_removed = {
        a.payload["removed"] for a in plan.actions if a.step == "dedupe" and a.kind == "merge"
    }
    assert planned_removed == {e for e, row in mid.entities.items() if row["redirect_to"]}
    assert plan.folded == off.folded
    assert losses(before, mid) == ([], [])
    Migration(onto.statements, None, fetch, None).rollback(off.run_id)
    assert dump(engine) == before_dump
    events.clear()
    report = Migration(onto.statements, None, fetch, llm).run(
        manifest=world.manifest, translate="model"
    )
    after = State.read(engine)
    assert losses(before, after) == ([], [])
    assert report.statements["lost"] == 0 and report.attributions["lost"] == 0
    _expect_run(world, after)
    blob = event_values(events)
    for text_ in name_texts(spec):
        assert text_ not in blob, text_
    check_keys(events)
    # «Проверенное человеком не трогается» на любых онтологиях — последним (Д2-mig).
    assert verified_dropped(before, mid) == [] and verified_dropped(before, after) == []


# =========================== Снятие =======================================================


def _kant_and_number(onto):
    kant = raw_entity(onto, "person", [("ru", "Кант", "primary")])
    num = raw_entity(onto, "concept", [("ru", "20.1", "primary")])
    sid = onto.statements.add(
        kant, "influenced_by", obj=num, attributions=[Attribution("source", "s_a")]
    )
    return kant, num, sid


@req(OM, RET, scenario="Номер раздела снят")
def test_section_number_retired(onto, events, clock):
    kant, num, sid = _kant_and_number(onto)
    report = migration(onto).run()
    api = Surface(onto, clock)
    assert all(i["id"] != num for i in api.catalog(q="20.1"))
    assert api.card(num).status_code == 404
    assert sid not in json.dumps(api.about(kant))
    assert sid not in json.dumps(api.map()) and num not in json.dumps(api.map())
    assert sid in State.read(onto.statements.engine).statements
    [retired] = events.of("knowledge.entity.retired")
    assert {k: retired[k] for k in ("entity_id", "type", "reason", "run_id")} == {
        "entity_id": num,
        "type": "concept",
        "reason": "number",
        "run_id": report.run_id,
    }
    check_keys(events)


@req(OM, RET, scenario="Ассистент не видит снятое")
def test_assistant_does_not_see_retired(onto, events, clock):
    kant = raw_entity(onto, "person", [("ru", "Кант", "primary")])
    lord = raw_entity(onto, "person", [("en", "your Lordship", "primary")])
    sid = onto.statements.add(
        kant, "studied_with", obj=lord, attributions=[Attribution("source", "s_a")]
    )
    migration(onto).run()
    events.clear()
    r = Surface(onto, clock).context("Кант", ["Кант"])
    assert r.status_code == 200, r.text
    assert sid not in r.text and lord not in r.text
    assert [e.name for e in events.items if e.level == "error"] == []


@req(OM, RET, scenario="Возврат при откате")
def test_restore_on_rollback(onto, events, clock):
    kant, num, sid = _kant_and_number(onto)
    m = migration(onto)
    report = m.run()
    m.rollback(report.run_id)
    api = Surface(onto, clock)
    assert num in [i["id"] for i in api.catalog(q="20.1")]
    assert sid in json.dumps(api.about(kant))
    [restored] = events.of("knowledge.entity.restored")
    assert (restored["entity_id"], restored["run_id"]) == (num, report.run_id)
    check_keys(events)


def _hidden_statements(state: State) -> set[str]:
    """Утверждения, которые нельзя показывать: снятый конец или все атрибуции — от снятых."""
    out = set()
    for sid, s in state.statements.items():
        if state.retired(s["subject"]) or state.retired(s["object"]):
            out.add(sid)
        attrs = state.attributions.get(sid, [])
        if attrs and all(a["who_kind"] == "entity" and state.retired(a["who"]) for a in attrs):
            out.add(sid)
    return out


@req(OM, RET, scenario="Инвариант снятия")
@settings(PROFILES["ci"], **DB_SETTINGS)
@given(spec=ontologies(manifest=False))
def test_retire_invariant(onto, events, clock, spec):
    wipe(onto)
    spec = {**spec, "clusters": []}
    world = build(onto, spec)
    engine = onto.statements.engine
    counts = {
        tb.name: len(dump(engine, (tb.name,))[tb.name]) for tb in (t.statements, t.attributions)
    }
    m = Migration(onto.statements, None, RecordFetch(world.wd), None)
    report = m.run()
    after = State.read(engine)
    if report.merged == 0:
        assert {
            tb.name: len(dump(engine, (tb.name,))[tb.name]) for tb in (t.statements, t.attributions)
        } == counts
    retired = {e for e in after.entities if after.retired(e)}
    assert retired == {world.ids[k] for k in world.garbage}
    surface = Surface(onto, clock)
    blob = shown(surface, after)
    for e in retired:
        assert e not in blob, e
    for sid in _hidden_statements(after):
        assert sid not in blob, sid
    for e in retired:  # поиск по названию
        label = after.label(e)
        if label.strip():
            assert e not in surface.find(label).text


# =========================== Перевод ======================================================


def _concepts(onto, labels, lang="en"):
    return {label: raw_entity(onto, "concept", [(lang, label, "primary")]) for label in labels}


@req(OM, TR, scenario="Пакет с ошибками модели")
def test_batch_with_model_errors(onto, events):
    ids = _concepts(onto, ["causality", "substance", "idea", "mind"])

    def answer(items, _n):
        n = {i["label"]: i["n"] for i in items}
        return [
            {"n": n["causality"], "ru": "Причинность"},
            {"n": n["substance"], "ru": "Substanz"},
            {"n": n["substance"], "ru": "Субстанция"},
            {"n": 7, "ru": "Ум"},
            {"n": n["idea"], "ru": "some"},
        ]

    llm = FakeLLM(answer)
    report = migration(onto, llm=llm).run(translate="model", batch=4)
    after = State.read(onto.statements.engine)
    assert after.label(ids["causality"]) == "Причинность"
    for label in ("substance", "idea", "mind"):
        assert after.label(ids[label]) == label
    u = report.to_json()["untranslated"]
    assert {
        k: u.get(k, 0) for k in ("duplicate_item", "unknown_item", "not_russian", "missing")
    } == {
        "duplicate_item": 2,
        "unknown_item": 1,
        "not_russian": 1,
        "missing": 1,
    }
    [tr] = events.of("knowledge.migration.translated")
    assert (tr["accepted"], tr["rejected"]) == (1, 4)
    for call in llm.calls:  # без идентификаторов сущностей
        for item in llm.items(call):
            assert set(item) == {"n", "type", "label"}
    check_keys(events)


LONG_RU = "Один два три четыре пять шесть семь"  # invalid:sentence для понятия
# Порядок проверок ответа — все пары (i < j): ответ нарушает обе, причина — первая (О26).
REPLY_PAIRS = {
    ("unknown_item", "duplicate_item"): ([(9, "Ум"), (9, "Ум")], {"unknown_item": 2}),
    ("unknown_item", "not_russian"): ([(9, "mind")], {"unknown_item": 1}),
    ("unknown_item", "invalid"): ([(9, LONG_RU)], {"unknown_item": 1}),
    ("duplicate_item", "not_russian"): (
        [(1, "Substanz"), (1, "Субстанция")],
        {"duplicate_item": 2},
    ),
    ("duplicate_item", "invalid"): ([(1, LONG_RU), (1, "Причинность")], {"duplicate_item": 2}),
    ("not_russian", "invalid"): ([(1, "one two three four five six seven")], {"not_russian": 1}),
}


@req(OM, TR, invariant="Порядок проверок ответа: каждая пара — первая по порядку (О26)")
@pytest.mark.parametrize("pair", sorted(REPLY_PAIRS), ids="/".join)
def test_reply_check_order_pairs(onto, events, pair):
    ids = _concepts(onto, ["causality", "substance"])
    reply, expected = REPLY_PAIRS[pair]
    proposed = {n for n, _ru in reply if 1 <= n <= 2}

    def answer(items, _n):
        return [{"n": n, "ru": ru} for n, ru in reply]

    report = migration(onto, llm=FakeLLM(answer)).run(translate="model", batch=2)
    after = State.read(onto.statements.engine)
    for label in ("causality", "substance"):
        assert after.label(ids[label]) == label
    u = {k: v for k, v in report.to_json()["untranslated"].items() if v}
    assert u == {**expected, **({"missing": 2 - len(proposed)} if len(proposed) < 2 else {})}
    check_keys(events)


@req(OM, TR, scenario="Русское стоп-слово от модели")
def test_russian_stopword(onto, events, monkeypatch, tmp_path):
    data = yaml.safe_load(naming.RULES_PATH.read_text(encoding="utf-8"))
    data["stopwords"].append("всякий")
    path = tmp_path / "naming_rules.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    original = naming.load_rules
    monkeypatch.setattr(naming, "load_rules", lambda *_a, **_k: original(Path(path)))
    ids = _concepts(onto, ["universality"])
    llm = FakeLLM.by_label({"universality": "Всякий"})
    report = migration(onto, llm=llm).run(translate="model")
    after = State.read(onto.statements.engine)
    assert all(n["text"] != "Всякий" for n in after.names.get(ids["universality"], []))
    assert after.label(ids["universality"]) == "universality"  # сущность не снята, имя прежнее
    assert report.to_json()["untranslated"].get("invalid:stopword") == 1


@req(OM, TR, scenario="Подпись из Wikidata раньше модели")
def test_wikidata_before_model(onto, events):
    hume = raw_entity(onto, "person", [("en", "Hume", "primary")], "Q41568")
    llm = FakeLLM.by_label({"Hume": "Хьюм"})
    report = migration(onto, llm=llm).run(translate="model")
    assert State.read(onto.statements.engine).label(hume) == "Юм"
    assert all("Hume" not in json.dumps(c, ensure_ascii=False) for c in llm.calls)
    assert report.to_json()["renamed"]["wikidata"] == 1


@req(OM, TR, scenario="Без флага модель не вызывается")
def test_no_model_without_flag(onto, events, capsys):
    stand(onto)
    llm = FakeLLM.by_label(TWO)
    code, report = cli(onto, capsys, ["run"], llm=llm)
    assert code == 0 and llm.calls == []
    after = State.read(onto.statements.engine)
    non_ru = [e for e in after.active() if not is_ru(after.label(e))]
    # к переводу (до слияния): causality, substance, Berkeley×3
    assert report["to_translate"] == 5
    assert len(non_ru) == 3  # causality, substance, Berkeley (после слияния)
    events.assert_none("knowledge.migration.translated")
    migration(onto, llm=llm).run()
    assert llm.calls == []


@req(OM, TR, scenario="Оценка стоимости")
def test_estimate(onto, events, capsys):
    letters = "bcdfghklmnpqrstvz"
    for i in range(120):
        word = "term" + letters[i % 17] + letters[(i // 17) % 17] + "a"
        raw_entity(onto, "concept", [("en", word, "primary")])
    before = dump(onto.statements.engine)
    llm = FakeLLM(lambda items, _n: [], cost=0.0125)
    code, report = cli(onto, capsys, ["plan", "--estimate", "--batch", "50"], llm=llm)
    assert code == 0 and len(llm.calls) == 1
    assert dump(onto.statements.engine) == before
    assert report["batches"] == 3 and report["estimate_usd"] == pytest.approx(0.0125 * 3)
    assert len(events.of("knowledge.migration.translated")) == 1
    check_keys(events)


RU_OK = ("Причинность", "Субстанция", "Опыт", "Пространство", "Ум", "Интуиция", "Идея", "Время")
REPLIES = ("ok", "latin", "stopword", "sentence", "duplicate", "missing", "ok_dup_unknown")


@hst.composite
def translation_replies(draw):
    """Пакеты латинских понятий и ответ модели по каждому элементу + ожидание."""
    k = draw(hst.integers(1, 8))
    labels = [f"word{chr(97 + i)}x" for i in range(k)]
    plan = {label: draw(hst.sampled_from(REPLIES)) for label in labels}
    batch = draw(hst.integers(1, max(1, k)))
    failed = set(
        draw(hst.lists(hst.integers(1, (k + batch - 1) // batch), max_size=1, unique=True))
    )
    unknown = draw(hst.integers(0, 2))
    return {
        "labels": labels,
        "plan": plan,
        "batch": batch,
        "failed": failed,
        "unknown": unknown,
        "ru": {
            label: RU_OK[i % len(RU_OK)] + "ий" * (i // len(RU_OK))
            for i, label in enumerate(labels)
        },
    }


def _answer(case):
    def answer(items, number):
        if number in case["failed"]:
            return None
        out = []
        for i in items:
            kind, ru = case["plan"][i["label"]], case["ru"][i["label"]]
            if kind in ("ok", "ok_dup_unknown"):
                out.append({"n": i["n"], "ru": ru})
            elif kind == "latin":
                out.append({"n": i["n"], "ru": "Causality"})
            elif kind == "stopword":
                out.append({"n": i["n"], "ru": "Поэт"})  # стоп-слово данных (naming_rules.yaml)
            elif kind == "sentence":
                out.append({"n": i["n"], "ru": "это очень длинное название понятия из восьми слов"})
            elif kind == "duplicate":
                out += [{"n": i["n"], "ru": ru}, {"n": i["n"], "ru": ru}]
        out += [{"n": len(items) + 1 + j, "ru": "Лишнее"} for j in range(case["unknown"])]
        return out

    return answer


def _expected_translation(case, calls, llm):
    """Ожидаемые принятые и причины по порядку спецификации; группировка — из запросов."""
    accepted, reasons = set(), {}
    for number, call in enumerate(calls, start=1):
        if number in case["failed"]:
            continue
        reasons["unknown_item"] = reasons.get("unknown_item", 0) + case["unknown"]
        for item in llm.items(call):
            kind = case["plan"][item["label"]]
            reason = {
                "latin": "not_russian",
                "stopword": "invalid:stopword",
                "sentence": "invalid:sentence",
                "missing": "missing",
            }.get(kind)
            if kind == "duplicate":
                reasons["duplicate_item"] = reasons.get("duplicate_item", 0) + 2
            elif reason:
                reasons[reason] = reasons.get(reason, 0) + 1
            else:
                accepted.add(item["label"])
    return accepted, {k: v for k, v in reasons.items() if v}


@req(OM, TR, scenario="Инвариант перевода")
@settings(PROFILES["ci"], **DB_SETTINGS)
@given(case=translation_replies())
@example(
    {
        "labels": ["wordax"],
        "plan": {"wordax": "duplicate"},
        "batch": 1,
        "failed": set(),
        "unknown": 0,
        "ru": {"wordax": "Причинность"},
    }
)
@example(
    {
        "labels": ["wordax", "wordbx"],
        "plan": {"wordax": "ok", "wordbx": "ok"},
        "batch": 1,
        "failed": {2},
        "unknown": 1,
        "ru": {"wordax": "Причинность", "wordbx": "Субстанция"},
    }
)
def test_translation_invariant(onto, events, case):
    wipe(onto)
    ids = _concepts(onto, case["labels"])
    off = FakeLLM(_answer(case))
    migration(onto, llm=off).run(translate="off")
    assert off.calls == []  # без флага запросов нет
    wipe(onto)
    ids = _concepts(onto, case["labels"])
    llm = FakeLLM(_answer(case))
    events.clear()
    report = migration(onto, llm=llm).run(translate="model", batch=case["batch"])
    assert all(len(llm.items(c)) <= case["batch"] for c in llm.calls)
    assert sorted(i["label"] for c in llm.calls for i in llm.items(c)) == sorted(case["labels"])
    accepted, reasons = _expected_translation(case, llm.calls, llm)
    after = State.read(onto.statements.engine)
    written = {label for label, e in ids.items() if after.label(e) != label}
    assert written == accepted
    for label in written:
        assert after.label(ids[label]) == case["ru"][label]
        assert ("en", label, "variant") in after.name_set(ids[label])
    assert {k: v for k, v in report.to_json()["untranslated"].items() if v} == reasons
    assert sum(e["accepted"] for e in events.of("knowledge.migration.translated")) == len(written)
    assert report.failed_batches == len(case["failed"] & set(range(1, len(llm.calls) + 1)))


# =========================== Откат ========================================================


@req(OM, RB, scenario="Полный откат")
def test_full_rollback(onto, events, capsys, tmp_path):
    ids = stand(onto)
    before = dump(onto.statements.engine)
    path = write_manifest(tmp_path, STAND_MANIFEST(ids))
    code, report = cli(
        onto, capsys, ["run", "--translate", "model", "--manifest", path], llm=FakeLLM.by_label(TWO)
    )
    assert code == 0
    events.clear()
    code, _summary = cli(onto, capsys, ["rollback", report["run_id"]])
    assert code == 0
    assert dump(onto.statements.engine) == before
    after = State.read(onto.statements.engine)
    assert after.name_set(ids["causality"]) == {("ru", "causality", "primary")}
    assert len(after.active()) == len(ids)
    [rolled] = events.of("knowledge.migration.rolled_back")
    assert (rolled["merges_undone"], rolled["restored"]) == (4, 7)
    assert rolled["run_id"] == report["run_id"]
    assert all(
        i["status"] == "rolled_back" for i in after.review if i.get("run_id") == report["run_id"]
    )
    check_keys(events)


@req(OM, RB, scenario="Последующее изменение сохраняется")
def test_later_change_kept(onto, events):
    ids = _concepts(onto, ["causality"], lang="ru")
    m = migration(onto, llm=FakeLLM.by_label(TWO))
    report = m.run(translate="model")
    onto.entities.set_primary_name(ids["causality"], "ru", "Каузальность")
    events.clear()
    m.rollback(report.run_id)
    assert State.read(onto.statements.engine).label(ids["causality"]) == "Каузальность"
    assert events.one("knowledge.migration.rolled_back")["kept"] == 1
    check_keys(events)


@req(OM, RB, invariant="Откат с проверенным утверждением шага QID: оно и его QID остаются")
def test_rollback_keeps_verified_qid(onto, events):
    plato = raw_entity(onto, "person", [("ru", "Платон", "primary")])
    rec = record(
        "Q859",
        ru="Платон",
        classes=HUMAN,
        times={"P569": ("-0427-00-00T00:00:00Z", 9), "P570": ("-0347-00-00T00:00:00Z", 9)},
    )
    manifest = {
        "entities": [
            {"entity": plato, "wikidata": "Q859", "decision": "accepted", "candidates": []}
        ]
    }
    m = migration(onto, fetch=RecordFetch({"Q859": rec}))
    report = m.run(manifest=manifest)
    [life] = [
        s for s in State.read(onto.statements.engine).statements.values() if s["type"] == "lifespan"
    ]
    onto.statements.confirm(life["id"], "operator")
    summary = m.rollback(report.run_id)
    after = State.read(onto.statements.engine)
    assert after.statements[life["id"]]["status"] == "verified"
    assert after.qids.get(plato) == {"Q859"}
    assert summary["kept"] >= 1


@req(OM, RB, scenario="Инвариант отката")
@settings(PROFILES["heavy"], **DB_SETTINGS)
@given(spec=ontologies())
@example(spec=SYMPTOMS_SPEC)
def test_rollback_invariant(onto, events, spec):
    wipe(onto)
    world = build(onto, spec)
    engine = onto.statements.engine
    before = dump(engine)
    m = Migration(onto.statements, None, RecordFetch(world.wd), FakeLLM.by_label(world.llm_table))
    report = m.run(manifest=world.manifest, translate="model")
    m.rollback(report.run_id)
    assert dump(engine) == before
    with engine.begin() as conn:
        statuses = {r.status for r in conn.execute(select(t.review_items))}
    assert statuses <= {"rolled_back"}


# =========================== Замер ========================================================


@req(OM, QM, scenario="Синтетическая онтология до и после")
def test_quality_before_after(onto, events, capsys, tmp_path, database_url):
    ids = stand(onto)
    base = tmp_path / "before.json"
    code, result = quality(capsys, database_url, "--save", str(base))
    v = values(result)
    assert (v["a2"], v["a3"], v["a4"]) == (1, 4, 3) and code == 1 and result["passed"] is False
    path = write_manifest(tmp_path, STAND_MANIFEST(ids))
    assert (
        cli(
            onto,
            capsys,
            ["run", "--translate", "model", "--manifest", path],
            llm=FakeLLM.by_label(TWO),
        )[0]
        == 0
    )
    code, result = quality(capsys, database_url, "--baseline", str(base))
    v = values(result)
    after = State.read(onto.statements.engine)
    assert (v["a2"], v["a3"], v["a4"], v["a7"], v["a8"]) == (0, 0, 0, 0, 0)
    assert v["a1"] == pytest.approx(a1(after), abs=5e-5)  # замер округляет до 4 знаков
    capsys.readouterr()
    quality_main(["--baseline", str(base)], url=database_url)
    lines = capsys.readouterr().out.strip().splitlines()
    rows = [
        line for line in lines if line.startswith("А") or line[:2] in {f"A{i}" for i in range(1, 9)}
    ]
    assert len(lines) >= 10 and len([line for line in lines if " | " in line]) == 9, (
        lines
    )  # шапка + 8
    measured = events.of("knowledge.quality.measured")
    assert len(measured) == 3 and measured[-1]["a8"] == 0
    _ = rows
    check_keys(events)


@req(OM, QM, scenario="А4 — объединение и решение «разные»")
def test_a4_union_and_distinct(onto, events, capsys, database_url):
    bacon = onto.entities.create("person", [("ru", "Бэкон", "primary")])
    francis = onto.entities.create(
        "person", [("ru", "Фрэнсис Бэкон", "primary"), ("ru", "Бэкон", "variant")]
    )
    roger = onto.entities.create(
        "person", [("ru", "Роджер Бэкон", "primary"), ("ru", "Бэкон", "variant")]
    )
    bacon2 = onto.entities.create("person", [("ru", "Бэкон", "primary")])
    with onto.statements.engine.begin() as conn:
        for pair, status, resolution in (
            ([bacon, francis], "open", None),
            ([roger, bacon2], "resolved", {"merge": False}),
        ):
            conn.execute(
                t.review_items.insert().values(
                    kind="duplicate",
                    status=status,
                    resolution=resolution,
                    payload={"pair": pair, "reason": "review:single_name"},
                )
            )
    _code, result = quality(capsys, database_url)
    state = State.read(onto.statements.engine)
    expected = a4_pairs(state)
    assert frozenset((bacon, francis)) in expected and frozenset((roger, bacon2)) not in expected
    assert values(result)["a4"] == len(expected)
    assert events.of("knowledge.quality.measured")[-1]["a4"] == len(expected)


@req(
    OM, QM, invariant="А4: основное одной в вариантах другой — пара, тёзки по общему варианту — нет"
)
def test_a4_primary_in_variants(onto, events, capsys, database_url):
    locke = onto.entities.create("person", [("ru", "Локк", "primary")])
    john = onto.entities.create(
        "person", [("ru", "Джон Локк", "primary"), ("ru", "Локк", "variant")]
    )
    francis = onto.entities.create(
        "person", [("ru", "Фрэнсис Бэкон", "primary"), ("ru", "Бэкон", "variant")]
    )
    roger = onto.entities.create(
        "person", [("ru", "Роджер Бэкон", "primary"), ("ru", "Бэкон", "variant")]
    )
    _code, result = quality(capsys, database_url)
    expected = a4_pairs(State.read(onto.statements.engine))
    assert expected == {frozenset((locke, john))}
    assert frozenset((francis, roger)) not in expected
    assert values(result)["a4"] == 1


def _philosophers(onto):
    for i, name in enumerate(("Кант", "Юм", "Локк")):
        p = raw_entity(onto, "person", [("ru", name, "primary")])
        add_dates(onto, p, str(1700 + i), str(1770 + i))
        add_role(onto, p)
    s = raw_entity(onto, "person", [("ru", "Ньютон", "primary")])
    add_dates(onto, s, "1643", "1727")
    add_role(onto, s, "scientist")
    add_role(onto, raw_entity(onto, "person", [("ru", "Сократ", "primary")]))
    raw_entity(onto, "concept", [("ru", "20.1", "primary")])


@req(OM, QM, scenario="А6 и А7 совпадают с API")
def test_a6_a7_match_api(onto, events, capsys, clock, database_url):
    _philosophers(onto)
    _code, result = quality(capsys, database_url)
    api = Surface(onto, clock)
    people = api.map()["people"]
    a6 = sum("philosopher" in p["roles"] for p in people)
    a7 = sum(reason_of(i["type"], i["label"]) is not None for i in api.catalog())
    v = values(result)
    assert v["a6"] == 3 == a6
    assert v["a7"] == a7 == 1
    assert events.of("knowledge.quality.measured")[-1]["a6"] == 3


@req(OM, QM, scenario="Без базы сравнения")
def test_without_baseline(onto, events, capsys, database_url):
    onto.entities.create("person", [("ru", "Кант", "primary")])
    capsys.readouterr()
    code = quality_main([], url=database_url)
    out = capsys.readouterr().out
    [row8] = [line for line in out.splitlines() if " | " in line][8:9]
    assert "не измерено" in row8 and "не выполнен" in row8
    assert out.strip().splitlines()[-1].endswith("не выполнен") and code == 1
    measured = events.of("knowledge.quality.measured")[-1]
    assert measured["a8"] is None and measured["passed"] is False and 8 in measured["failed"]
    check_keys(events)


@req(OM, QM, scenario="Только чтение")
def test_read_only(onto, events, capsys, database_url):
    stand(onto)
    before, files = dump(onto.statements.engine), db_files(database_url)
    mtimes = {
        p.name: p.stat().st_mtime_ns
        for p in Path(database_url.removeprefix("sqlite:///")).parent.glob("*.db")
    }
    quality(capsys, database_url)
    assert dump(onto.statements.engine) == before and db_files(database_url) == files
    assert {
        p.name: p.stat().st_mtime_ns
        for p in Path(database_url.removeprefix("sqlite:///")).parent.glob("*.db")
    } == mtimes
    ro = read_only_engine(database_url)
    with pytest.raises(Exception), ro.begin() as conn:  # noqa: B017 — любой отказ базы
        conn.execute(text(f"DELETE FROM {t.SCHEMA}.names"))
    assert dump(onto.statements.engine) == before
    assert events.of("knowledge.quality.measured")


@req(OM, QM, scenario="Старая схема")
def test_old_schema(tmp_path, events, capsys):
    from philograph.knowledge.registry import OntologyRegistry
    from philograph.platform.db import make_engine

    url = f"sqlite:///{(tmp_path / 'old.db').as_posix()}"
    engine = make_engine(url, [t.SCHEMA])
    with engine.begin() as conn:
        t.migrations._version_table.create(conn, checkfirst=True)
    for m in t.migrations._items:
        if m.version <= 8:
            with engine.begin() as conn:
                m.apply(conn)
                conn.execute(
                    t.migrations._version_table.insert().values(version=m.version, name=m.name)
                )
    with engine.begin() as conn:
        columns = [r[1] for r in conn.exec_driver_sql(f"PRAGMA {t.SCHEMA}.table_info(entities)")]
    if "retired_run" in columns:
        with engine.begin() as conn:
            conn.exec_driver_sql(f"ALTER TABLE {t.SCHEMA}.entities DROP COLUMN retired_run")
            conn.exec_driver_sql(f"ALTER TABLE {t.SCHEMA}.entities DROP COLUMN retired_reason")
    OntologyRegistry(engine).load_defaults()
    with engine.begin() as conn:
        version = conn.scalar(
            select(t.migrations._version_table.c.version)
            .order_by(t.migrations._version_table.c.version.desc())
            .limit(1)
        )
    t._HAS_RETIRED.clear()
    base = tmp_path / "before.json"
    code = quality_main(["--save", str(base)], url=url)
    assert code in (0, 1) and base.exists()
    with engine.begin() as conn:
        assert (
            conn.scalar(
                select(t.migrations._version_table.c.version)
                .order_by(t.migrations._version_table.c.version.desc())
                .limit(1)
            )
            == version
            == 8
        )
    assert events.of("knowledge.quality.measured")


@req(OM, QM, scenario="Инвариант замера")
@settings(PROFILES["ci"], **DB_SETTINGS)
@given(spec=ontologies(), migrate=hst.booleans())
@example(spec=SYMPTOMS_SPEC, migrate=True)
@example(spec=SYMPTOMS_SPEC, migrate=False)
def test_quality_invariant(
    onto, events, capsys, clock, database_url, tmp_path_factory, spec, migrate
):
    wipe(onto)
    world = build(onto, spec)
    base = tmp_path_factory.mktemp("q") / "before.json"
    quality(capsys, database_url, "--save", str(base))
    if migrate:
        Migration(
            onto.statements, None, RecordFetch(world.wd), FakeLLM.by_label(world.llm_table)
        ).run(manifest=world.manifest, translate="model")
    engine = onto.statements.engine
    before_dump, files = dump(engine), db_files(database_url)
    code, result = quality(capsys, database_url, "--baseline", str(base))
    assert dump(engine) == before_dump and db_files(database_url) == files
    state = State.read(engine)
    api = Surface(onto, clock)
    expected = {
        "a1": a1(state),
        "a2": a2(state),
        "a3": a3(state),
        "a4": len(a4_pairs(state)),
        "a5": a5(state),
        "a6": sum("philosopher" in p["roles"] for p in api.map()["people"]),
        "a7": sum(reason_of(i["type"], i["label"]) is not None for i in api.catalog()),
        "a8": 0,
    }
    got = values(result)
    assert got["a1"] == pytest.approx(expected["a1"], abs=5e-5)
    assert {k: got[k] for k in expected if k != "a1"} == {
        k: v for k, v in expected.items() if k != "a1"
    }
    passed = all(THRESHOLDS[k](got[k]) for k in THRESHOLDS)
    assert result["passed"] is passed and code == (0 if passed else 1)


# =========================== Приёмка П1–П4 (ведущий, О21) ==================================


@req(OM, QM, invariant="Приёмка: синтетика П1–П4 после миграции с фейковым переводом")
def test_acceptance_symptoms(onto, events, capsys, tmp_path, database_url):
    letters = "абвгдеклмнпрст"
    for i in range(24):  # ≥ 20 персон с датами, ≥ 10 философов
        name = "Ка" + letters[i % 14] + letters[(i // 14) % 14] + "ин"
        p = raw_entity(onto, "person", [("ru", name, "primary")])
        add_dates(onto, p, str(1600 + i), str(1660 + i))
        if i % 2 == 0:
            add_role(onto, p)
    table = {}
    for i in range(30):  # П1: латиница, часть с языком ru
        label = "notion" + "bcdfghklmnpqrstvz"[i % 17] + "bcdfg"[i // 17]
        table[label] = "Понятие" + letters[i % 14] + letters[i // 14] + "о"
        raw_entity(onto, "concept", [("ru" if i % 3 == 0 else "en", label, "primary")])
    for type_, label in GARBAGE:  # П2–П3: мусор
        raw_entity(onto, type_, [("en", label, "primary")])
    for _ in range(3):  # П4: дубли
        raw_entity(onto, "person", [("en", "Berkeley", "primary")])
    raw_entity(onto, "person", [("en", "Hume", "primary")], "Q41568")
    raw_entity(onto, "person", [("ru", "Юм", "primary")])
    table["Berkeley"] = "Беркли"
    base = tmp_path / "before.json"
    quality(capsys, database_url, "--save", str(base))
    report = migration(onto, llm=FakeLLM.by_label(table)).run(translate="model")
    code, result = quality(capsys, database_url, "--baseline", str(base))
    v = values(result)
    assert v["a1"] >= 0.90, v
    assert (v["a2"], v["a3"], v["a4"], v["a7"]) == (0, 0, 0, 0), v
    assert v["a5"] >= 20 and v["a6"] >= 10, v
    assert v["a8"] == 0 and report.statements["lost"] == 0
    assert code == 0 and result["passed"] is True
    _ = LATIN_CONCEPTS


# ============ О29: границы порогов, все страницы, обход после пропуска ====================
# Идентификаторы задаются явно: шаги обходят сущности в порядке идентификаторов, и пропуск
# должен стоять раньше элемента, который обязан обработаться (общее правило О26).


def _at(onto, eid: str, type_: str, names: list[tuple], qid: str | None = None) -> str:
    """Как ``raw_entity``, но с заданным идентификатором (порядок обхода)."""
    with onto.entities.engine.begin() as conn:
        conn.execute(t.entities.insert().values(id=eid, type=type_, primary={}, redirect_to=None))
        for lang, text_, kind in names:
            conn.execute(
                t.names.insert().values(
                    entity_id=eid,
                    lang=lang,
                    text=text_,
                    normalized=search_form(text_),
                    kind=kind,
                )
            )
        if qid:
            conn.execute(
                t.external_ids.insert().values(entity_id=eid, system="wikidata", value=qid)
            )
    return eid


def _open_item(onto, a: str, b: str, reason: str = "review:single_name") -> None:
    with onto.statements.engine.begin() as conn:
        conn.execute(
            t.review_items.insert().values(
                kind="duplicate",
                status="open",
                resolution=None,
                payload={"pair": [a, b], "reason": reason},
            )
        )


def _items(onto) -> list[dict]:
    with onto.statements.engine.begin() as conn:
        return [dict(r) for r in conn.execute(select(t.review_items)).mappings()]


def _pair_items(onto, a: str, b: str) -> list[dict]:
    return [i for i in _items(onto) if set(i["payload"]["pair"]) == {a, b}]


@req(OM, QM, invariant="Пороги «≥» включают границу: А1 = 0,90, А5 = 20, А6 = 10 — выполнено")
def test_thresholds_at_boundary(onto, events, capsys, tmp_path, database_url):
    letters = "абвгдеклмнпрст"
    for i in range(20):  # ровно 20 персон с основной датой, ровно 10 философов
        p = raw_entity(
            onto, "person", [("ru", "Ка" + letters[i % 14] + letters[i // 14] + "ин", "primary")]
        )
        add_dates(onto, p, str(1600 + i), str(1660 + i))
        if i % 2 == 0:
            add_role(onto, p)
    for i in range(6):  # 20 персон + 6 понятий + произведение = 27 русских из 30
        raw_entity(onto, "concept", [("ru", "Понятие" + letters[i] + "о", "primary")])
    for label in ("notionb", "notionc", "notiond"):  # А1 = 27/30 = 0,90 ровно
        raw_entity(onto, "concept", [("en", label, "primary")])
    work = raw_entity(onto, "work", [("ru", "Трактат о природе", "primary")])
    onto.statements.add(
        work, "dating", value=dates_parse("1739").to_json(), attributions=[Attribution("common")]
    )  # дата не у персоны — не в А5
    raw_entity(onto, "source", [("en", "3.1", "primary")])  # источник — не в А1
    base = tmp_path / "before.json"
    quality(capsys, database_url, "--save", str(base))
    capsys.readouterr()
    code = quality_main(["--baseline", str(base)], url=database_url)
    out = capsys.readouterr().out
    code_json, result = quality(capsys, database_url, "--baseline", str(base))
    v = values(result)
    assert v["a1"] == pytest.approx(0.90, abs=5e-5) and v["a5"] == 20 and v["a6"] == 10, v
    assert (v["a2"], v["a3"], v["a4"], v["a7"], v["a8"]) == (0, 0, 0, 0, 0), v
    assert result["passed"] is True and code == code_json == 0
    # таблица «критерий | значение | порог | итог»: у каждой строки критерия четыре столбца
    rows = [
        line for line in out.splitlines() if " | " in line and line.lstrip().startswith(("А", "A"))
    ]
    assert len(rows) == 8, out
    for row in rows:
        cells = [c.strip() for c in row.split(" | ")]
        assert len(cells) == 4, row
    thresholds = [c.split(" | ")[2].strip() for c in rows]
    assert [re.sub(r"[^0-9,.]", "", x).replace(",", ".") for x in thresholds] == [
        "0.9",
        "0",
        "0",
        "0",
        "20",
        "10",
        "0",
        "0",
    ], thresholds


@req(OM, QM, invariant="А7 — все страницы справочника")
def test_a7_all_pages(onto, events, capsys, clock, database_url):
    for i in range(61):  # больше страницы (60): хотя бы одна негодная — не на первой
        raw_entity(onto, "concept", [("ru", str(100 + i), "primary")])
    raw_entity(onto, "concept", [("ru", "Субстанция", "primary")])
    _code, result = quality(capsys, database_url)
    # правило number (entity-naming): нет букв, есть цифра
    api = sum(
        bool(re.search(r"\d", i["label"])) and not re.search(r"[^\W\d_]", i["label"])
        for i in Surface(onto, clock).catalog()
    )
    assert values(result)["a7"] == api == 61


@req(OM, QM, invariant="А8 считает и потерянные атрибуции")
def test_a8_counts_lost_attribution(onto, events, capsys, tmp_path, database_url):
    kant = raw_entity(onto, "person", [("ru", "Кант", "primary")])
    hume = raw_entity(onto, "person", [("ru", "Юм", "primary")])
    sid = add_statement(
        onto,
        kant,
        "influenced_by",
        hume,
        [Attribution("source", "s_a"), Attribution("source", "s_b")],
    )
    base = tmp_path / "before.json"
    quality(capsys, database_url, "--save", str(base))
    with onto.statements.engine.begin() as conn:  # «сбой»: одна атрибуция пропала
        conn.execute(
            delete(t.attributions).where(
                t.attributions.c.statement_id == sid, t.attributions.c.who == "s_b"
            )
        )
    _code, result = quality(capsys, database_url, "--baseline", str(base))
    assert values(result)["a8"] == 1


@req(OM, QM, invariant="А4: открытые пункты не-персон (review:same_name) в А4 не входят")
def test_a4_ignores_non_person_items(onto, events, capsys, database_url):
    a = raw_entity(onto, "concept", [("ru", "Субстанция", "primary")])
    b = raw_entity(onto, "concept", [("ru", "Субстанция", "primary")])
    _open_item(onto, a, b, "review:same_name")
    _code, result = quality(capsys, database_url)
    assert values(result)["a4"] == 0


@req(
    OM,
    MIG,
    invariant="Шаг 7: совпадения не-персон — в очередь review:same_name, персоны — нет",
)
def test_same_name_queue_after_skips(onto, events):
    # персона раньше всех (пропуск), пара «Материя» уже открыта (пропуск), затем «Субстанция»
    k1 = _at(onto, "e_000000000001", "person", [("ru", "Кант", "primary")], "Q9312")
    k2 = _at(onto, "e_000000000002", "person", [("ru", "Кант", "primary")], "Q9313")
    m1 = _at(onto, "e_000000000003", "concept", [("ru", "Материя", "primary")])
    m2 = _at(onto, "e_000000000004", "concept", [("ru", "Материя", "primary")])
    s1 = _at(onto, "e_000000000005", "concept", [("ru", "Субстанция", "primary")])
    s2 = _at(onto, "e_000000000006", "concept", [("ru", "Субстанция", "primary")])
    _open_item(onto, m1, m2)
    migration(onto).run()
    after = State.read(onto.statements.engine)
    assert after.resolve(s1) == s1 and after.resolve(s2) == s2  # без автослияния
    [queued] = _pair_items(onto, s1, s2)
    assert queued["status"] == "open" and queued["payload"]["reason"] == "review:same_name"
    assert len(_pair_items(onto, m1, m2)) == 1  # открытая пара повторно не ставится
    same = [i for i in _items(onto) if i["payload"].get("reason") == "review:same_name"]
    assert all(not ({k1, k2} & set(i["payload"]["pair"])) for i in same)


@req(OM, MIG, invariant="Шаг 2: обход кандидатов после пары, которая уже в очереди")
def test_pending_candidate_after_open_pair(onto, events, capsys, tmp_path):
    def pending(ids):
        return {
            "entities": [
                {
                    "entity": ids["omir"],
                    "wikidata": None,
                    "decision": "pending",
                    "candidates": [
                        {"qid": "Q41568", "holder": ids["hume"]},  # пара уже открыта
                        {"qid": "Q6691", "holder": ids["homer"]},
                    ],
                }
            ]
        }

    ids = stand(onto)
    _open_item(onto, ids["omir"], ids["hume"])
    path = write_manifest(tmp_path, pending(ids))
    code, _report = cli(onto, capsys, ["run", "--manifest", path])
    assert code == 0
    assert [i["status"] for i in _pair_items(onto, ids["omir"], ids["homer"])] == ["open"]
    assert [i["payload"]["reason"] for i in _pair_items(onto, ids["omir"], ids["homer"])] == [
        "review:qid_candidate"
    ]
    assert len(_pair_items(onto, ids["omir"], ids["hume"])) == 1


@req(OM, MIG, invariant="Шаг 1: в одной сущности после чистого названия нормализуется следующее")
def test_normalize_after_clean_name(onto, events):
    e = raw_entity(
        onto, "person", [("ru", "Кант", "primary"), ("ru", " Иммануил Кант ", "variant")]
    )
    migration(onto).run()
    after = State.read(onto.statements.engine)
    assert after.name_set(e) == {("ru", "Кант", "primary"), ("ru", "Иммануил Кант", "variant")}


@req(OM, MIG, invariant="Шаг 4: источники библиотеки не снимаются, обход после источника")
def test_source_not_retired(onto, events):
    src = _at(onto, "e_000000000001", "source", [("en", "3.1", "primary")])
    junk = _at(onto, "e_000000000002", "concept", [("ru", "20.1", "primary")])
    report = migration(onto).run()
    after = State.read(onto.statements.engine)
    assert src in after.active() and junk not in after.active()
    assert [x["id"] for x in report.to_json()["retired_list"]] == [junk]


@req(OM, MIG, invariant="Событие шага: dry_run = true в plan, false в run")
def test_step_event_dry_run(onto, events):
    stand(onto)
    migration(onto).plan()
    planned = events.of("knowledge.migration.step")
    assert planned and all(e["dry_run"] is True for e in planned)
    events.clear()
    migration(onto).run()
    ran = events.of("knowledge.migration.step")
    assert ran and all(e["dry_run"] is False for e in ran)


@req(
    OM,
    TR,
    invariant="Шаг 5: подпись ru Wikidata — только русская и годная; обход после сбоя и отказа",
)
def test_wikidata_labels_after_skips(onto, events):
    records = {
        "Q900001": record("Q900001", ru="Ошибка", en="Fail", classes=HUMAN),
        "Q900002": record("Q900002", ru="Hobbes", en="Hobbes", classes=HUMAN),  # латиница
        "Q900003": record("Q900003", ru="20.1", en="Twenty", classes=HUMAN),  # number
        "Q41568": record("Q41568", ru="Юм", en="Hume", classes=HUMAN),
    }
    a = _at(onto, "e_000000000001", "person", [("en", "Failer", "primary")], "Q900001")
    b = _at(onto, "e_000000000002", "person", [("en", "Hobbes", "primary")], "Q900002")
    c = _at(onto, "e_000000000003", "concept", [("en", "twenty", "primary")], "Q900003")
    d = _at(onto, "e_000000000004", "person", [("en", "Hume", "primary")], "Q41568")
    report = migration(onto, fetch=RecordFetch(records, failing=["Q900001"])).run()
    after = State.read(onto.statements.engine)
    assert (after.label(a), after.label(b), after.label(c), after.label(d)) == (
        "Failer",
        "Hobbes",
        "twenty",
        "Юм",
    )
    assert report.to_json()["renamed"]["wikidata"] == 1


@req(OM, RB, invariant="Откат закрывает пункты очереди запуска (rolled_back), чужие — нет")
def test_rollback_closes_run_items(onto, events, capsys, tmp_path):
    ids = stand(onto)
    _open_item(onto, ids["kant"], ids["b1"])  # пункт человека до запуска
    before = {i["id"]: i["status"] for i in _items(onto)}
    s1 = raw_entity(onto, "concept", [("ru", "Материя", "primary")])
    s2 = raw_entity(onto, "concept", [("ru", "Материя", "primary")])
    m = migration(onto, llm=FakeLLM.by_label(TWO))
    report = m.run(translate="model")
    created = [i for i in _items(onto) if i["id"] not in before]
    assert any(set(i["payload"]["pair"]) == {s1, s2} for i in created)
    m.rollback(report.run_id)
    now = {i["id"]: i["status"] for i in _items(onto)}
    assert all(now[i["id"]] == "rolled_back" for i in created), now
    assert {k: now[k] for k in before} == before


@req(OM, RB, invariant="Откат не отменяет слияния, сделанные после запуска человеком")
def test_rollback_keeps_later_merge(onto, events):
    ids = stand(onto)
    a = raw_entity(onto, "person", [("ru", "Фалес", "primary")])
    b = raw_entity(onto, "person", [("ru", "Фалес Милетский", "primary")])
    m = migration(onto, llm=FakeLLM.by_label(TWO))
    report = m.run(translate="model")
    onto.statements.merge_entities(a, b)  # оператор, после запуска
    m.rollback(report.run_id)
    after = State.read(onto.statements.engine)
    assert after.resolve(b) == a
    assert after.resolve(ids["hume"]) == ids["hume"]


@req(OM, MIG, invariant="--limit N — предел только для перевода, прочие шаги не затронуты")
def test_limit_only_translation(onto, events):
    ids = _concepts(onto, ["causality", "substance", "idea"])
    junk = [raw_entity(onto, "concept", [("ru", label, "primary")]) for label in ("20.1", "3.2.1")]
    table = {"causality": "Причинность", "substance": "Субстанция", "idea": "Идея"}
    llm = FakeLLM.by_label(table)
    planned = migration(onto, llm=llm).plan(limit=1).to_json()
    assert planned["to_translate"] == 1 and len(planned["retired_list"]) == 2
    report = migration(onto, llm=llm).run(translate="model", limit=1).to_json()
    after = State.read(onto.statements.engine)
    assert report["to_translate"] == 1
    assert sum(is_ru(after.label(e)) for e in ids.values()) == 1
    assert all(j not in after.active() for j in junk)  # снятие не ограничено


@req(
    OM,
    MIG,
    invariant="Шаг 7: источники библиотеки с одинаковым названием в очередь не идут (О30, С3)",
)
def test_same_name_sources_not_queued(onto, events):
    a = _at(onto, "e_000000000001", "source", [("ru", "Хрестоматия", "primary")])
    b = _at(onto, "e_000000000002", "source", [("ru", "Хрестоматия", "primary")])
    c1 = _at(onto, "e_000000000003", "concept", [("ru", "Субстанция", "primary")])
    c2 = _at(onto, "e_000000000004", "concept", [("ru", "Субстанция", "primary")])
    migration(onto).run()
    assert _pair_items(onto, a, b) == []
    [queued] = _pair_items(onto, c1, c2)
    assert queued["payload"]["reason"] == "review:same_name"


@req(OM, MIG, invariant="Шаг 2: пара, закрытая человеком «разные», в очередь не идёт (О30, С4)")
def test_pending_candidate_distinct_not_queued(onto, events, capsys, tmp_path):
    ids = stand(onto)
    with onto.statements.engine.begin() as conn:
        conn.execute(
            t.review_items.insert().values(
                kind="duplicate",
                status="resolved",
                resolution={"merge": False},
                payload={"pair": [ids["omir"], ids["homer"]], "reason": "review:single_name"},
            )
        )
    manifest = {
        "entities": [
            {
                "entity": ids["omir"],
                "wikidata": None,
                "decision": "pending",
                "candidates": [{"qid": "Q6691", "holder": ids["homer"]}],
            }
        ]
    }
    code, _report = cli(onto, capsys, ["run", "--manifest", write_manifest(tmp_path, manifest)])
    assert code == 0
    items = _pair_items(onto, ids["omir"], ids["homer"])
    assert [i["status"] for i in items] == ["resolved"]
    events.assert_none("knowledge.entity.merge_proposed")


# ============ О31: поздние названия при откате, отрицательный --limit, неизвестный run_id ==


@req(
    OM,
    RB,
    invariant="Откат удаляет только своё название; название человека после запуска остаётся, kept",
)
def test_rollback_keeps_later_added_name(onto, events):
    ids = _concepts(onto, ["causality"], lang="ru")
    m = migration(onto, llm=FakeLLM.by_label(TWO))
    report = m.run(translate="model")
    e = ids["causality"]
    onto.entities.add_name(e, "ru", "Казуальность")
    events.clear()
    m.rollback(report.run_id)
    after = State.read(onto.statements.engine)
    assert ("ru", "Казуальность", "variant") in after.name_set(e)
    assert ("ru", "Причинность", "primary") not in after.name_set(e)
    assert events.one("knowledge.migration.rolled_back")["kept"] == 1
    check_keys(events)


@req(OM, RB, invariant="Откат: название, пришедшее слиянием другого запуска, остаётся, kept")
def test_rollback_keeps_name_from_later_merge(onto, events):
    ids = _concepts(onto, ["causality"], lang="ru")
    m = migration(onto, llm=FakeLLM.by_label(TWO))
    report = m.run(translate="model")
    e = ids["causality"]
    other = raw_entity(onto, "concept", [("ru", "Каузальность", "primary")])
    onto.statements.merge_entities(e, other, run_id="later_run")
    events.clear()
    m.rollback(report.run_id)
    after = State.read(onto.statements.engine)
    assert after.resolve(other) == e
    assert any(text_ == "Каузальность" for _l, text_, _k in after.name_set(e))
    assert events.one("knowledge.migration.rolled_back")["kept"] == 1


@req(OM, MIG, invariant="Отрицательный --limit отклоняется с ненулевым кодом до любых изменений")
@pytest.mark.parametrize("command", ["plan", "run"])
def test_negative_limit_rejected(onto, events, capsys, command):
    stand(onto)
    before = dump(onto.statements.engine)
    llm = FakeLLM.by_label(TWO)
    argv = [command, "--limit", "-1"] + (["--translate", "model"] if command == "run" else [])
    try:
        code, _ = cli(onto, capsys, argv, llm=llm)
    except SystemExit as exc:  # отказ разбора аргументов — тоже ненулевой код
        code = exc.code
    assert code not in (0, None)
    assert dump(onto.statements.engine) == before and llm.calls == []
    events.assert_none("knowledge.migration.step")


@req(OM, RB, invariant="Откат неизвестного run_id — ненулевой код, сообщение, без изменений")
def test_rollback_unknown_run(onto, events, capsys):
    stand(onto)
    before = dump(onto.statements.engine)
    capsys.readouterr()
    try:
        code = main(
            ["rollback", "mig_doesnotexist"],
            fetch=RecordFetch(WD),
            llm=None,
            service=lambda fetch_, llm_: Migration(onto.statements, None, fetch_, llm_),
        )
    except SystemExit as exc:
        code = exc.code
    out = capsys.readouterr()
    assert code not in (0, None)
    assert (out.out + out.err).strip()
    assert dump(onto.statements.engine) == before
    events.assert_none("knowledge.migration.rolled_back")


LATER = "бвгдежзклмнп"


@req(OM, RB, invariant="Инвариант отката: произвольные последующие изменения сохраняются")
@settings(PROFILES["heavy"], **DB_SETTINGS)
@given(spec=ontologies(), data=hst.data())
@example(spec=SYMPTOMS_SPEC, data=None)
def test_rollback_keeps_arbitrary_later_names(onto, events, spec, data):
    wipe(onto)
    world = build(onto, spec)
    engine = onto.statements.engine
    pre = State.read(engine)
    m = Migration(onto.statements, None, RecordFetch(world.wd), FakeLLM.by_label(world.llm_table))
    report = m.run(manifest=world.manifest, translate="model")
    mid = State.read(engine)
    active = mid.active()
    if data is None:  # явный пример: позднее название у каждой переименованной
        chosen = sorted({r["id"] for r in report.renamed_list} & set(active))
    else:
        chosen = (
            data.draw(hst.lists(hst.sampled_from(active), unique=True, max_size=4))
            if active
            else []
        )
    later = {}
    for i, e in enumerate(chosen):
        later[e] = f"Позднее имя {LATER[i % len(LATER)]}{LATER[i // len(LATER)]}"
        onto.entities.add_name(e, "ru", later[e])
    events.clear()
    m.rollback(report.run_id)
    after = State.read(engine)
    for e, text_ in later.items():
        assert ("ru", text_, "variant") in after.name_set(e), (e, after.name_set(e))
    renamed = {r["id"] for r in report.renamed_list}
    [rolled] = events.of("knowledge.migration.rolled_back")
    assert rolled["kept"] >= len(renamed & set(later))
    # сущности без последующих изменений откатываются полностью
    for e in pre.entities:
        if e not in later:
            assert after.name_set(e) == pre.name_set(e), e


@req(
    OM,
    MIG,
    invariant="Сбой посреди запуска: failed, run_id в stderr, код 1, откат по run_id ⇒ дамп (О32)",
)
def test_failure_mid_run(onto, events, capsys, monkeypatch, tmp_path):
    stand(onto)
    before = dump(onto.statements.engine)
    original = onto.statements.merge_entities
    calls: list[int] = []

    def broken(kept, removed, **kw):  # первое слияние проходит, второе — исключение
        if calls:
            raise RuntimeError("Zq7Marker сбой")
        calls.append(1)
        return original(kept, removed, **kw)

    monkeypatch.setattr(onto.statements, "merge_entities", broken)
    capsys.readouterr()
    code = main(
        ["run", "--translate", "model"],
        fetch=RecordFetch(WD),
        llm=FakeLLM.by_label(TWO),
        service=lambda fetch_, llm_: Migration(onto.statements, None, fetch_, llm_),
    )
    err = capsys.readouterr().err
    monkeypatch.undo()
    assert code == 1 and calls
    assert dump(onto.statements.engine) != before  # шаги до сбоя записаны
    [failed] = events.of("knowledge.migration.failed")
    assert set(failed.fields) - NOISE == {"run_id", "dry_run", "error", "error_kind"}
    assert failed["error_kind"] == "exception" and failed["dry_run"] is False
    assert "Zq7Marker" not in json.dumps(dict(failed.fields), ensure_ascii=False, default=str)
    run_id = failed["run_id"]
    assert run_id in err and f"rollback {run_id}" in err
    events.assert_none("knowledge.migration.run")
    code, _ = cli(onto, capsys, ["rollback", run_id])
    assert code == 0
    assert dump(onto.statements.engine) == before
