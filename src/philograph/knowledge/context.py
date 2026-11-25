"""Исторический контекст эпохи или окна времени (``GET /v1/context``), без модели.

Правила — возможность ``epoch-context`` (требования «Контекст эпохи», «Проверка параметров
контекста», «Пометка непроверенного контекста», «Механизм влияния», «Контекст и закрытые
источники»):

- режим ровно один: эпоха (``epoch``) — события, явления и идейные события эпохи по правилу
  принадлежности (``knowledge/epochs.py``); окно (``from``, ``to``) — те же типы, у которых
  середина датировки (``dates.middle``) внутри ``[from, to)``;
- у события — вид (``event_kind``, основное значение — как на карте), датировка, места
  («произошло в») и исходящие действующие связи «стимулировало» (отклонённых в снимке нет);
- связи — проверенные, затем по источникам, затем сгенерированные, внутри — по названию
  объекта; ``verified`` убирает сгенерированные, событие без связей остаётся;
- подтверждения — только id абзаца и ссылка (цитат нет никогда); подтверждения и атрибуции
  закрытых для региона источников снимаются;
- ``counts`` — по событиям режима до фильтра видов и до усечения;
- пределы: 200 самых значимых событий (число действующих утверждений, затем начало
  датировки), у каждого — первые 30 связей; ``truncated``, если отброшено хоть что-то.

Данные — из общего снимка без окна устарелости (как карта): после достройки страница
перезапрашивает контекст и видит сохранённое. Индекс событий строится один раз на снимок
(``Snapshot.derived``). В журнал — только коды и числа.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from philograph.knowledge.catalog import Catalog
from philograph.knowledge.dates import middle, span
from philograph.knowledge.epochs import membership
from philograph.knowledge.graph import hidden_by_region, who_label
from philograph.knowledge.map import best_of
from philograph.knowledge.registry import RegistryError
from philograph.knowledge.snapshot import Snapshot
from philograph.knowledge.statements import attributed_sources
from philograph.knowledge.wikidata import QID
from philograph.platform import events

events.define(
    "knowledge.context.served",
    "info",
    "Отдан исторический контекст эпохи или окна времени",
    required=("mode", "events", "links", "generated_links", "truncated", "snapshot"),
)
events.define(
    "knowledge.context.rejected",
    "info",
    "Запрос контекста отклонён",
    required=("reason",),
)

Mode = Literal["epoch", "window"]
EVENT_TYPES = ["event", "phenomenon"]  # с подтипами реестра: идейное событие — подтип события
STIMULATED = "stimulated"
HAPPENED_IN = "happened_in"
EVENT_KIND = "event_kind"
MECHANISM = "mechanism"
NO_KIND = "none"
MAX_EVENTS = 200
MAX_LINKS = 30
# Порядок связей по статусу: проверенные, по источникам, сгенерированные.
STATUS_ORDER = {"verified": 0, "sourced": 1, "generated": 2}

MESSAGES = {  # текст ответа 400 по ``kind``
    "bad_query": "Недопустимые параметры контекста",
    "unknown_epoch": "Неизвестная эпоха",
    "unknown_kind": "Неизвестный вид события",
}


class ContextRejected(Exception):
    """Недопустимый запрос: ``kind`` — для ответа, ``reason`` — для журнала."""

    def __init__(self, kind: str, reason: str) -> None:
        super().__init__(MESSAGES[kind])
        self.kind = kind
        self.reason = reason


@dataclass(frozen=True)
class ContextQuery:
    mode: Mode
    epoch: str | None
    window: tuple[int, int] | None
    kinds: frozenset[str] | None  # None — без фильтра
    verified: bool
    textbook: str | None
    lang: str


@dataclass(frozen=True)
class EventRecord:
    id: str
    type: str
    dates: dict[str, Any] | None
    start: int | None
    middle: float | None
    kind: str | None
    places: tuple[str, ...]
    links: tuple[dict[str, Any], ...]  # утверждения «стимулировало», без порядка
    weight: int  # число действующих утверждений сущности


class ContextIndex:
    """События снимка с видом, местами и связями «стимулировало» — один раз на снимок."""

    def __init__(self, snapshot: Snapshot, catalog: Catalog) -> None:
        registry = catalog.registry
        self.snapshot = snapshot
        entities = snapshot.entities
        is_event: dict[str, bool] = {}

        def event_type(type_: str) -> bool:
            if type_ not in is_event:
                is_event[type_] = registry.is_a(type_, EVENT_TYPES)
            return is_event[type_]

        ids = [e for e, row in entities.items() if event_type(row["type"])]
        event_set = set(ids)
        stimulated = registry.relation_subtypes(STIMULATED)
        happened = registry.relation_subtypes(HAPPENED_IN)
        weight: dict[str, int] = defaultdict(int)
        kinds: dict[str, list[dict[str, Any]]] = defaultdict(list)
        places: dict[str, list[dict[str, Any]]] = defaultdict(list)
        links: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for s in snapshot.statements:
            weight[s["subject"]] += 1
            if s["object"]:
                weight[s["object"]] += 1
            if s["subject"] not in event_set:
                continue
            if s["type"] == EVENT_KIND:
                kinds[s["subject"]].append(s)
            elif s["type"] in happened and s["object"]:
                places[s["subject"]].append(s)
            elif s["type"] in stimulated and s["object"]:
                links[s["subject"]].append(s)
        records = {}
        for entity_id in ids:
            dates = entities[entity_id]["primary"].get("dates")
            kind = best_of(kinds.get(entity_id, []))
            ordered_places = sorted(
                places.get(entity_id, []), key=lambda s: STATUS_ORDER.get(s["status"], 3)
            )
            records[entity_id] = EventRecord(
                id=entity_id,
                type=entities[entity_id]["type"],
                dates=dates,
                start=span(dates)[0] if dates else None,
                middle=middle(dates) if dates else None,
                kind=kind["value"] if kind else None,
                places=tuple(dict.fromkeys(s["object"] for s in ordered_places)),
                links=tuple(links.get(entity_id, [])),
                weight=weight[entity_id],
            )
        self.records = records
        self.membership = membership(snapshot, registry)


class Context:
    """Контекст эпохи сервиса знаний: проверка параметров, снимок, индекс и журнал."""

    def __init__(
        self, catalog: Catalog, max_events: int = MAX_EVENTS, max_links: int = MAX_LINKS
    ) -> None:
        self.catalog = catalog
        self.registry = catalog.registry
        self.max_events = max_events
        self.max_links = max_links

    def index(self, snapshot: Snapshot) -> ContextIndex:
        return snapshot.derived("context", lambda s: ContextIndex(s, self.catalog))

    # --- параметры ---

    def _parse(
        self,
        snapshot: Snapshot,
        *,
        epoch: str | None,
        from_: str | None,
        to: str | None,
        kinds: str | None,
        verified: str | bool | None,
        textbook: str | None,
        lang: str | None,
    ) -> ContextQuery:
        has_epoch = bool(epoch)
        has_window = from_ not in (None, "") or to not in (None, "")
        if has_epoch == has_window:
            raise ContextRejected("bad_query", "mode")
        window = None
        epoch_id = None
        if has_window:
            window = (_year(from_), _year(to))
            if window[0] >= window[1]:
                raise ContextRejected("bad_query", "window")
        else:
            epoch_id = self.catalog.entities.resolve(epoch)
            row = snapshot.entities.get(epoch_id)
            if row is None or not self.registry.is_a(row["type"], ["epoch"]):
                raise ContextRejected("unknown_epoch", "unknown_epoch")
        return ContextQuery(
            mode="window" if window else "epoch",
            epoch=epoch_id,
            window=window,
            kinds=self._kinds(kinds),
            verified=verified is True or str(verified).lower() in ("true", "1"),
            textbook=textbook or None,
            lang=lang if lang in ("ru", "en") else "ru",
        )

    def _kinds(self, raw: str | None) -> frozenset[str] | None:
        codes = [c.strip() for c in (raw or "").split(",") if c.strip()]
        if not codes:
            return None
        allowed = set(self.registry.relation(EVENT_KIND).get("values") or []) | {NO_KIND}
        if any(c not in allowed for c in codes):
            raise ContextRejected("unknown_kind", "unknown_kind")
        return frozenset(codes)

    # --- ответ ---

    def get(
        self,
        *,
        epoch: str | None = None,
        from_: str | None = None,
        to: str | None = None,
        kinds: str | None = None,
        verified: str | bool | None = None,
        textbook: str | None = None,
        lang: str | None = None,
        closed: Callable[[], frozenset[str]] = frozenset,
    ) -> dict[str, Any]:
        """Контекст по запросу; недопустимый запрос — ``ContextRejected`` (и событие).
        ``closed`` — закрытые для читателя источники; спрашивается после проверки параметров."""
        snapshot, status = self.catalog.snapshots.get(max_stale=0)
        try:
            query = self._parse(
                snapshot,
                epoch=epoch,
                from_=from_,
                to=to,
                kinds=kinds,
                verified=verified,
                textbook=textbook,
                lang=lang,
            )
        except ContextRejected as exc:
            events.emit("knowledge.context.rejected", reason=exc.reason)
            raise
        result = self._answer(snapshot, query, closed())
        links = [link for e in result["events"] for link in e["stimulated"]]
        events.emit(
            "knowledge.context.served",
            mode=query.mode,
            events=len(result["events"]),
            links=len(links),
            generated_links=sum(1 for link in links if link["generated"]),
            truncated=result["truncated"],
            snapshot=status,
        )
        return result

    def _selected(self, index: ContextIndex, query: ContextQuery) -> list[tuple[str, str | None]]:
        """События режима с основанием принадлежности (в режиме окна — ``None``)."""
        if query.mode == "epoch":
            return [
                (entity_id, basis)
                for entity_id, basis in index.membership.members(query.epoch)
                if entity_id in index.records
            ]
        start, end = query.window
        return [
            (r.id, None)
            for r in index.records.values()
            if r.middle is not None and start <= r.middle < end
        ]

    def _answer(
        self, snapshot: Snapshot, query: ContextQuery, closed: frozenset[str]
    ) -> dict[str, Any]:
        index = self.index(snapshot)
        labels, _ = self.catalog.index(snapshot).labels(query.lang)
        label = lambda entity_id: labels.get(entity_id, entity_id)  # noqa: E731
        selected = self._selected(index, query)
        records = [(index.records[e], basis) for e, basis in selected]

        counts: dict[str, int] = defaultdict(int)
        for record, _ in records:
            counts[record.kind or NO_KIND] += 1
        if query.kinds is not None:
            records = [(r, b) for r, b in records if (r.kind or NO_KIND) in query.kinds]

        truncated = len(records) > self.max_events
        if truncated:
            records = sorted(records, key=lambda rb: (-rb[0].weight, _start_key(rb[0])))
            records = records[: self.max_events]
        records.sort(key=lambda rb: (*_start_key(rb[0]), label(rb[0].id), rb[0].id))

        out = []
        for record, basis in records:
            links = [s for s in record.links if not (query.verified and s["status"] == "generated")]
            links.sort(
                key=lambda s: (STATUS_ORDER.get(s["status"], 3), label(s["object"]), s["id"])
            )
            if len(links) > self.max_links:
                truncated = True
                links = links[: self.max_links]
            out.append(
                {
                    "id": record.id,
                    "label": label(record.id),
                    "type": record.type,
                    "kind": record.kind,
                    # Внешний идентификатор события (ссылка «Wikidata ↗»), только по шаблону.
                    "wikidata": _qid(snapshot.wikidata.get(record.id)),
                    "dates": _dates(record.dates),
                    "places": [
                        {"id": p, "label": label(p), "wikidata": _qid(snapshot.wikidata.get(p))}
                        for p in record.places
                    ],
                    "basis": basis,
                    "stimulated": [
                        self._link(snapshot, s, label, query.textbook, closed) for s in links
                    ],
                }
            )
        epoch = None
        if query.mode == "epoch":
            epoch_span = index.membership.span(query.epoch)
            epoch = {
                "id": query.epoch,
                "label": label(query.epoch),
                "from": epoch_span[0] if epoch_span else None,
                "to": epoch_span[1] if epoch_span else None,
            }
        return {
            "mode": query.mode,
            "epoch": epoch,
            "window": {"from": query.window[0], "to": query.window[1]} if query.window else None,
            "events": out,
            "counts": dict(counts),
            "truncated": truncated,
        }

    def _mechanism(self, s: dict[str, Any]) -> str | None:
        """Механизм — только допустимый реестром (проверен при записи; здесь — повторно,
        чтобы значение вне списка не попало в ответ ни при каком пути записи)."""
        value = (s.get("qualifiers") or {}).get(MECHANISM)
        if value is None:
            return None
        try:
            self.registry.check_qualifiers(s["type"], {MECHANISM: value})
        except RegistryError:
            return None
        return value

    def _link(
        self,
        snapshot: Snapshot,
        s: dict[str, Any],
        label: Callable[[str], str],
        textbook: str | None,
        closed: frozenset[str],
    ) -> dict[str, Any]:
        visible = [
            a for a in s["attributions"] if not a["hidden"] and not hidden_by_region(a, closed)
        ]
        evidence = []
        seen: set[str] = set()
        for e in s["evidence"]:
            if e["lost"] or e["source_id"] in closed or e["paragraph_id"] in seen:
                continue
            seen.add(e["paragraph_id"])
            # Цитаты нет никогда: её показывает карточка с учётом региона.
            evidence.append({"paragraph_id": e["paragraph_id"], "link": f"/p/{e['paragraph_id']}"})
        target = s["object"]
        return {
            "statement_id": s["id"],
            "target": {
                "id": target,
                "label": label(target),
                "type": snapshot.entities[target]["type"],
            },
            "mechanism": self._mechanism(s),
            "status": s["status"],
            "generated": s["status"] == "generated",
            "in_textbook": textbook in attributed_sources(s) if textbook else None,
            "attributed_to": list(
                dict.fromkeys(who_label(a, label, snapshot.library.get) for a in visible)
            ),
            "evidence": evidence,
        }


def _year(value: str | None) -> int:
    if value is None or value == "":
        raise ContextRejected("bad_query", "window")
    try:
        return int(value)
    except ValueError:
        raise ContextRejected("bad_query", "window") from None


def _start_key(record: EventRecord) -> tuple[bool, int]:
    """Начало датировки; без датировки — в конце."""
    return (record.start is None, record.start or 0)


def _dates(dates: dict[str, Any] | None) -> dict[str, Any] | None:
    if not dates:
        return None
    start, end = span(dates)
    return {
        "from": start,
        "to": end,
        "precision": dates.get("precision"),
        "original": dates.get("original"),
    }


def _qid(value: str | None) -> str | None:
    """Идентификатор Wikidata — только по шаблону ``^Q\\d+$``."""
    return value if value and QID.fullmatch(value) else None
