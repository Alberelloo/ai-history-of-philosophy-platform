"""ontology-extraction (improve-extraction-naming, MODIFIED): «Структурированный вывод по
реестру» и «Нормализация сущностей», плюс инвариант языка на ответах модели (entity-naming).

По дельте ``openspec/changes/improve-extraction-naming/specs/ontology-extraction``. Вывод —
перехваченный запрос к шлюзу (``json_schema``, данные), база и очередь проверки; журнал —
``knowledge.extraction.*`` и ``knowledge.entity.*``. Property-тесты — ``fragment_items`` и
типы элементов из реестра и вне его.
"""

from __future__ import annotations

import json

import pytest
from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as hs
from sqlalchemy import select

from philograph.knowledge import schema as t
from philograph.knowledge.review import Review
from philograph.operator.access import ActionLog

from ..conftest import PROFILES
from .extraction_stand import Stand
from .strategies import (
    LANG_SCRIPT,
    REGISTRY_TYPES,
    assert_dropped_codes,
    fragment_items,
    sentinel,
)

req = pytest.mark.req
EX = "ontology-extraction"
NM = "entity-naming"
OUTPUT = "Структурированный вывод по реестру"
NORM = "Нормализация сущностей"
CTX = {"request_id", "run_id", "service"}
CREATED = "knowledge.entity.created"
RENAMED = "knowledge.entity.renamed"
DROPPED = "knowledge.extraction.dropped"
FRAGMENT = "knowledge.extraction.fragment"
HEAVY = settings(
    parent=PROFILES["heavy"], suppress_health_check=[HealthCheck.function_scoped_fixture]
)


@pytest.fixture
def stand(onto, engine_for, clock) -> Stand:
    return Stand(onto, engine_for, clock)


@pytest.fixture
def passed(onto, engine_for, clock) -> Stand:
    """Ответ модели уже прошёл шлюз: сервер знаний проверяет его сам."""
    return Stand(onto, engine_for, clock, passed_gateway=True)


def st(subject, type_, obj, paragraph, quote, **extra):
    return {
        "subject": subject,
        "subject_type": extra.pop("subject_type", "person"),
        "type": type_,
        "object": obj,
        "object_type": extra.pop("object_type", "position"),
        "paragraph": paragraph,
        "quote": quote,
        **extra,
    }


def names(onto, entity_id) -> set[tuple[str, str, str]]:
    return {(n["lang"], n["text"], n["kind"]) for n in onto.entities.get(entity_id)["names"]}


def ids_by_text(onto, text: str) -> list[str]:
    with onto.statements.engine.begin() as conn:
        return sorted(set(conn.scalars(select(t.names.c.entity_id).where(t.names.c.text == text))))


def no_token(events, token: str) -> None:
    for event in events.items:
        assert token not in repr(event.fields), event.name


# =========================== Структурированный вывод по реестру ===========================


@req(EX, OUTPUT, scenario="Неуверенность в типе")
def test_uncertain_type_falls_back_to_general(stand, onto, events):
    stand.extract(
        ["Кант, по одним авторам, развивал идеи Юма, по другим — переосмыслял их."],
        {
            "statements": [
                st(
                    "Кант",
                    "studied_with",
                    "Скептицизм",
                    1,
                    "Кант, по одним авторам, развивал идеи Юма",
                )
            ]
        },
    )
    kinds = {s["type"] for s in stand.statements()}
    assert kinds == {"influenced_by"}
    assert len(events.where("knowledge.statement.created", type="influenced_by")) == 1


@req(EX, OUTPUT, scenario="Схема с сущностями и датировкой")
def test_schema_with_entities_and_dating(stand, events):
    token = sentinel()
    stand.extract(
        [
            (f"Locke wrote the Essay. {token}", "en"),
            ("Hume answered him.", "en"),
            ("Кант ответил обоим.", "ru"),
        ],
        {"statements": []},
    )
    [body] = stand.llm_transport.bodies
    assert body["template"] == "ontology.extract"
    schema = body["json_schema"]
    assert schema["required"] == ["statements"]
    entities = schema["properties"]["entities"]
    assert entities["type"] == "array"
    item = entities["items"]
    assert set(item["properties"]) == {"name", "type", "ru", "en", "original", "dating"}
    # reextract-with-claude: схема шлюза мягкая — перечней и типов у полей нет; допустимые
    # типы сущностей сервер знаний проверяет сам и передаёт модели в данных запроса
    assert "enum" not in json.dumps(schema)
    assert set(body["data"]["entity_types"].split(", ")) == set(REGISTRY_TYPES)
    assert set(item["required"]) == {"name", "type"}
    assert "entities" not in schema["required"]
    assert body["data"]["language"] == "en"
    # контракт промпта: правила языка, валидности и дат — в тексте шаблона
    [request] = stand.model.calls
    system = request.messages[0].content.lower()
    assert "извлекай годы, если они названы" in system
    [fragment] = events.of(FRAGMENT)
    assert fragment["run_id"]
    no_token(events, token)


