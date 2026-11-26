"""Общий дамп данных онтологии для инвариантов «до/после», отката и сухого прогона.

``dump(engine)`` возвращает строки таблиц данных, нормализованные для сравнения: JSON-поля —
канонический ``json.dumps(sort_keys=True)``, строки отсортированы по всем столбцам. Журнальные
таблицы (``merges``, ``run_actions``, ``journal``, ``filling_runs``, ``review_items``,
``graph_extensions``) в дамп не входят и проверяются отдельно.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select

from philograph.knowledge import schema as t

DATA_TABLES = (
    "entities",
    "names",
    "external_ids",
    "statements",
    "attributions",
    "evidence",
    "mentions",
    "portraits",
)


def _canonical(value: Any) -> Any:
    if isinstance(value, dict | list):
        return json.dumps(value, sort_keys=True, ensure_ascii=False)
    return value


def _key(row: tuple) -> tuple:
    return tuple((v is None, str(v)) for v in row)


def dump(engine, tables: tuple[str, ...] = DATA_TABLES) -> dict[str, list[tuple]]:
    by_name = {tb.name: tb for tb in t.metadata.sorted_tables}
    result: dict[str, list[tuple]] = {}
    with engine.begin() as conn:
        for name in tables:
            table = by_name.get(name)
            if table is None:
                raise KeyError(f"нет таблицы онтологии {name}")
            rows = [tuple(_canonical(v) for v in row) for row in conn.execute(select(table))]
            result[name] = sorted(rows, key=_key)
    return result
