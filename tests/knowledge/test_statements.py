"""Требования спецификации ontology-statements."""

from __future__ import annotations

import pytest

from philograph.knowledge.registry import RegistryError
from philograph.knowledge.statements import Attribution, Evidence, Provenance, StatementError

req = pytest.mark.req
OS = "ontology-statements"


@req(OS, "Состав утверждения")
def test_statement_composition(onto):
    concept = onto.thing("concept", "Причинность")
    sid = onto.statements.add(
        concept,
        "definition",
        value="связь причины и следствия",
        attributions=[Attribution("source", "s_textbook")],
    )
    s = onto.statements.get(sid)
    for key in (
        "subject",
        "type",
        "object",
        "value",
        "qualifiers",
        "attributions",
        "evidence",
        "consensus",
        "rank",
        "status",
        "provenance",
        "scope",
    ):
        assert key in s
    with pytest.raises(StatementError):
        onto.statements.add(concept, "definition", value="без атрибуции")


@req(OS, "Атрибуция")
def test_attribution_with_stances(onto):
    locke = onto.person("Локк")
    tabula = onto.thing("concept", "Чистая доска")
    sid = onto.statements.add(
        tabula,
        "description",
        value="образ введён Локком",
        rank="deprecated",
        attributions=[
            Attribution("common", stance="asserts"),
            Attribution("source", "s_textbook", stance="disputes"),
        ],
    )
    s = onto.statements.get(sid)
    assert {(a["who_kind"], a["stance"]) for a in s["attributions"]} == {
        ("common", "asserts"),
        ("source", "disputes"),
    }
    assert s["rank"] == "deprecated" and locke


@req(OS, "Подтверждения")
def test_evidence_quote_must_be_in_paragraph(onto, events):
    kant, hume = onto.person("Кант"), onto.person("Юм")
    sid = onto.sourced(kant, "influenced_by", hume)
    assert onto.statements.get(sid)["evidence"][0]["quote"] == "Кант испытал влияние Юма"
    with pytest.raises(StatementError) as info:
        onto.sourced(kant, "criticizes", hume, quote="Кант ненавидел Юма")
    assert "цитата не найдена" in str(info.value)
    assert events.where("knowledge.statement.refused", type="criticizes")


@req(OS, "Происхождение в системе")
def test_provenance_separate_from_attribution(onto):
    kant, hume = onto.person("Кант"), onto.person("Юм")
    sid = onto.statements.add(
        kant,
        "influenced_by",
        obj=hume,
        attributions=[Attribution("source", "s_textbook")],
        evidence=[Evidence("p2", "Кант испытал влияние Юма")],
        provenance=Provenance("extracted", run_id="run-1", model="flash", template="extract@abc"),
    )
    onto.statements.confirm(sid, "operator")
    s = onto.statements.get(sid)
    assert s["provenance"]["method"] == "extracted" and s["provenance"]["model"] == "flash"
    assert s["status"] == "verified"
    assert onto.statements.journal(sid)[-1]["actor"] == "operator"


@req(OS, "Статусы и переходы")
def test_status_transitions(onto, events):
    hume, malebranche = onto.person("Юм"), onto.person("Мальбранш")
    sid = onto.statements.add(
        hume, "influenced_by", obj=malebranche, provenance=Provenance("generated")
    )
    assert onto.statements.get(sid)["status"] == "generated"
    onto.paragraphs["p9"] = "Юм испытал влияние Мальбранша."
    onto.statements.add(
        hume,
        "influenced_by",
        obj=malebranche,
        evidence=[Evidence("p9", "Юм испытал влияние Мальбранша")],
        attributions=[Attribution("source", "s_other")],
        provenance=Provenance("extracted"),
    )
    assert onto.statements.get(sid)["status"] == "sourced"
    onto.statements.handle_library_event(
        "source.published",
        {
            "event_id": "e1",
            "source_id": "s_other",
            "removed": ["p9"],
            "changed": [],
            "redirected": {},
        },
    )
    assert onto.statements.get(sid)["status"] == "generated"
    assert "evidence_lost" in onto.statements.get(sid)["warnings"]
    with pytest.raises(StatementError):
        onto.statements.add(
            hume,
            "criticizes",
            obj=malebranche,
            status="sourced",
            provenance=Provenance("extracted"),
        )