@req(EX, OUTPUT, invariant="Промпт получает язык фрагмента и правила названий и дат")
@pytest.mark.parametrize(
    ("paragraphs", "language"),
    [
        ([("Кант ответил.", "ru")], "ru"),
        ([("Locke wrote.", "en")], "en"),
        ([("Locke wrote.", "en"), ("Hume answered.", "en"), ("Кант ответил.", "ru")], "en"),
        ([("Кант ответил.", "ru"), ("Юм писал.", "ru"), ("Locke wrote.", "en")], "ru"),
        ([("Kant antwortete.", "de"), ("Kant schrieb.", "de"), ("Hume wrote.", "en")], "de"),
        ([("Locke wrote.", "en"), ("Кант ответил.", "ru"), ("Юм писал.", "ru")], "ru"),
    ],
)
def test_prompt_language_and_rules(stand, paragraphs, language):
    stand.extract(paragraphs, {"statements": []})
    [body] = stand.llm_transport.bodies
    assert body["data"]["language"] == language
    [request] = stand.model.calls
    system = request.messages[0].content.lower()
    for rule in (
        "язык названий",  # правило языка названий
        "ru — всегда по-русски",
        "не номер, не фраза и не описание",  # что не считается названием
        "номера разделов",
        "местоимения",
        "роли и описания",
        "извлекай годы, если они названы",  # даты
    ):
        assert rule in system, rule


@req(EX, OUTPUT, invariant="Причина отказа элемента — код без названия: entity:no_type")
def test_new_entity_without_type_dropped_by_code(stand, onto, events):
    """Новая сущность без типа (нет ``subject_type`` и элемента ``entities``) не создаётся:
    утверждение отброшено с кодом ``entity:no_type``, названия в причине нет."""
    token = sentinel()
    item = st("Безымянный", "holds", "Привычка", 1, "Безымянный писал")
    del item["subject_type"]
    stand.extract([f"Безымянный писал о привычке. {token}"], {"statements": [item]})
    assert ids_by_text(onto, "Безымянный") == []
    [drop] = [dict(e.fields) for e in events.of(DROPPED)]
    assert drop["reason"] == "entity:no_type"
    assert drop["code"] == "entity_no_type"  # reextract-with-claude: код из перечня
    assert drop["run_id"]
    assert set(drop) - CTX == {"reason", "code"}
    assert events.where(CREATED, type="person") == []
    no_token(events, token)


@req(EX, OUTPUT, scenario="Тип вне реестра в сущностях")
def test_entity_type_outside_registry(passed, onto, events):
    stand = passed
    stand.extract(
        ["Зевс (V в. до н. э.) — бог; Кант (1724–1804) учил о вещи в себе."],
        {
            "statements": [
                st("Кант", "holds", "Вещь в себе", 1, "Кант (1724–1804) учил о вещи в себе")
            ],
            "entities": [
                {
                    "name": "Зевс",
                    "type": "deity",
                    "dating": {
                        "text": "V в. до н. э.",
                        "paragraph": 1,
                        "quote": "Зевс (V в. до н. э.)",
                    },
                },
                {
                    "name": "Кант",
                    "type": "person",
                    "dating": {"text": "1724–1804", "paragraph": 1, "quote": "Кант (1724–1804)"},
                },
            ],
        },
    )
    assert ids_by_text(onto, "Зевс") == []
    [kant] = ids_by_text(onto, "Кант")
    types = sorted(s["type"] for s in stand.statements())
    assert types == ["holds", "lifespan"]
    assert all(s["subject"] == kant for s in stand.statements())
    assert [e["reason"] for e in events.of(DROPPED)] == ["entity:type"]


