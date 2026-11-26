"""Наполнение онтологии: извлечение из библиотеки, ядро вручную, простые факты Wikidata.

Извлечение — основной источник утверждений (ontology.md, раздел 12). Модель получает фрагмент
главы из нескольких абзацев и возвращает утверждения; каждое — с цитатой, которую код сверяет
с абзацем. Шлюзу уходит мягкая схема, каждый элемент ответа проверяет этот сервис: плохой
элемент отбрасывается с кодом причины, остальные записываются. Тот же путь проверки и записи
проходят ответы внешнего извлекателя (``external_extraction``). Неоднозначная привязка
сущности не угадывается, а уходит на проверку. Всё, что сделал запуск, можно откатить.
"""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select, update

from philograph.knowledge import extraction_codes as codes
from philograph.knowledge import quotes
from philograph.knowledge import schema as t
from philograph.knowledge.dates import interval
from philograph.knowledge.entity_items import EntityItems
from philograph.knowledge.entity_items import Skip as _Skip
from philograph.knowledge.naming import InvalidName
from philograph.knowledge.registry import RegistryError
from philograph.knowledge.statements import (
    INFLUENCE,
    Attribution,
    Evidence,
    Provenance,
    StatementError,
    Statements,
)
from philograph.knowledge.wikidata import WIKIDATA_ROLES, format_original, simple_time
from philograph.platform import context, events
from philograph.platform.client import ServiceClient, ServiceUnavailable
from philograph.platform.clock import Clock, SystemClock

events.define(
    "knowledge.extraction.fragment",
    "info",
    "Фрагмент главы обработан моделью",
    required=("run_id", "paragraphs", "created", "dropped"),
)
events.define(
    "knowledge.extraction.skipped",
    "info",
    "Источник пропущен извлечением",
    required=("source_id", "reason"),
)
events.define(
    "knowledge.run.started", "info", "Запуск наполнения начат", required=("run_id", "kind")
)
events.define(
    "knowledge.run.finished",
    "info",
    "Запуск наполнения завершён",
    required=("run_id", "kind", "created", "dropped"),
)
events.define(
    "knowledge.run.failed",
    "error",
    "Запуск наполнения прерван исключением",
    required=("run_id", "kind", "error_kind"),
)
events.define(
    "knowledge.import.skipped",
    "debug",
    "Свойство внешней базы не импортируется",
    required=("property", "reason"),
)

FRAGMENT = 30  # предел абзацев во фрагменте; соседние фрагменты перекрываются на один абзац
FRAGMENT_CHARS = 3000  # цель длины фрагмента в символах (ontology-extraction, П12)
EXTRACT_ROLE = "strong"
EXTRACT_TIMEOUT = 1200.0  # таймаут вызова, если шлюз не сообщил бюджет роли
TIMEOUT_MARGIN = 30.0  # запас сверх бюджета шлюза на все попытки
STANCES = ("asserts", "disputes", "mentions")
REQUIRED = ("subject", "type", "object", "paragraph", "quote")
FAILURE_LIMIT = 500
# Wikidata: только простые факты. Влияние (P737) не берём: там нет обоснований.
WIKIDATA_SIMPLE = {
    "P569": "birth",
    "P570": "death",
    "P19": "place",
    "P50": "author",
    "P1066": "teacher",
    "P577": "published",
}
WIKIDATA_SKIPPED = {"P737": "связи влияния только из библиотеки или достройкой"}


@dataclass
class _Run:
    """Счёт запуска в памяти: модель для происхождения, время начала, обработанные фрагменты."""

    model: str | None
    started: datetime
    fragments: int = 0
    created: int = 0
    dropped: Counter = field(default_factory=Counter)


