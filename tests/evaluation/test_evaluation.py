"""Требования спецификаций evaluation-datasets и quality-evaluation."""

from __future__ import annotations

import json

import pytest

from philograph.assistant.app import build_app as assistant_app
from philograph.evaluation import components as c
from philograph.evaluation.datasets import Datasets, migrations
from philograph.evaluation.runs import (
    Evaluator,
    agreement,
    assistant_metrics,
    ocr_metrics,
    ontology_metrics,
    router_metrics,
    search_metrics,
)
from philograph.library.quality import error_rates
from philograph.platform.client import ServiceClient
from philograph.search.app import build_app as search_app

from ..assistant.conftest import bot  # noqa: F401
from ..helpers import asgi_transport
from ..search.conftest import rig as search_rig  # noqa: F401

req = pytest.mark.req
ED = "evaluation-datasets"
QE = "quality-evaluation"


@pytest.fixture
def ev(bot, engine_for, clock):
    engine = engine_for(migrations)
    datasets = Datasets(engine, clock)
    evaluator = Evaluator(engine, datasets, code_version="test-sha", clock=clock)
    search = ServiceClient(
        "search",
        "http://search",
        transport=asgi_transport(search_app(bot.rig.searcher, bot.rig.indexer)),
    )
    assistant = ServiceClient(
        "assistant", "http://assistant", transport=asgi_transport(assistant_app(bot.assistant))
    )
    llm = bot.assistant.llm.client
    return type(
        "Ev",
        (),
        {
            "datasets": datasets,
            "evaluator": evaluator,
            "search": search,
            "assistant": assistant,
            "llm": llm,
            "bot": bot,
        },
    )


def questions(ev, *items):
    dataset = ev.datasets.create("вопросы", "questions")
    for i, item in enumerate(items):
        ev.datasets.add(dataset, f"q{i}", item)
    return dataset


@req(ED, "Виды наборов")
def test_dataset_kinds(ev):
    for kind in ("questions", "mentions", "statements", "ocr_pages", "ontology_questions"):
        ev.datasets.create(f"набор {kind}", kind)
    with pytest.raises(ValueError):
        ev.datasets.create("плохой", "anything")
    dataset = questions(
        ev, {"question": "Что такое добродетель у стоиков?", "relevant": [], "has_answer": False}
    )
    item = ev.datasets.snapshot(dataset)[0]
    assert item["has_answer"] is False and item["relevant"] == []


@req(ED, "Версии наборов")
def test_dataset_versions(ev, events):
    dataset = questions(ev, {"question": "a"}, {"question": "b"}, {"question": "c"})
    assert ev.datasets.version(dataset) == 3
    run = ev.evaluator.run("search", dataset, {}, lambda item: {"found": []}, search_metrics)
    ev.datasets.add(dataset, "q9", {"question": "d"})
    assert ev.evaluator.get(run)["dataset_version"] == 3
    assert len(ev.datasets.snapshot(dataset, 3)) == 3 and len(ev.datasets.snapshot(dataset)) == 4
    assert events.of("evaluation.dataset.changed")[-1]["version"] == 4


@req(ED, "Черновая разметка моделью")
def test_model_drafts_not_in_metrics(ev, events):
    dataset = ev.datasets.create("черновики", "questions")
    ev.bot.model.routes.append({"type": "knowledge", "relevant": [1], "answer": "Привычка."})
    added = c.draft_questions(
        ev.datasets, dataset, ev.llm, ev.search, ["что Юм считал причинностью?"]
    )
    assert added == 1
    draft = ev.datasets.snapshot(dataset, include_drafts=True)[0]
    assert draft["status"] == "draft" and draft["relevant"] and draft["reference"] == "Привычка."
    run = ev.evaluator.run("search", dataset, {}, c.search_evaluator(ev.search), search_metrics)
    assert ev.evaluator.get(run)["unconfirmed"] == 1
    assert events.one("evaluation.run.finished")["items"] == 0


@req(ED, "Разметка человеком")
def test_human_decisions(ev):
    dataset = ev.datasets.create("разметка", "questions")
    ev.datasets.add(dataset, "q1", {"question": "x", "relevant": ["p1", "p2"]}, status="draft")
    ev.datasets.decide(dataset, "q1", "confirm", "operator", {"question": "x", "relevant": ["p1"]})
    item = ev.datasets.snapshot(dataset)[0]
    assert item["relevant"] == ["p1"] and item["status"] == "confirmed"
    ev.datasets.add(dataset, "q2", {"question": "y"}, status="draft")
    ev.datasets.decide(dataset, "q2", "reject", "operator")
    assert [i["item_id"] for i in ev.datasets.snapshot(dataset)] == ["q1"]


@req(ED, "Ссылки на абзацы в наборах")
def test_broken_paragraph_references(ev, events):
    rig = ev.bot.rig
    gone = rig.paragraph("ru", "Хьюм")
    kept = rig.paragraph("ru", "привычка ума")
    dataset = questions(ev, {"question": "q", "relevant": [gone, kept]})
    rig.files["ru.txt"] = rig.files["ru.txt"].replace(
        "Хьюм в старых переводах — тот же Юм.".encode(),
        "Совершенно другой абзац о стоиках и добродетели.".encode(),
    )
    rig.publish("ru")
    broken = ev.datasets.broken_references(dataset, rig.registry.resolve_paragraph)
    assert broken == [{"item_id": "q0", "paragraph_id": gone, "status": "removed"}]
    assert events.one("evaluation.reference.broken")["paragraph_id"] == gone


