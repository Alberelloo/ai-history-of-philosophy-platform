"""ontology-extraction (reextract-with-claude): «Цитата у каждого утверждения».

По дельте ``specs/ontology-extraction``. Сценарии идут настоящим ``Filling.extract_version``
(вывод — утверждения и подтверждения в базе, журнал — ``knowledge.extraction.dropped`` с
``code``, ``knowledge.statement.created``). Нормативные правила — property-тестами на
порождённых абзацах (типографские замены, внешние кавычки, многоточие, враждебные входы) и
параметризованной проверкой «одна функция сверки во всех четырёх местах».
"""

from __future__ import annotations

import random

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from philograph.knowledge import extraction_codes as codes
from philograph.knowledge import quotes
from philograph.knowledge.statements import Attribution, Evidence, StatementError

from ..conftest import PROFILES
from .extraction_stand import Stand
from .reextract_common import EO, assert_event_keys, dropped, dropped_codes, no_context
from .reextract_common import st as stmt

req = pytest.mark.req
QUOTE = "Цитата у каждого утверждения"
CREATED = "knowledge.statement.created"


@pytest.fixture
def stand(onto, engine_for, clock) -> Stand:
    return Stand(onto, engine_for, clock)


def evidence_quotes(stand) -> list[str]:
    return [e["quote"] for s in stand.statements() for e in s["evidence"]]


# --- сценарии ----------------------------------------------------------------------------


@req(EO, QUOTE, scenario="Цитата не найдена")
def test_quote_not_found(stand, events):
    stand.extract(
        ["Кант писал, что всякое знание начинается с опыта."],
        {"statements": [stmt("Кант", "holds", "Опыт", 1, "Кант отрицал всякий опыт")]},
    )
    assert stand.statements() == []
    [event] = events.of("knowledge.extraction.dropped")
    assert event["code"] == "quote_not_found"
    assert no_context(event.fields) == {"run_id", "reason", "code"}
    assert "Кант отрицал" not in event["reason"]  # текст цитаты в событие не попадает
    assert events.of(CREATED) == []
    assert_event_keys(events)


@req(EO, QUOTE, scenario="Цитата в кавычках и с другим тире")
def test_outer_quotes_and_other_dash(stand, events):
    given = '"Он сказал: - Бог умер"'
    stand.extract(
        ["Он сказал: — Бог умер"],
        {"statements": [stmt("Ницше", "holds", "Смерть Бога", 1, given)]},
    )
    [statement] = stand.statements()
    assert [e["quote"] for e in statement["evidence"]] == [given]  # цитата модели как есть
    assert len(events.of(CREATED)) == 1
    assert events.of("knowledge.extraction.dropped") == []


@req(EO, QUOTE, scenario="Многоточие-пропуск")
def test_ellipsis_gap_in_order_and_reversed(stand, events):
    text = "О, Заратустра, сказали они, ты нашёл счастье своё"
    ordered = "О, Заратустра… ты нашёл счастье своё"
    reversed_ = "ты нашёл счастье своё… О, Заратустра"
    stand.extract(
        [text],
        {
            "statements": [
                stmt("Заратустра", "holds", "Счастье", 1, ordered),
                stmt("Заратустра", "holds", "Иное счастье", 1, reversed_),
            ]
        },
    )
    [statement] = stand.statements()
    assert [e["quote"] for e in statement["evidence"]] == [ordered]
    [event] = events.of("knowledge.extraction.dropped")
    assert event["code"] == "quote_not_found"
    assert len(events.of(CREATED)) == 1


@req(EO, QUOTE, scenario="Мягкий перенос и ударение")
def test_soft_hyphen_and_accent(stand, events):
    stand.extract(
        ["Ум ищет позна­ние и знает, что́ есть истина."],
        {
            "statements": [
                stmt("Кант", "holds", "Познание", 1, "ищет познание и знает"),
                stmt("Кант", "holds", "Истина", 1, "знает, что есть истина"),
            ]
        },
    )
    assert sorted(evidence_quotes(stand)) == sorted(
        ["ищет познание и знает", "знает, что есть истина"]
    )
    assert events.of("knowledge.extraction.dropped") == []


