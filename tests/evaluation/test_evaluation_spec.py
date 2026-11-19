"""Нормативные правила и непокрытые утверждения THEN: evaluation-datasets, quality-evaluation."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from philograph.evaluation import components as c
from philograph.evaluation.datasets import Datasets, migrations
from philograph.evaluation.datasets import items as dataset_items
from philograph.evaluation.runs import (
    Evaluator,
    agreement,
    assistant_metrics,
    router_metrics,
    run_items,
    search_metrics,
)

from ..assistant.conftest import bot  # noqa: F401
from ..search.conftest import rig as search_rig  # noqa: F401
from .test_evaluation import AssistantStub, SearchStub, _Response, ev, questions  # noqa: F401

req = pytest.mark.req
ED = "evaluation-datasets"
QE = "quality-evaluation"


@pytest.fixture
def light(engine_for, clock):
    """Наборы и прогоны без сервисов: чистая логика хранения."""
    engine = engine_for(migrations)
    datasets = Datasets(engine, clock)
    return SimpleNamespace(
        engine=engine,
        datasets=datasets,
        evaluator=Evaluator(engine, datasets, code_version="sha", clock=clock),
    )


def ds(light, *payloads, kind="questions", name="набор"):
    dataset = light.datasets.create(name, kind)
    for i, payload in enumerate(payloads):
        light.datasets.add(dataset, f"q{i}", payload)
    return dataset


# --- evaluation-datasets -------------------------------------------------------------


@req(ED, "Виды наборов", invariant="вид набора из перечня, остальные отклоняются")
@pytest.mark.parametrize(
    "kind", ["questions", "mentions", "statements", "ocr_pages", "ontology_questions"]
)
def test_every_listed_kind_is_accepted(light, kind, events):
    dataset = light.datasets.create(f"набор {kind}", kind)
    light.datasets.add(dataset, "i1", {"x": 1})
    assert light.datasets.snapshot(dataset)[0]["x"] == 1
    assert events.one("evaluation.dataset.changed")["change"] == "add"


@req(ED, "Виды наборов", invariant="вид набора из перечня, остальные отклоняются")
@pytest.mark.parametrize("kind", ["", "Questions", "question", "ontology", " questions"])
def test_unknown_kind_rejected(light, kind, events):
    with pytest.raises(ValueError):
        light.datasets.create("плохой", kind)
    assert events.of("evaluation.dataset.changed") == []


@req(
    ED,
    "Версии наборов",
    invariant="каждое изменение создаёт новую версию, прежние версии сохраняются",
)
def test_every_change_bumps_version_and_keeps_old(light, events):
    dataset = light.datasets.create("набор", "questions")
    light.datasets.add(dataset, "a", {"question": "a", "relevant": ["p1", "p2"]}, status="draft")
    assert light.datasets.version(dataset) == 1
    light.datasets.decide(dataset, "a", "confirm", "op", {"question": "a", "relevant": ["p1"]})
    assert light.datasets.version(dataset) == 2
    light.datasets.add(dataset, "b", {"question": "b"})
    light.datasets.decide(dataset, "b", "reject", "op")
    assert light.datasets.version(dataset) == 4
    assert [(e["version"], e["change"]) for e in events.of("evaluation.dataset.changed")] == [
        (1, "add"),
        (2, "confirm"),
        (3, "add"),
        (4, "reject"),
    ]
    # Версия 1: только черновик с двумя абзацами; версия 2: подтверждённый с одним.
    v1 = light.datasets.snapshot(dataset, 1, include_drafts=True)
    assert [(i["status"], i["relevant"]) for i in v1] == [("draft", ["p1", "p2"])]
    v2 = light.datasets.snapshot(dataset, 2)
    assert [(i["status"], i["relevant"]) for i in v2] == [("confirmed", ["p1"])]
    assert [i["item_id"] for i in light.datasets.snapshot(dataset, 3)] == ["a", "b"]
    assert [i["item_id"] for i in light.datasets.snapshot(dataset, 4)] == ["a"]


@req(ED, "Версии наборов", invariant="прогон ссылается на конкретную версию набора")
def test_run_pins_dataset_version(light, events):
    dataset = ds(light, {"question": "a"}, {"question": "b"})
    first = light.evaluator.run("search", dataset, {}, lambda i: {"found": []}, search_metrics)
    light.datasets.add(dataset, "q9", {"question": "c"})
    second = light.evaluator.run("search", dataset, {}, lambda i: {"found": []}, search_metrics)
    assert [light.evaluator.get(r)["dataset_version"] for r in (first, second)] == [2, 3]
    with light.engine.begin() as conn:
        counts = [
            len(conn.execute(select(run_items).where(run_items.c.run_id == r)).all())
            for r in (first, second)
        ]
    assert counts == [2, 3]  # первый прогон остался на двух элементах
    assert [e["items"] for e in events.of("evaluation.run.finished")] == [2, 3]


@req(
    ED,
    "Разметка человеком",
    invariant="каждое решение записывается с автором и временем",
)
@pytest.mark.parametrize("decision, status", [("confirm", "confirmed"), ("reject", "rejected")])
def test_decision_records_author_and_time(light, clock, events, decision, status):
    dataset = light.datasets.create("разметка", "questions")
    light.datasets.add(dataset, "q", {"question": "x", "relevant": ["p"]}, status="draft")
    with light.engine.begin() as conn:
        draft = conn.execute(select(dataset_items)).mappings().one()
    assert draft["decided_by"] is None and draft["decided_at"] is None  # черновик не решён
    clock.advance(hours=3)
    light.datasets.decide(dataset, "q", decision, "alice")
    with light.engine.begin() as conn:
        rows = conn.execute(select(dataset_items).where(dataset_items.c.removed.is_(None)))
        current = rows.mappings().one()
    assert current["status"] == status and current["decided_by"] == "alice"
    assert current["decided_at"].replace(tzinfo=None) == clock.now().replace(tzinfo=None)
    assert events.where("evaluation.dataset.changed", change=decision)[0]["version"] == 2


@req(ED, "Разметка человеком", invariant="по отсутствующему элементу решение не записывается")
def test_decision_on_unknown_item_changes_nothing(light, events):
    dataset = ds(light, {"question": "a"})
    before = light.datasets.version(dataset)
    with pytest.raises(Exception):  # noqa: B017 — тип ошибки хранилища не задан спецификацией
        light.datasets.decide(dataset, "нет такого", "confirm", "op")
    assert light.datasets.version(dataset) == before
    assert events.where("evaluation.dataset.changed", change="confirm") == []


@req(
    ED,
    "Черновая разметка моделью",
    invariant="неподтверждённая разметка не участвует в метриках, число в отчёте",
)
def test_draft_enters_metrics_only_after_human_confirmation(light, events):
    dataset = light.datasets.create("черновики", "questions")
    for n in range(3):
        light.datasets.add(
            dataset, f"d{n}", {"question": f"q{n}", "relevant": ["p"]}, status="draft"
        )
    seen = []

    def evaluate(item):
        seen.append(item["item_id"])
        return {"found": ["p"]}

    first = light.evaluator.run("search", dataset, {}, evaluate, search_metrics)
    assert seen == [] and light.evaluator.get(first)["unconfirmed"] == 3
    assert light.evaluator.get(first)["metrics"]["mrr"] is None
    assert events.of("evaluation.run.finished")[-1]["unconfirmed"] == 3
    light.datasets.decide(dataset, "d0", "confirm", "op")
    light.datasets.decide(dataset, "d1", "reject", "op")
    second = light.evaluator.run("search", dataset, {}, evaluate, search_metrics)
    assert seen == ["d0"]  # подтверждённый вошёл, отклонённый и черновик нет
    assert light.evaluator.get(second)["unconfirmed"] == 1
    assert light.evaluator.get(second)["metrics"]["mrr"] == 1.0
    last = events.of("evaluation.run.finished")[-1]
    assert (last["items"], last["unconfirmed"]) == (1, 1)


@req(
    ED,
    "Черновая разметка моделью",
    invariant="черновик хранится с пометкой «черновик»; тип, кандидаты и эталон от модели",
)
def test_model_draft_stored_marked_and_on_strong_filling(ev, events):
    dataset = ev.datasets.create("черновики", "questions")
    ev.bot.model.routes.append({"type": "genesis", "relevant": [1, 99, 0], "answer": "Эталон."})
    c.draft_questions(ev.datasets, dataset, ev.llm, ev.search, ["почему привычка ума?"])
    draft = ev.datasets.snapshot(dataset, include_drafts=True)[0]
    assert draft["status"] == "draft" and draft["type"] == "genesis"
    assert len(draft["relevant"]) == 1  # индексы вне выдачи (99, 0) код отбросил
    call = next(x for x in ev.bot.gateway.store.calls() if x["operation"] == "draft")
    assert call["role"] == "strong" and call["budget"] == "filling"
    assert call["template"] == "evaluation.draft.question"
    assert events.one("evaluation.dataset.changed")["change"] == "add"
    assert ev.datasets.snapshot(dataset) == []  # в метрики не идёт


class Resolver:
    def __init__(self, table):
        self.table = table

    def __call__(self, paragraph_id):
        return self.table.get(paragraph_id, {"status": "removed"})


@req(
    ED,
    "Ссылки на абзацы в наборах",
    invariant="удалённые и перенаправленные абзацы показываются с затронутыми элементами",
)
def test_broken_references_listed_per_item_and_logged(light, events):
    dataset = ds(
        light,
        {"question": "a", "relevant": ["ok", "gone"]},
        {"question": "b", "relevant": ["moved"]},
        {"question": "c", "relevant": ["ok"]},
        {"question": "d"},  # без размеченных абзацев
    )
    light.datasets.add(dataset, "draft", {"question": "e", "relevant": ["gone"]}, status="draft")
    resolver = Resolver(
        {
            "ok": {"status": "found"},
            "moved": {"status": "found", "redirected": True},
            "gone": {"status": "removed"},
        }
    )
    broken = light.datasets.broken_references(dataset, resolver)
    assert broken == [
        {"item_id": "draft", "paragraph_id": "gone", "status": "removed"},
        {"item_id": "q0", "paragraph_id": "gone", "status": "removed"},
        {"item_id": "q1", "paragraph_id": "moved", "status": "redirected"},
    ]
    logged = events.of("evaluation.reference.broken")
    assert sorted((e["item_id"], e["paragraph_id"], e["status"]) for e in logged) == sorted(
        (b["item_id"], b["paragraph_id"], b["status"]) for b in broken
    )
    assert all(e["dataset"] == "набор" for e in logged)


@req(ED, "Ссылки на абзацы в наборах", invariant="целые ссылки не порождают предупреждений")
def test_intact_references_silent(light, events):
    dataset = ds(light, {"question": "a", "relevant": ["ok"]}, {"question": "b"})
    assert light.datasets.broken_references(dataset, Resolver({"ok": {"status": "found"}})) == []
    events.assert_none("evaluation.reference.broken")


@req(
    ED,
    "Отделение от данных продукта",
    invariant="эталонные ответы не используются ассистентом и не попадают в индексы",
)
def test_reference_answer_never_reaches_assistant(ev, events):
    phrase = "уникальнаяфразаэталонаюм"
    dataset = questions(
        ev,
        {
            "question": "Что Юм говорил о причинности?",
            "reference": f"Эталон: {phrase}.",
            "has_answer": True,
        },
    )
    item = ev.datasets.snapshot(dataset)[0]
    ev.bot.model.answers.append(["Юм говорил о привычке [1]. "])
    result = c.assistant_evaluator(ev.assistant)(item)
    assert result["fragments"]
    assert phrase not in json.dumps(result, ensure_ascii=False)
    prompts = " ".join(m.content for r in ev.bot.model.requests for m in r.messages)
    assert phrase not in prompts  # ни в одном запросе к модели
    found = ev.search.post("search", json={"query": phrase}).json()["results"]
    assert all(phrase not in r["text"] for r in found)
    assert events.of("search.query.completed")


# --- quality-evaluation --------------------------------------------------------------


@req(QE, "Прогон оценки", invariant="прогон записывает результат по каждому элементу набора")
def test_run_stores_result_per_item_with_cost_and_time(light, clock, events):
    dataset = ds(light, {"question": "a", "relevant": ["p"]}, {"question": "b", "relevant": ["q"]})
    run = light.evaluator.run(
        "search",
        dataset,
        {"limit": 7, "model": "strong-1"},
        lambda i: {"found": ["p"], "cost_usd": 0.01},
        search_metrics,
    )
    row = light.evaluator.get(run)
    assert row["component"] == "search" and row["code_version"] == "sha"
    assert row["settings"] == {"limit": 7, "model": "strong-1"}
    assert row["dataset_id"] == dataset and row["dataset_version"] == 2
    assert row["cost_usd"] == 0.02 and row["started_at"] and row["finished_at"]
    with light.engine.begin() as conn:
        stored = conn.execute(select(run_items).where(run_items.c.run_id == run)).mappings().all()
    assert {r["item_id"]: r["result"]["found"] for r in stored} == {"q0": ["p"], "q1": ["p"]}
    finished = events.one("evaluation.run.finished")
    assert finished["cost_usd"] == 0.02 and finished["run_id"] == run


@req(QE, "Метрики поиска", invariant="recall@k и MRR считаются только по вопросам с разметкой")
@pytest.mark.parametrize(
    "relevant, found, recall1, recall5, recall10, mrr",
    [
        (["a"], [], 0.0, 0.0, 0.0, 0.0),  # ничего не найдено
        (["a"], ["a"], 1.0, 1.0, 1.0, 1.0),
        (["a", "b"], ["x", "a"], 0.0, 0.5, 0.5, 0.5),  # ранг 2
        (["a"], ["x", "y", "z", "w", "v", "a"], 0.0, 0.0, 1.0, round(1 / 6, 4)),  # за границей k=5
        (["a", "b", "c", "d"], ["a", "b", "c", "d"], 0.25, 1.0, 1.0, 1.0),
    ],
)
def test_search_metric_boundaries(relevant, found, recall1, recall5, recall10, mrr):
    metrics = search_metrics([({"item_id": "x", "relevant": relevant}, {"found": found})])
    assert (metrics["recall@1"], metrics["recall@5"], metrics["recall@10"]) == (
        recall1,
        recall5,
        recall10,
    )
    assert metrics["mrr"] == mrr


@req(
    QE,
    "Метрики поиска",
    invariant="recall@k и MRR считаются только по вопросам с разметкой",
    nolog="чистая функция расчёта, события нет",
)
def test_search_metrics_skip_unlabelled_questions():
    rows = [
        ({"item_id": "a", "relevant": ["p"]}, {"found": ["p"]}),
        ({"item_id": "b", "relevant": []}, {"found": ["p"]}),  # без разметки (нет ответа)
        ({"item_id": "c"}, {"found": ["p"]}),
    ]
    metrics = search_metrics(rows)
    assert metrics["mrr"] == 1.0 and list(metrics["per_item"]) == ["a"]
    empty = search_metrics([({"item_id": "b", "relevant": []}, {"found": []})])
    assert empty["mrr"] is None and empty["recall@5"] is None
    custom = search_metrics(rows[:1], ks=(2, 3))
    assert {"recall@2", "recall@3"} <= set(custom) and "recall@5" not in custom


@req(QE, "Метрики маршрутизатора", invariant="матрица: сколько вопросов каждого типа к какому типу")
def test_router_confusion_counts(light, events):
    expected = ["genesis", "genesis", "genesis", "knowledge"]
    got = ["genesis", "knowledge", "knowledge", "knowledge"]
    dataset = ds(light, *[{"question": f"q{i}", "type": t} for i, t in enumerate(expected)])
    answers = iter(got)
    run = light.evaluator.run(
        "router", dataset, {}, lambda i: {"type": next(answers)}, router_metrics
    )
    metrics = light.evaluator.get(run)["metrics"]
    assert metrics["confusion"] == {
        "genesis": {"genesis": 1, "knowledge": 2},
        "knowledge": {"knowledge": 1},
    }
    assert metrics["accuracy"] == 0.5
    assert events.one("evaluation.run.finished")["component"] == "router"
    assert router_metrics([])["accuracy"] is None


@req(QE, "Метрики ассистента", invariant="правильность отказов считается по вопросам без ответа")
@pytest.mark.parametrize(
    "stream, expected",
    [
        ([{"type": "no_answer"}, {"type": "done", "stats": {}}], 1.0),
        ([{"type": "refused"}, {"type": "done", "stats": {}}], 1.0),
        (
            [
                {"type": "fragment", "text": "выдумка", "citations": []},
                {"type": "done", "stats": {}},
            ],
            0.0,
        ),
    ],
)
def test_refusal_correctness_from_stream(light, events, stream, expected):
    class Stub:
        def stream(self, method, path, json):
            self.body = json
            return _Response({}, stream)

    stub = Stub()
    dataset = ds(light, {"question": "Что ел Кант на завтрак?", "has_answer": False})
    run = light.evaluator.run(
        "assistant", dataset, {}, c.assistant_evaluator(stub), assistant_metrics
    )
    assert (
        stub.body["sources_only"] is True
    )  # вопрос без ответа идёт в режиме «только по источникам»
    assert light.evaluator.get(run)["metrics"]["refusal_correctness"] == expected
    assert events.one("evaluation.run.finished")["component"] == "assistant"


@req(QE, "Метрики ассистента", invariant="правильность отказов считается по вопросам без ответа")
def test_refusal_not_counted_on_answerable_questions():
    rows = [({"item_id": "a", "has_answer": True}, {"refused": True, "fragments": []})]
    assert assistant_metrics(rows)["refusal_correctness"] is None


@req(
    QE,
    "Метрики ассистента",
    invariant="доля корректных ссылок: ссылка вне переданных абзацев не засчитана",
)
def test_citation_correctness_counts_wrong_links():
    fragments = [
        {"citations": [{"paragraph_id": "p1"}, {"paragraph_id": "zzz"}]},
        {"citations": [{"paragraph_id": "p1"}]},
    ]
    rows = [({"item_id": "a"}, {"fragments": fragments, "passed": ["p1"]})]
    assert assistant_metrics(rows)["citation_correctness"] == round(2 / 3, 4)


@req(
    QE,
    "Метрики ассистента",
    invariant="доля использованных подходящих источников и точность пометки неподтверждённого",
)
def test_sources_used_and_marking_precision():
    fragments = [
        {
            "citations": [{"paragraph_id": "p1", "source_id": "s1"}],
            "grounded": True,
            "should_be_grounded": True,
        },
        {"citations": [], "grounded": True, "should_be_grounded": False},
    ]
    rows = [
        ({"item_id": "a", "relevant_sources": ["s1", "s2"]}, {"fragments": fragments}),
    ]
    metrics = assistant_metrics(rows)
    assert metrics["sources_used"] == 0.5 and metrics["marking_precision"] == 0.5


@req(
    QE,
    "Оценщик на сильной модели",
    invariant="результат оценщика хранится с обоснованием и фрагментом",
)
@pytest.mark.xfail(
    strict=True, reason="дефект: assistant_evaluator отбрасывает fragment из ответа оценщика"
)
def test_judge_fragment_kept_in_run_result(light, events):
    class StubJudge:
        def faithful(self, question, answer, passages):
            return {"verdict": False, "reason": "не подтверждено", "fragment": "ФРАГМЕНТ-777"}

        def quality(self, question, answer):
            return {"verdict": True, "reason": "ок"}

    lines = [
        {
            "type": "fragment",
            "text": "Платон",
            "citations": [{"paragraph_id": "p", "title": "т", "source_id": "s"}],
        },
        {"type": "done", "stats": {}},
    ]

    class Stub:
        def stream(self, method, path, json):
            return _Response({}, lines)

    dataset = ds(light, {"question": "q", "has_answer": True})
    run = light.evaluator.run(
        "assistant", dataset, {}, c.assistant_evaluator(Stub(), StubJudge()), assistant_metrics
    )
    with light.engine.begin() as conn:
        stored = conn.execute(select(run_items).where(run_items.c.run_id == run)).mappings().one()
    assert stored["result"]["faithful"] is False and stored["result"]["faithful_reason"]
    assert "ФРАГМЕНТ-777" in json.dumps(stored["result"], ensure_ascii=False)
    assert events.one("evaluation.run.finished")["items"] == 1


@req(
    QE,
    "Оценщик на сильной модели",
    invariant="оценщик идёт на роли «сильная» из бюджета «наполнение»",
)
def test_judge_quality_template_role_and_budget(ev, events):
    ev.bot.model.routes.append({"verdict": True, "reason": "полный ответ", "fragment": ""})
    verdict = c.Judge(ev.llm).quality("вопрос", "ответ")
    assert verdict["verdict"] is True and verdict["reason"] == "полный ответ"
    call = next(x for x in ev.bot.gateway.store.calls() if x["operation"] == "judge")
    assert (call["role"], call["budget"]) == ("strong", "filling")
    assert call["template"] == "evaluation.judge.quality" and call["template_version"]
    assert events.of("llm.call.completed")  # вызов виден в журнале шлюза моделей


@req(
    QE,
    "Согласие оценщика с человеком",
    invariant="согласие считается по общим оценкам; расхождения перечислены",
    nolog="чистая функция расчёта, события нет",
)
def test_agreement_only_over_common_items():
    judge = {f"a{i}": i % 2 == 0 for i in range(30)}
    human = {f"a{i}": True for i in range(30)}
    human["лишний"] = False
    result = agreement(judge, human)
    assert result["items"] == 30 and result["agreement"] == 0.5
    assert result["disagreements"] == sorted(f"a{i}" for i in range(30) if i % 2)
    assert agreement({"a": True}, {"b": True}) == {
        "items": 0,
        "agreement": None,
        "disagreements": [],
    }


@req(
    QE,
    "Согласие оценщика с человеком",
    invariant="метрики оценщика показываются с долей согласия рядом",
)
@pytest.mark.xfail(
    strict=True, reason="дефект: метрики ассистента с оценщиком не содержат долю согласия"
)
def test_judge_metrics_shown_with_agreement(light, events):
    dataset = ds(light, {"question": "q", "has_answer": True})
    run = light.evaluator.run(
        "assistant",
        dataset,
        {},
        lambda i: {"fragments": [], "faithful": True, "quality": True},
        assistant_metrics,
    )
    metrics = light.evaluator.get(run)["metrics"]
    assert metrics["faithfulness"] == 1.0
    assert any("agreement" in key for key in metrics)
    assert events.one("evaluation.run.finished")["items"] == 1


@req(
    QE,
    "Сравнение прогонов",
    invariant="разные версии набора сопровождаются предупреждением, одна версия — без",
)
def test_compare_warning_only_on_version_mismatch(light, events):
    dataset = ds(
        light, {"question": "a", "relevant": ["p1"]}, {"question": "b", "relevant": ["p2"]}
    )
    other = ds(light, {"question": "z", "relevant": ["p1"]}, name="другой")
    results = {"p1": ["p1"], "none": []}
    first = light.evaluator.run(
        "search", dataset, {}, lambda i: {"found": results["p1"]}, search_metrics
    )
    second = light.evaluator.run(
        "search", dataset, {}, lambda i: {"found": results["none"]}, search_metrics
    )
    same = light.evaluator.compare(first, second)
    assert same["warning"] is None and same["diff"]["mrr"] == -0.5
    assert same["worse"] == ["q0"] and same["better"] == []  # q0 был 1.0 и стал 0.0
    events.assert_none("evaluation.compare.version_mismatch")
    third = light.evaluator.run("search", other, {}, lambda i: {"found": ["p1"]}, search_metrics)
    mismatch = light.evaluator.compare(first, third)
    assert mismatch["warning"]
    assert events.one("evaluation.compare.version_mismatch")["run_a"] == first
    dataset_version = light.datasets.version(dataset)
    light.datasets.add(dataset, "q9", {"question": "c", "relevant": ["p3"]})
    assert light.datasets.version(dataset) == dataset_version + 1
    fourth = light.evaluator.run("search", dataset, {}, lambda i: {"found": []}, search_metrics)
    assert light.evaluator.compare(first, fourth)["warning"]


@req(
    QE,
    "Повторимость",
    invariant="метрики те же, кроме метрик оценщика и задержки",
)
def test_repeat_run_same_metrics_except_latency_and_judge(light, events):
    dataset = ds(light, {"question": "a", "has_answer": False})
    latency = iter([10, 999])
    judged = iter([True, False])

    def evaluate(item):
        return {
            "refused": True,
            "fragments": [],
            "first_fragment_ms": next(latency),
            "total_ms": 50,
            "faithful": next(judged),
        }

    a = light.evaluator.run("assistant", dataset, {}, evaluate, assistant_metrics)
    b = light.evaluator.run("assistant", dataset, {}, evaluate, assistant_metrics)
    ma, mb = (light.evaluator.get(r)["metrics"] for r in (a, b))
    volatile = {"first_fragment_ms", "total_ms", "faithfulness", "quality", "per_item"}
    assert {k: v for k, v in ma.items() if k not in volatile} == {
        k: v for k, v in mb.items() if k not in volatile
    }
    assert ma["faithfulness"] != mb["faithfulness"]
    assert len(events.of("evaluation.run.finished")) == 2


@req(QE, "Стоимость прогона", invariant="оценка стоимости до запуска, ничего не вызывая")
def test_estimate_does_not_run_anything(light, events):
    dataset = ds(light, *[{"question": f"q{i}"} for i in range(200)])
    called = []
    estimate = light.evaluator.estimate("assistant", dataset, 0.01)
    assert estimate == {"items": 200, "estimate_usd": 2.0}
    assert called == [] and events.of("evaluation.run.finished") == []
    logged = events.one("evaluation.estimate")
    assert (logged["component"], logged["items"], logged["estimate_usd"]) == ("assistant", 200, 2.0)
    light.datasets.add(dataset, "d", {"question": "черновик"}, status="draft")
    assert (
        light.evaluator.estimate("assistant", dataset, 0.01)["items"] == 200
    )  # черновик не считается
