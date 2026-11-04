"""Язык абзаца и нормализация слов: эвристики без внешних моделей.

Для разбора структуры достаточно отличить русский, латынь, древнегреческий, английский,
немецкий и французский. Короткие вставки внутри абзаца язык не меняют: решает большинство.
"""

from __future__ import annotations

import re

_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)

_STOPWORDS = {
    "la": {
        "et",
        "est",
        "in",
        "non",
        "quod",
        "ad",
        "cum",
        "sed",
        "ut",
        "qui",
        "quae",
        "esse",
        "enim",
        "autem",
        "ergo",
        "sum",
        "nihil",
        "ex",
        "de",
        "per",
    },
    "en": {
        "the",
        "and",
        "of",
        "to",
        "is",
        "that",
        "it",
        "which",
        "as",
        "be",
        "not",
        "this",
        "are",
        "by",
        "with",
        "from",
    },
    "de": {
        "der",
        "die",
        "das",
        "und",
        "ist",
        "nicht",
        "zu",
        "den",
        "von",
        "mit",
        "sich",
        "auf",
        "als",
        "auch",
        "es",
        "ein",
        "eine",
        "dass",
    },
    "fr": {
        "le",
        "la",
        "les",
        "et",
        "est",
        "des",
        "que",
        "qui",
        "dans",
        "pas",
        "une",
        "du",
        "pour",
        "sur",
        "ne",
        "il",
    },
}


def words(text: str) -> list[str]:
    return _WORD_RE.findall(text)


def detect(text: str, default: str) -> str:
    tokens = words(text)
    if len(tokens) < 4:
        return default
    cyr = sum(1 for t in tokens if re.match(r"[Ѐ-ӿ]", t))
    greek = sum(1 for t in tokens if re.match(r"[Ͱ-Ͽἀ-῿]", t))
    latin = len(tokens) - cyr - greek
    share = max(cyr, greek, latin) / len(tokens)
    if share < 0.7:
        return default  # смешанный текст: язык источника
    if cyr == max(cyr, greek, latin):
        return "ru"
    if greek == max(cyr, greek, latin):
        return "grc"
    lowered = [t.lower() for t in tokens]
    scores = {lang: sum(1 for t in lowered if t in stop) for lang, stop in _STOPWORDS.items()}
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] > 0 else default


# Дореформенная орфография → современная, для сравнения и поиска (не для показа).
_PREREFORM = str.maketrans(
    {"ѣ": "е", "Ѣ": "Е", "і": "и", "І": "И", "ѳ": "ф", "Ѳ": "Ф", "ѵ": "и", "Ѵ": "И"}
)
_HARD_SIGN_END = re.compile(r"ъ\b")


def normalize_word(word: str) -> str:
    w = word.lower().replace("ё", "е")
    w = w.translate(_PREREFORM)
    return _HARD_SIGN_END.sub("", w)


def normalize_text(text: str) -> str:
    """Для сравнения абзацев: регистр, «ё», дореформенная орфография, пробелы, переносы."""
    text = text.replace("­", "")
    return " ".join(normalize_word(w) for w in words(text))