@req(ED, "Отделение от данных продукта")
def test_reference_answers_not_searchable(ev):
    reference = "Эталон: уникальнаяфразаэталона о добродетели."
    questions(ev, {"question": "q", "reference": reference})
    found = ev.search.post("search", json={"query": "уникальнаяфразаэталона"}).json()
    assert all("уникальнаяфразаэталона" not in r["text"] for r in found["results"])


@req(QE, "Прогон оценки")
def test_run_records_everything(ev, events):
    dataset = questions(ev, {"question": "привычка ума", "relevant": []})
    run_id = ev.evaluator.run(
        "search", dataset, {"limit": 10}, c.search_evaluator(ev.search), search_metrics
    )
    run = ev.evaluator.get(run_id)
    assert run["code_version"] == "test-sha" and run["settings"] == {"limit": 10}
    assert run["dataset_version"] == 1 and run["started_at"] and run["finished_at"]
    events.one("evaluation.run.finished")


@req(QE, "Метрики поиска")
def test_search_recall_and_mrr(ev):
    rig = ev.bot.rig
    target = rig.paragraph("ru", "проблема индукции")
    other = rig.paragraph("en", "blank slate")
    dataset = questions(
        ev, {"question": "почему из прошлого нельзя вывести будущее", "relevant": [target, other]}
    )
    run = ev.evaluator.run("search", dataset, {}, c.search_evaluator(ev.search), search_metrics)
    metrics = ev.evaluator.get(run)["metrics"]
    assert metrics["recall@5"] == 0.5 and metrics["mrr"] == 1.0
    assert (
        search_metrics(
            [({"item_id": "x", "relevant": ["a", "b"]}, {"found": ["c", "a", "d", "e", "f"]})]
        )["recall@5"]
        == 0.5
    )


@req(QE, "Метрики маршрутизатора")
def test_router_accuracy_and_confusion(ev):
    ev.bot.model.routes.extend(
        [
            {"type": "genesis", "confidence": 0.9, "names": []},
            {"type": "knowledge", "confidence": 0.9, "names": []},
        ]
    )
    dataset = questions(
        ev,
        {"question": "откуда идея?", "type": "genesis"},
        {"question": "что считал Юм?", "type": "other_authors"},
    )
    run = ev.evaluator.run("router", dataset, {}, c.router_evaluator(ev.assistant), router_metrics)
    metrics = ev.evaluator.get(run)["metrics"]
    assert metrics["accuracy"] == 0.5
    assert metrics["confusion"] == {"genesis": {"genesis": 1}, "other_authors": {"knowledge": 1}}


@req(QE, "Метрики ассистента")
def test_assistant_metrics(ev):
    ev.bot.model.answers.extend([["Юм говорил о привычке [1]. ", "Платон [42]. "]])
    dataset = questions(
        ev,
        {"question": "Что Юм говорил о причинности?", "has_answer": True},
        {"question": "добродетель благо стоики", "has_answer": False},
    )
    run = ev.evaluator.run(
        "assistant", dataset, {}, c.assistant_evaluator(ev.assistant), assistant_metrics
    )
    metrics = ev.evaluator.get(run)["metrics"]
    assert metrics["citation_correctness"] == 1.0  # оставшиеся ссылки проверены кодом
    assert metrics["refusal_correctness"] == 1.0  # честный отказ на вопросе без ответа
    assert metrics["total_ms"] is not None and metrics["first_fragment_ms"] is not None


@req(QE, "Метрики онтологии и распознавания")
def test_ocr_and_ontology_metrics():
    per_page = {0: error_rates("кот пишет", "кот пишет"), 1: error_rates("кит", "кот")}
    ocr = ocr_metrics(per_page)
    assert ocr["wer"] == 0.5 and ocr["cer"] == round((0 + round(1 / 3, 4)) / 2, 4)
    statements = [
        {"type": "критикует", "correct": True, "quote_supported": True},
        {"type": "критикует", "correct": False, "quote_supported": False},
        {"type": "учился у", "correct": True, "quote_supported": True, "duplicate": True},
    ]
    control = [({"item_id": "c1"}, True), ({"item_id": "c2"}, False)]
    onto = ontology_metrics(statements, control)
    assert onto["accuracy_by_type"] == {"критикует": 0.5, "учился у": 1.0}
    assert onto["control_coverage"] == 0.5 and onto["control_failed"] == ["c2"]
    assert onto["duplicate_share"] == round(1 / 3, 4)


