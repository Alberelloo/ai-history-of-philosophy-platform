"""Ассистент: маршрутизация → заданная цепочка поисков → ответ потоком с проверкой опоры.

Это не агент с циклами: число вызовов модели на вопрос ограничено заранее, а шаги каждого
типа вопроса описаны данными (``CHAINS``). Шаги онтологии подключаются в точки ``hooks``.
"""

from __future__ import annotations

import re
import time
from collections import defaultdict, deque
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

from philograph.assistant.clients import LlmUnavailable
from philograph.assistant.grounding import FragmentStream, Passage
from philograph.platform import events
from philograph.platform.client import ServiceUnavailable
from philograph.platform.clock import Clock, SystemClock
from philograph.platform.metrics import metrics

TYPES = ("local", "knowledge", "other_authors", "genesis", "off_topic")

# Цепочки как данные: какие поиски, с какими фильтрами, каким шаблоном отвечать.
CHAINS: dict[str, dict[str, Any]] = {
    "local": {
        "template": "assistant.answer.local",
        "searches": [
            {"scope": "current", "limit": 6, "neighbors": 1},
            {"scope": "all", "limit": 6, "if_fewer_than": 3},
        ],
    },
    "knowledge": {
        "template": "assistant.answer.knowledge",
        "searches": [{"scope": "toggle", "limit": 8}],
    },
    "other_authors": {
        "template": "assistant.answer.other_authors",
        "searches": [{"scope": "others", "limit": 8, "per_chapter": 2}],
    },
    "genesis": {
        "template": "assistant.answer.genesis",
        "hooks": ["genesis"],
        "searches": [
            {"scope": "toggle", "limit": 8, "extra_terms": ["истоки", "предшественники", "впервые"]}
        ],
    },
    "off_topic": {"refuse": True},
}

ROUTER_SCHEMA = {
    "type": "object",
    "required": ["type", "confidence", "names"],
    "properties": {
        "type": {"enum": list(TYPES)},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "names": {"type": "array", "items": {"type": "string"}},
    },
}

events.define(
    "assistant.question.received",
    "info",
    "Ассистент получил вопрос",
    required=("question_length", "has_selection", "sources_only"),
)
events.define(
    "assistant.routed",
    "info",
    "Вопрос отнесён к типу",
    required=("type", "confidence", "fallback", "duration_ms"),
)
events.define(
    "assistant.searched", "info", "Шаг поиска цепочки выполнен", required=("scope", "results")
)
events.define(
    "assistant.refused",
    "info",
    "Ассистент отказал без вызова основной модели",
    required=("reason",),
)
events.define(
    "assistant.citation.invented",
    "warning",
    "Модель сослалась на непереданный абзац",
    required=("count",),
)
events.define(
    "assistant.answer.completed",
    "info",
    "Ответ ассистента завершён",
    required=(
        "type",
        "passages",
        "fragments",
        "grounded",
        "ungrounded",
        "hidden",
        "removed_citations",
        "removed_quotes",
        "llm_calls",
        "first_fragment_ms",
        "total_ms",
    ),
)
events.define(
    "assistant.answer.interrupted",
    "error",
    "Ответ ассистента оборвался",
    required=("type", "fragments"),
)
events.define("assistant.stopped", "info", "Читатель остановил ответ", required=("fragments",))


@dataclass
class AskRequest:
    question: str
    visitor: str
    selection: str | None = None
    selection_paragraphs: list[str] = field(default_factory=list)  # абзацы выделения
    source_id: str | None = None
    history: list[dict[str, str]] = field(default_factory=list)  # [{"question", "answer"}]
    sources_only: bool = False
    generation: bool = True  # генерация без опоры на источники (по умолчанию включена)
    scope: str = "all"  # переключатель источников: all | current


@dataclass
class AssistantSettings:
    max_question_chars: int = 2000
    max_selection_chars: int = 4000
    router_threshold: float = 0.5
    max_llm_calls: int = 3
    history_turns: int = 3
    visitor_per_hour: int = 20


def answer_language(text: str) -> str:
    letters = re.findall(r"[^\W\d_]", text)
    cyr = sum(1 for c in letters if "Ѐ" <= c <= "ӿ")
    return (
        "русский"
        if letters and cyr / len(letters) >= 0.5
        else "английский"
        if letters
        else "русский"
    )


class VisitorLimit:
    def __init__(self, per_hour: int, clock: Clock) -> None:
        self.per_hour = per_hour
        self.clock = clock
        self.seen: dict[str, deque[float]] = defaultdict(deque)

    def check(self, visitor: str) -> int | None:
        """``None`` — можно; иначе через сколько секунд."""
        now = self.clock.now().timestamp()
        window = self.seen[visitor]
        while window and now - window[0] >= 3600:
            window.popleft()
        if len(window) >= self.per_hour:
            return int(3600 - (now - window[0])) + 1
        window.append(now)
        return None