@req(OS, "Отклонённые не показываются")
def test_rejected_hidden_and_repeat_rejected(onto, events):
    hume, malebranche = onto.person("Юм"), onto.person("Мальбранш")
    sid = onto.statements.add(
        hume, "influenced_by", obj=malebranche, provenance=Provenance("generated")
    )
    onto.statements.reject(sid, "operator")
    assert onto.statements.about(hume, derived=False) == []
    again = onto.statements.add(
        hume, "influenced_by", obj=malebranche, provenance=Provenance("generated")
    )
    assert again == sid and onto.statements.get(sid)["status"] == "rejected"
    events.one("knowledge.statement.rejected_repeat")


@req(OS, "Согласие и ранг")
def test_consensus_and_rank(onto):
    kant, hume = onto.person("Кант"), onto.person("Юм")
    sid = onto.statements.add(
        kant,
        "influenced_by",
        obj=hume,
        attributions=[
            Attribution("source", "a"),
            Attribution("source", "b"),
            Attribution("source", "c", stance="disputes"),
        ],
    )
    assert onto.statements.get(sid)["consensus"] == "disputed"
    work = onto.thing("work", "Критика чистого разума")
    main = onto.statements.add(
        work,
        "dating",
        value={"original": "1781"},
        rank="preferred",
        attributions=[Attribution("common")],
    )
    onto.statements.add(
        work, "dating", value={"original": "1787"}, attributions=[Attribution("common")]
    )
    assert onto.entities.get(work)["primary"]["dates"] == {"original": "1781"} and main


@req(OS, "Проверки целостности")
def test_integrity_errors_and_warnings(onto, events):
    aristotle, being = onto.person("Аристотель"), onto.thing("concept", "Бытие")
    with pytest.raises(StatementError):
        onto.statements.add(
            aristotle, "studied_with", obj=being, attributions=[Attribution("common")]
        )
    locke = onto.person("Локк", "1632", "1704")
    new_essays = onto.thing("work", "Новые опыты", "1765")
    sid = onto.statements.add(
        locke, "influenced_by", obj=new_essays, attributions=[Attribution("common")]
    )
    assert onto.statements.get(sid)["warnings"] == ["influence_against_time"]
    events.one("knowledge.statement.warning")


@req(OS, "Объединение повторов")
def test_duplicates_merge_attributions(onto):
    kant, hume = onto.person("Кант"), onto.person("Юм")
    first = onto.sourced(kant, "influenced_by", hume, who="s_a")
    onto.paragraphs["p5"] = "Другой учебник: Кант испытал влияние Юма."
    second = onto.sourced(kant, "influenced_by", hume, who="s_b", paragraph="p5")
    assert first == second
    s = onto.statements.get(first)
    assert len(s["attributions"]) == 2 and len(s["evidence"]) == 2
    assert s["consensus"] == "prevailing"


@req(OS, "Симметричные и обратные связи")
def test_symmetric_once_both_sides(onto):
    descartes, elizabeth = onto.person("Декарт"), onto.person("Елизавета Богемская")
    a = onto.statements.add(
        descartes, "corresponded", obj=elizabeth, attributions=[Attribution("common")]
    )
    b = onto.statements.add(
        elizabeth, "corresponded", obj=descartes, attributions=[Attribution("common")]
    )
    assert a == b
    assert [s["id"] for s in onto.statements.about(elizabeth, derived=False)] == [a]
    assert [s["id"] for s in onto.statements.about(descartes, derived=False)] == [a]


@req(OS, "Выведенные утверждения")
def test_derived_influence_from_idea_event(onto):
    kant = onto.person("Кант")
    answer = onto.entities.create("idea_event", [("ru", "Ответ Канта Юму", "primary")])
    hume_causality = onto.thing("conception", "Причинность у Юма")
    onto.statements.add(kant, "participated", obj=answer, attributions=[Attribution("common")])
    onto.paragraphs["p6"] = "Кант исходил из концепции причинности Юма."
    onto.statements.add(
        answer,
        "source_material",
        obj=hume_causality,
        attributions=[Attribution("source", "s")],
        evidence=[Evidence("p6", "концепции причинности Юма")],
        provenance=Provenance("extracted"),
    )
    derived = [s for s in onto.statements.about(kant, types=["influenced_by"]) if s["derived"]]
    assert len(derived) == 1
    assert derived[0]["object"] == hume_causality and derived[0]["status"] == "sourced"


@req(OS, "Запрос утверждений о сущности")
def test_query_with_filters(onto):
    kant, hume, leibniz = onto.person("Кант"), onto.person("Юм"), onto.person("Лейбниц")
    onto.sourced(kant, "influenced_by", hume, who="s_textbook")
    onto.statements.add(kant, "develops", obj=leibniz, attributions=[Attribution("common")])
    only_textbook = onto.statements.about(kant, attributed_to="s_textbook")
    assert [s["object"] for s in only_textbook] == [hume]
    assert len(onto.statements.about(kant, statuses=["verified"], derived=False)) == 1


