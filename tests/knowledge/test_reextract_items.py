"""ontology-extraction (reextract-with-claude): «Проверка ответа по утверждениям» и «Коды
причин отбраковки».

По дельте ``specs/ontology-extraction``. Ответ идёт настоящим путём: через шлюз
(``Filling.extract_version``) или через внешний извлекатель (``external_extraction.ingest``) —
по тексту дельты оба используют одну проверку. Вывод — утверждения и сущности в базе,
``filling_runs``; журнал — ``knowledge.extraction.dropped`` с ``code`` и
``knowledge.extraction.fragment``.
"""

from __future__ import annotations

import copy
import json
from collections import Counter

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as hst
from sqlalchemy import select

from philograph.knowledge import external_extraction as ext
from philograph.knowledge import extraction_codes as codes
from philograph.knowledge import schema as t

from ..conftest import PROFILES
from .extraction_stand import Stand
from .reextract_common import (
    FRAGMENT,
    assert_event_keys,
    check_run_accounting,
    dropped_codes,
    one_run,
)
from .reextract_common import st as stmt

req = pytest.mark.req
EO = "ontology-extraction"
CHECK = "Проверка ответа по утверждениям"
CODE = "Коды причин отбраковки"

TEXTS = [
    "Кант писал, что всякое знание начинается с опыта.",
    "Юм считал причинность привычкой ума.",
    "Локк отвергал врождённые идеи и сравнивал душу с чистой доской.",
]
Q1 = "всякое знание начинается с опыта"
Q2 = "причинность привычкой ума"
Q3 = "отвергал врождённые идеи"


@pytest.fixture
def stand(onto, engine_for, clock) -> Stand:
    return Stand(onto, engine_for, clock, fragment_size=8)


def ingest(stand, vid, replies, **extra):
    """Внешний путь: ответ на фрагмент 1 (или заданные) без шлюза."""
    data = stand.filling.version(vid)
    params = dict(
        model="claude-opus-5-5",
        input_tokens=1000,
        output_tokens=100,
        duration_seconds=1.0,
        cost_usd=0.01,
    )
    params.update(extra)
    return ext.ingest(stand.filling, data, replies, **params)


def external(stand, statements, entities=None, texts=TEXTS):
    vid, ids = stand.version(texts)
    reply = {"statements": statements}
    if entities is not None:
        reply["entities"] = entities
    ingest(stand, vid, {"1": reply})
    return vid, ids


def types_of(stand) -> list[str]:
    return sorted(s["type"] for s in stand.statements())


# --- сценарии ----------------------------------------------------------------------------


@req(EO, CHECK, scenario="Отклонения в одном ответе")
def test_deviations_in_one_reply(stand, events):
    reply = {
        "statements": [
            stmt("Кант", "holds", "Опыт", 1, Q1, attributed_to=None),
            stmt("Юм", "holds", "Привычка ума", "1", Q1),
            stmt("Локк", "rejects", "Врождённые идеи", 3, Q3),
            stmt("Беркли", "holds", "Идеализм", 2, Q2, subject_type="character"),
            stmt("Рид", "holds", "Здравый смысл", 2, 7),
        ]
    }
    _vid, ids = stand.extract(TEXTS, reply)
    by_subject = {s["subject"]: s for s in stand.statements()}
    assert len(by_subject) == 3
    named = {name: stand.onto.entities.find(name)[0]["id"] for name in ("Кант", "Юм", "Локк")}
    kant, hume, locke = (by_subject[named[n]] for n in ("Кант", "Юм", "Локк"))
    # 1: null — как отсутствие, атрибуция учебнику
    assert [(a["who_kind"], a["stance"]) for a in kant["attributions"]] == [("source", "asserts")]
    # 2: номер строкой — тот же номер, подтверждение из абзаца 1
    assert [e["paragraph_id"] for e in hume["evidence"]] == [ids[0]]
    # 3: код вне реестра — «испытал влияние» и предложение в очереди проверки
    assert locke["type"] == "influenced_by"
    assert [p["payload"]["code"] for p in stand.onto.registry.proposals()] == ["rejects"]
    assert sorted(dropped_codes(events)) == ["entity_type", "schema_item"]
    [fragment] = events.of(FRAGMENT)
    assert (fragment["created"], fragment["dropped"]) == (3, 2)
    assert stand.onto.entities.find("Беркли") == [] and stand.onto.entities.find("Рид") == []
    row = check_run_accounting(stand, events)
    assert row["created"] == 3 and row["dropped"] == 2
    assert row["drop_reasons"] == {"entity_type": 1, "schema_item": 1}
    assert_event_keys(events)


