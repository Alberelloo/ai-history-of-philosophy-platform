"""entity-catalog: справочник сервиса знаний (``GET /v1/catalog``) — сценарии и инварианты.

Тесты написаны по дельте ``openspec/changes/add-reference-catalog/specs/entity-catalog``:
запрос идёт через HTTP-маршрут сервиса знаний (``CatalogService`` в ``conftest.py``), каждый
тест проверяет и ответ, и события журнала с ``request_id`` этого запроса.
"""

from __future__ import annotations

import itertools
import json
import random

import pytest
from sqlalchemy import func, select

from philograph.knowledge import schema as t

from .conftest import TEXTBOOK_N, TEXTBOOK_R, VISITOR_ADDRESS

req = pytest.mark.req
EC = "entity-catalog"
LISTED = "knowledge.catalog.listed"
REJECTED = "knowledge.catalog.rejected"
BUILT = "knowledge.snapshot.built"


def listed(events, rid: str):
    """Единственное событие ``knowledge.catalog.listed`` этого запроса."""
    found = events.where(LISTED, request_id=rid)
    assert len(found) == 1, f"ожидалось одно {LISTED} для {rid}: {events.names()}"
    return found[0]


def labels(body: dict) -> list[str]:
    return [item["label"] for item in body["items"]]


def by_label(body: dict) -> dict[str, dict]:
    return {item["label"]: item for item in body["items"]}


def all_ids(body: dict) -> set[str]:
    """Все идентификаторы, встречающиеся в записях (сами записи и их эпохи)."""
    ids = set()
    for item in body["items"]:
        ids.add(item["id"])
        ids.update(e["id"] for e in item.get("epochs") or [])
    return ids


# --- Список справочника -------------------------------------------------------------------


@req(EC, "Список справочника", scenario="Справочник без фильтров")
def test_list_without_filters(svc, events):
    w = svc.world.base()
    body, rid = svc.catalog_ok()
    assert sorted(labels(body)) == sorted(
        ["Иммануил Кант", "Дэвид Юм", "Причинность", "Критика чистого разума", "Просвещение"]
    )
    assert "Учебник N" not in labels(body)
    assert body["total"] == 5
    kant = by_label(body)["Иммануил Кант"]
    assert kant["id"] == w["kant"] and kant["type"] == "person"
    assert kant["dates"] == {"from": 1724, "to": 1804, "precision": "year", "original": "1724–1804"}
    assert kant["epochs"] == [{"id": w["enlightenment"], "label": "Просвещение", "basis": "dates"}]
    event = listed(events, rid)
    assert event["total"] == 5
    assert event["returned"] == 5
    assert event["page"] == 1
    assert event["filters"] == []
    assert event["q_len"] == 0
    assert event["sort"] == "label"
    assert event["textbook_closed"] is False


@req(EC, "Список справочника", scenario="Слитый дубль")
def test_merged_duplicate_hidden(svc, events):
    w = svc.world.base()
    dup = svc.world.person("Кант (дубль)", "1724", "1804")
    svc.onto.entities.merge(w["kant"], dup)
    body, rid = svc.catalog_ok()
    assert labels(body).count("Иммануил Кант") == 1
    assert "Кант (дубль)" not in labels(body)
    assert dup not in all_ids(body)
    with svc.onto.statements.engine.begin() as conn:
        rows = conn.scalar(
            select(func.count()).select_from(t.entities).where(t.entities.c.type != "source")
        )
    assert body["total"] == rows - 1
    assert listed(events, rid)["total"] == rows - 1


@req(EC, "Список справочника", scenario="Сгенерированное описание помечено")
def test_generated_summary_marked(svc, events):
    w = svc.world.base()
    svc.world.describe(w["causality"], "Связь причины и следствия", generated=True)
    verified = svc.world.describe(w["kant"], "Немецкий философ, основатель критицизма")
    svc.onto.statements.confirm(verified, "operator")
    body, rid = svc.catalog_ok()
    items = by_label(body)
    assert items["Причинность"]["summary"]["generated"] is True
    assert items["Иммануил Кант"]["summary"]["generated"] is False
    assert listed(events, rid)["total"] == 5


@req(EC, "Список справочника", scenario="Справочник без модели")
def test_catalog_without_model(svc, events):
    svc.world.base()
    body, rid = svc.catalog_ok()
    assert body["total"] == 5 and len(body["items"]) == 5
    assert svc.llm_calls == []
    with_rid = [e.name for e in events.items if e.get("request_id") == rid]
    assert not [name for name in with_rid if name.startswith("llm.")], with_rid
    assert LISTED in with_rid


@req(EC, "Список справочника", scenario="В журнале нет текста")
def test_no_query_text_in_journal(svc, events):
    svc.world.person("Пётр Чаадаев", "1794", "1856")
    first, rid1 = svc.catalog_ok({"q": "чаадаев"})
    assert labels(first) == ["Пётр Чаадаев"]
    svc.catalog_ok({"q": "<script>"})
    response, _ = svc.get(params={"q": "ч" * 201})
    assert response.status_code == 400
    catalog_events = [e for e in events.items if e.name.startswith("knowledge.catalog.")]
    assert len(catalog_events) == 3
    dumped = json.dumps([e.fields for e in catalog_events], ensure_ascii=False)
    for needle in ("чаадаев", "Чаадаев", "<script>", VISITOR_ADDRESS):
        assert needle not in dumped, needle
    assert listed(events, rid1)["q_len"] == 7


