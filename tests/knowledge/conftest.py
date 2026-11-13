from __future__ import annotations

from dataclasses import dataclass

import pytest

from philograph.knowledge import schema
from philograph.knowledge.dates import lifespan, parse
from philograph.knowledge.entities import Entities
from philograph.knowledge.registry import OntologyRegistry
from philograph.knowledge.statements import Attribution, Evidence, Provenance, Statements
from philograph.operator.access import migrations as operator_migrations

PARAGRAPHS = {
    "p1": "Кант признавал, что именно Юм пробудил его от догматического сна.",
    "p2": "Учебник: Кант испытал влияние Юма в вопросе о причинности.",
    "p3": "Локк сравнивал ум с чистой доской, на которой опыт пишет свои знаки.",
}


@dataclass
class Onto:
    registry: OntologyRegistry
    entities: Entities
    statements: Statements
    paragraphs: dict[str, str]

    def person(
        self, name: str, birth: str | None = None, death: str | None = None, **external
    ) -> str:
        entity = self.entities.create(
            "person", [("ru", name, "primary")], external=external or None
        )
        if birth:
            self.statements.add(
                entity,
                "lifespan",
                value=lifespan(birth, death).to_json(),
                attributions=[Attribution("common")],
            )
        return entity

    def thing(self, type_: str, name: str, dating: str | None = None) -> str:
        entity = self.entities.create(type_, [("ru", name, "primary")])
        if dating:
            self.statements.add(
                entity,
                "dating",
                value=parse(dating).to_json(),
                attributions=[Attribution("common")],
            )
        return entity

    def sourced(
        self,
        subject,
        type_,
        obj,
        paragraph="p2",
        quote="Кант испытал влияние Юма",
        who="s_textbook",
        run_id=None,
        **kw,
    ):
        return self.statements.add(
            subject,
            type_,
            obj=obj,
            attributions=[Attribution("source", who)],
            evidence=[Evidence(paragraph, quote, source_id=who)],
            provenance=Provenance("extracted", run_id=run_id),
            **kw,
        )


@pytest.fixture
def onto(engine_for, clock) -> Onto:
    engine = engine_for(schema.migrations, operator_migrations)  # журнал действий оператора
    _ = operator_migrations
    registry = OntologyRegistry(engine, clock)
    registry.load_defaults()
    entities = Entities(engine, registry)
    paragraphs = dict(PARAGRAPHS)
    statements = Statements(engine, registry, entities, paragraphs.get, clock)
    return Onto(registry, entities, statements, paragraphs)