def collect_keys(node, key, found=None):
    found = [] if found is None else found
    if isinstance(node, dict):
        for k, v in node.items():
            if k == key:
                found.append(v)
            collect_keys(v, key, found)
    elif isinstance(node, list):
        for v in node:
            collect_keys(v, key, found)
    return found


@req(EO, CHECK, scenario="Мягкая схема в запросе")
def test_soft_schema_in_request(stand, events):
    stand.extract(TEXTS[:1], {"statements": []})
    [body] = stand.llm_transport.bodies
    schema = body["json_schema"]
    assert collect_keys(schema, "enum") == []  # перечней нет ни на каком уровне
    assert schema["required"] == ["statements"]
    item = schema["properties"]["statements"]["items"]
    assert sorted(item["required"]) == sorted(["subject", "type", "object", "paragraph", "quote"])
    # у полей элемента нет типов
    for spec in item["properties"].values():
        assert "type" not in spec
    entity = schema["properties"]["entities"]["items"]
    assert sorted(entity["required"]) == ["name", "type"]
    assert {"name", "type", "ru", "en", "original", "dating"} <= set(entity["properties"])
    for spec in entity["properties"].values():
        assert "type" not in spec
    assert "entities" not in schema["required"]
    # relations и entity_types — из реестра, по данным запроса
    registry_schema = stand.filling.registry_schema()
    assert body["data"]["relations"] == str(registry_schema["x-relations"])
    assert set(body["data"]["entity_types"].split(", ")) == set(stand.onto.registry.entity_types())
    assert "holds" in body["data"]["relations"] and "person" in body["data"]["entity_types"]
    assert events.of("knowledge.extraction.dropped") == []


@req(EO, CHECK, invariant="Схема реестра — контракт проверки и данные для модели, а не схема шлюза")
def test_registry_schema_stays_contract(stand):
    full = stand.filling.registry_schema()
    assert collect_keys(full, "enum")  # реестровая схема с перечнями остаётся
    gate = stand.llm_transport.bodies
    assert gate == []
    stand.extract(TEXTS[:1], {"statements": []})
    assert collect_keys(stand.llm_transport.bodies[0]["json_schema"], "enum") == []


# --- порядок проверок по пунктам дельты --------------------------------------------------

OK = stmt("Кант", "holds", "Опыт", 1, Q1)


def mutate(**changes):
    item = copy.deepcopy(OK)
    for key, value in changes.items():
        if value is ...:
            item.pop(key, None)
        else:
            item[key] = value
    return item


