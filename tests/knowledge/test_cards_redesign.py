"""Требования entity-cards изменения redesign-entity-cards: сценарии и инварианты сервера.

Тесты написаны по дельте ``openspec/changes/redesign-entity-cards/specs/entity-cards``. Карточка
запрашивается по HTTP (``GET /v1/entities/{id}/card``) с ``X-Request-Id``; журнал —
``knowledge.card.served`` этого ``request_id``.
"""

from __future__ import annotations

import itertools
import json

import pytest
from fastapi.testclient import TestClient

from philograph.knowledge.app import build_app
from philograph.knowledge.cards import Cards
from philograph.knowledge.dates import parse
from philograph.knowledge.polities import PolityLayer
from philograph.knowledge.registry_data import ENTITY_TYPES, RELATIONS
from philograph.knowledge.statements import Attribution, Provenance

from .test_cards_redesign_unit import _artifact

req = pytest.mark.req
EC = "entity-cards"
SERVED = "knowledge.card.served"
REQUEST_IDS = itertools.count(1)
MARKS = ("verified", "sourced", "generated", "disputed")


def letters(text: str) -> str:
    """Название из одних букв: имена персон проверяются как имена (цифры и «_» не допускаются)."""
    table = {ord(c): chr(0x430 + i) for i, c in enumerate("0123456789")}
    return "".join(c for c in text.translate(table) if c.isalpha() or c == " ").strip().title()


def legacy_person(onto, label: str, birth: str, death: str) -> str:
    """Персона с названием, которое правила названий уже не пропустят (данные, записанные до
    правил): создаётся с допустимым именем, затем название меняется в базе."""
    from philograph.knowledge import schema as t
    from philograph.knowledge.entities import normalize

    pid = onto.person("Прежняя Запись", birth, death)
    with onto.statements.engine.begin() as conn:
        conn.execute(
            t.names.update()
            .where(t.names.c.entity_id == pid)
            .values(text=label, normalized=normalize(label))
        )
    return pid


def src(who: str = "s_a") -> list[Attribution]:
    return [Attribution("source", who)]


class CardSvc:
    """Сервис знаний с настоящим маршрутом карточки; ``onto`` — данные теста."""

    def __init__(self, onto, *, events, polities=None, mentions=None, on_view=None) -> None:
        self.onto = onto
        self.events = events
        self.w = onto.statements
        self.cards = Cards(onto.statements, mentions, None, on_view, polities=polities)
        self.client = TestClient(
            build_app(onto.statements, cards=self.cards, mentions=mentions),
            raise_server_exceptions=False,
        )

    def get(self, entity_id: str, **params) -> tuple[dict, str]:
        rid = f"rid-card-{next(REQUEST_IDS)}"
        response = self.client.get(
            f"/v1/entities/{entity_id}/card", params=params, headers={"X-Request-Id": rid}
        )
        assert response.status_code == 200, response.text
        card = response.json()
        # Журнал каждого запроса: одно событие, его поля равны ответу (sections, rows, empty,
        # layout, inferred); запрос карточки не пишет ничего лишнего.
        [event] = self.events.where(SERVED, request_id=rid)
        rows = [r for s in card["sections"] for r in s["rows"]]
        assert (event["entity_id"], event["type"]) == (card["id"], card["type"])
        assert (event["sections"], event["rows"]) == (len(card["sections"]), len(rows))
        assert (event["layout"], event["empty"]) == (card["layout"], card["empty"])
        assert event["inferred"] == sum(1 for r in rows if r["inferred"])
        return card, rid

    def served(self, events, rid: str) -> dict:
        [event] = events.where(SERVED, request_id=rid)
        return event

    def place(self, name: str, lat: float | None = None, lon: float | None = None) -> str:
        place = self.onto.thing("place", name)
        if lat is not None:
            self.w.add(place, "coordinates", value={"lat": lat, "lon": lon}, attributions=src())
        return place

    def lived(self, person: str, place: str, role: str | None = None, **kw) -> str:
        qualifiers = {"place_role": role} if role else {}
        return self.w.add(
            person, "lived_in", obj=place, qualifiers=qualifiers, attributions=src(), **kw
        )


@pytest.fixture(autouse=True)
def imported_statements_are_sourced(onto):
    """Данные теста — как импортированные: без явного статуса и происхождения утверждение
    с атрибуцией источника «по источникам» (ручная запись по умолчанию стала бы проверенной)."""
    original = onto.statements.add

    def add(subject, type_, **kw):
        sourced = any(a.who_kind == "source" for a in kw.get("attributions") or [])
        plain = "provenance" not in kw and not kw.get("evidence")
        if sourced and plain and kw.get("status") in (None, "sourced"):
            kw["provenance"] = Provenance("imported")
        return original(subject, type_, **kw)

    onto.statements.add = add
    yield
    onto.statements.add = original


@pytest.fixture
def cs(onto, clock, events) -> CardSvc:
    return CardSvc(onto, events=events)


def section(card: dict, code: str) -> dict:
    [found] = [s for s in card["sections"] if s["code"] == code]
    return found


def codes(card: dict) -> list[str]:
    return [s["code"] for s in card["sections"]]


def all_rows(card: dict) -> list[dict]:
    return [r for s in card["sections"] for r in s["rows"]]


def prussia_layer(tmp_path):
    return PolityLayer(
        _artifact(
            tmp_path / "polities.sqlite",
            [
                ("prussia", "Королевство Пруссия", 1701, 1918, (19, 53, 23, 56), 10.0),
                ("big", "Большая держава", 1600, 1800, (0, 40, 40, 70), 1000.0),
                ("england", "Королевство Англия", 1600, 1707, (-6, 50, 2, 56), 20.0),
            ],
        )
    )


# --- Карточка персоны: сценарии ------------------------------------------------------------


@req(EC, "Карточка персоны", scenario="Шапка и сводка Локка")
def test_locke_header_and_summary(onto, tmp_path, events):
    svc = CardSvc(onto, events=events, polities=prussia_layer(tmp_path))
    locke = onto.person("Локк", "1632", "1704")
    onto.statements.add(locke, "person_role", value="philosopher", attributions=src())
    london = svc.place("Лондон", 51.51, -0.13)
    rington = svc.place("Рингтон")
    svc.lived(locke, london, "activity", status="verified")
    svc.lived(locke, rington, "birth")
    card, rid = svc.get(locke)
    assert card["layout"] == "person"
    summary = card["summary"]
    assert summary["years"] == "1632–1704"
    assert summary["roles"][0]["value"] == "philosopher"
    assert summary["place"]["label"] == "Лондон"
    assert summary["place"]["geo"] == {"lat": 51.51, "lon": -0.13}
    assert summary["polity"]["name"] == "Королевство Англия" and summary["polity"]["year"] == 1632
    assert card["where_to_read"] == []
    assert "lifespan" not in {r["type"] for r in all_rows(card)}
    event = svc.served(events, rid)
    assert (event["type"], event["layout"], event["empty"], event["polity"]) == (
        "person",
        "person",
        False,
        "found",
    )


@req(EC, "Карточка персоны", scenario="Где жил свёрнут")
def test_places_inline_collapsed(cs, onto, events):
    p = onto.person("Странник", "1700", "1760")
    names = ["Аахен", "Бонн", "Вена", "Грац", "Дрезден"]
    for i, name in enumerate(names):
        cs.lived(p, cs.place(name), "residence" if i == 4 else None)
    card, rid = cs.get(p)
    places = section(card, "places")
    assert (places["display"], places["visible"], places["total"]) == ("inline", 3, 5)
    assert places["rows"][0]["label"] == "Дрезден"  # основное место первым
    assert {r["label"] for r in places["rows"]} == set(names)
    event = cs.served(events, rid)
    assert event["type"] == "person" and event["rows"] == len(all_rows(card))
    assert len(events.where(SERVED, request_id=rid)) == 1


@req(EC, "Карточка персоны", scenario="Влияние в обе стороны без повторов")
def test_influence_both_ways_without_repeats(cs, onto, events):
    kant = onto.person("Кант", "1724", "1804")
    hume = onto.person("Юм", "1711", "1776")
    knutzen = onto.person("Кнутцен", "1713", "1751")
    fichte = onto.person("Фихте", "1762", "1814")
    schelling = onto.person("Шеллинг", "1775", "1854")
    weak = onto.statements.add(kant, "influenced_by", obj=hume, attributions=src())
    strong = onto.statements.add(
        kant, "criticizes", obj=hume, attributions=src(), status="verified"
    )
    onto.statements.add(kant, "studied_with", obj=knutzen, attributions=src())
    onto.statements.add(fichte, "influenced_by", obj=kant, attributions=src())
    onto.statements.add(schelling, "influenced_by", obj=kant, attributions=src())
    card, rid = cs.get(kant)
    by = section(card, "influenced_by")
    [hume_row] = by["rows"]
    assert hume_row["label"] == "Юм" and hume_row["mark"] == "verified"
    assert len(hume_row["also"]) == 1
    assert {hume_row["statement_id"], *hume_row["also"]} == {weak, strong}
    assert sorted(r["label"] for r in section(card, "influenced")["rows"]) == [
        "Фихте",
        "Шеллинг",
    ]
    assert [r["label"] for r in section(card, "teachers")["rows"]] == ["Кнутцен"]
    assert "influence" not in codes(card)
    event = cs.served(events, rid)
    assert (event["sections"], event["rows"]) == (len(card["sections"]), len(all_rows(card)))


