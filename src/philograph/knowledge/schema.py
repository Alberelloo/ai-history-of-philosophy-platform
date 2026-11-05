"""Таблицы схемы ``knowledge`` (ontology.md, раздел 13)."""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)

from philograph.platform.db import Migrations

SCHEMA = "knowledge"
metadata = MetaData()

# --- реестр ---
registry_versions = Table(
    "registry_versions",
    metadata,
    Column("version", Integer, primary_key=True),
    Column("time", DateTime(timezone=True), nullable=False),
    Column("actor", String(100), nullable=False),
    Column("change", Text, nullable=False),
    schema=SCHEMA,
)
entity_types = Table(
    "entity_types",
    metadata,
    Column("code", String(50), primary_key=True),
    Column("title", String(100), nullable=False),
    Column("parent", String(50)),
    Column("deprecated_by", String(50)),
    schema=SCHEMA,
)
relation_types = Table(
    "relation_types",
    metadata,
    Column("code", String(50), primary_key=True),
    Column("spec", JSON, nullable=False),  # названия, концы, родитель, свойства, семейства…
    Column("deprecated_by", String(50)),
    schema=SCHEMA,
)
qualifiers = Table(
    "qualifiers",
    metadata,
    Column("code", String(50), primary_key=True),
    Column("title", String(100), nullable=False),
    Column("value_kind", String(20), nullable=False),
    Column("allowed", JSON),
    schema=SCHEMA,
)
recipes = Table(
    "recipes",
    metadata,
    Column("code", String(50), primary_key=True),
    Column("spec", JSON, nullable=False),
    schema=SCHEMA,
)
proposals = Table(
    "type_proposals",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("kind", String(20), nullable=False),
    Column("payload", JSON, nullable=False),
    Column("status", String(20), nullable=False),  # pending | accepted | rejected
    schema=SCHEMA,
)

# --- сущности ---
entities = Table(
    "entities",
    metadata,
    Column("id", String(40), primary_key=True),
    Column("type", String(50), nullable=False, index=True),
    Column("primary", JSON, nullable=False),  # копия основных значений: даты, описание
    Column("redirect_to", String(40)),
    schema=SCHEMA,
)
names = Table(
    "names",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("entity_id", String(40), nullable=False, index=True),
    Column("lang", String(10), nullable=False),
    Column("text", String(300), nullable=False),
    Column("normalized", String(300), nullable=False, index=True),
    Column("kind", String(20), nullable=False),  # primary | variant | original
    schema=SCHEMA,
)
external_ids = Table(
    "external_ids",
    metadata,
    Column("entity_id", String(40), nullable=False),
    Column("system", String(30), primary_key=True),
    Column("value", String(100), primary_key=True),
    schema=SCHEMA,
)
merges = Table(
    "merges",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("kept", String(40), nullable=False),
    Column("removed", String(40), nullable=False),
    Column("moved", JSON, nullable=False),  # что перенесено: для отмены
    Column("undone", Boolean, nullable=False),
    schema=SCHEMA,
)

# --- утверждения ---
statements = Table(
    "statements",
    metadata,
    Column("id", String(40), primary_key=True),
    Column("subject", String(40), nullable=False, index=True),
    Column("type", String(50), nullable=False, index=True),
    Column("object", String(40), index=True),
    Column("value", JSON),
    Column("qualifiers", JSON, nullable=False),
    Column("key", String(64), nullable=False, index=True),  # для объединения повторов
    Column("status", String(20), nullable=False),  # verified | sourced | generated | rejected
    Column("consensus", String(20), nullable=False),
    Column("consensus_manual", Boolean, nullable=False),
    Column("rank", String(20), nullable=False),  # preferred | normal | deprecated
    Column("provenance", JSON, nullable=False),
    Column("scope", String(100), nullable=False),
    Column("warnings", JSON, nullable=False),
    UniqueConstraint("key", "scope"),
    schema=SCHEMA,
)
attributions = Table(
    "attributions",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("statement_id", String(40), nullable=False, index=True),
    Column("who_kind", String(20), nullable=False),  # entity | source | common
    Column("who", String(100)),
    Column("stance", String(20), nullable=False),  # asserts | disputes | mentions
    Column("place", String(200)),
    Column("run_id", String(64)),
    Column("hidden", Boolean, nullable=False),  # источник снят с публикации
    schema=SCHEMA,
)
evidence = Table(
    "evidence",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("statement_id", String(40), nullable=False, index=True),
    Column("paragraph_id", String(40), nullable=False, index=True),
    Column("source_id", String(40)),
    Column("quote", Text, nullable=False),
    Column("supports", Boolean, nullable=False),
    Column("lost", Boolean, nullable=False),
    Column("run_id", String(64)),
    schema=SCHEMA,
)
journal = Table(
    "journal",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("statement_id", String(40), nullable=False, index=True),
    Column("time", DateTime(timezone=True), nullable=False),
    Column("actor", String(100), nullable=False),
    Column("change", JSON, nullable=False),
    schema=SCHEMA,
)
processed = Table(
    "processed_events",
    metadata,
    Column("event_id", String(64), primary_key=True),
    schema=SCHEMA,
)

migrations = Migrations(SCHEMA, metadata)
migrations.add(1, "онтология: реестр, сущности, утверждения")(
    migrations.create_tables(
        "registry_versions",
        "entity_types",
        "relation_types",
        "qualifiers",
        "recipes",
        "type_proposals",
        "entities",
        "names",
        "external_ids",
        "merges",
        "statements",
        "attributions",
        "evidence",
        "journal",
        "processed_events",
    )
)

# --- наполнение и проверка (миграция 2) ---
filling_runs = Table(
    "filling_runs",
    metadata,
    Column("run_id", String(64), primary_key=True),
    Column("kind", String(30), nullable=False),  # extraction | core | wikidata | sample
    Column("target", String(100)),  # источник или версия
    Column("model", String(100)),
    Column("template_version", String(40)),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("finished_at", DateTime(timezone=True)),
    Column("created", Integer, nullable=False),
    Column("dropped", Integer, nullable=False),
    Column("cost_usd", JSON),
    Column("status", String(20), nullable=False),  # running | done | rolled_back
    schema=SCHEMA,
)
review_items = Table(
    "review_items",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("kind", String(30), nullable=False),  # ambiguous_link | duplicate | proposal
    Column("payload", JSON, nullable=False),
    Column("status", String(20), nullable=False),  # open | resolved
    Column("resolution", JSON),
    schema=SCHEMA,
)
statement_views = Table(
    "statement_views",
    metadata,
    Column("statement_id", String(40), primary_key=True),
    Column("views", Integer, nullable=False),
    schema=SCHEMA,
)
review_samples = Table(
    "review_samples",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("sample", String(64), nullable=False, index=True),
    Column("statement_id", String(40), nullable=False),
    Column("decision", String(20)),  # correct | wrong
    schema=SCHEMA,
)
migrations.add(2, "наполнение и проверка")(
    migrations.create_tables("filling_runs", "review_items", "statement_views", "review_samples")
)