ITEM_FAULTS = [
    # (подпись, элемент, код)
    ("не объект: строка", "строка", "schema_item"),
    ("не объект: число", 5, "schema_item"),
    ("не объект: список", [OK], "schema_item"),
    ("не объект: null", None, "schema_item"),
    ("нет subject", mutate(subject=...), "schema_item"),
    ("нет type", mutate(type=...), "schema_item"),
    ("нет object", mutate(object=...), "schema_item"),
    ("нет paragraph", mutate(paragraph=...), "schema_item"),
    ("нет quote", mutate(quote=...), "schema_item"),
    ("null вместо обязательного quote", mutate(quote=None), "schema_item"),
    ("subject число", mutate(subject=3), "schema_item"),
    ("object список", mutate(object=["Опыт"]), "schema_item"),
    ("quote число", mutate(quote=7), "schema_item"),
    ("type пустая строка", mutate(type=""), "schema_item"),
    ("type число", mutate(type=1), "schema_item"),
    ("paragraph дробное", mutate(paragraph=1.5), "schema_item"),
    ("paragraph логическое", mutate(paragraph=True), "schema_item"),
    ("paragraph слово", mutate(paragraph="один"), "schema_item"),
    ("paragraph пустая строка", mutate(paragraph=""), "schema_item"),
    ("paragraph отрицательное строкой", mutate(paragraph="-1"), "schema_item"),
    ("paragraph надстрочная цифра", mutate(paragraph="²"), "schema_item"),
    ("qualifiers список", mutate(qualifiers=[1]), "schema_item"),
    ("qualifiers строка", mutate(qualifiers="x"), "schema_item"),
    ("attributed_to число", mutate(attributed_to=5), "schema_item"),
    ("proposed_type число", mutate(proposed_type=5), "schema_item"),
    ("stance вне перечня", mutate(stance="neutral"), "stance_invalid"),
    ("stance пустая строка", mutate(stance=""), "stance_invalid"),
    ("stance регистр", mutate(stance="Asserts"), "stance_invalid"),
    ("subject_type вне реестра", mutate(subject_type="character"), "entity_type"),
    ("object_type вне реестра", mutate(object_type="animal"), "entity_type"),
    ("связь реестра не для извлечения", mutate(type="lifespan"), "relation_not_allowed"),
    ("абзац 0", mutate(paragraph=0), "paragraph_out_of_window"),
    ("абзац -1", mutate(paragraph=-1), "paragraph_out_of_window"),
    ("абзац за окном", mutate(paragraph=4), "paragraph_out_of_window"),
    ("абзац огромный", mutate(paragraph=10**12), "paragraph_out_of_window"),
    ("цитаты нет в абзаце", mutate(quote="писал про Гегеля"), "quote_not_found"),
    ("пустая цитата", mutate(quote=""), "quote_not_found"),
    ("цитата из чужого абзаца", mutate(quote=Q2), "quote_not_found"),
    ("короткая часть", mutate(quote="Кант писал… опыта"), "quote_too_short"),
    ("пустой subject", mutate(subject=""), "entity_invalid"),
    ("пустой object", mutate(object="  "), "entity_invalid"),
    ("subject число-название", mutate(subject="123"), "entity_invalid"),
    ("новый без типа", mutate(subject_type=...), "entity_no_type"),
    ("тип не подходит концам", mutate(subject="Опыт", subject_type="position"), "type_mismatch"),
    ("уточнитель вне реестра", mutate(qualifiers={"нет_такого": 1}), "qualifier_invalid"),
]


@pytest.mark.parametrize(("label", "item", "code"), ITEM_FAULTS, ids=[f[0] for f in ITEM_FAULTS])
@req(
    EO,
    CHECK,
    invariant="Каждый отказ элемента — одно событие с кодом из перечня; остальные пишутся",
)
def test_item_fault_is_isolated_and_coded(stand, events, label, item, code):
    good = stmt("Юм", "holds", "Привычка ума", 2, Q2)
    external(stand, [item, good])
    assert dropped_codes(events) == [code], label
    # соседний элемент записан
    assert [s["type"] for s in stand.statements()] == ["holds"]
    hume = stand.onto.entities.find("Юм")[0]["id"]
    assert stand.statements()[0]["subject"] == hume
    row = check_run_accounting(stand, events)
    assert row["drop_reasons"] == {code: 1} and row["created"] == 1 and row["dropped"] == 1
    assert_event_keys(events)
    [fragment] = events.of(FRAGMENT)
    assert (fragment["created"], fragment["dropped"]) == (1, 1)


@req(
    EO,
    CHECK,
    invariant="Порядок проверок: схема, null, номер, позиция, типы, связь, абзац, цитата, привязка",
)
@pytest.mark.parametrize(
    ("first", "second"),
    [
        (mutate(subject=3, stance="x"), mutate(stance="neutral", subject_type="character")),
        (
            mutate(stance="neutral", subject_type="character"),
            mutate(subject_type="character", type="lifespan"),
        ),
        (mutate(subject_type="character", paragraph=9), mutate(type="lifespan", paragraph=9)),
        (mutate(type="lifespan", quote="нет"), mutate(paragraph=9, quote="нет")),
        (mutate(paragraph=9, quote="нет"), mutate(quote="нет", subject="")),
    ],
)
def test_check_order(stand, events, first, second):
    ladder = [
        "schema_item",
        "stance_invalid",
        "entity_type",
        "relation_not_allowed",
        "paragraph_out_of_window",
        "quote_not_found",
    ]
    external(stand, [first])
    got_first = dropped_codes(events)
    events.clear()
    external(stand, [second])
    got_second = dropped_codes(events)
    assert len(got_first) == len(got_second) == 1
    assert ladder.index(got_first[0]) < ladder.index(got_second[0])
    assert stand.statements() == []


