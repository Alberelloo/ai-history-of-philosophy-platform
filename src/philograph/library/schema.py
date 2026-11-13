"""Таблицы схемы ``library``."""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)

from philograph.platform.db import Migrations

SCHEMA = "library"
metadata = MetaData()

license_kinds = Table(
    "license_kinds",
    metadata,
    Column("code", String(50), primary_key=True),
    Column("title", String(200), nullable=False),
    Column("url", String(500)),
    Column("permissions", JSON, nullable=False),  # display, external_processing, quoting
    Column("regions", JSON),  # регионы показа вида лицензии; NULL — везде
    schema=SCHEMA,
)

sources = Table(
    "sources",
    metadata,
    Column("id", String(40), primary_key=True),
    Column("title", String(500), nullable=False),
    Column("authors", JSON, nullable=False),
    Column("language", String(10), nullable=False),
    Column("kind", String(20), nullable=False),  # textbook | primary | reference
    Column("year", Integer),
    Column("edition", String(200)),
    Column("publisher", String(200)),
    Column("translator", String(200)),
    Column("editor", String(200)),
    Column("isbn", String(40)),
    Column("original_url", String(1000)),
    Column("license", JSON, nullable=False),  # вид, основание, подробности, разрешения
    Column("regions", JSON),  # сужение регионов показа источника; NULL — как у вида
    Column("scope", String(100), nullable=False),  # public | user:<id> | group:<id>
    Column("settings", JSON, nullable=False),
    Column("files", JSON, nullable=False),  # [{name, url | path}] по порядку
    Column("status", String(20), nullable=False),  # active | unpublished | deleted
    Column("published_version", String(40)),
    Column("created_at", DateTime(timezone=True), nullable=False),
    schema=SCHEMA,
)

scope_log = Table(
    "scope_log",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("source_id", String(40), nullable=False, index=True),
    Column("time", DateTime(timezone=True), nullable=False),
    Column("actor", String(100), nullable=False),
    Column("old", String(100)),
    Column("new", String(100), nullable=False),
    schema=SCHEMA,
)

versions = Table(
    "versions",
    metadata,
    Column("id", String(40), primary_key=True),
    Column("source_id", String(40), nullable=False, index=True),
    Column("number", Integer, nullable=False),
    Column("state", String(30), nullable=False),
    Column("error", JSON),
    Column("files", JSON, nullable=False),  # [{name, sha256, format, size}]
    Column("pipeline_version", String(20), nullable=False),
    Column("settings", JSON, nullable=False),
    Column("corrections_digest", String(64), nullable=False),
    Column("text_digest", String(64)),
    Column("quality", JSON),  # метрики, выборка, решение
    Column("summary", JSON),  # сводка изменений относительно опубликованной
    Column("issues", JSON),
    Column("deferred_reason", Text),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("lock_owner", String(64)),
    Column("lock_heartbeat", DateTime(timezone=True)),
    UniqueConstraint("source_id", "number"),
    schema=SCHEMA,
)

version_log = Table(
    "version_log",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("version_id", String(40), nullable=False, index=True),
    Column("run_id", String(64)),
    Column("time", DateTime(timezone=True), nullable=False),
    Column("step", String(30), nullable=False),
    Column("event", String(20), nullable=False),  # started | finished | error | warning
    Column("message", Text),
    Column("page", String(20)),
    Column("block_id", String(40)),
    Column("cost_usd", Float),
    Column("settings", JSON),
    Column("pipeline_version", String(20)),
    schema=SCHEMA,
)

sections = Table(
    "sections",
    metadata,
    Column("version_id", String(40), primary_key=True),
    Column("id", String(40), primary_key=True),
    Column("parent_id", String(40)),
    Column("ord", Integer, nullable=False),
    Column("kind", String(20), nullable=False),
    Column("title", Text, nullable=False),
    Column("level", Integer, nullable=False),
    Column("visible", Boolean, nullable=False),
    Column("searchable", Boolean, nullable=False),
    schema=SCHEMA,
)

blocks = Table(
    "blocks",
    metadata,
    Column("version_id", String(40), primary_key=True),
    Column("id", String(40), primary_key=True),
    Column("section_id", String(40), nullable=False),
    Column("ord", Integer, nullable=False),
    Column("kind", String(20), nullable=False),
    Column("text", Text, nullable=False),
    Column("lang", String(10), nullable=False),
    Column("pages", JSON, nullable=False),
    Column("notes", JSON, nullable=False),
    Column("detail", Text),
    Column("detail_code", String(20)),
    Column("page", String(20)),
    schema=SCHEMA,
)

footnotes = Table(
    "footnotes",
    metadata,
    Column("version_id", String(40), primary_key=True),
    Column("id", String(40), primary_key=True),
    Column("section_id", String(40), nullable=False),
    Column("ord", Integer, nullable=False),
    Column("marker", String(20), nullable=False),
    Column("text", Text, nullable=False),
    Column("linked", Boolean, nullable=False),
    schema=SCHEMA,
)