@req(EC, "Карточка персоны", scenario="Только годы жизни")
def test_only_lifespan(cs, onto, events):
    hobbes = onto.person("Гоббс", "1588", "1679")
    card, rid = cs.get(hobbes)
    assert card["sections"] == [] and card["empty"] is False
    assert card["summary"]["years"] == "1588–1679"
    row = card["summary"]["years_row"]
    assert row["mark"] == "verified" and row["type"] == "lifespan"
    assert card["legend"] == [row["mark"]]
    event = cs.served(events, rid)
    assert (event["sections"], event["rows"], event["empty"]) == (0, 0, False)


def lifespan_statement(onto, person: str) -> str:
    [found] = [
        s["id"]
        for s in onto.statements.about(person, derived=False)
        if s["type"] == "lifespan" and s["direction"] == "out"
    ]
    return found


@req(EC, "Карточка персоны", scenario="Сгенерированная роль и годы помечены")
def test_generated_role_and_years_marked(cs, onto, events):
    hume = onto.entities.create("person", [("ru", "Юм", "primary")])
    st = onto.statements
    st.add(hume, "person_role", value="philosopher", provenance=Provenance("generated"))
    st.add(
        hume,
        "lifespan",
        value=parse("1711–1776").to_json(),
        attributions=src(),
        provenance=Provenance("imported"),
    )
    card, rid = cs.get(hume)
    summary = card["summary"]
    assert summary["roles"][0]["mark"] == "generated"
    assert summary["years_row"]["mark"] == "sourced"
    assert summary["years"] == "1711–1776"
    assert card["legend"] == ["sourced", "generated"]
    assert card["sections"] == [] and card["empty"] is False
    event = cs.served(events, rid)
    assert (event["type"], event["empty"]) == ("person", False)


@req(
    EC,
    "Карточка персоны",
    invariant="годы сводки: years_row — видимое утверждение lifespan, null без него",
)
def test_years_row_is_the_lifespan_statement_or_null(cs, onto):
    kant = onto.person("Кант", "1724", "1804")
    card, _ = cs.get(kant)
    row = card["summary"]["years_row"]
    assert row["statement_id"] == lifespan_statement(onto, kant)
    assert row["statement_id"] not in {r["statement_id"] for r in all_rows(card)}
    nameless = onto.person("Аноним")
    card, _ = cs.get(nameless)
    assert card["summary"]["years"] is None and card["summary"]["years_row"] is None
    assert card["legend"] == []


@req(
    EC,
    "Природа каждой строки",
    invariant="отметка годов: по шкале статусов, входит в легенду",
)
def test_years_row_mark_follows_status_scale(cs, onto):
    hume = onto.entities.create("person", [("ru", "Юм", "primary")])
    onto.statements.add(
        hume,
        "lifespan",
        value=parse("1711–1776").to_json(),
        attributions=src(),
        provenance=Provenance("generated"),
    )
    card, _ = cs.get(hume)
    assert card["summary"]["years_row"]["mark"] == "generated"
    assert card["legend"] == ["generated"]


# --- Карточка персоны: инварианты ----------------------------------------------------------


ROLE_ORDER = ["activity", "residence", "birth", "death", None]


@req(EC, "Карточка персоны", invariant="основное место: роль, отметка, подтверждения, порядок")
@pytest.mark.parametrize("order", list(itertools.permutations(ROLE_ORDER, 3))[:12])
def test_main_place_by_role(cs, onto, order):
    p = onto.person("Персона", "1700", "1760")
    places = {}
    # Записываем в порядке, обратном ожидаемому, чтобы порядок записи не мог подсказать.
    for role in sorted(order, key=lambda r: ROLE_ORDER.index(r), reverse=True):
        places[role] = cs.place(f"М-{role}")
        cs.lived(p, places[role], role)
    card, _ = cs.get(p)
    best = min(order, key=lambda r: ROLE_ORDER.index(r))
    assert card["summary"]["place"]["label"] == f"М-{best}"
    assert section(card, "places")["rows"][0]["label"] == f"М-{best}"


@req(EC, "Карточка персоны", invariant="основное место: роль, отметка, подтверждения, порядок")
def test_main_place_tie_breaks_by_mark_then_order(cs, onto):
    p = onto.person("Персона", "1700", "1760")
    weak = cs.place("Слабое")
    strong = cs.place("Сильное")
    gen = cs.place("Сгенерированное")
    cs.lived(p, gen, "residence", provenance=Provenance("generated"))
    cs.lived(p, weak, "residence")
    cs.lived(p, strong, "residence", status="verified")
    card, _ = cs.get(p)
    assert [r["label"] for r in section(card, "places")["rows"]] == [
        "Сильное",
        "Слабое",
        "Сгенерированное",
    ]
    # Равные роль и отметка: первым остаётся записанное раньше.
    q = onto.person("Другая", "1700", "1760")
    first, second = cs.place("Первое"), cs.place("Второе")
    cs.lived(q, first, "birth")
    cs.lived(q, second, "birth")
    card, _ = cs.get(q)
    assert card["summary"]["place"]["label"] == "Первое"


@req(EC, "Карточка персоны", invariant="основное место: роль, отметка, подтверждения, порядок")
def test_main_place_tie_breaks_by_evidence_count(cs, onto):
    from philograph.knowledge.statements import Evidence

    p = onto.person("Персона", "1700", "1760")
    plain, backed = cs.place("Без подтверждений"), cs.place("С подтверждением")
    onto.paragraphs["pp1"] = "Он жил в городе С подтверждением."
    cs.lived(p, plain, "residence")
    cs.lived(
        p,
        backed,
        "residence",
        evidence=[Evidence("pp1", "жил в городе", source_id="s_a")],
        provenance=Provenance("extracted"),
    )
    card, _ = cs.get(p)
    assert card["summary"]["place"]["label"] == "С подтверждением"


PERSON_ORDER = [
    "places",
    "influenced_by",
    "influenced",
    "teachers",
    "schools",
    "positions",
    "interests",
    "works",
    "biography",
    "epoch",
    "context",
    "misconceptions",
]


@req(EC, "Карточка персоны", invariant="порядок разделов персоны и их вид показа")
def test_person_section_order_and_display(cs, onto, events):
    p = onto.person("Полная", "1700", "1760")
    other = onto.person("Другой", "1710", "1770")
    school = onto.thing("group", "Школа")
    doctrine = onto.thing("doctrine", "Учение")
    work = onto.thing("work", "Труд", "1750")
    topic = onto.thing("concept", "Тема")
    epoch = onto.thing("epoch", "Эпоха", "1600–1800")
    event = onto.thing("event", "Событие", "1720")
    st = onto.statements
    cs.lived(p, cs.place("Город"), "activity")
    st.add(p, "influenced_by", obj=other, attributions=src())
    st.add(other, "influenced_by", obj=p, attributions=src())
    st.add(p, "studied_with", obj=other, attributions=src())
    st.add(p, "member_of", obj=school, attributions=src())
    st.add(p, "holds", obj=doctrine, attributions=src())
    st.add(work, "author", obj=p, attributions=src())
    st.add(work, "discusses", obj=topic, attributions=src())
    st.add(p, "participated", obj=onto.thing("idea_event", "Идейное событие"), attributions=src())
    st.add(p, "belongs_to_epoch", obj=epoch, attributions=src())
    st.add(event, "stimulated", obj=p, attributions=src())
    card, rid = cs.get(p)
    got = codes(card)
    assert got == [c for c in PERSON_ORDER if c in got]
    assert set(got) >= {
        "places",
        "influenced_by",
        "influenced",
        "teachers",
        "schools",
        "positions",
        "interests",
        "works",
        "biography",
        "epoch",
        "context",
    }
    shape = {c: (s["display"], s["visible"]) for c in got for s in [section(card, c)]}
    assert shape["places"] == ("inline", 3)
    assert shape["influenced_by"] == ("list", 5) and shape["influenced"] == ("list", 5)
    assert shape["interests"] == ("inline", 6) and shape["works"] == ("list", 6)
    assert section(card, "interests")["inferred"] is True
    assert section(card, "works")["rows"][0]["note"] == "1750"
    assert cs.served(events, rid)["layout"] == "person"


