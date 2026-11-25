"""person-quality (improve-person-quality): «Качество персон» и «Слияние вариантов персоны».

По дельте ``openspec/changes/improve-person-quality/specs/person-quality``. Извлечение —
стенд ``extraction_stand`` (фейк шлюза, поддельная библиотека, сеть запрещена). «Запуск
слияния вариантов» — ``Dedupe(statements, review).run``; команда QID — ``LifeDates`` с
записями Wikidata из теста. Вывод — база, ``GET /v1/entities/{id}``, очередь проверки
``duplicate``; журнал — ``knowledge.entity.*``. Property-тесты: ``not_persons`` и
``persons_with_variants`` (стратегии не импортируют ``dedupe``).
"""

from __future__ import annotations

import random

import pytest
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as hst
from sqlalchemy import select

from philograph.knowledge import dedupe, naming
from philograph.knowledge import schema as t
from philograph.knowledge.app import build_app
from philograph.knowledge.dates import lifespan, span
from philograph.knowledge.dedupe import Dedupe, Entity, plan
from philograph.knowledge.life_dates import LifeDates
from philograph.knowledge.naming import normalize
from philograph.knowledge.review import Review
from philograph.knowledge.statements import Attribution
from philograph.operator.access import ActionLog

from ..conftest import PROFILES
from .extraction_stand import Stand
from .strategies import (
    PERSON,
    assert_dropped_codes,
    expected_kept,
    expected_label,
    name_of,
    names_with_reason,
    not_persons,
    persons_with_variants,
    sentinel,
)
from .wd_records import RecordFetch, no_network, record  # noqa: F401

req = pytest.mark.req
PQ = "person-quality"
QUALITY = "Качество персон"
MERGE = "Слияние вариантов персоны"
CTX = {"request_id", "run_id", "service"}
REJECTED = "knowledge.entity.rejected"
CREATED = "knowledge.entity.created"
MERGED = "knowledge.entity.merged"
PROPOSED = "knowledge.entity.merge_proposed"
DROPPED = "knowledge.extraction.dropped"
CI = settings(parent=PROFILES["ci"], suppress_health_check=[HealthCheck.function_scoped_fixture])
HEAVY = settings(
    parent=PROFILES["heavy"], suppress_health_check=[HealthCheck.function_scoped_fixture]
)


def fields(event) -> dict:
    return {k: v for k, v in event.fields.items() if k not in CTX}


def stm(subject, type_, obj, paragraph, quote, **extra):
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


def persons(onto) -> list[str]:
    """Действующие персоны (без перенаправлений)."""
    with onto.statements.engine.begin() as conn:
        rows = conn.execute(
            select(t.entities.c.id).where(
                t.entities.c.type == PERSON, t.entities.c.redirect_to.is_(None)
            )
        )
        return sorted(r[0] for r in rows)


def no_token(events, token: str, allowed=frozenset()) -> None:
    for event in events.items:
        for key, value in event.fields.items():
            if (event.name, key) not in allowed:
                assert token not in repr(value), (event.name, key)


@pytest.fixture
def stand(onto, engine_for, clock) -> Stand:
    return Stand(onto, engine_for, clock)


@pytest.fixture
def review(onto, clock) -> Review:
    return Review(onto.statements, ActionLog(onto.statements.engine, clock))


def queue_pairs(review) -> dict[frozenset, dict]:
    return {frozenset(i["payload"]["pair"]): i for i in review.queue(kind="duplicate")}


def decide_apart(onto, review, a: str, b: str) -> None:
    """Человек закрыл пункт ``duplicate`` по паре решением «разные»."""
    dedupe.propose(onto.statements.engine, a, b, "review:variant", set())
    [item] = [i for i in review.queue(kind="duplicate") if set(i["payload"]["pair"]) == {a, b}]
    review.resolve_duplicate(item["item_id"], False, "operator")


def api(onto) -> TestClient:
    return TestClient(build_app(onto.statements))


# =========================== Качество персон ==============================================


@req(PQ, QUALITY, scenario="Мусорная персона")
def test_garbage_person(stand, onto, events):
    token = sentinel()
    stand.extract(
        [f"Об этом знают и children. {token}"],
        {"statements": [stm("children", "holds", "Опыт", 1, "Об этом знают и children")]},
    )
    assert persons(onto) == []
    assert [fields(e) for e in events.of(REJECTED)] == [
        {"type": "person", "label": "children", "reason": "not_a_name"}
    ]
    assert [d["reason"] for d in events.of(DROPPED)] == ["entity:not_a_name"]  # О17: код
    assert stand.statements() == []
    no_token(events, token)
    assert_dropped_codes(events)


