"""Гибридный поиск абзацев: по словам (BM25 по леммам) и по смыслу, слияние по рангам (RRF)."""

from __future__ import annotations

import math
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Engine, and_, func, select

from philograph.platform import events
from philograph.search import schema as t
from philograph.search.indexing import EmbedPort
from philograph.search.text import terms
from philograph.search.vectors import VectorStore

events.define(
    "search.query.completed",
    "info",
    "Поиск выполнен",
    required=("results", "semantic_used", "embed_ms", "semantic_ms", "lexical_ms", "fusion_ms"),
    optional=("expanded",),
)
events.define(
    "search.semantic.unavailable",
    "warning",
    "Смысловой поиск недоступен, ответ только по словам",
    required=("reason",),
)

# Служебные слова не несут смысла запроса: без них «тема, которой нет» не найдёт абзацы
# по совпадению предлогов.
STOPWORDS = frozenset(
    terms(
        "и в во не что он на я с со как а то все она так его но да ты к у же вы за бы по только "
        "ее мне было вот от меня еще нет о из ему теперь когда даже ну вдруг ли если уже или ни "
        "быть был него до вас нибудь опять уж вам ведь там потом себя ничего ей может они тут где "
        "есть надо ней для мы тебя их чем была сам чтоб без будто чего раз тоже себе под будет ж "
        "тогда кто этот того потому этого какой совсем ним здесь этом один почти мой тем чтобы нее "
        "сейчас были куда зачем всех никогда можно при наконец два об другой хоть после над больше "
        "тот через эти нас про всего них какая много разве три эту моя впрочем хорошо свою этой "
        "перед иногда лучше чуть том нельзя такой им более всегда конечно всю между почему "
        "the a an of to in and or is are was be it that this for on with as by at from"
    )
)


@dataclass
class SearchSettings:
    k1: float = 1.2
    b: float = 0.75
    rrf_k: int = 60
    min_lexical_score: float = 1.0
    min_semantic_score: float = 0.35
    candidates: int = 50


@dataclass
class Query:
    text: str
    sources: list[str] | None = None
    languages: list[str] | None = None
    exclude: list[str] = field(default_factory=list)
    extra_terms: list[str] = field(default_factory=list)  # расширение запроса, например онтологией
    priority: list[str] = field(default_factory=list)  # абзацы, которым дать приоритет
    neighbors: int = 0
    per_chapter: int = 3
    limit: int = 10
    scopes: list[str] = field(default_factory=lambda: ["public"])