@req(EC, "Карточка персоны", invariant="у персоны нет influence, studied_with и «Где читать»")
def test_person_has_no_influence_code_and_no_where(onto, events):
    class Forbidden:
        def where_to_read(self, *a, **k):
            raise AssertionError("указатель упоминаний не должен вызываться у персоны")

    svc = CardSvc(onto, events=events, mentions=Forbidden())
    p = onto.person("Кант", "1724", "1804")
    q = onto.person("Кнутцен", "1713", "1751")
    r = onto.person("Юм", "1711", "1776")
    onto.statements.add(p, "studied_with", obj=q, attributions=src())
    onto.statements.add(q, "studied_with", obj=p, attributions=src())
    onto.statements.add(p, "influenced_by", obj=r, attributions=src())
    for who in (p, q, r):
        card, _ = svc.get(who)
        assert card["where_to_read"] == []
        assert "influence" not in codes(card) and "life" not in codes(card)
        for code in ("influenced_by", "influenced"):
            rows = section(card, code)["rows"] if code in codes(card) else []
            assert all(x["type"] != "studied_with" for x in rows)
    card, _ = svc.get(p)
    assert [x["label"] for x in section(card, "teachers")["rows"]] == ["Кнутцен"]


@req(
    EC,
    "Карточка персоны",
    invariant="не больше одной строки на сущность в местах, влияниях, учителях и трудах",
)
def test_one_row_per_entity(cs, onto):
    p = onto.person("Кант", "1724", "1804")
    hume = onto.person("Юм", "1711", "1776")
    teacher = onto.person("Кнутцен", "1713", "1751")
    pupil = onto.person("Герц", "1747", "1803")
    st = onto.statements
    city = cs.place("Кёнигсберг")
    for role in ("birth", "death", "activity"):
        cs.lived(p, city, role)
    for t in ("influenced_by", "criticizes", "develops"):
        st.add(p, t, obj=hume, attributions=src())
        st.add(hume, t, obj=p, attributions=src())
    st.add(p, "studied_with", obj=teacher, attributions=src())
    st.add(teacher, "studied_with", obj=p, attributions=src())
    st.add(pupil, "studied_with", obj=p, attributions=src())
    work = onto.thing("work", "Критика", "1781")
    st.add(work, "author", obj=p, attributions=src())
    card, _ = cs.get(p)
    for code in ("places", "influenced_by", "influenced", "teachers", "works"):
        ids = [r["entity_id"] for r in section(card, code)["rows"]]
        assert len(ids) == len(set(ids)), (code, ids)
    assert len(section(card, "influenced_by")["rows"][0]["also"]) == 2
    assert len(section(card, "places")["rows"][0]["also"]) == 2


@req(EC, "Карточка персоны", invariant="примечание строки труда — год, если труд датирован")
def test_work_note_is_year_only_when_dated(cs, onto):
    p = onto.person("Автор", "1700", "1760")
    dated = onto.thing("work", "Датированный", "1739")
    undated = onto.thing("work", "Без даты")
    for w in (dated, undated):
        onto.statements.add(w, "author", obj=p, attributions=src())
    card, _ = cs.get(p)
    notes = {r["label"]: r["note"] for r in section(card, "works")["rows"]}
    assert notes == {"Датированный": "1739", "Без даты": None}


# --- К кому относится ---------------------------------------------------------------------


@req(EC, "Выведенные строки", scenario="Только выбранный учебник — все звенья")
def test_source_scope_every_link_of_the_chain(cs, onto, events):
    hume = onto.person("Юм", "1711", "1776")
    berkeley = onto.person("Беркли", "1685", "1753")
    causality = onto.thing("concept", "причинность")
    hume_work = onto.thing("work", "Трактат Юма")
    berkeley_work = onto.thing("work", "Трактат Беркли")
    st = onto.statements
    st.add(hume_work, "discusses", obj=causality, attributions=src("s_t"))
    st.add(hume_work, "author", obj=hume, attributions=src("wikidata"))
    st.add(berkeley_work, "discusses", obj=causality, attributions=src("s_t"))
    st.add(berkeley_work, "author", obj=berkeley, attributions=src("s_t"))
    card, rid = cs.get(causality, attributed_to="s_t")
    labels = [r["label"] for r in section(card, "relates_to")["rows"]]
    assert labels == ["Беркли"]
    assert cs.served(events, rid)["inferred"] == len([r for r in all_rows(card) if r["inferred"]])
    card, _ = cs.get(causality)
    assert sorted(r["label"] for r in section(card, "relates_to")["rows"]) == ["Беркли", "Юм"]


@req(
    EC,
    "Выведенные строки",
    invariant="режим учебника: звено цепочки вне учебника выводов не даёт",
)
def test_source_scope_chain_variants(cs, onto, events):
    locke = onto.person("Локк", "1632", "1704")
    term = onto.thing("term", "tabula rasa")
    concept = onto.thing("concept", "Чистая доска")
    st = onto.statements
    st.add(term, "denotes", obj=concept, attributions=src("s_t"))
    st.add(term, "introduced_by", obj=locke, attributions=src("wikidata"))
    st.add(concept, "definition", value="ум без идей", attributions=src("s_t"))
    # Путь через термин: introduced_by не из учебника — вывода нет; без режима есть.
    card, _ = cs.get(concept, attributed_to="s_t")
    assert "relates_to" not in codes(card)
    card, _ = cs.get(concept)
    assert [r["label"] for r in section(card, "relates_to")["rows"]] == ["Локк"]
    # Связь «термин обозначает понятие» не из учебника — вывода нет и при верном introduced_by.
    other_term = onto.thing("term", "blank slate")
    other_concept = onto.thing("concept", "Пустая доска")
    st.add(other_term, "denotes", obj=other_concept, attributions=src("wikidata"))
    st.add(other_term, "introduced_by", obj=locke, attributions=src("s_t"))
    st.add(other_concept, "definition", value="ум без идей", attributions=src("s_t"))
    card, _ = cs.get(other_concept, attributed_to="s_t")
    assert "relates_to" not in codes(card)
    # Интересы: труд автора из учебника, но discusses не из учебника — интереса нет.
    hume = onto.person("Юм", "1711", "1776")
    work = onto.thing("work", "Трактат")
    kept, dropped, hidden_author = (
        onto.thing("concept", "причинность"),
        onto.thing("concept", "индукция"),
        onto.thing("concept", "привычка"),
    )
    other_work = onto.thing("work", "Статья")
    st.add(work, "author", obj=hume, attributions=src("s_t"))
    st.add(work, "discusses", obj=kept, attributions=src("s_t"))
    st.add(work, "discusses", obj=dropped, attributions=src("wikidata"))
    st.add(other_work, "author", obj=hume, attributions=src("wikidata"))
    st.add(other_work, "discusses", obj=hidden_author, attributions=src("s_t"))
    card, rid = cs.get(hume, attributed_to="s_t")
    assert [r["label"] for r in section(card, "interests")["rows"]] == ["причинность"]
    assert cs.served(events, rid)["inferred"] == 1
    card, _ = cs.get(hume)
    assert {r["label"] for r in section(card, "interests")["rows"]} == {
        "индукция",
        "причинность",
        "привычка",
    }


@req(EC, "К кому относится", scenario="Учение без сторонников, но с трудом")
def test_relates_to_inferred_via_work(cs, onto, events):
    berkeley = onto.person("Беркли", "1685", "1753")
    treatise = onto.thing("work", "Трактат о началах человеческого знания")
    doctrine = onto.thing("doctrine", "Имматериализм")
    onto.statements.add(treatise, "author", obj=berkeley, attributions=src(), status="verified")
    onto.statements.add(treatise, "discusses", obj=doctrine, attributions=src())
    card, rid = cs.get(doctrine)
    assert codes(card) == ["relates_to", "in_works"]
    [row] = section(card, "relates_to")["rows"]
    assert row["inferred"] is True and row["label"] == "Беркли"
    assert row["statement_id"] == f"inferred:relates_to:{berkeley}"
    assert (row["type"], row["status"], row["mark"], row["evidence"]) == (
        "author",
        "sourced",
        "sourced",
        [],
    )
    assert [v["label"] for v in row["via"]] == ["Трактат о началах человеческого знания"]
    [work_row] = section(card, "in_works")["rows"]
    assert work_row["label"] == "Трактат о началах человеческого знания"
    assert work_row["inferred"] is False
    event = cs.served(events, rid)
    assert (event["type"], event["sections"], event["rows"], event["inferred"]) == (
        "doctrine",
        2,
        2,
        1,
    )
    assert event["empty"] is False


