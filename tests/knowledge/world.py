"""Построитель данных онтологии для тестов справочника и эпох.

Данные задаёт тест через ``Entities``/``Statements`` — тот же путь записи, что у сервиса.
Один построитель служит сервисным тестам (``tests/knowledge``) и браузерным (``tests/web``):
так сценарии спецификации собираются одинаково на обоих уровнях.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from philograph.knowledge import schema as t
from philograph.knowledge.dates import lifespan, parse
from philograph.knowledge.entities import Entities
from philograph.knowledge.statements import Attribution, Evidence, Provenance, Statements

COMMON = [Attribution("common")]


@dataclass
class World:
    entities: Entities
    statements: Statements
    paragraphs: dict[str, str] = field(default_factory=dict)

    @property
    def engine(self):
        return self.statements.engine

    # --- сущности ---

    def person(self, name: str, birth: str | None = None, death: str | None = None) -> str:
        entity = self.entities.create("person", [("ru", name, "primary")])
        if birth:
            self.statements.add(
                entity, "lifespan", value=lifespan(birth, death).to_json(), attributions=COMMON
            )
        return entity

    def thing(self, type_: str, name: str, dating: str | None = None) -> str:
        entity = self.entities.create(type_, [("ru", name, "primary")])
        if dating:
            self.statements.add(
                entity, "dating", value=parse(dating).to_json(), attributions=COMMON
            )
        return entity

    def dated(self, type_: str, name: str, dating: dict[str, Any]) -> str:
        """Сущность с датировкой, заданной JSON нечёткого интервала (``FuzzyDate.to_json``)."""
        entity = self.entities.create(type_, [("ru", name, "primary")])
        self.statements.add(entity, "dating", value=dating, attributions=COMMON)
        return entity

    def source(self, source_id: str, title: str) -> str:
        """Источник библиотеки как сущность онтологии."""
        return self.entities.source_entity(source_id, title)

    def variant(self, entity: str, text: str, lang: str = "en") -> None:
        self.entities.add_name(entity, lang, text, "variant")

    # --- утверждения ---

    def relate(self, subject: str, type_: str, obj: str, **kw) -> str:
        return self.statements.add(subject, type_, obj=obj, attributions=COMMON, **kw)

    def describe(self, entity: str, text: str, generated: bool = False) -> str:
        return self.statements.add(
            entity,
            "description",
            value=text,
            attributions=COMMON,
            provenance=Provenance("generated") if generated else None,
        )

    def belongs(self, entity: str, epoch: str) -> str:
        return self.statements.add(entity, "belongs_to_epoch", obj=epoch, attributions=COMMON)

    def confirmed(
        self,
        subject: str,
        type_: str,
        obj: str,
        *,
        paragraph: str,
        text: str,
        source: str,
        attributed_to: str | None = None,
    ) -> str:
        """Утверждение, подтверждённое абзацем источника ``source``; атрибуция — другой
        источник (``attributed_to``) или тот же."""
        self.paragraphs[paragraph] = text
        return self.statements.add(
            subject,
            type_,
            obj=obj,
            attributions=[Attribution("source", attributed_to or source)],
            evidence=[Evidence(paragraph, text, source_id=source)],
            provenance=Provenance("extracted"),
        )

    def mention(self, entity: str, source: str, paragraph: str = "p1") -> None:
        """Упоминание сущности в абзаце источника (как пишет указатель упоминаний)."""
        with self.engine.begin() as conn:
            conn.execute(
                t.mentions.insert().values(
                    target_id=paragraph,
                    target_kind="paragraph",
                    source_id=source,
                    entity_id=entity,
                    start=0,
                    end=4,
                    method="name",
                )
            )

    # --- наборы данных сценариев ---

    def base(self, textbook: str = "s_textbook_n") -> dict[str, str]:
        """Данные сценария «Справочник без фильтров»."""
        return {
            "kant": self.person("Иммануил Кант", "1724", "1804"),
            "hume": self.person("Дэвид Юм", "1711", "1776"),
            "causality": self.thing("concept", "Причинность"),
            "critique": self.thing("work", "Критика чистого разума", "1781"),
            "enlightenment": self.thing("epoch", "Просвещение", "1680–1800"),
            "textbook": self.source(textbook, "Учебник N"),
        }

    def epochs_and_people(self) -> dict[str, str]:
        """Данные сценария «Эпоха и тип»."""
        return {
            "sci": self.thing("epoch", "Научная революция", "1543–1687"),
            "enl": self.thing("epoch", "Просвещение", "1680–1800"),
            "descartes": self.person("Рене Декарт", "1596", "1650"),
            "hume": self.person("Дэвид Юм", "1711", "1776"),
            "kant": self.person("Иммануил Кант", "1724", "1804"),
        }
