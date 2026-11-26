"""entity-naming (improve-extraction-naming): «Язык названий сущностей» и «Валидность
названий сущностей».

Тесты написаны по дельте ``openspec/changes/improve-extraction-naming/specs/entity-naming``.
Извлечение идёт настоящим путём ``Filling.extract_version`` на стенде ``extraction_stand``:
модель — фейковый провайдер шлюза, библиотека — поддельный транспорт, сеть запрещена
автофикстурой ``tests/knowledge/conftest.py``. Property-тесты берут пары «вход, ожидание» из
``strategies.py``: оракул не импортирует проверяемые функции.
"""

from __future__ import annotations

import unicodedata
from pathlib import Path

import pytest
import yaml
from hypothesis import HealthCheck, assume, example, given, settings
from hypothesis import strategies as hs
from sqlalchemy import insert, select

from philograph.knowledge import naming
from philograph.knowledge import schema as t
from philograph.knowledge.naming import InvalidName
from philograph.knowledge.review import Review
from philograph.operator.access import ActionLog

from ..conftest import PROFILES
from .conftest import CatalogService
from .extraction_stand import Stand
from .strategies import (
    expected_label,
    name_of,
    names_with_reason,
    scripts_mix,
    sentinel,
)
from .wd_records import no_network  # noqa: F401

req = pytest.mark.req
NM = "entity-naming"
LANG = "Язык названий сущностей"
VALID = "Валидность названий сущностей"
CTX = {"request_id", "run_id", "service"}  # поля контекста, которые журнал добавляет сам
REJECTED = "knowledge.entity.rejected"
RENAMED = "knowledge.entity.renamed"
CREATED = "knowledge.entity.created"
DROPPED = "knowledge.extraction.dropped"
DB_SETTINGS = settings(
    parent=PROFILES["ci"], suppress_health_check=[HealthCheck.function_scoped_fixture]
)
HEAVY = settings(
    parent=PROFILES["heavy"], suppress_health_check=[HealthCheck.function_scoped_fixture]
)
PURE = settings(parent=PROFILES["pure"])


def fields(event) -> dict:
    return {k: v for k, v in event.fields.items() if k not in CTX}


def names(onto, entity_id) -> set[tuple[str, str, str]]:
    return {(n["lang"], n["text"], n["kind"]) for n in onto.entities.get(entity_id)["names"]}


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


def no_token(events, token: str, allowed: set[tuple[str, str]] = frozenset()) -> None:
    """Сторожевой токен не попал ни в одно событие, кроме разрешённых полей."""
    for event in events.items:
        for key, value in event.fields.items():
            if (event.name, key) in allowed:
                continue
            assert token not in repr(value), (event.name, key, value)


def by_text(onto, text: str) -> list[str]:
    with onto.statements.engine.begin() as conn:
        return list(conn.scalars(select(t.names.c.entity_id).where(t.names.c.text == text)))


@pytest.fixture
def stand(onto, engine_for, clock) -> Stand:
    return Stand(onto, engine_for, clock)


# =========================== Язык названий сущностей ======================================


@req(NM, LANG, scenario="Русский учебник")
def test_russian_textbook(stand, onto, clock, events):
    token = sentinel()
    stand.extract(
        [f"Платон учил о мире идей. {token}"],
        {
            "statements": [st("Платон", "holds", "Учение об идеях", 1, "Платон учил о мире идей")],
            "entities": [{"name": "Платон", "type": "person", "ru": "Платон", "en": "Plato"}],
        },
    )
    [plato] = by_text(onto, "Платон")
    assert stand.entities_of("person") == 1
    assert names(onto, plato) == {("ru", "Платон", "primary"), ("en", "Plato", "variant")}
    data, _rid = CatalogService(onto, clock).catalog_ok({"q": "Платон"})
    [item] = [i for i in data["items"] if i["id"] == plato]
    assert item["label"] == "Платон"
    [created] = events.where(CREATED, type="person")
    assert fields(created) == {"entity_id": plato, "type": "person"}
    no_token(events, token)


def _mention(onto, entity_id: str) -> int:
    with onto.statements.engine.begin() as conn:
        return conn.execute(
            insert(t.mentions).values(
                target_id="p_old",
                target_kind="paragraph",
                source_id="s_old",
                chapter_id="c_old",
                source_title="Старый учебник",
                chapter_title="Глава",
                entity_id=entity_id,
                start=0,
                end=5,
                method="exact",
                position=1,
            )
        ).inserted_primary_key[0]


def _mention_entity(onto, mention_id: int) -> str:
    with onto.statements.engine.begin() as conn:
        return conn.scalar(select(t.mentions.c.entity_id).where(t.mentions.c.id == mention_id))