class Filling:
    def __init__(
        self,
        statements: Statements,
        llm: ServiceClient | None,
        library: ServiceClient,
        *,
        clock: Clock | None = None,
        fragment_size: int = FRAGMENT,
        fragment_chars: int = FRAGMENT_CHARS,
        call_timeout: float = EXTRACT_TIMEOUT,
    ) -> None:
        self.statements = statements
        self.entities = statements.entities
        self.registry = statements.registry
        self.llm = llm
        self.library = library
        self.clock = clock or SystemClock()
        self.fragment_size = fragment_size
        self.fragment_chars = fragment_chars
        self.call_timeout = call_timeout
        self.created_entities: list[str] = []  # для пересчёта упоминаний новых сущностей
        self.items = EntityItems(self.entities, statements, self.created_entities)
        self._runs: dict[str, _Run] = {}

    # --- запуски ---

    def start_run(
        self,
        kind: str,
        target: str | None = None,
        *,
        extractor: str | None = None,
        source_id: str | None = None,
        model: str | None = None,
        run_id: str | None = None,
    ) -> str:
        run_id = run_id or context.run_id() or f"fill_{uuid.uuid4().hex[:12]}"
        now = self.clock.now()
        with self.statements.engine.begin() as conn:
            conn.execute(
                t.filling_runs.insert().values(
                    run_id=run_id,
                    kind=kind,
                    target=target,
                    model=model,
                    template_version=None,
                    started_at=now,
                    created=0,
                    dropped=0,
                    status="running",
                    extractor=extractor,
                    source_id=source_id,
                    fragments=0,
                    drop_reasons={},
                )
            )
        self._runs[run_id] = _Run(model, now)
        events.emit("knowledge.run.started", run_id=run_id, kind=kind)
        return run_id

    def _run(self, run_id: str) -> _Run:
        """Счёт запуска; запуск, начатый не этим объектом, получает его при первом обращении."""
        if run_id not in self._runs:
            self._runs[run_id] = _Run(None, self.clock.now())
        return self._runs[run_id]

    def _count(
        self, run_id: str, created: int = 0, dropped: int = 0, reasons: Counter | None = None
    ) -> None:
        with self.statements.engine.begin() as conn:
            row = (
                conn.execute(select(t.filling_runs).where(t.filling_runs.c.run_id == run_id))
                .mappings()
                .one()
            )
            merged = Counter(row["drop_reasons"] or {})
            merged.update(reasons or {})
            conn.execute(
                update(t.filling_runs)
                .where(t.filling_runs.c.run_id == run_id)
                .values(
                    created=row["created"] + created,
                    dropped=row["dropped"] + dropped,
                    drop_reasons=dict(sorted(merged.items())),
                )
            )

    def finish_run(
        self,
        run_id: str,
        *,
        fragments: int | None = None,
        duration_seconds: float | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        cost_usd: float | None = None,
    ) -> dict[str, Any]:
        """Запуск завершён: ``done``, время, метрики. Не переданные метрики шлюзового запуска
        берутся из сводки расходов шлюза по ``run_id`` и из часов сервиса."""
        state = self._runs.pop(run_id, None)
        if cost_usd is None or input_tokens is None or output_tokens is None:
            spend = self._run_spend(run_id)
            cost_usd = spend["cost_usd"] if cost_usd is None else cost_usd
            input_tokens = spend["input_tokens"] if input_tokens is None else input_tokens
            output_tokens = spend["output_tokens"] if output_tokens is None else output_tokens
        values = self._closing(state, fragments, duration_seconds)
        values.update(
            status="done", cost_usd=cost_usd, input_tokens=input_tokens, output_tokens=output_tokens
        )
        row = self._close(run_id, values)
        events.emit(
            "knowledge.run.finished",
            run_id=run_id,
            kind=row["kind"],
            created=row["created"],
            dropped=row["dropped"],
        )
        return row

    def fail_run(self, run_id: str, exc: BaseException) -> dict[str, Any]:
        """Запуск прерван исключением: ``failed``, причина, время; сделанное сохраняется."""
        state = self._runs.pop(run_id, None)
        values = self._closing(state, None, None)
        values.update(status="failed", failure=f"{type(exc).__name__}: {exc}"[:FAILURE_LIMIT])
        row = self._close(run_id, values)
        events.emit(
            "knowledge.run.failed", run_id=run_id, kind=row["kind"], error_kind=type(exc).__name__
        )
        return row

    def _closing(
        self, state: _Run | None, fragments: int | None, duration: float | None
    ) -> dict[str, Any]:
        now = self.clock.now()
        if duration is None and state is not None:
            duration = round((now - state.started).total_seconds(), 3)
        if fragments is None and state is not None:
            fragments = state.fragments
        values: dict[str, Any] = {"finished_at": now, "duration_seconds": duration}
        if fragments is not None:
            values["fragments"] = fragments
        return values

    def _close(self, run_id: str, values: dict[str, Any]) -> dict[str, Any]:
        with self.statements.engine.begin() as conn:
            conn.execute(
                update(t.filling_runs).where(t.filling_runs.c.run_id == run_id).values(**values)
            )
            return dict(
                conn.execute(select(t.filling_runs).where(t.filling_runs.c.run_id == run_id))
                .mappings()
                .one()
            )

    def _run_spend(self, run_id: str) -> dict[str, Any]:
        """Стоимость и токены запуска по сводке расходов шлюза; без шлюза — нули."""
        empty = {"cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0}
        if self.llm is None:
            return empty
        try:
            response = self.llm.get("spend", params={"days": 3650, "group_by": "run_id"})
        except ServiceUnavailable:
            return empty  # запись расхода не должна валить извлечение
        if response.status_code != 200:
            return empty
        rows = [r for r in response.json() if r.get("run_id") == run_id]
        return {
            "cost_usd": round(sum(r.get("cost_usd") or 0 for r in rows), 6),
            "input_tokens": int(sum(r.get("input_tokens") or 0 for r in rows)),
            "output_tokens": int(sum(r.get("output_tokens") or 0 for r in rows)),
        }

    def runs(self) -> list[dict[str, Any]]:
        with self.statements.engine.begin() as conn:
            return [dict(r) for r in conn.execute(select(t.filling_runs)).mappings()]

    def rollback(self, run_id: str) -> dict[str, int]:
        result = self.statements.rollback_run(run_id)
        with self.statements.engine.begin() as conn:
            conn.execute(
                update(t.filling_runs)
                .where(t.filling_runs.c.run_id == run_id)
                .values(status="rolled_back")
            )
        return result

    # --- схемы и данные для модели ---

    def _schema(self) -> dict[str, Any]:
        """Схема реестра — контракт проверки ответа и данные для модели (``relations``,
        ``entity_types``). Шлюзу уходит мягкая ``_gateway_schema``."""
        schema = self.registry.output_schema()
        item = schema["properties"]["statements"]["items"]["properties"]
        types = sorted(self.registry.entity_types())
        item["subject_type"] = {"enum": types}
        item["object_type"] = {"enum": types}
        item["proposed_type"] = {"type": "string"}
        schema["properties"]["entities"] = _entities_schema(types)  # необязательный массив
        return schema

    def registry_schema(self) -> dict[str, Any]:
        """Схема реестра для задания внешнего извлекателя (то же, что ``_schema``)."""
        return self._schema()

    @staticmethod
    def _gateway_schema() -> dict[str, Any]:
        """Мягкая схема для шлюза: массивы объектов с обязательными полями, без перечней и
        типов полей — одно отклонение в одном элементе не бракует весь ответ."""
        statement = (
            "subject",
            "subject_type",
            "type",
            "object",
            "object_type",
            "qualifiers",
            "paragraph",
            "quote",
            "stance",
            "attributed_to",
            "proposed_type",
        )
        return {
            "type": "object",
            "required": ["statements"],
            "properties": {
                "statements": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": list(REQUIRED),
                        "properties": {k: {} for k in statement},
                    },
                },
                "entities": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["name", "type"],
                        "properties": {
                            k: {} for k in ("name", "type", "ru", "en", "original", "dating")
                        },
                    },
                },
            },
        }

    def prompt_data(self, window: list[dict[str, Any]], schema: dict[str, Any]) -> dict[str, str]:
        """Данные шаблона ``ontology.extract`` для фрагмента — одни для шлюза и задания
        внешнего извлекателя."""
        passages = "\n\n".join(f"[{i + 1}] {p['text']}" for i, p in enumerate(window))
        langs = Counter(p["lang"] for p in window if p.get("lang")).most_common(1)
        types = schema["properties"]["statements"]["items"]["properties"]["subject_type"]["enum"]
        return {
            "passages": passages,
            "language": langs[0][0] if langs else "ru",
            "section": window[0].get("section_title") or "",
            "relations": str(schema["x-relations"]),
            "entity_types": ", ".join(types),
        }

    # --- фрагменты ---

    def fragments(
        self, paragraphs: list[dict[str, Any]], changed: set[str] | None
    ) -> list[list[dict[str, Any]]]:
        """Окна глав: абзацы подряд, пока длина меньше ``fragment_chars`` и абзацев меньше
        ``fragment_size``; следующее окно — с последнего абзаца (перекрытие), если в окне их
        больше одного. ``changed`` — только окна с добавленным или изменённым абзацем."""
        by_chapter: dict[str | None, list[dict[str, Any]]] = {}
        for p in paragraphs:
            by_chapter.setdefault(p["chapter_id"], []).append(p)
        result = []
        for chapter in by_chapter.values():
            start = 0
            while start < len(chapter):
                end, length = start, 0
                while end < len(chapter) and end - start < self.fragment_size:
                    length += len(chapter[end].get("text") or "")
                    end += 1
                    if length >= self.fragment_chars:
                        break
                window = chapter[start:end]
                if changed is None or {p["id"] for p in window} & changed:
                    result.append(window)
                if end >= len(chapter):
                    break
                start = end - 1 if len(window) > 1 else end
        return result

    def version(self, version_id: str) -> dict[str, Any]:
        """Абзацы версии — только через интерфейс библиотеки."""
        return self.library.get(f"internal/versions/{version_id}/paragraphs").json()

    def version_fragments(
        self, data: dict[str, Any], changed: set[str] | None = None
    ) -> list[list[dict[str, Any]]]:
        return self.fragments([p for p in data["paragraphs"] if p["searchable"]], changed)

    # --- извлечение через шлюз ---

    def _role(self) -> tuple[str | None, float]:
        """Модель роли извлечения и таймаут вызова: бюджет шлюза на все попытки + запас;
        шлюз не ответил — модели нет, таймаут из настройки."""
        if self.llm is None:
            return None, self.call_timeout
        try:
            response = self.llm.get(f"roles/{EXTRACT_ROLE}")
        except ServiceUnavailable:
            return None, self.call_timeout
        if response.status_code != 200:
            return None, self.call_timeout
        info = response.json()
        budget = info.get("call_budget_seconds")
        timeout = float(budget) + TIMEOUT_MARGIN if budget else self.call_timeout
        return info.get("model"), timeout

    def extract_version(
        self,
        version_id: str,
        *,
        changed: list[str] | None = None,
        limit: int | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        data = self.version(version_id)
        if not data["permissions"].get("external_processing"):
            events.emit(
                "knowledge.extraction.skipped",
                source_id=data["source_id"],
                reason="external_processing_forbidden",
            )
            return {"skipped": True}
        model, timeout = self._role()
        run_id = run_id or self.start_run(
            "extraction",
            version_id,
            extractor="gateway",
            source_id=data["source_id"],
            model=model,
        )
        self._run(run_id).model = model
        try:
            source = self.entities.source_entity(
                data["source_id"], data.get("source_title") or data["source_id"]
            )
            fragments = self.version_fragments(data, set(changed) if changed is not None else None)
            if limit is not None:
                fragments = fragments[:limit]
            schema = self._schema()
            with context.scope(run_id=run_id):
                for window in fragments:
                    self._extract_fragment(window, data, source, schema, run_id, timeout)
        except BaseException as exc:
            self.fail_run(run_id, exc)
            raise
        return self.finish_run(run_id)

    def _extract_fragment(
        self,
        window: list[dict[str, Any]],
        data: dict[str, Any],
        source: str,
        schema: dict[str, Any],
        run_id: str,
        timeout: float = EXTRACT_TIMEOUT,
    ) -> None:
        assert self.llm is not None, "извлечение через шлюз без клиента шлюза"
        try:
            response = self.llm.post(
                "structured",
                json={
                    "role": EXTRACT_ROLE,
                    "template": "ontology.extract",
                    "caller": "knowledge",
                    "operation": "extract",
                    "budget": "filling",
                    "json_schema": self._gateway_schema(),
                    "data": self.prompt_data(window, schema),
                },
                timeout=timeout,
            )
        except ServiceUnavailable as exc:
            # Сбой вызова: отбрасываем фрагмент, а не весь запуск.
            code = (
                codes.MODEL_TIMEOUT
                if exc.reason == "таймаут"
                else codes.MODEL_SCHEMA
                if exc.reason == "ответ 502"
                else codes.MODEL_UNAVAILABLE
            )
            self.drop_fragment(run_id, f"модель: {exc.reason}", code)
            return
        if response.status_code != 200:
            try:
                kind = response.json().get("kind", response.status_code)
            except ValueError:
                kind = response.status_code
            code = codes.MODEL_BUDGET if response.status_code == 429 else codes.MODEL_REFUSED
            self.drop_fragment(run_id, f"модель: {kind}", code)
            return
        self.apply_reply(window, data, source, run_id, response.json().get("value"), schema)

    # --- общий путь ответа: шлюз и внешний извлекатель ---

    def drop(self, run_id: str, reason: str, code: str) -> None:
        """Отбраковка вне элементов ответа (ответ без фрагмента и т. п.): событие и счёт."""
        self._drop(run_id, reason, code)
        self._count(run_id, dropped=1, reasons=Counter({code: 1}))

    def drop_fragment(self, run_id: str, reason: str, code: str) -> None:
        """Фрагмент без ответа модели: одна отбраковка с кодом, фрагмент обработан."""
        self._run(run_id).fragments += 1
        self.drop(run_id, reason, code)

    def apply_reply(
        self,
        window: list[dict[str, Any]],
        data: dict[str, Any],
        source: str,
        run_id: str,
        reply: Any,
        schema: dict[str, Any] | None = None,
    ) -> tuple[int, int]:
        """Ответ модели на фрагмент: каждый элемент проверяется отдельно, отказ элемента не
        отменяет остальные. Возвращает (создано, отброшено)."""
        state = self._run(run_id)
        state.fragments += 1
        dropped: Counter = Counter()

        def drop(reason: str, code: str) -> None:
            self._drop(run_id, reason, code)
            dropped[code] += 1

        created = 0
        if not isinstance(reply, dict) or not isinstance(reply.get("statements"), list):
            drop("ответ не объект с массивом statements", codes.REPLY_INVALID)
        else:
            allowed = set((schema or self._schema())["x-relations"])
            resolved: dict[str, str] = {}
            index = self.items.index(reply.get("entities"), run_id, on_drop=drop)
            for raw in reply["statements"]:
                try:
                    item = self._item(raw, window, allowed)
                    self._store(item, window, data, source, run_id, resolved, index, state.model)
                    created += 1
                except (StatementError, RegistryError, _Skip) as exc:
                    drop(str(exc), _code(exc))
            for name, entity in index.items():
                if not entity.get("dating"):
                    continue
                try:
                    self.items.date_item(
                        name, entity, resolved, window, data["source_id"], run_id, state.model
                    )
                    created += 1
                except (StatementError, RegistryError, _Skip) as exc:
                    drop(str(exc), _code(exc))
        total = sum(dropped.values())
        self._count(run_id, created=created, dropped=total, reasons=dropped)
        events.emit(
            "knowledge.extraction.fragment",
            run_id=run_id,
            paragraphs=len(window),
            created=created,
            dropped=total,
        )
        return created, total

    def _drop(self, run_id: str, reason: str, code: str | None = None) -> None:
        events.emit(
            "knowledge.extraction.dropped",
            run_id=run_id,
            reason=reason[:300],
            code=code if code in codes.CODES else codes.code_for(reason),
        )

    def _item(self, item: Any, window: list[dict[str, Any]], allowed: set[str]) -> dict[str, Any]:
        """Элемент ``statements``, приведённый и проверенный до привязки сущностей: вид полей,
        ``null`` как отсутствие, номер абзаца строкой, позиция, типы сущностей, код связи,
        абзац фрагмента и цитата. Отказ — ``Skip`` с кодом."""
        if not isinstance(item, dict):
            raise _Skip("элемент не объект", codes.SCHEMA_ITEM)
        clean = {k: v for k, v in item.items() if v is not None}
        # Пустое название — не вид поля, а отказ правил названий (``entity:empty``).
        for key in ("subject", "type", "object", "quote"):
            if not isinstance(clean.get(key), str):
                raise _Skip(f"поле {key}: нужна строка", codes.SCHEMA_ITEM)
        if not clean["type"].strip():
            raise _Skip("поле type: пустой код связи", codes.SCHEMA_ITEM)
        number = clean.get("paragraph")
        if isinstance(number, str) and number.strip().isdigit():
            number = int(number.strip())
        if isinstance(number, bool) or not isinstance(number, int):
            raise _Skip("поле paragraph: нужно целое число", codes.SCHEMA_ITEM)
        clean["paragraph"] = number
        if "qualifiers" in clean and not isinstance(clean["qualifiers"], dict):
            raise _Skip("поле qualifiers: нужен объект", codes.SCHEMA_ITEM)
        for key in ("subject_type", "object_type", "stance", "attributed_to", "proposed_type"):
            if key in clean and not isinstance(clean[key], str):
                raise _Skip(f"поле {key}: нужна строка", codes.SCHEMA_ITEM)
        if "stance" in clean and clean["stance"] not in STANCES:
            raise _Skip("позиция вне перечня", codes.STANCE_INVALID)
        known = self.registry.entity_types()
        for key in ("subject_type", "object_type"):
            if key in clean and clean[key] not in known:
                raise _Skip("entity:type", codes.ENTITY_TYPE)
        if clean["type"] not in allowed:
            try:
                self.registry.relation(clean["type"])
            except RegistryError:
                # Кода нет в реестре — предложение нового типа и общий тип «испытал влияние».
                clean.setdefault("proposed_type", clean["type"])
                clean["type"] = INFLUENCE
            else:
                raise _Skip(f"связь {clean['type']} не для извлечения", codes.RELATION_NOT_ALLOWED)
        if not 1 <= number <= len(window):
            raise _Skip("ссылка на абзац вне фрагмента", codes.PARAGRAPH_OUT_OF_WINDOW)
        paragraph = window[number - 1]
        refused = quotes.check(clean["quote"], paragraph.get("text"))
        if refused is not None:
            raise _Skip(f"цитата не найдена в абзаце {paragraph['id']}", refused)
        return clean

    def _store(
        self,
        item: dict[str, Any],
        window: list[dict[str, Any]],
        data: dict[str, Any],
        source: str,
        run_id: str,
        resolved: dict[str, str],
        index: dict[str, dict[str, Any]] | None = None,
        model: str | None = None,
    ) -> str:
        """Запись проверенного элемента (``_item``): привязка концов, тип по иерархии,
        атрибуция, утверждение с подтверждением."""
        paragraph = window[item["paragraph"] - 1]
        subject = self._resolve(item["subject"], item.get("subject_type"), resolved, index)
        obj = self._resolve(item["object"], item.get("object_type"), resolved, index)
        relation = item["type"]
        if item.get("proposed_type"):
            self.registry.propose(
                "relation", {"code": item["proposed_type"], "example": item.get("quote", "")}
            )
            relation = INFLUENCE
        relation = self._fit(relation, subject, obj)
        attributions = [Attribution("source", data["source_id"], stance="asserts")]
        if item.get("attributed_to"):
            author = self._resolve(item["attributed_to"], "person", resolved, index)
            attributions = [
                Attribution("entity", author, stance=item.get("stance", "asserts")),
                Attribution("source", data["source_id"], stance="mentions"),
            ]
        elif item.get("stance") in ("disputes", "mentions"):
            attributions = [Attribution("source", data["source_id"], stance=item["stance"])]
        return self.statements.add(
            subject,
            relation,
            obj=obj,
            qualifiers=item.get("qualifiers") or {},
            attributions=attributions,
            scope=data["scope"],
            evidence=[Evidence(paragraph["id"], item["quote"], source_id=data["source_id"])],
            provenance=Provenance(
                "extracted",
                run_id=run_id,
                model=model,
                template="ontology.extract",
                extra={"source": source},
            ),
        )

    def _fit(self, relation: str, subject: str, obj: str) -> str:
        """Если частный тип не подходит концам, берётся родительский — общий тип иерархии."""
        current: str | None = relation
        s_type = self.entities.get(subject)["type"]
        o_type = self.entities.get(obj)["type"]
        while current is not None:
            spec = self.registry.relation(current)
            if (
                not spec.get("deprecated_by")
                and self.registry.is_a(s_type, spec["subject_types"])
                and self.registry.is_a(o_type, spec["object_types"])
            ):
                return current
            current = spec.get("parent")
        raise _Skip(f"тип {relation} не подходит концам {s_type} → {o_type}", codes.TYPE_MISMATCH)

    def _resolve(
        self,
        name: str,
        type_: str | None,
        resolved: dict[str, str],
        index: dict[str, dict[str, Any]] | None = None,
    ) -> str:
        """Существующая сущность по названию; новая — если нет; неоднозначная — на проверку.
        Привязка по всем написаниям элемента ``entities`` — в ``EntityItems.resolve``."""
        return self.items.resolve(name, type_, (index or {}).get(name), resolved)

    def handle_published(self, payload: dict[str, Any]) -> None:
        """По событию публикации: извлечение только из добавленных и изменённых абзацев."""
        if not payload.get("external_processing", True):
            events.emit(
                "knowledge.extraction.skipped",
                source_id=payload["source_id"],
                reason="external_processing_forbidden",
            )
            return
        changed = list(payload.get("added", [])) + list(payload.get("changed", []))
        first = payload.get("previous_version_id") is None
        self.extract_version(payload["version_id"], changed=None if first else changed)

    def estimate(self, version_id: str, sample_fragments: int = 2) -> dict[str, Any]:
        """Проба на нескольких фрагментах: стоимость пробы и оценка полного прохода."""
        total = len(self.version_fragments(self.version(version_id)))
        run = self.extract_version(version_id, limit=sample_fragments)
        sample_cost = float(run.get("cost_usd") or 0.0)
        per_fragment = sample_cost / max(1, min(sample_fragments, total))
        return {
            "run_id": run.get("run_id"),
            "sample_cost_usd": sample_cost,
            "fragments": total,
            "estimate_usd": round(per_fragment * total, 6),
        }

    # --- ядро вручную ---

    def propose_core(self, topic: str) -> list[dict[str, Any]]:
        types = sorted(self.registry.entity_types())
        response = self.llm.post(
            "structured",
            json={
                "role": "main",
                "template": "ontology.core_draft",
                "caller": "knowledge",
                "operation": "core_draft",
                "budget": "filling",
                "data": {"topic": topic, "entity_types": ", ".join(types)},
                "json_schema": {
                    "type": "object",
                    "required": ["items"],
                    "properties": {
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": ["name", "type"],
                                "properties": {
                                    "name": {"type": "string"},
                                    "type": {"enum": types},
                                    "note": {"type": "string"},
                                },
                            },
                        }
                    },
                },
            },
        )
        response.raise_for_status()
        return response.json()["value"]["items"]

    def accept_core(self, items: list[dict[str, Any]], actor: str) -> list[str]:
        """Принятое из черновика создаётся как ручное, с отметкой, что был черновик модели."""
        return self.accept_core_report(items, actor)["created"]

    def accept_core_report(self, items: list[dict[str, Any]], actor: str) -> dict[str, Any]:
        """То же, с отказами: элемент с названием, не прошедшим проверку, не создаётся и
        возвращается в ``rejected`` с причиной; остальные создаются."""
        created: list[str] = []
        rejected: list[dict[str, str]] = []
        for item in items:
            try:
                entity = self.entities.create(item["type"], [("ru", item["name"], "primary")])
            except InvalidName as exc:
                rejected.append({"name": item["name"], "type": item["type"], "reason": exc.reason})
                continue
            if item.get("note"):
                self.statements.add(
                    entity,
                    "description",
                    value=item["note"],
                    attributions=[Attribution("common")],
                    provenance=Provenance("manual", actor=actor, extra={"draft": "model"}),
                )
            created.append(entity)
        return {"created": created, "rejected": rejected}

    # --- Wikidata ---

    def import_wikidata(self, qid: str, fetch: Callable[[str], dict[str, Any]]) -> list[str]:
        """Простые факты: даты, места, авторство, учителя — со ссылкой на запись."""
        record = fetch(qid)
        label = record["labels"].get("ru") or record["labels"].get("en") or qid
        kind = "work" if "P50" in record["claims"] else "person"
        try:
            entity = self.entities.by_external("wikidata", qid) or self.entities.create(
                kind, [("ru", label, "primary")], external={"wikidata": qid}
            )
        except InvalidName:
            return []  # мусорная подпись записи: событие отказа уже в журнале
        url = f"https://www.wikidata.org/wiki/{qid}"
        attribution = [Attribution("source", f"wikidata:{qid}", place=url)]
        imported = Provenance("imported", extra={"wikidata": qid})
        created = []
        for prop in record["claims"]:
            if prop in WIKIDATA_SKIPPED:
                events.emit(
                    "knowledge.import.skipped", property=prop, reason=WIKIDATA_SKIPPED[prop]
                )
        claims = record["claims"]
        # Время — общим правилом ``wikidata.simple_time`` (знак — эра), годы жизни — только
        # при обеих датах; одна — событие ``partial``.
        born, died = (simple_time((claims.get(p) or [None])[0]) for p in ("P569", "P570"))
        if (born is None) != (died is None):
            events.emit(
                "knowledge.import.skipped",
                property="P570" if died is None else "P569",
                reason="partial",
            )
        if born is not None and died is not None:
            span = interval(born, died, format_original(born, died))
            created.append(
                self.statements.add(
                    entity,
                    "lifespan",
                    value=span.to_json(),
                    attributions=attribution,
                    provenance=imported,
                    status="sourced",
                )
            )
        dating = simple_time((claims.get("P577") or [None])[0])
        if dating is not None:
            created.append(
                self.statements.add(
                    entity,
                    "dating",
                    value=dating.to_json(),
                    attributions=attribution,
                    provenance=imported,
                    status="sourced",
                )
            )
        roles = {WIKIDATA_ROLES[q] for q in claims.get("P106", []) if q in WIKIDATA_ROLES}
        for role in sorted(roles):
            created.append(
                self.statements.add(
                    entity,
                    "person_role",
                    value=role,
                    attributions=attribution,
                    provenance=imported,
                    status="sourced",
                )
            )
        for prop, relation, target_type in (
            ("P19", "lived_in", "place"),
            ("P1066", "studied_with", "person"),
            ("P50", "author", "person"),
        ):
            for target in claims.get(prop, []):
                target_label = fetch(target)["labels"].get("ru") or target
                try:
                    other = self.entities.by_external("wikidata", target) or self.entities.create(
                        target_type,
                        [("ru", target_label, "primary")],
                        external={"wikidata": target},
                    )
                except InvalidName:
                    continue  # место или учитель с мусорной подписью не создаётся
                created.append(
                    self.statements.add(
                        entity,
                        relation,
                        obj=other,
                        attributions=attribution,
                        provenance=imported,
                        status="sourced",
                    )
                )
        return created


def _entities_schema(types: list[str]) -> dict[str, Any]:
    """Необязательный массив ``entities``: написания и датировка упомянутых сущностей."""
    text = {"type": "string"}
    return {
        "type": "array",
        "items": {
            "type": "object",
            "required": ["name", "type"],
            "properties": {
                "name": text,
                "type": {"enum": types},
                "ru": text,
                "en": text,
                "original": {"type": "object", "properties": {"lang": text, "text": text}},
                "dating": {
                    "type": "object",
                    "required": ["text", "paragraph", "quote"],
                    "properties": {"text": text, "paragraph": {"type": "integer"}, "quote": text},
                },
            },
        },
    }


def _code(exc: Exception) -> str:
    """Код отказа элемента: у Skip — свой; уточнитель вне реестра (RegistryError в
    проверке записи) — qualifier_invalid; иной отказ записи — statement_refused."""
    if isinstance(exc, _Skip):
        return exc.code
    if isinstance(exc, RegistryError) or isinstance(exc.__cause__, RegistryError):
        return codes.QUALIFIER_INVALID
    return codes.STATEMENT_REFUSED
