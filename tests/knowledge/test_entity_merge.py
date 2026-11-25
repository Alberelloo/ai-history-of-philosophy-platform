"""ontology-entities, MODIFIED (improve-person-quality): «Поиск дублей» и «Слияние с
перенаправлением».

По дельте ``openspec/changes/improve-person-quality/specs/ontology-entities``. Слияние —
``Statements.merge_entities``, отмена — ``Statements.undo_merge`` (пути оператора), поиск —
``Entities.duplicate_candidates``, очередь — ``Review.refresh_duplicates``. Вывод —
карточка и ``/entities/{id}/statements`` по HTTP, карта, дамп таблиц данных (``dump.py``).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, example, given, settings
from sqlalchemy import select

from philograph.knowledge import schema as t
from philograph.knowledge.app import build_app
from philograph.knowledge.map import SectionMap
from philograph.knowledge.review import Review
from philograph.knowledge.statements import Attribution, Evidence
from philograph.operator.access import ActionLog

from ..conftest import PROFILES
from .dump import dump
from .strategies import expected_candidates, ontology_names, ontology_with_duplicates

req = pytest.mark.req
OE = "ontology-entities"
SEARCH = "Поиск дублей"
MERGE = "Слияние с перенаправлением"
CTX = {"request_id", "run_id", "service"}
MERGED = "knowledge.entity.merged"
UNDONE = "knowledge.entity.merge_undone"
MERGED_KEYS = {"kept", "removed", "reason", "statements", "attributions", "folded", "loops"}
UNDONE_KEYS = {"kept", "removed", "restored"}
CI = settings(parent=PROFILES["ci"], suppress_health_check=[HealthCheck.function_scoped_fixture])
HEAVY = settings(
    parent=PROFILES["heavy"], suppress_health_check=[HealthCheck.function_scoped_fixture]
)


def keys(event) -> set[str]:
    return set(event.fields) - CTX


def names(onto, entity_id) -> set[tuple[str, str, str]]:
    return {(n["lang"], n["text"], n["kind"]) for n in onto.entities.get(entity_id)["names"]}


def api(onto) -> TestClient:
    return TestClient(build_app(onto.statements))


def influence(onto, subject, obj, who, paragraph="p2"):
    quote = onto.paragraphs[paragraph][:12]
    return onto.statements.add(
        subject,
        "influenced_by",
        obj=obj,
        attributions=[Attribution("source", who)],
        evidence=[Evidence(paragraph, quote, source_id=who)],
    )


def wipe(onto) -> None:
    with onto.statements.engine.begin() as conn:
        for table in (
            t.attributions,
            t.evidence,
            t.statements,
            t.mentions,
            t.portraits,
            t.merges,
            t.external_ids,
            t.names,
            t.entities,
        ):
            conn.execute(table.delete())


def portrait(onto, entity_id, phash):
    with onto.statements.engine.begin() as conn:
        return conn.execute(
            t.portraits.insert().values(
                entity_id=entity_id,
                file_id="f" * 64,
                width=1,
                height=1,
                license="cc0",
                source_url="https://example.org",
                origin="wikidata:Q1",
                phash=phash,
                position=0,
                status="draft",
                hidden=False,
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        ).inserted_primary_key[0]


def mention(onto, entity_id, start):
    with onto.statements.engine.begin() as conn:
        conn.execute(
            t.mentions.insert().values(
                target_id="p1",
                target_kind="paragraph",
                source_id="s_a",
                entity_id=entity_id,
                start=start,
                end=start + 3,
                method="exact",
            )
        )


# =========================== Поиск дублей ================================================


@req(OE, SEARCH, scenario="Кандидаты")
def test_candidates(onto):
    a = onto.person("Дж. Локк", "1632", "1704")
    b = onto.person("Джон Локк", "1632", "1704")
    pairs = {frozenset(p) for p in onto.entities.duplicate_candidates()}
    assert frozenset({a, b}) in pairs


@req(OE, SEARCH, scenario="Основное название на разных записях")
def test_primary_on_different_records(onto, clock):
    ids = [onto.entities.create("person", [("en", "Berkeley", "primary")]) for _ in range(3)]
    review = Review(onto.statements, ActionLog(onto.statements.engine, clock))
    review.refresh_duplicates()
    items = review.queue(kind="duplicate")
    assert sorted(frozenset(i["payload"]["pair"]) for i in items) == sorted(
        [frozenset({ids[0], ids[1]}), frozenset({ids[0], ids[2]}), frozenset({ids[1], ids[2]})]
    )
    assert len(items) == 3


@req(OE, SEARCH, scenario="Разные типы")
def test_different_types(onto):
    plato = onto.person("Платон")
    work = onto.thing("work", "Платон")
    pairs = {frozenset(p) for p in onto.entities.duplicate_candidates()}
    assert frozenset({plato, work}) not in pairs


@req(OE, SEARCH, invariant="Основное одной = любое название другой ⇒ кандидат; разные типы никогда")
@CI
@given(ontology_names())
@example(
    [
        {"type": "person", "primary": "Фрэнсис Бэкон", "variants": ["Бэкон"]},
        {"type": "person", "primary": "Бэкон", "variants": []},
        {"type": "work", "primary": "Бэкон", "variants": []},
    ]
)
@example(
    [
        {"type": "person", "primary": "Berkeley", "variants": []},
        {"type": "person", "primary": "Berkeley", "variants": []},
        {"type": "concept", "primary": "berkeley", "variants": []},
    ]
)
def test_candidates_invariant(onto, case):
    wipe(onto)
    ids = []
    for e in case:
        lang = "ru" if any("а" <= ch <= "я" for ch in e["primary"].lower()) else "en"
        rows = [(lang, e["primary"], "primary")] + [
            ("ru" if any("а" <= ch <= "я" for ch in v.lower()) else "en", v, "variant")
            for v in e["variants"]
        ]
        ids.append(onto.entities.create(e["type"], rows))
    got = {frozenset(p) for p in onto.entities.duplicate_candidates()}
    expected = {frozenset(ids[i] for i in pair) for pair in expected_candidates(case)}
    assert expected <= got
    by_id = dict(zip(ids, case, strict=True))
    for pair in got:
        a, b = sorted(pair)
        assert by_id[a]["type"] == by_id[b]["type"], (by_id[a], by_id[b])


# =========================== Слияние с перенаправлением ===================================


@req(OE, MERGE, scenario="Старая ссылка")
def test_old_link(onto, svc):
    a = onto.person("Дж. Локк", "1632", "1704")
    b = onto.person("Джон Локк", "1632", "1704")
    onto.statements.merge_entities(b, a)
    old, _ = svc.get(f"/v1/entities/{a}/card")
    new, _ = svc.get(f"/v1/entities/{b}/card")
    assert old.status_code == new.status_code == 200
    assert old.json() == new.json()
    assert api(onto).get(f"/v1/entities/{a}").json()["id"] == b


@req(OE, MERGE, scenario="Отмена")
def test_undo(onto, events):
    a = onto.person("Дж. Локк", "1632", "1704")
    b = onto.person("Джон Локк", "1632", "1704")
    sa = onto.statements.add(
        a, "holds", obj=onto.thing("position", "Всё из опыта"), attributions=[Attribution("common")]
    )
    sb = onto.statements.add(
        b, "holds", obj=onto.thing("position", "Чистая доска"), attributions=[Attribution("common")]
    )
    before = dump(onto.statements.engine)
    merge_id = onto.statements.merge_entities(a, b)
    events.clear()
    onto.statements.undo_merge(merge_id)
    assert dump(onto.statements.engine) == before
    client = api(onto)
    assert {s["id"] for s in client.get(f"/v1/entities/{a}/statements").json()} >= {sa}
    assert sb in {s["id"] for s in client.get(f"/v1/entities/{b}/statements").json()}
    assert sb not in {s["id"] for s in client.get(f"/v1/entities/{a}/statements").json()}
    [undone] = events.of(UNDONE)
    assert keys(undone) == UNDONE_KEYS
    assert (undone["kept"], undone["removed"]) == (a, b)


def _hume_yum(onto):
    hume = onto.entities.create(
        "person", [("en", "Hume", "primary")], external={"wikidata": "Q41568"}
    )
    yum = onto.entities.create("person", [("ru", "Юм", "primary")])
    locke = onto.thing("person", "Локк")
    return hume, yum, locke


@req(OE, MERGE, scenario="Повтор сворачивается")
def test_repeat_folds(onto, events):
    hume, yum, locke = _hume_yum(onto)
    kept_st = influence(onto, yum, locke, "s_a", paragraph="p1")
    folded_st = influence(onto, hume, locke, "s_b", paragraph="p2")
    events.clear()
    onto.statements.merge_entities(yum, hume)
    survivor = onto.statements.get(folded_st)
    assert survivor["id"] == kept_st
    assert sorted(a["who"] for a in survivor["attributions"]) == ["s_a", "s_b"]
    assert sorted((e["paragraph_id"], e["source_id"]) for e in survivor["evidence"]) == [
        ("p1", "s_a"),
        ("p2", "s_b"),
    ]
    about = api(onto).get(f"/v1/entities/{yum}/statements").json()
    assert [s["id"] for s in about if s["type"] == "influenced_by"] == [kept_st]
    [merged] = events.of(MERGED)
    assert keys(merged) == MERGED_KEYS
    assert merged["folded"] == 1


@req(OE, MERGE, scenario="Атрибуция автору переносится")
def test_author_attribution_moves(onto, events):
    hume, yum, _locke = _hume_yum(onto)
    work = onto.thing("position", "Причинность — привычка")
    st_id = onto.statements.add(
        work,
        "description",
        value="связь причины и следствия выводится из опыта",
        attributions=[Attribution("entity", hume, stance="supports")],
    )
    events.clear()
    onto.statements.merge_entities(yum, hume)
    [who] = onto.statements.get(st_id)["attributions"]
    assert (who["who_kind"], who["who"], who["stance"]) == ("entity", yum, "supports")
    [merged] = events.of(MERGED)
    assert keys(merged) == MERGED_KEYS
    assert merged["attributions"] >= 1


@req(OE, MERGE, scenario="Петля")
def test_loop(onto, events):
    hume = onto.entities.create("person", [("en", "Hume", "primary")])
    yum = onto.person("Юм", "1711", "1776")
    locke = onto.person("Локк", "1632", "1704")
    loop = influence(onto, hume, yum, "s_a")
    control = influence(onto, yum, locke, "s_a")
    events.clear()
    onto.statements.merge_entities(yum, hume)
    with onto.statements.engine.begin() as conn:
        assert conn.scalar(select(t.statements.c.id).where(t.statements.c.id == loop)) == loop
    client = api(onto)
    shown = {s["id"] for s in client.get(f"/v1/entities/{yum}/statements").json()}
    assert control in shown and loop not in shown
    links = {link["id"] for link in SectionMap(onto.statements).build()["links"]}
    assert control in links and loop not in links
    [merged] = events.of(MERGED)
    assert keys(merged) == MERGED_KEYS
    assert merged["loops"] == 1


@req(OE, MERGE, scenario="Отмена со свёрткой и QID")
def test_undo_with_fold_and_qid(onto, events):
    hume, yum, locke = _hume_yum(onto)
    yum_st = influence(onto, yum, locke, "s_a", paragraph="p1")
    hume_st = influence(onto, hume, locke, "s_b", paragraph="p2")
    before = dump(onto.statements.engine)
    merge_id = onto.statements.merge_entities(yum, hume)
    assert onto.entities.externals("wikidata") == {yum: "Q41568"}
    events.clear()
    onto.statements.undo_merge(merge_id)
    assert dump(onto.statements.engine) == before
    assert onto.entities.externals("wikidata") == {hume: "Q41568"}
    restored = onto.statements.get(hume_st)
    assert restored["id"] == hume_st and restored["subject"] == hume
    assert [(a["who"]) for a in restored["attributions"]] == ["s_b"]
    assert [(e["paragraph_id"], e["source_id"]) for e in restored["evidence"]] == [("p2", "s_b")]
    assert names(onto, hume) == {("en", "Hume", "primary")}
    assert [a["who"] for a in onto.statements.get(yum_st)["attributions"]] == ["s_a"]
    [undone] = events.of(UNDONE)
    assert keys(undone) == UNDONE_KEYS
    assert undone["restored"] == 1


# --- инвариант сохранения ---------------------------------------------------------------


def _build(onto, case) -> tuple[list[str], dict[int, list[str]]]:
    ids = []
    for i, e in enumerate(case["entities"]):
        external = {"wikidata": "Q41568"} if case["qid_side"] == i else None
        ids.append(onto.entities.create(e["type"], list(e["names"]), external=external))
    created: dict[int, list[str]] = {}
    for n, s in enumerate(case["statements"]):
        attributions = [
            Attribution(kind, ids[who] if kind == "entity" else who, stance=stance)
            for kind, who, stance in s["attributions"]
        ]
        evidence = [Evidence(p, onto.paragraphs[p][:12], source_id=src) for p, src in s["evidence"]]
        created[n] = [
            onto.statements.add(
                ids[s["subject"]],
                s["type"],
                obj=ids[s["object"]] if s["object"] is not None else None,
                value=s["value"],
                attributions=attributions,
                evidence=evidence,
            )
        ]
    for k, side in enumerate(case["mentions"]):
        mention(onto, ids[side], 10 * k)
    for side, phash in case["portraits"]:
        portrait(onto, ids[side], phash)
    return ids, created


def _content(s: dict, r) -> tuple:
    return (r(s["subject"]), s["type"], r(s["object"]), s["value"])


EXACT_REPEAT = {
    "entities": [
        {"type": "person", "names": [("en", "Hume", "primary")]},
        {"type": "person", "names": [("ru", "Юм", "primary")]},
        {"type": "person", "names": [("ru", "Персона 2", "primary")]},
        {"type": "position", "names": [("ru", "Позиция 0", "primary")]},
        {"type": "position", "names": [("ru", "Позиция 1", "primary")]},
    ],
    "qid_side": 1,
    "statements": [
        {
            "subject": 0,
            "type": "influenced_by",
            "object": 2,
            "value": None,
            "attributions": [("source", "s_a", "asserts")],
            "evidence": [("p1", "s_a")],
        },
        {
            "subject": 1,
            "type": "influenced_by",
            "object": 2,
            "value": None,
            "attributions": [("source", "s_a", "asserts")],
            "evidence": [("p1", "s_a")],
        },
        {
            "subject": 2,
            "type": "criticizes",
            "object": 0,
            "value": None,
            "attributions": [("entity", 1, "supports")],
            "evidence": [],
        },
        {
            "subject": 1,
            "type": "criticizes",
            "object": 0,
            "value": None,
            "attributions": [("source", "s_b", "asserts")],
            "evidence": [("p2", "s_b")],
        },
    ],
    "mentions": [0, 1],
    "portraits": [(0, "aaaa"), (1, "aaaa"), (1, "bbbb")],
}


@req(OE, MERGE, scenario="Инвариант сохранения")
@req(OE, MERGE, invariant="Не потеряно утверждение, атрибуция, подтверждение; отмена ⇒ дамп")
@HEAVY
@given(ontology_with_duplicates())
@example(EXACT_REPEAT)
def test_preservation_and_undo(onto, events, case):
    wipe(onto)
    ids, created = _build(onto, case)
    kept, removed = ids[0], ids[1]

    def r(x):
        return None if x is None else (kept if ids[x] == removed else ids[x])

    def who(kind, w):
        if kind != "entity":
            return w
        return kept if ids[w] == removed else ids[w]

    groups: dict[tuple, dict] = {}
    loops = set()
    for n, s in enumerate(case["statements"]):
        content = _content(s, r)
        if content[0] == content[2] == kept:
            loops.add(created[n][0])
            continue
        g = groups.setdefault(content, {"attributions": set(), "evidence": set(), "ids": set()})
        g["attributions"] |= {(k, who(k, w), stance) for k, w, stance in s["attributions"]}
        g["evidence"] |= set(s["evidence"])
        g["ids"].add(created[n][0])
    kept_phash = {p for side, p in case["portraits"] if side == 0}
    before = dump(onto.statements.engine)
    had_ru = any(
        lang == "ru" and kind == "primary"
        for e in case["entities"][:2]
        for lang, _text, kind in e["names"]
    )
    all_names = {(lang, text) for e in case["entities"][:2] for lang, text, _k in e["names"]}
    events.clear()

    merge_id = onto.statements.merge_entities(kept, removed)

    # содержание без петель
    survivors = {}
    for content, g in groups.items():
        got = {onto.statements.get(i)["id"] for i in g["ids"]}
        assert len(got) == 1, content
        survivor = onto.statements.get(next(iter(got)))
        assert (survivor["subject"], survivor["type"], survivor["object"], survivor["value"]) == (
            content
        )
        survivors[content] = survivor
    assert len({s["id"] for s in survivors.values()}) == len(groups)
    # атрибуции и подтверждения
    for content, g in groups.items():
        s = survivors[content]
        att = [(a["who_kind"], a["who"], a["stance"]) for a in s["attributions"]]
        assert sorted(set(att)) == sorted(g["attributions"]), content
        # точный повтор атрибуции на одном утверждении допускается спецификацией; повтор
        # при повторном add — до слияния (наблюдение в verification.md), поэтому без счёта
        ev = {(e["paragraph_id"], e["source_id"]) for e in s["evidence"]}
        assert ev >= g["evidence"], content
    for loop in loops:
        got = onto.statements.get(loop)
        assert got["subject"] == got["object"] == kept
    shown = {s["id"] for s in onto.statements.about(kept, derived=False)}
    assert not (shown & loops)
    # названия, внешние, упоминания, портреты
    primaries = [n for n in onto.entities.get(kept)["names"] if n["kind"] == "primary"]
    assert len(primaries) == 1
    assert (primaries[0]["lang"] == "ru") == had_ru
    assert {(lang, text) for lang, text, _ in names(onto, kept)} >= all_names
    if case["qid_side"] is not None:
        assert onto.entities.externals("wikidata") == {kept: "Q41568"}
    with onto.statements.engine.begin() as conn:
        assert set(conn.scalars(select(t.mentions.c.entity_id))) <= {kept}
        owners = conn.execute(select(t.portraits.c.entity_id, t.portraits.c.phash)).all()
    for owner, phash in owners:
        assert owner == (removed if (owner == removed and phash in kept_phash) else kept)
    stays = sum(1 for side, p in case["portraits"] if side == 1 and p in kept_phash)
    assert sum(1 for o, _ in owners if o == removed) == stays
    [merged] = events.of(MERGED)
    assert keys(merged) == MERGED_KEYS
    assert (merged["kept"], merged["removed"], merged["loops"]) == (kept, removed, len(loops))

    events.clear()
    onto.statements.undo_merge(merge_id)
    assert dump(onto.statements.engine) == before
    [undone] = events.of(UNDONE)
    assert keys(undone) == UNDONE_KEYS
