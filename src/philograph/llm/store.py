"""Данные сервиса LLM: журнал вызовов, учёт расходов, кэш, лимиты запусков."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Engine,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    and_,
    delete,
    func,
    select,
    update,
)

from philograph.platform.db import Migrations

SCHEMA = "llm"
metadata = MetaData()

calls = Table(
    "calls",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("time", DateTime(timezone=True), nullable=False, index=True),
    Column("caller", String(50), nullable=False),
    Column("operation", String(100), nullable=False),
    Column("kind", String(20), nullable=False),  # generate | stream | structured | embed
    Column("role", String(50), nullable=False),
    Column("model", String(100), nullable=False),
    Column("budget", String(20), nullable=False),
    Column("run_id", String(64)),
    Column("request_id", String(64)),
    Column("template", String(100)),
    Column("template_version", String(20)),
    Column("attempt", Integer, nullable=False),
    Column("input_tokens", Integer, nullable=False, default=0),
    Column("cached_input_tokens", Integer, nullable=False, default=0),
    Column("output_tokens", Integer, nullable=False, default=0),
    Column("cost_usd", Float, nullable=False, default=0.0),
    Column("duration_ms", Float, nullable=False, default=0.0),
    Column("cache_hit", Boolean, nullable=False, default=False),
    Column("status", String(20), nullable=False),  # ok | error
    Column("error_kind", String(50)),
    Column("prompt_text", Text),
    Column("response_text", Text),
    schema=SCHEMA,
)

# Учёт расходов: резерв на время вызова и фактическая стоимость после него.
ledger = Table(
    "ledger",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("budget", String(20), nullable=False),
    Column("day", String(10), nullable=False, index=True),  # YYYY-MM-DD по UTC
    Column("run_id", String(64), index=True),
    Column("amount_usd", Float, nullable=False),
    Column("reserved", Boolean, nullable=False),
    Column("time", DateTime(timezone=True), nullable=False),
    schema=SCHEMA,
)

cache = Table(
    "cache",
    metadata,
    Column("key", String(64), primary_key=True),
    Column("response", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    schema=SCHEMA,
)

run_limits = Table(
    "run_limits",
    metadata,
    Column("run_id", String(64), primary_key=True),
    Column("limit_usd", Float, nullable=False),
    schema=SCHEMA,
)

alerts_sent = Table(
    "alerts_sent",
    metadata,
    Column("key", String(100), primary_key=True),
    schema=SCHEMA,
)

migrations = Migrations(SCHEMA, metadata)
migrations.add(1, "журнал, учёт, кэш")(
    migrations.create_tables("calls", "ledger", "cache", "run_limits", "alerts_sent")
)


class _SerializedEngine:
    """SQLite в памяти — одно соединение на процесс, поэтому доступ к нему по очереди."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._lock = threading.RLock()

    @contextmanager
    def begin(self) -> Iterator[Any]:
        with self._lock, self._engine.begin() as conn:
            yield conn


