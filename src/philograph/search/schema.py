"""Таблицы схемы ``search``: полнотекстовый индекс по леммам и учёт эмбеддингов."""

from __future__ import annotations

from sqlalchemy import Boolean, Column, Integer, MetaData, String, Table, Text

from philograph.platform.db import Migrations

SCHEMA = "search"
metadata = MetaData()

# Проиндексированный абзац: всё, что нужно поиску, без обращения к библиотеке.
docs = Table(
    "docs",
    metadata,
    Column("paragraph_id", String(40), primary_key=True),
    Column("source_id", String(40), nullable=False, index=True),
    Column("version_id", String(40), nullable=False),
    Column("chapter_id", String(40)),
    Column("section_id", String(40)),
    Column("section_title", Text),
    Column("source_title", Text),  # чтобы ответ «по авторам» называл учебник
    Column("ord", Integer, nullable=False),
    Column("lang", String(10), nullable=False),
    Column("scope", String(100), nullable=False),
    Column("text", Text, nullable=False),
    Column("text_hash", String(64), nullable=False),
    Column("length", Integer, nullable=False),  # число терминов, для BM25
    Column("embedded", Boolean, nullable=False),  # есть ли в смысловом индексе
    Column("active", Boolean, nullable=False),  # снятый источник: в поиске нет, данные целы
    Column("quoting", Boolean, nullable=False, server_default="1"),  # можно ли цитировать
    # Регионы показа источника: "*" (везде) или ",RU,BY," (подстрока "%,RU,%" безопасна).
    Column("regions", String(100), nullable=False, server_default="*"),
    # Разрешение внешней обработки: абзацы без него не уходят модели (группа 7).
    Column("external", Boolean, nullable=False, server_default="1"),
    schema=SCHEMA,
)

postings = Table(
    "postings",
    metadata,
    Column("term", String(100), primary_key=True),
    Column("paragraph_id", String(40), primary_key=True),
    Column("tf", Integer, nullable=False),
    schema=SCHEMA,
)

# Готовые эмбеддинги по тексту и модели: тот же текст той же моделью не пересчитывается.
vectors_done = Table(
    "vectors_done",
    metadata,
    Column("text_hash", String(64), primary_key=True),
    Column("model", String(100), primary_key=True),
    Column("chunks", Integer, nullable=False),
    schema=SCHEMA,
)

state = Table(
    "state",
    metadata,
    Column("key", String(50), primary_key=True),  # active_collection, active_model
    Column("value", String(200), nullable=False),
    schema=SCHEMA,
)

processed = Table(
    "processed_events",
    metadata,
    Column("event_id", String(64), primary_key=True),
    schema=SCHEMA,
)

migrations = Migrations(SCHEMA, metadata)
migrations.add(1, "индекс абзацев")(
    migrations.create_tables("docs", "postings", "vectors_done", "state", "processed_events")
)


@migrations.add(2, "разрешение на цитирование у абзаца")
def _add_quoting(conn) -> None:
    from sqlalchemy import inspect, text

    columns = {c["name"] for c in inspect(conn).get_columns("docs", schema=SCHEMA)}
    if "quoting" not in columns:  # база, созданная до этой миграции
        default = "TRUE" if conn.dialect.name == "postgresql" else "1"
        conn.execute(
            text(f"ALTER TABLE {SCHEMA}.docs ADD COLUMN quoting BOOLEAN NOT NULL DEFAULT {default}")
        )


@migrations.add(3, "название источника у абзаца")
def _add_source_title(conn) -> None:
    from sqlalchemy import inspect, text

    columns = {c["name"] for c in inspect(conn).get_columns("docs", schema=SCHEMA)}
    if "source_title" not in columns:  # база, созданная до этой миграции
        conn.execute(text(f"ALTER TABLE {SCHEMA}.docs ADD COLUMN source_title TEXT"))


def _add_regions_and_external(conn) -> None:
    from sqlalchemy import inspect, text

    columns = {c["name"] for c in inspect(conn).get_columns("docs", schema=SCHEMA)}
    if "regions" not in columns:  # база, созданная до этой миграции
        conn.execute(
            text(f"ALTER TABLE {SCHEMA}.docs ADD COLUMN regions TEXT NOT NULL DEFAULT '*'")
        )
    if "external" not in columns:
        default = "TRUE" if conn.dialect.name == "postgresql" else "1"
        conn.execute(
            text(
                f"ALTER TABLE {SCHEMA}.docs ADD COLUMN external BOOLEAN NOT NULL DEFAULT {default}"
            )
        )


migrations.add(4, "регионы показа и внешняя обработка у абзаца")(_add_regions_and_external)
