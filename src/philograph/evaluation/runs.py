"""Прогоны оценки и метрики компонентов.

Прогон запоминает версию кода, настройки, версию набора, результат по каждому элементу и
итоговые метрики. Метрики считает код; то, что код посчитать не может (верность источникам,
качество ответа), считает оценщик на сильной модели, и рядом показывается его согласие с
человеком.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from typing import Any

from sqlalchemy import JSON, Column, DateTime, Engine, Float, Integer, String, Table, select

from philograph.evaluation.datasets import Datasets, metadata, migrations
from philograph.platform import events
from philograph.platform.clock import Clock, SystemClock

runs = Table(
    "runs",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("component", String(30), nullable=False),
    Column("code_version", String(40), nullable=False),
    Column("settings", JSON, nullable=False),
    Column("dataset_id", Integer, nullable=False),
    Column("dataset_version", Integer, nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("finished_at", DateTime(timezone=True)),
    Column("cost_usd", Float, nullable=False),
    Column("metrics", JSON),
    Column("unconfirmed", Integer, nullable=False),
    schema="evaluation",
)
run_items = Table(
    "run_items",
    metadata,
    Column("run_id", Integer, primary_key=True),
    Column("item_id", String(40), primary_key=True),
    Column("result", JSON, nullable=False),
    schema="evaluation",
)
migrations.add(2, "прогоны оценки")(migrations.create_tables("runs", "run_items"))

events.define(
    "evaluation.run.finished",
    "info",
    "Прогон оценки завершён",
    required=("run_id", "component", "items", "unconfirmed", "cost_usd"),
)
events.define(
    "evaluation.estimate",
    "info",
    "Оценка стоимости прогона",
    required=("component", "items", "estimate_usd"),
)
events.define(
    "evaluation.compare.version_mismatch",
    "warning",
    "Сравниваются прогоны на разных версиях набора",
    required=("run_a", "run_b"),
)


# --- метрики ------------------------------------------------------------------------


def search_metrics(rows: list[tuple[dict, dict]], ks: Iterable[int] = (1, 5, 10)) -> dict:
    """recall@k и MRR по вопросам с размеченными релевантными абзацами."""
    ks = list(ks)
    recall = {k: [] for k in ks}
    reciprocal = []
    per_item = {}
    for item, result in rows:
        relevant = set(item.get("relevant", []))
        if not relevant:
            continue
        found = result["found"]
        for k in ks:
            recall[k].append(len(relevant & set(found[:k])) / len(relevant))
        rank = next((i + 1 for i, pid in enumerate(found) if pid in relevant), None)
        reciprocal.append(1 / rank if rank else 0.0)
        per_item[item["item_id"]] = reciprocal[-1]
    mean = lambda xs: round(sum(xs) / len(xs), 4) if xs else None  # noqa: E731
    return {
        **{f"recall@{k}": mean(v) for k, v in recall.items()},
        "mrr": mean(reciprocal),
        "per_item": per_item,
    }


def router_metrics(rows: list[tuple[dict, dict]]) -> dict:
    confusion: dict[str, Counter] = defaultdict(Counter)
    correct = 0
    for item, result in rows:
        confusion[item["type"]][result["type"]] += 1
        correct += item["type"] == result["type"]
    return {
        "accuracy": round(correct / len(rows), 4) if rows else None,
        "confusion": {k: dict(v) for k, v in confusion.items()},
        "per_item": {i["item_id"]: float(i["type"] == r["type"]) for i, r in rows},
    }


def assistant_metrics(rows: list[tuple[dict, dict]]) -> dict:
    """Метрики ответов по результатам прогона и оценкам оценщика (если были)."""
    citations_ok = citations = 0
    marking_ok = marking = 0
    refusals_ok = refusals = 0
    used, available = 0, 0
    faithful, quality, first_ms, total_ms, cost = [], [], [], [], []
    per_item = {}
    for item, r in rows:
        for fragment in r.get("fragments", []):
            for c in fragment.get("citations", []):
                citations += 1
                citations_ok += c["paragraph_id"] in r.get("passed", [])
            if "should_be_grounded" in fragment:
                marking += 1
                marking_ok += fragment["grounded"] == fragment["should_be_grounded"]
        if not item.get("has_answer", True):
            refusals += 1
            refusals_ok += r.get("refused", False)
        relevant_sources = set(item.get("relevant_sources", []))
        if relevant_sources:
            available += len(relevant_sources)
            cited = {c["source_id"] for f in r.get("fragments", []) for c in f["citations"]}
            used += len(relevant_sources & cited)
        if "faithful" in r:
            faithful.append(float(r["faithful"]))
        if "quality" in r:
            quality.append(float(r["quality"]))
        first_ms.append(r.get("first_fragment_ms", 0))
        total_ms.append(r.get("total_ms", 0))
        cost.append(r.get("cost_usd", 0.0))
        per_item[item["item_id"]] = float(r.get("faithful", r.get("refused", False)))
    share = lambda a, b: round(a / b, 4) if b else None  # noqa: E731
    mean = lambda xs: round(sum(xs) / len(xs), 4) if xs else None  # noqa: E731
    return {
        "citation_correctness": share(citations_ok, citations),
        "faithfulness": mean(faithful),
        "marking_precision": share(marking_ok, marking),
        "refusal_correctness": share(refusals_ok, refusals),
        "sources_used": share(used, available),
        "quality": mean(quality),
        "first_fragment_ms": mean(first_ms),
        "total_ms": mean(total_ms),
        "cost_per_question_usd": mean(cost),
        "per_item": per_item,
    }


def ocr_metrics(per_page: dict[Any, dict[str, float]]) -> dict:
    count = len(per_page) or 1
    return {
        "cer": round(sum(r["cer"] for r in per_page.values()) / count, 4),
        "wer": round(sum(r["wer"] for r in per_page.values()) / count, 4),
        "per_item": {str(k): v["wer"] for k, v in per_page.items()},
    }


def ontology_metrics(statements: list[dict], control: list[tuple[dict, bool]]) -> dict:
    """Выборка утверждений с решениями человека и контрольные вопросы онтологии."""
    by_type: dict[str, list[bool]] = defaultdict(list)
    for s in statements:
        by_type[s["type"]].append(bool(s["correct"]))
    share = lambda xs: round(sum(xs) / len(xs), 4) if xs else None  # noqa: E731
    return {
        "accuracy_by_type": {t: share(v) for t, v in sorted(by_type.items())},
        "quote_supported": share([bool(s.get("quote_supported")) for s in statements]),
        "duplicate_share": share([bool(s.get("duplicate")) for s in statements]),
        "integrity_violation_share": share([bool(s.get("violation")) for s in statements]),
        "control_coverage": share([ok for _, ok in control]),
        "control_failed": [q["item_id"] for q, ok in control if not ok],
    }


# --- прогоны ------------------------------------------------------------------------


class Evaluator:
    def __init__(
        self, engine: Engine, datasets: Datasets, *, code_version: str, clock: Clock | None = None
    ) -> None:
        self.engine = engine
        self.datasets = datasets
        self.code_version = code_version
        self.clock = clock or SystemClock()

    def estimate(self, component: str, dataset_id: int, cost_per_item: float) -> dict:
        count = len(self.datasets.snapshot(dataset_id))
        estimate = round(count * cost_per_item, 6)
        events.emit("evaluation.estimate", component=component, items=count, estimate_usd=estimate)
        return {"items": count, "estimate_usd": estimate}

    def run(
        self,
        component: str,
        dataset_id: int,
        settings: dict[str, Any],
        evaluate: Callable[[dict], dict],
        metric: Callable[[list[tuple[dict, dict]]], dict],
    ) -> int:
        """Прогоняет компонент по подтверждённым элементам; черновики в метрики не идут."""
        version = self.datasets.version(dataset_id)
        elements = self.datasets.snapshot(dataset_id, version)
        unconfirmed = self.datasets.counts(dataset_id, version)["draft"]
        started = self.clock.now()
        rows = []
        cost = 0.0
        for item in elements:
            result = evaluate(item)
            cost += float(result.get("cost_usd", 0.0))
            rows.append((item, result))
        metrics = metric(rows)
        with self.engine.begin() as conn:
            run_id = conn.execute(
                runs.insert().values(
                    component=component,
                    code_version=self.code_version,
                    settings=settings,
                    dataset_id=dataset_id,
                    dataset_version=version,
                    started_at=started,
                    finished_at=self.clock.now(),
                    cost_usd=round(cost, 6),
                    metrics=metrics,
                    unconfirmed=unconfirmed,
                )
            ).inserted_primary_key[0]
            if rows:
                conn.execute(
                    run_items.insert(),
                    [{"run_id": run_id, "item_id": i["item_id"], "result": r} for i, r in rows],
                )
        events.emit(
            "evaluation.run.finished",
            run_id=run_id,
            component=component,
            items=len(rows),
            unconfirmed=unconfirmed,
            cost_usd=round(cost, 6),
        )
        return run_id

    def get(self, run_id: int) -> dict[str, Any]:
        with self.engine.begin() as conn:
            return dict(conn.execute(select(runs).where(runs.c.id == run_id)).mappings().one())

    def compare(self, run_a: int, run_b: int) -> dict[str, Any]:
        a, b = self.get(run_a), self.get(run_b)
        warning = None
        if (a["dataset_id"], a["dataset_version"]) != (b["dataset_id"], b["dataset_version"]):
            warning = "прогоны сделаны на разных версиях набора"
            events.emit("evaluation.compare.version_mismatch", run_a=run_a, run_b=run_b)
        diff = {}
        for key, value in b["metrics"].items():
            if isinstance(value, int | float) and isinstance(a["metrics"].get(key), int | float):
                diff[key] = round(value - a["metrics"][key], 4)
        pa, pb = a["metrics"].get("per_item", {}), b["metrics"].get("per_item", {})
        better = sorted(i for i in pb if i in pa and pb[i] > pa[i])
        worse = sorted(i for i in pb if i in pa and pb[i] < pa[i])
        return {"diff": diff, "better": better, "worse": worse, "warning": warning}


# --- оценщик и согласие с человеком -------------------------------------------------

JUDGE_SCHEMA = {
    "type": "object",
    "required": ["verdict", "reason"],
    "properties": {
        "verdict": {"type": "boolean"},
        "reason": {"type": "string"},
        "fragment": {"type": "string"},
    },
}


def agreement(judge: dict[str, bool], human: dict[str, bool]) -> dict[str, Any]:
    common = sorted(set(judge) & set(human))
    agree = [i for i in common if judge[i] == human[i]]
    return {
        "items": len(common),
        "agreement": round(len(agree) / len(common), 4) if common else None,
        "disagreements": [i for i in common if judge[i] != human[i]],
    }