@req(NM, LANG, scenario="Существующая английская сущность")
def test_existing_english_entity_gets_russian_primary(stand, onto, events):
    plato = onto.entities.create("person", [("en", "Plato", "primary")])
    onto.entities.add_external(plato, "wikidata", "Q859")
    idea = onto.thing("position", "Теория идей")
    old = onto.sourced(plato, "holds", idea)
    mention = _mention(onto, plato)
    persons = stand.entities_of("person")
    events.clear()
    stand.extract(
        ["Платон основал Академию в Афинах."],
        {
            "statements": [
                st("Платон", "holds", "Учение об Академии", 1, "Платон основал Академию")
            ],
            "entities": [{"name": "Платон", "type": "person", "ru": "Платон", "en": "Plato"}],
        },
    )
    assert onto.entities.resolve(plato) == plato
    assert names(onto, plato) == {("ru", "Платон", "primary"), ("en", "Plato", "variant")}
    assert stand.entities_of("person") == persons
    assert onto.statements.get(old)["subject"] == plato
    assert _mention_entity(onto, mention) == plato
    assert onto.entities.externals("wikidata") == {plato: "Q859"}
    new = [s for s in stand.statements() if s["id"] != old and s["type"] == "holds"]
    assert [s["subject"] for s in new] == [plato]
    [renamed] = events.of(RENAMED)
    assert fields(renamed) == {"entity_id": plato, "lang": "ru", "previous_lang": "en"}
    assert events.where(CREATED, type="person") == []


@req(NM, LANG, scenario="Латиница без русского написания")
def test_latin_without_russian(stand, onto, events):
    stand.extract(
        ["Кант называл это Ding an sich, вещью в себе."],
        {
            "statements": [
                st(
                    "Ding an sich",
                    "opposed_to",
                    "Явление",
                    1,
                    "Кант называл это Ding an sich",
                    subject_type="concept",
                    object_type="concept",
                )
            ],
            "entities": [{"name": "Ding an sich", "type": "concept"}],
        },
    )
    [concept] = by_text(onto, "Ding an sich")
    assert onto.entities.get(concept)["type"] == "concept"
    assert names(onto, concept) == {("en", "Ding an sich", "primary")}
    assert len(events.where(CREATED, type="concept", entity_id=concept)) == 1


@req(NM, LANG, scenario="Язык по письменности на любом пути")
def test_language_by_script_on_every_path(stand, onto, events, no_network):
    from philograph.knowledge.geo_enrich import PlaceEnrichment

    from .test_geo_enrich import Fetch, person_record
    from .wd_records import record

    def langs(entity_id):
        return {n["lang"] for n in onto.entities.get(entity_id)["names"]}

    events.clear()
    source = onto.entities.source_entity("s_empiricism", "Empiricism: a demonstration reader")
    report = stand.filling.accept_core_report([{"name": "Locke", "type": "person"}], "operator")
    [locke] = report["created"]
    kant = onto.person("Иммануил Кант", wikidata="Q9312")
    records = {
        "Q9312": person_record("Q9312", "Иммануил Кант", items={"P19": ["Q4120832"]}),
        "Q4120832": record("Q4120832", en="Königsberg", classes=("Q515",)),
    }
    PlaceEnrichment(onto.statements, Fetch(records)).run()
    place = onto.entities.by_external("wikidata", "Q4120832")
    assert place is not None
    louis = onto.entities.create("person", [("en", "Людовик XIV", "primary")])
    aristotle = onto.entities.create("person", [("ru", "Ἀριστοτέλης", "primary")])
    glued = onto.entities.create("person", [("ru", "Kant-Кант", "primary")])
    got = [langs(e) for e in (source, locke, place, louis, aristotle, glued)]
    assert got == [{"en"}, {"en"}, {"en"}, {"ru"}, {"el"}, {"und"}]
    created = {e["entity_id"] for e in events.of(CREATED)}
    assert {source, locke, place, louis, aristotle, glued, kant} <= created
    assert len(events.of(CREATED)) == len(created)


@req(NM, LANG, scenario="Русское написание не прошло проверку")
def test_rejected_russian_spelling(stand, onto, events):
    plato = onto.entities.create("person", [("en", "Plato", "primary")])
    events.clear()
    stand.extract(
        ["Plato, как говорит поэт, учил об идеях."],
        {
            "statements": [st("Plato", "holds", "Учение об идеях", 1, "учил об идеях")],
            "entities": [{"name": "Plato", "type": "person", "ru": "поэт"}],
        },
    )
    assert names(onto, plato) == {("en", "Plato", "primary")}
    assert by_text(onto, "поэт") == []
    [rejected] = events.of(REJECTED)
    assert fields(rejected) == {"type": "person", "label": "поэт", "reason": "not_a_name"}
    events.assert_none(RENAMED)


@req(NM, LANG, scenario="Написания нашли разные сущности")
def test_spellings_found_different_entities(stand, onto, engine_for, clock, events):
    substance = onto.entities.create("concept", [("en", "Substance", "primary")])
    substantia = onto.entities.create("concept", [("ru", "Субстанция", "primary")])
    onto.entities.create("concept", [("ru", "Акциденция", "primary")])
    events.clear()
    stand.extract(
        ["Субстанция есть то, что существует само по себе."],
        {
            "statements": [
                st(
                    "Субстанция",
                    "opposed_to",
                    "Акциденция",
                    1,
                    "Субстанция есть то, что существует само по себе",
                    subject_type="concept",
                    object_type="concept",
                )
            ],
            "entities": [
                {"name": "Субстанция", "type": "concept", "ru": "Субстанция", "en": "Substance"}
            ],
        },
    )
    assert stand.count(t.entities, type="concept") == 3
    assert by_text(onto, "Субстанция") == [substantia] and by_text(onto, "Substance") == [substance]
    assert [s for s in stand.statements() if s["type"] == "opposed_to"] == []
    review = Review(onto.statements, ActionLog(onto.statements.engine, clock))
    [item] = review.queue(kind="ambiguous_link")
    assert {substance, substantia} <= set(repr(item).replace("'", '"').split('"'))
    [ambiguous] = events.of("knowledge.extraction.ambiguous")
    assert ambiguous["candidates"] == 2
    assert [d["reason"] for d in events.of(DROPPED)] == ["entity:ambiguous"]  # О18: код


