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


def parts(quote: str) -> list[str]:
    """Части цитаты: нормализация, снятие обрамляющих кавычек, деление по многоточию."""
    q = normalize(quote)
    while len(q) >= 2 and q[0] in _EDGE_QUOTES and q[-1] in _EDGE_QUOTES:
        q = q[1:-1].strip()
    return [p for p in (s.strip() for s in _ELLIPSIS.split(q)) if p]


def check(quote: str, text: str | None) -> str | None:
    """``None``, если цитата есть в абзаце; иначе код причины."""
    found = parts(quote)
    if not found or text is None:
        return QUOTE_NOT_FOUND
    if len(found) > 1 and any(len(p) < MIN_PART for p in found):
        return QUOTE_TOO_SHORT
    haystack = normalize(text)
    position = 0
    for part in found:
        at = haystack.find(part, position)
        if at < 0:
            return QUOTE_NOT_FOUND
        position = at + len(part)
    return None


def found(quote: str, text: str | None) -> bool:
    return check(quote, text) is None