@req(EX, OUTPUT, scenario="Ответ без сущностей")
def test_answer_without_entities(stand, onto, events):
    stand.extract(
        ["Hume held that causation is habit. Юм так и писал."],
        {
            "statements": [
                st("Hume", "holds", "Causation as habit", 1, "Hume held that causation is habit"),
                st("Юм", "holds", "Привычка", 1, "Юм так и писал"),
            ]
        },
    )
    [hume] = ids_by_text(onto, "Hume")
    assert names(onto, hume) == {("en", "Hume", "primary")}
    [yum] = ids_by_text(onto, "Юм")
    assert names(onto, yum) == {("ru", "Юм", "primary")}
    [habit] = ids_by_text(onto, "Causation as habit")
    assert names(onto, habit) == {("en", "Causation as habit", "primary")}
    holds = [s for s in stand.statements() if s["type"] == "holds"]
    assert len(holds) == 2
    [fragment] = events.of(FRAGMENT)
    assert fragment["created"] == 2


JUNK_TYPES = ("deity", "Person", "", "source ", "persons", "персона", "entity", "<script>")


@hs.composite
def typed_items(draw):
    """Элементы ``entities`` с типами реестра и вне его; имена уникальны и годны."""
    count = draw(hs.integers(1, 5))
    items = []
    for i in range(count):
        type_ = draw(hs.sampled_from([*REGISTRY_TYPES, *JUNK_TYPES]))
        if type_ == "source":
            type_ = "work"
        name = f"Сущность {'АБВГДЕЖЗИК'[i]}{draw(hs.sampled_from(['ов', 'ин', 'ий']))}"
        item = {"name": name, "type": type_}
        if draw(hs.booleans()):
            item["dating"] = {"text": "1781", "paragraph": 1, "quote": f"{name} (1781)"}
        items.append(item)
    return items


@req(EX, OUTPUT, invariant="Только типы реестра; entities дают только lifespan и dating")
@HEAVY
@given(typed_items())
@example(
    [
        {
            "name": "Зевс",
            "type": "deity",
            "dating": {"text": "1781", "paragraph": 1, "quote": "Зевс (1781)"},
        }
    ]
)
@example([{"name": "Кант", "type": "Person"}, {"name": "Юм", "type": "person"}])
def test_only_registry_types_for_any_items(passed, onto, events, items):
    stand = passed
    stand.reset()
    events.clear()
    text = " ".join(f"{i['name']} (1781)." for i in items)
    stand.extract([text], {"statements": [], "entities": items})
    registry = set(REGISTRY_TYPES)
    with onto.statements.engine.begin() as conn:
        types = set(conn.scalars(select(t.entities.c.type)))
    assert types <= registry
    for row in stand.statements():
        assert row["type"] in ("lifespan", "dating"), row["type"]
    junk = [i for i in items if i["type"] not in registry]
    for item in junk:
        assert ids_by_text(onto, item["name"]) == []
    assert [e["reason"] for e in events.of(DROPPED)].count("entity:type") == len(junk)
    assert_dropped_codes(events)


# =========================== Нормализация сущностей =======================================


@req(EX, NORM, scenario="Привязка")
def test_binding_by_variant(stand, onto, events):
    hume = onto.person("Юм")
    onto.entities.add_name(hume, "ru", "Хьюм")
    events.clear()
    stand.extract(
        ["Хьюм считал причинность привычкой."],
        {"statements": [st("Хьюм", "holds", "Привычка", 1, "Хьюм считал причинность привычкой")]},
    )
    [holds] = [s for s in stand.statements() if s["type"] == "holds"]
    assert holds["subject"] == hume
    assert events.where(CREATED, type="person") == []


@req(EX, NORM, scenario="Неоднозначность")
def test_ambiguous_goes_to_review(stand, onto, clock, events):
    onto.person("Бэкон", "1214", "1292")
    onto.person("Бэкон", "1561", "1626")
    stand.extract(
        ["Бэкон ценил опыт."],
        {"statements": [st("Бэкон", "holds", "Опыт", 1, "Бэкон ценил опыт")]},
    )
    assert [s for s in stand.statements() if s["type"] == "holds"] == []
    review = Review(onto.statements, ActionLog(onto.statements.engine, clock))
    assert len(review.queue(kind="ambiguous_link")) == 1
    assert events.one("knowledge.extraction.ambiguous")["candidates"] == 2
    assert [d["reason"] for d in events.of(DROPPED)] == ["entity:ambiguous"]  # О18


@req(EX, NORM, scenario="Привязка по английскому написанию")
def test_binding_by_english_spelling(stand, onto, events):
    locke = onto.entities.create("person", [("en", "Locke", "primary")])
    persons = stand.entities_of("person")
    events.clear()
    stand.extract(
        ["Локк сравнивал ум с чистой доской."],
        {
            "statements": [
                st("Локк", "holds", "Чистая доска", 1, "Локк сравнивал ум с чистой доской")
            ],
            "entities": [{"name": "Локк", "type": "person", "ru": "Локк", "en": "Locke"}],
        },
    )
    [holds] = [s for s in stand.statements() if s["type"] == "holds"]
    assert holds["subject"] == locke
    assert stand.entities_of("person") == persons
    assert [e["entity_id"] for e in events.of(RENAMED)] == [locke]
    assert events.where(CREATED, type="person") == []