# --- инвариант языка ---------------------------------------------------------------------


@req(NM, LANG, invariant="Язык названия по письменности (пп. 1–5), чистая функция")
@PURE
@given(scripts_mix())
@example((("Kant-Кант", "ru"), "und", None))
@example((("Людовик XIV", "en"), "ru", None))
@example((("Ἀριστοτέλης", "ru"), "el", None))
@example((("Königsberg", "en"), "en", None))
@example((("Locke", "ru"), "en", None))
@example((("Mill", "ru"), "en", None))  # J1: буквы IVXLCDM не заглавными — латиница
@example((("Civil Xiv", None), "en", None))
@example((("Empiricism: a demonstration reader", "ru"), "en", None))
@example((("Ding an sich", "de"), "de", None))
@example((("XIV", "ru"), "und", None))
@example((("(XIV) Кант", "la"), "ru", None))
@example((("Аристотель", "grc"), "ru", None))
@example((("Ἀριστοτέλης", "grc"), "grc", None))
@example((("汉字", "en"), "und", None))
# аудит пунктов (О21): п. 1 — знаки по краям слова, римское число с точкой/скобками
@example((("(XIV) Ки", None), "ru", None))
@example((("Людовик XIV.", None), "ru", None))
# п. 2 — цифры не буквы; границы диапазонов кириллицы, греческой и прочих
@example((("Kant 1781", None), "en", None))
@example((("Ки 1781 1724", None), "ru", None))
@example((("Ԯԯ", None), "ru", None))  # U+052E, U+052F — последние кириллические
@example((("Ͱͱ", None), "el", None))  # U+0370 — первая греческая
@example((("ῳῳ", "grc"), "grc", None))  # U+1FF3 — расширенная греческая
@example((("Աբգ", "ru"), "und", None))  # армянская — прочая
# п. 3–4 — равенство, нет букв
@example((("Kant-Кант", None), "und", None))
@example((("1781", "ru"), "und", None))
@example((("!!!", "en"), "und", None))
# п. 5 — таблица письменностей переданных языков
@example((("Ens rationis", "la"), "la", None))
@example((("Cogito", "fr"), "fr", None))
@example((("Cogito", "it"), "it", None))
@example((("Cogito", "zz"), "en", None))
@example((("Cogito", "ru"), "en", None))
@example((("Платон", "en"), "ru", None))
@example((("Платон", "la"), "ru", None))
@example((("Платон", "ru"), "ru", None))
@example((("Plato", "grc"), "en", None))
@example((("Ἀριστοτέλης", "el"), "el", None))
def test_lang_for_any_text(case):
    (text, given_lang), expected, _info = case
    assert naming.lang_for(text, given_lang) == expected