# --- Поиск по названию ----------------------------------------------------------------------


@req(EC, "Поиск по названию", scenario="Часть названия")
def test_search_part_of_name(svc, events):
    w = svc.world
    w.person("Иммануил Кант")
    w.person("Георг Кантор")
    w.thing("concept", "Пространство")
    w.thing("concept", "Американский прагматизм")
    body, rid = svc.catalog_ok({"q": "кан"})
    assert body["total"] == 3
    # Начало слова: равная значимость (0) — по названию; затем вхождение внутрь слова.
    assert labels(body) == ["Георг Кантор", "Иммануил Кант", "Американский прагматизм"]
    assert "Пространство" not in labels(body)
    event = listed(events, rid)
    assert event["filters"] == ["q"]
    assert event["q_len"] == 3
    assert event["sort"] == "relevance"


@req(EC, "Поиск по названию", scenario="Часть названия")
def test_search_word_start_ordered_by_weight(svc, events):
    """Внутри группы «начало слова» значимость важнее названия."""
    w = svc.world
    kant = w.person("Иммануил Кант")
    w.person("Георг Кантор")
    w.thing("concept", "Американский прагматизм")
    w.relate(kant, "criticizes", w.thing("concept", "Догматизм"))
    body, rid = svc.catalog_ok({"q": "кан"})
    assert labels(body) == ["Иммануил Кант", "Георг Кантор", "Американский прагматизм"]
    assert listed(events, rid)["sort"] == "relevance"


@req(EC, "Поиск по названию", scenario="Точное совпадение первым")
def test_exact_match_first(svc, events):
    w = svc.world
    kant = w.person("Кант")
    kantor = w.person("Кантор")
    w.relate(kant, "criticizes", w.thing("concept", "Идея 0"))
    for i in range(1, 51):
        w.relate(kantor, "criticizes", w.thing("concept", f"Идея {i}"))
    body, rid = svc.catalog_ok({"q": "кант", "sort": "weight"})
    assert labels(body)[:2] == ["Кантор", "Кант"]  # значимость: 50 против 1
    assert body["items"][0]["weight"] == 50 and body["items"][1]["weight"] == 1
    body, rid = svc.catalog_ok({"q": "кант"})
    assert labels(body)[:2] == ["Кант", "Кантор"]
    assert listed(events, rid)["q_len"] == 4


@req(EC, "Поиск по названию", scenario="Вариант названия")
def test_variant_name_match(svc, events):
    w = svc.world.base()
    svc.world.variant(w["kant"], "Kant")
    body, rid = svc.catalog_ok({"q": "kant"})
    assert [(i["label"], i["matched_name"]) for i in body["items"]] == [("Иммануил Кант", "Kant")]
    assert body["items"][0]["id"] == w["kant"]
    body, rid = svc.catalog_ok({"q": "кант"})
    assert by_label(body)["Иммануил Кант"]["matched_name"] is None
    assert listed(events, rid)["filters"] == ["q"]


@req(EC, "Поиск по названию", scenario="Ё и регистр")
def test_yo_and_case(svc, events):
    svc.world.person("Пётр Чаадаев", "1794", "1856")
    svc.world.person("Иммануил Кант", "1724", "1804")
    body, rid = svc.catalog_ok({"q": "ПЕТР"})
    assert body["total"] == 1
    assert labels(body) == ["Пётр Чаадаев"]
    assert listed(events, rid)["q_len"] == 4


@pytest.mark.parametrize("blank", ["", "   ", "\t "])
@req(EC, "Поиск по названию", invariant="пустая строка поиска или из пробелов — без поиска")
def test_blank_query_means_no_search(svc, events, blank):
    svc.world.base()
    body, rid = svc.catalog_ok({"q": blank})
    assert body["total"] == 5 and body["sort"] == "label"
    event = listed(events, rid)
    assert event["filters"] == [] and event["q_len"] == 0 and event["sort"] == "label"


# --- Фильтры справочника --------------------------------------------------------------------


@req(EC, "Фильтры справочника", scenario="Тип с подтипом")
def test_type_includes_subtypes(svc, events):
    w = svc.world
    revolution = w.thing("event", "Славная революция", "1688")
    answer = w.thing("idea_event", "Ответ Канта Юму", "1783")
    w.person("Иммануил Кант", "1724", "1804")
    body, rid = svc.catalog_ok({"type": "event"})
    assert body["total"] == 2
    assert {i["id"] for i in body["items"]} == {revolution, answer}
    assert "Иммануил Кант" not in labels(body)
    assert listed(events, rid)["filters"] == ["type"]


