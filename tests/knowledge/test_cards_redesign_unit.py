"""Юнит-тесты разработчика: разделы карточки данными, выводы, сводка персоны, образование
в точке (redesign-entity-cards). Сценарные и нормативные тесты пишет тестировщик."""

from __future__ import annotations

import json
import sqlite3

from philograph.knowledge.cards import TEMPLATES, Cards, mark_of
from philograph.knowledge.polities import FORMAT_VERSION, SCHEMA, PolityLayer
from philograph.knowledge.registry_data import ENTITY_TYPES
from philograph.knowledge.statements import Attribution, Provenance


def _src(who="s_a"):
    return [Attribution("source", who)]


def test_every_type_has_template_and_valid_display():
    for code, *_ in ENTITY_TYPES:
        if code == "source":
            continue
        template = TEMPLATES.get(code)
        assert template is not None, code
        for section in template.sections:
            assert section.display in ("facts", "list", "inline"), (code, section.code)
    assert TEMPLATES["person"].layout == "person" and not TEMPLATES["person"].where
    assert TEMPLATES["epoch"].layout == "epoch" and not TEMPLATES["epoch"].other


def test_mark_rule():
    assert mark_of("verified", "single") == "verified"
    assert mark_of("sourced", "disputed") == "disputed"
    assert mark_of("generated", None) == "generated"


def test_person_influence_split_and_dedupe(onto, events):
    kant = onto.person("Кант", "1724", "1804")
    hume = onto.person("Юм", "1711", "1776")
    knutzen = onto.person("Кнутцен", "1713", "1751")
    fichte = onto.person("Фихте", "1762", "1814")
    weak = onto.statements.add(kant, "influenced_by", obj=hume, provenance=Provenance("generated"))
    strong = onto.statements.add(
        kant, "criticizes", obj=hume, attributions=_src(), status="verified"
    )
    onto.statements.add(kant, "studied_with", obj=knutzen, attributions=_src())
    onto.statements.add(fichte, "influenced_by", obj=kant, attributions=_src())
    card = Cards(onto.statements).card(kant)
    sections = {s["code"]: s for s in card["sections"]}
    assert "influence" not in sections and "life" not in sections
    [row] = sections["influenced_by"]["rows"]
    assert row["label"] == "Юм" and row["statement_id"] == strong and row["also"] == [weak]
    assert row["mark"] == "verified"
    assert [r["label"] for r in sections["influenced"]["rows"]] == ["Фихте"]
    assert [r["label"] for r in sections["teachers"]["rows"]] == ["Кнутцен"]
    assert card["layout"] == "person" and card["where_to_read"] == []
    assert card["summary"]["years"] and card["summary"]["polity"] is None
    [event] = events.of("knowledge.card.served")
    assert event["layout"] == "person" and event["inferred"] == 0 and event["polity"] == "skipped"


def test_interests_weakest_link_and_no_writes(onto):
    hume = onto.person("Юм", "1711", "1776")
    treatise = onto.thing("work", "Трактат")
    enquiry = onto.thing("work", "Исследование")
    causality = onto.thing("concept", "причинность")
    induction = onto.thing("concept", "индукция")
    for w in (treatise, enquiry):
        onto.statements.add(w, "author", obj=hume, attributions=_src(), status="verified")
    onto.statements.add(
        treatise, "discusses", obj=causality, attributions=_src(), status="verified"
    )
    onto.statements.add(treatise, "discusses", obj=induction, provenance=Provenance("generated"))
    onto.statements.add(enquiry, "discusses", obj=causality, attributions=_src())
    before = len(onto.statements.about(hume))
    card = Cards(onto.statements).card(hume)
    interests = next(s for s in card["sections"] if s["code"] == "interests")
    assert interests["inferred"] is True and interests["display"] == "inline"
    first, second = interests["rows"]
    assert (first["label"], first["mark"], len(first["via"])) == ("причинность", "verified", 2)
    assert (second["label"], second["mark"]) == ("индукция", "generated")
    assert first["statement_id"] == f"inferred:interests:{causality}"
    assert first["evidence"] == [] and first["derived"] is True and first["type"] == "discusses"
    assert len(onto.statements.about(hume)) == before


def test_doctrine_relates_to_inferred_via_work(onto, events):
    berkeley = onto.person("Беркли", "1685", "1753")
    work = onto.thing("work", "Трактат о началах")
    doctrine = onto.thing("doctrine", "Имматериализм")
    onto.statements.add(work, "author", obj=berkeley, attributions=_src(), status="verified")
    onto.statements.add(work, "discusses", obj=doctrine, provenance=Provenance("generated"))
    card = Cards(onto.statements).card(doctrine)
    assert [s["code"] for s in card["sections"]] == ["relates_to", "in_works"]
    [row] = card["sections"][0]["rows"]
    assert row["inferred"] and row["label"] == "Беркли" and row["type"] == "author"
    assert row["status"] == "generated" and row["mark"] == "generated" and row["generated"]
    assert [v["label"] for v in row["via"]] == ["Трактат о началах"]
    [event] = events.of("knowledge.card.served")
    assert (event["sections"], event["rows"], event["inferred"]) == (2, 2, 1)


