"""Морфология для сопоставления слов: лемма русского слова, основа латинского.

Общая для сервисов, которым нужно узнать слово в любой форме: «Канту» → «кант»,
«причинности» → «причинность», «познанія» → «познание».
"""

from __future__ import annotations

import re
from functools import lru_cache

TOKEN_RE = re.compile(r"[^\W\d_]+(?:-[^\W\d_]+)*", re.UNICODE)
_PREREFORM = str.maketrans({"ѣ": "е", "і": "и", "ѳ": "ф", "ѵ": "и"})


@lru_cache(maxsize=1)
def _morph():
    import pymorphy3

    return pymorphy3.MorphAnalyzer()


@lru_cache(maxsize=2)
def _stemmer(language: str = "english"):
    import snowballstemmer

    return snowballstemmer.stemmer(language)


@lru_cache(maxsize=200_000)
def lemma(word: str) -> str:
    w = word.lower().replace("ё", "е").translate(_PREREFORM)
    if re.match(r"[а-я]", w):
        w = re.sub(r"ъ$", "", w)
        if not _morph().word_is_known(w):
            # Незнакомое словарю слово — обычно иностранная фамилия («Гоббсом», «Локка»):
            # угаданная лемма ненадёжна, основа одинакова для всех падежей.
            return _stemmer("russian").stemWord(w)
        return _morph().parse(w)[0].normal_form.replace("ё", "е")
    if w.isascii():
        return _stemmer().stemWord(w)
    return w


def tokens(text: str) -> list[tuple[str, int, int]]:
    """Слова текста с позициями: (лемма, начало, конец)."""
    return [(lemma(m.group(0)), m.start(), m.end()) for m in TOKEN_RE.finditer(text)]


@lru_cache(maxsize=200_000)
def keys(word: str) -> tuple[str, ...]:
    """Ключи сопоставления слова: лемма, а у слова с заглавной ещё и основа словоформы.

    Имя собственное словарь может разобрать как другое слово («Юма» — топоним), а основа
    у всех падежей фамилии общая. Нарицательные слова сравниваются только по лемме, чтобы
    «вера» не совпала с «верить».
    """
    first = lemma(word)
    if not word[:1].isupper() or not re.match(r"[а-яё]", word[:1].lower()):
        return (first,)
    w = word.lower().replace("ё", "е").translate(_PREREFORM)
    stem = _stemmer("russian").stemWord(re.sub(r"ъ$", "", w))
    return (first,) if stem == first else (first, stem)


def forms(text: str) -> list[tuple[tuple[str, ...], int, int]]:
    """Слова текста с позициями и ключами сопоставления: (ключи, начало, конец)."""
    return [(keys(m.group(0)), m.start(), m.end()) for m in TOKEN_RE.finditer(text)]