@req(PQ, QUALITY, scenario="Склейка")
def test_glued(stand, onto, events):
    stand.extract(
        ["Kepler and Des Cartes изучали свет."],
        {"statements": [stm("Kepler and Des Cartes", "holds", "Оптика", 1, "изучали свет")]},
    )
    assert persons(onto) == []
    [rejected] = events.of(REJECTED)
    assert (rejected["type"], rejected["reason"]) == ("person", "not_a_name")
    assert [d["reason"] for d in events.of(DROPPED)] == ["entity:not_a_name"]


@req(PQ, QUALITY, scenario="Определение персоны в промпте")
def test_person_definition_in_prompt(stand, events):
    stand.extract(["Кант писал о разуме."], {"statements": []})
    [request] = stand.model.calls
    system = request.messages[0].content
    assert "person" in system and "Персона" in system
    for negative in ("your Lordship", "blind mathematician", "children"):
        assert negative in system, negative
    [body] = stand.llm_transport.bodies
    assert body["template"] == "ontology.extract"
    assert events.one("knowledge.extraction.fragment")["run_id"]


def _person_cases():
    return names_with_reason().filter(lambda c: c[0][0] == PERSON) | not_persons()


@req(PQ, QUALITY, scenario="Инвариант качества персон")
@req(PQ, QUALITY, invariant="Персона запуска создаётся тогда и только тогда, когда название годно")
@CI
@given(_person_cases())
@example(((PERSON, "your Lordship"), "not_a_name"))
@example(((PERSON, "   "), "empty"))
@example(((PERSON, ""), "empty"))
@example(((PERSON, "Your Lordship"), "stopword"))
@example(((PERSON, "blind mathematician"), "not_a_name"))
@example(((PERSON, "Children"), "stopword"))
@example(((PERSON, "Kepler and Des Cartes"), "not_a_name"))
@example(((PERSON, "The author of the Treatise"), "not_a_name"))
@example(((PERSON, "аль-Фараби"), None))
@example(((PERSON, "Людовик XIV"), None))
@example(((PERSON, "Один Два Три Четыре Пять Шесть Семь"), "sentence"))
def test_person_quality_invariant(stand, onto, events, case):
    (_type, raw), reason = case
    raw = raw.strip()  # краевые пробелы — дефект Д2 improve-extraction-naming, отдельный тест
    stand.reset()
    events.clear()
    token = sentinel()
    stand.extract(
        [f"Фрагмент про {raw}. {token}"],
        {"statements": [stm(raw, "holds", "Опыт", 1, "Фрагмент про")]},
    )
    created = events.where(CREATED, type=PERSON)
    assert len(persons(onto)) == len(created)
    if reason is None:
        assert len(created) == 1
        [entity] = persons(onto)
        assert onto.entities.label(entity) == raw
        events.assert_none(REJECTED)
    else:
        assert created == []
        [rejected] = events.of(REJECTED)
        assert fields(rejected) == {"type": PERSON, "label": expected_label(raw), "reason": reason}
        assert [d["reason"] for d in events.of(DROPPED)] == [f"entity:{reason}"]  # О17
    no_token(events, token)
    assert_dropped_codes(events)


@req(PQ, QUALITY, invariant="Правило названий персон — чистая функция: ожидаемая причина")
@settings(parent=PROFILES["pure"])
@given(_person_cases())
@example(((PERSON, "your Lordship"), "not_a_name"))
@example(((PERSON, "Kepler and Des Cartes"), "not_a_name"))
@example(((PERSON, "Children"), "stopword"))
@example(((PERSON, "Logicians"), "stopword"))
@example(((PERSON, "Иоганн Вольфганг фон Гёте"), None))
def test_person_rule_any_input(case):
    (_type, raw), reason = case
    assert naming.check_name(PERSON, name_of(raw)) == reason


# =========================== Слияние вариантов персоны ====================================


@req(PQ, MERGE, scenario="Слияние вариантов")
def test_variants_merge_by_model_pair(stand, onto, events):
    locke = onto.entities.create(
        "person", [("en", "Locke", "primary")], external={"wikidata": "Q9353"}
    )
    essay = onto.thing("work", "An Essay Concerning Human Understanding")
    authored = onto.statements.add(essay, "author", obj=locke, attributions=[Attribution("common")])
    lokk = onto.person("Локк")
    member = onto.statements.add(
        lokk, "member_of", obj=onto.thing("group", "Эмпиризм"), attributions=[Attribution("common")]
    )
    events.clear()
    stand.extract(
        ["Локк сравнивал ум с чистой доской."],
        {
            "statements": [stm("Локк", "holds", "Чистая доска", 1, "Локк сравнивал ум")],
            "entities": [{"name": "Локк", "type": "person", "ru": "Локк", "en": "Locke"}],
        },
    )
    assert persons(onto) == [locke]
    assert names(onto, locke) == {("ru", "Локк", "primary"), ("en", "Locke", "variant")}
    assert onto.entities.externals("wikidata") == {locke: "Q9353"}
    assert onto.statements.get(authored)["object"] == locke
    assert onto.statements.get(member)["subject"] == locke
    response = api(onto).get(f"/v1/entities/{lokk}")
    assert response.status_code == 200 and response.json()["id"] == locke
    [merged] = events.of(MERGED)
    assert (merged["kept"], merged["removed"], merged["reason"], merged["statements"]) == (
        locke,
        lokk,
        "merge:model_pair",
        1,
    )