def test_direct_holder_replaces_inference(onto):
    descartes = onto.person("Декарт", "1596", "1650")
    work = onto.thing("work", "Размышления")
    position = onto.thing("position", "Методическое сомнение")
    onto.statements.add(descartes, "holds", obj=position, attributions=_src(), status="verified")
    onto.statements.add(work, "author", obj=descartes, attributions=_src())
    onto.statements.add(work, "expresses", obj=position, attributions=_src())
    card = Cards(onto.statements).card(position)
    relates = next(s for s in card["sections"] if s["code"] == "relates_to")
    assert [(r["label"], r["inferred"]) for r in relates["rows"]] == [("Декарт", False)]


def test_work_facts_order_and_group_kind(onto):
    locke = onto.person("Локк", "1632", "1704")
    essay = onto.thing("work", "Опыт", "1689")
    onto.statements.add(essay, "author", obj=locke, attributions=_src(), status="verified")
    card = Cards(onto.statements).card(essay)
    facts = card["sections"][0]
    assert facts["code"] == "facts" and facts["display"] == "facts"
    assert [r["type"] for r in facts["rows"]] == ["author", "dating"]
    group = onto.thing("group", "Кембриджские платоники")
    onto.statements.add(group, "group_kind", value="school", attributions=_src())
    gcard = Cards(onto.statements).card(group)
    assert gcard["sections"][0]["code"] == "facts"
    assert gcard["sections"][0]["rows"][0]["value"] == "school"
    person_card = Cards(onto.statements).card(locke)
    works = next(s for s in person_card["sections"] if s["code"] == "works")
    assert works["rows"][0]["note"] == "1689"


def test_other_section_keeps_unplaced_statement(onto):
    term = onto.thing("term", "tabula rasa")
    event = onto.thing("idea_event", "Перевод Аристотеля")
    sid = onto.statements.add(event, "result", obj=term, attributions=_src())
    card = Cards(onto.statements).card(term)
    other = next(s for s in card["sections"] if s["code"] == "other")
    assert [r["statement_id"] for r in other["rows"]] == [sid]


def test_empty_card(onto, events):
    place = onto.thing("place", "Пустошь")
    card = Cards(onto.statements).card(place)
    assert card["sections"] == [] and card["empty"] is True and card["geo"] is None
    assert card["legend"] == []
    [event] = events.of("knowledge.card.served")
    assert event["empty"] is True


def _artifact(path, polities):
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO meta VALUES ('format_version', ?)", (str(FORMAT_VERSION),))
    conn.execute("INSERT INTO meta VALUES ('source', '{}')")
    for i, (pid, name, start, end, box, area) in enumerate(polities):
        x0, y0, x1, y1 = box
        ring = [[x0, y0], [x0, y1], [x1, y1], [x1, y0], [x0, y0]]
        conn.execute(
            "INSERT INTO polity_rows VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (i, pid, start, end, name, "ru", "wikidata", name, None, area,
             json.dumps({"type": "Polygon", "coordinates": [ring]})),
        )  # fmt: skip
    conn.commit()
    conn.close()
    return path


def test_polity_at_point_year_and_smallest(tmp_path):
    db = _artifact(
        tmp_path / "p.sqlite",
        [
            ("prussia", "Королевство Пруссия", 1701, 1918, (19, 53, 23, 56), 10.0),
            ("big", "Большая держава", 1600, 1800, (0, 40, 40, 70), 1000.0),
        ],
    )
    layer = PolityLayer(db)
    assert layer.at(54.71, 20.51, 1724)["name"] == "Королевство Пруссия"
    assert layer.at(54.71, 20.51, 1650)["name"] == "Большая держава"
    assert layer.at(54.71, 20.51, 1950) is None
    assert layer.at(10.0, 100.0, 1724) is None


def test_person_summary_polity(onto, tmp_path, events):
    db = _artifact(
        tmp_path / "p.sqlite",
        [("prussia", "Королевство Пруссия", 1701, 1918, (19, 53, 23, 56), 10.0)],
    )
    kant = onto.person("Кант", "1724", "1804")
    city = onto.thing("place", "Кёнигсберг")
    onto.statements.add(
        city, "coordinates", value={"lat": 54.71, "lon": 20.51}, attributions=_src()
    )
    onto.statements.add(
        kant, "lived_in", obj=city, qualifiers={"place_role": "activity"}, attributions=_src()
    )
    card = Cards(onto.statements, polities=PolityLayer(db)).card(kant)
    assert card["summary"]["place"]["label"] == "Кёнигсберг"
    assert card["summary"]["place"]["geo"] == {"lat": 54.71, "lon": 20.51}
    assert card["summary"]["polity"]["name"] == "Королевство Пруссия"
    assert card["summary"]["polity"]["year"] == 1724
    missing = Cards(onto.statements, polities=PolityLayer(tmp_path / "none.sqlite")).card(kant)
    assert missing["summary"]["polity"] is None
    outcomes = [e["polity"] for e in events.of("knowledge.card.served")]
    assert outcomes == ["found", "unavailable"]
