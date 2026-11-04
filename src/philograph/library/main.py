"""Точка входа сервиса библиотеки: ``uvicorn philograph.library.main:app``."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from sqlalchemy import text

from philograph import __version__
from philograph.library import schema
from philograph.library.app import build_app
from philograph.library.reading import Reading
from philograph.library.registry import Registry
from philograph.operator.access import migrations as operator_migrations
from philograph.platform import events
from philograph.platform.db import make_engine
from philograph.platform.health import Health


def create(database_url: str, web_root: Path | None) -> FastAPI:
    engine = make_engine(database_url, [schema.SCHEMA, operator_migrations.schema])
    schema.migrations.upgrade(engine)
    operator_migrations.upgrade(engine)
    health = Health("library", __version__)

    def database() -> None:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))

    health.depends_on("database", database)
    return build_app(Reading(Registry(engine), engine), health, web_root=web_root)


if os.environ.get("PHILOGRAPH_DATABASE_URL"):
    events.configure(sinks=[events.json_sink()])
    root = os.environ.get("PHILOGRAPH_WEB_ROOT")
    app = create(os.environ["PHILOGRAPH_DATABASE_URL"], Path(root) if root else None)