@req(PQ, MERGE, scenario="Общее основное название")
def test_common_primary_name(onto, review, events):
    ids = [onto.entities.create("person", [("en", "Berkeley", "primary")]) for _ in range(3)]
    opinions = [
        onto.statements.add(
            i,
            "holds",
            obj=onto.thing("position", f"Позиция {n}"),
            attributions=[Attribution("common")],
        )
        for n, i in enumerate(ids)
    ]
    events.clear()
    Dedupe(onto.statements, review).run()
    [kept] = persons(onto)
    assert {onto.statements.get(s)["subject"] for s in opinions} == {kept}
    assert [n for n in names(onto, kept) if n[2] == "primary"] == [("en", "Berkeley", "primary")]
    assert [e["reason"] for e in events.of(MERGED)] == ["merge:name"] * 2


@req(PQ, MERGE, scenario="Слияние по решению человека")
def test_merge_by_human_decision(onto, review, events):
    first = onto.person("Бэкон")
    second = onto.person("Фрэнсис Бэкон")
    held = onto.statements.add(
        second,
        "holds",
        obj=onto.thing("position", "Знание — сила"),
        attributions=[Attribution("common")],
    )
    dedupe.propose(onto.statements.engine, first, second, "review:single_name", set())
    [item] = review.queue(kind="duplicate")
    a, b = item["payload"]["pair"]
    label = {first: "Бэкон", second: "Фрэнсис Бэкон"}
    events.clear()
    review.resolve_duplicate(item["item_id"], True, "operator")
    assert persons(onto) == [a]
    assert onto.entities.resolve(b) == a
    assert names(onto, a) == {("ru", label[a], "primary"), ("ru", label[b], "variant")}
    assert onto.statements.get(held)["subject"] == a
    assert api(onto).get(f"/v1/entities/{b}").json()["id"] == a
    assert review.queue(kind="duplicate") == []
    [merged] = events.of(MERGED)
    assert (merged["kept"], merged["removed"], merged["reason"]) == (a, b, "merge:review")
    decided = events.one("knowledge.review.decided")
    assert decided["decision"] == "merge"


@req(PQ, MERGE, scenario="QID подтверждён человеком для другой")
def test_qid_confirmed_for_other(onto, review, events):
    hume = onto.entities.create(
        "person", [("en", "Hume", "primary")], external={"wikidata": "Q41568"}
    )
    yum = onto.person("Юм")
    events.clear()
    Dedupe(onto.statements, review).run(confirmed=[(yum, hume)])
    [kept] = persons(onto)
    assert kept == hume
    assert names(onto, kept) == {("ru", "Юм", "primary"), ("en", "Hume", "variant")}
    assert onto.entities.externals("wikidata") == {hume: "Q41568"}
    [merged] = events.of(MERGED)
    assert merged["reason"] == "merge:qid_confirmed"


HOMER = record("Q6691", ru="Гомер", en="Homer", classes=("Q5",))


@req(PQ, MERGE, scenario="Транслитерация")
def test_transliteration_with_decision(onto, review, events, no_network):
    homer = onto.entities.create(
        "person", [("ru", "Гомер", "primary")], external={"wikidata": "Q6691"}
    )
    iliad = onto.statements.add(
        onto.thing("work", "Илиада"), "author", obj=homer, attributions=[Attribution("common")]
    )
    omir = onto.person("Омир")
    plato = onto.person("Платон")
    mentioned = onto.statements.add(
        plato, "criticizes", obj=omir, attributions=[Attribution("common")]
    )
    events.clear()
    manifest = {
        "entities": [
            {"entity": omir, "wikidata": "Q6691", "decision": "accepted", "candidates": []}
        ]
    }
    LifeDates(onto.statements, RecordFetch({"Q6691": HOMER}), review).apply(manifest)
    Dedupe(onto.statements, review).run(confirmed=[(omir, homer)])
    assert set(persons(onto)) == {homer, plato}
    assert names(onto, homer) == {("ru", "Гомер", "primary"), ("ru", "Омир", "variant")}
    assert onto.entities.externals("wikidata") == {homer: "Q6691"}
    assert onto.statements.get(iliad)["object"] == homer
    assert onto.statements.get(mentioned)["object"] == homer
    assert api(onto).get(f"/v1/entities/{omir}").json()["id"] == homer
    assert events.where("knowledge.life_dates.skipped", reason="qid_taken")
    assert [e["reason"] for e in events.of(MERGED)] == ["merge:qid_confirmed"]