@req(EO, QUOTE, scenario="Сирот нет")
@pytest.mark.parametrize(
    ("statement", "expected_code"),
    [
        (stmt("Иероним", "holds", "Тезис", 1, "Иероним спорил с Августином"), "quote_not_found"),
        (stmt("Иероним", "holds", "Тезис", 9, "Кант писал"), "paragraph_out_of_window"),
        (
            stmt(
                "Иероним",
                "holds",
                "Тезис",
                1,
                "Кант писал… спорил",
            ),
            "quote_too_short",
        ),
    ],
)
def test_no_orphans(stand, events, statement, expected_code):
    stand.extract(
        ["Кант писал, что всякое знание начинается с опыта."], {"statements": [statement]}
    )
    assert stand.entities_of("person") == 0
    assert stand.onto.entities.find("Иероним") == []
    assert stand.onto.entities.find("Тезис") == []
    assert [e["type"] for e in events.of("knowledge.entity.created")] == ["source"]
    assert dropped_codes(events) == [expected_code]
    assert stand.statements() == []


@req(EO, QUOTE, invariant="Отказ по абзацу или цитате не создаёт сущностей, в том числе атрибуции")
def test_refusal_creates_no_entities_with_attribution_and_entities_block(stand, events):
    reply = {
        "statements": [
            stmt(
                "Иероним",
                "holds",
                "Тезис",
                1,
                "этого нет в абзаце",
                attributed_to="Августин",
            ),
            stmt("Иероним", "holds", "Тезис", 7, "Кант писал", attributed_to="Августин"),
        ],
    }
    stand.extract(["Кант писал, что всякое знание начинается с опыта."], reply)
    names = ("Иероним", "Тезис", "Августин")
    assert [stand.onto.entities.find(n) for n in names] == [[], [], []]
    assert sorted(dropped_codes(events)) == ["paragraph_out_of_window", "quote_not_found"]
    assert [e["type"] for e in events.of("knowledge.entity.created")] == ["source"]


# --- одна функция сверки в четырёх местах -----------------------------------------------

PARAGRAPH = "О, Заратустра, сказали они, ты нашёл счастье своё. Он сказал: — Бог умер!"

CASES = [
    ("типографика и кавычки", '"Он сказал: - Бог умер"', True),
    ("ё и регистр", "О, ЗАРАТУСТРА, СКАЗАЛИ ОНИ, ТЫ НАШЕЛ СЧАСТЬЕ СВОЁ", True),
    ("многоточие по порядку", "О, Заратустра… ты нашёл счастье своё", True),
    ("многоточие в скобках", "О, Заратустра (...) ты нашёл счастье своё", True),
    ("части не по порядку", "ты нашёл счастье своё… О, Заратустра", False),
    ("пересказ", "Заратустра сказал, что нашёл счастье", False),
    ("чужое слово", "ты нашёл счастье своё навсегда", False),
    ("перестановка слов", "счастье ты нашёл своё", False),
    ("пустая", "", False),
    ("слишком короткая часть", "О, Заратустра… ты", False),
]