@req(EC, "К кому относится", scenario="Прямая строка вытесняет вывод")
def test_direct_row_replaces_inferred(cs, onto, events):
    descartes = onto.person("Декарт", "1596", "1650")
    work = onto.thing("work", "Рассуждение о методе")
    doubt = onto.thing("position", "Методическое сомнение")
    onto.statements.add(descartes, "holds", obj=doubt, attributions=src(), status="verified")
    onto.statements.add(work, "author", obj=descartes, attributions=src())
    onto.statements.add(work, "expresses", obj=doubt, attributions=src())
    card, rid = cs.get(doubt)
    [row] = section(card, "relates_to")["rows"]
    assert (row["label"], row["inferred"], row["mark"]) == ("Декарт", False, "verified")
    assert cs.served(events, rid)["inferred"] == 0


@req(EC, "К кому относится", invariant="набор типов, выводы у понятия, место раздела")
def test_relates_to_term_authors_only_for_concept_and_position_in_order(cs, onto):
    locke = onto.person("Локк", "1632", "1704")
    term = onto.thing("term", "tabula rasa")
    concept = onto.thing("concept", "Чистая доска")
    work = onto.thing("work", "Опыт")
    onto.statements.add(term, "denotes", obj=concept, attributions=src())
    onto.statements.add(term, "introduced_by", obj=locke, attributions=src())
    onto.statements.add(concept, "definition", value="ум без идей", attributions=src())
    card, _ = cs.get(concept)
    assert codes(card)[:2] == ["definitions", "relates_to"]
    [row] = section(card, "relates_to")["rows"]
    assert (row["label"], row["inferred"], row["type"]) == ("Локк", True, "introduced_by")
    assert [v["label"] for v in row["via"]] == ["tabula rasa"]
    # У учения связь через термин не выводится: термин обозначает понятие, а не учение.
    doctrine = onto.thing("doctrine", "Эмпиризм")
    onto.statements.add(work, "discusses", obj=doctrine, attributions=src())
    onto.statements.add(work, "author", obj=locke, attributions=src())
    card, _ = cs.get(doctrine)
    assert codes(card)[0] == "relates_to"
    # Идея без единой строки «К кому относится» получает карточку без раздела.
    plain = onto.thing("doctrine", "Одинокое")
    onto.statements.add(plain, "part_of", obj=doctrine, attributions=src())
    card, _ = cs.get(plain)
    assert "relates_to" not in codes(card)


@req(EC, "К кому относится", invariant="одна строка на персону, прямая вытесняет выведенную")
def test_relates_to_one_row_per_person(cs, onto):
    kant = onto.person("Кант", "1724", "1804")
    idea = onto.thing("position", "Идеализм")
    for i in range(3):
        w = onto.thing("work", f"Труд {i}")
        onto.statements.add(w, "author", obj=kant, attributions=src())
        onto.statements.add(w, "discusses", obj=idea, attributions=src())
    onto.statements.add(kant, "holds", obj=idea, attributions=src())
    onto.statements.add(kant, "advanced", obj=idea, attributions=src())
    card, _ = cs.get(idea)
    rows = section(card, "relates_to")["rows"]
    assert [r["entity_id"] for r in rows] == [kant]
    assert rows[0]["inferred"] is False
    assert len(rows[0]["also"]) == 1  # holds и advanced — одна строка


# --- Выведенные строки --------------------------------------------------------------------


@req(EC, "Выведенные строки", scenario="Интересы Юма")
def test_hume_interests(cs, onto, events):
    hume = onto.person("Юм", "1711", "1776")
    treatise = onto.thing("work", "Трактат о человеческой природе")
    enquiry = onto.thing("work", "Исследование о человеческом познании")
    causality = onto.thing("concept", "причинность")
    induction = onto.thing("concept", "индукция")
    st = onto.statements
    for w in (treatise, enquiry):
        st.add(w, "author", obj=hume, attributions=src(), status="verified")
    st.add(treatise, "discusses", obj=causality, attributions=src(), status="verified")
    st.add(treatise, "discusses", obj=induction, provenance=Provenance("generated"))
    st.add(enquiry, "discusses", obj=causality, attributions=src())
    before = len(st.about(hume, derived=False))
    total_before = len(st.about(causality, derived=False)) + len(st.about(induction, derived=False))
    card, rid = cs.get(hume)
    interests = section(card, "interests")
    assert interests["inferred"] is True and interests["display"] == "inline"
    first, second = interests["rows"]
    assert (first["label"], first["mark"], len(first["via"])) == (
        "причинность",
        "verified",
        2,
    )
    assert (second["label"], second["mark"]) == ("индукция", "generated")
    assert len(st.about(hume, derived=False)) == before
    assert (
        len(st.about(causality, derived=False)) + len(st.about(induction, derived=False))
        == total_before
    )
    assert cs.served(events, rid)["inferred"] == 2


@req(EC, "Выведенные строки", scenario="Отвергнутое звено не даёт вывода")
def test_rejected_link_gives_no_inference(cs, onto, events):
    kant = onto.person("Кант", "1724", "1804")
    work = onto.thing("work", "Критика")
    idea = onto.thing("concept", "Вещь в себе")
    link = onto.statements.add(work, "author", obj=kant, attributions=src())
    onto.statements.add(work, "discusses", obj=idea, attributions=src())
    onto.statements.reject(link, "operator")
    card, rid = cs.get(idea)
    assert "relates_to" not in codes(card)
    assert cs.served(events, rid)["inferred"] == 0
    # Отвергнутое звено «обсуждает» не даёт интереса.
    hume = onto.person("Юм", "1711", "1776")
    treatise = onto.thing("work", "Трактат")
    topic = onto.thing("concept", "привычка")
    onto.statements.add(treatise, "author", obj=hume, attributions=src())
    bad = onto.statements.add(treatise, "discusses", obj=topic, attributions=src())
    onto.statements.reject(bad, "operator")
    card, rid = cs.get(hume)
    assert "interests" not in codes(card)
    assert cs.served(events, rid)["inferred"] == 0


@req(EC, "Выведенные строки", invariant="выведенная строка берётся только из видимых утверждений")
def test_inference_ignores_statements_of_hidden_source(cs, onto):
    kant = onto.person("Кант", "1724", "1804")
    work = onto.thing("work", "Критика")
    idea = onto.thing("concept", "Вещь в себе")
    onto.statements.add(work, "author", obj=kant, attributions=src("s_hidden"))
    onto.statements.add(work, "discusses", obj=idea, attributions=src())
    card, _ = cs.get(idea)
    assert [r["label"] for r in section(card, "relates_to")["rows"]] == ["Кант"]
    onto.statements._set_source_hidden("s_hidden", True)
    card, _ = cs.get(idea)
    assert "relates_to" not in codes(card)


STATUSES = ("verified", "sourced", "generated")
RANK = {"verified": 3, "sourced": 2, "generated": 1}


def _add(st, subj, type_, obj, status, disputed=False):
    attributions = src()
    if disputed:
        attributions.append(Attribution("source", "s_b", stance="disputes"))
    if status == "generated":
        return st.add(
            subj, type_, obj=obj, attributions=attributions, provenance=Provenance("generated")
        )
    return st.add(subj, type_, obj=obj, attributions=attributions, status=status)


@req(EC, "Выведенные строки", invariant="отметка вывода не сильнее самого слабого звена")
@pytest.mark.parametrize("author_status", STATUSES)
@pytest.mark.parametrize("topic_status", STATUSES)
@pytest.mark.parametrize("disputed", [False, True])
def test_inferred_mark_is_weakest_link(cs, onto, author_status, topic_status, disputed):
    person = onto.person("Автор", "1700", "1760")
    work = onto.thing("work", "Труд")
    idea = onto.thing("concept", "Идея")
    st = onto.statements
    _add(st, work, "author", person, author_status)
    _add(st, work, "discusses", idea, topic_status, disputed=disputed)
    weakest = min((author_status, topic_status), key=RANK.get)
    expected = "disputed" if disputed else weakest
    card, _ = cs.get(person)
    [interest] = section(card, "interests")["rows"]
    assert interest["mark"] == expected, (author_status, topic_status, disputed)
    assert interest["status"] == weakest
    assert interest["generated"] == (weakest == "generated")
    card, _ = cs.get(idea)
    [holder] = section(card, "relates_to")["rows"]
    assert holder["mark"] == expected


