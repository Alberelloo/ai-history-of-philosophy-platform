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
    """Маленькая демо-онтология: связь с цитатой из учебника и одна на проверку; эпохи,
    события, группы и роли — чтобы карта раздела не была пустой."""
    from philograph.knowledge import schema as knowledge_schema
    from philograph.knowledge.entities import Entities
    from philograph.knowledge.registry import OntologyRegistry
    from philograph.knowledge.statements import Statements
    from philograph.library.reading import Internal

    engine = make_engine(database_url, [knowledge_schema.SCHEMA])
    knowledge_schema.migrations.upgrade(engine)
    registry = OntologyRegistry(engine)
    registry.load_defaults()
    entities = Entities(engine, registry)
    internal = Internal(reading.registry, reading)
    paragraphs = internal.version_paragraphs(reading.registry.get(textbook).published_version)
    text_of = {p["id"]: p["text"] for p in paragraphs["paragraphs"]}
    statements = Statements(engine, registry, entities, text_of.get)
    if not entities.find("Кант"):
        seed_core(entities, statements, reading, textbook, text_of)
    if not entities.find("Просвещение"):
        seed_map(entities, statements)
    if not entities.find("Кёнигсберг"):
        seed_reference(entities, statements)
    if not entities.find("Барокко"):
        seed_epochs(entities, statements)
    if not entities.find("Южноморский пузырь"):
        seed_context(entities, statements)