@req(
    EO,
    CHECK,
    invariant="Ответ не объект или statements не массив — одна отбраковка фрагмента reply_invalid",
)
@pytest.mark.parametrize(
    "reply",
    [
        [],
        "строка",
        5,
        None,
        True,
        {},
        {"statements": "x"},
        {"statements": {}},
        {"statements": None},
        {"entities": []},
        [{"statements": []}],
    ],
)
def test_reply_invalid(stand, events, reply):
    vid, _ = stand.version(TEXTS)
    ingest(stand, vid, {"1": reply})
    assert dropped_codes(events) == ["reply_invalid"]
    row = check_run_accounting(stand, events)
    assert row["created"] == 0 and row["drop_reasons"] == {"reply_invalid": 1}
    assert stand.statements() == []
    [fragment] = events.of(FRAGMENT)
    assert (fragment["created"], fragment["dropped"]) == (0, 1)


@req(
    EO,
    CHECK,
    invariant="Шлюз отвергает ответ без обязательного поля (model_schema), внешний — schema_item",
)
def test_missing_required_field_gateway_vs_external(stand, events):
    broken = mutate(quote=...)
    good = stmt("Юм", "holds", "Привычка ума", 2, Q2)
    stand.extract(TEXTS, {"statements": [broken, good]})
    assert dropped_codes(events) == ["model_schema"]  # весь ответ отвергнут шлюзом
    assert stand.statements() == []
    row = check_run_accounting(stand, events)
    assert row["drop_reasons"] == {"model_schema": 1}
    events.clear()
    stand.reset()
    external(stand, [broken, good])
    assert dropped_codes(events) == ["schema_item"]
    assert len(stand.statements()) == 1  # остальные записаны


# --- null ≡ отсутствие ------------------------------------------------------------------

NULLABLE = {
    "subject_type": "person",
    "object_type": "position",
    "qualifiers": {},
    "stance": "disputes",
    "attributed_to": "Гегель",
    "proposed_type": "x_custom",
}


def snapshot(stand, events):
    rows = []
    for s in stand.statements():
        rows.append(
            (
                s["type"],
                s["qualifiers"],
                sorted((a["who_kind"], a["stance"]) for a in s["attributions"]),
                [e["quote"] for e in s["evidence"]],
            )
        )
    return (
        sorted(rows, key=repr),
        sorted(dropped_codes(events)),
        one_run(stand)["drop_reasons"],
    )


DECLARED = [{"name": "Кант", "type": "person"}, {"name": "Опыт", "type": "position"}]


@pytest.mark.parametrize("field", list(NULLABLE))
@pytest.mark.parametrize("with_value", [True, False])
@req(EO, CHECK, invariant="Поле со значением null обрабатывается так же, как отсутствующее")
def test_null_equals_absent(stand, events, field, with_value):
    base = stmt("Кант", "holds", "Опыт", 1, Q1)
    if with_value:  # поле, заполненное допустимым значением, и тот же элемент с null
        base[field] = NULLABLE[field]
    with_null = {**base, field: None}
    without = {k: v for k, v in base.items() if k != field}
    results = []
    for item in (with_null, without):
        events.clear()
        stand.reset()
        external(stand, [item], entities=DECLARED)  # типы концов заданы в entities
        results.append(snapshot(stand, events))
    assert results[0] == results[1]
    assert len(results[0][0]) == 1  # элемент записан в обоих случаях