@req(EC, "Выведенные строки", invariant="выведенная строка — полная строка с прежними полями")
def test_inferred_row_has_all_old_fields(cs, onto):
    person = onto.person("Автор", "1700", "1760")
    idea = onto.thing("concept", "Идея")
    works = [onto.thing("work", f"Труд {i}") for i in range(5)]
    for w in works:
        onto.statements.add(w, "author", obj=person, attributions=src())
        onto.statements.add(w, "discusses", obj=idea, attributions=src())
    card, _ = cs.get(person)
    [row] = section(card, "interests")["rows"]
    legacy = {
        "statement_id", "type", "relation", "inverse", "entity_id", "label", "value",
        "qualifiers", "status", "consensus", "disputed", "disputed_by", "generated",
        "derived", "attributed_to", "attributions", "evidence", "mark", "inferred", "via",
    }  # fmt: skip
    assert legacy <= set(row)
    assert row["statement_id"] == f"inferred:interests:{idea}"
    assert row["derived"] is True and row["inferred"] is True
    assert row["evidence"] == [] and row["attributions"] == [] and row["attributed_to"] == []
    assert row["disputed_by"] == []
    assert len(row["via"]) == 3  # не больше трёх сущностей


@req(
    EC,
    "Выведенные строки",
    invariant="выведенное не пишется в онтологию и не идёт в очередь проверки",
)
def test_inferred_rows_not_written_and_not_queued(onto, events):
    seen: list[list[str]] = []
    svc = CardSvc(onto, events=events, on_view=seen.append)
    hume = onto.person("Юм", "1711", "1776")
    work = onto.thing("work", "Трактат")
    idea = onto.thing("concept", "Скептицизм")
    st = onto.statements
    author = st.add(work, "author", obj=hume, attributions=src())
    topic = st.add(work, "discusses", obj=idea, attributions=src())
    ids = {e: {s["id"] for s in st.about(e, derived=False)} for e in (hume, work, idea)}
    for who in (hume, idea):
        card, _ = svc.get(who)
        assert any(r["inferred"] for r in all_rows(card))
    after = {e: {s["id"] for s in st.about(e, derived=False)} for e in (hume, work, idea)}
    assert after == ids
    sent = [x for batch in seen for x in batch]
    assert sent and not [x for x in sent if str(x).startswith("inferred:")]
    assert set(sent) <= {author, topic}


@req(EC, "Выведенные строки", invariant="интересы: типы, порядок, исключение учений, пределы")
def test_interests_rules(cs, onto):
    p = onto.person("Автор", "1700", "1760")
    st = onto.statements
    held = onto.thing("doctrine", "Скептицизм")
    st.add(p, "holds", obj=held, attributions=src())
    problem = onto.thing("problem", "Проблема индукции")
    concepts = [onto.thing("concept", f"Понятие {c}") for c in "БАВ"]
    works = [onto.thing("work", f"Труд {i}") for i in range(3)]
    for w in works:
        st.add(w, "author", obj=p, attributions=src())
    for w in works:  # Б — в трёх трудах, В — в двух, А — в одном; учение и проблема
        st.add(w, "discusses", obj=concepts[0], attributions=src())
    for w in works[:2]:
        st.add(w, "discusses", obj=concepts[2], attributions=src())
    st.add(works[0], "discusses", obj=concepts[1], attributions=src())
    st.add(works[0], "discusses", obj=held, attributions=src())
    st.add(works[0], "discusses", obj=problem, attributions=src())
    other_doctrine = onto.thing("doctrine", "Не интерес")
    st.add(works[1], "discusses", obj=other_doctrine, attributions=src())
    card, _ = cs.get(p)
    labels = [r["label"] for r in section(card, "interests")["rows"]]
    assert labels == ["Понятие Б", "Понятие В", "Понятие А", "Проблема индукции"]
    # Равное число трудов — по названию.
    assert held not in [r["entity_id"] for r in section(card, "interests")["rows"]]
    assert other_doctrine not in [r["entity_id"] for r in section(card, "interests")["rows"]]


@req(EC, "Выведенные строки", invariant="интересы: просматривается не больше 30 трудов")
def test_interests_scan_limit(cs, onto):
    p = onto.person("Плодовитый", "1700", "1760")
    st = onto.statements
    ids = []
    for i in range(31):
        w = onto.thing("work", f"Труд {i:02d}")
        c = onto.thing("concept", f"Тема {i:02d}")
        st.add(w, "author", obj=p, attributions=src())
        st.add(w, "discusses", obj=c, attributions=src())
        ids.append(c)
    card, _ = cs.get(p)
    interests = section(card, "interests")
    assert interests["total"] == 30 and interests["visible"] == 6
    assert interests["rows"] and len(interests["rows"]) == 30


# --- Свёрнутые списки ---------------------------------------------------------------------


@req(EC, "Свёрнутые списки", scenario="Короткий список без кнопки")
def test_short_list_totals(cs, onto, events):
    p = onto.person("Автор", "1700", "1760")
    for i in range(3):
        onto.statements.add(onto.thing("work", f"Труд {i}"), "author", obj=p, attributions=src())
    card, rid = cs.get(p)
    works = section(card, "works")
    assert (works["display"], works["visible"], works["total"]) == ("list", 6, 3)
    assert cs.served(events, rid)["type"] == "person"


@req(EC, "Свёрнутые списки", scenario="Длинный список")
def test_long_list_totals(cs, onto, events):
    p = onto.person("Автор", "1700", "1760")
    for i in range(9):
        onto.statements.add(onto.thing("work", f"Труд {i}"), "author", obj=p, attributions=src())
    card, rid = cs.get(p)
    works = section(card, "works")
    assert (works["visible"], works["total"], len(works["rows"])) == (6, 9, 9)
    assert len(events.where(SERVED, request_id=rid)) == 1


@req(
    EC,
    "Свёрнутые списки",
    invariant="у каждого раздела есть display, visible и total = числу строк",
)
@pytest.mark.parametrize(
    "type_", ["person", "concept", "doctrine", "work", "group", "event", "place", "term"]
)
def test_every_section_has_display_visible_total(cs, onto, type_):
    card = sweep(cs, onto, type_)[0]
    assert card["sections"]
    for s in card["sections"]:
        assert s["display"] in ("facts", "list", "inline"), s["code"]
        assert s["visible"] is None or (isinstance(s["visible"], int) and s["visible"] > 0)
        assert s["total"] == len(s["rows"]), s["code"]


# --- Государство основного места ----------------------------------------------------------


def kant_world(cs, onto, born="1724", place_name="Кёнигсберг", coords=(54.71, 20.51)):
    kant = onto.person("Кант", born, "1804")
    city = cs.place(place_name, *coords) if coords else cs.place(place_name)
    cs.lived(kant, city, "activity")
    return kant


@req(EC, "Государство основного места", scenario="Историческое государство")
def test_historical_polity(onto, tmp_path, events):
    svc = CardSvc(onto, events=events, polities=prussia_layer(tmp_path))
    kant = kant_world(svc, onto)
    card, rid = svc.get(kant)
    polity = card["summary"]["polity"]
    assert (polity["name"], polity["year"]) == ("Королевство Пруссия", 1724)
    assert svc.served(events, rid)["polity"] == "found"


@req(EC, "Государство основного места", scenario="Слоя нет — современная страна с пометкой")
def test_no_layer(onto, tmp_path, events):
    svc = CardSvc(onto, events=events, polities=PolityLayer(tmp_path / "absent.sqlite"))
    kant = kant_world(svc, onto)
    card, rid = svc.get(kant)
    assert card["summary"]["polity"] is None
    assert card["summary"]["place"]["geo"] == {"lat": 54.71, "lon": 20.51}
    assert svc.served(events, rid)["polity"] == "unavailable"


@req(EC, "Государство основного места", scenario="Вне покрытия слоя")
def test_outside_layer_coverage(onto, tmp_path, events):
    svc = CardSvc(onto, events=events, polities=prussia_layer(tmp_path))
    kant = kant_world(svc, onto, coords=(10.0, 100.0), place_name="Далёкий город")
    card, rid = svc.get(kant)
    assert card["summary"]["polity"] is None
    assert svc.served(events, rid)["polity"] == "none"


@req(
    EC,
    "Государство основного места",
    invariant="повреждённый артефакт слоя — как недоступный: polity unavailable, ответ 200",
)
@pytest.mark.parametrize("damage", ["no_table", "broken_geometry", "not_a_database"])
def test_damaged_layer_is_unavailable_not_500(onto, tmp_path, events, damage):
    import sqlite3

    path = _artifact(
        tmp_path / "polities.sqlite",
        [("prussia", "Королевство Пруссия", 1701, 1918, (19, 53, 23, 56), 10.0)],
    )
    if damage == "no_table":
        conn = sqlite3.connect(path)
        conn.execute("DROP TABLE polity_rows")
        conn.commit()
        conn.close()
    elif damage == "broken_geometry":
        conn = sqlite3.connect(path)
        conn.execute("UPDATE polity_rows SET geometry = '{не json'")
        conn.commit()
        conn.close()
    else:
        path.write_bytes(b"not a database" * 200)
    svc = CardSvc(onto, events=events, polities=PolityLayer(path))
    kant = kant_world(svc, onto)
    card, rid = svc.get(kant)  # статус 200 проверяет CardSvc.get
    assert card["summary"]["polity"] is None
    assert card["summary"]["place"]["geo"] == {"lat": 54.71, "lon": 20.51}
    assert svc.served(events, rid)["polity"] == "unavailable"


