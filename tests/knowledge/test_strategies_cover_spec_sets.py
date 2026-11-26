"""О23: каждое множество, которое задаёт спецификация, перечислено в стратегиях целиком.

Множества переписаны здесь из дельт спецификаций (entity-naming, entity-dating, person-quality)
и из ``knowledge/naming_rules.yaml`` руками, без импорта проверяемого кода. Для каждого
элемента множества генератор должен уметь его породить: ``hypothesis.find`` ищет пример с этим
элементом, иначе тест падает (``NoSuchExample``) — пробел в области входов генератора.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import pytest
import yaml
from hypothesis import HealthCheck, find, settings

from . import strategies as S
from .test_entity_naming import raw_names

req = pytest.mark.req
NM, ED, PQ = "entity-naming", "entity-dating", "person-quality"
LANG, VALID = "Язык названий сущностей", "Валидность названий сущностей"
DATING = "Извлечение дат"

FIND = settings(
    max_examples=4000,
    database=None,
    deadline=None,
    suppress_health_check=list(HealthCheck),
)

# --- множества из спецификаций (переписаны вручную) -------------------------------------

ROMAN_LETTERS = set("IVXLCDM")  # entity-naming п. 1: ^[IVXLCDM]+$, только заглавные
EDGE_MARKS = set(".,;:!?()[]«»\"'„“”")  # п. 1: знаки по краям слова
LANG_SCRIPTS = {  # п. 5
    "ru": "cyrillic",
    "en": "latin",
    "de": "latin",
    "fr": "latin",
    "la": "latin",
    "it": "latin",
    "el": "greek",
    "grc": "greek",
}
WHITESPACE = {" ", "\t", "\n", " ", " "}  # «пробельные символы» (str.split), О23
REASONS = ("empty", "number", "sentence", "not_a_name", "stopword")
LONG_TYPES = {"work", "event", "idea_event", "phenomenon"}
LIMITS = {"default": (6, 80), "long": (12, 160)}
PARTICLES = {"de", "d", "van", "von", "ibn", "al", "де", "д", "фон", "ван", "ибн", "аль"}
JOINERS = {"-", "'", "’"}

DASHES = {"–", "—", "-"}  # entity-dating: тире
APPROX = {"ок.", "около", "c.", "circa"}
ERA_TEXT = {"до н. э.", "до н.э."}
ERA_QUOTE = ERA_TEXT | {"до нашей эры"}
CENTURIES = [
    "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI",
    "XII", "XIII", "XIV", "XV", "XVI", "XVII", "XVIII", "XIX", "XX", "XXI",
]  # fmt: skip
DATING_ORDER = (
    "dating:paragraph",
    "dating:quote",
    "dating:unparsed",
    "dating:not_in_quote",
    "dating:era",
    "dating:single_year",
)
WD_PRECISIONS = (11, 10, 9, 8, 7, 6)  # таблица точностей Wikidata; ниже 6 — bad_value
WD_RANKS = {"normal", "preferred", "deprecated"}
DECISIONS = {"pending", "accepted", "auto", "rejected"}

MERGE_GENERATED = ("merge:name", "merge:model_pair", "merge:qid_confirmed")
QUEUE_GENERATED = (
    "review:dates",
    "review:decided_conflict",
    "review:qid_cluster",
    "review:single_name",
    "review:variant",
)
# Коды person-quality, которые дают не генератор лиц, а решения человека и команда QID:
# проверяются сценариями и таблицей шагов правила (по тексту тестов).
SCENARIO_CODES = (
    "merge:review",
    "review:qid_candidate",
    "review:qid_taken",
    "apart:decided",
    "apart:none",
    "apart:qid",
    "apart:type",
)

HERE = Path(__file__).parent


def _script(ch: str) -> str | None:
    if unicodedata.category(ch)[0] != "L":
        return None
    code = ord(ch)
    if 0x0400 <= code <= 0x052F:
        return "cyrillic"
    if unicodedata.name(ch, "").startswith("LATIN"):
        return "latin"
    if 0x0370 <= code <= 0x03FF or 0x1F00 <= code <= 0x1FFF:
        return "greek"
    return "other"


def _words(text: str) -> list[str]:
    return [w.strip(".,;:!?()[]«»\"'„“”") for w in text.split()]


def _text(case) -> str:
    return case[0][0]


def _find(strategy, predicate):
    return find(strategy, predicate, settings=FIND)


# --- entity-naming ----------------------------------------------------------------------


@req(
    NM,
    LANG,
    invariant="Генератор языка порождает каждую букву римских чисел и похожие вне множества (О23)",
)
@pytest.mark.parametrize("letter", sorted(ROMAN_LETTERS))
def test_roman_letters_generated(letter):
    assert set(S.ROMAN_LETTERS) == ROMAN_LETTERS
    _find(
        S.scripts_mix(),
        lambda c: any(re.fullmatch("[IVXLCDM]+", w) and letter in w for w in _words(_text(c))),
    )
    # «похожие, но вне множества»: та же буква строчной в слове не целиком из заглавных
    _find(
        S.scripts_mix(),
        lambda c: any(
            letter.lower() in w and set(w.upper()) <= ROMAN_LETTERS and not w.isupper()
            for w in _words(_text(c))
        ),
    )


@req(NM, LANG, invariant="Генератор языка порождает каждый знак края слова (О23)")
@pytest.mark.parametrize("mark", sorted(EDGE_MARKS))
def test_edge_marks_generated(mark):
    assert set(S.EDGE_MARKS) == EDGE_MARKS
    _find(S.scripts_mix(), lambda c: mark in _text(c))


@req(NM, LANG, invariant="Генератор языка порождает каждую письменность и границы диапазонов (О23)")
@pytest.mark.parametrize(
    "ch",
    ["Ѐ", "ѐ", "ԯ", "ͱ", "Ͽ", "ἀ", "ῳ", "ﬁ", "ａ"],
)
def test_script_boundaries_generated(ch):
    def has(c) -> bool:
        return ch in _text(c) or ch.lower() in _text(c) or ch.upper() in _text(c)

    _find(S.scripts_mix(), has)


@req(NM, LANG, invariant="Генератор языка: все письменности и все языки таблицы п. 5 (О23)")
def test_scripts_and_langs_generated():
    for script in ("cyrillic", "latin", "greek", "other"):
        _find(S.scripts_mix(), lambda c, s=script: any(_script(ch) == s for ch in _text(c)))
    assert set(LANG_SCRIPTS) <= set(S.GIVEN_LANGS)
    assert {g for g in S.GIVEN_LANGS if g not in LANG_SCRIPTS} - {None}, "языки вне таблицы"
    assert {k: S.LANG_SCRIPT[k] for k in LANG_SCRIPTS} == LANG_SCRIPTS


@req(NM, VALID, invariant="Генераторы названий: каждый пробельный символ внутри и по краям (О23)")
@pytest.mark.parametrize("space", sorted(WHITESPACE))
def test_whitespace_generated(space):
    assert set(S.WHITESPACE) >= WHITESPACE
    _find(S.scripts_mix(), lambda c: space in _text(c).strip())
    _find(raw_names(), lambda raw: raw.startswith(space) or raw.endswith(space))


@req(NM, VALID, invariant="Генераторы названий: NFC ≠ NFKC и NFC ≠ NFD (О23, O5)")
def test_normal_forms_distinguished():
    def nfkc_differs(text: str) -> bool:
        nfc = unicodedata.normalize("NFC", text)
        return unicodedata.normalize("NFKC", nfc) != nfc

    _find(S.scripts_mix(), lambda c: nfkc_differs(_text(c)))
    _find(raw_names(), nfkc_differs)
    _find(raw_names(), lambda raw: unicodedata.normalize("NFC", raw) != raw)
    # лигатура: NFKC меняет число кодовых точек; внутренний NBSP/EM SPACE: NFKC → пробел
    _find(raw_names(), lambda raw: "ﬁ" in raw)
    _find(raw_names(pool=True), lambda raw: " " in raw.strip() or " " in raw.strip())


@req(NM, VALID, invariant="Генератор правил порождает каждую причину (О23)")
@pytest.mark.parametrize("reason", [*REASONS, None])
def test_reasons_generated(reason):
    _find(S.names_with_reason(), lambda c: c[1] == reason)


def test_rule_data_sets():
    """Пределы, типы, частицы — как в спецификации и в naming_rules.yaml (данные)."""
    rules = yaml.safe_load(
        (HERE.parents[1] / "src/philograph/knowledge/naming_rules.yaml").read_text(encoding="utf-8")
    )
    assert set(S.LONG_LIMIT_TYPES) == LONG_TYPES
    assert (LIMITS["default"], LIMITS["long"]) == (S.DEFAULT_LIMIT, S.LONG_LIMIT)
    assert set(S.PARTICLES) >= PARTICLES
    assert set(S.APOSTROPHES) == JOINERS
    for word in rules.get("stopwords") or []:  # стоп-список данных — целиком в генераторе
        assert word in S.STOPWORDS, word


# --- entity-dating ----------------------------------------------------------------------


@req(ED, DATING, invariant="Генератор датировок: все тире, маркеры, эры, века и причины (О23)")
def test_dating_sets():
    assert set(S.DASHES) == DASHES
    assert set(S.APPROX) == APPROX
    assert set(S.ERA_TEXT) == ERA_TEXT and set(S.ERA_QUOTE) == ERA_QUOTE
    assert list(S.CENTURIES) == CENTURIES
    assert set(DATING_ORDER) <= set(S.DATING_CODES)


@req(ED, DATING, invariant="Генератор датировок порождает каждую причину по порядку проверки (О23)")
@pytest.mark.parametrize("reason", [*DATING_ORDER, None])
def test_dating_reasons_generated(reason):
    _find(S.datings(), lambda d: d["reason"] == reason)


@req(ED, DATING, invariant="Генератор датировок: каждое тире и маркер «около» в тексте (О23)")
@pytest.mark.parametrize("piece", sorted(DASHES | APPROX))
def test_dating_pieces_generated(piece):
    _find(S.datings(), lambda d: piece in d["dating"]["text"].lower() and d["reason"] is None)


# --- add-wikidata-life-dates: таблица точностей, ранги, решения ---------------------------


@req(
    ED,
    "Даты жизни из Wikidata",
    invariant="Генератор порождает каждую строку таблицы точностей (О23)",
)
@pytest.mark.parametrize("precision", [*WD_PRECISIONS, "low", "zero", "+", "-"])
def test_wd_precisions_generated(precision):
    def ok(case) -> bool:
        (value, p), bounds = case
        if precision == "low":
            return p < 6 and bounds is None
        if precision == "zero":
            return value[1:5] == "0000"
        if precision in ("+", "-"):
            return value.startswith(precision) and bounds is not None
        return p == precision and bounds is not None

    _find(S.wd_times(), ok)


def test_wd_ranks_and_decisions():
    assert set(S.RANKS) == WD_RANKS
    assert set(S.DECISIONS) == DECISIONS
    for rank in WD_RANKS:
        _find(S.wd_claim_values(True), lambda c, r=rank: any(v[2] == r for v in c[0]))


# --- person-quality ---------------------------------------------------------------------


@req(
    PQ,
    "Слияние вариантов персоны",
    invariant="Генератор лиц порождает каждую причину слияния и очереди (О23)",
)
@pytest.mark.parametrize("code", [*MERGE_GENERATED, *QUEUE_GENERATED])
def test_person_codes_generated(code):
    def has(case) -> bool:
        for face in case["faces"]:
            if face.get("reason") == code or code in (face.get("queue") or {}).values():
                return True
        return False

    _find(S.persons_with_variants(), has)


def test_person_scenario_codes():
    """Коды решений человека и команды QID — в сценарных тестах (не генератор лиц)."""
    sources = "".join(
        (HERE / f).read_text(encoding="utf-8")
        for f in ("test_person_quality.py", "test_entity_merge.py", "test_life_dates.py")
    )
    for code in SCENARIO_CODES:
        assert f'"{code}"' in sources, code
