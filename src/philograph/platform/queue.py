"""Очередь задач на реляционной базе.

Задача выполняется хотя бы один раз, поэтому обработчик обязан переносить повтор.
Ключ идемпотентности не даёт поставить одну и ту же задачу дважды. После заданного числа
неудач задача получает статус ``failed`` с причиной и видна оператору.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Engine,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    and_,
    select,
    update,
)

from philograph.platform import context, events
from philograph.platform.clock import Clock, SystemClock
from philograph.platform.db import Migrations

SCHEMA = "queue"
metadata = MetaData()

jobs = Table(
    "jobs",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("kind", String(100), nullable=False, index=True),
    Column("idempotency_key", String(200), nullable=False, unique=True),
    Column("payload", JSON, nullable=False),
    Column("status", String(20), nullable=False, index=True),  # pending, running, done, failed
    Column("attempts", Integer, nullable=False, default=0),
    Column("max_attempts", Integer, nullable=False),
    Column("run_after", DateTime(timezone=True), nullable=False),
    Column("enqueued_at", DateTime(timezone=True), nullable=False),
    Column("last_error", Text),
    Column("run_id", String(64)),
    Column("request_id", String(64)),
    schema=SCHEMA,
)

migrations = Migrations(SCHEMA, metadata)
migrations.add(1, "jobs")(migrations.create_tables("jobs"))

events.define(
    "queue.job.enqueued", "info", "Задача поставлена в очередь", required=("job_id", "kind")
)
events.define(
    "queue.job.duplicate",
    "debug",
    "Задача с тем же ключом уже в очереди",
    required=("kind", "idempotency_key"),
)
events.define(
    "queue.job.started", "info", "Исполнитель взял задачу", required=("job_id", "kind", "attempt")
)
events.define("queue.job.done", "info", "Задача выполнена", required=("job_id", "kind"))
events.define(
    "queue.job.retry",
    "warning",
    "Задача не удалась и будет повторена",
    required=("job_id", "kind", "attempt", "reason"),
)
events.define(
    "queue.job.failed",
    "error",
    "Задача не удалась после всех попыток",
    required=("job_id", "kind", "attempts", "reason"),
)


@dataclass(frozen=True)
class Job:
    id: int
    kind: str
    payload: dict[str, Any]
    attempts: int


Handler = Callable[[Job], None]


class Queue:
    def __init__(
        self,
        engine: Engine,
        clock: Clock | None = None,
        *,
        max_attempts: int = 3,
        backoff_seconds: float = 30.0,
    ) -> None:
        self.engine = engine
        self.clock = clock or SystemClock()
        self.max_attempts = max_attempts
        self.backoff_seconds = backoff_seconds
        self._handlers: dict[str, Handler] = {}

    def handler(self, kind: str) -> Callable[[Handler], Handler]:
        def register(fn: Handler) -> Handler:
            self._handlers[kind] = fn
            return fn

        return register

    def enqueue(self, kind: str, payload: dict[str, Any], *, key: str) -> int | None:
        """Ставит задачу. Возвращает ``None``, если задача с этим ключом уже есть."""
        now = self.clock.now()
        with self.engine.begin() as conn:
            existing = conn.scalar(select(jobs.c.id).where(jobs.c.idempotency_key == key))
            if existing is not None:
                events.emit("queue.job.duplicate", kind=kind, idempotency_key=key)
                return None
            job_id = conn.execute(
                jobs.insert().values(
                    kind=kind,
                    idempotency_key=key,
                    payload=json.loads(json.dumps(payload)),
                    status="pending",
                    attempts=0,
                    max_attempts=self.max_attempts,
                    run_after=now,
                    enqueued_at=now,
                    run_id=context.run_id(),
                    request_id=context.request_id(),
                )
            ).inserted_primary_key[0]
        events.emit("queue.job.enqueued", job_id=job_id, kind=kind)
        return job_id

    def _claim(self) -> tuple[Job, str | None, str | None] | None:
        """Берёт только задачи, для которых у этого исполнителя есть обработчик: каждый сервис
        разбирает свою подписку и не трогает чужую."""
        if not self._handlers:
            return None
        now = self.clock.now()
        with self.engine.begin() as conn:
            query = (
                select(jobs)
                .where(
                    and_(
                        jobs.c.status == "pending",
                        jobs.c.run_after <= now,
                        jobs.c.kind.in_(list(self._handlers)),
                    )
                )
                .order_by(jobs.c.id)
                .limit(1)
            )
            if conn.dialect.name == "postgresql":
                query = query.with_for_update(skip_locked=True)
            row = conn.execute(query).mappings().first()
            if row is None:
                return None
            attempt = row["attempts"] + 1
            conn.execute(
                update(jobs)
                .where(jobs.c.id == row["id"])
                .values(status="running", attempts=attempt)
            )
        job = Job(row["id"], row["kind"], dict(row["payload"]), attempt)
        return job, row["run_id"], row["request_id"]

    def run_once(self) -> bool:
        """Выполняет одну готовую задачу. Возвращает ``False``, если задач нет."""
        claimed = self._claim()
        if claimed is None:
            return False
        job, run_id, request_id = claimed
        with context.scope(run_id=run_id, request_id=request_id):
            events.emit("queue.job.started", job_id=job.id, kind=job.kind, attempt=job.attempts)
            try:
                handler = self._handlers[job.kind]
                handler(job)
            except Exception as exc:
                self._fail(job, f"{type(exc).__name__}: {exc}")
            else:
                with self.engine.begin() as conn:
                    conn.execute(update(jobs).where(jobs.c.id == job.id).values(status="done"))
                events.emit("queue.job.done", job_id=job.id, kind=job.kind)
        return True

    def serve(self, stop: threading.Event, idle_seconds: float = 1.0) -> None:
        """Цикл исполнителя: берёт задачи, пока не попросят остановиться."""
        while not stop.is_set():
            if not self.run_once():
                stop.wait(idle_seconds)

    def run_until_empty(self, limit: int = 1000) -> int:
        count = 0
        while count < limit and self.run_once():
            count += 1
        return count

    def _fail(self, job: Job, reason: str) -> None:
        reason = events.redact(reason)[:2000]
        with self.engine.begin() as conn:
            if job.attempts >= self.max_attempts:
                conn.execute(
                    update(jobs)
                    .where(jobs.c.id == job.id)
                    .values(status="failed", last_error=reason)
                )
                failed = True
            else:
                delay = timedelta(seconds=self.backoff_seconds * 2 ** (job.attempts - 1))
                conn.execute(
                    update(jobs)
                    .where(jobs.c.id == job.id)
                    .values(status="pending", last_error=reason, run_after=self.clock.now() + delay)
                )
                failed = False
        if failed:
            events.emit(
                "queue.job.failed",
                job_id=job.id,
                kind=job.kind,
                attempts=job.attempts,
                reason=reason,
                error_kind="job_failed",
            )
        else:
            events.emit(
                "queue.job.retry", job_id=job.id, kind=job.kind, attempt=job.attempts, reason=reason
            )

    def failed(self) -> list[dict[str, Any]]:
        with self.engine.begin() as conn:
            rows = conn.execute(select(jobs).where(jobs.c.status == "failed")).mappings()
            return [dict(r) for r in rows]

    def stats(self) -> dict[str, Any]:
        """Длина очереди и возраст самой старой ожидающей задачи в секундах."""
        with self.engine.begin() as conn:
            pending = list(
                conn.execute(select(jobs.c.enqueued_at).where(jobs.c.status == "pending")).scalars()
            )
        oldest = None
        if pending:
            first = min(pending)
            if first.tzinfo is None:
                from datetime import UTC

                first = first.replace(tzinfo=UTC)
            oldest = (self.clock.now() - first).total_seconds()
        return {"pending": len(pending), "oldest_age_seconds": oldest}