@req(EC, "Государство основного места", scenario="Место с координатами")
def test_place_card_has_geo_without_polity(onto, tmp_path, events):
    svc = CardSvc(onto, events=events, polities=prussia_layer(tmp_path))
    place = svc.place("Кёнигсберг", 54.71, 20.51)
    card, rid = svc.get(place)
    assert card["geo"] == {"lat": 54.71, "lon": 20.51} and card["summary"] is None
    event = svc.served(events, rid)
    assert (event["type"], event["polity"]) == ("place", "skipped")


@req(EC, "Государство основного места", scenario="Без координат")
def test_no_coordinates(onto, tmp_path, events):
    svc = CardSvc(onto, events=events, polities=prussia_layer(tmp_path))
    kant = kant_world(svc, onto, coords=None)
    card, rid = svc.get(kant)
    assert card["summary"]["place"]["geo"] is None and card["summary"]["polity"] is None
    event = svc.served(events, rid)
    assert (event["layout"], event["polity"]) == ("person", "skipped")


@req(
    EC,
    "Государство основного места",
    invariant="образование — на год рождения, из слоя, меньшее по площади",
)
def test_polity_depends_on_birth_year_and_picks_smallest(onto, tmp_path, events):
    svc = CardSvc(onto, events=events, polities=prussia_layer(tmp_path))
    early = kant_world(svc, onto, born="1650")  # Пруссии ещё нет: остаётся большая держава
    late = kant_world(svc, onto, born="1724")  # точку содержат Пруссия (меньше) и большая
    after = kant_world(svc, onto, born="1850")  # на 1850 год — только Пруссия
    none = kant_world(svc, onto, born="1950")  # образований на 1950 год нет
    names = {}
    for key, who in (("early", early), ("late", late), ("after", after), ("none", none)):
        card, _ = svc.get(who)
        polity = card["summary"]["polity"]
        names[key] = (polity["name"], polity["year"]) if polity else None
    assert names == {
        "early": ("Большая держава", 1650),
        "late": ("Королевство Пруссия", 1724),
        "after": ("Королевство Пруссия", 1850),
        "none": None,
    }
    assert [e["polity"] for e in events.of(SERVED)] == ["found", "found", "found", "none"]


@req(
    EC,
    "Государство основного места",
    invariant="без года рождения образование не ищется; название не из словаря",
)
def test_polity_needs_birth_year(onto, tmp_path, events):
    svc = CardSvc(onto, events=events, polities=prussia_layer(tmp_path))
    nameless = onto.person("Аноним")
    city = svc.place("Кёнигсберг", 54.71, 20.51)
    svc.lived(nameless, city, "activity")
    card, rid = svc.get(nameless)
    assert card["summary"]["polity"] is None
    assert svc.served(events, rid)["polity"] == "skipped"
    # Город известный, но слоя нет: название государства не берётся ни из какого словаря.
    bare = CardSvc(onto, events=events)
    kant = kant_world(bare, onto)
    card, _ = bare.get(kant)
    assert card["summary"]["polity"] is None


# --- Тексты карточки — текст --------------------------------------------------------------


@req(EC, "Тексты карточки — текст", scenario="Разметка в названии")
def test_markup_in_titles_served_verbatim(cs, onto, events):
    evil_person = '<img src=x onerror="window.__pwned=1">'
    evil_work = "<b>Труд</b>"
    evil_place = "<script>window.__pwned=2</script>"
    person = legacy_person(onto, evil_person, "1700", "1760")
    work = onto.thing("work", evil_work, "1739")
    place = cs.place(evil_place, 1.0, 2.0)
    onto.statements.add(work, "author", obj=person, attributions=src())
    cs.lived(person, place, "activity")
    seen = {}
    for key, eid in (("person", person), ("work", work), ("place", place)):
        card, rid = cs.get(eid)
        seen[key] = (card, rid)
        assert cs.served(events, rid)["type"] == key
    assert seen["person"][0]["title"] == evil_person
    assert seen["work"][0]["title"] == evil_work
    assert seen["place"][0]["title"] == evil_place
    # Сервер не экранирует разметку в строках разделов: клиент выводит их текстом.
    person_card = seen["person"][0]
    assert section(person_card, "works")["rows"][0]["label"] == evil_work
    assert section(person_card, "places")["rows"][0]["label"] == evil_place
    raw = json.dumps(person_card, ensure_ascii=False)
    assert evil_work in raw and "&lt;" not in raw and "\\u003c" not in raw
    assert seen["work"][0]["sections"][0]["rows"][0]["label"] == evil_person


@req(
    EC,
    "Тексты карточки — текст",
    invariant="значения, примечания и названия «через» отдаются как есть",
)
def test_markup_in_value_note_via_served_verbatim(cs, onto):
    evil = "<i onclick=alert(1)>x</i>"
    person = onto.person("Автор", "1700", "1760")
    work = onto.thing("work", evil, "1739")
    idea = onto.thing("concept", evil + "2")
    onto.statements.add(work, "author", obj=person, attributions=src())
    onto.statements.add(work, "discusses", obj=idea, attributions=src())
    onto.statements.add(idea, "definition", value=evil, attributions=src())
    card, _ = cs.get(idea)
    assert section(card, "definitions")["rows"][0]["value"] == evil
    [holder] = section(card, "relates_to")["rows"]
    assert holder["via"][0]["label"] == evil
    card, _ = cs.get(person)
    assert section(card, "works")["rows"][0]["label"] == evil
    assert section(card, "interests")["rows"][0]["via"][0]["label"] == evil


# --- Разделы карточки по типу (MODIFIED) --------------------------------------------------


@req(EC, "Разделы карточки по типу", scenario="Карточка понятия")
def test_concept_card(cs, onto, events):
    hume = onto.person("Юм", "1711", "1776")
    kant = onto.person("Кант", "1724", "1804")
    concept = onto.thing("concept", "причинность")
    term = onto.thing("term", "causa")
    conception = onto.thing("conception", "Причинность у Канта")
    work = onto.thing("work", "Трактат")
    st = onto.statements
    st.add(
        concept,
        "definition",
        value="связь причины и следствия",
        attributions=[Attribution("entity", hume)],
    )
    st.add(term, "denotes", obj=concept, attributions=src())
    st.add(conception, "conception_of", obj=concept, attributions=src())
    st.add(work, "discusses", obj=concept, attributions=src())
    st.add(work, "author", obj=hume, attributions=src())
    _ = kant
    card, rid = cs.get(concept)
    assert codes(card) == ["definitions", "relates_to", "words", "conceptions", "in_works"]
    assert card["layout"] == "entity"
    assert [r["label"] for r in section(card, "relates_to")["rows"]] == ["Юм"]
    assert section(card, "relates_to")["rows"][0]["inferred"] is True
    event = cs.served(events, rid)
    assert (event["type"], event["layout"], event["sections"]) == ("concept", "entity", 5)


@req(EC, "Разделы карточки по типу", scenario="Карточка труда")
def test_work_card(cs, onto, events):
    locke = onto.person("Локк", "1632", "1704")
    work = onto.thing("work", "Опыт о человеческом разумении")
    idea = onto.thing("concept", "идея")
    innate = onto.thing("concept", "врождённые идеи")
    st = onto.statements
    st.add(work, "author", obj=locke, attributions=src(), status="verified")
    st.add(work, "dating", value=parse("1689").to_json(), attributions=src())
    st.add(work, "discusses", obj=idea, attributions=src())
    st.add(work, "discusses", obj=innate, attributions=src())
    card, rid = cs.get(work)
    facts = card["sections"][0]
    assert (facts["code"], facts["display"]) == ("facts", "facts")
    assert next((r["type"], r["label"] or r["value"], r["mark"]) for r in facts["rows"]) == (
        "author",
        "Локк",
        "verified",
    )
    date_row = facts["rows"][1]
    assert date_row["type"] == "dating" and date_row["value"]["original"] == "1689"
    assert date_row["mark"] == "sourced"
    assert [r["label"] for r in section(card, "topics")["rows"]] == ["идея", "врождённые идеи"] or {
        r["label"] for r in section(card, "topics")["rows"]
    } == {"идея", "врождённые идеи"}
    assert "cites" not in codes(card)
    event = cs.served(events, rid)
    assert (event["type"], event["sections"], event["rows"]) == ("work", 2, 4)


