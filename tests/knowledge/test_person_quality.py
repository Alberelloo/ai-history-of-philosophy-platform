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

from philograph.knowledge import dedupe
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
    expected_kept,
    expected_label,
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
    assert events.of(DROPPED)
    assert stand.statements() == []
    no_token(events, token)


@req(PQ, QUALITY, scenario="Склейка")
def test_glued(stand, onto, events):
    stand.extract(
        ["Kepler and Des Cartes изучали свет."],
        {"statements": [stm("Kepler and Des Cartes", "holds", "Оптика", 1, "изучали свет")]},
    )
    assert persons(onto) == []
    [rejected] = events.of(REJECTED)
    assert (rejected["type"], rejected["reason"]) == ("person", "not_a_name")


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
    return names_with_reason().filter(
        lambda c: c[0][0] == PERSON and c[1] not in ("empty",)
    ) | not_persons().filter(lambda c: c[1] != "empty")


@req(PQ, QUALITY, scenario="Инвариант качества персон")
@req(PQ, QUALITY, invariant="Персона запуска создаётся тогда и только тогда, когда название годно")
@CI
@given(_person_cases())
@example(((PERSON, "your Lordship"), "not_a_name"))
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
        assert events.of(DROPPED)
    no_token(events, token)


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
            out.append(Entity(ids[r["key"]], PERSON, names_, dates, r["qid"]))
    return out, ids


def _expected(case, ids, links=None):
    """Ожидаемое разбиение (оставшаяся → удалённые), очередь и причины — из построения."""
    merges, queue = {}, {}
    for face in case["faces"]:
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
def test_plan_partition_any_order(case, rnd):
    entities, ids = _pure_entities(case)
    confirmed = [(ids[a], ids[b]) for a, b in case["confirmed"]]
    distinct = [(ids[a], ids[b]) for a, b in case["decided"]]
    merges, queue = _expected(case, ids)
    results = []
    for _ in range(2):
        order = list(entities)
        rnd.shuffle(order)
        result = plan(order, confirmed=confirmed, distinct=distinct)
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
        ids[r["key"]] = onto.entities.create(PERSON, list(r["names"]), external=external)
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
        merges, queue = _expected(case, ids, links)
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