@req(PQ, MERGE, scenario="Транслитерация без решения человека")
def test_transliteration_pending(onto, review, events, no_network):
    homer = onto.entities.create(
        "person", [("ru", "Гомер", "primary")], external={"wikidata": "Q6691"}
    )
    omir = onto.person("Омир")
    fetch = RecordFetch({"Q6691": HOMER}, searches={("Омир", "ru"): [{"id": "Q6691"}]})
    events.clear()
    manifest = LifeDates(onto.statements, fetch, review).suggest({"entities": []})
    [entry] = [e for e in manifest["entities"] if e["entity"] == omir]
    assert entry["decision"] == "pending"
    Dedupe(onto.statements, review).run()
    assert set(persons(onto)) == {homer, omir}
    assert frozenset({homer, omir}) in queue_pairs(review)
    assert [e["reason"] for e in events.of(PROPOSED)] == ["review:qid_candidate"]
    events.assert_none(MERGED)


@req(PQ, MERGE, scenario="Решение «разные» и третья запись")
def test_decided_apart_and_third(onto, review, events):
    a, b, c = (onto.person("Бэкон") for _ in range(3))
    decide_apart(onto, review, a, b)
    events.clear()
    Dedupe(onto.statements, review).run()
    assert set(persons(onto)) == {a, b, c}
    assert set(queue_pairs(review)) == {frozenset({a, c}), frozenset({b, c})}
    assert [e["reason"] for e in events.of(PROPOSED)] == ["review:decided_conflict"] * 2
    events.assert_none(MERGED)


@req(PQ, MERGE, scenario="Тёзки")
def test_namesakes(onto, review, events):
    roger = onto.entities.create(
        "person", [("ru", "Бэкон", "primary"), ("ru", "Роджер Бэкон", "variant")]
    )
    francis = onto.entities.create(
        "person", [("ru", "Бэкон", "primary"), ("ru", "Фрэнсис Бэкон", "variant")]
    )
    decide_apart(onto, review, roger, francis)
    events.clear()
    Dedupe(onto.statements, review).run()
    assert set(persons(onto)) == {roger, francis}
    assert queue_pairs(review) == {}
    events.assert_none(MERGED)
    events.assert_none(PROPOSED)


@req(PQ, MERGE, scenario="Разные QID")
def test_different_qids(onto, review, events):
    a = onto.person("Бэкон", wikidata="Q37388")
    b = onto.person("Бэкон", wikidata="Q192010")
    events.clear()
    Dedupe(onto.statements, review).run()
    assert set(persons(onto)) == {a, b}
    assert queue_pairs(review) == {}
    events.assert_none(MERGED)
    events.assert_none(PROPOSED)


@req(PQ, MERGE, scenario="Транзитивная компонента с двумя QID")
@pytest.mark.parametrize("order", [(0, 1, 2), (2, 0, 1), (1, 2, 0)])
def test_transitive_component_two_qids(onto, review, events, order):
    specs = [{"wikidata": "Q1"}, {}, {"wikidata": "Q2"}]
    ids = {}
    for i in order:
        ids[i] = onto.entities.create(
            "person", [("en", "Hume", "primary")], external=specs[i] or None
        )
    events.clear()
    Dedupe(onto.statements, review).run()
    assert set(persons(onto)) == set(ids.values())
    assert set(queue_pairs(review)) == {frozenset({ids[0], ids[1]}), frozenset({ids[1], ids[2]})}
    assert [e["reason"] for e in events.of(PROPOSED)] == ["review:qid_cluster"] * 2
    events.assert_none(MERGED)


@req(PQ, MERGE, scenario="Противоречащие даты")
def test_conflicting_dates(stand, onto, review, events):
    berkeley = onto.entities.create("person", [("en", "Berkeley", "primary")])
    onto.statements.add(
        berkeley,
        "lifespan",
        value=lifespan("1685", "1753").to_json(),
        attributions=[Attribution("common")],
    )
    berkli = onto.person("Беркли", "1885", "1953")
    events.clear()
    stand.extract(
        ["Беркли отрицал материю."],
        {
            "statements": [stm("Беркли", "holds", "Имматериализм", 1, "Беркли отрицал материю")],
            "entities": [{"name": "Беркли", "type": "person", "ru": "Беркли", "en": "Berkeley"}],
        },
    )
    assert set(persons(onto)) == {berkeley, berkli}
    assert frozenset({berkeley, berkli}) in queue_pairs(review)
    [proposed] = events.of(PROPOSED)
    assert fields(proposed)["reason"] == "review:dates"
    assert {proposed["kept"], proposed["removed"]} == {berkeley, berkli}
    events.assert_none(MERGED)