@req(EC, "Разделы карточки по типу", scenario="Карточка группы")
def test_group_card(cs, onto, events):
    group = onto.thing("group", "Кембриджские платоники")
    st = onto.statements
    st.add(group, "group_kind", value="school", attributions=src())
    for name in ("Уичкот", "Мор"):
        st.add(onto.person(name, "1609", "1683"), "member_of", obj=group, attributions=src())
    card, rid = cs.get(group)
    assert codes(card) == ["facts", "membership"]
    assert section(card, "facts")["rows"][0]["value"] == "school"
    membership = section(card, "membership")
    assert membership["display"] == "inline" and len(membership["rows"]) == 2
    event = cs.served(events, rid)
    assert (event["type"], event["sections"], event["rows"]) == ("group", 2, 3)


@req(EC, "Разделы карточки по типу", scenario="Карточка события")
def test_event_card(cs, onto, events):
    event = onto.thing("event", "Славная революция")
    onto.statements.add(event, "event_kind", value="political", attributions=src())
    onto.statements.add(event, "dating", value=parse("1688").to_json(), attributions=src())
    card, rid = cs.get(event)
    assert codes(card) == ["when"] and section(card, "when")["display"] == "facts"
    assert [r["type"] for r in section(card, "when")["rows"]] == ["event_kind", "dating"]
    served = cs.served(events, rid)
    assert (served["type"], served["sections"], served["rows"]) == ("event", 1, 2)


@req(EC, "Разделы карточки по типу", scenario="Ничего не теряется")
def test_nothing_lost_tabula_rasa(cs, onto, events):
    term = onto.thing("term", "tabula rasa")
    event = onto.thing("idea_event", "Перевод Аристотеля")
    sid = onto.statements.add(event, "result", obj=term, attributions=src())
    card, rid = cs.get(term)
    assert sid in [r["statement_id"] for r in section(card, "other")["rows"]]
    served = cs.served(events, rid)
    assert served["rows"] == len(all_rows(card))


NOT_LISTED = {"description", "lifespan", "coordinates"}
SWEEP_TYPES = [t[0] for t in ENTITY_TYPES if t[0] not in ("source", "epoch")]


def sweep(cs, onto, type_: str):
    """Сущность типа с утверждениями по каждому типу связи реестра, в обе стороны."""
    registry = onto.registry
    entity = onto.thing(type_, f"Сущность {type_}")
    if type_ == "person":
        entity = onto.person("Сущность person", "1700", "1760")
    st = onto.statements
    made = 0
    for spec in RELATIONS:
        code = spec["code"]
        if spec.get("deprecated_by") or code in ("lifespan", "description", "coordinates"):
            continue
        kind = spec["value_kind"]
        if kind is not None:
            if registry.is_a(type_, spec["subject_types"]):
                value = {
                    "date": parse("1700").to_json(),
                    "text": "значение",
                    "enum": (spec.get("values") or ["x"])[0],
                }.get(kind)
                if value is None:
                    continue
                st.add(entity, code, value=value, attributions=src())
                made += 1
            continue
        for direction in ("out", "in"):
            ends = spec["object_types"] if direction == "out" else spec["subject_types"]
            mine = spec["subject_types"] if direction == "out" else spec["object_types"]
            if not registry.is_a(type_, mine):
                continue
            other_type = next(
                (t[0] for t in ENTITY_TYPES if t[0] != "source" and registry.is_a(t[0], ends)),
                None,
            )
            if other_type is None:
                continue
            other = onto.thing(other_type, letters(f"{other_type} {code} {direction}"))
            subj, obj = (entity, other) if direction == "out" else (other, entity)
            if code == "lived_in" and direction == "out":
                st.add(
                    subj, code, obj=obj, qualifiers={"place_role": "activity"}, attributions=src()
                )
            else:
                st.add(subj, code, obj=obj, attributions=src())
            made += 1
    assert made, type_
    card, rid = cs.get(entity)
    return card, rid, entity


def visible_ids(onto, entity: str) -> set[str]:
    return {
        s["id"] for s in onto.statements.about(entity, derived=False) if s["type"] not in NOT_LISTED
    }


def shown_ids(card: dict) -> set[str]:
    ids = set()
    for s in card["sections"]:
        if s["code"] == "misconceptions":
            continue
        for r in s["rows"]:
            if not r["inferred"]:
                ids |= {r["statement_id"], *r["also"]}
    summary = card.get("summary")
    if summary:
        ids |= {r["statement_id"] for r in summary["roles"]}
        if summary["place"]:
            ids |= {summary["place"]["statement_id"], *summary["place"]["also"]}
        # summary.years_row — утверждение lifespan: из множества видимых оно вычтено (NOT_LISTED)
    return ids


@req(EC, "Разделы карточки по типу", invariant="ни одно видимое утверждение не пропадает")
@pytest.mark.parametrize("type_", SWEEP_TYPES)
def test_nothing_lost_for_every_type(cs, onto, events, type_):
    card, rid, entity = sweep(cs, onto, type_)
    assert shown_ids(card) == visible_ids(onto, entity)
    assert cs.served(events, rid)["rows"] == len(all_rows(card))


@req(EC, "Разделы карточки по типу", invariant="разделы по типам: порядок и состав")
@pytest.mark.parametrize(
    "type_,expected",
    [
        ("term", ["facts", "translations", "in_works", "epoch", "other"]),
        (
            "doctrine",
            [
                "facts",
                "relates_to",
                "parts",
                "answers",
                "arguments",
                "in_works",
                "influence",
                "epoch",
                "context",
                "other",
            ],
        ),
        (
            "work",
            [
                "facts",
                "topics",
                "cites",
                "response",
                "influence",
                "parts",
                "epoch",
                "context",
                "other",
            ],
        ),
        (
            "group",
            [
                "facts",
                "membership",
                "founders",
                "positions",
                "debated",
                "staff",
                "epoch",
                "context",
                "other",
            ],
        ),
        ("place", ["residents", "events", "other"]),
        ("idea_event", ["when", "participants", "genesis", "effects", "epoch", "other"]),
        ("event", ["when", "participants", "effects", "epoch", "other"]),
    ],
)
def test_section_codes_order_by_type(cs, onto, type_, expected):
    card, _, _ = sweep(cs, onto, type_)
    got = codes(card)
    positions = [expected.index(c) for c in got if c != "misconceptions"]
    assert positions == sorted(positions) and all(
        c in expected or c == "misconceptions" for c in got
    ), got
    assert card["layout"] == "entity"


# --- Природа каждой строки ----------------------------------------------------------------


@req(EC, "Природа каждой строки", scenario="По источникам без подтверждения")
def test_sourced_without_evidence(cs, onto, events):
    kant = onto.person("Кант", "1724", "1804")
    hume = onto.person("Юм", "1711", "1776")
    sid = onto.statements.add(kant, "influenced_by", obj=hume, attributions=src(), status="sourced")
    card, rid = cs.get(kant)
    [row] = section(card, "influenced_by")["rows"]
    assert (row["statement_id"], row["mark"], row["evidence"]) == (sid, "sourced", [])
    assert cs.served(events, rid)["rows"] == 1


@req(EC, "Природа каждой строки", scenario="Сгенерированная строка")
def test_generated_row(cs, onto, events):
    kant = onto.person("Кант", "1724", "1804")
    locke = onto.person("Локк", "1632", "1704")
    onto.statements.add(kant, "develops", obj=locke, provenance=Provenance("generated"))
    card, rid = cs.get(kant)
    [row] = section(card, "influenced_by")["rows"]
    assert (row["mark"], row["generated"], row["status"]) == ("generated", True, "generated")
    # Легенда — отметки строк и частей сводки: годы Канта (lifespan, общее знание) проверены.
    assert card["summary"]["years_row"]["mark"] == "verified"
    assert card["legend"] == ["verified", "generated"]
    assert cs.served(events, rid)["rows"] == 1


@req(EC, "Природа каждой строки", scenario="Спорное")
def test_disputed_row(cs, onto, events):
    kant = onto.person("Кант", "1724", "1804")
    hume = onto.person("Юм", "1711", "1776")
    onto.statements.add(
        kant,
        "influenced_by",
        obj=hume,
        attributions=[
            Attribution("source", "s_a"),
            Attribution("source", "s_b", stance="disputes"),
        ],
    )
    card, rid = cs.get(kant)
    [row] = section(card, "influenced_by")["rows"]
    assert row["mark"] == "disputed" and row["disputed_by"] == ["s_b"]
    assert row["attributed_to"] == ["s_a", "s_b"]
    assert cs.served(events, rid)["rows"] == 1


