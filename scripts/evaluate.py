"""Прогон оценки оператором: ``python scripts/evaluate.py search <набор> [--compare <прогон>]``.

Компоненты вызываются по HTTP, как в работе: ``PHILOGRAPH_SEARCH_URL``,
``PHILOGRAPH_ASSISTANT_URL``, ``PHILOGRAPH_LLM_URL``; результаты — в ``PHILOGRAPH_DATABASE_URL``.
Перед прогоном с оценщиком печатается оценка стоимости.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess

from sqlalchemy import select

from philograph.evaluation import components as c
from philograph.evaluation.datasets import Datasets, datasets, migrations
from philograph.evaluation.runs import (
    Evaluator,
    assistant_metrics,
    router_metrics,
    search_metrics,
)
from philograph.platform.client import ServiceClient
from philograph.platform.db import make_engine


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("component", choices=["search", "router", "assistant"])
    parser.add_argument("dataset")
    parser.add_argument("--judge", action="store_true", help="оценщик на сильной модели")
    parser.add_argument("--cost-per-item", type=float, default=0.002)
    parser.add_argument("--compare", type=int, help="сравнить с прогоном")
    args = parser.parse_args()
    engine = make_engine(os.environ["PHILOGRAPH_DATABASE_URL"], [migrations.schema])
    migrations.upgrade(engine)
    store = Datasets(engine)
    with engine.begin() as conn:
        dataset_id = conn.scalar(select(datasets.c.id).where(datasets.c.name == args.dataset))
    sha = (
        subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=False
        ).stdout.strip()
        or "unknown"
    )
    evaluator = Evaluator(engine, store, code_version=sha)
    if args.component == "search":
        evaluate = c.search_evaluator(ServiceClient("search", os.environ["PHILOGRAPH_SEARCH_URL"]))
        metric = search_metrics
    elif args.component == "router":
        evaluate = c.router_evaluator(
            ServiceClient("assistant", os.environ["PHILOGRAPH_ASSISTANT_URL"])
        )
        metric = router_metrics
    else:
        judge = (
            c.Judge(ServiceClient("llm", os.environ["PHILOGRAPH_LLM_URL"], timeout=120))
            if args.judge
            else None
        )
        print(evaluator.estimate("assistant", dataset_id, args.cost_per_item))
        evaluate = c.assistant_evaluator(
            ServiceClient("assistant", os.environ["PHILOGRAPH_ASSISTANT_URL"], timeout=120), judge
        )
        metric = assistant_metrics
    run_id = evaluator.run(args.component, dataset_id, {"judge": args.judge}, evaluate, metric)
    metrics = {k: v for k, v in evaluator.get(run_id)["metrics"].items() if k != "per_item"}
    print(json.dumps({"run_id": run_id, **metrics}, ensure_ascii=False, indent=2))
    if args.compare:
        print(json.dumps(evaluator.compare(args.compare, run_id), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