@req(PQ, MERGE, invariant="Компонента с review:dates через запись без дат не сливается")
def test_date_chain_component(onto, review, events):
    """«Berkeley» 1685–1753, «Berkeley» без дат, «Berkeley» 1885–1953: рёбра merge:name идут
    через среднюю, у крайних даты противоречат — компонента не сливается, все пары в очереди
    с причиной review:dates."""
    ids = []
    for dates in (("1685", "1753"), None, ("1885", "1953")):
        e = onto.entities.create("person", [("en", "Berkeley", "primary")])
        if dates:
            onto.statements.add(
                e,
                "lifespan",
                value=lifespan(*dates).to_json(),
                attributions=[Attribution("common")],
            )
        ids.append(e)
    events.clear()
    Dedupe(onto.statements, review).run()
    assert sorted(persons(onto)) == sorted(ids)
    events.assert_none(MERGED)
    assert set(queue_pairs(review)) == {
        frozenset(p) for p in ((ids[0], ids[1]), (ids[1], ids[2]), (ids[0], ids[2]))
    }
    proposed = events.of(PROPOSED)
    assert {frozenset((e["kept"], e["removed"])) for e in proposed} == set(queue_pairs(review))
    assert {e["reason"] for e in proposed} == {"review:dates"}


@req(PQ, MERGE, scenario="Даты у одной стороны")
def test_dates_on_one_side(onto, review, events):
    dated = onto.entities.create("person", [("en", "Berkeley", "primary")])
    onto.statements.add(
        dated,
        "lifespan",
        value=lifespan("1685", "1753").to_json(),
        attributions=[Attribution("common")],
    )
    bare = onto.entities.create("person", [("en", "Berkeley", "primary")])
    events.clear()
    Dedupe(onto.statements, review).run()
    [kept] = persons(onto)
    assert {onto.entities.resolve(dated), onto.entities.resolve(bare)} == {kept}
    assert span(onto.entities.get(kept)["primary"]["dates"]) == (1685, 1753)
    assert [e["reason"] for e in events.of(MERGED)] == ["merge:name"]


@req(PQ, MERGE, scenario="Совпал только вариант")
def test_only_variant_matched(onto, review, events):
    francis = onto.entities.create(
        "person", [("ru", "Фрэнсис Бэкон", "primary"), ("ru", "Бэкон", "variant")]
    )
    bacon = onto.person("Бэкон")
    reid = onto.entities.create(
        "person", [("en", "Thomas Reid", "primary"), ("ru", "Томас Рид", "variant")]
    )
    rid = onto.person("Томас Рид")
    events.clear()
    Dedupe(onto.statements, review).run()
    assert set(persons(onto)) == {francis, bacon, reid, rid}
    assert set(queue_pairs(review)) == {frozenset({francis, bacon}), frozenset({reid, rid})}
    reasons = {frozenset({e["kept"], e["removed"]}): e["reason"] for e in events.of(PROPOSED)}
    assert reasons == {
        frozenset({francis, bacon}): "review:single_name",
        frozenset({reid, rid}): "review:variant",
    }
    events.assert_none(MERGED)


# --- инвариант слияния -------------------------------------------------------------------


def _pure_entities(case) -> tuple[list[Entity], dict]:
    ids, out = {}, []
    for face in case["faces"]:
        for r in face["records"]:
            ids[r["key"]] = f"e_{r['key'][0]:02d}{r['key'][1]}"
            names_ = tuple((kind, normalize(text)) for _lang, text, kind in r["names"])
            dates = (
                lifespan(str(r["dates"][0]), str(r["dates"][1])).to_json() if r["dates"] else None
            )
            out.append(Entity(ids[r["key"]], r.get("type", PERSON), names_, dates, r["qid"]))
    return out, ids


def _expected(case, ids, links=None, model=True):
    """Ожидаемое разбиение (оставшаяся → удалённые), очередь и причины — из построения.
    ``model=False`` — пар модели нет (``Dedupe.run``): лицо ``model_pair`` без доказательства."""
    merges, queue = {}, {}
    for face in case["faces"]:
        if face.get("needs_model") and not model:
            continue
        for block in face["merge"]:
            recs = [r for r in face["records"] if r["key"] in block]
            kept = expected_kept(recs, ids, links)
            merges[kept] = (sorted(ids[k] for k in block if ids[k] != kept), face["reason"])
        for pair, reason in face["queue"].items():
            queue[frozenset(ids[k] for k in pair)] = reason
    return merges, queue