@req(EC, "Фильтры справочника", scenario="Несколько типов")
def test_several_types(svc, events):
    svc.world.base()
    body, rid = svc.catalog_ok([("type", "person"), ("type", "work")])
    assert body["total"] == 3
    assert sorted(labels(body)) == sorted(["Иммануил Кант", "Дэвид Юм", "Критика чистого разума"])
    assert listed(events, rid)["filters"] == ["type"]


@req(EC, "Фильтры справочника", scenario="Эпоха и тип")
def test_epoch_and_type(svc, events):
    w = svc.world.epochs_and_people()
    body, rid = svc.catalog_ok({"type": "person", "epoch": w["enl"]})
    assert body["total"] == 2
    assert sorted(labels(body)) == sorted(["Дэвид Юм", "Иммануил Кант"])
    assert "Рене Декарт" not in labels(body)
    assert listed(events, rid)["filters"] == ["epoch", "type"]


@req(EC, "Фильтры справочника", scenario="Раздел через упоминание")
def test_textbook_by_mention(svc, events):
    w = svc.world
    w.source(TEXTBOOK_N, "Учебник N")
    kant = w.person("Иммануил Кант", "1724", "1804")
    w.person("Джордж Беркли", "1685", "1753")
    w.mention(kant, TEXTBOOK_N)
    body, rid = svc.catalog_ok({"textbook": TEXTBOOK_N})
    assert "Иммануил Кант" in labels(body)
    assert "Джордж Беркли" not in labels(body)
    assert listed(events, rid)["filters"] == ["textbook"]


@req(EC, "Фильтры справочника", scenario="Раздел через подтверждение абзацем")
def test_textbook_by_evidence(svc, events):
    w = svc.world
    w.source(TEXTBOOK_N, "Учебник N")
    w.source("s_other", "Другой источник")
    locke = w.person("Джон Локк", "1632", "1704")
    innate = w.thing("concept", "врождённые идеи")
    w.person("Джордж Беркли", "1685", "1753")
    w.confirmed(
        locke,
        "criticizes",
        innate,
        paragraph="pN1",
        text="Локк критикует врождённые идеи",
        source=TEXTBOOK_N,
        attributed_to="s_other",
    )
    body, rid = svc.catalog_ok({"textbook": TEXTBOOK_N})
    assert sorted(labels(body)) == sorted(["Джон Локк", "врождённые идеи"])
    event = listed(events, rid)
    assert event["filters"] == ["textbook"] and event["total"] == 2


@req(EC, "Фильтры справочника", invariant="регион спрашивается только для фильтра по разделу")
def test_region_only_for_textbook(svc, events):
    svc.world.base()
    svc.catalog_ok({"q": "кант"}, region="DE")
    assert svc.library_calls == []
    _, rid = svc.catalog_ok({"textbook": TEXTBOOK_N}, region="DE")
    assert [c["region"] for c in svc.library_calls] == ["DE"]
    assert listed(events, rid)["filters"] == ["textbook"]


# --- Проверка параметров справочника ----------------------------------------------------------

BOUNDS = [
    # (имя, параметры, статус, kind, reason)
    ("q200", {"q": "щ" * 200}, 200, None, None),
    ("q201", {"q": "щ" * 201}, 400, "bad_query", "query_too_long"),
    ("q200_trimmed", {"q": "  " + "щ" * 200 + "  "}, 200, None, None),
    ("limit60", {"limit": "60"}, 200, None, None),
    ("limit61", {"limit": "61"}, 400, "bad_query", "limit"),
    ("limit0", {"limit": "0"}, 400, "bad_query", "limit"),
    ("limit_nan", {"limit": "abc"}, 400, "bad_query", "limit"),
    ("page0", {"page": "0"}, 400, "bad_query", "page"),
    ("page_nan", {"page": "x"}, 400, "bad_query", "page"),
    ("page99", {"page": "99"}, 200, None, None),
    ("sort_rank", {"sort": "rank"}, 400, "bad_query", "sort"),
    ("sort_relevance", {"sort": "relevance"}, 200, None, None),
    ("type_dragon", {"type": "dragon"}, 400, "unknown_type", "unknown_type"),
    ("epoch_kant", {"epoch": "<kant>"}, 400, "unknown_epoch", "unknown_epoch"),
    ("epoch_missing", {"epoch": "e_000000000000"}, 400, "unknown_epoch", "unknown_epoch"),
    ("textbook_unknown", {"textbook": "s_unknown"}, 400, "unknown_textbook", "unknown_textbook"),
]


@pytest.mark.parametrize(("name", "params", "status", "kind", "reason"), BOUNDS)
@req(EC, "Проверка параметров справочника", scenario="Границы параметров")
def test_parameter_bounds(svc, events, name, params, status, kind, reason):
    w = svc.world.base()
    params = {k: (w["kant"] if v == "<kant>" else v) for k, v in params.items()}
    first_page, _ = svc.catalog_ok()
    events.clear()
    response, rid = svc.get(params=params)
    assert response.status_code == status, response.text
    body = response.json()
    if status == 400:
        assert body["kind"] == kind
        rejected = events.where(REJECTED, request_id=rid)
        assert len(rejected) == 1 and rejected[0]["reason"] == reason
        assert events.where(LISTED, request_id=rid) == []
        return
    assert events.where(REJECTED, request_id=rid) == []
    event = listed(events, rid)
    if name.startswith("q200"):
        assert body["total"] == 0 and event["total"] == 0
    elif name == "page99":
        assert body["items"] == [] and body["total"] == 5
        assert body["facets"] == first_page["facets"]
        assert event["returned"] == 0 and event["page"] == 99 and event["total"] == 5
    elif name == "sort_relevance":
        assert body["sort"] == "label" and event["sort"] == "label"
    elif name == "limit60":
        assert body["limit"] == 60 and len(body["items"]) == 5