def seed_core(entities, statements, reading, textbook: str, text_of: dict[str, str]) -> None:
    """Связь с цитатой из учебника и одна на проверку."""
    from philograph.knowledge.dates import lifespan, parse
    from philograph.knowledge.statements import Attribution, Evidence, Provenance

    entities.source_entity(textbook, reading.registry.get(textbook).title)
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
    causality = entities.create("concept", [("ru", "Причинность", "primary")])
    category = next(pid for pid, text in text_of.items() if "априорная категория" in text)
    statements.add(
        causality,
        "definition",
        value="априорная категория рассудка",
        attributions=[Attribution("entity", people["Кант"])],
        evidence=[
            Evidence(category, "причинность — априорная категория рассудка", source_id=textbook)
        ],
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


def seed_map(entities, statements) -> None:
    """Карта раздела: эпохи с датировкой, события с видом, группы с видом и участниками, роли.

    Новые персоны и труды не связаны с Кантом и Юмом связями, которые видны в их карточках
    и графе генезиса: эталонные снимки чтения от демо-данных карты не меняются. Названия
    не встречаются в тексте демо-учебника — новых упоминаний в главах нет."""
    from philograph.knowledge.dates import lifespan, parse
    from philograph.knowledge.statements import Attribution, Provenance

    common = [Attribution("common")]

    def entity(type_: str, name: str, dating: str | None = None) -> str:
        found = entities.find(name)
        if found:
            return found[0]["id"]
        entity_id = entities.create(type_, [("ru", name, "primary")])
        if dating:
            statements.add(entity_id, "dating", value=parse(dating).to_json(), attributions=common)
        return entity_id

    def person(name: str, birth: str, death: str, roles: tuple[str, ...]) -> str:
        found = entities.find(name)
        if found:
            entity_id = found[0]["id"]
        else:
            entity_id = entities.create("person", [("ru", name, "primary")])
            statements.add(
                entity_id,
                "lifespan",
                value=lifespan(birth, death).to_json(),
                attributions=common,
            )
        for role in roles:
            statements.add(entity_id, "person_role", value=role, attributions=common)
        return entity_id

    people = {
        "Кант": person("Кант", "1724", "1804", ("philosopher", "scientist")),
        "Юм": person("Юм", "1711", "1776", ("philosopher", "writer")),
        "Локк": person("Локк", "1632", "1704", ("philosopher",)),
        "Лейбниц": person("Лейбниц", "1646", "1716", ("philosopher", "scientist")),
        "Декарт": person("Декарт", "1596", "1650", ("philosopher", "scientist")),
        "Беркли": person("Беркли", "1685", "1753", ("philosopher", "theologian")),
        "Вольф": person("Вольф", "1679", "1754", ("philosopher", "scientist")),
        "Фихте": person("Фихте", "1762", "1814", ("philosopher",)),
    }
    entity("epoch", "Научная революция", "1543–1687")
    entity("epoch", "Просвещение", "1680–1800")
    for name, year, kind in (
        ("Смерть Декарта в Стокгольме", "1650", "biographical"),
        ("Отлучение Спинозы", "1656", "religious"),
        ("Основание Лондонского королевского общества", "1660", "scientific"),
        ("Славная революция", "1688", "political"),
        ("Выход первого тома «Энциклопедии»", "1751", "intellectual"),
    ):
        event = entity("event", name, year)
        statements.add(event, "event_kind", value=kind, attributions=common)
    works = {}
    for title, year, author in (
        ("Рассуждение о методе", "1637", "Декарт"),
        ("Трактат о принципах человеческого знания", "1710", "Беркли"),
        ("Разумные мысли о Боге, мире и душе человека", "1720", "Вольф"),
        ("Основа общего наукоучения", "1794", "Фихте"),
    ):
        works[title] = entity("work", title, year)
        statements.add(works[title], "author", obj=people[author], attributions=common)
    # Идеи ставятся на год труда, где высказаны; «Субстанция» без труда — «без даты».
    doubt = entity("position", "Методическое сомнение")
    statements.add(works["Рассуждение о методе"], "expresses", obj=doubt, attributions=common)
    immaterialism = entity("doctrine", "Имматериализм")
    statements.add(
        works["Трактат о принципах человеческого знания"],
        "discusses",
        obj=immaterialism,
        attributions=common,
    )
    entity("concept", "Субстанция")
    for name, kind, members in (
        ("Рационализм", "direction", ("Декарт", "Вольф")),
        ("Эмпиризм", "direction", ("Беркли",)),
        ("Немецкий идеализм", "direction", ("Фихте",)),
        ("Школа Вольфа", "school", ("Вольф",)),
    ):
        group = entity("group", name)
        statements.add(group, "group_kind", value=kind, attributions=common)
        for member in members:
            statements.add(people[member], "member_of", obj=group, attributions=common)
    statements.add(people["Вольф"], "influenced_by", obj=people["Лейбниц"], attributions=common)
    statements.add(people["Беркли"], "influenced_by", obj=people["Локк"], attributions=common)
    # Достроенная моделью связь — пунктир на карте.
    statements.add(
        people["Беркли"],
        "criticizes",
        obj=people["Декарт"],
        attributions=common,
        provenance=Provenance("generated"),
    )


def seed_reference(entities, statements) -> None:
    """Справочник: латинский вариант названия, явное «относится к эпохе», термин и место.

    Названия не встречаются в текстах демо-источников — новых упоминаний нет; у Канта и Юма
    новых утверждений нет, их карточки и граф не меняются (вариант названия карточка не
    показывает). Локк по датам (середина жизни 1668) — «Научная революция»; явная связь
    с «Просвещением» показывает, что явное важнее дат."""
    from philograph.knowledge.statements import Attribution

    common = [Attribution("common")]
    kant = entities.find("Кант")[0]["id"]
    if not entities.find("Kant"):
        entities.add_name(kant, "en", "Kant")
    statements.add(
        entities.find("Локк")[0]["id"],
        "belongs_to_epoch",
        obj=entities.find("Просвещение")[0]["id"],
        qualifiers={"membership_basis": "historians"},
        attributions=common,
    )
    entities.create("term", [("ru", "Эпистемология", "primary")])
    entities.create("place", [("ru", "Кёнигсберг", "primary")])


def seed_epochs(entities, statements) -> None:
    """Эпохи (add-epochs): эпоха без датировки с явным участником и нечёткий конец пролёта.

    «Барокко» без датировки — в списке «без датировки» страницы эпох, Лейбниц относится
    к нему явно. У «Научной революции» — вторая датировка с концом между 1687 и 1700 и рангом
    «предпочтённое»: она становится основной (пролёт 1543–1694 с растушёвкой конца). Названия
    не встречаются в текстах демо-источников — новых упоминаний нет; у Канта и Юма новых
    утверждений нет, эталоны чтения не меняются."""
    from philograph.knowledge.dates import FuzzyDate
    from philograph.knowledge.statements import Attribution

    common = [Attribution("common")]
    baroque = entities.create("epoch", [("ru", "Барокко", "primary"), ("en", "Baroque", "variant")])
    statements.add(
        entities.find("Лейбниц")[0]["id"],
        "belongs_to_epoch",
        obj=baroque,
        qualifiers={"membership_basis": "historians"},
        attributions=common,
    )
    revolution = entities.find("Научная революция")[0]["id"]
    fuzzy_end = statements.add(
        revolution,
        "dating",
        value=FuzzyDate(1543, 1543, 1687, 1700, "approx", "1543 – 1687…1700").to_json(),
        attributions=common,
    )
    statements.set_rank(fuzzy_end, "preferred", "seed")


def seed_context(entities, statements) -> None:
    """Исторический контекст (add-epoch-context): место события, связи «стимулировало».

    «Славная революция» произошла в Лондоне и стимулировала «Политическую философию Локка»
    (механизм — политический; по источникам — импорт общеизвестного факта, без абзаца:
    в демо-текстах нет подходящей цитаты). «Выход первого тома «Энциклопедии»» стимулировал
    «Основу общего наукоучения» — связь достроена моделью (без механизма, не проверена).
    «Южноморский пузырь» — экономическое событие без связей. Названия не встречаются
    в текстах демо-источников — новых упоминаний нет; у Канта, Юма и Локка новых
    утверждений нет, эталоны чтения не меняются."""
    from philograph.knowledge.dates import parse
    from philograph.knowledge.statements import Attribution, Provenance

    common = [Attribution("common")]

    def found(name: str) -> str:
        return entities.find(name)[0]["id"]

    london = entities.create("place", [("ru", "Лондон", "primary"), ("en", "London", "primary")])
    revolution = found("Славная революция")
    statements.add(revolution, "happened_in", obj=london, attributions=common)
    locke_politics = entities.create(
        "doctrine",
        [
            ("ru", "Политическая философия Локка", "primary"),
            ("en", "Locke's political philosophy", "primary"),
        ],
    )
    statements.add(
        revolution,
        "stimulated",
        obj=locke_politics,
        qualifiers={"mechanism": "political"},
        attributions=common,
        provenance=Provenance("imported", actor="seed"),
    )
    statements.add(
        found("Выход первого тома «Энциклопедии»"),
        "stimulated",
        obj=found("Основа общего наукоучения"),
        attributions=common,
        provenance=Provenance("generated"),
    )
    bubble = entities.create(
        "event", [("ru", "Южноморский пузырь", "primary"), ("en", "South Sea Bubble", "primary")]
    )
    statements.add(bubble, "dating", value=parse("1720").to_json(), attributions=common)
    statements.add(bubble, "event_kind", value="economic", attributions=common)


if __name__ == "__main__":
    print(seed(os.environ["PHILOGRAPH_DATABASE_URL"], Path(os.environ["PHILOGRAPH_FILES_ROOT"])))