removed_paragraphs = Table(
    "removed_paragraphs",
    metadata,
    Column("paragraph_id", String(40), primary_key=True),
    Column("source_id", String(40), nullable=False),
    Column("last_version", String(40), nullable=False),
    Column("section_id", String(40)),
    Column("section_title", Text),
    schema=SCHEMA,
)

redirects = Table(
    "redirects",
    metadata,
    Column("from_id", String(40), primary_key=True),
    Column("to_id", String(40), nullable=False),
    Column("source_id", String(40), nullable=False),
    schema=SCHEMA,
)

corrections = Table(
    "corrections",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("source_id", String(40), ForeignKey(f"{SCHEMA}.sources.id"), nullable=False, index=True),
    Column("op", String(30), nullable=False),
    Column("anchor", JSON, nullable=False),
    Column("payload", JSON, nullable=False),
    Column("actor", String(100), nullable=False),
    Column("reason", Text),
    Column("time", DateTime(timezone=True), nullable=False),
    schema=SCHEMA,
)

outbox = Table(
    "outbox",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("event_id", String(64), nullable=False, unique=True),
    Column("kind", String(50), nullable=False),
    Column("payload", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("sent_at", DateTime(timezone=True)),
    schema=SCHEMA,
)

golden_pages = Table(
    "golden_pages",
    metadata,
    Column("source_id", String(40), primary_key=True),
    Column("page_index", Integer, primary_key=True),
    Column("text", Text, nullable=False),
    Column("actor", String(100), nullable=False),
    schema=SCHEMA,
)

page_cache = Table(
    "page_cache",
    metadata,
    Column("key", String(120), primary_key=True),  # отпечаток входов шага [+ страница]
    Column("page", JSON, nullable=False),
    schema=SCHEMA,
)

defaults = Table(
    "defaults",
    metadata,
    Column("key", String(50), primary_key=True),  # default_source — учебник по умолчанию
    Column("value", String(100), nullable=False),
    schema=SCHEMA,
)

# Связь записи каталога источников (sources/catalog.yaml) с источником учёта.
catalog_links = Table(
    "catalog_links",
    metadata,
    Column("catalog_id", String(120), primary_key=True),
    Column("source_id", String(40), nullable=False, unique=True),
    Column("linked_at", DateTime(timezone=True), nullable=False),
    schema=SCHEMA,
)

# Состояние загрузки по ссылке: условные запросы, неудачи подряд, перенаправления.
fetch_state = Table(
    "fetch_state",
    metadata,
    Column("url", String(1000), primary_key=True),
    Column("etag", String(300)),
    Column("last_modified", String(100)),
    Column("sha256", String(64)),  # хеш очищенного содержимого прошлого ответа 200
    Column("final_url", String(1000)),
    Column("last_status", Integer),
    Column("last_error", Text),
    Column("failures", Integer, nullable=False, default=0),
    Column("checked_at", DateTime(timezone=True)),
    schema=SCHEMA,
)

migrations = Migrations(SCHEMA, metadata)
migrations.add(1, "учёт источников, версии, структура")(
    migrations.create_tables(
        "license_kinds",
        "sources",
        "scope_log",
        "versions",
        "version_log",
        "sections",
        "blocks",
        "footnotes",
        "removed_paragraphs",
        "redirects",
        "corrections",
        "outbox",
        "golden_pages",
        "page_cache",
    )
)
migrations.add(2, "учебник по умолчанию")(migrations.create_tables("defaults"))
migrations.add(3, "каталог источников и состояние загрузки")(
    migrations.create_tables("catalog_links", "fetch_state")
)


@migrations.add(4, "код и страница неразобранной части")
def _add_unrendered_codes(conn) -> None:
    from sqlalchemy import inspect, text

    columns = {c["name"] for c in inspect(conn).get_columns("blocks", schema=SCHEMA)}
    if "detail_code" not in columns:
        conn.execute(text(f"ALTER TABLE {SCHEMA}.blocks ADD COLUMN detail_code VARCHAR(20)"))
    if "page" not in columns:
        conn.execute(text(f"ALTER TABLE {SCHEMA}.blocks ADD COLUMN page VARCHAR(20)"))


@migrations.add(5, "регионы показа у вида лицензии и источника")
def _add_regions(conn) -> None:
    """Регионы лежат отдельными столбцами, а не в JSON ``license``: старый код при откате читает
    ``License(**data)`` и упал бы на неизвестном ключе."""
    from sqlalchemy import inspect, text

    kinds = {c["name"] for c in inspect(conn).get_columns("license_kinds", schema=SCHEMA)}
    if "regions" not in kinds:
        conn.execute(text(f"ALTER TABLE {SCHEMA}.license_kinds ADD COLUMN regions JSON"))
    sources = {c["name"] for c in inspect(conn).get_columns("sources", schema=SCHEMA)}
    if "regions" not in sources:
        conn.execute(text(f"ALTER TABLE {SCHEMA}.sources ADD COLUMN regions JSON"))