def _primaries_per_lang(onto, entity_id: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for n in onto.entities.get(entity_id)["names"]:
        if n["kind"] == "primary":
            counts[n["lang"]] = counts.get(n["lang"], 0) + 1
    return counts


@req(NM, LANG, scenario="Инвариант языка и основного названия")
@req(NM, LANG, invariant="Язык каждого названия по письменности для create и add_name")
@DB_SETTINGS
@given(main=scripts_mix(), extra=scripts_mix())
@example(main=(("Kant-Кант", "ru"), "und", None), extra=(("Locke", "ru"), "en", None))
@example(main=(("Людовик XIV", "en"), "ru", None), extra=(("Ἀριστοτέλης", "ru"), "el", None))
@example(main=(("Mill", "ru"), "en", None), extra=(("Lid", None), "en", None))  # J1
def test_language_invariant_create_and_add_name(onto, events, main, extra):
    (text, given_lang), expected, _ = main
    (vtext, vgiven), vexpected, _ = extra
    before = stand_count(onto)
    created_before = len(events.of(CREATED))
    entity = onto.entities.create("concept", [(given_lang or "ru", text, "primary")])
    onto.entities.add_name(entity, vgiven or "ru", vtext)
    langs = {(n["text"], n["kind"]): n["lang"] for n in onto.entities.get(entity)["names"]}
    assert langs[(name_of(text), "primary")] == expected
    if name_of(vtext) != name_of(text):
        assert langs[(name_of(vtext), "variant")] == vexpected
    assert set(_primaries_per_lang(onto, entity).values()) == {1}
    assert stand_count(onto) - before == len(events.of(CREATED)) - created_before == 1


@req(
    NM,
    LANG,
    invariant="Латиницы вне римских чисел не меньше кириллицы — не ru; перевес кириллицы — ru",
)
@pytest.mark.parametrize(
    ("text", "is_ru"),
    [
        ("Locke", False),  # язык передан ru, кириллицы нет
        ("Kant-Кант", False),  # равенство: 4 и 4
        ("Kantt-Кант", False),  # латиницы больше
        ("Кантq", True),  # перевес кириллицы: 4 против 1
        ("Иммануил Kant", True),  # кириллицы 8, латиницы 4
        ("Людовик XIV", True),  # римское число — не латиница
        ("XIV", False),  # одни римские цифры: кириллицы нет
    ],
)
def test_no_latin_name_has_ru(onto, events, text, is_ru):
    """О15: формулировка инварианта после правки спецификации (Д1)."""
    entity = onto.entities.create("concept", [("ru", text, "primary")])
    [name] = onto.entities.get(entity)["names"]
    assert (name["lang"] == "ru") == is_ru, (text, name["lang"])
    assert events.where(CREATED, entity_id=entity)


@req(NM, LANG, invariant="Основное — русское написание ru, если оно русское и прошло проверку")
@pytest.mark.parametrize(
    ("item", "expected"),
    [
        # ru не русское (латиница): основное — name, ru — вариант
        (
            {"name": "Платон", "type": "person", "ru": "Plato"},
            {("ru", "Платон", "primary"), ("en", "Plato", "variant")},
        ),
        # ru смешанное с перевесом латиницы — не русское
        (
            {"name": "Kant", "type": "person", "ru": "Kantt-Кант"},
            {("en", "Kant", "primary"), ("en", "Kantt-Кант", "variant")},
        ),
        # ru русское и годное: основное — ru
        (
            {"name": "Plato", "type": "person", "ru": "Платон", "en": "Plato"},
            {("ru", "Платон", "primary"), ("en", "Plato", "variant")},
        ),
        # ru русское, но не прошло проверку: основное — name, ru не записано
        ({"name": "Plato", "type": "person", "ru": "поэт"}, {("en", "Plato", "primary")}),
    ],
)
def test_primary_choice_by_item(events, item, expected):
    got = {(lang, text, kind) for lang, text, kind in naming.names_for(item["type"], item)}
    assert got == expected


def stand_count(onto) -> int:
    with onto.statements.engine.begin() as conn:
        return len(list(conn.scalars(select(t.entities.c.id))))


# =========================== Валидность названий сущностей ================================


def _rejected_fields(events):
    return [fields(e) for e in events.of(REJECTED)]


@req(NM, VALID, scenario="Номер раздела")
def test_section_number(stand, onto, events):
    token = sentinel()
    stand.extract(
        [f"См. 20.1 о субстанции. {token}"],
        {
            "statements": [
                st(
                    "20.1",
                    "opposed_to",
                    "Акциденция",
                    1,
                    "См. 20.1 о субстанции",
                    subject_type="concept",
                    object_type="concept",
                )
            ]
        },
    )
    assert by_text(onto, "20.1") == []
    assert [s for s in stand.statements() if s["type"] == "opposed_to"] == []
    assert _rejected_fields(events) == [{"type": "concept", "label": "20.1", "reason": "number"}]
    assert [d["reason"] for d in events.of(DROPPED)] == ["entity:number"]  # О17: код без названия
    no_token(events, token)


@req(NM, VALID, scenario="Номер со знаками")
def test_numbers_with_marks(onto, events):
    for raw in ("§ 20.1", "(3.2)", "20,1"):
        with pytest.raises(InvalidName):
            onto.entities.create("concept", [("ru", raw, "primary")])
    assert stand_count(onto) == 0
    assert [e["reason"] for e in events.of(REJECTED)] == ["number"] * 3
    assert [e["label"] for e in events.of(REJECTED)] == ["§ 20.1", "(3.2)", "20,1"]


@req(NM, VALID, scenario="Предложение вместо термина")
def test_sentence_instead_of_term(stand, onto, events):
    name = "the author of An Inquiry into the Human Mind"
    stand.extract(
        ["Его называют the author of An Inquiry into the Human Mind."],
        {
            "statements": [
                st(name, "holds", "Здравый смысл", 1, "Его называют the author of An Inquiry")
            ],
            "entities": [{"name": name, "type": "person"}],
        },
    )
    assert by_text(onto, name) == []
    assert stand.entities_of("person") == 0
    [rejected] = events.of(REJECTED)
    assert fields(rejected) == {"type": "person", "label": name, "reason": "sentence"}


@req(NM, VALID, scenario="Описание с заглавной")
def test_description_with_capital(onto, events):
    for raw in ("The author of the Treatise", "Author of Leviathan"):
        with pytest.raises(InvalidName) as caught:
            onto.entities.create("person", [("en", raw, "primary")])
        assert caught.value.reason == "not_a_name"
    assert stand_count(onto) == 0
    assert _rejected_fields(events) == [
        {"type": "person", "label": "The author of the Treatise", "reason": "not_a_name"},
        {"type": "person", "label": "Author of Leviathan", "reason": "not_a_name"},
    ]


@req(NM, VALID, scenario="Роль вместо имени")
def test_role_instead_of_name(stand, onto, events):
    stand.extract(
        ["Слепой математик, blind mathematician у Дидро, рассуждал о пространстве."],
        {
            "statements": [
                st("blind mathematician", "holds", "Пространство", 1, "blind mathematician у Дидро")
            ]
        },
    )
    assert stand.entities_of("person") == 0
    assert _rejected_fields(events) == [
        {"type": "person", "label": "blind mathematician", "reason": "not_a_name"}
    ]
    assert [d["reason"] for d in events.of(DROPPED)] == ["entity:not_a_name"]  # О17


@req(NM, VALID, scenario="Стоп-слово у понятия")
def test_stopword_concept(stand, onto, events):
    stand.extract(
        ["Every idea comes from experience."],
        {
            "statements": [
                st(
                    "Every",
                    "opposed_to",
                    "Врождённые идеи",
                    1,
                    "Every idea comes from experience",
                    subject_type="concept",
                    object_type="concept",
                )
            ]
        },
    )
    assert by_text(onto, "Every") == []
    [rejected] = events.of(REJECTED)
    assert fields(rejected) == {"type": "concept", "label": "Every", "reason": "stopword"}


@req(NM, VALID, scenario="Пустое название")
def test_empty_names(stand, onto, events):
    stand.extract(
        ["Термин — обозначает понятие опыта."],
        {
            "statements": [
                st(
                    raw,
                    "denotes",
                    "Опыт",
                    1,
                    "обозначает понятие опыта",
                    subject_type="term",
                    object_type="concept",
                )
                for raw in (" ", "—")
            ]
        },
    )
    assert stand.entities_of("term") == 0
    got = [(e["type"], e["reason"]) for e in events.of(REJECTED)]
    assert got == [("term", "empty"), ("term", "empty")]


@req(NM, VALID, scenario="Склейка двух имён")
def test_glued_names(stand, onto, events):
    stand.extract(
        ["Kepler and Des Cartes писали об оптике."],
        {"statements": [st("Kepler and Des Cartes", "holds", "Оптика", 1, "писали об оптике")]},
    )
    assert stand.entities_of("person") == 0
    [rejected] = events.of(REJECTED)
    assert fields(rejected) == {
        "type": "person",
        "label": "Kepler and Des Cartes",
        "reason": "not_a_name",
    }


@req(NM, VALID, scenario="Границы предела")
def test_limit_boundaries(onto, events):
    six = "Один Два Три Четыре Пять Шесть"
    seven = six + " Семь"
    eighty = "Б" * 80
    eighty_one = "В" * 81
    twelve = " ".join(["Слово"] * 12)
    assert (len(six.split()), len(seven.split()), len(eighty), len(eighty_one)) == (6, 7, 80, 81)
    results = []
    for type_, raw in (
        ("concept", six),
        ("concept", seven),
        ("concept", eighty),
        ("concept", eighty_one),
        ("work", twelve),
    ):
        try:
            results.append(onto.entities.create(type_, [("ru", raw, "primary")]))
        except InvalidName as exc:
            results.append(exc.reason)
    assert results[1] == "sentence" and results[3] == "sentence"
    assert all(
        isinstance(r, str) and r.startswith("e_") for r in (results[0], results[2], results[4])
    )
    labels = [e["label"] for e in events.of(REJECTED)]
    assert [e["reason"] for e in events.of(REJECTED)] == ["sentence", "sentence"]
    assert labels[0] == seven
    assert len(labels[1]) == 80 and labels[1] == "В" * 79 + "…"


@req(NM, VALID, scenario="Имя с частицей и римским числом")
def test_particles_and_roman(onto, events):
    raws = ["де Бройль", "ибн Сина", "аль-Фараби", "д’Аламбер", "Людовик XIV"]
    created = [onto.entities.create("person", [("ru", raw, "primary")]) for raw in raws]
    assert [onto.entities.label(e) for e in created] == raws
    events.assert_none(REJECTED)
    assert len(events.where(CREATED, type="person")) == 5


@req(NM, VALID, scenario="Ручное создание")
def test_manual_core(stand, onto, events):
    report = stand.filling.accept_core_report(
        [{"name": "your Lordship", "type": "person"}, {"name": "Локк", "type": "person"}],
        "operator",
    )
    [locke] = report["created"]
    assert onto.entities.label(locke) == "Локк"
    assert report["rejected"] == [
        {"name": "your Lordship", "type": "person", "reason": "not_a_name"}
    ]
    assert by_text(onto, "your Lordship") == []
    assert _rejected_fields(events) == [
        {"type": "person", "label": "your Lordship", "reason": "not_a_name"}
    ]
    assert len(events.where(CREATED, type="person")) == 1


@req(NM, VALID, invariant="Ядро: отклонённый элемент возвращается с причиной, остальные создаются")
def test_core_rejection_reasons(stand, onto, events):
    items = [
        {"name": "20.1", "type": "concept"},
        {"name": "Локк", "type": "person"},
        {"name": "Every", "type": "concept"},
        {"name": "—", "type": "term"},
        {"name": "Один Два Три Четыре Пять Шесть Семь", "type": "concept"},
        {"name": "Hume and Locke", "type": "person"},
        {"name": "Сознание", "type": "concept"},
    ]
    report = stand.filling.accept_core_report(items, "operator")
    assert [onto.entities.label(e) for e in report["created"]] == ["Локк", "Сознание"]
    assert report["rejected"] == [
        {"name": "20.1", "type": "concept", "reason": "number"},
        {"name": "Every", "type": "concept", "reason": "stopword"},
        {"name": "—", "type": "term", "reason": "empty"},
        {"name": items[4]["name"], "type": "concept", "reason": "sentence"},
        {"name": "Hume and Locke", "type": "person", "reason": "not_a_name"},
    ]
    assert [f["reason"] for f in _rejected_fields(events)] == [
        "number",
        "stopword",
        "empty",
        "sentence",
        "not_a_name",
    ]
    assert len(events.of(CREATED)) == 2


@req(NM, VALID, scenario="Стоп-список из данных")
def test_stopword_list_from_data(onto, events, tmp_path, monkeypatch):
    data = yaml.safe_load(naming.RULES_PATH.read_text(encoding="utf-8"))
    data["stopwords"] = [*data["stopwords"], "некто"]
    path = tmp_path / "naming_rules.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    control = onto.entities.create("concept", [("ru", "Некто", "primary")])  # без слова — создаётся
    assert onto.entities.label(control) == "Некто"
    # Правила — данные: загрузка правил читает другой файл данных, код не меняется.
    original = naming.load_rules
    monkeypatch.setattr(naming, "load_rules", lambda *_a, **_k: original(Path(path)))
    with pytest.raises(InvalidName) as caught:
        onto.entities.create("concept", [("ru", "Некто", "primary")])
    assert caught.value.reason == "stopword"
    assert _rejected_fields(events) == [{"type": "concept", "label": "Некто", "reason": "stopword"}]


@req(NM, VALID, invariant="Знаки — кодовые точки названия после strip() и NFC")
@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ("Е\u0308" * 80, None),  # NFD: 160 кодовых точек, после NFC — 80
        ("Е\u0308" * 81, "sentence"),
        ("  " + "Е\u0308" * 80 + "\t", None),
    ],
)
def test_signs_counted_after_nfc(onto, events, raw, reason):
    assert naming.check_name("concept", raw) == reason
    try:
        onto.entities.create("concept", [("ru", raw, "primary")])
    except InvalidName as exc:
        assert exc.reason == reason
        [rejected] = events.of(REJECTED)
        assert fields(rejected) == {
            "type": "concept",
            "label": expected_label(raw),
            "reason": "sentence",
        }
    else:
        assert reason is None
        events.assert_none(REJECTED)


