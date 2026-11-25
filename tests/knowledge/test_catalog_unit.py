"""Юнит-тесты индекса и запроса справочника (``knowledge/catalog.py``)."""

from __future__ import annotations

import pytest

from philograph.knowledge.catalog import Catalog, CatalogRejected, CatalogSettings, _summary
from philograph.knowledge.snapshot import Snapshots
from philograph.knowledge.statements import Attribution, Evidence, Provenance

COMMON = [Attribution("common")]
TEXTBOOK = "s_textbook"


@pytest.fixture
def cat(onto, clock):
    return Catalog(
        Snapshots(onto.statements.engine, clock),
        onto.registry,
        onto.entities,
        CatalogSettings(max_stale_seconds=15),
    )


@pytest.fixture
def base(onto):
    w = {
        "kant": onto.person("Иммануил Кант", "1724", "1804"),
        "hume": onto.person("Дэвид Юм", "1711", "1776"),
        "causality": onto.thing("concept", "Причинность"),
        "critique": onto.thing("work", "Критика чистого разума", "1781"),
        "enl": onto.thing("epoch", "Просвещение", "1680–1800"),
        "source": onto.entities.source_entity(TEXTBOOK, "Учебник N"),
    }
    return w


def labels(result):
    return [i["label"] for i in result["items"]]


def test_list_without_filters(cat, base, events):
    result = cat.list()
    assert labels(result) == [
        "Дэвид Юм",
        "Иммануил Кант",
        "Критика чистого разума",
        "Причинность",
        "Просвещение",
    ]
    kant = next(i for i in result["items"] if i["id"] == base["kant"])
    assert kant["dates"] == {"from": 1724, "to": 1804, "precision": "year", "original": "1724–1804"}
    assert kant["epochs"] == [{"id": base["enl"], "label": "Просвещение", "basis": "dates"}]
    assert kant["matched_name"] is None and kant["summary"] is None
    assert result["facets"]["types"] == {"concept": 1, "epoch": 1, "person": 2, "work": 1}
    listed = events.one("knowledge.catalog.listed")
    assert {k: listed.get(k) for k in listed.fields if k != "request_id"} == {
        "total": 5,
        "returned": 5,
        "page": 1,
        "filters": [],
        "q_len": 0,
        "sort": "label",
        "snapshot": "fresh",
        "textbook_closed": False,
    }


def test_search_ranking_and_variant(onto, cat):
    kant = onto.person("Иммануил Кант")
    onto.person("Георг Кантор")
    onto.thing("concept", "Пространство")
    onto.thing("concept", "Американский прагматизм")
    onto.entities.add_name(kant, "de", "Kant")
    result = cat.list(q="кан")
    assert labels(result) == ["Георг Кантор", "Иммануил Кант", "Американский прагматизм"]
    assert result["sort"] == "relevance"
    found = cat.list(q="KANT")["items"]
    assert [(i["label"], i["matched_name"]) for i in found] == [("Иммануил Кант", "Kant")]


def test_exact_match_first(onto, cat):
    kant = onto.person("Кант")
    kantor = onto.person("Кантор")
    for _ in range(3):
        onto.statements.add(onto.thing("work", "Труд"), "author", obj=kantor, attributions=COMMON)
    assert [i["id"] for i in cat.list(q="кант")["items"]] == [kant, kantor]


def test_yo_and_case(onto, cat):
    onto.person("Пётр Чаадаев")
    assert labels(cat.list(q="ПЕТР")) == ["Пётр Чаадаев"]


def test_type_with_subtypes_and_epoch_facets(onto, cat):
    sci = onto.thing("epoch", "Научная революция", "1543–1687")
    enl = onto.thing("epoch", "Просвещение", "1680–1800")
    onto.person("Декарт", "1596", "1650")
    onto.person("Юм", "1711", "1776")
    onto.person("Кант", "1724", "1804")
    onto.thing("idea_event", "Ответ Канта Юму", "1781")
    assert labels(cat.list(types=["event"])) == ["Ответ Канта Юму"]
    result = cat.list(types=["person"], epoch=enl)
    assert labels(result) == ["Кант", "Юм"]
    assert result["facets"]["epochs"] == [
        {"id": sci, "label": "Научная революция", "count": 1},
        {"id": enl, "label": "Просвещение", "count": 2},
    ]
    # Счётчик типов — без фильтра типа, но с фильтром эпохи.
    assert result["facets"]["types"] == {"idea_event": 1, "person": 2}  # точный код


def test_textbook_scope_mentions_and_evidence(onto, cat, base):
    locke = onto.person("Локк")
    ideas = onto.thing("concept", "Врождённые идеи")
    onto.person("Беркли")
    onto.statements.add(
        locke,
        "criticizes",
        obj=ideas,
        attributions=[Attribution("source", "s_other")],
        evidence=[Evidence("p3", "Локк сравнивал ум с чистой доской", source_id=TEXTBOOK)],
        provenance=Provenance("extracted"),
    )
    result = cat.list(textbook=TEXTBOOK)
    assert labels(result) == ["Врождённые идеи", "Локк"]
    closed = cat.list(textbook=TEXTBOOK, q="локк", closed=lambda: frozenset({TEXTBOOK}))
    assert closed == {
        "items": [],
        "total": 0,
        "page": 1,
        "limit": 24,
        "sort": "relevance",
        "facets": {"types": {}, "epochs": []},
        "textbook_closed": True,
    }