@pytest.mark.parametrize("field", ["subject_type", "object_type"])
@req(EO, CHECK, invariant="Поле со значением null обрабатывается так же, как отсутствующее поле")
def test_null_type_equals_absent_for_new_entity(stand, events, field):
    base = stmt("Кант", "holds", "Опыт", 1, Q1)
    results = []
    for item in ({**base, field: None}, {k: v for k, v in base.items() if k != field}):
        events.clear()
        stand.reset()
        external(stand, [item])
        results.append(snapshot(stand, events))
    assert results[0] == results[1]
    assert results[0][1] == ["entity_no_type"] and results[0][0] == []


@req(
    EO, CHECK, invariant="null вместо необязательного поля сущности из entities — поле отсутствует"
)
def test_entities_item_nulls(stand, events):
    entities = [
        {"name": "Кант", "type": "person", "ru": None, "en": None, "original": None, "dating": None}
    ]
    external(stand, [stmt("Кант", "holds", "Опыт", 1, Q1)], entities=entities)
    assert events.of("knowledge.extraction.dropped") == []
    assert len(stand.statements()) == 1


# --- номер абзаца строкой ----------------------------------------------------------------


@pytest.mark.parametrize("raw", ["1", " 1", "1 ", "  1  ", "01", "\t1\n"])
@req(EO, CHECK, invariant="paragraph строкой из цифр (с пробелами по краям) — то же число")
def test_paragraph_digit_string(stand, events, raw):
    _vid, ids = external(stand, [stmt("Кант", "holds", "Опыт", raw, Q1)])
    [s] = stand.statements()
    assert [e["paragraph_id"] for e in s["evidence"]] == [ids[0]]
    assert events.of("knowledge.extraction.dropped") == []


# --- позиция, типы, связь ----------------------------------------------------------------


@pytest.mark.parametrize("stance", ["asserts", "disputes", "mentions"])
@req(EO, CHECK, invariant="Допустимые позиции asserts, disputes, mentions принимаются")
def test_valid_stances_accepted(stand, events, stance):
    external(stand, [stmt("Кант", "holds", "Опыт", 1, Q1, stance=stance)])
    [s] = stand.statements()
    assert [a["stance"] for a in s["attributions"] if a["who_kind"] == "source"] == [stance]
    assert events.of("knowledge.extraction.dropped") == []


@req(EO, CHECK, invariant="Код связи вне реестра — предложение нового типа и «испытал влияние»")
@pytest.mark.parametrize("code", ["rejects", "x_made_up", "ПРИДУМАННАЯ", "a b", "holds2"])
def test_unknown_relation_becomes_proposal(stand, events, code):
    external(stand, [stmt("Локк", code, "Гоббс", 3, Q3, object_type="person")])
    [s] = stand.statements()
    assert s["type"] == "influenced_by"
    assert [p["payload"]["code"] for p in stand.onto.registry.proposals()] == [code]
    assert events.of("knowledge.extraction.dropped") == []
    assert [e.fields["code"] for e in events.of("knowledge.registry.proposal")] == [code]


@req(
    EO,
    CHECK,
    invariant="Код реестра, не допустимый для извлечения: relation_not_allowed, без предложения",
)
def test_relation_not_allowed_no_proposal(stand, events):
    assert "lifespan" not in set(stand.filling.registry_schema()["x-relations"])
    stand.onto.registry.relation("lifespan")  # код есть в реестре
    external(stand, [stmt("Кант", "lifespan", "Опыт", 1, Q1)])
    assert dropped_codes(events) == ["relation_not_allowed"]
    assert stand.onto.registry.proposals() == []
    assert stand.statements() == []


