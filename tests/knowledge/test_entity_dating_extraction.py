"""entity-dating (improve-extraction-naming): «Извлечение дат».

По дельте ``openspec/changes/improve-extraction-naming/specs/entity-dating``. Извлечение —
настоящий ``Filling.extract_version`` на стенде ``extraction_stand`` (модель — фейк шлюза,
библиотека — поддельный транспорт, сеть запрещена). Вывод — утверждение ``lifespan``/``dating``
и ``primary.dates`` сущности, журнал — ``knowledge.statement.created`` и
``knowledge.extraction.dropped``. Property-тест берёт пары из ``strategies.datings``.
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, example, given, settings

from philograph.knowledge.dates import span

from ..conftest import PROFILES
from .extraction_stand import Stand
from .strategies import assert_dropped_codes, datings, sentinel

req = pytest.mark.req
ED = "entity-dating"
EXTRACT = "Извлечение дат"
CTX = {"request_id", "run_id", "service"}
DROPPED = "knowledge.extraction.dropped"
STATEMENT = "knowledge.statement.created"


@pytest.fixture
def stand(onto, engine_for, clock) -> Stand:
    return Stand(onto, engine_for, clock)


def entity_of(stand, name: str) -> str:
    [found] = stand.onto.entities.find(name)
    return found["id"] if isinstance(found, dict) else found


def datings_of(stand, entity_id: str) -> list[dict]:
    return [
        s
        for s in stand.statements()
        if s["subject"] == entity_id and s["type"] in ("lifespan", "dating")
    ]


def dropped(events) -> list[dict]:
    return [dict(e.fields) for e in events.of(DROPPED)]


def no_token(events, token: str) -> None:
    for event in events.items:
        assert token not in repr(event.fields), event.name


def reply(name: str, type_: str, dating: dict, statements=None) -> dict:
    return {
        "statements": statements or [],
        "entities": [{"name": name, "type": type_, "dating": dating}],
    }


# --- сценарии --------------------------------------------------------------------------


@req(ED, EXTRACT, scenario="Дата жизни в тексте")
def test_life_dates_in_text(stand, onto, events):
    token = sentinel()
    _vid, [pid] = stand.extract(
        [f"Иммануил Кант (1724–1804) родился в Кёнигсберге. {token}"],
        reply("Кант", "person", {"text": "1724–1804", "paragraph": 1, "quote": "Кант (1724–1804)"}),
    )
    kant = entity_of(stand, "Кант")
    dates = onto.entities.get(kant)["primary"]["dates"]
    assert span(dates) == (1724, 1804)
    assert dates["precision"] == "year" and dates["original"] == "1724–1804"
    [lifespan] = datings_of(stand, kant)
    assert lifespan["type"] == "lifespan"
    assert [(e["paragraph_id"], e["quote"]) for e in lifespan["evidence"]] == [
        (pid, "Кант (1724–1804)")
    ]
    assert [a["who_kind"] for a in lifespan["attributions"]] == ["source"]
    assert lifespan["provenance"]["method"] == "extracted"
    assert len(events.where(STATEMENT, type="lifespan")) == 1
    events.assert_none(DROPPED)
    no_token(events, token)


@req(ED, EXTRACT, scenario="Дата до нашей эры")
def test_bc_dates(stand, onto, events):
    stand.extract(
        ["Платон (427–347 до н. э.) основал Академию."],
        reply(
            "Платон",
            "person",
            {"text": "427–347 до н. э.", "paragraph": 1, "quote": "Платон (427–347 до н. э.)"},
        ),
    )
    plato = entity_of(stand, "Платон")
    dates = onto.entities.get(plato)["primary"]["dates"]
    assert span(dates) == (-426, -346)
    assert dates["precision"] == "year"
    assert len(events.where(STATEMENT, type="lifespan")) == 1


@req(ED, EXTRACT, scenario="Год произведения")
def test_work_year(stand, onto, events):
    stand.extract(
        ["„Критика чистого разума“ (1781) вышла в Риге."],
        reply(
            "Критика чистого разума",
            "work",
            {"text": "1781", "paragraph": 1, "quote": "„Критика чистого разума“ (1781)"},
        ),
    )
    work = entity_of(stand, "Критика чистого разума")
    [dating] = datings_of(stand, work)
    assert dating["type"] == "dating"
    assert span(onto.entities.get(work)["primary"]["dates"]) == (1781, 1781)
    assert len(events.where(STATEMENT, type="dating")) == 1


@req(ED, EXTRACT, scenario="Века у события")
def test_event_century(stand, onto, events):
    stand.extract(
        ["В V в. до н. э. софисты учили за плату."],
        reply(
            "Софистическое движение",
            "event",
            {"text": "V в. до н. э.", "paragraph": 1, "quote": "В V в. до н. э."},
        ),
    )
    event = entity_of(stand, "Софистическое движение")
    dates = onto.entities.get(event)["primary"]["dates"]
    assert span(dates) == (-450, -450)
    assert dates["precision"] == "century"
    assert len(events.where(STATEMENT, type="dating")) == 1


def _rejected(stand, events, paragraphs, name, type_, dating, reason, statements=None):
    stand.extract(paragraphs, reply(name, type_, dating, statements))
    entity = entity_of(stand, name)
    assert datings_of(stand, entity) == []
    assert "dates" not in (stand.onto.entities.get(entity)["primary"] or {})
    [drop] = dropped(events)
    assert drop["reason"] == reason
    assert set(drop) - {"request_id", "service"} == {"run_id", "reason"}
    if not statements:
        events.assert_none(STATEMENT)
    return entity


@req(ED, EXTRACT, scenario="Века нет в цитате")
def test_century_not_in_quote(stand, events):
    _rejected(
        stand,
        events,
        ["В V в. до н. э. софисты учили за плату."],
        "Софистика",
        "event",
        {"text": "V в. до н. э.", "paragraph": 1, "quote": "софисты учили за плату"},
        "dating:not_in_quote",
    )


@req(ED, EXTRACT, scenario="Эра не совпадает")
def test_era_mismatch(stand, events):
    _rejected(
        stand,
        events,
        ["«Государство» (ок. 375 до н. э.) — диалог Платона."],
        "Государство",
        "work",
        {"text": "375", "paragraph": 1, "quote": "(ок. 375 до н. э.)"},
        "dating:era",
    )


@req(ED, EXTRACT, scenario="Года нет в цитате")
def test_year_not_in_quote(stand, onto, events):
    statement = {
        "subject": "Кант",
        "subject_type": "person",
        "type": "holds",
        "object": "Трансцендентальный идеализм",
        "object_type": "position",
        "paragraph": 1,
        "quote": "Кант родился в Кёнигсберге",
    }
    kant = _rejected(
        stand,
        events,
        ["Кант родился в Кёнигсберге и учил трансцендентальному идеализму."],
        "Кант",
        "person",
        {"text": "1724–1804", "paragraph": 1, "quote": "Кант родился в Кёнигсберге"},
        "dating:not_in_quote",
        statements=[statement],
    )
    holds = [s for s in stand.statements() if s["type"] == "holds"]
    assert [s["subject"] for s in holds] == [kant]
    assert len(events.where(STATEMENT, type="holds")) == 1
    events.assert_none("knowledge.entity.rejected")


@req(ED, EXTRACT, scenario="Число внутри другого числа")
def test_number_inside_number(stand, events):
    _rejected(
        stand,
        events,
        ["Трактат разошёлся в 17245 экземплярах."],
        "Трактат о природе",
        "work",
        {"text": "1724", "paragraph": 1, "quote": "в 17245 экземплярах"},
        "dating:not_in_quote",
    )


@req(ED, EXTRACT, scenario="Один год у персоны")
def test_single_year_person(stand, events):
    _rejected(
        stand,
        events,
        ["Кант родился в 1724 году в Кёнигсберге."],
        "Кант",
        "person",
        {"text": "1724", "paragraph": 1, "quote": "в 1724 году"},
        "dating:single_year",
    )


@req(ED, EXTRACT, scenario="Неразборчивая дата")
def test_unparsed(stand, onto, events):
    stand.extract(
        ["Он жил в эпоху Просвещения.", "Сенека (4 до н. э. – 65) писал письма."],
        {
            "statements": [],
            "entities": [
                {
                    "name": "Вольтер",
                    "type": "person",
                    "dating": {
                        "text": "в эпоху Просвещения",
                        "paragraph": 1,
                        "quote": "Он жил в эпоху Просвещения",
                    },
                },
                {
                    "name": "Сенека",
                    "type": "person",
                    "dating": {
                        "text": "4 до н. э. – 65",
                        "paragraph": 2,
                        "quote": "Сенека (4 до н. э. – 65)",
                    },
                },
            ],
        },
    )
    for name in ("Вольтер", "Сенека"):
        assert datings_of(stand, entity_of(stand, name)) == []
    assert [d["reason"] for d in dropped(events)] == ["dating:unparsed"] * 2
    events.assert_none(STATEMENT)


@req(ED, EXTRACT, scenario="Абзац вне фрагмента")
def test_paragraph_outside_fragment(stand, events):
    paragraphs = [f"Абзац {i}: Юм (1711–1776) писал." for i in range(1, 5)]
    stand.extract(
        paragraphs,
        {
            "statements": [],
            "entities": [
                {
                    "name": name,
                    "type": "person",
                    "dating": {"text": "1711–1776", "paragraph": p, "quote": "Юм (1711–1776)"},
                }
                for name, p in (("Юм", 0), ("Дэвид Юм", 5))
            ],
        },
    )
    for name in ("Юм", "Дэвид Юм"):
        assert datings_of(stand, entity_of(stand, name)) == []
    assert [d["reason"] for d in dropped(events)] == ["dating:paragraph"] * 2
    events.assert_none(STATEMENT)


# --- инвариант ---------------------------------------------------------------------------


def _ints(text: str) -> set[int]:
    """Целые числа по границам цифр — своим проходом, без регулярного выражения модуля."""
    found, current = set(), ""
    for ch in text + " ":
        if ch.isdigit():
            current += ch
        elif current:
            if len(current) <= 4:
                found.add(int(current))
            current = ""
    return found


def _case(text, quote, paragraph_text, reason, expect, type_="work", paragraph=1, n=1):
    paragraphs = [f"Пустой абзац {i}." for i in range(1, n + 1)]
    paragraphs[min(max(paragraph, 1), n) - 1] = paragraph_text
    return {
        "dating": {"text": text, "paragraph": paragraph, "quote": quote},
        "paragraphs": paragraphs,
        "type": type_,
        "person": type_ == "person",
        "reason": reason,
        "expect": expect,
        "statement": "lifespan" if type_ == "person" else "dating",
        "token": "SENTINELexample",
    }


EXAMPLES = [
    # J3: обратный интервал нашей эры — формата нет в таблице
    _case(
        "1804–1724", "жил 1804–1724", "Кант жил 1804–1724 годы.", "dating:unparsed", None, "person"
    ),
    _case("ок. 1690-1689", "ок. 1690-1689", "Трактат (ок. 1690-1689).", "dating:unparsed", None),
    _case(
        "V в. до н. э.",
        "софисты учили",
        "софисты учили за плату",
        "dating:not_in_quote",
        None,
        "event",
    ),
    _case("375", "(ок. 375 до н. э.)", "Диалог (ок. 375 до н. э.).", "dating:era", None),
    _case("1724", "в 17245 экземплярах", "в 17245 экземплярах", "dating:not_in_quote", None),
    _case(
        "1724–1804",
        "Кант (1724–1804)",
        "Кант (1724–1804)",
        "dating:paragraph",
        None,
        "person",
        0,
        4,
    ),
    _case(
        "1724–1804",
        "Кант (1724–1804)",
        "Кант (1724–1804)",
        "dating:paragraph",
        None,
        "person",
        5,
        4,
    ),
    _case("1724", "в 1724 году", "в 1724 году", "dating:single_year", None, "person"),
    _case(
        "4 до н. э. – 65", "(4 до н. э. – 65)", "Сенека (4 до н. э. – 65)", "dating:unparsed", None
    ),
    _case(
        "427–347 до н. э.",
        "(427–347 до н. э.)",
        "Платон (427–347 до н. э.)",
        None,
        {"edges": (-426, -426, -346, -346), "span": (-426, -346), "precision": "year"},
        "person",
    ),
    _case(
        "ок. 470 до н. э.",
        "ок. 470 до нашей эры",
        "Родился ок. 470 до нашей эры.",
        None,
        {"edges": (-479, -459, -479, -459), "span": (-469, -469), "precision": "approx"},
    ),
    _case(
        "XVII в.",
        "в XVII в.",
        "в XVII в. наука",
        None,
        {"edges": (1601, None, None, 1700), "span": (1650, 1650), "precision": "century"},
    ),
    _case("XVII в.", "в XVIII в.", "в XVIII в. наука", "dating:not_in_quote", None),
    # --- аудит пунктов (О21): строки таблицы форматов ---
    # «Г»
    _case(
        "1781",
        "„Критика“ (1781)",
        "„Критика“ (1781)",
        None,
        {"edges": (1781, 1781, 1781, 1781), "span": (1781, 1781), "precision": "year"},
    ),
    # «Г1–Г2»: пробелы вокруг тире и любое из трёх тире
    _case(
        "1724 - 1804",
        "Кант (1724 - 1804)",
        "Кант (1724 - 1804)",
        None,
        {"edges": (1724, 1724, 1804, 1804), "span": (1724, 1804), "precision": "year"},
        "person",
    ),
    _case(
        "1724—1804",
        "Кант (1724—1804)",
        "Кант (1724—1804)",
        None,
        {"edges": (1724, 1724, 1804, 1804), "span": (1724, 1804), "precision": "year"},
        "person",
    ),
    # «ок. Г»: все четыре маркера «около», без учёта регистра
    *(
        _case(
            text,
            "Трактат (" + text + ")",
            "Трактат (" + text + ")",
            None,
            {"edges": (1770, 1790, 1770, 1790), "span": (1780, 1780), "precision": "approx"},
        )
        for text in ("ок. 1780", "около 1780", "c. 1780", "circa 1780", "ОК. 1780", "Circa 1780")
    ),
    # «ок. Г1–Г2» с эрой: Г1 ± 5, Г2 ± 5, границы упорядочены
    _case(
        "ок. 430–420 до н.э.",
        "ок. 430–420 до н. э.",
        "Диалог ок. 430–420 до н. э.",
        None,
        {"edges": (-434, -424, -424, -414), "span": (-429, -419), "precision": "approx"},
    ),
    # «Г» с эрой, маркер эры «до н.э.» без пробела
    _case(
        "375 до н.э.",
        "(375 до н. э.)",
        "Диалог Платона (375 до н. э.)",
        None,
        {"edges": (-374, -374, -374, -374), "span": (-374, -374), "precision": "year"},
    ),
    # «R в.»: верхняя граница таблицы (XXI), регистр
    _case(
        "XXI в.",
        "в XXI в.",
        "в XXI в. наука",
        None,
        {"edges": (2001, None, None, 2100), "span": (2050, 2050), "precision": "century"},
        "event",
    ),
    _case(
        "xvii в.",
        "в XVII в.",
        "Событие в XVII в. наука",
        None,
        {"edges": (1601, None, None, 1700), "span": (1650, 1650), "precision": "century"},
        "event",
    ),
    # «R в. до н. э.»: 1 − R·100 … 1 − ((R−1)·100+1)
    _case(
        "V в. до н. э.",
        "В V в. до н. э.",
        "В V в. до н. э. софисты учили",
        None,
        {"edges": (-499, None, None, -400), "span": (-450, -450), "precision": "century"},
        "event",
    ),
    # границы года 1…2100
    _case(
        "2100",
        "в 2100 году",
        "в 2100 году",
        None,
        {"edges": (2100, 2100, 2100, 2100), "span": (2100, 2100), "precision": "year"},
    ),
    _case(
        "1",
        "в 1 году",
        "в 1 году",
        None,
        {"edges": (1, 1, 1, 1), "span": (1, 1), "precision": "year"},
    ),
    # --- не из таблицы: dating:unparsed ---
    *(
        _case(text, "жил " + text, "жил " + text, "dating:unparsed", None)
        for text in (
            "2101",
            "0",
            "+1724",
            "XXII в.",
            "XVII в. – XVIII в.",
            "XVII–XVIII в.",
            "XVII - XVIII в. до н. э.",
            "4 до н. э. – 65",
            "470 до н. э. – 399",
            "XVII–XVIII вв.",
            "12 мая 1724",
            "март 1724",
            "1724 г.",
            "в эпоху Просвещения",
            "1804–1724",
        )
    ),
    # --- первая по порядку из двух несработавших ---
    _case(  # paragraph раньше quote
        "1724–1804",
        "Кант (1724–1804) и другое",
        "Кант (1724–1804)",
        "dating:paragraph",
        None,
        "person",
        0,
        2,
    ),
    _case(  # quote раньше unparsed
        "в эпоху Просвещения",
        "в эпоху Просвещения и другое",
        "в эпоху Просвещения",
        "dating:quote",
        None,
    ),
    _case(  # unparsed раньше not_in_quote
        "12 мая 1724", "жил в Кёнигсберге", "жил в Кёнигсберге", "dating:unparsed", None
    ),
    _case(  # not_in_quote раньше era
        "375 до н. э.", "(ок. 380)", "Диалог (ок. 380)", "dating:not_in_quote", None
    ),
    _case(  # era раньше single_year
        "1724", "в 1724 до нашей эры", "в 1724 до нашей эры", "dating:era", None, "person"
    ),
    _case(  # not_in_quote раньше single_year
        "1724", "в 1725 году", "в 1725 году", "dating:not_in_quote", None, "person"
    ),
    # --- один год и век у персоны: single_year ---
    _case("ок. 1724", "ок. 1724", "родился ок. 1724", "dating:single_year", None, "person"),
    _case("XVIII в.", "в XVIII в.", "жил в XVIII в.", "dating:single_year", None, "person"),
    # --- правило поиска цитаты: регистр, ё/е, пробелы ---
    _case(
        "1724–1804",
        "кант  (1724–1804)",
        "КАНТ (1724–1804) жил в Кёнигсберге",
        None,
        {"edges": (1724, 1724, 1804, 1804), "span": (1724, 1804), "precision": "year"},
        "person",
    ),
    _case(
        "1781",
        "Кёнигсберг (1781)",
        "в кенигсберг (1781) вышла",
        None,
        {"edges": (1781, 1781, 1781, 1781), "span": (1781, 1781), "precision": "year"},
    ),
    # --- эра в цитате без эры в тексте и наоборот ---
    _case("375", "(375 до н. э.)", "Диалог (375 до н. э.)", "dating:era", None),
    _case("375 до н. э.", "(375)", "Диалог (375)", "dating:era", None),
    # --- числа по границам цифр и римское слово целиком ---
    _case("1724–1804", "в 1724 и 18041", "в 1724 и 18041", "dating:not_in_quote", None, "person"),
    _case("XVII в.", "в XVIII в.", "в XVIII в.", "dating:not_in_quote", None, "event"),
    _case(
        "ок. 1739–1740",
        "ок. 1739–1740",
        "Трактат ок. 1739–1740 гг.",
        None,
        {"edges": (1734, 1744, 1735, 1745), "span": (1739, 1740), "precision": "approx"},
    ),
]


def _with_examples(test):
    for case in EXAMPLES:
        test = example(case)(test)
    return test


@req(ED, EXTRACT, invariant="Тип без датировки в реестре — отказ dating:type (О15)")
def test_dating_of_type_not_allowed(stand, onto, events):
    """О15: датировка понятия — реестр не разрешает ``dating`` для ``concept``; причина — код."""
    token = sentinel()
    text = f"Учение о субстанции сложилось в 1641 году. {token}"
    stand.extract(
        [text],
        {
            "statements": [
                {
                    "subject": "Субстанция",
                    "subject_type": "concept",
                    "type": "opposed_to",
                    "object": "Акциденция",
                    "object_type": "concept",
                    "paragraph": 1,
                    "quote": "Учение о субстанции",
                }
            ],
            "entities": [
                {
                    "name": "Субстанция",
                    "type": "concept",
                    "dating": {"text": "1641", "paragraph": 1, "quote": "в 1641 году"},
                }
            ],
        },
    )
    concept = entity_of(stand, "Субстанция")
    assert onto.entities.get(concept)["type"] == "concept"  # сущность и связь не отменены
    assert datings_of(stand, concept) == []
    assert "dates" not in onto.entities.get(concept)["primary"]
    assert [s["type"] for s in stand.statements() if s["subject"] == concept] == ["opposed_to"]
    [drop] = dropped(events)
    assert drop["reason"] == "dating:type"
    assert drop["run_id"]
    no_token(events, token)


@req(ED, EXTRACT, invariant="Сущность не определена — dating:unresolved, без второй привязки (О18)")
def test_dating_of_unresolved_entity(stand, onto, clock, events):
    """Неоднозначное название в утверждении и в датировке: один пункт ``ambiguous_link``,
    ``entity:ambiguous`` для утверждения и ``dating:unresolved`` для датировки; отклонённое
    название с датировкой — ``entity:<причина>`` и ``dating:unresolved``."""
    from philograph.knowledge.review import Review
    from philograph.operator.access import ActionLog

    onto.person("Бэкон", "1214", "1292")
    onto.person("Бэкон", "1561", "1626")
    token = sentinel()
    before = {s["id"] for s in stand.statements()}
    events.clear()
    stand.extract(
        [f"Бэкон (1561–1626) ценил опыт. Об этом знают и children (1700). {token}"],
        {
            "statements": [
                {
                    "subject": "Бэкон",
                    "subject_type": "person",
                    "type": "holds",
                    "object": "Опыт",
                    "object_type": "position",
                    "paragraph": 1,
                    "quote": "Бэкон (1561–1626) ценил опыт",
                }
            ],
            "entities": [
                {
                    "name": "Бэкон",
                    "type": "person",
                    "dating": {"text": "1561–1626", "paragraph": 1, "quote": "Бэкон (1561–1626)"},
                },
                {
                    "name": "children",
                    "type": "person",
                    "dating": {"text": "1700", "paragraph": 1, "quote": "children (1700)"},
                },
            ],
        },
    )
    review = Review(onto.statements, ActionLog(onto.statements.engine, clock))
    assert len(review.queue(kind="ambiguous_link")) == 1
    assert sorted(d["reason"] for d in dropped(events)) == sorted(
        ["entity:ambiguous", "dating:unresolved", "dating:unresolved"]
    )
    assert [s for s in stand.statements() if s["id"] not in before] == []
    assert_dropped_codes(events)
    no_token(events, token)


@req(ED, EXTRACT, scenario="Инвариант датировки")
@req(ED, EXTRACT, invariant="Записана по таблице либо отклонена одной причиной")
@settings(parent=PROFILES["ci"], suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(datings())
@_with_examples
def test_dating_invariant(stand, onto, events, case):
    stand.reset()
    events.clear()
    name = "Иммануил Кант" if case["person"] else "Опорная сущность"
    stand.extract(case["paragraphs"], reply(name, case["type"], case["dating"]))
    entity = entity_of(stand, name)
    rows = datings_of(stand, entity)
    if case["reason"] is None:
        expect = case["expect"]
        [row] = rows
        assert row["type"] == case["statement"]
        value = row["value"]
        edges = (
            value["earliest_start"],
            value["latest_start"],
            value["earliest_end"],
            value["latest_end"],
        )
        assert all(e is None or e == g for e, g in zip(expect["edges"], edges, strict=True)), (
            expect,
            value,
        )
        dates = onto.entities.get(entity)["primary"]["dates"]
        assert span(dates) == expect["span"]
        assert dates["precision"] == expect["precision"]
        assert _ints(case["dating"]["text"]) <= _ints(case["dating"]["quote"])
        assert [e["quote"] for e in row["evidence"]] == [case["dating"]["quote"]]
        assert len(events.where(STATEMENT, type=case["statement"])) == 1
        events.assert_none(DROPPED)
    else:
        assert rows == []
        [drop] = dropped(events)
        assert drop["reason"] == case["reason"]
        events.assert_none(STATEMENT)
    no_token(events, case["token"])
    assert_dropped_codes(events)


@req(ED, EXTRACT, invariant="Проверка датировки по порядку причин, чистая функция")
@settings(parent=PROFILES["pure"])
@given(datings())
@_with_examples
def test_dating_check_any_input(case):
    from philograph.knowledge import dating

    d = case["dating"]
    result = dating.check(
        d["text"], d["quote"], d["paragraph"], case["paragraphs"], is_person=case["person"]
    )
    if case["reason"] is not None:
        assert result == case["reason"]
        return
    assert not isinstance(result, str), result
    expect = case["expect"]
    value = result.to_json()
    edges = (
        value["earliest_start"],
        value["latest_start"],
        value["earliest_end"],
        value["latest_end"],
    )
    assert all(e is None or e == g for e, g in zip(expect["edges"], edges, strict=True)), (
        expect,
        value,
    )
    assert span(value) == expect["span"]
    assert value["precision"] == expect["precision"]
