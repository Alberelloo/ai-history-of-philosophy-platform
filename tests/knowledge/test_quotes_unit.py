"""Юнит-тесты ``knowledge.quotes``: нормализация, части по многоточию, коды отказа.
Сценарии требования «Цитата у каждого утверждения» — у тестировщика."""

from __future__ import annotations

import pytest

from philograph.knowledge import quotes

PARAGRAPH = "О, Заратустра, сказали они, ты нашёл счастье своё — и «Бог умер»."


@pytest.mark.parametrize(
    "quote",
    [
        "О, Заратустра, сказали они",
        '"О, Заратустра, сказали они"',
        "«О, Заратустра, сказали они»",
        "о,  ЗАРАТУСТРА, сказали они",
        "О, Заратустра… ты нашёл счастье своё",
        "О, Заратустра... ты нашел счастье свое",
        "О, Заратустра [...] ты нашёл счастье своё",
        'счастье своё - и "Бог умер"',
        "счастье своё – и „Бог умер“",
    ],
)
def test_found(quote):
    assert quotes.check(quote, PARAGRAPH) is None


@pytest.mark.parametrize(
    ("quote", "code"),
    [
        ("Заратустра пересказал учение", quotes.QUOTE_NOT_FOUND),
        ("ты нашёл счастье своё… О, Заратустра", quotes.QUOTE_NOT_FOUND),  # порядок частей
        ("О… своё", quotes.QUOTE_TOO_SHORT),
        ("", quotes.QUOTE_NOT_FOUND),
        ("…", quotes.QUOTE_TOO_SHORT),  # нет значимого текста
    ],
)
def test_refused(quote, code):
    assert quotes.check(quote, PARAGRAPH) == code


def test_soft_hyphen_and_stress_in_paragraph():
    assert quotes.found("познание вещей", "позна­ние ве́щей")


def test_no_text():
    assert quotes.check("что угодно", None) == quotes.QUOTE_NOT_FOUND


def test_parts_do_not_overlap():
    # вторая часть должна идти после первой, а не внутри неё
    assert not quotes.found("абвгдежзик… жзиклмнопр", "абвгдежзиклмнопр")
    assert quotes.found("абвгдежзик… лмнопрстуф", "абвгдежзик и лмнопрстуф")


def test_single_short_quote_allowed():
    assert quotes.found("Бог", PARAGRAPH)  # одна часть — без минимума длины


def test_author_ellipsis_found_whole():
    text = "Он сказал... и замолчал."
    assert quotes.check("сказал... и", text) is None  # целиком; по частям было бы too_short
    assert quotes.check("Он сказал… и замолчал", text) is None


@pytest.mark.parametrize("quote", ["...", "…", " - ", ", .", "« »", "[...]", "———"])
def test_quote_without_significant_text(quote):
    text = "Он сказал... и замолчал — , . «» [...] ———"
    assert quotes.check(quote, text) == quotes.QUOTE_TOO_SHORT


@pytest.mark.parametrize("quote", ["априори", "tabula rasa", "Бог", "7"])
def test_short_real_quotes_pass(quote):
    assert quotes.found(quote, "Понятие априори, tabula rasa, Бог и 7 дней.")