def test_closed_not_asked_without_textbook(cat, base):
    def boom():
        raise AssertionError("регион без раздела не нужен")

    assert cat.list(q="кант", closed=boom)["total"] == 1


def test_pages_stable_and_beyond_end(onto, cat):
    for n in range(30):
        onto.person(f"Персона {n:02d}")
    first = cat.list(page="1", limit="24")
    second = cat.list(page="2", limit="24")
    assert len(first["items"]) == 24 and len(second["items"]) == 6
    assert not {i["id"] for i in first["items"]} & {i["id"] for i in second["items"]}
    beyond = cat.list(page="99")
    assert beyond["items"] == [] and beyond["total"] == 30
    assert beyond["facets"] == first["facets"]


def test_sort_date_and_weight(cat, onto, base, clock):
    assert labels(cat.list(sort="date")) == [
        "Просвещение",
        "Дэвид Юм",
        "Иммануил Кант",
        "Критика чистого разума",
        "Причинность",
    ]
    onto.statements.add(base["critique"], "author", obj=base["kant"], attributions=COMMON)
    clock.advance(seconds=15)  # окно устарелости справочника
    top = cat.list(sort="weight")["items"][:2]  # оба по 2 утверждения: равный ключ — по id
    assert [i["id"] for i in top] == sorted([base["kant"], base["critique"]])
    assert cat.list(sort="relevance")["sort"] == "label"


def test_summary_and_generated(onto, cat, base):
    onto.statements.add(
        base["causality"],
        "description",
        value="Связь причины и следствия",
        attributions=COMMON,
        provenance=Provenance("generated"),
    )
    onto.statements.add(
        base["kant"], "description", value="Немецкий философ " * 30, attributions=COMMON
    )
    items = {i["id"]: i for i in cat.list()["items"]}
    assert items[base["causality"]]["summary"] == {
        "text": "Связь причины и следствия",
        "generated": True,
    }
    kant = items[base["kant"]]["summary"]
    assert kant["generated"] is False and kant["text"].endswith("Немецкий…")
    assert len(kant["text"]) <= 201


def test_summary_cut_by_word():
    assert _summary("слово " * 50) == ("слово " * 33).strip() + "…"
    assert _summary("коротко") == "коротко"


@pytest.mark.parametrize(
    ("params", "kind", "reason"),
    [
        ({"q": "к" * 201}, "bad_query", "query_too_long"),
        ({"limit": "61"}, "bad_query", "limit"),
        ({"limit": "0"}, "bad_query", "limit"),
        ({"limit": "x"}, "bad_query", "limit"),
        ({"page": "0"}, "bad_query", "page"),
        ({"page": "-"}, "bad_query", "page"),
        ({"sort": "rank"}, "bad_query", "sort"),
        ({"types": ["dragon"]}, "unknown_type", "unknown_type"),
        ({"epoch": "KANT"}, "unknown_epoch", "unknown_epoch"),
        ({"epoch": "e_missing"}, "unknown_epoch", "unknown_epoch"),
        ({"textbook": "s_unknown"}, "unknown_textbook", "unknown_textbook"),
    ],
)
def test_rejected(cat, base, events, params, kind, reason):
    if params.get("epoch") == "KANT":
        params = {"epoch": base["kant"]}
    with pytest.raises(CatalogRejected) as exc:
        cat.list(**params)
    assert (exc.value.kind, exc.value.reason) == (kind, reason)
    assert events.one("knowledge.catalog.rejected").get("reason") == reason
    events.assert_none("knowledge.catalog.listed")


def test_bounds_accepted(cat, base):
    assert cat.list(q="к" * 200)["total"] == 0
    assert cat.list(limit="60")["limit"] == 60
    assert cat.list(q="   ")["sort"] == "label"


def test_merged_and_epoch_redirect(onto, cat, base):
    dup = onto.person("Кант (дубль)")
    epoch_dup = onto.thing("epoch", "Век Просвещения")
    onto.entities.merge(base["kant"], dup)
    onto.entities.merge(base["enl"], epoch_dup)
    result = cat.list(epoch=epoch_dup)  # id слитой эпохи ведёт на оставшуюся
    assert base["kant"] in {i["id"] for i in result["items"]}
    assert dup not in {i["id"] for i in cat.list()["items"]}


def test_events_have_no_text(onto, cat, events):
    onto.person("Пётр Чаадаев")
    cat.list(q="чаадаев")
    cat.list(q="<script>")
    with pytest.raises(CatalogRejected):
        cat.list(q="чаадаев" * 40)
    for event in events.items:
        if event.name.startswith("knowledge.catalog."):
            text = repr(event.fields).lower()
            assert "чаадаев" not in text and "script" not in text
    assert events.of("knowledge.catalog.listed")[0].get("q_len") == 7


def test_stale_window(onto, cat, clock, events):
    cat.list()
    clock.advance(seconds=1)
    onto.person("Иоганн Фихте")
    clock.advance(seconds=4)
    assert cat.list(q="фихте")["total"] == 0
    clock.advance(seconds=11)
    assert cat.list(q="фихте")["total"] == 1
    statuses = [e.get("snapshot") for e in events.of("knowledge.catalog.listed")]
    assert statuses == ["fresh", "stale", "fresh"]


def test_lang_label_falls_back_to_russian(onto, cat):
    kant = onto.entities.create("person", [("ru", "Кант", "primary"), ("en", "Kant", "primary")])
    onto.person("Юм")
    items = cat.list(lang="en")["items"]
    assert [(i["id"] == kant, i["label"]) for i in items] == [(True, "Kant"), (False, "Юм")]
