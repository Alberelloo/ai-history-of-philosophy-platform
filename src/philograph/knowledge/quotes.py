"""Сверка цитаты с абзацем — одно правило для всех мест (ontology-extraction, «Цитата у
каждого утверждения»): извлечение до привязки сущностей, запись утверждения, перепроверка
изменённого абзаца и цитата датировки.

Цитата должна быть дословной, но типографика не считается расхождением: кавычки, тире,
мягкий перенос, ударения, неразрывные пробелы, ``ё``, регистр. Обрамляющие кавычки
снимаются; многоточие — пропуск: части цитаты ищутся дословно и по порядку.
"""

from __future__ import annotations

import re
import unicodedata

QUOTE_NOT_FOUND = "quote_not_found"
QUOTE_TOO_SHORT = "quote_too_short"
MIN_PART = 10  # символов после нормализации у каждой части, если частей больше одной
# Цитата целиком: хотя бы одна буква или цифра. Выше не берём: прежнее правило принимало любую
# подстроку, и подтверждение из одного короткого слова («Бог», «априори») при перепроверке
# абзаца не должно стать потерянным.
MIN_WHOLE = 1

_REMOVE = dict.fromkeys(map(ord, "­́̀​⁠﻿"))
_MAP = str.maketrans(
    {
        **dict.fromkeys("«»„“”‟″", '"'),
        **dict.fromkeys("‘’‚‛′`", "'"),
        **dict.fromkeys("‐‑‒–—―−", "-"),
        "…": "...",
        "ё": "е",
        "Ё": "Е",
    }
)
_SPACE = re.compile(r"\s+")
_ELLIPSIS = re.compile(r"\s*[\[(]?\s*\.{3,}\s*[\])]?\s*")
_EDGE_QUOTES = "\"'"


def normalize(text: str) -> str:
    """NFC, без мягкого переноса и ударений, единые кавычки и тире, ``…`` → ``...``,
    пробелы схлопнуты, ``ё`` → ``е``, нижний регистр."""
    text = unicodedata.normalize("NFC", text or "").translate(_REMOVE).translate(_MAP)
    return _SPACE.sub(" ", text).strip().lower()


def _unquoted(quote: str) -> str:
    q = normalize(quote)
    while len(q) >= 2 and q[0] in _EDGE_QUOTES and q[-1] in _EDGE_QUOTES:
        q = q[1:-1].strip()
    return q


def _significant(text: str) -> int:
    """Значимые символы: буквы и цифры (любой письменности)."""
    return sum(ch.isalnum() for ch in text)


def parts(quote: str) -> list[str]:
    """Части цитаты: нормализация, снятие обрамляющих кавычек, деление по многоточию."""
    return [p for p in (s.strip() for s in _ELLIPSIS.split(_unquoted(quote))) if p]


def check(quote: str, text: str | None) -> str | None:
    """``None``, если цитата есть в абзаце; иначе код причины. Сначала цитата ищется целиком
    (многоточие автора — часть текста), и только если её нет — по частям многоточия."""
    if text is None:
        return QUOTE_NOT_FOUND
    if not normalize(quote):
        return QUOTE_NOT_FOUND  # пустая цитата
    whole = _unquoted(quote)
    if _significant(whole) < MIN_WHOLE:
        return QUOTE_TOO_SHORT  # «...», «—», «, .»: подтверждать нечего
    haystack = normalize(text)
    if whole in haystack:
        return None
    found = parts(quote)
    if not found:
        return QUOTE_NOT_FOUND
    if len(found) > 1 and any(len(p) < MIN_PART or not _significant(p) for p in found):
        return QUOTE_TOO_SHORT
    position = 0
    for part in found:
        at = haystack.find(part, position)
        if at < 0:
            return QUOTE_NOT_FOUND
        position = at + len(part)
    return None


def found(quote: str, text: str | None) -> bool:
    return check(quote, text) is None