@req(OS, "Обход по рецепту")
def test_traverse_recipe_with_cycles_and_limits(onto):
    aristotle = onto.person("Аристотель", "-383", "-321")
    hume = onto.person("Юм", "1711", "1776")
    kant = onto.person("Кант", "1724", "1804")
    onto.statements.add(kant, "criticizes", obj=hume, attributions=[Attribution("common")])
    onto.statements.add(hume, "influenced_by", obj=aristotle, attributions=[Attribution("common")])
    graph = onto.statements.traverse("genesis", [kant], depth=3)
    assert [n["id"] for n in graph["nodes"]] == [aristotle, hume, kant]  # по времени
    onto.statements.add(hume, "criticizes", obj=kant, attributions=[Attribution("common")])
    cyclic = onto.statements.traverse("polemic", [kant], depth=2)
    ids = [n["id"] for n in cyclic["nodes"]]
    assert len(ids) == len(set(ids))
    limited = onto.statements.traverse("genesis", [kant], max_nodes=2)
    assert limited["truncated"] is True
    with pytest.raises(RegistryError):
        onto.statements.traverse("answers", [kant])


@req(OS, "Область видимости утверждений")
def test_scope(onto):
    kant, hume = onto.person("Кант"), onto.person("Юм")
    onto.statements.add(
        kant,
        "influenced_by",
        obj=hume,
        scope="group:teacher-1",
        attributions=[Attribution("source", "s_uploaded")],
    )
    assert onto.statements.about(kant, derived=False) == []
    assert (
        len(onto.statements.about(kant, scopes=("public", "group:teacher-1"), derived=False)) == 1
    )


@req(OS, "Журнал изменений и откат запуска")
def test_journal_and_rollback(onto, events):
    kant, hume, leibniz = onto.person("Кант"), onto.person("Юм"), onto.person("Лейбниц")
    bad = onto.sourced(kant, "influenced_by", hume, run_id="run-bad")
    onto.paragraphs["p7"] = "Кант испытал влияние Лейбница."
    keep = onto.sourced(
        kant,
        "influenced_by",
        leibniz,
        run_id="run-bad",
        paragraph="p7",
        quote="Кант испытал влияние Лейбница",
    )
    onto.statements.confirm(keep, "operator")
    result = onto.statements.rollback_run("run-bad")
    assert result["statements"] == 1
    from sqlalchemy.exc import NoResultFound

    with pytest.raises(NoResultFound):
        onto.statements.get(bad)
    assert onto.statements.get(keep)["status"] == "verified"
    assert len(onto.statements.journal(keep)) == 2
    events.one("knowledge.run.rolled_back")


@req(OS, "Реакция на изменения библиотеки")
def test_library_events(onto, events):
    kant, hume = onto.person("Кант"), onto.person("Юм")
    sid = onto.sourced(
        kant,
        "influenced_by",
        hume,
        paragraph="p1",
        quote="Юм пробудил его от догматического сна",
        who="s_textbook",
    )
    onto.paragraphs["p1"] = "Кант написал Критику."
    onto.statements.handle_library_event(
        "source.published",
        {
            "event_id": "e1",
            "source_id": "s_textbook",
            "changed": ["p1"],
            "removed": [],
            "redirected": {},
        },
    )
    s = onto.statements.get(sid)
    assert s["evidence"][0]["lost"] and "evidence_lost" in s["warnings"]
    onto.paragraphs["p8"] = "Учебник: Кант испытал влияние Юма в вопросе о причинности."
    other = onto.sourced(kant, "criticizes", hume, paragraph="p2", who="s_textbook")
    onto.statements.handle_library_event(
        "source.published",
        {
            "event_id": "e2",
            "source_id": "s_textbook",
            "changed": [],
            "removed": [],
            "redirected": {"p2": "p8"},
        },
    )
    assert onto.statements.get(other)["evidence"][0]["paragraph_id"] == "p8"
    onto.statements.handle_library_event(
        "source.unpublished", {"event_id": "e3", "source_id": "s_textbook"}
    )
    assert onto.statements.about(kant, derived=False) == []
    onto.statements.handle_library_event(
        "source.unpublished", {"event_id": "e3", "source_id": "s_textbook"}
    )  # повтор события ничего не делает
    assert len(events.of("knowledge.library.event")) == 3
