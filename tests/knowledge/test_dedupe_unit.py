"""Юнит-тесты правила слияния вариантов (``knowledge/dedupe.py``) на опорных случаях.
Сценарные и нормативные тесты требования «Слияние вариантов персоны» — у тестировщика."""

from __future__ import annotations

import itertools

import pytest

from philograph.knowledge.dates import lifespan
from philograph.knowledge.dedupe import Dedupe, Entity, choose_kept, plan, same_person
from philograph.knowledge.naming import normalize


def person(id_, primary, *variants, dates=None, qid=None, type_="person"):
    names = [("primary", normalize(primary))] + [("variant", normalize(v)) for v in variants]
    span = lifespan(*dates.split("–")).to_json() if dates else None
    return Entity(id_, type_, tuple(names), span, qid)


@pytest.mark.parametrize(
    ("a", "b", "kw", "reason"),
    [
        (person("a", "Платон"), person("b", "Платон", type_="work"), {}, "apart:type"),
        (person("a", "Бэкон", qid="Q1"), person("b", "Бэкон", qid="Q2"), {}, "apart:qid"),
        (person("a", "Бэкон"), person("b", "Бэкон"), {"decided_apart": True}, "apart:decided"),
        (
            person("a", "Berkeley", dates="1685–1753"),
            person("b", "Berkeley", dates="1885–1953"),
            {},
            "review:dates",
        ),
        (
            person("a", "Hume", qid="Q1"),
            person("b", "Юм"),
            {"qid_confirmed": True},
            "merge:qid_confirmed",
        ),
        (person("a", "Berkeley"), person("b", "berkeley"), {}, "merge:name"),
        (person("a", "Locke"), person("b", "Локк"), {"paired_by_model": True}, "merge:model_pair"),
        (person("a", "Бэкон"), person("b", "Фрэнсис Бэкон", "Бэкон"), {}, "review:single_name"),
        (person("a", "Томас Рид"), person("b", "Thomas Reid", "Томас Рид"), {}, "review:variant"),
        (person("a", "Гомер"), person("b", "Омир"), {}, "apart:none"),
        (
            person("a", "Berkeley", dates="1685–1753"),
            person("b", "Berkeley", dates="1687–1755"),
            {},
            "merge:name",
        ),  # в допуске 2 года
        (person("a", "Berkeley", dates="1685–1753"), person("b", "Berkeley"), {}, "merge:name"),
    ],
)
def test_same_person(a, b, kw, reason):
    assert same_person(a, b, **kw).reason == reason
    assert same_person(b, a, **kw).reason == reason


def test_choose_kept_order():
    a, b, c = person("e_b", "X"), person("e_a", "X"), person("e_c", "X", qid="Q1")
    assert choose_kept([a, b, c], {}) == "e_c"
    assert choose_kept([a, b], {"e_b": 3}) == "e_b"
    assert choose_kept([a, b], {}) == "e_a"


def test_component_with_two_qids_goes_to_queue():
    ents = [person("e1", "Hume", qid="Q1"), person("e2", "Hume"), person("e3", "Hume", qid="Q2")]
    for order in itertools.permutations(ents):
        result = plan(order)
        assert result.merges == []
        assert result.review == [
            ("e1", "e2", "review:qid_cluster"),
            ("e2", "e3", "review:qid_cluster"),
        ]


def test_plan_independent_of_order():
    ents = [
        person("e1", "Berkeley"),
        person("e2", "Berkeley"),
        person("e3", "Berkeley"),
        person("e4", "Юм"),
        person("e5", "Hume", qid="Q1"),
        person("e6", "Бэкон"),
        person("e7", "Фрэнсис Бэкон", "Бэкон"),
    ]
    results = {
        repr(plan(order, confirmed=[("e4", "e5")])) for order in itertools.permutations(ents, 7)
    }
    assert len(results) == 1
    result = plan(ents, confirmed=[("e4", "e5")])
    assert result.merges == [
        ("e1", ["e2", "e3"], "merge:name"),
        ("e5", ["e4"], "merge:qid_confirmed"),
    ]
    assert result.review == [("e6", "e7", "review:single_name")]


def test_decided_pair_blocks_transitive_merge():
    ents = [person("e1", "Бэкон"), person("e2", "Бэкон"), person("e3", "Бэкон")]
    result = plan(ents, distinct=[("e1", "e2")])
    assert result.merges == []
    assert ("e1", "e2") not in {(a, b) for a, b, _ in result.review}


def test_dedupe_run_merges_and_proposes(onto, events):
    ids = [onto.person("Berkeley") for _ in range(3)]
    francis = onto.entities.create(
        "person", [("ru", "Фрэнсис Бэкон", "primary"), ("ru", "Бэкон", "variant")]
    )
    bacon = onto.person("Бэкон")
    dedupe = Dedupe(onto.statements)
    assert dedupe.run(dry_run=True) == {"merged": 2, "proposed": 1, "apart": 0}
    assert dedupe.run(run_id="r1") == {"merged": 2, "proposed": 1, "apart": 0}
    assert {onto.entities.resolve(i) for i in ids} == {min(ids)}
    reasons = [e.fields["reason"] for e in events.of("knowledge.entity.merged")]
    assert reasons == ["merge:name", "merge:name"]
    proposed = events.one("knowledge.entity.merge_proposed").fields
    assert {proposed["kept"], proposed["removed"]} == {francis, bacon}
    assert dedupe.run()["proposed"] == 0  # пункт по паре уже открыт


def test_duplicate_candidates_by_index(onto):
    a = onto.person("Дж. Локк", "1632", "1704")
    b = onto.person("Джон Локк", "1632", "1704")
    berkeley = [onto.person("Berkeley") for _ in range(3)]
    francis = onto.entities.create(
        "person", [("ru", "Фрэнсис Бэкон", "primary"), ("ru", "Бэкон", "variant")]
    )
    roger = onto.person("Бэкон", "1214", "1292")
    plato_work = onto.thing("work", "Berkeley")
    pairs = onto.entities.duplicate_candidates()
    assert (a, b) in pairs
    assert {p for p in pairs if set(p) <= set(berkeley)} == {
        (berkeley[0], berkeley[1]),
        (berkeley[0], berkeley[2]),
        (berkeley[1], berkeley[2]),
    }
    assert (francis, roger) in pairs  # основное одной — вариант другой
    assert not any(plato_work in p for p in pairs)  # разные типы — никогда