TRANSITIVE = {
    "faces": [
        {
            "kind": "two_qids",
            "records": [
                {"key": (0, 0), "names": [("en", "Hume", "primary")], "qid": "Q1", "dates": None},
                {"key": (0, 1), "names": [("en", "Hume", "primary")], "qid": None, "dates": None},
                {"key": (0, 2), "names": [("en", "Hume", "primary")], "qid": "Q2", "dates": None},
            ],
            "merge": [],
            "queue": {
                frozenset({(0, 0), (0, 1)}): "review:qid_cluster",
                frozenset({(0, 1), (0, 2)}): "review:qid_cluster",
            },
        }
    ],
    "confirmed": [],
    "decided": [],
}
DATE_CHAIN = {  # J1 судьи: review:dates через запись без дат запрещает всю компоненту
    "faces": [
        {
            "kind": "date_chain",
            "records": [
                {
                    "key": (0, 0),
                    "names": [("en", "Berkeley", "primary")],
                    "qid": None,
                    "dates": (1685, 1753),
                },
                {
                    "key": (0, 1),
                    "names": [("en", "Berkeley", "primary")],
                    "qid": None,
                    "dates": None,
                },
                {
                    "key": (0, 2),
                    "names": [("en", "Berkeley", "primary")],
                    "qid": None,
                    "dates": (1885, 1953),
                },
            ],
            "merge": [],
            "queue": {
                frozenset({(0, 0), (0, 1)}): "review:dates",
                frozenset({(0, 1), (0, 2)}): "review:dates",
                frozenset({(0, 0), (0, 2)}): "review:dates",
            },
        }
    ],
    "confirmed": [],
    "decided": [],
}
MODEL_PAIR = {  # шаг 7 и шаг 1: пары модели — слияние и apart:type
    "faces": [
        {
            "kind": "model_pair",
            "records": [
                {"key": (0, 0), "names": [("en", "Hume", "primary")], "qid": None, "dates": None},
                {"key": (0, 1), "names": [("ru", "Хьюм", "primary")], "qid": None, "dates": None},
            ],
            "merge": [[(0, 0), (0, 1)]],
            "reason": "merge:model_pair",
            "queue": {},
            "needs_model": True,
        },
        {
            "kind": "mixed_type",
            "records": [
                {
                    "key": (1, 0),
                    "names": [("en", "Substance", "primary")],
                    "qid": None,
                    "dates": None,
                },
                {
                    "key": (1, 1),
                    "names": [("en", "Substance", "primary")],
                    "qid": None,
                    "dates": None,
                },
                {
                    "key": (1, 2),
                    "names": [("en", "Substance", "primary")],
                    "qid": None,
                    "dates": None,
                    "type": "concept",
                },
            ],
            "merge": [[(1, 0), (1, 1)]],
            "reason": "merge:name",
            "queue": {},
        },
    ],
    "confirmed": [],
    "decided": [],
    "model": [((0, 0), (0, 1)), ((1, 0), (1, 2))],
}
REVIEW_INSIDE = {  # review:single_name внутри сливаемой компоненты — не в очередь
    "faces": [
        {
            "kind": "review_inside",
            "records": [
                {
                    "key": (0, 0),
                    "names": [("en", "Homer", "primary")],
                    "qid": "Q6691",
                    "dates": None,
                },
                {"key": (0, 1), "names": [("ru", "Омир", "primary")], "qid": None, "dates": None},
                {
                    "key": (0, 2),
                    "names": [("ru", "Гомерос", "primary"), ("ru", "Омир", "variant")],
                    "qid": None,
                    "dates": None,
                },
            ],
            "merge": [[(0, 0), (0, 1), (0, 2)]],
            "reason": "merge:qid_confirmed",
            "queue": {},
        }
    ],
    "confirmed": [((0, 1), (0, 0)), ((0, 2), (0, 0))],
    "decided": [],
}
BOUNDARY_DATES = {
    "faces": [
        {
            "kind": "plain",
            "records": [
                {
                    "key": (0, 0),
                    "names": [("en", "Berkeley", "primary")],
                    "qid": None,
                    "dates": (1685, 1753),
                },
                {
                    "key": (0, 1),
                    "names": [("en", "Berkeley", "primary")],
                    "qid": None,
                    "dates": (1689, 1757),
                },
            ],
            "merge": [[(0, 0), (0, 1)]],
            "reason": "merge:name",
            "queue": {},
        },
        {
            "kind": "dates",
            "records": [
                {
                    "key": (1, 0),
                    "names": [("ru", "Беркли", "primary")],
                    "qid": None,
                    "dates": (1685, 1753),
                },
                {
                    "key": (1, 1),
                    "names": [("ru", "Беркли", "primary")],
                    "qid": None,
                    "dates": (1690, 1758),
                },
            ],
            "merge": [],
            "queue": {frozenset({(1, 0), (1, 1)}): "review:dates"},
        },
    ],
    "confirmed": [],
    "decided": [],
}


@req(PQ, MERGE, invariant="Разбиение по правилу и не зависит от порядка входа, чистая функция")
@settings(parent=PROFILES["pure"])
@given(persons_with_variants(max_faces=5), hst.randoms())
@example(TRANSITIVE, random.Random(1))
@example(BOUNDARY_DATES, random.Random(2))
@example(DATE_CHAIN, random.Random(5))
@example(MODEL_PAIR, random.Random(7))
@example(REVIEW_INSIDE, random.Random(8))
def test_plan_partition_any_order(case, rnd):
    entities, ids = _pure_entities(case)
    confirmed = [(ids[a], ids[b]) for a, b in case["confirmed"]]
    distinct = [(ids[a], ids[b]) for a, b in case["decided"]]
    by_model = [(ids[a], ids[b]) for a, b in case.get("model", [])]
    merges, queue = _expected(case, ids)
    results = []
    for _ in range(2):
        order = list(entities)
        rnd.shuffle(order)
        result = plan(order, pairs_by_model=by_model, confirmed=confirmed, distinct=distinct)
        got = {kept: (sorted(removed), reason) for kept, removed, reason in result.merges}
        assert got == merges
        assert {frozenset((a, b)): r for a, b, r in result.review} == queue
        results.append((result.merges, result.review))
    assert results[0] == results[1]


