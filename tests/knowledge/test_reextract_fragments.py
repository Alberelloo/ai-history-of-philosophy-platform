"""ontology-extraction (reextract-with-claude): «Фрагменты из нескольких абзацев».

Тесты написаны по дельте ``specs/ontology-extraction``: сценарии идут настоящим
``Filling.extract_version`` на стенде ``extraction_stand`` (вывод — какие абзацы получила
модель по запросу шлюзу, журнал — ``knowledge.extraction.fragment`` с ``paragraphs``).
Нормативные правила проверяются property-тестом против эталона, записанного по тексту
дельты (а не по коду), и по каждому правилу отдельно.
"""

from __future__ import annotations

import itertools
import re

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from ..conftest import PROFILES
from .extraction_stand import Stand

req = pytest.mark.req
EO = "ontology-extraction"
FRAGMENTS = "Фрагменты из нескольких абзацев"
FRAGMENT = "knowledge.extraction.fragment"
CTX = {"request_id", "run_id", "service"}


@pytest.fixture
def stand(onto, engine_for, clock) -> Stand:
    return Stand(onto, engine_for, clock)


def sent_windows(stand) -> list[list[int]]:
    """Номера абзацев (с 1), которые ушли модели по каждому запросу, в порядке запросов."""
    result = []
    for body in stand.llm_transport.bodies:
        found = re.findall(r"^\[(\d+)\] ", body["data"]["passages"], flags=re.MULTILINE)
        result.append([int(n) for n in found])
    return result


def windows_ids(stand, vid) -> list[list[str]]:
    data = stand.filling.version(vid)
    return [[p["id"] for p in w] for w in stand.filling.version_fragments(data)]


def fragment_events(events) -> list[dict]:
    return [dict(e.fields) for e in events.of(FRAGMENT)]


@req(EO, FRAGMENTS, scenario="Утверждение на границе")
def test_statement_on_boundary_is_stored_once(stand, events):
    stand.filling.fragment_size = 2
    texts = [
        "Кант писал, что всякое знание начинается с опыта.",
        "Юм считал причинность привычкой ума.",
        "Локк сравнивал душу с чистой доской.",
    ]
    vid, _ids = stand.version(texts)
    same = {
        "subject": "Юм",
        "subject_type": "person",
        "type": "holds",
        "object": "Причинность как привычка",
        "object_type": "position",
        "quote": "причинность привычкой ума",
    }
    # абзац 2 — второй в первом фрагменте [1,2] и первый во втором [2,3]
    stand.model.replies.extend(
        [
            {"statements": [{**same, "paragraph": 2}]},
            {"statements": [{**same, "paragraph": 1}]},
        ]
    )
    stand.filling.extract_version(vid)
    assert sent_windows(stand) == [[1, 2], [1, 2]]
    assert len(stand.statements()) == 1
    assert len(events.of("knowledge.statement.created")) == 1
    assert [e["paragraphs"] for e in fragment_events(events)] == [2, 2]
    assert events.of("knowledge.extraction.dropped") == []


@req(EO, FRAGMENTS, scenario="Короткие абзацы собираются в один фрагмент")
def test_short_paragraphs_gather_by_volume(onto, engine_for, clock, events):
    stand = Stand(onto, engine_for, clock, fragment_size=30, fragment_chars=3000)
    texts = [("п" * 130) for _ in range(40)]
    assert all(len(t) == 130 for t in texts)
    vid, ids = stand.version(texts)
    stand.filling.extract_version(vid)
    first, second = windows_ids(stand, vid)
    # после 23-го длина 2990 < 3000, после 24-го — 3120
    assert len(first) == 24 and first == ids[:24]
    assert second[0] == ids[23] and second == ids[23:]
    assert [e["paragraphs"] for e in fragment_events(events)] == [24, 17]
    assert [set(e) - CTX for e in fragment_events(events)] == [
        {"paragraphs", "created", "dropped"}
    ] * 2
    assert sent_windows(stand) == [list(range(1, 25)), list(range(1, 18))]


@req(EO, FRAGMENTS, scenario="Длинный абзац — отдельный фрагмент")
def test_long_paragraph_is_its_own_fragment(stand, events):
    vid, ids = stand.version(["д" * 9000, "Короткий один.", "Короткий два."])
    stand.filling.extract_version(vid)
    assert windows_ids(stand, vid) == [[ids[0]], [ids[1], ids[2]]]
    assert sent_windows(stand) == [[1], [1, 2]]
    assert [e["paragraphs"] for e in fragment_events(events)] == [1, 2]


@req(EO, FRAGMENTS, scenario="Предел числа абзацев")
def test_paragraph_limit_gives_overlapping_pairs(stand, events):
    stand.filling.fragment_size = 2
    vid, ids = stand.version([f"Короткий абзац {i}." for i in range(1, 6)])
    stand.filling.extract_version(vid)
    assert windows_ids(stand, vid) == [ids[0:2], ids[1:3], ids[2:4], ids[3:5]]
    assert [e["paragraphs"] for e in fragment_events(events)] == [2, 2, 2, 2]