@req(EC, "Природа каждой строки", invariant="отметка — «спорное» либо статус, одна шкала")
@pytest.mark.parametrize("status", STATUSES)
@pytest.mark.parametrize("disputed", [False, True])
def test_mark_rule_for_all_combinations(cs, onto, status, disputed):
    a, b = onto.person("А", "1700", "1760"), onto.person("Б", "1701", "1761")
    _add(onto.statements, a, "influenced_by", b, status, disputed=disputed)
    card, _ = cs.get(a)
    [row] = section(card, "influenced_by")["rows"]
    assert row["status"] == status
    assert row["mark"] == ("disputed" if disputed else status)
    assert row["generated"] == (status == "generated")


@req(EC, "Природа каждой строки", scenario="Одна легенда")
def test_legend_is_set_of_marks(cs, onto):
    p = onto.person("Кант", "1724", "1804")
    st = onto.statements
    st.add(p, "person_role", value="philosopher", attributions=src(), status="verified")
    st.add(p, "influenced_by", obj=onto.person("Юм", "1711", "1776"), attributions=src())
    st.add(
        p, "develops", obj=onto.person("Локк", "1632", "1704"), provenance=Provenance("generated")
    )
    st.add(
        p,
        "criticizes",
        obj=onto.person("Лейбниц", "1646", "1716"),
        attributions=[
            Attribution("source", "s_a"),
            Attribution("source", "s_b", stance="disputes"),
        ],
    )
    card, _ = cs.get(p)
    marks = {r["mark"] for r in all_rows(card)}
    marks |= {r["mark"] for r in card["summary"]["roles"]}
    assert marks == {"verified", "sourced", "generated", "disputed"}
    assert card["legend"] == list(MARKS)


@req(
    EC,
    "Природа каждой строки",
    invariant="легенда: отметки строк, сводки и сгенерированного описания по шкале",
)
@pytest.mark.parametrize("type_", SWEEP_TYPES)
def test_legend_equals_marks_in_every_type(cs, onto, type_):
    card, _, _ = sweep(cs, onto, type_)
    marks = {r["mark"] for r in all_rows(card)}
    summary = card.get("summary")
    if summary:
        marks |= {r["mark"] for r in summary["roles"]}
        if summary["place"]:
            marks.add(summary["place"]["mark"])
        if summary["years_row"]:
            marks.add(summary["years_row"]["mark"])
    if card["description"] and card["description"]["generated"]:
        marks.add("generated")
    assert card["legend"] == [m for m in MARKS if m in marks]
    assert all(r["mark"] in MARKS for r in all_rows(card))
    ids = [r["statement_id"] for r in all_rows(card)]
    assert len(ids) == len(set(ids))  # statement_id уникальны в карточке


@req(
    EC,
    "Природа каждой строки",
    invariant="сгенерированное описание попадает в легенду, пустая карточка — без легенды",
)
def test_generated_description_in_legend_and_none_when_empty(cs, onto):
    thing = onto.thing("doctrine", "Учение")
    onto.statements.add(
        thing, "description", value="Текст.", provenance=Provenance("generated"), attributions=src()
    )
    card, _ = cs.get(thing)
    assert card["sections"] == [] and card["legend"] == ["generated"]
    assert card["empty"] is False
    bare = onto.thing("doctrine", "Пустое")
    card, _ = cs.get(bare)
    assert card["legend"] == [] and card["empty"] is True


# --- Пустые разделы -----------------------------------------------------------------------


@req(EC, "Пустые разделы", scenario="Совсем пусто")
def test_place_completely_empty(cs, onto, events):
    place = onto.thing("place", "Пустошь")
    card, rid = cs.get(place)
    assert (card["empty"], card["where_to_read"], card["geo"]) == (True, [], None)
    event = cs.served(events, rid)
    assert (event["type"], event["empty"]) == ("place", True)


@req(
    EC,
    "Пустые разделы",
    invariant="ни одной пустой карточки: у типа с утверждением есть раздел или сводка",
)
@pytest.mark.parametrize("type_", SWEEP_TYPES)
def test_one_statement_never_gives_empty_card(cs, onto, events, type_):
    """C3: у сущности с одним видимым утверждением (кроме описания) карточка не пуста."""
    st = onto.statements
    entity = (
        onto.person("Персона", "1700", "1760") if type_ == "person" else onto.thing(type_, "Одна")
    )
    # По одному утверждению на каждый вид связи, где сущность — субъект или объект.
    ones = []
    for spec in RELATIONS:
        code = spec["code"]
        if spec["value_kind"] is not None or spec.get("deprecated_by"):
            continue
        for direction in ("out", "in"):
            ends = spec["object_types"] if direction == "out" else spec["subject_types"]
            mine = spec["subject_types"] if direction == "out" else spec["object_types"]
            if onto.registry.is_a(type_, mine):
                other_type = next(
                    (
                        t[0]
                        for t in ENTITY_TYPES
                        if t[0] != "source" and onto.registry.is_a(t[0], ends)
                    ),
                    None,
                )
                if other_type:
                    ones.append((code, direction, other_type))
    assert ones, type_
    for code, direction, other_type in ones:
        fresh = (
            onto.person("Персона", "1700", "1760")
            if type_ == "person"
            else onto.thing(type_, "Одна")
        )
        other = onto.thing(other_type, letters(f"{other_type} {code} {direction}"))
        subj, obj = (fresh, other) if direction == "out" else (other, fresh)
        st.add(subj, code, obj=obj, attributions=src())
        card, rid = cs.get(fresh)
        assert card["empty"] is False, (type_, code, direction)
        assert card["sections"] or card["summary"], (type_, code, direction)
        assert cs.served(events, rid)["empty"] is False
    _ = entity


@req(EC, "Пустые разделы", invariant="сущность без утверждений — empty = true, разделов нет")
@pytest.mark.parametrize("type_", [t for t in SWEEP_TYPES if t != "person"])
def test_no_statements_gives_empty_card(cs, onto, events, type_):
    card, rid = cs.get(onto.thing(type_, "Ничего"))
    assert card["empty"] is True and card["sections"] == [] and card["legend"] == []
    event = cs.served(events, rid)
    assert (event["sections"], event["rows"], event["empty"]) == (0, 0, True)


@req(
    EC,
    "Пустые разделы",
    invariant="ни одного пустого раздела; пустая персона — без раздела, но с сводкой",
)
@pytest.mark.parametrize("type_", SWEEP_TYPES)
def test_no_empty_sections_in_any_type(cs, onto, type_):
    card, _, _ = sweep(cs, onto, type_)
    assert all(s["rows"] for s in card["sections"])
    assert len({s["code"] for s in card["sections"]}) == len(card["sections"])


@req(EC, "Пустые разделы", invariant="место только с координатами: карточка не пуста")
def test_place_with_only_coordinates_is_not_empty(cs, onto):
    """C3: утверждение о месте — координаты; карточка места показывает страну по ним."""
    place = cs.place("Кёнигсберг", 54.71, 20.51)
    card, rid = cs.get(place)
    assert card["geo"] == {"lat": 54.71, "lon": 20.51}
    assert card["sections"] == [] and card["summary"] is None
    assert card["empty"] is False
    assert cs.served(cs.events, rid)["empty"] is False


@req(
    EC, "Пустые разделы", invariant="место вне любой страны (точка в океане): координаты — не пусто"
)
def test_place_in_ocean_with_only_coordinates_is_not_empty(cs, onto):
    place = cs.place("Остров в океане", 30.5, -40.25)
    card, rid = cs.get(place)
    assert card["geo"] == {"lat": 30.5, "lon": -40.25}
    assert card["sections"] == [] and card["summary"] is None
    assert card["empty"] is False
    assert cs.served(cs.events, rid)["empty"] is False


@req(EC, "Природа каждой строки", invariant="регион снимает подтверждение, но не меняет отметку")
def test_region_hides_evidence_but_keeps_mark(cs, onto, events):
    from philograph.knowledge.statements import Evidence

    kant, hume = onto.person("Кант", "1724", "1804"), onto.person("Юм", "1711", "1776")
    onto.paragraphs["pr1"] = "Кант испытал влияние Юма."
    onto.statements.add(
        kant,
        "influenced_by",
        obj=hume,
        attributions=src("s_closed"),
        evidence=[Evidence("pr1", "испытал влияние Юма", source_id="s_closed")],
        provenance=Provenance("extracted"),
    )
    [open_row] = section(cs.get(kant)[0], "influenced_by")["rows"]
    assert open_row["mark"] == "sourced" and len(open_row["evidence"]) == 1
    card = cs.cards.card(kant, closed=frozenset({"s_closed"}))
    [row] = section(card, "influenced_by")["rows"]
    assert (row["mark"], row["status"]) == ("sourced", "sourced")
    assert row["evidence"] == [] and row["attributions"] == []
    # Легенда: отметка строки и отметка годов сводки (lifespan Канта — общее знание).
    assert card["summary"]["years_row"]["mark"] == "verified"
    assert card["legend"] == ["verified", "sourced"]
    assert [e["rows"] for e in events.of(SERVED)] == [1, 1]