@req(EC, "Проверка параметров справочника", invariant="эпоха проверяется после перенаправления")
def test_epoch_after_redirect(svc, events):
    w = svc.world.epochs_and_people()
    dup = svc.world.thing("epoch", "Эпоха Просвещения", "1680–1800")
    svc.onto.entities.merge(w["enl"], dup)
    body, rid = svc.catalog_ok({"type": "person", "epoch": dup})
    assert sorted(labels(body)) == sorted(["Дэвид Юм", "Иммануил Кант"])
    assert listed(events, rid)["filters"] == ["epoch", "type"]


# --- Счётчики справочника -------------------------------------------------------------------


@req(EC, "Счётчики справочника", scenario="Счётчики при поиске")
def test_facets_with_search(svc, events):
    w = svc.world
    w.thing("work", "Критика чистого разума", "1781")
    w.thing("work", "Критика практического разума", "1788")
    w.thing("group", "Критицизм")
    w.person("Иммануил Кант", "1724", "1804")
    body, rid = svc.catalog_ok({"q": "крит", "type": "work"})
    assert body["total"] == 2
    assert body["facets"]["types"] == {"work": 2, "group": 1}
    assert listed(events, rid)["total"] == 2


@req(EC, "Счётчики справочника", scenario="Сумма счётчиков")
def test_facets_sum(svc, events):
    svc.world.base()
    body, rid = svc.catalog_ok()
    assert body["facets"]["types"] == {"person": 2, "concept": 1, "work": 1, "epoch": 1}
    assert sum(body["facets"]["types"].values()) == body["total"] == 5
    assert listed(events, rid)["total"] == 5


@req(EC, "Счётчики справочника", scenario="Счётчики эпох")
def test_epoch_facets(svc, events):
    w = svc.world.epochs_and_people()
    body, rid = svc.catalog_ok({"type": "person", "epoch": w["enl"]})
    assert body["facets"]["epochs"] == [
        {"id": w["sci"], "label": "Научная революция", "count": 1},
        {"id": w["enl"], "label": "Просвещение", "count": 2},
    ]
    assert listed(events, rid)["filters"] == ["epoch", "type"]


@req(EC, "Счётчики справочника", invariant="эпохи без датировки — в конце, внутри — по названию")
def test_epoch_facets_order_undated_last(svc, events):
    w = svc.world
    baroque = w.thing("epoch", "Барокко")
    antiquity = w.thing("epoch", "Античность")
    enl = w.thing("epoch", "Просвещение", "1680–1800")
    sci = w.thing("epoch", "Научная революция", "1543–1687")
    hume = w.person("Дэвид Юм", "1711", "1776")
    w.belongs(hume, baroque)
    w.belongs(hume, antiquity)
    w.belongs(hume, enl)
    w.belongs(hume, sci)
    body, rid = svc.catalog_ok({"type": "person"})
    assert [e["id"] for e in body["facets"]["epochs"]] == [sci, enl, antiquity, baroque]
    assert all(e["count"] == 1 for e in body["facets"]["epochs"])
    assert listed(events, rid)["filters"] == ["type"]


@req(EC, "Счётчики справочника", invariant="без фильтра типа сумма facets.types равна total")
def test_facets_sum_invariant(svc, events):
    rng = random.Random(20261125)
    w = svc.world
    w.source(TEXTBOOK_N, "Учебник N")
    epochs = [
        w.thing("epoch", "Научная революция", "1543–1687"),
        w.thing("epoch", "Просвещение", "1680–1800"),
    ]
    kinds = ["person", "concept", "work", "event", "idea_event", "group", "term", "place"]
    made = []
    for i in range(40):
        kind = rng.choice(kinds)
        name = f"{rng.choice(['Альфа', 'Бета', 'Гамма', 'Дельта'])} {i}"
        if kind == "person":
            birth = rng.randint(1500, 1780)
            made.append(w.person(name, str(birth), str(birth + rng.randint(20, 80))))
        elif kind in ("work", "event", "idea_event"):
            made.append(w.thing(kind, name, str(rng.randint(1500, 1850))))
        else:
            made.append(w.thing(kind, name))
    for a, b in zip(made[::2], made[1::2], strict=False):
        same_type = svc.onto.entities.get(a)["type"] == svc.onto.entities.get(b)["type"]
        if same_type and rng.random() < 0.5:
            svc.onto.entities.merge(a, b)
    for e in made[:10]:
        w.mention(svc.onto.entities.resolve(e), TEXTBOOK_N)
    queries = [
        {},
        {"q": "альфа"},
        {"q": "а"},
        {"epoch": epochs[1]},
        {"textbook": TEXTBOOK_N},
        {"q": "бета", "epoch": epochs[0]},
        {"page": "3", "limit": "5"},
    ]
    for params in queries:
        body, rid = svc.catalog_ok(params)
        assert sum(body["facets"]["types"].values()) == body["total"], params
        assert all(n > 0 for n in body["facets"]["types"].values()), params
        assert all(e["count"] > 0 for e in body["facets"]["epochs"]), params
        assert "source" not in body["facets"]["types"]
        assert listed(events, rid)["total"] == body["total"]


