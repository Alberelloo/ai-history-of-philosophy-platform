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
    reading = Reading(registry, engine)
    reading.set_default("seed", ids["textbook"])
    seed_ontology(database_url, reading, ids["textbook"])
    pipeline.dispatch_outbox(Queue(engine))
    return ids


def seed_ontology(database_url: str, reading: Reading, textbook: str) -> None:
    """Маленькая демо-онтология: связь с цитатой из учебника и одна на проверку."""
    from philograph.knowledge import schema as knowledge_schema
    from philograph.knowledge.dates import lifespan, parse
    from philograph.knowledge.entities import Entities
    from philograph.knowledge.registry import OntologyRegistry
    from philograph.knowledge.statements import Attribution, Evidence, Provenance, Statements
    from philograph.library.reading import Internal

    engine = make_engine(database_url, [knowledge_schema.SCHEMA])
    knowledge_schema.migrations.upgrade(engine)
    registry = OntologyRegistry(engine)
    registry.load_defaults()
    entities = Entities(engine, registry)
    if entities.find("Кант"):
        return
    internal = Internal(reading.registry, reading)
    paragraphs = internal.version_paragraphs(reading.registry.get(textbook).published_version)
    text_of = {p["id"]: p["text"] for p in paragraphs["paragraphs"]}
    statements = Statements(engine, registry, entities, text_of.get)
    people = {}
    for name, birth, death in (
        ("Кант", "1724", "1804"),
        ("Юм", "1711", "1776"),
        ("Локк", "1632", "1704"),
        ("Лейбниц", "1646", "1716"),
    ):
        people[name] = entities.create("person", [("ru", name, "primary")])
        statements.add(
            people[name],
            "lifespan",
            value=lifespan(birth, death).to_json(),
            attributions=[Attribution("common")],
        )
    awakening = next(pid for pid, text in text_of.items() if "догматического сна" in text)
    statements.add(
        people["Кант"],
        "influenced_by",
        obj=people["Юм"],
        attributions=[Attribution("source", textbook)],
        evidence=[Evidence(awakening, "Юм пробудил его от догматического сна", source_id=textbook)],
        provenance=Provenance("extracted", actor="seed"),
    )
    new_essays = entities.create(
        "work", [("ru", "Новые опыты о человеческом разумении", "primary")]
    )
    statements.add(
        new_essays, "dating", value=parse("1765").to_json(), attributions=[Attribution("common")]
    )
    statements.add(
        new_essays, "author", obj=people["Лейбниц"], attributions=[Attribution("common")]
    )
    # Влияние против времени: Локк умер до издания «Новых опытов» — попадёт на проверку.
    statements.add(
        people["Локк"],
        "influenced_by",
        obj=new_essays,
        attributions=[Attribution("common")],
        provenance=Provenance("generated"),
    )


if __name__ == "__main__":
    print(seed(os.environ["PHILOGRAPH_DATABASE_URL"], Path(os.environ["PHILOGRAPH_FILES_ROOT"])))
