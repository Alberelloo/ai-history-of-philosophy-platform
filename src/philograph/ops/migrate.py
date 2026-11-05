"""Миграции всех схем одной командой: ``python -m philograph.ops.migrate``.

Обновление запускает её новой версией образа до перезапуска сервисов: если миграция упала,
прежние версии продолжают работать. Каждый сервис при старте тоже применяет свои миграции —
команда нужна, чтобы ошибка проявилась до остановки старой версии, а не после.
"""

from __future__ import annotations

import os
import sys

from philograph.platform import events
from philograph.platform.db import Migrations, make_engine

events.define(
    "ops.migrations.applied",
    "info",
    "Миграции применены",
    required=("applied",),
)
events.define(
    "ops.migrations.failed",
    "error",
    "Миграция не применилась",
    required=("schema", "detail"),
)


def all_migrations() -> list[Migrations]:
    from philograph.evaluation import datasets
    from philograph.knowledge import schema as knowledge
    from philograph.library import schema as library
    from philograph.llm import store as llm
    from philograph.operator import access as operator
    from philograph.ops import schema as ops
    from philograph.platform import queue
    from philograph.search import schema as search

    return [
        library.migrations,
        operator.migrations,
        queue.migrations,
        search.migrations,
        llm.migrations,
        knowledge.migrations,
        datasets.migrations,
        ops.migrations,
    ]


def upgrade_all(database_url: str) -> dict[str, list[int]]:
    sets = all_migrations()
    engine = make_engine(database_url, [m.schema for m in sets])
    applied: dict[str, list[int]] = {}
    try:
        for m in sets:
            try:
                applied[m.schema] = m.upgrade(engine)
            except Exception as exc:
                events.emit(
                    "ops.migrations.failed",
                    schema=m.schema,
                    detail=f"{type(exc).__name__}: {exc}",
                    error_kind=type(exc).__name__,
                )
                raise
    finally:
        engine.dispose()
    events.emit("ops.migrations.applied", applied={k: v for k, v in applied.items() if v})
    return applied


def main() -> int:
    events.configure(sinks=[events.json_sink()])
    try:
        upgrade_all(os.environ["PHILOGRAPH_DATABASE_URL"])
    except Exception:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