def _rules_from(tmp_path, monkeypatch, mutate):
    data = yaml.safe_load(naming.RULES_PATH.read_text(encoding="utf-8"))
    mutate(data)
    path = tmp_path / "naming_rules.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    original = naming.load_rules
    monkeypatch.setattr(naming, "load_rules", lambda *_a, **_k: original(Path(path)))


def _limit(data):
    data["limits"]["default"] = {"max_words": 2, "max_chars": 80}


def _limit_chars(data):
    data["limits"]["concept"] = {"max_words": 6, "max_chars": 5}


def _particle(data):
    data["person"]["particles"].append("зу")


def _pattern(data):
    data["person"]["patterns"].append("^some one ")


def _conjunction(data):
    data["person"]["conjunctions"].append("or")


def _person_types(data):
    data["person"]["types"].append("group")


def _exempt(data):
    data["exempt"].append("concept")


@req(
    NM, VALID, invariant="Правила — данные: стоп-список, пределы, частицы, шаблоны без правки кода"
)
@pytest.mark.parametrize(
    ("mutate", "type_", "label", "control", "reason"),
    [
        (_limit, "concept", "Один Два Три", "Один Два", "sentence"),  # предел слов по типу
        (_limit_chars, "concept", "Шестой", "Пять", "sentence"),  # предел знаков по типу
        (_particle, "person", "зу Чжи", "зу Чжи", None),  # частица из данных: строчная допустима
        (_pattern, "person", "Some one Else", "Some two Else", "not_a_name"),  # шаблон
        (_conjunction, "person", "Kant or Hume", "Kant nor Hume", "not_a_name"),  # союз
        (_person_types, "group", "группа людей", "Группа людей", "not_a_name"),  # типы персон
        (_exempt, "concept", "20.1", "20.2", None),  # типы вне проверки
    ],
)
def test_rules_are_data(onto, events, tmp_path, monkeypatch, mutate, type_, label, control, reason):
    """Без правки данных ``label`` даёт другой результат, чем с ними: код один и тот же."""
    before = naming.check_name(type_, label)
    _rules_from(tmp_path, monkeypatch, mutate)
    after = naming.check_name(type_, label)
    assert after == reason
    assert before != after  # данные изменили исход: правило не зашито в код
    if reason is None:
        entity = onto.entities.create(type_, [("ru", label, "primary")])
        assert onto.entities.label(entity) == label
        events.assert_none(REJECTED)
    else:
        with pytest.raises(InvalidName) as caught:
            onto.entities.create(type_, [("ru", label, "primary")])
        assert caught.value.reason == reason
        assert _rejected_fields(events) == [{"type": type_, "label": label, "reason": reason}]