def _lang(text: str, given: str | None) -> str:
    """Ожидаемый язык написания из букв одной письменности (вход ``fragment_items``):
    диапазоны письменностей — из п. 2 спецификации."""
    import unicodedata

    letters = [ch for ch in text if ch.isalpha()]
    if all("\u0400" <= ch <= "\u052f" for ch in letters):
        script = "cyrillic"
    elif all("\u0370" <= ch <= "\u03ff" or "\u1f00" <= ch <= "\u1fff" for ch in letters):
        script = "greek"
    else:
        assert all(unicodedata.name(ch).startswith("LATIN") for ch in letters), text
        script = "latin"
    if given is not None and LANG_SCRIPT.get(given) == script:
        return given
    return {"cyrillic": "ru", "latin": "en", "greek": "el"}[script]


@req(EX, NORM, invariant="Найденная по любому написанию сущность не дублируется")
@req(
    NM,
    "Язык названий сущностей",
    invariant="Ответы модели: основное по правилу, язык по письменности",
)
@HEAVY
@given(fragment_items())
@example(
    {
        "item": {"name": "Локк", "type": "person", "ru": "Локк", "en": "Locke"},
        "type": "person",
        "spellings": {"ru": "Локк", "en": "Locke"},
        "orig_lang": "la",
        "existing": "en",
        "existing_text": "LOCKE",
    }
)
@example(
    {
        "item": {
            "name": "Платон",
            "type": "person",
            "ru": "Платон",
            "en": "Plato",
            "original": {"lang": "grc", "text": "Πλάτων"},
        },
        "type": "person",
        "spellings": {"ru": "Платон", "en": "Plato", "original": "Πλάτων"},
        "orig_lang": "grc",
        "existing": "original",
        "existing_text": "Πλάτων",
    }
)
def test_normalization_and_language_for_any_items(stand, onto, events, case):
    stand.reset()
    item, type_ = case["item"], case["type"]
    existing = None
    if case["existing"]:
        key = case["existing"]
        given = "ru" if key == "ru" else ("en" if key == "en" else case["orig_lang"])
        existing = onto.entities.create(type_, [(given, case["existing_text"], "primary")])
    before = stand.entities_of(type_)
    events.clear()
    token = sentinel()
    name = item["name"]
    stand.extract(
        [f"{name} упомянут здесь. {token}"],
        {
            "statements": [
                st(
                    name,
                    "belongs_to_epoch",
                    "Новое время",
                    1,
                    f"{name} упомянут здесь",
                    subject_type=type_,
                    object_type="epoch",
                )
            ],
            "entities": [item],
        },
    )
    [row] = [s for s in stand.statements() if s["type"] == "belongs_to_epoch"]
    created = [e for e in events.of(CREATED) if e["type"] == type_]
    assert stand.entities_of(type_) - before == len(created)
    if existing is not None:
        assert row["subject"] == existing
        assert created == []
        ru = case["spellings"].get("ru")
        if ru is not None and case["existing"] != "ru":
            assert ("ru", ru, "primary") in names(onto, existing)
            [renamed] = events.of(RENAMED)
            previous = _lang(case["existing_text"], given)
            assert {k: v for k, v in renamed.fields.items() if k not in CTX} == {
                "entity_id": existing,
                "lang": "ru",
                "previous_lang": previous,
            }
        else:
            events.assert_none(RENAMED)
    else:
        assert len(created) == 1
        entity = row["subject"]
        assert created[0]["entity_id"] == entity
        got = names(onto, entity)
        spellings = case["spellings"]
        primary_text = spellings.get("ru", name)
        primary_lang = "ru" if "ru" in spellings else _lang(name, None)
        assert (primary_lang, primary_text, "primary") in got
        expected = {(primary_lang, primary_text, "primary")}
        for key, text in spellings.items():
            if text == primary_text:
                continue
            given = key if key != "original" else case["orig_lang"]
            expected.add((_lang(text, given), text, "variant"))
        assert got == expected
    primaries: dict[str, int] = {}
    for lang, _text, kind in names(onto, row["subject"]):
        if kind == "primary":
            primaries[lang] = primaries.get(lang, 0) + 1
    assert set(primaries.values()) == {1}
    no_token(events, token)
    assert_dropped_codes(events)