@req(
    EC,
    "Счётчики справочника",
    invariant="слитые и источники не попадают ни в список, ни в счётчики",
)
def test_merged_and_sources_never_counted(svc, events):
    w = svc.world.base()
    dup = svc.world.person("Иммануил Кант", "1724", "1804")
    svc.onto.entities.merge(w["kant"], dup)
    svc.world.source(TEXTBOOK_R, "Учебник R")
    for params in [
        {},
        {"q": "учебник"},
        {"q": "кант"},
        {"type": "person"},
        {"epoch": w["enlightenment"]},
        {"sort": "date"},
        {"sort": "weight"},
    ]:
        body, rid = svc.catalog_ok(params)
        assert dup not in all_ids(body), params
        assert all(i["type"] != "source" for i in body["items"]), params
        assert "source" not in body["facets"]["types"], params
        assert "Учебник N" not in labels(body) and "Учебник R" not in labels(body)
        assert sum(body["facets"]["types"].values()) <= 5
        if "type" not in params:
            assert sum(body["facets"]["types"].values()) == body["total"]
        assert listed(events, rid)["total"] == body["total"]
    body, _ = svc.catalog_ok({"q": "кант"})
    assert body["total"] == 1


# --- Постраничная выдача --------------------------------------------------------------------


@req(EC, "Постраничная выдача", scenario="Вторая страница")
def test_second_page(svc, events):
    for i in range(30):
        svc.world.thing("concept", f"Понятие {i:02d}")
    first, rid1 = svc.catalog_ok({"page": "1", "limit": "24"})
    second, rid2 = svc.catalog_ok({"page": "2", "limit": "24"})
    assert len(first["items"]) == 24 and len(second["items"]) == 6
    assert not ({i["id"] for i in first["items"]} & {i["id"] for i in second["items"]})
    assert first["total"] == second["total"] == 30
    e1, e2 = listed(events, rid1), listed(events, rid2)
    assert (e1["returned"], e1["page"]) == (24, 1)
    assert (e2["returned"], e2["page"]) == (6, 2)


@req(EC, "Постраничная выдача", invariant="размер страницы по умолчанию 24")
def test_default_page_size(svc, events):
    for i in range(30):
        svc.world.thing("concept", f"Понятие {i:02d}")
    body, rid = svc.catalog_ok()
    assert len(body["items"]) == 24 and body["limit"] == 24 and body["page"] == 1
    assert listed(events, rid)["returned"] == 24


@req(EC, "Постраничная выдача", scenario="Без даты в конце")
def test_sort_by_date_undated_last(svc, events):
    svc.world.base()
    body, rid = svc.catalog_ok({"sort": "date"})
    assert labels(body) == [
        "Просвещение",
        "Дэвид Юм",
        "Иммануил Кант",
        "Критика чистого разума",
        "Причинность",
    ]
    assert listed(events, rid)["sort"] == "date"


def _random_world(svc, seed: int) -> list[str]:
    """Сущности с повторяющимися названиями, годами и значимостью — много равных ключей."""
    rng = random.Random(seed)
    w = svc.world
    words = ["Альфа", "Бета", "Гамма", "Дельта", "Каппа"]
    ids = []
    for _i in range(53):
        name = f"{rng.choice(words)} {rng.choice(['Один', 'Два'])}"
        kind = rng.choice(["work", "event", "concept"])
        dating = str(rng.choice([1600, 1650, 1700])) if kind != "concept" else None
        ids.append(w.thing(kind, name, dating))
    for _ in range(25):
        a, b = rng.sample(ids, 2)
        if svc.onto.entities.get(a)["type"] == "work" and svc.onto.entities.get(b)["type"] in (
            "work",
            "concept",
        ):
            w.relate(a, "criticizes", b)
    return ids


def _sort_key(sort: str):
    def key(item):
        if sort == "label":
            return (item["label"],)
        if sort == "weight":
            return (-item["weight"],)
        start = item["dates"]["from"] if item["dates"] else None
        return (start is None, start or 0, item["label"] if start is None else "")

    return key


def _pages(svc, events, sort: str, limit: int) -> list[dict]:
    paged, page = [], 1
    while True:
        body, rid = svc.catalog_ok({"sort": sort, "limit": str(limit), "page": str(page)})
        assert listed(events, rid)["returned"] == len(body["items"])
        assert listed(events, rid)["page"] == page
        if not body["items"]:
            return paged
        paged.extend(body["items"])
        page += 1