# --- инвариант отказа --------------------------------------------------------------------

BOUNDARY_EXAMPLES = [
    (("concept", "Один Два Три Четыре Пять Шесть"), None),
    (("concept", "Один Два Три Четыре Пять Шесть Семь"), "sentence"),
    (("concept", "Б" * 80), None),
    (("concept", "В" * 81), "sentence"),
    (("work", " ".join(["Слово"] * 12)), None),
    (("work", " ".join(["Слово"] * 13)), "sentence"),
    (("event", "Г" * 160), None),
    (("event", "Д" * 161), "sentence"),
    (("person", "your Lordship"), "not_a_name"),
    (("person", "Your Lordship"), "stopword"),
    (("concept", "your lordship"), "stopword"),
    (("person", "The author of the Treatise"), "not_a_name"),
    (("person", "Author of Leviathan"), "not_a_name"),
    (("person", "THE TEACHER OF Plato"), "not_a_name"),
    (("person", "аль-Фараби"), None),
    (("person", "д’Аламбер"), None),
    (("person", "d'Alembert"), None),
    (("person", "де Бройль"), None),
    (("person", "Людовик XIV"), None),
    (("person", "Kant-Кант"), None),
    (("person", "Кант и Юм"), "not_a_name"),
    (("person", "Kepler and Des Cartes"), "not_a_name"),
    (("person", "blind mathematician"), "not_a_name"),
    (("concept", "§ 20.1"), "number"),
    (("concept", "23.4.3"), "number"),
    (("concept", "(3.2)"), "number"),
    (("concept", "20,1"), "number"),
    (("term", " "), "empty"),
    (("term", "—"), "empty"),
    (("term", ""), "empty"),
    (("concept", "Тот, кто  чувствует"), "stopword"),
    (("concept", "тот кто чувствуёт"), "stopword"),
    (("concept", "  EVERY "), "stopword"),
    (("source", "20.1"), None),
    # --- аудит пунктов (О21): ветви правила 4 ---
    (("person", "Кант и юм"), None),  # склейка — только между двумя словами с заглавной
    (("person", "Kant and hume"), None),
    (("person", "Kepler & Des Cartes"), "not_a_name"),
    (("person", "dE Broglie"), None),  # частица без учёта регистра
    (("person", "дЕ Бройль"), None),
    (("person", "ван Гог"), None),
    (("person", "von Neumann"), None),
    (("person", "ibn Rushd"), None),
    (("person", "al-Kindi"), None),
    (("person", "the Author of Hume"), "not_a_name"),
    (("person", "Author Of Leviathan"), "not_a_name"),
    (("person", "the author of An Inquiry into the Human Mind"), "sentence"),  # 9 слов > 6
    (("person", "кант"), "not_a_name"),  # первая буква строчная, частицы нет
    (("person", "(кант)"), "not_a_name"),
    (("concept", "кант и Юм"), None),  # не персона: not_a_name не применяется
    (("concept", "Кант и Юм"), None),
    (("work", "Kepler and Des Cartes"), None),
    (("concept", "The author of the Treatise"), None),
    (("doctrine", "the teacher of Plato"), None),
    # порядок: empty и number раньше sentence, sentence раньше not_a_name
    (("concept", "1 2 3 4 5 6 7"), "number"),
    (("work", " ".join(["1"] * 13)), "number"),
    (("term", "- - - - - - -"), "empty"),
    (("person", "a b c d e f g"), "sentence"),
    # пределы остальных типов и слова по любому пробельному
    (("idea_event", " ".join(["Слово"] * 12)), None),
    (("idea_event", " ".join(["Слово"] * 13)), "sentence"),
    (("phenomenon", "Ж" * 160), None),
    (("phenomenon", "Ж" * 161), "sentence"),
    (("place", " ".join(["Слово"] * 7)), "sentence"),
    (("concept", "Один\tДва\nТри Четыре Пять Шесть Семь"), "sentence"),
    (("concept", "Тот кто чувствуе\u0308т"), "stopword"),
]


