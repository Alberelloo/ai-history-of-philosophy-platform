"""Юнит-тесты модуля названий (``knowledge/naming.py``): форма данных, письменность, причины.

Сценарные и нормативные тесты требований ``entity-naming`` пишет тестировщик; здесь — проверки
самих функций модуля на опорных значениях.
"""

from __future__ import annotations

import copy

import pytest
import yaml

from philograph.knowledge import naming
from philograph.knowledge.naming import (
    RulesError,
    check_name,
    event_label,
    is_russian,
    lang_for,
    names_for,
    normalize,
    parse_rules,
    script_of,
)
from philograph.platform import events


def _data() -> dict:
    return yaml.safe_load(naming.RULES_PATH.read_text(encoding="utf-8"))


def test_rules_load_from_package_data():
    rules = naming.load_rules()
    assert rules.exempt == {"source"}
    assert rules.limits_for("concept").max_words == 6
    assert rules.limits_for("work").max_chars == 160
    assert normalize("your Lordship") in rules.stopwords


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("limits", "default", "max_words"), 0),
        (("limits", "work", "max_chars"), "12"),
        (("person", "patterns"), ["(unclosed"]),
        (("stopwords",), "some"),
        (("version",), 2),
    ],
)
def test_rules_shape_errors(path, value):
    data = copy.deepcopy(_data())
    node = data
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    with pytest.raises(RulesError):
        parse_rules(data)


@pytest.mark.parametrize(
    ("text", "script"),
    [
        ("Платон", "cyrillic"),
        ("Plato", "latin"),
        ("Ἀριστοτέλης", "greek"),
        ("Людовик XIV", "cyrillic"),  # слово из римских цифр не считается
        ("Kant-Кант", None),  # 4 и 4 — равенство
        ("XIV", None),
        ("20.1", None),
        ("孔子", "other"),
    ],
)
def test_script_of(text, script):
    assert script_of(text) == script


@pytest.mark.parametrize(
    ("text", "given", "lang"),
    [
        ("Empiricism: a demonstration reader", "ru", "en"),
        ("Locke", "ru", "en"),
        ("Königsberg", "en", "en"),
        ("Ding an sich", "de", "de"),
        ("Людовик XIV", "en", "ru"),
        ("Ἀριστοτέλης", "ru", "el"),
        ("Ἀριστοτέλης", "grc", "grc"),
        ("Kant-Кант", "ru", "und"),
        ("孔子", "zh", "und"),
        ("Платон", None, "ru"),
    ],
)
def test_lang_for(text, given, lang):
    assert lang_for(text, given) == lang


@pytest.mark.parametrize(
    ("text", "russian"),
    [("Платон", True), ("Людовик XIV", True), ("Kant-Кант", False), ("Plato", False)],
)
def test_is_russian(text, russian):
    assert is_russian(text) is russian


@pytest.mark.parametrize(
    ("type_", "label", "reason"),
    [
        ("concept", "", "empty"),
        ("term", " ", "empty"),
        ("term", "—", "empty"),
        ("concept", "20.1", "number"),
        ("concept", "§ 20.1", "number"),
        ("concept", "(3.2)", "number"),
        ("concept", "20,1", "number"),
        ("concept", "a b c d e f", None),
        ("concept", "a b c d e f g", "sentence"),
        ("concept", "x" * 80, None),
        ("concept", "x" * 81, "sentence"),
        ("work", " ".join(["Слово"] * 12), None),
        ("work", " ".join(["Слово"] * 13), "sentence"),
        ("person", "the author of An Inquiry into the Human Mind", "sentence"),
        ("person", "The author of the Treatise", "not_a_name"),
        ("person", "Author of Leviathan", "not_a_name"),
        ("person", "blind mathematician", "not_a_name"),
        ("person", "your Lordship", "not_a_name"),  # строчная — раньше стоп-слова
        ("person", "Kepler and Des Cartes", "not_a_name"),
        ("person", "Кант и Юм", "not_a_name"),
        ("person", "Kant & Hume", "not_a_name"),
        ("person", "де Бройль", None),
        ("person", "ибн Сина", None),
        ("person", "аль-Фараби", None),
        ("person", "д’Аламбер", None),
        ("person", "d'Alembert", None),
        ("person", "Людовик XIV", None),
        ("person", "Your Lordship", "stopword"),
        ("person", "Поэт", "stopword"),
        ("person", "Тот, кто чувствует", "stopword"),
        ("concept", "Every", "stopword"),
        ("concept", "  EVERY ", "stopword"),
        ("concept", "blind mathematician", "stopword"),  # не персона — правило 4 не действует
        ("source", "20.1", None),  # источники библиотеки не проверяются
    ],
)
def test_check_name(type_, label, reason):
    assert check_name(type_, label) == reason


def test_stopwords_are_data():
    data = _data()
    data["stopwords"].append("некто")
    rules = parse_rules(data)
    assert check_name("concept", "Некто", rules) == "stopword"
    assert check_name("concept", "Некто") is None


def test_normalize_nfc_and_signs():
    decomposed = "Ёж_и"  # Е + комбинирующая диерезис → «Ё» в NFC → «е»
    assert normalize(decomposed) == "еж и"
    assert normalize("  Тот,  кто чувствует ") == "тот кто чувствует"


def test_event_label_cut():
    assert event_label("x" * 80) == "x" * 80
    cut = event_label("x" * 81)
    assert len(cut) == 80 and cut.endswith("…")


def _rejected(caplog_events):
    return [e for e in caplog_events if e["event"] == "knowledge.entity.rejected"]


def test_names_for_primary_and_variants(monkeypatch):
    emitted = []
    monkeypatch.setattr(events, "emit", lambda name, **f: emitted.append({"event": name, **f}))
    item = {
        "name": "Платон",
        "ru": "Платон",
        "en": "Plato",
        "original": {"lang": "grc", "text": "Πλάτων"},
    }
    assert names_for("person", item) == [
        ("ru", "Платон", "primary"),
        ("en", "Plato", "variant"),
        ("grc", "Πλάτων", "variant"),
    ]
    assert _rejected(emitted) == []


def test_names_for_rejected_spelling_not_written(monkeypatch):
    emitted = []
    monkeypatch.setattr(events, "emit", lambda name, **f: emitted.append({"event": name, **f}))
    assert names_for("person", {"name": "Plato", "ru": "поэт"}) == [("en", "Plato", "primary")]
    assert _rejected(emitted) == [
        {
            "event": "knowledge.entity.rejected",
            "type": "person",
            "label": "поэт",
            "reason": "not_a_name",
        }
    ]


def test_names_for_latin_without_ru():
    assert names_for("concept", {"name": "Ding an sich"}) == [("en", "Ding an sich", "primary")]