@req(
    EO,
    CHECK,
    invariant="В онтологию попадают только типы связей и сущностей реестра, при любом ответе",
)
@given(
    hst.lists(
        hst.tuples(
            hst.sampled_from(
                ["holds", "rejects", "lifespan", "zzz", "", "influenced_by", "dating"]
            ),
            hst.sampled_from(["person", "position", "character", "work", "", "source", None, "x"]),
            hst.sampled_from(["person", "position", "animal", None, "concept", "event"]),
            hst.sampled_from([Q1, "нет такой", "", Q1.upper()]),
        ),
        min_size=1,
        max_size=6,
    ),
    hst.lists(
        hst.tuples(
            hst.sampled_from(["Платон", "Зевс", "Сократ"]),
            hst.sampled_from(["person", "character", "god", "", "work"]),
        ),
        max_size=3,
    ),
)
@settings(
    parent=PROFILES["heavy"],
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
def test_only_registry_types_stored(stand, events, items, ents):
    stand.reset()
    events.clear()
    statements = [
        stmt(f"Субъект{i}", r, f"Объект{i}", 1, q, subject_type=s, object_type=o)
        for i, (r, s, o, q) in enumerate(items)
    ]
    entities = [{"name": n, "type": ty} for n, ty in ents]
    external(stand, statements, entities=entities)
    registry = stand.onto.registry
    known_entity = set(registry.entity_types())
    for s in stand.statements():
        assert registry.relation(s["type"])  # не бросает: тип есть в реестре
        assert not registry.relation(s["type"]).get("deprecated_by")
    with stand.onto.statements.engine.begin() as conn:
        entity_types = set(conn.scalars(select(t.entities.c.type)))
    assert entity_types <= known_entity
    check_run_accounting(stand, events)
    for c in dropped_codes(events):
        assert c in codes.CODES


# --- property: отказ элемента не отменяет остальных -------------------------------------

FAULTS = [
    (lambda i: mutate(subject=f"Кант{i}", quote="нет в абзаце"), "quote_not_found"),
    (lambda i: mutate(subject=f"Кант{i}", paragraph=77), "paragraph_out_of_window"),
    (lambda i: mutate(subject=f"Кант{i}", stance="x"), "stance_invalid"),
    (lambda i: mutate(subject=f"Кант{i}", subject_type="character"), "entity_type"),
    (lambda i: mutate(subject=f"Кант{i}", type="lifespan"), "relation_not_allowed"),
    (lambda i: mutate(subject=f"Кант{i}", quote=7), "schema_item"),
    (lambda i: "не объект", "schema_item"),
    (lambda i: mutate(subject=f"Кант{i}", paragraph=None), "schema_item"),
]

PARAGRAPHS = [
    f"Мыслитель номер {n} утверждал тезис {n} и спорил с оппонентом {n}." for n in range(8)
]


@req(EO, CHECK, invariant="Отказ одного элемента не отменяет запись остальных элементов ответа")
@given(
    hst.lists(
        hst.one_of(hst.just("good"), hst.integers(0, len(FAULTS) - 1)), min_size=1, max_size=10
    )
)
@settings(
    parent=PROFILES["heavy"],
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
def test_bad_item_does_not_reject_the_rest_property(stand, events, plan):
    stand.reset()
    events.clear()
    statements, expected_codes, good = [], [], 0
    for i, step in enumerate(plan):
        if step == "good":
            n = good % 8
            statements.append(
                stmt(f"Мыслитель{i}", "holds", f"Тезис{i}", n + 1, f"утверждал тезис {n}")
            )
            good += 1
        else:
            make, code = FAULTS[step]
            statements.append(make(i))
            expected_codes.append(code)
    vid, _ = stand.version(PARAGRAPHS)
    stand.filling.fragment_size = 8
    ingest(stand, vid, {"1": {"statements": statements}})
    assert len(stand.statements()) == good
    assert Counter(dropped_codes(events)) == Counter(expected_codes)
    row = check_run_accounting(stand, events)
    assert (row["created"], row["dropped"]) == (good, len(expected_codes))
    [fragment] = events.of(FRAGMENT)
    assert (fragment["created"], fragment["dropped"]) == (good, len(expected_codes))
    assert_event_keys(events)
    # ни одной сущности из отброшенных утверждений
    assert stand.entities_of("person") == good


# --- коды причин ------------------------------------------------------------------------


@req(EO, CODE, scenario="Сводка причин в запуске")
def test_drop_reasons_summary(stand, events):
    vid, _ = stand.version(TEXTS[:2])
    stand.filling.fragment_size = 2
    stand.model.replies.append(
        {
            "statements": [
                stmt("Кант", "holds", "Опыт", 1, "цитата не из абзаца вовсе"),
                stmt("Юм", "holds", "Привычка", 9, Q2),
            ]
        }
    )
    stand.filling.extract_version(vid)
    row = one_run(stand)
    assert row["drop_reasons"] == {"quote_not_found": 1, "paragraph_out_of_window": 1}
    assert row["dropped"] == 2
    assert sorted(dropped_codes(events)) == ["paragraph_out_of_window", "quote_not_found"]
    assert all(e["run_id"] == row["run_id"] for e in events.of("knowledge.extraction.dropped"))


@req(
    EO,
    CODE,
    invariant="Событие отбраковки: run_id, reason до 300 знаков и code; без названий и цитат",
)
def test_event_fields_and_no_leak(stand, events):
    secret_name = "СекретноеИмяСубъекта"
    secret_quote = "СекретнаяЦитатаКоторойНет"
    external(
        stand,
        [
            stmt(secret_name, "holds", "Объект", 1, secret_quote),
            stmt("Кант", "holds", "Опыт", 99, "Кант писал " * 80),
        ],
    )
    assert_event_keys(events)
    for e in events.of("knowledge.extraction.dropped"):
        assert secret_name not in json.dumps(e.fields, ensure_ascii=False)
        assert secret_quote not in json.dumps(e.fields, ensure_ascii=False)
        assert "Кант писал Кант писал" not in e["reason"]


@req(
    EO,
    CODE,
    invariant="Сводка drop_reasons совпадает с числом событий по кодам, dropped — их сумма",
)
@given(
    hst.lists(hst.integers(0, len(FAULTS) - 1), min_size=0, max_size=8),
    hst.lists(hst.integers(0, len(FAULTS) - 1), min_size=0, max_size=8),
)
@settings(
    parent=PROFILES["heavy"],
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
def test_summary_matches_events_over_fragments(stand, events, first, second):
    stand.reset()
    events.clear()
    stand.filling.fragment_size = 2
    vid, _ = stand.version(PARAGRAPHS[:4])  # фрагменты [1,2], [2,3], [3,4]
    replies = {
        "1": {"statements": [FAULTS[i][0](i) for i in first]},
        "2": {"statements": [FAULTS[i][0](i + 50) for i in second]},
        # фрагмента 3 ответ отсутствует, ответ на 9 — вне задания
        "9": {"statements": []},
    }
    ingest(stand, vid, replies)
    row = check_run_accounting(stand, events)
    expected = Counter(FAULTS[i][1] for i in [*first, *second])
    expected["reply_missing"] += 1
    expected["reply_invalid"] += 1
    assert row["drop_reasons"] == dict(expected)
    assert row["dropped"] == sum(expected.values())


@req(
    EO,
    CODE,
    invariant="code всегда из перечня; reason прежних кодов (entity:*, dating:*) не меняется",
)
def test_codes_closed_list_and_old_reasons_kept(stand, events):
    vid, _ = stand.version(["Иммануил Кант (1724–1804) родился в Кёнигсберге."])
    reply = {
        "statements": [
            stmt("Кант", "holds", "Опыт", 1, "Иммануил Кант", subject_type="character"),
            stmt("123", "holds", "Опыт", 1, "Иммануил Кант"),
        ],
        "entities": [
            {
                "name": "Кант",
                "type": "person",
                "dating": {"text": "1724–1804", "paragraph": 1, "quote": "нет такой цитаты"},
            },
        ],
    }
    ingest(stand, vid, {"1": reply})
    for e in events.of("knowledge.extraction.dropped"):
        assert e["code"] in codes.CODES
    pairs = {(e["reason"], e["code"]) for e in events.of("knowledge.extraction.dropped")}
    assert ("entity:type", "entity_type") in pairs
    assert any(r.startswith("entity:") and c == "entity_invalid" for r, c in pairs)
    assert any(r.startswith("dating:") and c == "dating_quote" for r, c in pairs)


EXPECTED_CODES = {
    "reply_invalid",
    "reply_missing",
    "schema_item",
    "stance_invalid",
    "relation_not_allowed",
    "paragraph_out_of_window",
    "quote_not_found",
    "quote_too_short",
    "type_mismatch",
    "qualifier_invalid",
    "statement_refused",
    "entity_type",
    "entity_no_type",
    "entity_ambiguous",
    "entity_invalid",
    "dating_paragraph",
    "dating_quote",
    "dating_unparsed",
    "dating_not_in_quote",
    "dating_era",
    "dating_single_year",
    "dating_type",
    "dating_unresolved",
    "model_timeout",
    "model_schema",
    "model_unavailable",
    "model_budget",
    "model_refused",
}


@req(EO, CODE, invariant="Перечень кодов закрыт и совпадает с таблицей требования")
def test_code_list_equals_spec_table():
    assert set(codes.CODES) == EXPECTED_CODES


@req(EO, CODE, invariant="Коды dating_* — по отказам датировки из entity-dating")
@pytest.mark.parametrize(
    ("dating", "code"),
    [
        ({"text": "1724–1804", "paragraph": 9, "quote": "Кант (1724–1804)"}, "dating_paragraph"),
        ({"text": "1724–1804", "paragraph": 1, "quote": "Не из абзаца 1724–1804"}, "dating_quote"),
        ({"text": "когда-то", "paragraph": 1, "quote": "Кант (1724–1804)"}, "dating_unparsed"),
        ({"text": "1724–1805", "paragraph": 1, "quote": "Кант (1724–1804)"}, "dating_not_in_quote"),
        ({"text": "1724–1804 до н. э.", "paragraph": 1, "quote": "Кант (1724–1804)"}, "dating_era"),
        ({"text": "1724", "paragraph": 1, "quote": "Кант (1724–1804)"}, "dating_single_year"),
    ],
)
def test_dating_codes(stand, events, dating, code):
    vid, _ = stand.version(["Иммануил Кант (1724–1804) родился в Кёнигсберге."])
    ingest(
        stand,
        vid,
        {
            "1": {
                "statements": [],
                "entities": [{"name": "Кант", "type": "person", "dating": dating}],
            }
        },
    )
    assert dropped_codes(events) == [code]
    check_run_accounting(stand, events)
    assert_event_keys(events)


@req(EO, CODE, invariant="statement_refused — иной отказ записи утверждения")
def test_statement_refused_code(stand, events, monkeypatch):
    """Иной отказ записи (не тип, не уточнитель): код statement_refused; остальные пишутся."""
    from philograph.knowledge.statements import StatementError, Statements

    real = Statements.add

    def refusing(self, subject, type_, **kwargs):
        if self.entities.label(subject) == "Юм":
            raise StatementError("запись отклонена по иной причине")
        return real(self, subject, type_, **kwargs)

    monkeypatch.setattr(Statements, "add", refusing)
    external(
        stand,
        [stmt("Юм", "holds", "Привычка", 2, Q2), stmt("Кант", "holds", "Опыт", 1, Q1)],
    )
    assert dropped_codes(events) == ["statement_refused"]
    assert len(stand.statements()) == 1
    assert check_run_accounting(stand, events)["drop_reasons"] == {"statement_refused": 1}


@req(EO, CODE, invariant="entity_ambiguous — неоднозначная привязка, сущность не создаётся молча")
def test_entity_ambiguous_code(stand, events):
    stand.onto.person("Иоанн")
    stand.onto.person("Иоанн")
    before = stand.entities_of("person")
    external(stand, [stmt("Иоанн", "holds", "Опыт", 1, Q1)])
    assert dropped_codes(events) == ["entity_ambiguous"]
    assert stand.entities_of("person") == before
    assert stand.statements() == []
    check_run_accounting(stand, events)


@req(
    EO,
    CODE,
    invariant="reason события — до 300 знаков, даже если причина содержит длинный текст модели",
)
def test_reason_is_cut_to_300(stand, events):
    external(stand, [stmt("Кант", "holds", "Опыт", 1, Q1, qualifiers={"к" * 1000: 1})])
    [event] = events.of("knowledge.extraction.dropped")
    assert event["code"] == "qualifier_invalid"
    assert len(event["reason"]) == 300