@pytest.mark.parametrize(("label", "quote", "ok"), CASES, ids=[c[0] for c in CASES])
@req(
    EO, QUOTE, invariant="Одна функция сверки: извлечение, Statements.add, перепроверка, датировка"
)
def test_one_check_everywhere(stand, onto, events, label, quote, ok):
    expected = None if ok else (codes.QUOTE_TOO_SHORT if label.startswith("слишком") else "nf")
    # функция сверки
    got = quotes.check(quote, PARAGRAPH)
    assert (got is None) == ok
    if expected not in (None, "nf"):
        assert got == expected
    # 1. извлечение
    vid, [pid] = stand.version([PARAGRAPH])
    stand.model.replies.append({"statements": [stmt("Заратустра", "holds", "Счастье", 1, quote)]})
    stand.filling.extract_version(vid)
    assert (len(stand.statements()) == 1) == ok
    assert len(events.of("knowledge.extraction.dropped")) == (0 if ok else 1)
    if not ok:
        assert events.of("knowledge.extraction.dropped")[0]["code"] == (
            expected if expected != "nf" else "quote_not_found"
        )
    # 2. Statements.add
    zar, happy = (
        onto.person(f"Зар {label}"),
        onto.entities.create("position", [("ru", f"Сч {label}", "primary")]),
    )
    try:
        onto.statements.add(
            zar,
            "holds",
            obj=happy,
            attributions=[Attribution("source", "s_x")],
            evidence=[Evidence(pid, quote, source_id="s_x")],
        )
        added = True
    except StatementError:
        added = False
    assert added == ok
    # 3. перепроверка изменённого абзаца: цитата сверяется с новым текстом тем же правилом
    if ok:
        onto.paragraphs["p_re"] = quote.strip('"')
        a = onto.person(f"Re {label}")
        b = onto.entities.create("position", [("ru", f"Re поз {label}", "primary")])
        onto.statements.add(
            a,
            "holds",
            obj=b,
            attributions=[Attribution("source", "s_re")],
            evidence=[Evidence("p_re", quote.strip('"'), source_id="s_re")],
        )
        onto.paragraphs["p_re"] = PARAGRAPH
        counts = onto.statements.handle_library_event(
            "source.published",
            {
                "event_id": f"e-{label}",
                "source_id": "s_re",
                "removed": [],
                "changed": ["p_re"],
                "redirected": {},
            },
        )
        assert counts["rechecked"] == 1 and counts["lost"] == (0 if got is None else 1)
    else:
        onto.paragraphs["p_re"] = "Совсем другой текст абзаца, где ничего нет."
        a = onto.person(f"Re2 {label}")
        b = onto.entities.create("position", [("ru", f"Re2 поз {label}", "primary")])
        old = "Совсем другой текст абзаца"
        onto.statements.add(
            a,
            "holds",
            obj=b,
            attributions=[Attribution("source", "s_re2")],
            evidence=[Evidence("p_re", old, source_id="s_re2")],
        )
        onto.paragraphs["p_re"] = PARAGRAPH
        counts = onto.statements.handle_library_event(
            "source.published",
            {
                "event_id": f"e2-{label}",
                "source_id": "s_re2",
                "removed": [],
                "changed": ["p_re"],
                "redirected": {},
            },
        )
        assert counts["lost"] == 1
        assert events.where("knowledge.library.event", event_id=f"e2-{label}")[0]["lost"] == 1


DATING_PARAGRAPH = "Иммануил Кант (1724–1804) родился в Кёнигсберге."
DATING_CASES = [
    ("иммануил кант (1724-1804)", True),
    ("«Иммануил Кант (1724–1804)»", True),
    ("Иммануил Кант… (1724–1804)", True),
    ("(1724–1804)… Иммануил Кант", False),
    ("Кант прожил 1724–1804 годы", False),
]


@pytest.mark.parametrize(("quote", "ok"), DATING_CASES)
@req(EO, QUOTE, invariant="Одна функция сверки: цитата датировки (entity-dating)")
def test_dating_uses_same_quote_check(stand, onto, events, quote, ok):
    reply = {
        "statements": [],
        "entities": [
            {
                "name": "Кант",
                "type": "person",
                "dating": {"text": "1724–1804", "paragraph": 1, "quote": quote},
            }
        ],
    }
    stand.extract([DATING_PARAGRAPH], reply)
    assert (quotes.check(quote, DATING_PARAGRAPH) is None) == ok
    created = [s for s in stand.statements() if s["type"] == "lifespan"]
    if ok:
        assert len(created) == 1
        assert [e["quote"] for e in created[0]["evidence"]] == [quote]  # как есть
        assert events.of("knowledge.extraction.dropped") == []
    else:
        assert created == []
        assert dropped_codes(events) == ["dating_quote"]
        assert dropped(events)[0]["reason"].startswith("dating:")


# --- property: сверка на порождённых абзацах ---------------------------------------------

LETTERS = "абвгдежзиклмнопрстуфхцчшщыэюя"
DASHES = "‐‑‒–—―−"
DQUOTES = "«»„“”‟"
SQUOTES = "‘’‚‛"
SPACES = [" ", " ", " ", " ", "  ", "\t", "\n"]
ELLIPSES = ["...", "…", "[...]", "(...)", " … ", " ... ", " [...] ", "…."]

word = st.text(alphabet=LETTERS, min_size=4, max_size=9)
words = st.lists(
    st.text(alphabet=LETTERS, min_size=12, max_size=16), min_size=12, max_size=24, unique=True
)

SETTINGS = settings(
    parent=PROFILES["pure"],
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
    max_examples=400,
)


def with_marks(ws: list[str]) -> str:
    """Абзац со знаками, которые нормализация сводит к общему виду."""
    out = []
    for i, w in enumerate(ws):
        if i % 5 == 1:
            w = w + " - " + w[:0]
        out.append(w)
    return " ".join(out)