def _create_case(onto, case, order) -> dict:
    ids = {}
    records = [r for face in case["faces"] for r in face["records"]]
    for r in [records[i] for i in order]:
        external = {"wikidata": r["qid"]} if r["qid"] else None
        ids[r["key"]] = onto.entities.create(
            r.get("type", PERSON), list(r["names"]), external=external
        )
        if r["dates"]:
            onto.statements.add(
                ids[r["key"]],
                "lifespan",
                value=lifespan(str(r["dates"][0]), str(r["dates"][1])).to_json(),
                attributions=[Attribution("common")],
            )
    return ids


def _outcome(onto, review, case, ids, events) -> tuple:
    """Итог в ключах записей: разбиение, оставшиеся с QID, очередь, события."""
    back = {v: k for k, v in ids.items()}
    blocks: dict[str, list] = {}
    for key, entity in ids.items():
        blocks.setdefault(onto.entities.resolve(entity), []).append(key)
    partition = sorted(sorted(b) for b in blocks.values())
    queue = {
        frozenset(back[x] for x in pair): i["payload"].get("reason")
        for pair, i in queue_pairs(review).items()
    }
    merged = sorted(e["reason"] for e in events.of(MERGED))
    proposed = sorted(e["reason"] for e in events.of(PROPOSED))
    return partition, queue, merged, proposed


@req(PQ, MERGE, scenario="Инвариант слияния")
@req(PQ, MERGE, invariant="Слиты ровно допустимые компоненты; разные QID никогда; одно основное")
@HEAVY
@given(persons_with_variants(), hst.randoms())
@example(TRANSITIVE, random.Random(3))
@example(BOUNDARY_DATES, random.Random(4))
@example(DATE_CHAIN, random.Random(6))
@example(MODEL_PAIR, random.Random(9))
@example(REVIEW_INSIDE, random.Random(10))
def test_merge_invariant_two_orders(stand, onto, review, events, case, rnd):
    outcomes = []
    for _ in range(2):
        stand.reset()
        n = sum(len(f["records"]) for f in case["faces"])
        order = list(range(n))
        rnd.shuffle(order)
        ids = _create_case(onto, case, order)
        for a, b in case["decided"]:
            decide_apart(onto, review, ids[a], ids[b])
        events.clear()
        links = {ids[r["key"]]: 1 for f in case["faces"] for r in f["records"] if r["dates"]}
        merges, queue = _expected(case, ids, links, model=False)  # Dedupe.run — без пар модели
        Dedupe(onto.statements, review).run(
            confirmed=[(ids[a], ids[b]) for a, b in case["confirmed"]]
        )
        # разбиение и оставшиеся
        for kept, (removed, _reason) in merges.items():
            assert onto.entities.resolve(kept) == kept
            assert {onto.entities.resolve(r) for r in removed} == {kept}
        merged_away = {r for removed, _ in merges.values() for r in removed}
        for entity in ids.values():
            if entity not in merged_away:
                assert onto.entities.resolve(entity) == entity
        # QID и основные названия
        externals = onto.entities.externals("wikidata")
        for entity in persons(onto):
            assert list(externals).count(entity) <= 1
            primaries = [n for n in onto.entities.get(entity)["names"] if n["kind"] == "primary"]
            if entity in merges:
                assert len(primaries) == 1
                block = [entity, *merges[entity][0]]
                had_ru = any(
                    lang == "ru"
                    for f in case["faces"]
                    for r in f["records"]
                    if ids[r["key"]] in block
                    for lang, _text, kind in r["names"]
                    if kind == "primary"
                )
                assert (primaries[0]["lang"] == "ru") == had_ru
            langs = [n["lang"] for n in primaries]
            assert len(langs) == len(set(langs))
        # события и очередь
        got_queue = {pair: i for pair, i in queue_pairs(review).items()}
        assert set(got_queue) == set(queue)
        proposed = {frozenset({e["kept"], e["removed"]}): e["reason"] for e in events.of(PROPOSED)}
        assert proposed == queue
        assert len(events.of(PROPOSED)) == len(queue)
        expected_merged = sorted(r for removed, r in merges.values() for _ in removed)
        assert sorted(e["reason"] for e in events.of(MERGED)) == expected_merged
        outcomes.append(_outcome(onto, review, case, ids, events))
    assert outcomes[0] == outcomes[1]