@pytest.mark.parametrize("seed", [1, 7, 42])
@pytest.mark.parametrize("sort", ["label", "date", "weight"])
@pytest.mark.parametrize("limit", [5, 7, 24])
@req(EC, "Постраничная выдача", invariant="порядок устойчив, страницы не пересекаются")
def test_stable_order_and_disjoint_pages(svc, events, seed, sort, limit):
    ids = _random_world(svc, seed)
    whole, _ = svc.catalog_ok({"sort": sort, "limit": "60"})
    assert whole["total"] == len(ids)
    paged = _pages(svc, events, sort, limit)
    assert [i["id"] for i in paged] == [i["id"] for i in whole["items"]]
    assert len({i["id"] for i in paged}) == len(ids)
    key = _sort_key(sort)
    for a, b in itertools.pairwise(paged):
        assert key(a) <= key(b), (sort, a, b)


@pytest.mark.parametrize("seed", [1, 7])
@pytest.mark.parametrize("sort", ["label", "date", "weight"])
@req(EC, "Постраничная выдача", invariant="при равенстве ключа сортировки — по идентификатору")
def test_ties_broken_by_id(svc, events, seed, sort):
    _random_world(svc, seed)
    paged = _pages(svc, events, sort, 7)
    key = _sort_key(sort)
    ties = 0
    for a, b in itertools.pairwise(paged):
        if key(a) == key(b):
            ties += 1
            assert a["id"] < b["id"], (sort, a["label"], a["id"], b["label"], b["id"])
    assert ties > 0  # набор данных действительно содержит равные ключи


# --- Прежний поиск по названию --------------------------------------------------------------


@req(EC, "Прежний поиск по названию", scenario="Точный поиск не изменился")
def test_exact_name_lookup_unchanged(svc, events):
    kant = svc.world.person("Кант", "1724", "1804")
    svc.world.person("Кантор", "1845", "1918")
    response, rid = svc.get("/v1/entities", params={"name": "Кант"})
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list) and len(body) == 1
    assert body[0]["id"] == kant
    assert set(body[0]) == {"id", "type", "primary", "names"}
    assert events.where(LISTED, request_id=rid) == []
    completed = events.where("http.request.completed", request_id=rid)
    assert [e["route"] for e in completed] == ["/v1/entities"]


# --- Справочник и закрытые источники ----------------------------------------------------------


@pytest.fixture
def closed_world(svc):
    w = svc.world
    w.source(TEXTBOOK_R, "Учебник R")
    kant = w.person("Иммануил Кант", "1724", "1804")
    w.mention(kant, TEXTBOOK_R)
    return {"kant": kant}


@req(EC, "Справочник и закрытые источники", scenario="Учебник закрыт для региона")
def test_closed_textbook(svc, events, closed_world):
    body, rid = svc.catalog_ok({"textbook": TEXTBOOK_R, "q": "кант"}, region="DE")
    assert body["items"] == []
    assert body["total"] == 0
    assert body["facets"] == {"types": {}, "epochs": []}
    assert body["textbook_closed"] is True
    assert listed(events, rid)["textbook_closed"] is True
    # Тот же учебник в РФ открыт (контроль: пустота — от закрытия, а не от данных).
    body, rid = svc.catalog_ok({"textbook": TEXTBOOK_R, "q": "кант"}, region="RU")
    assert labels(body) == ["Иммануил Кант"] and body["textbook_closed"] is False
    assert listed(events, rid)["textbook_closed"] is False


@req(EC, "Справочник и закрытые источники", scenario="Сущность видна вне РФ")
def test_entity_visible_outside_ru(svc, events, closed_world):
    body, rid = svc.catalog_ok({"q": "кант"}, region="DE")
    assert labels(body) == ["Иммануил Кант"]
    assert listed(events, rid)["textbook_closed"] is False


PHRASE = "синтетические суждения a priori возможны"


@pytest.mark.parametrize("region", [None, "DE", "RU"])
@req(EC, "Справочник и закрытые источники", scenario="Текст абзаца не попадает в ответ")
def test_paragraph_text_not_in_body(svc, events, closed_world, region):
    w = svc.world
    judgments = w.thing("concept", "Синтетические суждения")
    w.confirmed(
        closed_world["kant"],
        "criticizes",
        judgments,
        paragraph="pR1",
        text=f"Кант утверждает: {PHRASE}.",
        source=TEXTBOOK_R,
    )
    w.describe(closed_world["kant"], "Немецкий философ")
    for params in [{}, {"q": "кант"}, {"textbook": TEXTBOOK_R}, {"q": "синтетические"}]:
        response, rid = svc.get(params=params, region=region)
        assert response.status_code == 200
        assert PHRASE not in response.text, params
        assert "a priori" not in response.text, params
        listed(events, rid)


CLOSED_COMBOS = [
    {},
    {"q": "кант"},
    {"type": "person"},
    {"type": "concept"},
    {"epoch": "<enl>"},
    {"sort": "date"},
    {"sort": "weight", "page": "2", "limit": "1"},
    {"q": "кант", "type": "person", "epoch": "<enl>", "sort": "relevance"},
]


