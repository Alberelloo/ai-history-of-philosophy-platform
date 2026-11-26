"""Юнит-тесты ``knowledge.ontology_migrate`` (migrate-ontology-quality, задачи 2.3–2.4) на
фейковой модели и фикстурах Wikidata. Сценарные и нормативные тесты — у тестировщика."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from philograph.knowledge import run_actions
from philograph.knowledge import schema as ks
from philograph.knowledge.ontology_migrate import STEPS, Aborted, Migration, main
from philograph.knowledge.statements import Attribution
from tests.knowledge.dump import dump
from tests.knowledge.wd_records import RecordFetch, record


class Reply:
    def __init__(self, status: int, body: object) -> None:
        self.status_code, self._body = status, body

    def json(self) -> object:
        return self._body


class FakeLLM:
    """Шлюз моделей: ``replies`` — по пакету (список предложений или ``None`` — сбой)."""

    def __init__(self, replies=None, cost=0.002) -> None:
        self.replies = list(replies or [])
        self.calls: list[dict] = []
        self.cost = cost
        self.run_ids: list[str] = []

    def post(self, path, json):
        from philograph.platform import context

        self.calls.append(json)
        self.run_ids.append(context.run_id())
        reply = self.replies.pop(0) if self.replies else []
        if reply is None:
            return Reply(503, {"kind": "unavailable"})
        return Reply(200, {"value": {"translations": reply}})

    def get(self, path, params=None):
        return Reply(200, [{"run_id": r, "cost_usd": self.cost} for r in self.run_ids])


def items_of(call):
    return json.loads(call["data"]["items"])


_n = iter(range(1, 10**6))


def raw(onto, type_, names, qid=None):
    """Сущность «старых данных» — в обход правила названий, как на стенде до миграции."""
    from philograph.knowledge.naming import normalize

    entity_id = f"e_raw{next(_n):06d}"
    with onto.entities.engine.begin() as conn:
        conn.execute(
            ks.entities.insert().values(id=entity_id, type=type_, primary={}, redirect_to=None)
        )
        for lang, text, kind in names:
            conn.execute(
                ks.names.insert().values(
                    entity_id=entity_id, lang=lang, text=text, normalized=normalize(text), kind=kind
                )
            )
        if qid:
            conn.execute(
                ks.external_ids.insert().values(entity_id=entity_id, system="wikidata", value=qid)
            )
    return entity_id


class Raw:
    def __init__(self, onto) -> None:
        self.onto = onto

    def create(self, type_, names, external=None):
        return raw(self.onto, type_, names, (external or {}).get("wikidata"))


def build(onto):
    e, add = Raw(onto), onto.statements.add
    ids = {
        "causality": e.create("concept", [("ru", "causality", "primary")]),
        "num": e.create("concept", [("ru", "20.1", "primary")]),
        "every": e.create("term", [("en", "Every", "primary")]),
        "lord": e.create("person", [("en", "your Lordship", "primary")]),
        "b1": e.create("person", [("en", "Berkeley", "primary")]),
        "b2": e.create("person", [("en", "Berkeley", "primary")]),
        "hume": e.create("person", [("en", "Hume", "primary")], external={"wikidata": "Q41568"}),
        "yum": e.create("person", [("ru", "Юм", "primary")]),
        "homer": e.create("person", [("ru", "Гомер", "primary")], external={"wikidata": "Q6691"}),
        "omir": e.create("person", [("ru", "Омир", "primary")]),
        "kant": e.create("person", [("ru", "Кант", "primary")]),
    }
    src = [Attribution("source", "s1")]
    add(ids["kant"], "studied_with", obj=ids["b1"], attributions=src)
    add(ids["kant"], "studied_with", obj=ids["b2"], attributions=src)
    add(ids["kant"], "studied_with", obj=ids["lord"], attributions=src)
    add(
        ids["kant"],
        "studied_with",
        obj=ids["hume"],
        attributions=[Attribution("entity", ids["lord"])],
    )
    add(ids["yum"], "studied_with", obj=ids["kant"], attributions=src)
    return ids


WD = {"Q41568": record("Q41568", ru="Юм", en="Hume", classes=("Q5",))}


def migration(onto, llm=None, fetch=None):
    return Migration(onto.statements, None, fetch or RecordFetch(WD), llm)


def manifest(ids, decision="accepted"):
    entry = {
        "entity": ids["omir"],
        "wikidata": None if decision == "pending" else "Q6691",
        "decision": decision,
        "candidates": [{"qid": "Q6691", "holder": ids["homer"]}],
    }
    return {"entities": [entry]}


def primary(onto, entity_id):
    return [n["text"] for n in onto.entities.get(entity_id)["names"] if n["kind"] == "primary"]


def test_run_full_then_rollback(onto, events):
    ids = build(onto)
    engine = onto.entities.engine
    before = dump(engine)
    llm = FakeLLM([[{"n": 1, "ru": "Причинность"}]])
    report = migration(onto, llm).run(manifest=manifest(ids), translate="model")
    data = report.to_json()
    assert data["retired"] == {"not_a_name": 1, "number": 1, "stopword": 1}
    assert primary(onto, ids["causality"]) == ["Причинность"]
    assert primary(onto, ids["hume"]) == ["Юм"]
    assert onto.entities.resolve(ids["yum"]) == onto.entities.resolve(ids["hume"])
    assert onto.entities.resolve(ids["b1"]) == onto.entities.resolve(ids["b2"])
    assert onto.entities.resolve(ids["omir"]) == ids["homer"]
    assert data["renamed"] == {"wikidata": 1, "model": 1}
    assert data["statements"]["lost"] == 0 and data["attributions"]["lost"] == 0
    assert data["statements"]["dropped_garbage"] == 1  # Кант → your Lordship
    assert data["a1"]["after"] > data["a1"]["before"]
    # Модели не передан «Hume»: его назвала Wikidata.
    assert "Hume" not in [i["label"] for i in items_of(llm.calls[0])]
    steps = [e["step"] for e in events.where("knowledge.migration.step")]
    assert steps == list(STEPS)
    reasons = sorted(e["reason"] for e in events.where("knowledge.entity.merged"))
    assert reasons == ["merge:name", "merge:name", "merge:qid_confirmed"]
    summary = migration(onto).rollback(report.run_id)
    assert dump(engine) == before
    assert (summary["merges_undone"], summary["restored"], summary["kept"]) == (3, 3, 0)


def test_plan_equals_run_without_translation(onto, events):
    ids = build(onto)
    engine = onto.entities.engine
    before = dump(engine)
    llm = FakeLLM()
    plan = migration(onto, llm).plan(manifest=manifest(ids))
    assert dump(engine) == before and llm.calls == []
    run = migration(onto).run(manifest=manifest(ids))
    strip = lambda r: {k: v for k, v in r.to_json().items() if k not in ("run_id", "dry_run")}  # noqa: E731
    assert strip(plan) == strip(run)
    logged = [
        {k: v for k, v in a["payload"].items() if k != "names_before"}
        for a in run_actions.actions(engine, run.run_id)
        if a["kind"] != "external"
    ]
    planned = [a.to_json() for a in plan.actions if a.kind != "external"]
    assert logged == planned
    assert plan.to_translate == 3 and plan.batches == 1  # causality, Berkeley×2


def test_translation_checks_in_order(onto, events):
    e = Raw(onto)
    ids = [
        e.create("concept", [("en", w, "primary")])
        for w in ("causality", "substance", "idea", "mind")
    ]
    reply = [
        {"n": 1, "ru": "Причинность"},
        {"n": 2, "ru": "Substanz"},
        {"n": 2, "ru": "Субстанция"},
        {"n": 7, "ru": "Ум"},
        {"n": 3, "ru": "some"},
    ]
    report = Migration(onto.statements, None, None, FakeLLM([reply])).run(translate="model")
    assert primary(onto, ids[0]) == ["Причинность"]
    assert [primary(onto, i) for i in ids[1:]] == [["substance"], ["idea"], ["mind"]]
    assert report.to_json()["untranslated"] == {
        "duplicate_item": 2,
        "missing": 1,
        "not_russian": 1,
        "unknown_item": 1,
    }
    event = events.where("knowledge.migration.translated")[0]
    assert (event["accepted"], event["rejected"]) == (1, 4)


def test_estimate_one_call_and_failed_batch(onto, events):
    e = Raw(onto)
    for i in range(120):
        e.create("concept", [("en", f"term{chr(97 + i % 26)}{chr(97 + i // 26)}", "primary")])
    engine = onto.entities.engine
    before = dump(engine)
    llm = FakeLLM([[]], cost=0.01)
    report = Migration(onto.statements, None, None, llm).plan(estimate=True)
    assert len(llm.calls) == 1 and dump(engine) == before
    assert report.batches == 3 and report.estimate_usd == pytest.approx(0.03)
    failed = Migration(onto.statements, None, None, FakeLLM([None, [], []])).run(translate="model")
    assert failed.failed_batches == 1


def test_no_model_without_flag(onto, events):
    build(onto)
    llm = FakeLLM()
    report = migration(onto, llm).run()
    assert llm.calls == [] and report.to_translate == 3
    assert not events.where("knowledge.migration.translated")


def test_pending_holder_goes_to_queue_and_rollback_closes(onto, events):
    ids = build(onto)
    report = migration(onto).run(manifest=manifest(ids, "pending"))
    assert onto.entities.resolve(ids["omir"]) == ids["omir"]
    assert events.where("knowledge.entity.merge_proposed", reason="review:qid_candidate")
    migration(onto).rollback(report.run_id)
    with onto.entities.engine.begin() as conn:
        statuses = {r.status for r in conn.execute(select(ks.review_items))}
    assert "open" not in statuses


def test_rollback_keeps_later_rename(onto, events):
    ids = build(onto)
    report = migration(onto, FakeLLM([[{"n": 1, "ru": "Причинность"}]])).run(translate="model")
    onto.entities.set_primary_name(ids["causality"], "ru", "Каузальность")
    summary = migration(onto).rollback(report.run_id)
    assert summary["kept"] == 1
    assert primary(onto, ids["causality"]) == ["Каузальность"]


def test_loss_aborts_and_rolls_back(onto, events, monkeypatch):
    from sqlalchemy import delete

    ids = build(onto)
    engine = onto.entities.engine
    before = dump(engine)
    original = Migration._step_dedupe

    def lossy(self, view, report, **kw):
        found = original(self, view, report, **kw)
        with engine.begin() as conn:
            row = conn.execute(
                select(ks.attributions.c.id)
                .join(ks.statements, ks.statements.c.id == ks.attributions.c.statement_id)
                .where(ks.statements.c.object == ids["kant"])  # «Юм → Кант»
            ).scalar()
            conn.execute(delete(ks.attributions).where(ks.attributions.c.id == row))
        return found

    monkeypatch.setattr(Migration, "_step_dedupe", lossy)
    with pytest.raises(Aborted):
        migration(onto).run()
    aborted = events.where("knowledge.migration.aborted")[0]
    assert aborted["lost_attributions"] >= 1
    assert events.where("knowledge.migration.rolled_back", run_id=aborted["run_id"])
    # Удалённую подменой строку откат не вернёт; прочее — как было.
    after = dump(engine)
    assert {k: v for k, v in after.items() if k != "attributions"} == {
        k: v for k, v in before.items() if k != "attributions"
    }


def test_no_names_in_events(onto, events):
    e = Raw(onto)
    e.create("concept", [("en", "Zq7Marker idea", "primary")])
    e.create("person", [("en", "Zq7Marker", "primary")])
    e.create("person", [("en", "Zq7Marker", "primary")])
    m = Migration(onto.statements, None, None, FakeLLM([[{"n": 1, "ru": "Идея"}]]))
    m.plan()
    report = m.run(translate="model")
    m.rollback(report.run_id)
    assert "Zq7Marker" not in json.dumps(
        [vars(x) if hasattr(x, "__dict__") else str(x) for x in events.items],
        ensure_ascii=False,
        default=str,
    )


def test_cli_bad_batch_and_manifest(tmp_path, capsys):
    def service(fetch, llm):
        raise AssertionError("база до проверки аргументов")

    assert main(["plan", "--batch", "0"], service=service) == 2
    bad = tmp_path / "m.yaml"
    bad.write_text("entities:\n- entity: e1\n  decision: accepted\n", encoding="utf-8")
    assert main(["run", "--manifest", str(bad)], service=service) == 2


KANT = {
    "Q9312": record(
        "Q9312",
        ru="Кант",
        en="Kant",
        classes=("Q5",),
        times={"P569": ("+1724-04-22T00:00:00Z", 11), "P570": ("+1804-02-12T00:00:00Z", 11)},
    )
}


def _kant_manifest(ids):
    return {"entities": [{"entity": ids["kant"], "wikidata": "Q9312", "decision": "accepted"}]}


@pytest.mark.parametrize("keep", ["verified", "other_run", None])
def test_rollback_manifest_qid_by_life_dates_rule(onto, events, keep):
    """О20: откат шага ``manifest_qids`` — правило ``LifeDates``: QID, на который ссылается
    проверенное утверждение или утверждение другого запуска, остаётся и идёт в ``kept``."""
    from philograph.knowledge.statements import Provenance

    ids = build(onto)
    m = migration(onto, fetch=RecordFetch({**WD, **KANT}))
    report = m.run(manifest=_kant_manifest(ids))
    assert onto.entities.by_external("wikidata", "Q9312") == ids["kant"]
    if keep == "other_run":
        onto.statements.add(
            ids["kant"],
            "description",
            value="другой запуск",
            attributions=[Attribution("source", "wikidata:Q9312")],
            provenance=Provenance("imported", run_id="other"),
        )
    if keep == "verified":
        with onto.entities.engine.begin() as conn:
            conn.execute(
                ks.statements.update()
                .where(ks.statements.c.subject == ids["kant"])
                .where(ks.statements.c.type == "lifespan")
                .values(status="verified")
            )
    summary = migration(onto).rollback(report.run_id)
    kept_qid = onto.entities.by_external("wikidata", "Q9312") == ids["kant"]
    assert kept_qid is (keep is not None)
    assert summary["kept"] == (1 if keep else 0)
    [event] = events.where("knowledge.migration.rolled_back")
    assert event["kept"] == summary["kept"]


def _stale(onto, type_, text, normalized):
    """Название «старых данных»: сырой текст и устаревший ключ поиска."""
    entity_id = raw(onto, type_, [("ru", text, "primary")])
    with onto.entities.engine.begin() as conn:
        conn.execute(
            ks.names.update().where(ks.names.c.entity_id == entity_id).values(normalized=normalized)
        )
    return entity_id


def test_normalize_names_step_plan_run_rollback(onto, events):
    """О24: шаг ``normalize_names`` — strip+NFC и пересчёт ключа; сухой прогон — только
    проекция; откат возвращает прежние значения."""
    engine = onto.entities.engine
    nfd = "\u0418\u0306оганн"  # «Й» = «И» + U+0306 (NFD)
    johann = _stale(onto, "person", nfd, "иоганн-старый")
    kant = _stale(onto, "person", " Кант ", "кант-старый")
    assert onto.entities.find("Кант") == [] and onto.entities.find("Йоганн") == []
    before = dump(engine)
    plan = migration(onto).plan()
    assert dump(engine) == before
    assert plan.to_json()["names_normalized"] == 2
    assert plan.steps["normalize_names"] == 2
    report = migration(onto).run()
    assert report.to_json()["names_normalized"] == 2
    assert [e["id"] for e in onto.entities.find("Кант")] == [kant]
    assert [e["id"] for e in onto.entities.find("Йоганн")] == [johann]
    assert primary(onto, kant) == ["Кант"] and primary(onto, johann) == ["Йоганн"]
    steps = [e for e in events.where("knowledge.migration.step") if e["step"] == "normalize_names"]
    assert [e["actions"] for e in steps] == [2, 2]
    plan_actions = [a.to_json() for a in plan.actions if a.step == "normalize_names"]
    run_actions_ = [
        a["payload"]
        for a in run_actions.actions(engine, report.run_id, reverse=False)
        if a["kind"] == "name_text"
    ]
    assert plan_actions == [{"step": "normalize_names", "kind": "name_text", **p} for p in []] + [
        {**p} for p in run_actions_
    ]
    migration(onto).rollback(report.run_id)
    assert dump(engine) == before


def test_normalize_names_rollback_keeps_later_change(onto, events):
    kant = _stale(onto, "person", " Кант ", "кант-старый")
    report = migration(onto).run()
    with onto.entities.engine.begin() as conn:  # правка названия после запуска
        conn.execute(
            ks.names.update()
            .where(ks.names.c.entity_id == kant)
            .values(text="Иммануил Кант", normalized="иммануил кант")
        )
    summary = migration(onto).rollback(report.run_id)
    assert primary(onto, kant) == ["Иммануил Кант"]
    assert summary["kept"] == 1


def test_normalize_names_then_duplicate_merges(onto, events):
    """О24: « Кант » с устаревшим ключом после шага сливается с «Кант» (``merge:name``)."""
    engine = onto.entities.engine
    spaced = _stale(onto, "person", " Кант ", "кант-старый")
    plain = raw(onto, "person", [("ru", "Кант", "primary")])
    before = dump(engine)
    report = migration(onto).run()
    assert onto.entities.resolve(spaced) == onto.entities.resolve(plain)
    assert [e["reason"] for e in events.where("knowledge.entity.merged")] == ["merge:name"]
    migration(onto).rollback(report.run_id)
    assert dump(engine) == before
