"""Проверка качества извлечённого текста: метрики по страницам, отсев, выборка, эталоны."""

from __future__ import annotations

import random
import re
from dataclasses import asdict, dataclass, field
from functools import lru_cache

from philograph.library.lang import normalize_word, words
from philograph.library.model import RawDocument, RawPage

# Текст UTF-8, прочитанный как Latin-1 или CP1252 (Ð, Ñ…), и CP1251 как Latin-1 (Ï, î…).
_MOJIBAKE_RE = re.compile(r"[ÐÑÏÎÈÌÒÓÔÕÖØÙÚÛÜÝÞßàáâãäåæçèéêëìíîïðñòóôõöøùúûüýþÿ]")
_GARBAGE_RE = re.compile(r"[^\w\s.,;:!?«»\"'()\[\]\-–—…/*§№%+=<>°̀-ͯ]", re.UNICODE)


@dataclass(frozen=True)
class QualitySettings:
    """Пороги отсева. Значения уточним на прототипе, поэтому они — настройка."""

    min_dictionary_share: float = 0.55
    max_garbage_share: float = 0.05
    min_confidence: float = 0.5
    max_empty_share: float = 0.3
    max_mojibake_share: float = 0.2
    random_pages: int = 6
    worst_pages: int = 3


@dataclass
class PageMetrics:
    index: int
    confidence: float | None
    dictionary_share: float | None
    garbage_share: float
    mojibake_share: float
    empty: bool
    suspicious_words: list[str] = field(default_factory=list)


@lru_cache(maxsize=1)
def _morph():
    import pymorphy3

    return pymorphy3.MorphAnalyzer()


_LATIN_COMMON = frozenset(
    {
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
        "ergo",
        "sum",
        "cogito",
        "the",
        "and",
        "of",
        "to",
        "is",
        "that",
        "der",
        "die",
        "und",
        "das",
    }
)


def is_known(word: str, languages: list[str]) -> bool | None:
    """Словарное ли слово. ``None`` — для языка нет словаря, слово не учитывается."""
    if re.match(r"[Ѐ-ӿ]", word):
        if not {"ru", "rus"} & set(languages):
            return False
        normalized = normalize_word(word)
        return _morph().word_is_known(normalized) or len(normalized) <= 2
    if re.match(r"[Ͱ-Ͽἀ-῿]", word):
        return None if {"grc", "el"} & set(languages) else False
    if word.isascii() and word.isalpha():
        return True if word.lower() in _LATIN_COMMON else None
    return False


def page_metrics(page: RawPage, languages: list[str]) -> PageMetrics:
    text = "\n".join(line.text for line in page.lines)
    tokens = [w for w in words(text) if len(w) > 1]
    known = [(w, is_known(w, languages)) for w in tokens]
    counted = [(w, k) for w, k in known if k is not None]
    share = sum(1 for _, k in counted if k) / len(counted) if counted else None
    chars = len(text.replace("\n", "").replace(" ", "")) or 1
    confidences = [ln.confidence for ln in page.lines if ln.confidence is not None]
    confidence = (
        page.ocr_confidence
        if page.ocr_confidence is not None
        else (sum(confidences) / len(confidences) if confidences else None)
    )
    return PageMetrics(
        index=page.index,
        confidence=confidence,
        dictionary_share=share,
        garbage_share=len(_GARBAGE_RE.findall(text)) / chars,
        mojibake_share=len(_MOJIBAKE_RE.findall(text)) / chars
        if {"ru", "rus"} & set(languages)
        else 0.0,
        empty=len(text.strip()) < 20,
        suspicious_words=[w for w, k in counted if k is False][:20],
    )


@dataclass
class Assessment:
    pages: list[PageMetrics]
    totals: dict[str, float | None]
    needs_review: bool
    defer_reason: str | None
    sample: list[int] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "pages": [asdict(p) for p in self.pages],
            "totals": self.totals,
            "needs_review": self.needs_review,
            "defer_reason": self.defer_reason,
            "sample": self.sample,
        }


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def assess(
    raw: RawDocument, languages: list[str], settings: QualitySettings, seed: str
) -> Assessment:
    pages = [page_metrics(p, languages) for p in raw.pages]
    totals = {
        "confidence": _mean([p.confidence for p in pages if p.confidence is not None]),
        "dictionary_share": _mean(
            [p.dictionary_share for p in pages if p.dictionary_share is not None]
        ),
        "garbage_share": _mean([p.garbage_share for p in pages]) or 0.0,
        "mojibake_share": _mean([p.mojibake_share for p in pages]) or 0.0,
        "empty_share": sum(p.empty for p in pages) / len(pages) if pages else 1.0,
    }
    reason = None
    if totals["mojibake_share"] > settings.max_mojibake_share:
        reason = "сломанная кодировка"
    elif totals["dictionary_share"] is not None and (
        totals["dictionary_share"] < settings.min_dictionary_share
    ):
        reason = "низкое качество распознавания"
    elif totals["garbage_share"] > settings.max_garbage_share:
        reason = "много мусорных символов"
    elif totals["confidence"] is not None and totals["confidence"] < settings.min_confidence:
        reason = "низкая уверенность распознавания"
    elif totals["empty_share"] > settings.max_empty_share:
        reason = "много пустых страниц"
    recognized = raw.fmt == "pdf"  # распознанные сканы и чужой текстовый слой PDF
    metrics_bad = any(
        (p.dictionary_share is not None and p.dictionary_share < settings.min_dictionary_share)
        or p.garbage_share > settings.max_garbage_share
        or p.mojibake_share > settings.max_mojibake_share
        for p in pages
    )
    needs_review = reason is None and (recognized or metrics_bad)
    sample: list[int] = []
    if needs_review:
        rng = random.Random(seed)
        indices = [p.index for p in pages if not p.empty]
        sample = sorted(rng.sample(indices, min(settings.random_pages, len(indices))))
        worst = sorted(
            pages,
            key=lambda p: (
                (p.dictionary_share if p.dictionary_share is not None else 1.0) - p.garbage_share
            ),
        )
        for p in worst[: settings.worst_pages]:
            if p.index not in sample:
                sample.append(p.index)
    return Assessment(pages, totals, needs_review, reason, sample)


# --- эталонные страницы -------------------------------------------------------------


def _levenshtein(a: list[str] | str, b: list[str] | str) -> int:
    previous = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        current = [i]
        for j, y in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (x != y)))
        previous = current
    return previous[-1]


def error_rates(recognized: str, reference: str) -> dict[str, float]:
    """Доля ошибок по символам (CER) и по словам (WER) относительно эталона."""
    norm = lambda s: " ".join(s.split())  # noqa: E731
    rec, ref = norm(recognized), norm(reference)
    cer = _levenshtein(rec, ref) / max(1, len(ref))
    wer = _levenshtein(rec.split(), ref.split()) / max(1, len(ref.split()))
    return {"cer": round(cer, 4), "wer": round(wer, 4)}
