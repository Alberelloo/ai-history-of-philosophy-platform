"""Опора ответа на источники: проверяет код, а не модель.

Модель получает абзацы под номерами и ставит после каждого предложения ссылки ``[n]``.
Код делит ответ на фрагменты, переводит номера в идентификаторы абзацев, удаляет ссылки на
непереданное, сверяет цитаты с абзацем и помечает фрагменты без подтверждённой опоры.
Под номером может стоять и утверждение онтологии: проверенное или подтверждённое источником
служит опорой, сгенерированное моделью — нет.
Инструкции внутри вопроса или текста источника эти правила отключить не могут.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

CITATION_RE = re.compile(r"\s*\[(\d+(?:\s*,\s*\d+)*)\]")
QUOTE_RE = re.compile(r"«([^»]{3,})»|\"([^\"]{3,})\"|“([^”]{3,})”")
# Конец предложения: знак конца, затем, возможно, ссылки ``[n]``, затем начало
# следующего. Ссылки после точки остаются с предложением, к которому относятся.
BOUNDARY = re.compile(r"[.!?…]+(?:\s*\[\d+(?:\s*,\s*\d+)*\])?(?=\s+\S)|\n+")
# Цитата из источника без права цитирования допустима только короткой фразой.
SHORT_QUOTE_WORDS = 6


@dataclass(frozen=True)
class Passage:
    number: int
    paragraph_id: str
    source_id: str
    chapter_id: str | None
    title: str
    text: str
    quoting: bool = True
    kind: str = "paragraph"  # paragraph | statement
    statement_id: str | None = None
    grounds: bool = True  # служит ли опорой: у сгенерированного утверждения — нет
    source_title: str | None = None
    chapter_title: str | None = None
    paragraph_start: str | None = None
    entity_id: str | None = None


@dataclass
class Fragment:
    text: str
    citations: list[Passage] = field(default_factory=list)
    grounded: bool = False
    removed_citations: int = 0
    removed_quotes: int = 0
    unverified_quotes: list[str] = field(default_factory=list)
    contradicts: list[dict] = field(default_factory=list)  # противоречия онтологии

    def to_json(self) -> dict:
        return {
            "text": self.text,
            "grounded": self.grounded,
            "unverified_quotes": self.unverified_quotes,
            "contradicts": self.contradicts,
            "citations": [
                {
                    "kind": p.kind,
                    "paragraph_id": p.paragraph_id or None,
                    "statement_id": p.statement_id,
                    "entity_id": p.entity_id,
                    "source_id": p.source_id,
                    "chapter_id": p.chapter_id,
                    "title": p.title,
                    "source_title": p.source_title,
                    "chapter_title": p.chapter_title,
                    "paragraph_start": p.paragraph_start,
                }
                for p in self.citations
            ],
        }


def _norm(text: str) -> str:
    text = text.replace("ё", "е").replace("Ё", "Е")
    text = re.sub(r"[«»“”\"'„]", "", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def split_fragments(text: str) -> list[str]:
    """Фрагмент — предложение вместе со ссылками на абзацы."""
    parts, start = [], 0
    for match in BOUNDARY.finditer(text):
        parts.append(text[start : match.end()])
        start = match.end()
    parts.append(text[start:])
    return [p.strip() for p in parts if p.strip()]


def verify(raw: str, passages: dict[int, Passage]) -> Fragment:
    numbers = [int(n) for group in CITATION_RE.findall(raw) for n in group.split(",")]
    text = CITATION_RE.sub("", raw).strip()
    fragment = Fragment(text=text)
    seen: set[str] = set()
    for number in numbers:
        passage = passages.get(number)
        if passage is None:
            fragment.removed_citations += 1  # ссылка на непереданный абзац
            continue
        key = passage.statement_id or passage.paragraph_id
        if key not in seen:
            fragment.citations.append(passage)
            seen.add(key)
    for match in QUOTE_RE.finditer(text):
        quote = next(g for g in match.groups() if g)
        found_in = [p for p in fragment.citations if _norm(quote) in _norm(p.text)]
        if not found_in:
            fragment.unverified_quotes.append(quote)
            # Искажённая цитата не показывается как цитата из источника.
            text = text.replace(match.group(0), quote)
            continue
        if any(not p.quoting for p in found_in) and len(quote.split()) > SHORT_QUOTE_WORDS:
            fragment.removed_quotes += 1
            text = text.replace(
                match.group(0), "[цитата опущена: источник не разрешает цитирование]"
            )
    fragment.text = text
    fragment.grounded = (
        any(p.grounds for p in fragment.citations) and not fragment.unverified_quotes
    )
    return fragment


class FragmentStream:
    """Собирает поток текста в фрагменты и отдаёт каждый только после проверки."""

    def __init__(self, passages: dict[int, Passage]) -> None:
        self.passages = passages
        self.buffer = ""

    def feed(self, chunk: str) -> list[Fragment]:
        self.buffer += chunk
        # Отдаём всё до последней границы, за которой уже началось следующее предложение:
        # недописанное предложение и его ссылки ждут продолжения.
        cuts = [m.end() for m in BOUNDARY.finditer(self.buffer)]
        if not cuts:
            return []
        ready, self.buffer = self.buffer[: cuts[-1]], self.buffer[cuts[-1] :]
        return [verify(p, self.passages) for p in split_fragments(ready)]

    def finish(self) -> list[Fragment]:
        rest, self.buffer = self.buffer.strip(), ""
        return [verify(p, self.passages) for p in split_fragments(rest)] if rest else []
