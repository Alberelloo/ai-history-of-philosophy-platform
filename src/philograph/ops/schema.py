"""Таблицы схемы ``ops``: итоги копирования и проверок восстановления для оповещений."""

from __future__ import annotations

from sqlalchemy import JSON, Boolean, Column, DateTime, Integer, MetaData, String, Table

from philograph.platform.db import Migrations

SCHEMA = "ops"
metadata = MetaData(schema=SCHEMA)

runs = Table(
    "runs",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("kind", String(40), nullable=False, index=True),  # backup | verify
    Column("ok", Boolean, nullable=False),
    Column("time", DateTime(timezone=True), nullable=False),
    Column("name", String(200)),  # имя копии
    Column("detail", JSON, nullable=False),
    schema=SCHEMA,
)

migrations = Migrations(SCHEMA, metadata)
migrations.add(1, "итоги копирования и проверок")(migrations.create_tables("runs"))
