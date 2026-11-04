"""Нормализация слов для поиска: леммы русского, основы других языков.

«Канту» → «кант», «причинностью» → «причинность», «познанія» → «познание», «ёж» → «еж».
Запрос и абзацы нормализуются одинаково, поэтому совпадение не зависит от формы слова.
"""

from __future__ import annotations

import re
from functools import lru_cache

_WORD_RE = re.compile(r"[^\W\d_]+(?:-[^\W\d_]+)*", re.UNICODE)
_PREREFORM = str.maketrans({"ѣ": "е", "і": "и", "ѳ": "ф", "ѵ": "и"})
_SNOWBALL = {"en": "english", "de": "german", "fr": "french"}


@lru_cache(maxsize=1)
def _morph():
    import pymorphy3

    return pymorphy3.MorphAnalyzer()


@lru_cache(maxsize=8)
def _stemmer(lang: str):
    import snowballstemmer

    return snowballstemmer.stemmer(_SNOWBALL[lang])


@lru_cache(maxsize=200_000)
def normalize(word: str) -> str:
    w = word.lower().replace("ё", "е").translate(_PREREFORM)
    if re.match(r"[а-я]", w):
        w = re.sub(r"ъ$", "", w)
        return _morph().parse(w)[0].normal_form.replace("ё", "е")
    if w.isascii():
        # Язык латинского слова неизвестен заранее: английская основа подходит и для
        # латинских корней достаточно хорошо, а точность даёт смысловой поиск.
        return _stemmer("en").stemWord(w)
    return w


def terms(text: str) -> list[str]:
    return [normalize(w) for w in _WORD_RE.findall(text) if len(w) > 1 or w.isdigit()]