# --- аудит пунктов (О21): границы определений и компонент ------------------------------


def _bounds(es, ls, ee, le) -> dict:
    return {
        "earliest_start": es,
        "latest_start": ls,
        "earliest_end": ee,
        "latest_end": le,
        "precision": "year",
        "original": "",
    }


def _berkeley(id_: str, dates: dict | None, qid: str | None = None) -> Entity:
    return Entity(id_, "person", (("primary", "berkeley"),), dates, qid)


@req(PQ, MERGE, invariant="Даты противоречат, если не пересекаются интервалы начала или конца")
@pytest.mark.parametrize(
    ("other", "verdict"),
    [
        (_bounds(1685, 1685, 1800, 1800), "review:dates"),  # расходится только конец
        (_bounds(1750, 1750, 1753, 1753), "review:dates"),  # расходится только начало
        (_bounds(1690, 1690, 1753, 1753), "review:dates"),  # начало: 5 лет > 2 + 2
        (_bounds(1685, 1685, 1758, 1758), "review:dates"),  # конец: 5 лет > 2 + 2
        (_bounds(1689, 1689, 1753, 1753), "merge:name"),  # начало: 4 года — допуски касаются
        (_bounds(1685, 1685, 1757, 1757), "merge:name"),  # конец: 4 года — допуски касаются
        (_bounds(1680, 1685, 1750, 1753), "merge:name"),  # интервалы неопределённости пересекаются
        (_bounds(1690, 1692, 1757, 1760), "review:dates"),  # начало врозь при близком конце
    ],
)
def test_dates_conflict_on_start_or_end_interval(other, verdict):
    base = _bounds(1685, 1685, 1753, 1753)
    assert dedupe.same_person(_berkeley("a", base), _berkeley("b", other)).reason == verdict
    assert dedupe.same_person(_berkeley("b", other), _berkeley("a", base)).reason == verdict


@req(PQ, MERGE, invariant="Решённая пара не ставится в очередь и после слияния компонент")
def test_decided_pair_not_requeued_after_merge_mapping():
    """Y слит в Z (одно основное); пара X–Y — review:single_name, но X и Z решением «разные»:
    после отображения Y → Z пара совпадает с решённой и в очередь не идёт."""
    z = Entity("e1", "person", (("primary", "zeta"),), None, None)
    y = Entity("e2", "person", (("primary", "zeta"),), None, None)
    x = Entity("e3", "person", (("primary", "xi"), ("variant", "zeta")), None, None)
    result = plan([z, y, x], distinct=[("e1", "e3")])
    assert result.merges == [("e1", ["e2"], "merge:name")]
    assert result.review == []


@req(PQ, MERGE, invariant="Причина отказа компоненты: qid_cluster раньше review:dates")
def test_component_reason_priority_qid_cluster_over_dates():
    a = Entity("a", "person", (("primary", "same"),), _bounds(1685, 1685, 1753, 1753), "Q1")
    b = Entity("b", "person", (("primary", "same"),), _bounds(1885, 1885, 1953, 1953), None)
    c = Entity("c", "person", (("primary", "same"),), None, "Q2")
    d = Entity("d", "person", (("primary", "same"),), None, None)
    result = plan([a, b, c, d])
    assert result.merges == []
    assert result.review == [
        ("a", "b", "review:dates"),  # собственный вердикт пары: противоречащие даты
        ("a", "d", "review:qid_cluster"),
        ("b", "c", "review:qid_cluster"),
        ("b", "d", "review:qid_cluster"),
        ("c", "d", "review:qid_cluster"),
    ]


@req(PQ, MERGE, invariant="В слиянии участвуют только действующие персоны")
def test_redirected_person_not_loaded(onto):
    kept = onto.entities.create("person", [("en", "Berkeley", "primary")])
    removed = onto.entities.create("person", [("en", "Berkeley", "primary")])
    onto.entities.merge(kept, removed)
    assert [p.id for p in dedupe.load_persons(onto.statements.engine)] == [kept]


@req(PQ, MERGE, invariant="Ссылки на сущность: субъект и объект утверждений плюс атрибуция-автор")
def test_link_counts_subject_object_author(onto):
    p1 = onto.entities.create("person", [("en", "Alpha", "primary")])
    p2 = onto.entities.create("person", [("en", "Beta", "primary")])
    p3 = onto.entities.create("person", [("en", "Gamma", "primary")])
    work = onto.thing("work", "Трактат")
    onto.statements.add(p1, "influenced_by", obj=p2)  # p1 — субъект, p2 — объект
    onto.statements.add(p3, "influenced_by", obj=p1)  # p1 — объект
    onto.statements.add(work, "author", obj=p3, attributions=[Attribution("entity", p1)])
    counts = dedupe.link_counts(onto.statements.engine, [p1, p2, p3])
    assert counts == {p1: 3, p2: 1, p3: 2}