class Assistant:
    def __init__(
        self,
        search,
        llm,
        *,
        settings: AssistantSettings | None = None,
        clock: Clock | None = None,
        hooks: dict[str, Callable[[AskRequest, list[dict]], list[dict]]] | None = None,
    ) -> None:
        self.search = search
        self.llm = llm
        self.settings = settings or AssistantSettings()
        self.clock = clock or SystemClock()
        self.hooks = hooks or {}
        self.limits = VisitorLimit(self.settings.visitor_per_hour, self.clock)

    # --- маршрутизация ---

    def route(self, request: AskRequest) -> tuple[str, list[str]]:
        started = time.perf_counter()
        fallback = "local" if request.selection else "knowledge"
        try:
            value = self.llm.structured(
                "fast",
                "assistant.route",
                {
                    "question": request.question,
                    "selection": request.selection or "",
                    "history": self._history_summary(request),
                },
                ROUTER_SCHEMA,
                "route",
            )
            kind, confidence = value["type"], float(value["confidence"])
            names = value.get("names", [])
            used_fallback = confidence < self.settings.router_threshold
        except LlmUnavailable as exc:
            if exc.kind in ("budget_exhausted",):
                raise
            kind, confidence, names, used_fallback = fallback, 0.0, [], True
        except ServiceUnavailable:
            kind, confidence, names, used_fallback = fallback, 0.0, [], True
        if used_fallback and kind != "off_topic":
            kind = fallback
        duration = round((time.perf_counter() - started) * 1000, 2)
        events.emit(
            "assistant.routed",
            type=kind,
            confidence=confidence,
            fallback=used_fallback,
            duration_ms=duration,
        )
        return kind, names

    def _history_summary(self, request: AskRequest) -> str:
        earlier = (
            request.history[: -self.settings.history_turns]
            if len(request.history) > self.settings.history_turns
            else []
        )
        recent = request.history[-self.settings.history_turns :]
        lines = []
        if earlier:
            lines.append("Раньше читатель спрашивал: " + "; ".join(h["question"] for h in earlier))
        for h in recent:
            lines.append(f"Вопрос: {h['question']}\nОтвет: {h.get('answer', '')[:1500]}")
        return "\n\n".join(lines)

    # --- поиск ---

    def _gather(self, kind: str, request: AskRequest, names: list[str]) -> list[dict]:
        chain = CHAINS[kind]
        query_text = request.question
        if request.selection:
            query_text = f"{request.question}\n{request.selection}"
        found: list[dict] = []
        seen: set[str] = set()
        for step in chain["searches"]:
            if "if_fewer_than" in step and len(found) >= step["if_fewer_than"]:
                continue
            scope = step["scope"]
            if scope == "toggle":
                scope = "current" if request.scope == "current" and request.source_id else "all"
            query: dict[str, Any] = {
                "query": query_text[:2000],
                "limit": step["limit"],
                "neighbors": step.get("neighbors", 0),
                "per_chapter": step.get("per_chapter", 3),
                "extra_terms": list(step.get("extra_terms", [])) + names,
            }
            if scope == "current" and request.source_id:
                query["sources"] = [request.source_id]
                query["priority"] = list(request.selection_paragraphs)
            if scope == "others" and request.source_id:
                query["exclude_sources"] = [request.source_id]
            results = self.search.search(**query)["results"]
            events.emit("assistant.searched", scope=scope, results=len(results))
            for r in results:
                if r["paragraph_id"] not in seen:
                    seen.add(r["paragraph_id"])
                    found.append(r)
        for hook in chain.get("hooks", []):
            if hook in self.hooks:
                found = self.hooks[hook](request, found)
        return found

    # --- ответ ---

    def ask(self, request: AskRequest) -> Iterator[dict[str, Any]]:
        started = time.perf_counter()
        events.emit(
            "assistant.question.received",
            question_length=len(request.question),
            has_selection=bool(request.selection),
            sources_only=request.sources_only,
        )
        if (
            len(request.question) > self.settings.max_question_chars
            or len(request.selection or "") > self.settings.max_selection_chars
        ):
            events.emit("assistant.refused", reason="too_long")
            yield {
                "type": "refused",
                "reason": "too_long",
                "message": "Слишком длинный фрагмент или вопрос: выделите меньше.",
            }
            return
        wait = self.limits.check(request.visitor)
        if wait is not None:
            events.emit("assistant.refused", reason="visitor_limit")
            yield {
                "type": "unavailable",
                "reason": "visitor_limit",
                "retry_after_seconds": wait,
                "message": f"Слишком много вопросов подряд. Спросите снова через "
                f"{max(1, wait // 60)} мин.",
            }
            return
        if not request.question.strip() and request.selection:
            request.question = "Объясни этот фрагмент."
        try:
            kind, names = self.route(request)
        except LlmUnavailable:
            yield from self._unavailable("budget_exhausted")
            return
        calls = 1
        if CHAINS[kind].get("refuse"):
            events.emit("assistant.refused", reason="off_topic")
            yield {
                "type": "refused",
                "reason": "off_topic",
                "message": "Я помогаю разбираться с материалами по философии.",
            }
            return
        try:
            results = self._gather(kind, request, names)
        except ServiceUnavailable:
            yield {
                "type": "unavailable",
                "reason": "search_unavailable",
                "message": "Ответ временно недоступен: поиск не отвечает.",
            }
            return
        strict = request.sources_only or not request.generation
        if not results and strict:
            events.emit("assistant.refused", reason="no_sources")
            yield {
                "type": "no_answer",
                "message": "В источниках ответа не нашлось.",
                "suggestions": [],
            }
            return
        passages = {
            i + 1: Passage(
                i + 1,
                r["paragraph_id"],
                r["source_id"],
                r.get("chapter_id"),
                r.get("section_title") or "",
                r["text"],
                quoting=r.get("quoting", True),
            )
            for i, r in enumerate(results)
        }
        if not results:
            yield {
                "type": "notice",
                "kind": "no_library_support",
                "message": "Ответ составлен без опоры на библиотеку.",
            }
        data = {
            "question": request.question,
            "history": self._history_summary(request),
            "answer_language": answer_language(request.question),
            "passages": "\n\n".join(
                f"[{p.number}] {p.title}\n{p.text}"
                + ("" if p.quoting else "\n(пересказывай, не цитируй дословно)")
                for p in passages.values()
            ),
        }
        if kind != "knowledge":
            data["selection"] = request.selection or ""
        stream = FragmentStream(passages)
        stats = {
            "fragments": 0,
            "grounded": 0,
            "ungrounded": 0,
            "hidden": 0,
            "removed_citations": 0,
            "removed_quotes": 0,
        }
        first_ms = -1.0
        calls += 1
        assert calls <= self.settings.max_llm_calls

        def emit_fragments(fragments) -> Iterator[dict[str, Any]]:
            nonlocal first_ms
            for fragment in fragments:
                stats["removed_citations"] += fragment.removed_citations
                stats["removed_quotes"] += fragment.removed_quotes
                if fragment.removed_citations:
                    events.emit("assistant.citation.invented", count=fragment.removed_citations)
                if not fragment.grounded and strict:
                    stats["hidden"] += 1
                    continue
                stats["fragments"] += 1
                stats["grounded" if fragment.grounded else "ungrounded"] += 1
                if first_ms < 0:
                    first_ms = round((time.perf_counter() - started) * 1000, 2)
                    metrics.observe("assistant.first_fragment_ms", first_ms)
                yield {"type": "fragment", **fragment.to_json()}

        try:
            try:
                for item in self.llm.stream("main", CHAINS[kind]["template"], data, "answer"):
                    if item["type"] == "delta":
                        yield from emit_fragments(stream.feed(item["text"]))
                    elif item["type"] == "error":
                        yield from emit_fragments(stream.finish())
                        events.emit(
                            "assistant.answer.interrupted",
                            type=kind,
                            fragments=stats["fragments"],
                            error_kind="stream_broken",
                        )
                        yield {
                            "type": "error",
                            "message": "Ответ оборвался. Можно повторить.",
                            "retry": True,
                        }
                        return
            except LlmUnavailable as exc:
                yield from self._unavailable(exc.kind)
                return
            yield from emit_fragments(stream.finish())
        except GeneratorExit:
            events.emit("assistant.stopped", fragments=stats["fragments"])
            raise
        if strict and stats["fragments"] == 0:
            yield {
                "type": "no_answer",
                "message": "В источниках ответа не нашлось.",
                "suggestions": [p.title for p in passages.values()][:3],
            }
        total = round((time.perf_counter() - started) * 1000, 2)
        events.emit(
            "assistant.answer.completed",
            type=kind,
            passages=len(passages),
            llm_calls=calls,
            first_fragment_ms=first_ms,
            total_ms=total,
            **stats,
        )
        yield {
            "type": "done",
            "kind": kind,
            "stats": stats,
            "passages": len(passages),
            "llm_calls": calls,
            "first_fragment_ms": first_ms,
            "total_ms": total,
        }

    def _unavailable(self, kind: str) -> Iterator[dict[str, Any]]:
        if kind == "budget_exhausted":
            events.emit("assistant.refused", reason="budget_exhausted")
            yield {
                "type": "unavailable",
                "reason": "budget_exhausted",
                "message": "Сегодня ассистент недоступен, он заработает завтра. Чтение и "
                "карточки работают.",
            }
        else:
            events.emit("assistant.refused", reason="llm_unavailable")
            yield {
                "type": "unavailable",
                "reason": "llm_unavailable",
                "message": "Ассистент временно недоступен. Чтение и карточки работают.",
            }