def _with_examples(test):
    for case in BOUNDARY_EXAMPLES:
        test = example(case)(test)
    return test


def _with_path_examples(test):
    for case in BOUNDARY_EXAMPLES:
        test = example(case=case, path="create")(test)
    for case in BOUNDARY_EXAMPLES[:12]:
        test = example(case=case, path="set_primary_name")(test)
    return test


@req(NM, VALID, invariant="Причина отказа по правилам 1–5, чистая функция")
@PURE
@given(names_with_reason())
@_with_examples
def test_check_name_any_input(case):
    (type_, raw), reason = case
    assert naming.check_name(type_, name_of(raw)) == reason
    assert naming.event_label(name_of(raw)) == expected_label(raw)


@req(NM, VALID, scenario="Инвариант отказа")
@req(NM, VALID, invariant="Создано тогда и только тогда, когда нет причины; одно событие")
@DB_SETTINGS
@given(case=names_with_reason(), path=hs.sampled_from(["create", "set_primary_name", "add_name"]))
@_with_path_examples
@example(case=(("concept", " 20.1 "), "number"), path="create")  # M3: label после strip
@example(case=(("concept", "  EVERY "), "stopword"), path="add_name")
@example(case=(("term", "\t"), "empty"), path="set_primary_name")
def test_rejection_invariant(onto, events, case, path):
    (type_, raw), reason = case  # сырой вход: label события — по оракулу strip + NFC (Д2)
    token = sentinel()
    if path == "create" or type_ == "source":
        before = stand_count(onto)
        events.clear()
        try:
            entity = onto.entities.create(
                type_, [("ru", raw, "primary"), ("en", f"Variant {token}", "variant")]
            )
        except InvalidName as exc:
            entity, got = None, exc.reason
        else:
            got = None
        assert got == reason
        assert (entity is not None) == (reason is None)
        assert stand_count(onto) - before == len(events.of(CREATED)) == (1 if reason is None else 0)
        if entity is not None:
            [primary] = [n for n in onto.entities.get(entity)["names"] if n["kind"] == "primary"]
            assert primary["text"] == name_of(raw)
    else:
        base = onto.entities.create(type_, [("ru", "Опорное Имя", "primary")])
        events.clear()
        try:
            if path == "set_primary_name":
                onto.entities.set_primary_name(base, "ru", raw)
            else:
                onto.entities.add_name(base, "ru", raw, kind="primary")
        except InvalidName as exc:
            got = exc.reason
        else:
            got = None
        assert got == reason
        primaries = {n["text"] for n in onto.entities.get(base)["names"] if n["kind"] == "primary"}
        if reason is None:
            assert name_of(raw) in primaries
        else:
            assert name_of(raw) not in {n["text"] for n in onto.entities.get(base)["names"]}
            assert "Опорное Имя" in primaries
        events.assert_none(CREATED)
    if reason is None:
        events.assert_none(REJECTED)
    else:
        [rejected] = events.of(REJECTED)
        assert fields(rejected) == {"type": type_, "label": expected_label(raw), "reason": reason}
    no_token(events, token)