@req(QE, "Оценщик на сильной модели")
def test_judge_on_strong_role(ev):
    ev.bot.model.routes.append(
        {"verdict": False, "reason": "фраза о Платоне не подтверждена", "fragment": "Платон"}
    )
    verdict = c.Judge(ev.llm).faithful("вопрос", "ответ", "абзацы")
    assert verdict["verdict"] is False and "Платон" in verdict["reason"]
    call = next(x for x in ev.bot.gateway.store.calls() if x["operation"] == "judge")
    assert call["role"] == "strong" and call["budget"] == "filling"
    assert call["template"] == "evaluation.judge.faithfulness" and call["template_version"]


@req(QE, "Согласие оценщика с человеком")
def test_judge_human_agreement():
    result = agreement({"a": True, "b": False, "c": True}, {"a": True, "b": True, "c": True})
    assert result == {"items": 3, "agreement": round(2 / 3, 4), "disagreements": ["b"]}


@req(QE, "Сравнение прогонов")
def test_compare_runs(ev, events):
    dataset = questions(
        ev, {"question": "a", "relevant": ["p1"]}, {"question": "b", "relevant": ["p2"]}
    )
    first = ev.evaluator.run("search", dataset, {}, lambda i: {"found": ["p1"]}, search_metrics)
    second = ev.evaluator.run("search", dataset, {}, lambda i: {"found": ["p2"]}, search_metrics)
    comparison = ev.evaluator.compare(first, second)
    assert comparison["better"] == ["q1"] and comparison["worse"] == ["q0"]
    assert comparison["warning"] is None and "mrr" in comparison["diff"]
    ev.datasets.add(dataset, "q5", {"question": "c", "relevant": ["p3"]})
    third = ev.evaluator.run("search", dataset, {}, lambda i: {"found": []}, search_metrics)
    assert ev.evaluator.compare(first, third)["warning"]
    events.one("evaluation.compare.version_mismatch")


@req(QE, "Повторимость")
def test_repeatable_search_metrics(ev):
    dataset = questions(
        ev, {"question": "привычка ума", "relevant": [ev.bot.rig.paragraph("ru", "привычка ума")]}
    )
    evaluate = c.search_evaluator(ev.search)
    a = ev.evaluator.run("search", dataset, {}, evaluate, search_metrics)
    b = ev.evaluator.run("search", dataset, {}, evaluate, search_metrics)
    ma, mb = ev.evaluator.get(a)["metrics"], ev.evaluator.get(b)["metrics"]
    assert (ma["recall@5"], ma["mrr"]) == (mb["recall@5"], mb["mrr"])


@req(QE, "Стоимость прогона")
def test_run_cost_estimate(ev, events):
    dataset = questions(ev, *[{"question": f"q{i}"} for i in range(4)])
    assert ev.evaluator.estimate("assistant", dataset, 0.002) == {"items": 4, "estimate_usd": 0.008}
    events.one("evaluation.estimate")
    run = ev.evaluator.run(
        "assistant", dataset, {}, lambda i: {"cost_usd": 0.001}, assistant_metrics
    )
    assert ev.evaluator.get(run)["cost_usd"] == 0.004


class _Response:
    """Ответ поддельного сервиса: и JSON, и поток событий."""

    def __init__(self, payload: dict, lines: list[dict]) -> None:
        self.payload, self.lines = payload, lines

    def json(self) -> dict:
        return self.payload

    def raise_for_status(self) -> None:
        return None

    def iter_lines(self):
        return iter(json.dumps(line, ensure_ascii=False) for line in self.lines)

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        return False


class SearchStub:
    def __init__(self) -> None:
        self.bodies: list[dict] = []

    def post(self, path: str, json: dict) -> _Response:
        self.bodies.append(json)
        return _Response({"results": []}, [])


class AssistantStub:
    def __init__(self) -> None:
        self.bodies: list[dict] = []

    def stream(self, method: str, path: str, json: dict) -> _Response:
        self.bodies.append(json)
        return _Response({}, [{"type": "done", "stats": {}}])


@req("regional-access", "Оценка и служебные запросы задают регион явно")
def test_evaluation_queries_carry_dataset_region(ev):
    """Набор хранит регион, и замеры идут от имени читателя этого региона."""
    dataset = ev.datasets.create("вопросы РФ", "questions", region="ru")
    assert ev.datasets.region(dataset) == "RU"
    ev.datasets.add(dataset, "q0", {"question": "что такое опыт?"})
    item = ev.datasets.snapshot(dataset)[0]
    assert item["region"] == "RU"

    search = SearchStub()
    c.search_evaluator(search, limit=3)(item)
    assert search.bodies[-1]["region"] == "RU"

    assistant = AssistantStub()
    c.assistant_evaluator(assistant)(item)
    assert assistant.bodies[-1]["region"] == "RU"

    # Набор без региона (и со служебным XX) идёт как из неизвестного региона.
    unknown = ev.datasets.create("вопросы без региона", "questions")
    ev.datasets.add(unknown, "q0", {"question": "что такое опыт?"})
    assert ev.datasets.snapshot(unknown)[0]["region"] is None
    c.search_evaluator(search, limit=3)(ev.datasets.snapshot(unknown)[0])
    assert search.bodies[-1]["region"] is None

    assert ev.datasets.region(ev.datasets.create("набор XX", "questions", region="XX")) is None