# --- нормативные правила: эталон по тексту дельты ---------------------------------------


def reference(chapters, goal, size):
    """Эталон по тексту требования: набор подряд идущих абзацев главы, пока суммарная длина
    меньше цели и число абзацев меньше предела; следующий — с последнего абзаца, если в
    предыдущем больше одного, иначе со следующего."""
    out = []
    for chapter in chapters:
        start = 0
        while start < len(chapter):
            end = start
            total = 0
            while end < len(chapter) and total < goal and end - start < size:
                total += chapter[end]["len"]
                end += 1
            out.append([p["id"] for p in chapter[start:end]])
            if end >= len(chapter):
                break
            start = end - 1 if end - start > 1 else end
    return out


chapters_strategy = st.lists(
    st.lists(st.integers(0, 5000), min_size=1, max_size=40), min_size=1, max_size=4
)


def build(chapter_lengths):
    chapters = []
    n = 0
    for c, lengths in enumerate(chapter_lengths):
        rows = []
        for length in lengths:
            n += 1
            rows.append({"id": f"p{n}", "chapter_id": f"c{c}", "len": length})
        chapters.append(rows)
    paragraphs = [
        {"id": r["id"], "chapter_id": r["chapter_id"], "text": "я" * r["len"]}
        for rows in chapters
        for r in rows
    ]
    return chapters, paragraphs


SETTINGS = settings(
    parent=PROFILES["pure"],
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    max_examples=300,
)


@req(EO, FRAGMENTS, invariant="Размер, границы главы, покрытие и правило окончания")
@given(
    chapters_strategy,
    st.integers(1, 6000),
    st.integers(1, 12),
)
@SETTINGS
def test_fragment_rules_property(stand, lengths, goal, size):
    chapters, paragraphs = build(lengths)
    stand.filling.fragment_chars = goal
    stand.filling.fragment_size = size
    got = stand.filling.fragments(paragraphs, None)
    by_id = {p["id"]: p for p in paragraphs}
    ids = [[p["id"] for p in w] for w in got]
    # сам эталон, записанный по тексту
    assert ids == reference(chapters, goal, size)
    # правила по отдельности
    for w in got:
        assert 1 <= len(w) <= size  # не меньше одного и не больше fragment_size
        assert len({p["chapter_id"] for p in w}) == 1  # не выходит за главу
    covered = {i for w in ids for i in w}
    assert covered == set(by_id)  # каждый абзац входит хотя бы в один фрагмент
    for chapter in chapters:
        last_id = chapter[-1]["id"]
        for w in got:
            if w[0]["chapter_id"] != chapter[0]["chapter_id"] or w[-1]["id"] == last_id:
                continue
            total = sum(len(p["text"]) for p in w)
            before = total - len(w[-1]["text"])
            # кроме последнего в главе: длина впервые достигла цели или абзацев `size`
            assert (total >= goal and before < goal) or len(w) == size
    # перекрытие: следующий начинается с последнего, если в предыдущем больше одного
    for prev, nxt in itertools.pairwise(got):
        if prev[0]["chapter_id"] != nxt[0]["chapter_id"]:
            continue
        expected = prev[-1]["id"] if len(prev) > 1 else None
        if expected:
            assert nxt[0]["id"] == expected
        else:
            assert nxt[0]["id"] != prev[-1]["id"]


@req(EO, FRAGMENTS, invariant="При changed — только фрагменты с изменённым абзацем")
@given(
    chapters_strategy,
    st.integers(1, 6000),
    st.integers(1, 12),
    st.data(),
)
@SETTINGS
def test_changed_filters_fragments_property(stand, lengths, goal, size, data):
    _chapters, paragraphs = build(lengths)
    stand.filling.fragment_chars = goal
    stand.filling.fragment_size = size
    everything = stand.filling.fragments(paragraphs, None)
    changed = set(
        data.draw(st.lists(st.sampled_from([p["id"] for p in paragraphs]), max_size=6, unique=True))
    )
    got = stand.filling.fragments(paragraphs, changed)
    all_ids = [[p["id"] for p in w] for w in everything]
    assert [[p["id"] for p in w] for w in got] == [w for w in all_ids if changed & set(w)]
    # каждый изменённый абзац обработан
    assert changed <= {p["id"] for w in got for p in w}


@req(EO, FRAGMENTS, invariant="При changed в запуске обрабатываются только фрагменты с изменённым")
def test_changed_limits_extraction_run(stand, events):
    stand.filling.fragment_size = 2
    vid, ids = stand.version([f"Короткий абзац {i}." for i in range(1, 7)])
    stand.filling.extract_version(vid, changed=[ids[4]])
    assert sent_windows(stand) == [[1, 2], [1, 2]]  # [4,5] и [5,6]
    bodies = [b["data"]["passages"] for b in stand.llm_transport.bodies]
    assert "Короткий абзац 5." in bodies[0] and "Короткий абзац 5." in bodies[1]
    assert all("Короткий абзац 1." not in b for b in bodies)
    assert [e["paragraphs"] for e in fragment_events(events)] == [2, 2]
    [run] = stand.filling.runs()
    assert run["fragments"] == 2