@pytest.mark.parametrize("combo", CLOSED_COMBOS)
@pytest.mark.parametrize("region", [None, "DE", "ru-x"])
@req(EC, "Справочник и закрытые источники", invariant="закрытый учебник: пусто при любых фильтрах")
def test_closed_textbook_empty_for_any_filters(svc, events, closed_world, combo, region):
    enl = svc.world.thing("epoch", "Просвещение", "1680–1800")
    params = {k: (enl if v == "<enl>" else v) for k, v in combo.items()}
    body, rid = svc.catalog_ok({**params, "textbook": TEXTBOOK_R}, region=region)
    assert body["items"] == [] and body["total"] == 0
    assert body["facets"] == {"types": {}, "epochs": []}
    assert body["textbook_closed"] is True
    event = listed(events, rid)
    assert event["textbook_closed"] is True and event["total"] == 0


# --- Свежесть справочника -----------------------------------------------------------------


@req(EC, "Свежесть справочника", scenario="Снимок переиспользуется")
def test_snapshot_reused(svc, events):
    svc.world.base()
    first, rid1 = svc.catalog_ok()
    second, rid2 = svc.catalog_ok()
    assert first == second
    built = events.of(BUILT)
    assert len(built) == 1 and built[0]["reason"] == "first"
    assert listed(events, rid1)["snapshot"] == "fresh"
    assert listed(events, rid2)["snapshot"] == "cached"


@req(EC, "Свежесть справочника", scenario="Внутри окна и после")
def test_stale_window(svc, events, clock):
    svc.world.base()
    svc.catalog_ok()  # снимок собран в момент t
    clock.advance(seconds=1)
    svc.world.person("Иоганн Фихте", "1762", "1814")
    clock.advance(seconds=4)  # t+5
    body, rid = svc.catalog_ok({"q": "фихте"})
    assert body["total"] == 0
    assert listed(events, rid)["snapshot"] == "stale"
    assert events.where(BUILT, reason="changed") == []
    clock.advance(seconds=11)  # t+16
    body, rid = svc.catalog_ok({"q": "фихте"})
    assert body["total"] == 1 and labels(body) == ["Иоганн Фихте"]
    assert listed(events, rid)["snapshot"] == "fresh"
    changed = events.where(BUILT, reason="changed")
    assert len(changed) == 1 and changed[0]["request_id"] == rid


@pytest.mark.parametrize(
    ("age", "changed", "status"),
    [
        (0.0, False, "cached"),
        (100.0, False, "cached"),
        (14.9, True, "stale"),
        (15.0, True, "fresh"),
        (15.1, True, "fresh"),
    ],
)
@req(EC, "Свежесть справочника", invariant="таблица fresh/cached/stale по окну 15 секунд")
def test_snapshot_status_table(svc, events, clock, age, changed, status):
    svc.world.base()
    svc.catalog_ok()
    if changed:
        svc.world.thing("concept", "Новое понятие")
    clock.advance(seconds=age)
    _, rid = svc.catalog_ok()
    assert listed(events, rid)["snapshot"] == status
    rebuilt = events.where(BUILT, request_id=rid)
    if status == "fresh":
        assert len(rebuilt) == 1 and rebuilt[0]["reason"] == "changed"
    else:
        assert rebuilt == []


@pytest.mark.parametrize(
    "change",
    ["entity", "name", "statement", "merge", "reject"],
)
@req(EC, "Свежесть справочника", invariant="изменения базы видны не позже окна")
def test_changes_visible_after_window(svc, events, clock, change):
    w = svc.world.base()
    extra = svc.world.thing("concept", "Опыт")
    st = svc.world.belongs(extra, w["enlightenment"])
    before, _ = svc.catalog_ok()
    if change == "entity":
        svc.world.thing("concept", "Рассудок")
    elif change == "name":
        svc.world.variant(w["hume"], "Hume")
    elif change == "statement":
        svc.world.relate(w["kant"], "criticizes", w["causality"])
    elif change == "merge":
        svc.onto.entities.merge(w["kant"], svc.world.person("Кант И.", "1724", "1804"))
    elif change == "reject":
        svc.onto.statements.reject(st, "operator")
    clock.advance(seconds=15)
    after, rid = svc.catalog_ok({"q": "hume"} if change == "name" else None)
    assert listed(events, rid)["snapshot"] == "fresh"
    if change == "entity":
        assert after["total"] == before["total"] + 1
    elif change == "name":
        assert [(i["label"], i["matched_name"]) for i in after["items"]] == [("Дэвид Юм", "Hume")]
    elif change == "statement":
        assert (
            by_label(after)["Иммануил Кант"]["weight"]
            == by_label(before)["Иммануил Кант"]["weight"] + 1
        )
    elif change == "merge":
        assert after["total"] == before["total"]  # дубль создан и сразу слит
    elif change == "reject":
        assert by_label(after)["Опыт"]["epochs"] == []
        assert by_label(before)["Опыт"]["epochs"][0]["basis"] == "explicit"


