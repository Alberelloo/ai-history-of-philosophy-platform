"""Подключение компонентов к оценке: всё через HTTP-интерфейсы сервисов, как у соседей."""

from __future__ import annotations

import json
from typing import Any

from philograph.evaluation.datasets import Datasets
from philograph.evaluation.runs import JUDGE_SCHEMA
from philograph.platform.client import ServiceClient


def search_evaluator(search: ServiceClient, limit: int = 10):
    def evaluate(item: dict) -> dict:
        found = search.post(
            "search",
            json={
                "query": item["question"],
                "limit": limit,
                "per_chapter": limit,
                # Регион набора: замер повторяет условия читателя этой страны.
                "region": item.get("region"),
            },
        ).json()["results"]
        return {"found": [r["paragraph_id"] for r in found]}

    return evaluate


def router_evaluator(assistant: ServiceClient):
    def evaluate(item: dict) -> dict:
        return assistant.post(
            "internal/route",
            json={"question": item["question"], "selection": item.get("selection")},
        ).json()

    return evaluate


class Judge:
    """Оценщик на роли «сильная»: решение с обоснованием, расход — бюджет «наполнение»."""

    def __init__(self, llm: ServiceClient) -> None:
        self.llm = llm

    def _ask(self, template: str, data: dict[str, str]) -> dict:
        response = self.llm.post(
            "structured",
            json={
                "role": "strong",
                "template": template,
                "caller": "evaluation",
                "operation": "judge",
                "budget": "filling",
                "data": data,
                "json_schema": JUDGE_SCHEMA,
            },
        )
        response.raise_for_status()
        return response.json()["value"]

    def faithful(self, question: str, answer: str, passages: str) -> dict:
        return self._ask(
            "evaluation.judge.faithfulness",
            {"question": question, "answer": answer, "passages": passages},
        )

    def quality(self, question: str, answer: str) -> dict:
        return self._ask("evaluation.judge.quality", {"question": question, "answer": answer})


def assistant_evaluator(
    assistant: ServiceClient, judge: Judge | None = None, sources_only: bool = False
):
    def evaluate(item: dict) -> dict:
        body = {
            "question": item["question"],
            "selection": item.get("selection"),
            "sources_only": sources_only or not item.get("has_answer", True),
            # Регион набора: ассистент отвечает так, как ответил бы читателю этой страны.
            "region": item.get("region"),
        }
        with assistant.stream("POST", "ask", json=body) as response:
            events = [json.loads(line) for line in response.iter_lines() if line.strip()]
        fragments = [e for e in events if e["type"] == "fragment"]
        done = next((e for e in events if e["type"] == "done"), {})
        stats = done.get("stats", {})
        kept = sum(len(f["citations"]) for f in fragments)
        result: dict[str, Any] = {
            "fragments": fragments,
            "refused": any(e["type"] in ("no_answer", "refused") for e in events),
            "passed": [c["paragraph_id"] for f in fragments for c in f["citations"]],
            "removed_citations": stats.get("removed_citations", 0),
            "citations_kept": kept,
            "first_fragment_ms": done.get("first_fragment_ms", 0),
            "total_ms": done.get("total_ms", 0),
        }
        answer = " ".join(f["text"] for f in fragments)
        if judge is not None and fragments:
            verdict = judge.faithful(
                item["question"],
                answer,
                "\n".join(c["title"] for f in fragments for c in f["citations"]),
            )
            result["faithful"] = verdict["verdict"]
            result["faithful_reason"] = verdict["reason"]
            result["quality"] = judge.quality(item["question"], answer)["verdict"]
        return result

    return evaluate


def draft_questions(
    datasets: Datasets,
    dataset_id: int,
    llm: ServiceClient,
    search: ServiceClient,
    questions: list[str],
) -> int:
    """Черновая разметка моделью: кандидаты в абзацы и эталон — со статусом «черновик»."""
    added = 0
    for i, question in enumerate(questions):
        found = search.post(
            "search",
            json={"query": question, "limit": 8, "region": datasets.region(dataset_id)},
        ).json()["results"]
        passages = "\n\n".join(f"[{n + 1}] {r['text']}" for n, r in enumerate(found))
        response = llm.post(
            "structured",
            json={
                "role": "strong",
                "template": "evaluation.draft.question",
                "caller": "evaluation",
                "operation": "draft",
                "budget": "filling",
                "data": {"question": question, "passages": passages},
                "json_schema": {
                    "type": "object",
                    "required": ["type", "relevant", "answer"],
                    "properties": {
                        "type": {"type": "string"},
                        "relevant": {"type": "array", "items": {"type": "integer"}},
                        "answer": {"type": "string"},
                    },
                },
            },
        )
        response.raise_for_status()
        value = response.json()["value"]
        relevant = [found[n - 1]["paragraph_id"] for n in value["relevant"] if 0 < n <= len(found)]
        datasets.add(
            dataset_id,
            f"draft-{i}",
            {
                "question": question,
                "type": value["type"],
                "relevant": relevant,
                "reference": value["answer"],
            },
            status="draft",
        )
        added += 1
    return added