class Searcher:
    def __init__(
        self,
        engine: Engine,
        embedder: EmbedPort,
        vectors: VectorStore,
        collection: callable,
        settings: SearchSettings | None = None,
    ) -> None:
        self.engine = engine
        self.embedder = embedder
        self.vectors = vectors
        self.collection = collection  # функция: активная коллекция
        self.settings = settings or SearchSettings()

    def _filters(self, q: Query):
        conds = [t.docs.c.active, t.docs.c.scope.in_(q.scopes)]
        if q.sources:
            conds.append(t.docs.c.source_id.in_(q.sources))
        if q.languages:
            conds.append(t.docs.c.lang.in_(q.languages))
        if q.exclude:
            conds.append(t.docs.c.paragraph_id.not_in(q.exclude))
        return and_(*conds)

    def lexical(self, q: Query, words: list[str]) -> dict[str, float]:
        if not words:
            return {}
        s = self.settings
        with self.engine.begin() as conn:
            total, avg = conn.execute(
                select(func.count(), func.avg(t.docs.c.length)).where(t.docs.c.active)
            ).one()
            if not total:
                return {}
            avg = float(avg or 1)  # PostgreSQL отдаёт среднее как Decimal
            df = dict(
                conn.execute(
                    select(t.postings.c.term, func.count())
                    .join(t.docs, t.docs.c.paragraph_id == t.postings.c.paragraph_id)
                    .where(and_(t.postings.c.term.in_(words), t.docs.c.active))
                    .group_by(t.postings.c.term)
                ).all()
            )
            rows = conn.execute(
                select(
                    t.postings.c.term, t.postings.c.paragraph_id, t.postings.c.tf, t.docs.c.length
                )
                .join(t.docs, t.docs.c.paragraph_id == t.postings.c.paragraph_id)
                .where(and_(t.postings.c.term.in_(words), self._filters(q)))
            ).all()
        scores: dict[str, float] = defaultdict(float)
        for term, pid, tf, length in rows:
            idf = math.log(1 + (total - df[term] + 0.5) / (df[term] + 0.5))
            scores[pid] += (
                idf * tf * (s.k1 + 1) / (tf + s.k1 * (1 - s.b + s.b * length / (avg or 1)))
            )
        return {pid: v for pid, v in scores.items() if v >= s.min_lexical_score}

    def search(self, q: Query) -> dict[str, Any]:
        timings = {"embed_ms": 0.0, "semantic_ms": 0.0, "lexical_ms": 0.0, "fusion_ms": 0.0}
        semantic: dict[str, float] = {}
        semantic_used = True
        started = time.perf_counter()
        try:
            vector = self.embedder.embed([q.text], budget="site")[0]
            timings["embed_ms"] = round((time.perf_counter() - started) * 1000, 2)
            started = time.perf_counter()
            hits = self.vectors.search(
                self.collection(),
                vector,
                sources=q.sources,
                languages=q.languages,
                exclude=q.exclude,
                scopes=q.scopes,
                limit=self.settings.candidates,
            )
            semantic = {
                h.paragraph_id: h.score for h in hits if h.score >= self.settings.min_semantic_score
            }
            timings["semantic_ms"] = round((time.perf_counter() - started) * 1000, 2)
        except Exception as exc:  # провайдер или векторная база недоступны
            semantic_used = False
            events.emit("search.semantic.unavailable", reason=type(exc).__name__)
        started = time.perf_counter()
        base_terms = [w for w in terms(q.text) if w not in STOPWORDS]
        extra = [w for x in q.extra_terms for w in terms(x) if w not in STOPWORDS]
        lexical = self.lexical(q, base_terms)
        expanded = {pid: v for pid, v in self.lexical(q, extra).items() if pid not in lexical}
        timings["lexical_ms"] = round((time.perf_counter() - started) * 1000, 2)

        started = time.perf_counter()
        k = self.settings.rrf_k
        fused: dict[str, float] = defaultdict(float)
        found_by: dict[str, set[str]] = defaultdict(set)
        for name, ranking in (
            ("semantic", semantic),
            ("lexical", lexical),
            ("expansion", expanded),
        ):
            ordered = sorted(ranking, key=lambda pid: -ranking[pid])
            for rank, pid in enumerate(ordered):
                fused[pid] += 1 / (k + rank + 1)
                found_by[pid].add(name)
        for pid in q.priority:
            if pid in fused:
                fused[pid] += 1 / k
        ranked = sorted(fused, key=lambda pid: -fused[pid])
        with self.engine.begin() as conn:
            docs = {
                r.paragraph_id: r
                for r in conn.execute(
                    select(t.docs).where(and_(t.docs.c.paragraph_id.in_(ranked), self._filters(q)))
                )
            }
        per_chapter: dict[str | None, int] = defaultdict(int)
        results = []
        for pid in ranked:
            doc = docs.get(pid)
            if doc is None:
                continue
            if per_chapter[doc.chapter_id] >= q.per_chapter:
                continue
            per_chapter[doc.chapter_id] += 1
            results.append(
                {
                    "paragraph_id": pid,
                    "source_id": doc.source_id,
                    "chapter_id": doc.chapter_id,
                    "section_title": doc.section_title,
                    "text": doc.text,
                    "lang": doc.lang,
                    "score": round(fused[pid], 6),
                    "found_by": sorted(found_by[pid]),
                    "neighbors": self._neighbors(doc, q.neighbors),
                }
            )
            if len(results) >= q.limit:
                break
        timings["fusion_ms"] = round((time.perf_counter() - started) * 1000, 2)
        events.emit(
            "search.query.completed",
            results=len(results),
            semantic_used=semantic_used,
            expanded=len(expanded),
            **timings,
        )
        return {"results": results, "semantic_used": semantic_used}

    def _neighbors(self, doc, count: int) -> dict[str, list[dict[str, str]]]:
        if count <= 0:
            return {"before": [], "after": []}
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(t.docs.c.paragraph_id, t.docs.c.text, t.docs.c.ord)
                .where(
                    and_(
                        t.docs.c.source_id == doc.source_id,
                        t.docs.c.chapter_id == doc.chapter_id,
                        t.docs.c.ord.between(doc.ord - count, doc.ord + count),
                    )
                )
                .order_by(t.docs.c.ord)
            ).all()
        before = [{"paragraph_id": r.paragraph_id, "text": r.text} for r in rows if r.ord < doc.ord]
        after = [{"paragraph_id": r.paragraph_id, "text": r.text} for r in rows if r.ord > doc.ord]
        return {"before": before, "after": after}
