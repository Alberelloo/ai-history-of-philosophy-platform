"""Юнит-тесты поштучной проверки ответа (``Filling._item``, ``apply_reply``), фрагментов по
объёму и жизненного цикла запуска. Сценарии и инварианты требований — у тестировщика."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from philograph.knowledge import schema as t
from philograph.knowledge.entity_items import Skip

from .extraction_stand import Stand

P1 = "Кант писал, что всякое знание начинается с опыта."
P2 = "Юм считал причинность привычкой ума."


@pytest.fixture
def stand(onto, engine_for, clock) -> Stand:
    return Stand(onto, engine_for, clock)


def st(subject, type_, obj, paragraph, quote, **extra):
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


def run_row(stand) -> dict:
    with stand.onto.statements.engine.begin() as conn:
        [row] = conn.execute(select(t.filling_runs)).mappings().all()
    return dict(row)


WINDOW = [{"id": "p1", "text": P1}, {"id": "p2", "text": P2}]


def item(stand, raw):
    allowed = set(stand.filling._schema()["x-relations"])
    return stand.filling._item(raw, WINDOW, allowed)


def test_item_nulls_and_paragraph_string(stand):
    got = item(
        stand,
        st("Кант", "holds", "Опыт", " 1 ", "всякое знание", attributed_to=None, stance=None),
    )
    assert got["paragraph"] == 1 and "attributed_to" not in got and "stance" not in got


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        ("строка", "schema_item"),
        ({"subject": "Кант", "type": "holds", "object": "Опыт", "paragraph": 1}, "schema_item"),
        (st("Кант", "holds", "Опыт", True, "знание"), "schema_item"),
        (st("Кант", "holds", "Опыт", "один", "знание"), "schema_item"),
        (st("Кант", "holds", "Опыт", 1, "знание", qualifiers=[1]), "schema_item"),
        (st("Кант", "holds", "Опыт", 1, "знание", stance="neutral"), "stance_invalid"),
        (st("Кант", "holds", "Опыт", 1, "знание", subject_type="character"), "entity_type"),
        (st("Кант", "lifespan", "Опыт", 1, "знание"), "relation_not_allowed"),
        (st("Кант", "holds", "Опыт", 3, "знание"), "paragraph_out_of_window"),
        (st("Кант", "holds", "Опыт", 0, "знание"), "paragraph_out_of_window"),
        (st("Кант", "holds", "Опыт", 1, "привычкой ума"), "quote_not_found"),
        (st("Кант", "holds", "Опыт", 1, "Кант… опыта"), "quote_too_short"),
    ],
)
def test_item_refused(stand, raw, code):
    with pytest.raises(Skip) as exc:
        item(stand, raw)
    assert exc.value.code == code


def test_unknown_relation_becomes_proposal(stand):
    got = item(stand, st("Кант", "rejects", "Опыт", 1, "всякое знание"))
    assert (got["type"], got["proposed_type"]) == ("influenced_by", "rejects")


def test_reply_items_independent_and_counted(stand, events):
    stand.extract(
        [P1, P2],
        {
            "statements": [
                st("Кант", "holds", "Опыт", 1, "всякое знание начинается с опыта"),
                st("Юм", "holds", "Привычка", 2, "Кант это не писал"),
                st("Иероним", "holds", "Привычка", 9, "причинность"),
                st("Юм", "holds", "Привычка", 2, 7),  # проходит мягкую схему, не вид поля
            ],
            "entities": [{"name": "Зевс", "type": "deity"}],
        },
    )
    row = run_row(stand)
    assert row["created"] == 1 and row["dropped"] == 4
    assert row["drop_reasons"] == {
        "entity_type": 1,
        "paragraph_out_of_window": 1,
        "quote_not_found": 1,
        "schema_item": 1,
    }
    assert len(events.of("knowledge.extraction.dropped")) == 4
    assert stand.onto.entities.find("Иероним") == []  # сирот нет
    assert row["status"] == "done" and row["extractor"] == "gateway"
    assert row["model"] == "flash" and row["fragments"] == 1
    assert row["input_tokens"] > 0 and row["output_tokens"] > 0
    [statement] = stand.statements()
    assert statement["provenance"]["model"] == "flash"


def test_reply_not_object(onto, engine_for, clock, events):
    stand = Stand(onto, engine_for, clock, passed_gateway=True)  # шлюз такой ответ бы отверг
    stand.extract([P1], {"statements": "нет"})
    row = run_row(stand)
    assert row["drop_reasons"] == {"reply_invalid": 1} and row["dropped"] == 1


def test_gateway_schema_soft(stand):
    stand.extract([P1], {"statements": []})
    [body] = stand.llm_transport.bodies
    assert "enum" not in str(body["json_schema"])
    assert body["json_schema"]["properties"]["statements"]["items"]["required"] == [
        "subject",
        "type",
        "object",
        "paragraph",
        "quote",
    ]


def test_gateway_refusal_counted(onto, engine_for, clock, events):
    stand = Stand(onto, engine_for, clock, passed_gateway=True)
    stand.model.replies.append({"statements": []})

    class Busy:
        def handle_request(self, request):
            import httpx

            if request.url.path.endswith("/structured"):
                return httpx.Response(429, json={"kind": "budget_exhausted"})
            return httpx.Response(404, json={})

    stand.llm_transport.inner = Busy()
    vid, _ = stand.version([P1])
    stand.filling.extract_version(vid)
    row = run_row(stand)
    assert row["dropped"] == 1 and row["drop_reasons"] == {"model_budget": 1}
    assert row["model"] is None  # шлюз не сообщил модель роли


def test_failure_closes_run(stand, events, monkeypatch):
    vid, _ = stand.version([P1, P2])

    def boom(*_a, **_k):
        raise RuntimeError("библиотека упала")

    monkeypatch.setattr(stand.filling, "apply_reply", boom)
    with pytest.raises(RuntimeError):
        stand.filling.extract_version(vid)
    row = run_row(stand)
    assert row["status"] == "failed" and row["finished_at"] is not None
    assert row["failure"].startswith("RuntimeError: библиотека упала")
    [failed] = events.of("knowledge.run.failed")
    assert failed["error_kind"] == "RuntimeError"


def test_timeout_from_role_budget(stand):
    model, timeout = stand.filling._role()
    assert model == "flash" and timeout > 30


# --- фрагменты по объёму ---


def paragraphs(lengths, chapter="c1"):
    return [
        {"id": f"p{i}", "chapter_id": chapter, "text": "x" * n, "searchable": True}
        for i, n in enumerate(lengths, start=1)
    ]


def ids(windows):
    return [[p["id"] for p in w] for w in windows]


def test_fragments_by_chars(stand):
    filling = stand.filling
    filling.fragment_size, filling.fragment_chars = 30, 3000
    windows = filling.fragments(paragraphs([130] * 40), None)
    assert len(windows[0]) == 24 and windows[1][0]["id"] == "p24"
    assert windows[-1][-1]["id"] == "p40"


def test_long_paragraph_alone(stand):
    filling = stand.filling
    filling.fragment_size, filling.fragment_chars = 30, 3000
    assert ids(filling.fragments(paragraphs([9000, 10, 10]), None)) == [["p1"], ["p2", "p3"]]


def test_fragment_size_cap_as_before(stand):
    filling = stand.filling
    filling.fragment_size = 2
    assert ids(filling.fragments(paragraphs([1] * 5), None)) == [
        ["p1", "p2"],
        ["p2", "p3"],
        ["p3", "p4"],
        ["p4", "p5"],
    ]
    assert ids(filling.fragments(paragraphs([1] * 5), {"p5"})) == [["p4", "p5"]]


def test_fragments_stay_in_chapter(stand):
    filling = stand.filling
    filling.fragment_size, filling.fragment_chars = 30, 3000
    mixed = paragraphs([10, 10], "a") + paragraphs([10], "b")
    mixed[2]["id"] = "b1"
    assert ids(filling.fragments(mixed, None)) == [["p1", "p2"], ["b1"]]
