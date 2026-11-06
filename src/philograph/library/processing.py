"""Конвейер обработки версии источника.

Шаги: получение файлов → извлечение текста → проверка качества → разбор структуры →
автоматические проверки. Состояние версии — последний пройденный шаг; ошибка записывается
рядом с ним. Результат извлечения сохраняется по ключу входов, поэтому повторная обработка,
изменившая только разбор, не распознаёт страницы заново.
"""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import timedelta
from typing import Any

from sqlalchemy import Engine, and_, select

from philograph.library import checks, corrections, matching, quality
from philograph.library import schema as t
from philograph.library.extract import ExtractionError, OcrEngine, extract_pdf, sniff_format
from philograph.library.extract import extract as extract_file
from philograph.library.model import (
    Document,
    RawDocument,
    RawLine,
    RawPage,
    RawSpan,
)
from philograph.library.parse import ParseSettings, parse
from philograph.library.registry import Registry, RegistryError
from philograph.platform import context, events
from philograph.platform.clock import Clock, SystemClock
from philograph.platform.files import FileStore, fingerprint

# 2: сноски HTML/EPUB, обложки PDF, выбросы номеров страниц;
# 3: заглушки пустых страниц PDF и неоцифрованных подстраниц
PIPELINE_VERSION = "3"
STEP_VERSIONS = {"extract": "3", "parse": "3"}
FORMATS = ("txt", "html", "epub", "pdf")
ORDER = ["created", "files_received", "text_extracted", "quality_passed", "structured", "checked"]

events.define(
    "library.pipeline.step.started",
    "info",
    "Шаг обработки версии начат",
    required=("version_id", "step"),
)
events.define(
    "library.pipeline.step.finished",
    "info",
    "Шаг обработки версии завершён",
    required=("version_id", "step", "state"),
    optional=("reused",),
)
events.define(
    "library.pipeline.step.failed",
    "error",
    "Шаг обработки версии не удался",
    required=("version_id", "step", "message"),
    optional=("page",),
)
events.define(
    "library.pipeline.nothing_to_do",
    "info",
    "Изменений нет, версия не создана",
    required=("source_id",),
)
events.define(
    "library.pipeline.busy", "warning", "Источник уже обрабатывается", required=("source_id",)
)
events.define(
    "library.pipeline.interrupted",
    "warning",
    "Прерванный запуск освобождён",
    required=("version_id",),
)
events.define(
    "library.pipeline.budget_stop",
    "warning",
    "Обработка остановлена: исчерпан лимит запуска",
    required=("version_id", "spent_usd", "limit_usd"),
)
events.define(
    "library.pipeline.estimate",
    "info",
    "Оценка стоимости обработки",
    required=("source_id", "paid_pages", "estimate_usd"),
)
events.define(
    "library.pipeline.batch.finished",
    "info",
    "Пакетный запуск завершён",
    required=(
        "total",
        "ready",
        "awaiting_quality",
        "deferred",
        "failed",
        "nothing_to_do",
        "cost_usd",
    ),
)
events.define(
    "library.quality.assessed",
    "info",
    "Посчитаны метрики качества текста",
    required=("version_id", "needs_review"),
    optional=("defer_reason",),
)
events.define(
    "library.quality.decided",
    "info",
    "Решение о качестве текста",
    required=("version_id", "decision", "actor"),
    optional=("reason", "carried_over"),
)
events.define(
    "library.outbox.dispatched", "info", "Событие передано в очередь", required=("event_id", "kind")
)


class ProcessingBusy(Exception):
    pass


class BudgetStop(Exception):
    pass


class StepFailed(Exception):
    def __init__(self, step: str, message: str, page: str | None = None) -> None:
        super().__init__(message)
        self.step = step
        self.page = page


@dataclass
class PipelineSettings:
    max_file_bytes: int = 200 * 1024 * 1024
    max_pages: int = 3000
    fetch_retries: int = 2
    lock_timeout: timedelta = timedelta(minutes=30)
    max_parallel: int = 2
    ocr_price_per_page: float = 0.0  # платное распознавание в облаке; локальное бесплатно
    quality: quality.QualitySettings = field(default_factory=quality.QualitySettings)
    match_threshold: float = 0.85


Fetch = Callable[[dict[str, Any]], bytes]


