"""Журнал действий запуска вне утверждений (таблица ``run_actions``, ``knowledge:8``).

Общий для команд оператора, которые меняют что-то кроме утверждений: QID (``life_dates``),
переименования, снятия, языки названий, слияния (``ontology_migrate``). Номер ``seq`` —
сквозной в пределах запуска, поэтому команда внутри другой команды (QID из манифеста внутри
миграции) пишет в тот же порядок; откат читает действия в обратном порядке.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

from philograph.knowledge import schema as t

# Отметка начала запуска (``seq`` 0): запуск без единого действия тоже известен откату.
# В ``actions`` не входит — это не действие.
STARTED = "run"


def record(engine: Any, run_id: str, kind: str, payload: dict[str, Any]) -> int:
    """Записать действие в своей транзакции; возвращает его ``seq``."""
    with engine.begin() as conn:
        return record_in(conn, run_id, kind, payload)


def record_in(conn: Any, run_id: str, kind: str, payload: dict[str, Any]) -> int:
    """Записать действие в транзакции вызывающего, вместе с самим изменением: сбой между
    ними не оставит изменение без записи, по которой работает откат."""
    last = conn.scalar(
        select(func.max(t.run_actions.c.seq)).where(t.run_actions.c.run_id == run_id)
    )
    seq = (last or 0) + 1
    conn.execute(
        t.run_actions.insert().values(
            run_id=run_id,
            seq=seq,
            kind=kind,
            payload=payload,
            created_at=datetime.now(UTC),
        )
    )
    return seq


def start(engine: Any, run_id: str) -> None:
    """Отметить начало запуска до первого изменения."""
    with engine.begin() as conn:
        conn.execute(
            t.run_actions.insert().values(
                run_id=run_id, seq=0, kind=STARTED, payload={}, created_at=datetime.now(UTC)
            )
        )


def known(engine: Any, run_id: str) -> bool:
    """Был ли такой запуск: отметка начала или хотя бы одно действие."""
    with engine.begin() as conn:
        return (
            conn.scalar(select(t.run_actions.c.id).where(t.run_actions.c.run_id == run_id).limit(1))
            is not None
        )


def actions(engine: Any, run_id: str, *, reverse: bool = False) -> list[dict[str, Any]]:
    """Действия запуска ``[{seq, kind, payload}]`` по порядку (или в обратном)."""
    order = t.run_actions.c.seq.desc() if reverse else t.run_actions.c.seq
    with engine.begin() as conn:
        rows = conn.execute(
            select(t.run_actions.c.seq, t.run_actions.c.kind, t.run_actions.c.payload)
            .where(t.run_actions.c.run_id == run_id, t.run_actions.c.kind != STARTED)
            .order_by(order)
        ).all()
    return [{"seq": s, "kind": k, "payload": p} for s, k, p in rows]
