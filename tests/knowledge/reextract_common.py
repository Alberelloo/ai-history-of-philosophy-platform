"""Общие помощники тестов reextract-with-claude: ответы модели, чтение запусков и событий."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from philograph.knowledge import schema as t
from philograph.knowledge.extraction_codes import CODES

EO = "ontology-extraction"
LG = "llm-gateway"
CTX = {"request_id", "service"}  # run_id — поле самого события
DROPPED = "knowledge.extraction.dropped"
FRAGMENT = "knowledge.extraction.fragment"


def st(subject, type_, obj, paragraph, quote, **extra) -> dict[str, Any]:
    """Утверждение ответа модели: персона удерживает позицию (подставляется своё)."""
    return {
        "subject": subject,
        "subject_type": extra.pop("subject_type", "person"),
        "type": type_,
        "object": obj,
        "object_type": extra.pop("object_type", "position"),
        "paragraph": paragraph,
        "quote": quote,
        **extra,
    }


def runs(stand) -> list[dict[str, Any]]:
    with stand.onto.statements.engine.begin() as conn:
        return [dict(r) for r in conn.execute(select(t.filling_runs)).mappings()]


def one_run(stand) -> dict[str, Any]:
    [row] = runs(stand)
    return row


def table_count(stand, table) -> int:
    with stand.onto.statements.engine.begin() as conn:
        return conn.scalar(select(func.count()).select_from(table))


def dropped(events) -> list[dict[str, Any]]:
    return [dict(e.fields) for e in events.of(DROPPED)]


def dropped_codes(events) -> list[str]:
    return [e["code"] for e in events.of(DROPPED)]


def no_context(fields: dict[str, Any]) -> set[str]:
    return set(fields) - CTX


def assert_event_keys(events) -> None:
    """Каждое событие отбраковки: ровно run_id, reason, code (без названий и цитат)."""
    for e in events.of(DROPPED):
        assert set(e.fields) - CTX == {"run_id", "reason", "code"}, e.fields
        assert e["code"] in CODES
        assert len(e["reason"]) <= 300


def check_run_accounting(stand, events, run_id: str | None = None) -> dict[str, Any]:
    """dropped = Σ drop_reasons = число событий с run_id запуска; события — по кодам."""
    row = (
        one_run(stand) if run_id is None else next(r for r in runs(stand) if r["run_id"] == run_id)
    )
    mine = [e for e in events.of(DROPPED) if e["run_id"] == row["run_id"]]
    assert row["dropped"] == sum((row["drop_reasons"] or {}).values()) == len(mine)
    counted: dict[str, int] = {}
    for e in mine:
        counted[e["code"]] = counted.get(e["code"], 0) + 1
    assert (row["drop_reasons"] or {}) == counted
    return row