@req(NM, VALID, invariant="label — название после strip() и NFC, обрезка до 80 знаков")
@pytest.mark.parametrize(
    ("type_", "raw", "reason"),
    [
        ("term", " ", "empty"),
        ("concept", "  EVERY ", "stopword"),
        ("concept", " 20.1 ", "number"),
        ("concept", " " + "Ж" * 80, None),  # название — 80 знаков: создаётся
        ("concept", " " + "Ж" * 81 + " ", "sentence"),
    ],
)
def test_rejected_label_is_name_after_strip(onto, events, type_, raw, reason):
    try:
        onto.entities.create(type_, [("ru", raw, "primary")])
    except InvalidName as exc:
        got = exc.reason
    else:
        got = None
    assert got == reason
    if reason is None:
        events.assert_none(REJECTED)
        return
    [rejected] = events.of(REJECTED)
    assert fields(rejected) == {"type": type_, "label": expected_label(raw), "reason": reason}


def test_strategies_oracle_independent():
    """Оракул стратегий не импортирует проверяемые функции (design.md, О7)."""
    import ast

    source = (Path(__file__).parent / "strategies.py").read_text(encoding="utf-8")
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported |= {a.name for a in node.names}
        elif isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
    banned = {"naming", "dating", "dates", "entity_items", "dedupe"}
    assert not {m for m in imported if any(b in m.split(".") for b in banned)}, imported


# --- О22: хранимая форма названия — strip + NFC на любом пути записи --------------------

_PAD = hs.sampled_from(["", " ", "  ", "\t", "\n", "  ", " "])
_STORED_POOL = ["Пётр Абеляр", "Йозеф Шумпетер", "Ἀριστοτέλης", "Renée Descartes", "Декарт"]


@hs.composite
def raw_names(draw, pool: bool = False) -> str:
    """Вход записи: пробелы по краям, NFD или NFC, смешанные письменности (``scripts_mix``)."""
    text = draw(hs.sampled_from(_STORED_POOL)) if pool else draw(scripts_mix())[0][0]
    form = draw(hs.sampled_from(["NFC", "NFD", "NFKD"]))
    if form != "NFKD":  # NFKD меняет совместимые знаки — не тот же текст; только NFD/NFC
        text = unicodedata.normalize(form, text)
    return draw(_PAD) + text + draw(_PAD)


def _stored(onto, entity_id) -> dict[str, str]:
    return {n["kind"]: n["text"] for n in onto.entities.get(entity_id)["names"]} | {
        "all": sorted(n["text"] for n in onto.entities.get(entity_id)["names"])
    }


@req(NM, VALID, invariant="Название хранится в форме strip+NFC на любом пути записи (О22)")
@DB_SETTINGS
@given(main=raw_names(), variant=raw_names(), primary=raw_names(pool=True))
@example(main=" Декарт ", variant="\tLocke\n", primary=" Пётр Абеляр ")
@example(
    main=unicodedata.normalize("NFD", "Ἀριστοτέλης"),
    variant=unicodedata.normalize("NFD", " Renée Descartes"),
    primary=unicodedata.normalize("NFD", "Йозеф Шумпетер") + " ",
)
@example(main="Kant-Кант ", variant=" Людовик XIV", primary="Декарт")
def test_stored_form_strip_nfc(onto, events, main, variant, primary):
    try:
        entity = onto.entities.create("concept", [("ru", main, "primary")])
    except InvalidName:
        assume(False)
    [created] = onto.entities.get(entity)["names"]
    assert created["text"] == name_of(main), (main, created["text"])
    onto.entities.add_name(entity, "ru", variant)
    texts = {n["text"] for n in onto.entities.get(entity)["names"]}
    assert texts == {name_of(main), name_of(variant)}, (main, variant, texts)
    onto.entities.set_primary_name(entity, "ru", primary)
    rows = onto.entities.get(entity)["names"]
    assert [n["text"] for n in rows if n["kind"] == "primary"] == [name_of(primary)]
    assert {n["text"] for n in rows} == {name_of(main), name_of(variant), name_of(primary)}


@req(NM, VALID, invariant="Название хранится в форме strip+NFC и через извлечение (О22)")
@pytest.mark.parametrize(
    "raw",
    [
        "  Пётр Абеляр ",
        unicodedata.normalize("NFD", "Пётр Абеляр"),
        "\t" + unicodedata.normalize("NFD", "Йозеф Шумпетер") + " ",
    ],
)
def test_stored_form_via_extraction(stand, onto, events, raw):
    name = name_of(raw)
    stand.extract(
        [f"{name} учил о мире идей."],
        {
            "statements": [st(raw, "holds", "Учение об идеях", 1, f"{name} учил о мире идей")],
            "entities": [{"name": raw, "type": "person", "ru": raw}],
        },
    )
    [entity] = by_text(onto, name)
    stored = {n["text"] for n in onto.entities.get(entity)["names"]}
    assert stored == {name}, (raw, stored)
    with onto.statements.engine.begin() as conn:
        texts = list(conn.scalars(select(t.names.c.text)))
    assert all(x == name_of(x) for x in texts), texts