@req(EC, "Свежесть справочника", scenario="Карта без окна")
def test_map_without_window(svc, events, clock):
    w = svc.world.base()
    svc.catalog_ok()
    response, _ = svc.get("/v1/map")
    assert response.status_code == 200
    statement = svc.world.relate(w["kant"], "influenced_by", w["hume"])
    response, rid = svc.get("/v1/map")
    assert response.status_code == 200
    assert statement in {link["id"] for link in response.json()["links"]}
    changed = events.where(BUILT, request_id=rid)
    assert len(changed) == 1 and changed[0]["reason"] == "changed"
    assert events.where("knowledge.map.built", request_id=rid)


@req(
    EC,
    "Свежесть справочника",
    invariant="событие пересборки с полями entities, statements, took_ms",
)
def test_snapshot_built_fields(svc, events):
    svc.world.base()
    _, rid = svc.catalog_ok()
    built = events.one(BUILT)
    assert built["request_id"] == rid and built["reason"] == "first"
    with svc.onto.statements.engine.begin() as conn:
        statements = conn.scalar(select(func.count()).select_from(t.statements))
    assert isinstance(built["entities"], int) and built["entities"] >= 5
    assert built["statements"] == statements
    assert isinstance(built["took_ms"], int | float) and built["took_ms"] >= 0


# --- инварианты журнала и модели ---------------------------------------------------------------

HOSTILE = [
    "Чаадаев",
    "чаадаев",
    "<script>alert(1)</script>",
    "Иммануил",
    "' OR 1=1 --",
    "ПЁТР",
    "кан",
    "a" * 201,
    "%00‮",
]


@req(EC, "Список справочника", invariant="события справочника — только id, коды и числа")
def test_journal_has_only_ids_codes_numbers(svc, events, clock):
    w = svc.world.base()
    svc.world.person("Пётр Чаадаев", "1794", "1856")
    svc.world.source(TEXTBOOK_R, "Учебник R")
    names = []
    with svc.onto.statements.engine.begin() as conn:
        names = [r for r in conn.scalars(select(t.names.c.text))]
    for i, q in enumerate(HOSTILE):
        params = {"q": q}
        if i % 3 == 0:
            params["textbook"] = TEXTBOOK_R
        if i % 4 == 0:
            params["epoch"] = w["enlightenment"]
        svc.get(params=params, region="DE" if i % 2 else "RU")
        clock.advance(seconds=20)
        svc.world.thing("concept", f"Понятие {i}")
    svc.get(params={"type": "dragon"})
    svc.get(params={"epoch": "<script>"})
    checked = [
        e for e in events.items if e.name.startswith("knowledge.catalog.") or e.name == BUILT
    ]
    assert len([e for e in checked if e.name == LISTED]) >= 7
    assert any(e.name == REJECTED for e in checked)
    allowed_strings = {
        "fresh",
        "cached",
        "stale",
        "first",
        "changed",
        "label",
        "date",
        "weight",
        "relevance",
        "query_too_long",
        "limit",
        "page",
        "sort",
        "unknown_type",
        "unknown_epoch",
        "unknown_textbook",
        "q",
        "type",
        "epoch",
        "textbook",
        "knowledge",
    }
    for e in checked:
        for key, value in e.fields.items():
            if key == "request_id":
                continue
            values = value if isinstance(value, list) else [value]
            for v in values:
                assert isinstance(v, bool | int | float | str), (e.name, key, v)
                if isinstance(v, str):
                    assert v in allowed_strings, (e.name, key, v)
        dumped = json.dumps(e.fields, ensure_ascii=False)
        for text in [*HOSTILE, *names, VISITOR_ADDRESS, "RU", "DE"]:
            assert text not in dumped or text in allowed_strings, (e.name, text)


@req(EC, "Список справочника", invariant="filters — отсортированный список имён без значений")
def test_filters_sorted_names(svc, events):
    w = svc.world.base()
    params = [
        ("textbook", TEXTBOOK_N),
        ("type", "person"),
        ("type", "work"),
        ("q", "кант"),
        ("epoch", w["enlightenment"]),
    ]
    _, rid = svc.catalog_ok(params)
    assert listed(events, rid)["filters"] == ["epoch", "q", "textbook", "type"]


@req(EC, "Список справочника", invariant="справочник не вызывает модель")
def test_catalog_never_calls_model(svc, events, clock):
    w = svc.world.base()
    svc.world.describe(w["kant"], "Описание", generated=True)
    params_set = [
        {},
        {"q": "кант"},
        {"sort": "weight"},
        {"type": "concept"},
        {"epoch": w["enlightenment"]},
        {"textbook": TEXTBOOK_N},
        {"page": "9"},
        {"q": "x" * 300},
        {"type": "dragon"},
    ]
    rids = []
    for params in params_set:
        _, rid = svc.get(params=params)
        rids.append(rid)
        clock.advance(seconds=20)
    assert svc.llm_calls == []
    assert not [e.name for e in events.items if e.name.startswith("llm.")]
    for rid in rids:
        assert (
            len(events.where(LISTED, request_id=rid) + events.where(REJECTED, request_id=rid)) == 1
        )