def _digest(*parts: Any) -> str:
    return hashlib.sha256(
        json.dumps(parts, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# --- сериализация сырого документа --------------------------------------------------


def raw_to_json(raw: RawDocument) -> dict[str, Any]:
    return asdict(raw)


def _page_from_json(data: dict[str, Any]) -> RawPage:
    lines = [
        RawLine(**{**ln, "spans": [RawSpan(**s) for s in ln["spans"]]}) for ln in data["lines"]
    ]
    return RawPage(**{**data, "lines": lines})


def raw_from_json(data: dict[str, Any]) -> RawDocument:
    pages = [_page_from_json(p) for p in data["pages"]]
    return RawDocument(
        pages=pages,
        fmt=data["fmt"],
        paginated=data["paginated"],
        printed_toc=[tuple(x) for x in data.get("printed_toc", [])],
    )


class Pipeline:
    def __init__(
        self,
        registry: Registry,
        files: FileStore,
        fetch: Fetch,
        *,
        ocr: OcrEngine | None = None,
        clock: Clock | None = None,
        settings: PipelineSettings | None = None,
    ) -> None:
        self.registry = registry
        self.engine: Engine = registry.engine
        self.files = files
        self.fetch = fetch
        self.ocr = ocr
        self.clock = clock or SystemClock()
        self.settings = settings or PipelineSettings()
        self._slots = threading.BoundedSemaphore(self.settings.max_parallel)
        self._lock = threading.Lock()
        self.active = 0
        self.peak = 0
        self._run_spent: dict[str, float] = {}

    # --- журнал версии ---

    def _log(
        self,
        version_id: str,
        step: str,
        event: str,
        message: str | None = None,
        *,
        page: str | None = None,
        cost: float | None = None,
    ) -> None:
        version = self.registry.version(version_id)
        with self.engine.begin() as conn:
            conn.execute(
                t.version_log.insert().values(
                    version_id=version_id,
                    run_id=context.run_id(),
                    time=self.clock.now(),
                    step=step,
                    event=event,
                    message=message,
                    page=page,
                    cost_usd=cost,
                    settings=version["settings"],
                    pipeline_version=version["pipeline_version"],
                )
            )

    def journal(self, version_id: str) -> list[dict[str, Any]]:
        with self.engine.begin() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    select(t.version_log)
                    .where(t.version_log.c.version_id == version_id)
                    .order_by(t.version_log.c.id)
                ).mappings()
            ]

    # --- запуск ---

    def _corrections(self, source_id: str) -> list[corrections.Correction]:
        with self.engine.begin() as conn:
            rows = (
                conn.execute(
                    select(t.corrections)
                    .where(t.corrections.c.source_id == source_id)
                    .order_by(t.corrections.c.id)
                )
                .mappings()
                .all()
            )
        return [
            corrections.Correction(
                r["id"], r["op"], corrections.Anchor(**r["anchor"]), r["payload"]
            )
            for r in rows
        ]

    def add_correction(
        self,
        actor: str,
        source_id: str,
        op: str,
        anchor: corrections.Anchor,
        payload: dict[str, Any],
        reason: str | None = None,
    ) -> int:
        with self.engine.begin() as conn:
            cid = conn.execute(
                t.corrections.insert().values(
                    source_id=source_id,
                    op=op,
                    anchor=asdict(anchor),
                    payload=payload,
                    actor=actor,
                    reason=reason,
                    time=self.clock.now(),
                )
            ).inserted_primary_key[0]
            self.registry.actions.record(
                actor, "correct_structure", source_id, {"op": op, "reason": reason}, conn=conn
            )
        return cid

    def _receive(self, source_id: str) -> list[dict[str, Any]]:
        """Получает файлы источника по порядку, с отпечатком и проверкой формата и размера."""
        received = []
        for spec in self.registry.get(source_id).files:
            data = None
            reason = ""
            for _ in range(1 + self.settings.fetch_retries):
                try:
                    data = self.fetch(spec)
                    break
                except OSError as exc:
                    reason = str(exc) or type(exc).__name__
            if data is None:
                raise StepFailed("receive", f"файл «{spec.get('name')}» не получен: {reason}")
            if len(data) > self.settings.max_file_bytes:
                raise StepFailed("receive", f"файл «{spec.get('name')}» слишком большой")
            fmt = sniff_format(data)
            if fmt not in FORMATS:
                raise StepFailed("receive", f"файл «{spec.get('name')}»: формат не поддерживается")
            if fmt == "pdf":
                import pymupdf

                try:
                    with pymupdf.open(stream=data, filetype="pdf") as doc:
                        if doc.needs_pass:
                            raise StepFailed(
                                "receive", f"файл «{spec.get('name')}» защищён паролем"
                            )
                        if doc.page_count > self.settings.max_pages:
                            raise StepFailed(
                                "receive",
                                f"в файле «{spec.get('name')}» больше "
                                f"{self.settings.max_pages} страниц",
                            )
                except StepFailed:
                    raise
                except Exception as exc:
                    raise StepFailed(
                        "receive", f"файл «{spec.get('name')}» повреждён: {exc}"
                    ) from exc
            digest = self.files.put(data)
            received.append(
                {"name": spec.get("name"), "sha256": digest, "format": fmt, "size": len(data)}
            )
        return received

    def start(self, actor: str, source_id: str, *, limit_usd: float | None = None) -> str | None:
        """Создаёт версию и обрабатывает её. ``None`` — изменений нет, версия не создана."""
        blocked = self.registry.blocked_reason(source_id)
        if blocked:
            raise RegistryError(blocked)
        source = self.registry.get(source_id)
        received = self._receive(source_id)
        for item in received:
            for other in self.registry.duplicate_files(item["sha256"], exclude=source_id):
                events.emit("library.source.duplicate", other_source_id=other, by="file")
        digest = _digest(
            [c.op for c in self._corrections(source_id)],
            [asdict(c.anchor) for c in self._corrections(source_id)],
            [c.payload for c in self._corrections(source_id)],
        )

        def same_inputs(version: dict[str, Any]) -> bool:
            return (
                [f["sha256"] for f in version["files"]] == [f["sha256"] for f in received]
                and version["pipeline_version"] == PIPELINE_VERSION
                and version["settings"] == source.settings
                and version["corrections_digest"] == digest
            )

        if source.published_version and same_inputs(
            self.registry.version(source.published_version)
        ):
            events.emit("library.pipeline.nothing_to_do", source_id=source_id)
            return None
        # Версия с теми же входами уже ждёт решения: вторая такая же не нужна.
        # Упавшая на шаге версия с теми же входами продолжается с места падения.
        versions = self.registry.versions(source_id)
        latest = max(versions, key=lambda v: v["number"]) if versions else None
        if (
            latest is not None
            and latest["id"] != source.published_version
            and latest["state"] != "published"
            and same_inputs(latest)
        ):
            waiting = latest["state"] in (
                "checked",
                "awaiting_quality",
                "deferred",
                "withdrawn",
                "replaced",
            )
            if latest["error"] or not waiting:
                # упавшая или прерванная на полпути версия продолжается с места остановки
                self.run(latest["id"], limit_usd=limit_usd)
                return latest["id"]
            events.emit("library.pipeline.nothing_to_do", source_id=source_id)
            return None
        version_id = self.registry.create_version(
            source_id, received, PIPELINE_VERSION, source.settings, digest
        )
        self.registry.update_version(version_id, state="files_received")
        self._log(version_id, "receive", "finished")
        self.run(version_id, limit_usd=limit_usd)
        return version_id

    # --- блокировка ---

    def _acquire(self, version_id: str) -> str:
        version = self.registry.version(version_id)
        owner = uuid.uuid4().hex
        now = self.clock.now()
        with self._lock, self.engine.begin() as conn:
            rows = conn.execute(
                select(t.versions.c.id, t.versions.c.lock_owner, t.versions.c.lock_heartbeat).where(
                    and_(
                        t.versions.c.source_id == version["source_id"],
                        t.versions.c.lock_owner.is_not(None),
                    )
                )
            ).all()
            for row in rows:
                beat = row.lock_heartbeat
                if beat is not None and beat.tzinfo is None:
                    beat = beat.replace(tzinfo=now.tzinfo)
                if beat is not None and now - beat < self.settings.lock_timeout:
                    events.emit("library.pipeline.busy", source_id=version["source_id"])
                    raise ProcessingBusy("обработка источника уже идёт")
                conn.execute(
                    t.versions.update()
                    .where(t.versions.c.id == row.id)
                    .values(lock_owner=None, lock_heartbeat=None)
                )
                events.emit("library.pipeline.interrupted", version_id=row.id)
            conn.execute(
                t.versions.update()
                .where(t.versions.c.id == version_id)
                .values(lock_owner=owner, lock_heartbeat=now)
            )
        return owner

    def _release(self, version_id: str) -> None:
        self.registry.update_version(version_id, lock_owner=None, lock_heartbeat=None)

    def _heartbeat(self, version_id: str) -> None:
        self.registry.update_version(version_id, lock_heartbeat=self.clock.now())

    def interrupted(self) -> list[str]:
        """Запуски, которые держат блокировку дольше времени ожидания."""
        now = self.clock.now()
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(t.versions.c.id, t.versions.c.lock_heartbeat).where(
                    t.versions.c.lock_owner.is_not(None)
                )
            ).all()
        stale = []
        for row in rows:
            beat = row.lock_heartbeat
            if beat.tzinfo is None:
                beat = beat.replace(tzinfo=now.tzinfo)
            if now - beat >= self.settings.lock_timeout:
                stale.append(row.id)
        return stale

    # --- обработка ---

    def run(self, version_id: str, *, limit_usd: float | None = None) -> str:
        """Продолжает обработку с шага после последнего пройденного. Возвращает состояние."""
        with self._slots:
            with self._lock:
                self.active += 1
                self.peak = max(self.peak, self.active)
            try:
                return self._run(version_id, limit_usd)
            finally:
                with self._lock:
                    self.active -= 1

    def _run(self, version_id: str, limit_usd: float | None) -> str:
        self._acquire(version_id)
        try:
            while True:
                version = self.registry.version(version_id)
                state = version["state"]
                if state in ("checked", "awaiting_quality", "deferred", "published"):
                    return state
                step = {
                    "files_received": self._extract,
                    "text_extracted": self._quality,
                    "quality_passed": self._structure,
                    "structured": self._check,
                }.get(state)
                if step is None:
                    return state
                name = step.__name__.strip("_")
                events.emit("library.pipeline.step.started", version_id=version_id, step=name)
                self._log(version_id, name, "started")
                try:
                    new_state, reused = step(version, limit_usd)
                except BudgetStop:
                    return state
                except Exception as exc:  # любая ошибка шага записывается в версию
                    page = getattr(exc, "page", None)
                    expected = isinstance(exc, (StepFailed, ExtractionError))
                    message = str(exc) if expected else f"{type(exc).__name__}: {exc}"
                    self.registry.update_version(
                        version_id, error={"step": name, "message": message, "page": page}
                    )
                    self._log(version_id, name, "error", message, page=page)
                    events.emit(
                        "library.pipeline.step.failed",
                        version_id=version_id,
                        step=name,
                        message=message,
                        page=page,
                        error_kind="pipeline_step" if expected else "unexpected",
                    )
                    return state
                self.registry.update_version(version_id, state=new_state, error=None)
                self._log(version_id, name, "finished")
                events.emit(
                    "library.pipeline.step.finished",
                    version_id=version_id,
                    step=name,
                    state=new_state,
                    reused=reused,
                )
                self._heartbeat(version_id)
        finally:
            self._release(version_id)

    # шаг: извлечение

    def _raw_key(self, version: dict[str, Any], item: dict[str, Any]) -> str:
        settings = version["settings"]
        return _digest(
            "extract",
            STEP_VERSIONS["extract"],
            item["sha256"],
            settings.get("languages"),
            settings.get("encoding"),
            settings.get("spreads"),
            settings.get("skip_pages"),
        )

    def _extract(self, version: dict[str, Any], limit_usd: float | None) -> tuple[str, bool]:
        settings = version["settings"]
        documents: list[RawDocument] = []
        reused = True
        for item in version["files"]:
            key = self._raw_key(version, item)
            artifact = self._cached_raw(key)
            if artifact is None:
                reused = False
                artifact = self._extract_file(version, item, key, limit_usd)
                self.files.put(json.dumps(raw_to_json(artifact)).encode("utf-8"))
                with self.engine.begin() as conn:
                    conn.execute(t.page_cache.delete().where(t.page_cache.c.key == key))
                    conn.execute(
                        t.page_cache.insert().values(
                            key=key,
                            page={
                                "artifact": fingerprint(
                                    json.dumps(raw_to_json(artifact)).encode("utf-8")
                                )
                            },
                        )
                    )
            documents.append(artifact)
        raw = self._combine(documents, settings, version["files"])
        self.files.put(json.dumps(raw_to_json(raw)).encode("utf-8"))
        text = "\n".join(line.text for page in raw.pages for line in page.lines)
        self.registry.update_version(
            version["id"],
            text_digest=fingerprint(text.encode()),
            quality={"raw": fingerprint(json.dumps(raw_to_json(raw)).encode("utf-8"))},
        )
        return "text_extracted", reused

    def _cached_raw(self, key: str) -> RawDocument | None:
        with self.engine.begin() as conn:
            entry = conn.scalar(select(t.page_cache.c.page).where(t.page_cache.c.key == key))
        if not entry or "artifact" not in entry or not self.files.exists(entry["artifact"]):
            return None
        return raw_from_json(json.loads(self.files.get(entry["artifact"])))

    def _extract_file(
        self, version: dict[str, Any], item: dict[str, Any], key: str, limit_usd: float | None
    ) -> RawDocument:
        data = self.files.get(item["sha256"])
        settings = version["settings"]
        languages = settings.get("ocr_languages") or settings.get("languages") or ["rus"]
        if item["format"] != "pdf":
            return extract_file(data, item["format"], encoding=settings.get("encoding"))
        done: dict[int, RawPage] = {}
        with self.engine.begin() as conn:
            for row in conn.execute(
                select(t.page_cache).where(t.page_cache.c.key.like(f"{key}:page:%"))
            ).mappings():
                index = int(row["key"].rsplit(":", 1)[1])
                done[index] = _page_from_json(row["page"])
        run = context.run_id() or version["id"]

        def on_page(page: RawPage) -> None:
            if not page.has_text_layer and self.settings.ocr_price_per_page:
                spent = self._run_spent.get(run, 0.0) + self.settings.ocr_price_per_page
                self._run_spent[run] = spent
                self._log(
                    version["id"],
                    "extract",
                    "cost",
                    page=str(page.index + 1),
                    cost=self.settings.ocr_price_per_page,
                )
            page_key = f"{key}:page:{page.index}"
            with self.engine.begin() as conn:
                conn.execute(t.page_cache.delete().where(t.page_cache.c.key == page_key))
                conn.execute(t.page_cache.insert().values(key=page_key, page=asdict(page)))
            self._heartbeat(version["id"])

        class _Budgeted:
            def __init__(inner, engine: OcrEngine) -> None:
                inner.engine = engine

            def recognize(inner, image: bytes, langs: list[str]) -> tuple[list[RawLine], float]:
                if (
                    limit_usd is not None
                    and self.settings.ocr_price_per_page
                    and (
                        self._run_spent.get(run, 0.0) + self.settings.ocr_price_per_page > limit_usd
                    )
                ):
                    events.emit(
                        "library.pipeline.budget_stop",
                        version_id=version["id"],
                        spent_usd=round(self._run_spent.get(run, 0.0), 6),
                        limit_usd=limit_usd,
                    )
                    raise BudgetStop()
                return inner.engine.recognize(image, langs)

        ocr = _Budgeted(self.ocr) if self.ocr is not None else None
        skip = set(settings.get("skip_pages") or [])
        return extract_pdf(
            data,
            languages=languages,
            ocr=ocr,
            skip_pages=skip,
            on_page=on_page,
            done_pages=done,
            store_image=self.files.put,
            spreads=bool(settings.get("spreads")),
        )

    @staticmethod
    def _combine(
        documents: list[RawDocument], settings: dict[str, Any], files: list[dict[str, Any]]
    ) -> RawDocument:
        if len(documents) == 1:
            return documents[0]
        pages: list[RawPage] = []
        titles = settings.get("volume_titles") or [
            f.get("name") or f"Том {i + 1}" for i, f in enumerate(files)
        ]
        for i, doc in enumerate(documents):
            for j, page in enumerate(doc.pages):
                page.file_index = i
                if j == 0:
                    page.lines.insert(0, RawLine(titles[i], heading_level=0, block_break=True))
                page.index = len(pages)
                pages.append(page)
        return RawDocument(
            pages=pages, fmt=documents[0].fmt, paginated=any(d.paginated for d in documents)
        )

    def _raw(self, version: dict[str, Any]) -> RawDocument:
        return raw_from_json(json.loads(self.files.get(version["quality"]["raw"])))

    # шаг: проверка качества

    def _quality(self, version: dict[str, Any], limit_usd: float | None) -> tuple[str, bool]:
        raw = self._raw(version)
        languages = version["settings"].get("languages") or ["ru"]
        assessment = quality.assess(raw, languages, self.settings.quality, seed=version["id"])
        stored = {**(version["quality"] or {}), "assessment": assessment.to_json()}
        self.registry.update_version(version["id"], quality=stored)
        events.emit(
            "library.quality.assessed",
            version_id=version["id"],
            needs_review=assessment.needs_review,
            defer_reason=assessment.defer_reason,
        )
        if assessment.defer_reason:
            self.registry.update_version(version["id"], deferred_reason=assessment.defer_reason)
            return "deferred", False
        if not assessment.needs_review:
            return "quality_passed", False
        carried = self._accepted_with_same_text(version)
        if carried:
            stored["decision"] = {"decision": "accept", "actor": "system", "carried_over": carried}
            self.registry.update_version(version["id"], quality=stored)
            events.emit(
                "library.quality.decided",
                version_id=version["id"],
                decision="accept",
                actor="system",
                carried_over=carried,
            )
            return "quality_passed", True
        return "awaiting_quality", False

    def _accepted_with_same_text(self, version: dict[str, Any]) -> str | None:
        for other in self.registry.versions(version["source_id"]):
            decision = (other["quality"] or {}).get("decision") or {}
            if (
                other["id"] != version["id"]
                and other["text_digest"] == version["text_digest"]
                and decision.get("decision") == "accept"
            ):
                return other["id"]
        return None

    def decide_quality(
        self, actor: str, version_id: str, decision: str, reason: str | None = None
    ) -> str:
        version = self.registry.version(version_id)
        if version["state"] != "awaiting_quality":
            raise RegistryError("версия не ждёт решения о качестве")
        if decision not in ("accept", "defer"):
            raise RegistryError("решение: принять или отложить")
        stored = {
            **(version["quality"] or {}),
            "decision": {
                "decision": decision,
                "actor": actor,
                "reason": reason,
                "time": self.clock.now().isoformat(),
            },
        }
        state = "quality_passed" if decision == "accept" else "deferred"
        self.registry.update_version(
            version_id,
            quality=stored,
            state=state,
            deferred_reason=reason if decision == "defer" else None,
        )
        self.registry.actions.record(actor, f"quality_{decision}", version_id, {"reason": reason})
        events.emit(
            "library.quality.decided",
            version_id=version_id,
            decision=decision,
            actor=actor,
            reason=reason,
        )
        return self.run(version_id) if decision == "accept" else state

    def review_sample(self, version_id: str) -> list[dict[str, Any]]:
        """Страницы выборки: изображение, текст и сомнительные слова."""
        version = self.registry.version(version_id)
        raw = self._raw(version)
        assessment = version["quality"]["assessment"]
        by_index = {p["index"]: p for p in assessment["pages"]}
        pages = {p.index: p for p in raw.pages}
        return [
            {
                "index": i,
                "image": pages[i].image_ref,
                "text": "\n".join(ln.text for ln in pages[i].lines),
                "suspicious": by_index[i]["suspicious_words"],
            }
            for i in assessment["sample"]
            if i in pages
        ]

    def deferred(self) -> list[dict[str, Any]]:
        with self.engine.begin() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    select(
                        t.versions.c.id, t.versions.c.source_id, t.versions.c.deferred_reason
                    ).where(t.versions.c.state == "deferred")
                ).mappings()
            ]

    # шаг: разбор структуры

    def _structure(self, version: dict[str, Any], limit_usd: float | None) -> tuple[str, bool]:
        source = self.registry.get(version["source_id"])
        settings = version["settings"]
        raw = self._raw(version)
        temp = iter(range(1, 10**9))
        doc = parse(
            raw,
            ParseSettings(
                language=source.language,
                header_patterns=settings.get("header_patterns", []),
                page_offset=settings.get("page_offset"),
                section_kinds=settings.get("section_kinds", {}),
            ),
            lambda prefix: f"tmp-{prefix}-{next(temp)}",
        )
        previous = (
            self.registry.load_document(source.published_version)
            if source.published_version
            else Document(sections=[])
        )
        result = self._assign_ids(doc, previous)
        unapplied = corrections.apply(doc, self._corrections(source.id), _new_id)
        summary = self._summary(doc, previous, result, source.published_version)
        summary["unapplied_corrections"] = [c.id for c in unapplied]
        self.registry.save_document(version["id"], doc)
        issues = checks.check(doc, unapplied_corrections=len(unapplied))
        self.registry.update_version(
            version["id"], summary=summary, issues=[asdict(i) for i in issues]
        )
        return "structured", False

    def _assign_ids(self, doc: Document, previous: Document) -> matching.MatchResult:
        old = [matching.Item(b.id, b.text) for _, b in previous.blocks()]
        new = [matching.Item(b.id, b.text) for _, b in doc.blocks()]
        result = matching.match(old, new, _new_id, threshold=self.settings.match_threshold)
        for _, block in doc.blocks():
            block.id = result.ids[block.id]
        old_notes = [matching.Item(n.id, n.text) for _, n in previous.footnotes()]
        new_notes = [matching.Item(n.id, n.text) for _, n in doc.footnotes()]
        notes = matching.match(
            old_notes, new_notes, _new_id, threshold=self.settings.match_threshold
        )
        for _, note in doc.footnotes():
            note.id = notes.ids[note.id]
        for _, block in doc.blocks():
            for ref in block.notes:
                ref.footnote_id = notes.ids.get(ref.footnote_id, ref.footnote_id)
        # Разделы сохраняют идентификатор, если совпали название и уровень по порядку.
        old_sections: dict[tuple[str, int], list[str]] = {}
        for s in previous.walk():
            old_sections.setdefault((s.title, s.level), []).append(s.id)
        for s in doc.walk():
            queue = old_sections.get((s.title, s.level))
            s.id = queue.pop(0) if queue else _new_id("sec")
        return result

    @staticmethod
    def _summary(
        doc: Document, previous: Document, result: matching.MatchResult, against: str | None
    ) -> dict[str, Any]:
        before = {b.id: b.text for _, b in previous.blocks()}
        now = {b.id: b.text for _, b in doc.blocks()}
        changed = sorted(i for i in now if i in before and now[i] != before[i])
        added = sorted(i for i in now if i not in before)
        removed = sorted(i for i in before if i not in now and i not in result.redirected)
        redirected = {k: v for k, v in result.redirected.items() if v in now}
        return {
            "against": against,
            "added": added,
            "changed": changed,
            "removed": removed,
            "redirected": redirected,
            "counts": {
                "added": len(added),
                "changed": len(changed),
                "removed": len(removed),
                "redirected": len(redirected),
            },
        }

    # шаг: проверки

    def _check(self, version: dict[str, Any], limit_usd: float | None) -> tuple[str, bool]:
        issues = version["issues"] or []
        errors = [i for i in issues if i["level"] == "error"]
        if errors:
            raise StepFailed(
                "check", "; ".join(i["message"] for i in errors), page=errors[0].get("page")
            )
        return "checked", False

    # --- оценка, пакет, плановая проверка, повторная обработка ---

    def estimate(self, source_id: str) -> dict[str, float]:
        """Сколько страниц придётся распознавать платно и сколько это стоит."""
        import pymupdf

        paid = 0
        for item in self._receive(source_id):
            if item["format"] != "pdf":
                continue
            with pymupdf.open(stream=self.files.get(item["sha256"]), filetype="pdf") as doc:
                paid += sum(1 for page in doc if not page.get_text().strip())
        estimate = round(paid * self.settings.ocr_price_per_page, 6)
        events.emit(
            "library.pipeline.estimate", source_id=source_id, paid_pages=paid, estimate_usd=estimate
        )
        return {"paid_pages": paid, "estimate_usd": estimate}

    def run_cost(self, run_id: str) -> float:
        return round(self._run_spent.get(run_id, 0.0), 6)

    def batch(
        self, actor: str, source_ids: list[str], *, limit_usd: float | None = None
    ) -> dict[str, Any]:
        run_id = context.run_id() or uuid.uuid4().hex
        totals = {
            "total": len(source_ids),
            "ready": 0,
            "awaiting_quality": 0,
            "deferred": 0,
            "failed": 0,
            "nothing_to_do": 0,
        }
        with context.scope(run_id=run_id):
            for source_id in source_ids:
                try:
                    version_id = self.start(actor, source_id, limit_usd=limit_usd)
                except (StepFailed, RegistryError, ProcessingBusy):
                    totals["failed"] += 1
                    continue
                if version_id is None:
                    totals["nothing_to_do"] += 1
                    continue
                version = self.registry.version(version_id)
                if version["error"]:
                    totals["failed"] += 1
                elif version["state"] == "checked":
                    totals["ready"] += 1
                elif version["state"] in totals:
                    totals[version["state"]] += 1
                else:
                    totals["failed"] += 1
        result = {**totals, "cost_usd": self.run_cost(run_id)}
        events.emit("library.pipeline.batch.finished", **result)
        return result

    def check_updates(self, actor: str) -> list[str]:
        """Плановая проверка: изменились ли файлы по ссылкам. Новые версии ждут публикации."""
        created = []
        for item in self.registry.overview():
            source = self.registry.get(item["source_id"])
            if source.status != "active" or not any("url" in f for f in source.files):
                continue
            version_id = self.start(actor, source.id)
            if version_id is not None:
                created.append(version_id)
        return created

    def reprocess(
        self, actor: str, *, source_ids: list[str] | None = None, older_pipeline: bool = False
    ) -> dict[str, Any]:
        ids = source_ids
        if ids is None:
            ids = []
            for item in self.registry.overview():
                published = item["published_version"]
                if published is None:
                    continue
                if (
                    not older_pipeline
                    or self.registry.version(published)["pipeline_version"] != PIPELINE_VERSION
                ):
                    ids.append(item["source_id"])
        return self.batch(actor, ids)

    def dispatch_outbox(self, queue, subscribers: tuple[str, ...] = ("search", "knowledge")) -> int:
        """Передаёт записанные события в очередь, каждому подписчику своей задачей.

        Задача называется ``<подписчик>:<событие>``; повторная передача не создаёт дублей.
        """
        sent = 0
        for item in self.registry.outbox_pending():
            for subscriber in subscribers:
                queue.enqueue(
                    f"{subscriber}:{item['kind']}",
                    {**item["payload"], "event_id": item["event_id"]},
                    key=f"{item['event_id']}:{subscriber}",
                )
            self.registry.mark_sent(item["event_id"], self.clock.now())
            events.emit("library.outbox.dispatched", event_id=item["event_id"], kind=item["kind"])
            sent += 1
        return sent

    def delete_source(self, actor: str, source_id: str) -> None:
        for digest in self.registry.delete(actor, source_id):
            self.files.delete(digest)

    def save_golden_page(self, actor: str, source_id: str, page_index: int, text: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                t.golden_pages.delete().where(
                    and_(
                        t.golden_pages.c.source_id == source_id,
                        t.golden_pages.c.page_index == page_index,
                    )
                )
            )
            conn.execute(
                t.golden_pages.insert().values(
                    source_id=source_id, page_index=page_index, text=text, actor=actor
                )
            )

    def golden_report(self, version_id: str) -> dict[str, Any]:
        version = self.registry.version(version_id)
        raw = self._raw(version)
        pages = {p.index: "\n".join(ln.text for ln in p.lines) for p in raw.pages}
        with self.engine.begin() as conn:
            golden = (
                conn.execute(
                    select(t.golden_pages).where(t.golden_pages.c.source_id == version["source_id"])
                )
                .mappings()
                .all()
            )
        per_page = {
            g["page_index"]: quality.error_rates(pages.get(g["page_index"], ""), g["text"])
            for g in golden
        }
        count = len(per_page) or 1
        return {
            "pages": per_page,
            "cer": round(sum(r["cer"] for r in per_page.values()) / count, 4),
            "wer": round(sum(r["wer"] for r in per_page.values()) / count, 4),
        }
