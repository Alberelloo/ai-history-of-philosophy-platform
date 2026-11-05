"""Заполняет библиотеку демо-источниками через настоящий конвейер: ``python scripts/seed_demo.py``.

Нужны переменные ``PHILOGRAPH_DATABASE_URL`` и ``PHILOGRAPH_FILES_ROOT``. Повторный запуск ничего
не дублирует. События публикации уходят в очередь, индексацию делает сервис поиска.
"""

from __future__ import annotations

import os
from pathlib import Path

from philograph.library import schema
from philograph.library.processing import Pipeline
from philograph.library.reading import Reading
from philograph.library.registry import License, Registry
from philograph.operator.access import migrations as operator_migrations
from philograph.platform.db import make_engine
from philograph.platform.files import FileStore
from philograph.platform.queue import Queue
from philograph.platform.queue import migrations as queue_migrations

DEMO = Path(__file__).resolve().parent.parent / "demo"
SOURCES = [
    {
        "title": "Теория познания: демонстрационный учебник",
        "authors": ["Проект PhiloGraph"],
        "year": 2026,
        "language": "ru",
        "kind": "textbook",
        "file": "textbook.html",
    },
    {
        "title": "Empiricism: a demonstration reader",
        "authors": ["PhiloGraph project"],
        "year": 2026,
        "language": "en",
        "kind": "primary",
        "file": "primary_en.txt",
    },
]


def seed(database_url: str, files_root: Path) -> dict[str, str]:
    sets = (schema.migrations, operator_migrations, queue_migrations)
    engine = make_engine(database_url, [m.schema for m in sets])
    for m in sets:
        m.upgrade(engine)
    registry = Registry(engine)
    registry.add_license_kind(
        "cc-by-4.0",
        "CC BY 4.0",
        "https://creativecommons.org/licenses/by/4.0/",
        {"display": True, "external_processing": True, "quoting": True},
    )
    pipeline = Pipeline(
        registry, FileStore(files_root), lambda spec: (DEMO / spec["path"]).read_bytes()
    )
    existing = {item["title"]: item for item in registry.overview()}
    ids = {}
    for spec in SOURCES:
        if spec["title"] in existing and existing[spec["title"]]["published_version"]:
            ids[spec["kind"]] = existing[spec["title"]]["source_id"]
            continue
        source_id = registry.register(
            "seed",
            title=spec["title"],
            authors=spec["authors"],
            year=spec["year"],
            language=spec["language"],
            kind=spec["kind"],
            scope="public",
            license=License("cc-by-4.0", "open_license"),
            files=[{"name": spec["file"], "path": spec["file"]}],
            confirm_duplicate=True,
        )
        version_id = pipeline.start("seed", source_id)
        state = registry.version(version_id)["state"]
        if state != "checked":
            raise SystemExit(f"{spec['title']}: версия в состоянии {state}")
        registry.publish("seed", version_id)
        ids[spec["kind"]] = source_id
    Reading(registry, engine).set_default("seed", ids["textbook"])
    pipeline.dispatch_outbox(Queue(engine))
    return ids


if __name__ == "__main__":
    print(seed(os.environ["PHILOGRAPH_DATABASE_URL"], Path(os.environ["PHILOGRAPH_FILES_ROOT"])))