class Store:
    def __init__(self, engine: Engine) -> None:
        self.engine = _SerializedEngine(engine) if engine.dialect.name == "sqlite" else engine

    # --- журнал ---

    def record_call(self, **values: Any) -> int:
        with self.engine.begin() as conn:
            return conn.execute(calls.insert().values(**values)).inserted_primary_key[0]

    def calls(self) -> list[dict[str, Any]]:
        with self.engine.begin() as conn:
            return [dict(r) for r in conn.execute(select(calls).order_by(calls.c.id)).mappings()]

    def purge_texts(self, older_than: datetime) -> int:
        with self.engine.begin() as conn:
            result = conn.execute(
                update(calls)
                .where(and_(calls.c.time < older_than, calls.c.prompt_text.is_not(None)))
                .values(prompt_text=None, response_text=None)
            )
            return result.rowcount

    # --- учёт ---

    def spent(self, budget: str, day: str) -> float:
        with self.engine.begin() as conn:
            total = conn.scalar(
                select(func.coalesce(func.sum(ledger.c.amount_usd), 0.0)).where(
                    and_(ledger.c.budget == budget, ledger.c.day == day)
                )
            )
        return float(total or 0.0)

    def spent_between(self, budget: str, first_day: str, last_day: str) -> float:
        with self.engine.begin() as conn:
            total = conn.scalar(
                select(func.coalesce(func.sum(ledger.c.amount_usd), 0.0)).where(
                    and_(
                        ledger.c.budget == budget,
                        ledger.c.day >= first_day,
                        ledger.c.day <= last_day,
                    )
                )
            )
        return float(total or 0.0)

    def run_spent(self, run_id: str) -> float:
        with self.engine.begin() as conn:
            total = conn.scalar(
                select(func.coalesce(func.sum(ledger.c.amount_usd), 0.0)).where(
                    ledger.c.run_id == run_id
                )
            )
        return float(total or 0.0)

    def reserve(
        self, budget: str, day: str, run_id: str | None, amount: float, now: datetime
    ) -> int:
        with self.engine.begin() as conn:
            return conn.execute(
                ledger.insert().values(
                    budget=budget,
                    day=day,
                    run_id=run_id,
                    amount_usd=amount,
                    reserved=True,
                    time=now,
                )
            ).inserted_primary_key[0]

    def settle(self, reservation_id: int, amount: float) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                update(ledger)
                .where(ledger.c.id == reservation_id)
                .values(amount_usd=amount, reserved=False)
            )

    def release(self, reservation_id: int) -> None:
        with self.engine.begin() as conn:
            conn.execute(delete(ledger).where(ledger.c.id == reservation_id))

    def set_run_limit(self, run_id: str, limit_usd: float) -> None:
        with self.engine.begin() as conn:
            conn.execute(delete(run_limits).where(run_limits.c.run_id == run_id))
            conn.execute(run_limits.insert().values(run_id=run_id, limit_usd=limit_usd))

    def run_limit(self, run_id: str) -> float | None:
        with self.engine.begin() as conn:
            return conn.scalar(select(run_limits.c.limit_usd).where(run_limits.c.run_id == run_id))

    # --- кэш ---

    def cache_get(self, key: str) -> dict[str, Any] | None:
        with self.engine.begin() as conn:
            return conn.scalar(select(cache.c.response).where(cache.c.key == key))

    def cache_put(self, key: str, response: dict[str, Any], now: datetime) -> None:
        with self.engine.begin() as conn:
            if conn.scalar(select(cache.c.key).where(cache.c.key == key)) is None:
                conn.execute(cache.insert().values(key=key, response=response, created_at=now))

    # --- оповещения ---

    def mark_alert(self, key: str) -> bool:
        """Отмечает оповещение отправленным. ``False``, если уже было."""
        with self.engine.begin() as conn:
            if conn.scalar(select(alerts_sent.c.key).where(alerts_sent.c.key == key)):
                return False
            conn.execute(alerts_sent.insert().values(key=key))
            return True

    # --- сводка ---

    def spend_summary(
        self, first: datetime, last: datetime, group_by: tuple[str, ...]
    ) -> list[dict[str, Any]]:
        cols = [calls.c[name] for name in group_by]
        query = (
            select(*cols, func.sum(calls.c.cost_usd).label("cost_usd"), func.count().label("calls"))
            .where(and_(calls.c.time >= first, calls.c.time < last))
            .group_by(*cols)
        )
        with self.engine.begin() as conn:
            return [dict(r) for r in conn.execute(query).mappings()]


def day_of(moment: datetime) -> str:
    return moment.date().isoformat()


def month_bounds(moment: datetime) -> tuple[str, str]:
    first = moment.date().replace(day=1)
    nxt = (first + timedelta(days=32)).replace(day=1)
    return first.isoformat(), (nxt - timedelta(days=1)).isoformat()