def typographic(text: str, rnd: random.Random) -> str:
    """Тот же текст с другими, но эквивалентными по нормализации знаками."""
    out = []
    for ch in text:
        if ch == "-":
            out.append(rnd.choice(DASHES + "-"))
        elif ch == " ":
            out.append(rnd.choice([*SPACES, " "]))
        elif ch == "е":
            out.append(rnd.choice("её"))
        elif ch.islower() and rnd.random() < 0.2:
            out.append(ch.upper())
        else:
            out.append(ch)
    return "".join(out)


def pieces(ws: list[str], rnd: random.Random, count: int) -> list[str]:
    """``count`` непересекающихся частей из подряд идущих слов, по порядку, каждая ≥ 10 знаков."""
    size = max(1, len(ws) // count)
    result = []
    for i in range(count):
        chunk = ws[i * size : (i + 1) * size]
        piece = " ".join(chunk)
        while len(piece) < 10:
            piece += " " + ws[-1]
        result.append(piece)
    return result


@req(EO, QUOTE, invariant="Любая подстрока абзаца находится, в том числе с типографскими заменами")
@given(words, st.integers(0, 10**6), st.data())
@SETTINGS
def test_any_substring_found_property(ws, seed, data):
    rnd = random.Random(seed)
    text = with_marks(ws)
    a = data.draw(st.integers(0, len(text) - 1))
    b = data.draw(st.integers(a + 1, len(text)))
    sub = text[a:b]
    if not sub.strip():
        return
    assert quotes.check(sub, text) is None
    assert quotes.check(typographic(sub, rnd), text) is None
    assert quotes.check(sub, typographic(text, rnd)) is None
    # внешние кавычки любых видов
    left, right = rnd.choice(
        [('"', '"'), ("«", "»"), ("„", "“"), ("“", "”"), ("'", "'"), ("‘", "’")]
    )
    assert quotes.check(left + sub + right, text) is None
    # тот же текст в разложенной (NFD) форме
    import unicodedata

    assert quotes.check(unicodedata.normalize("NFD", sub), text) is None


@req(EO, QUOTE, invariant="Многоточие делит цитату на части: по порядку и без наложения")
@given(words, st.integers(0, 10**6), st.integers(2, 4))
@SETTINGS
def test_ellipsis_parts_property(ws, seed, count):
    rnd = random.Random(seed)
    text = " ".join(ws)
    ps = pieces(ws, rnd, count)
    assert all(len(p) >= 10 for p in ps)
    glue = [rnd.choice(ELLIPSES) for _ in range(count - 1)]
    quote = ps[0] + "".join(g + p for g, p in zip(glue, ps[1:], strict=True))
    assert quotes.check(quote, text) is None
    assert quotes.check(typographic(quote, rnd), text) is None
    assert len(quotes.parts(quote)) == count
    # части не по порядку: первые две меняются местами
    swapped = [ps[1], ps[0], *ps[2:]]
    bad = swapped[0] + "".join(g + p for g, p in zip(glue, swapped[1:], strict=True))
    assert quotes.check(bad, text) == "quote_not_found"
    # часть повторена сверх одного вхождения (наложение/повтор): одно вхождение на два
    assert quotes.check(ps[0] + glue[0] + ps[0], text) == "quote_not_found"
    # слишком короткая часть при многоточии — отказ quote_too_short, даже если слова из абзаца
    short = ps[0] + glue[0] + ws[0][:3]
    assert quotes.check(short, text) == "quote_too_short"
    assert quotes.check(ws[0][:3] + glue[0] + ps[0], text) == "quote_too_short"


@req(EO, QUOTE, invariant="Пересказ, перестановка и чужие слова не проходят сверку")
@given(words, st.integers(0, 10**6))
@SETTINGS
def test_paraphrase_and_extra_words_rejected_property(ws, seed):
    rnd = random.Random(seed)
    text = " ".join(ws)
    start = rnd.randrange(0, len(ws) - 3)
    chunk = ws[start : start + 3]
    assert quotes.check(" ".join(chunk), text) is None
    # перестановка слов
    swapped = [chunk[1], chunk[0], chunk[2]]
    assert quotes.check(" ".join(swapped), text) == "quote_not_found"
    # чужое слово внутри и по краям
    assert quotes.check(" ".join([*chunk, "zzzz"]), text) == "quote_not_found"
    assert quotes.check(" ".join(["zzzz", *chunk]), text) == "quote_not_found"
    assert quotes.check(chunk[0] + " zzzz " + chunk[2], text) == "quote_not_found"
    # пересказ: слова из абзаца, но не подряд (пропуск без многоточия)
    assert quotes.check(chunk[0] + " " + chunk[2], text) == "quote_not_found"
    # цитата длиннее абзаца
    assert quotes.check(text + " " + chunk[0] * 2, text) == "quote_not_found"


HOSTILE = [
    "",
    "   ",
    "...",
    "…",
    "[...]",
    "(...)",
    " ... ",
    '""',
    "«»",
    '"..."',
    "' '",
    "­",
    "́",
    "  ",
]


@pytest.mark.parametrize("quote", HOSTILE)
@req(EO, QUOTE, invariant="Пустая и вырожденная цитата никогда не находится")
def test_degenerate_quotes_never_found(stand, events, quote):
    assert quotes.check(quote, "Кант писал, что всякое знание начинается с опыта.") == (
        "quote_not_found"
    )
    assert quotes.check(quote, None) == "quote_not_found"
    stand.extract(
        ["Кант писал, что всякое знание начинается с опыта."],
        {"statements": [stmt("Кант", "holds", "Опыт", 1, quote)]},
    )
    assert stand.statements() == []
    assert dropped_codes(events) == ["quote_not_found"]


@req(EO, QUOTE, invariant="Части многоточия без наложения: общий кусок не считается дважды")
def test_overlapping_parts_rejected():
    text = "abcdefghijklmnop"
    assert quotes.check("abcdefghij... ghijklmnop", text) == "quote_not_found"
    assert quotes.check("abcdefghij... klmnop qrstu", text) == "quote_not_found"
    assert quotes.check("abcdefghij...klmnop", text) == "quote_too_short"  # вторая часть 6 знаков
    assert quotes.check("abcdefghij... klmnopqrst", text) == "quote_not_found"
    assert quotes.check("abcdefg hij", text) == "quote_not_found"
    assert quotes.check("abcdefghij…efghijklmnop", text) == "quote_not_found"


@req(
    EO,
    QUOTE,
    invariant="Единственная часть короче 10 знаков допустима (минимум — только при многоточии)",
)
def test_single_short_part_allowed():
    assert quotes.check("что", "Он знает, что есть истина") is None
    assert quotes.check("…что…", "Он знает, что есть истина") is None  # одна часть


@req(EO, QUOTE, invariant="В подтверждении хранится цитата модели как есть")
@pytest.mark.parametrize(
    "quote",
    [
        '"Заратустра сказал: - Бог умер"',
        "«заратустра СКАЗАЛ:  — бог\u00a0умер»",
        "Заратустра сказал… и мы его убили",
        "ЗАРАТУСТРА СКАЗАЛ: — БОГ УМЕР, И МЫ ЕГО УБИЛИ",
    ],
)
def test_stored_quote_is_models_as_is(stand, quote):
    stand.extract(
        ["Заратустра сказал: — Бог умер, и мы его убили"],
        {"statements": [stmt("Ницше", "holds", "Смерть Бога", 1, quote)]},
    )
    [statement] = stand.statements()
    assert [e["quote"] for e in statement["evidence"]] == [quote]


@req(EO, QUOTE, invariant="Проверки до сущностей: абзац и цитата проверяются раньше привязки")
def test_checks_precede_entity_resolution(stand, events):
    """Элемент с отказом по цитате и неверным типом сущности (entity_type проверяется в
    _item до цитаты) — код отказа по порядку дельты: тип, затем абзац, затем цитата."""
    text = "Кант писал, что всякое знание начинается с опыта."
    stand.extract(
        [text],
        {
            "statements": [
                stmt(
                    "Кант",
                    "holds",
                    "Опыт",
                    1,
                    "нет такой цитаты в абзаце",
                    subject_type="character",
                ),
                stmt("Кант", "holds", "Опыт", 5, "нет такой цитаты в абзаце"),
                stmt("Кант", "holds", "Опыт", 1, "нет такой цитаты в абзаце"),
            ]
        },
    )
    assert dropped_codes(events) == ["entity_type", "paragraph_out_of_window", "quote_not_found"]
    assert stand.entities_of("person") == 0
    assert_event_keys(events)


def test_codes_closed_list_contains_quote_codes():
    assert {codes.QUOTE_NOT_FOUND, codes.QUOTE_TOO_SHORT} <= codes.CODES
