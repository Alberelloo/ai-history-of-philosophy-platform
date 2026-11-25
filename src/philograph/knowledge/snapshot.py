"""Снимок действующих данных онтологии в памяти процесса: общий для карты и справочника.

Снимок читает базу одним проходом: сущности без перенаправления, их названия и подписи,
действующие утверждения (не отклонённые, не отвергнутые рангом «устаревшее», не основанные
только на снятом источнике) с атрибуциями и подтверждениями, упоминания по источникам.
Отпечаток базы — счётчики и последние записи таблиц, влияющих на эти данные: пока он не
изменился, снимок переиспользуется.

``Snapshots.get(max_stale)`` отдаёт снимок и его статус: ``cached`` — отпечаток совпал;
``stale`` — отпечаток изменился, но снимку меньше ``max_stale`` секунд (по внедряемым часам),
отдан прежний; ``fresh`` — снимок собран этим вызовом. Пересборка идёт под блокировкой:
параллельный вызов ждёт её и не строит второй снимок. Карта берёт снимок с ``max_stale=0``
(изменения видны сразу), справочник — с окном устарелости.

Снимок не изменяют: потребители строят из него свои производные (индекс справочника,
принадлежность к эпохам) через ``Snapshot.derived`` — один раз на снимок.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, TypeVar

from sqlalchemy import Engine, and_, func, select

from philograph.knowledge import schema as t
from philograph.platform import events
from philograph.platform.clock import Clock, SystemClock

events.define(
    "knowledge.snapshot.built",
    "info",
    "Собран снимок данных онтологии",
    required=("entities", "statements", "took_ms", "reason"),
)

Status = Literal["fresh", "cached", "stale"]
T = TypeVar("T")


@dataclass(frozen=True, eq=False)
class Snapshot:
    """Действующие данные онтологии на момент ``built_at``.

    ``entities`` — id → ``{"type", "primary"}``; ``names`` — id → названия (строки таблицы
    ``names`` по порядку записи); ``labels`` — id → основное русское название (иначе первое
    основное, иначе первое любое, иначе сам id); ``statements`` — действующие утверждения
    с ``attributions`` и ``evidence``; ``mentions`` — источник → сущности, упомянутые в нём;
    ``library`` — источник библиотеки → его сущность типа ``source``; ``wikidata`` —
    сущность → её внешний идентификатор Wikidata (как записан, без проверки шаблона)."""

    entities: Mapping[str, dict[str, Any]]
    names: Mapping[str, list[dict[str, Any]]]
    labels: Mapping[str, str]
    statements: tuple[dict[str, Any], ...]
    mentions: Mapping[str, frozenset[str]]
    library: Mapping[str, str]
    fingerprint: tuple
    built_at: datetime
    wikidata: Mapping[str, str] = field(default_factory=dict)
    _derived: dict[str, Any] = field(default_factory=dict, repr=False)
    # Повторно входимая: производное может опираться на другое (справочник — на эпохи).
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def derived(self, key: str, build: Callable[[Snapshot], T]) -> T:
        """Производное снимка (индекс, принадлежность): строится один раз на снимок."""
        with self._lock:
            if key not in self._derived:
                self._derived[key] = build(self)
            return self._derived[key]


def fingerprint(engine: Engine) -> tuple:
    """Меняется при любой записи, влияющей на снимок: новые и изменённые утверждения
    (журнал), атрибуции и подтверждения, события библиотеки (снятие источника), сущности,
    имена, слияния, упоминания, внешние идентификаторы и версия реестра."""
    count = func.count
    with engine.begin() as conn:
        return tuple(
            conn.execute(
                select(
                    select(count()).select_from(t.statements).scalar_subquery(),
                    select(func.max(t.journal.c.id)).scalar_subquery(),
                    select(count()).select_from(t.attributions).scalar_subquery(),
                    select(count()).select_from(t.evidence).scalar_subquery(),
                    select(count()).select_from(t.processed).scalar_subquery(),
                    select(count()).select_from(t.entities).scalar_subquery(),
                    select(count()).select_from(t.names).scalar_subquery(),
                    select(count()).select_from(t.merges).scalar_subquery(),
                    select(func.max(t.merges.c.id)).scalar_subquery(),
                    select(count()).select_from(t.mentions).scalar_subquery(),
                    select(func.max(t.mentions.c.id)).scalar_subquery(),
                    select(func.max(t.registry_versions.c.version)).scalar_subquery(),
                    select(count()).select_from(t.external_ids).scalar_subquery(),
                )
            ).one()
        )


def load(engine: Engine, stamp: tuple, built_at: datetime) -> Snapshot:
    """Сущности, подписи и действующие утверждения: не отклонённые, не отвергнутые
    (ранг «устаревшее»), не основанные только на снятом источнике — как в ``about``."""
    with engine.begin() as conn:
        entities = {
            r["id"]: {"type": r["type"], "primary": r["primary"] or {}}
            for r in conn.execute(
                select(t.entities.c.id, t.entities.c.type, t.entities.c.primary).where(
                    t.entities.c.redirect_to.is_(None)
                )
            ).mappings()
        }
        names: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in conn.execute(select(t.names).order_by(t.names.c.id)).mappings():
            names[r["entity_id"]].append(dict(r))
        rows = (
            conn.execute(
                select(t.statements).where(
                    and_(
                        t.statements.c.scope == "public",
                        t.statements.c.status != "rejected",
                        t.statements.c.rank != "deprecated",
                    )
                )
            )
            .mappings()
            .all()
        )
        attrs: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in conn.execute(select(t.attributions)).mappings():
            attrs[r["statement_id"]].append(dict(r))
        evs: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in conn.execute(select(t.evidence)).mappings():
            evs[r["statement_id"]].append(dict(r))
        mentioned: dict[str, set[str]] = defaultdict(set)
        for source_id, entity_id in conn.execute(
            select(t.mentions.c.source_id, t.mentions.c.entity_id)
        ):
            mentioned[source_id].add(entity_id)
        library: dict[str, str] = {}
        wikidata: dict[str, str] = {}
        for entity_id, system, value in conn.execute(
            select(t.external_ids.c.entity_id, t.external_ids.c.system, t.external_ids.c.value)
            .where(t.external_ids.c.system.in_(("library", "wikidata")))
            .order_by(t.external_ids.c.entity_id, t.external_ids.c.value)
        ):
            if system == "library":
                library[value] = entity_id
            else:
                wikidata.setdefault(entity_id, value)
    labels = {}
    for entity_id in entities:
        own = names.get(entity_id, [])
        primary = [n for n in own if n["kind"] == "primary"]
        ru = [n for n in primary if n["lang"] == "ru"]
        pick = (ru or primary or own or [{"text": entity_id}])[0]
        labels[entity_id] = pick["text"]
    statements = []
    for r in rows:
        s = {
            **dict(r),
            "attributions": attrs.get(r["id"], []),
            "evidence": evs.get(r["id"], []),
        }
        if s["attributions"] and all(a["hidden"] for a in s["attributions"]):
            continue  # основано только на снятом источнике
        if s["subject"] not in entities or (s["object"] and s["object"] not in entities):
            continue
        if s["object"] is not None and s["object"] == s["subject"]:
            continue  # петля после слияния двух концов: хранится, но не показывается
        statements.append(s)
    return Snapshot(
        entities=entities,
        names=dict(names),
        labels=labels,
        statements=tuple(statements),
        mentions={k: frozenset(v) for k, v in mentioned.items()},
        library=library,
        fingerprint=stamp,
        built_at=built_at,
        wikidata=wikidata,
    )


class Snapshots:
    """Текущий снимок процесса и правило его пересборки (см. модуль)."""

    def __init__(self, engine: Engine, clock: Clock | None = None) -> None:
        self.engine = engine
        self.clock = clock or SystemClock()
        self._current: Snapshot | None = None
        self._lock = threading.Lock()

    def _fits(self, snapshot: Snapshot | None, stamp: tuple, max_stale: float) -> Status | None:
        if snapshot is None:
            return None
        if snapshot.fingerprint == stamp:
            return "cached"
        if (self.clock.now() - snapshot.built_at).total_seconds() < max_stale:
            return "stale"
        return None

    def get(self, max_stale: float = 0.0) -> tuple[Snapshot, Status]:
        current = self._current
        status = self._fits(current, fingerprint(self.engine), max_stale)
        if status is not None:
            return current, status  # type: ignore[return-value]
        with self._lock:
            # Пока ждали блокировку, снимок мог пересобрать другой запрос.
            current = self._current
            stamp = fingerprint(self.engine)
            status = self._fits(current, stamp, max_stale)
            if status is not None:
                return current, status  # type: ignore[return-value]
            started = time.perf_counter()
            snapshot = load(self.engine, stamp, self.clock.now())
            self._current = snapshot
        events.emit(
            "knowledge.snapshot.built",
            entities=len(snapshot.entities),
            statements=len(snapshot.statements),
            took_ms=round((time.perf_counter() - started) * 1000, 1),
            reason="first" if current is None else "changed",
        )
        return snapshot, "fresh"
