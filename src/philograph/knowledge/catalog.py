"""Справочник: постраничный список сущностей онтологии с поиском, фильтрами и счётчиками.

Данные — из общего снимка онтологии (``knowledge/snapshot.py``) с окном устарелости;
индекс справочника (``CatalogIndex``) строится один раз на снимок. Модель не вызывается.

Правила (возможность ``entity-catalog``):

- в списке — действующие сущности снимка, кроме источников библиотеки (тип ``source``);
- поиск — по части любого названия после ``entities.normalize``; ранг: 0 — точное
  совпадение, 1 — начало слова, 2 — внутри слова;
- фильтры: тип (повтором параметра, с подтипами реестра), эпоха (``knowledge/epochs.py``),
  раздел — упоминания в учебнике и концы утверждений, атрибутированных учебнику или
  подтверждённых его абзацами; фильтры сочетаются через «и»;
- счётчики: ``types`` — по точному коду без фильтра типа, ``epochs`` — без фильтра эпохи;
- порядок устойчив: при равных ключах — по идентификатору;
- по учебнику, закрытому для региона, ответ пуст (``textbook_closed``).

В журнал пишутся только коды и числа: текста поиска, названий и региона в событиях нет.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from philograph.knowledge.dates import span
from philograph.knowledge.entities import Entities, normalize
from philograph.knowledge.epochs import EpochMembership, membership
from philograph.knowledge.registry import OntologyRegistry, RegistryError
from philograph.knowledge.snapshot import Snapshot, Snapshots, Status
from philograph.knowledge.statements import STRENGTH
from philograph.platform import events

events.define(
    "knowledge.catalog.listed",
    "info",
    "Отдана страница справочника",
    required=(
        "total",
        "returned",
        "page",
        "filters",
        "q_len",
        "sort",
        "snapshot",
        "textbook_closed",
    ),
)
events.define(
    "knowledge.catalog.rejected",
    "info",
    "Запрос справочника отклонён",
    required=("reason",),
)

SORTS = ("label", "date", "weight", "relevance")
MAX_QUERY = 200
MAX_LIMIT = 60
DEFAULT_LIMIT = 24
SUMMARY_CHARS = 200
SOURCE = "source"  # источники библиотеки в справочник не попадают


@dataclass(frozen=True)
class CatalogSettings:
    max_stale_seconds: float = 15.0


MESSAGES = {  # текст ответа 400 по ``kind``
    "bad_query": "Недопустимые параметры справочника",
    "unknown_type": "Неизвестный тип сущности",
    "unknown_epoch": "Неизвестная эпоха",
    "unknown_textbook": "Неизвестный учебник",
}


class CatalogRejected(Exception):
    """Недопустимый параметр: ``kind`` — для ответа, ``reason`` — для журнала."""

    def __init__(self, kind: str, reason: str) -> None:
        super().__init__(MESSAGES[kind])
        self.kind = kind
        self.reason = reason


@dataclass(frozen=True)
class Query:
    q: str  # нормализованная строка поиска; пусто — без поиска
    q_len: int
    types: frozenset[str] | None  # коды с подтипами; None — без фильтра
    epoch: str | None
    textbook: str | None
    sort: str
    page: int
    limit: int
    lang: str

    @property
    def filters(self) -> list[str]:
        names = []
        if self.q:
            names.append("q")
        if self.types is not None:
            names.append("type")
        if self.epoch is not None:
            names.append("epoch")
        if self.textbook is not None:
            names.append("textbook")
        return sorted(names)


@dataclass(frozen=True)
class Record:
    id: str
    type: str
    names: tuple[tuple[str, str], ...]  # (нормализованное, текст), по порядку записи
    dates: dict[str, Any] | None
    start: int | None
    weight: int
    summary: dict[str, Any] | None
    epochs: tuple[tuple[str, str], ...]  # (id эпохи, основание)
    sources: frozenset[str]


def _summary(text: str) -> str:
    """Первые ``SUMMARY_CHARS`` знаков по границе слова, с «…», если обрезано."""
    text = " ".join(text.split())
    if len(text) <= SUMMARY_CHARS:
        return text
    cut = text[:SUMMARY_CHARS]
    if " " in cut:
        cut = cut[: cut.rindex(" ")]
    return cut.rstrip(" ,.;:—–-") + "…"


def _rank(normalized: str, q: str) -> int | None:
    if normalized == q:
        return 0
    if normalized.startswith(q) or f" {q}" in normalized:
        return 1
    if q in normalized:
        return 2
    return None


class CatalogIndex:
    """Записи справочника одного снимка и запрос по ним."""

    def __init__(
        self, snapshot: Snapshot, registry: OntologyRegistry, epochs: EpochMembership
    ) -> None:
        self.snapshot = snapshot
        self.registry = registry
        self.epochs = epochs
        excluded = registry.entity_subtypes(SOURCE)
        weight: Counter[str] = Counter()
        sources: dict[str, set[str]] = defaultdict(set)
        descriptions: dict[str, list[dict[str, Any]]] = defaultdict(list)
        known_sources: set[str] = set(snapshot.mentions) | set(snapshot.library)
        for source_id, mentioned in snapshot.mentions.items():
            for entity_id in mentioned:
                sources[entity_id].add(source_id)
        for s in snapshot.statements:
            ends = [s["subject"]] + ([s["object"]] if s["object"] else [])
            for end in ends:
                weight[end] += 1
            # Как ``Statements._attributed``: атрибуция учебнику или его подтверждающий абзац.
            cited = {
                a["who"]
                for a in s["attributions"]
                if a["who_kind"] == "source" and a["who"] and not a["hidden"]
            } | {e["source_id"] for e in s["evidence"] if e["source_id"] and not e["lost"]}
            known_sources |= cited
            for end in ends:
                sources[end] |= cited
            if s["type"] == "description" and isinstance(s["value"], str):
                descriptions[s["subject"]].append(s)
        self.known_sources = frozenset(known_sources)

        records = []
        for entity_id, row in snapshot.entities.items():
            if row["type"] in excluded:
                continue
            dates = row["primary"].get("dates")
            start = end = None
            if dates:
                start, end = span(dates)
            summary = None
            if descriptions.get(entity_id):
                best = sorted(
                    descriptions[entity_id],
                    key=lambda s: (s["rank"] != "preferred", -STRENGTH[s["status"]], s["id"]),
                )[0]
                summary = {
                    "text": _summary(best["value"]),
                    "generated": best["status"] == "generated",
                }
            records.append(
                Record(
                    id=entity_id,
                    type=row["type"],
                    names=tuple(
                        (n["normalized"], n["text"]) for n in snapshot.names.get(entity_id, [])
                    ),
                    dates=(
                        {
                            "from": start,
                            "to": end,
                            "precision": dates.get("precision"),
                            "original": dates.get("original"),
                        }
                        if dates
                        else None
                    ),
                    start=start,
                    weight=weight[entity_id],
                    summary=summary,
                    epochs=tuple(epochs.of(entity_id)),
                    sources=frozenset(sources.get(entity_id, ())),
                )
            )
        self.records = records
        self._labels: dict[str, tuple[dict[str, str], dict[str, str]]] = {}

    # --- подписи ---

    def labels(self, lang: str) -> tuple[dict[str, str], dict[str, str]]:
        """Основное название на языке ``lang`` (нет — русское, затем любое, как в снимке)
        и его нормализованная форма — ключ сортировки по названию."""
        if lang not in self._labels:
            labels = dict(self.snapshot.labels)
            if lang != "ru":
                for entity_id, names in self.snapshot.names.items():
                    own = [n for n in names if n["kind"] == "primary" and n["lang"] == lang]
                    if own and entity_id in labels:
                        labels[entity_id] = own[0]["text"]
            self._labels[lang] = (labels, {e: normalize(text) for e, text in labels.items()})
        return self._labels[lang]

    # --- запрос ---

    def query(self, query: Query, closed: bool = False) -> dict[str, Any]:
        sort = query.sort
        if sort == "relevance" and not query.q:
            sort = "label"
        if closed:
            return {
                "items": [],
                "total": 0,
                "page": query.page,
                "limit": query.limit,
                "sort": sort,
                "facets": {"types": {}, "epochs": []},
                "textbook_closed": True,
            }
        labels, normalized_labels = self.labels(query.lang)

        def sort_label(r: Record) -> str:
            return normalized_labels[r.id]

        # Поиск и раздел — общие для списка и обоих счётчиков; тип и эпоха — «без своего».
        matched: list[tuple[Record, int, str | None]] = []
        for r in self.records:
            if query.textbook is not None and query.textbook not in r.sources:
                continue
            if not query.q:
                matched.append((r, 0, None))
                continue
            best: tuple[int, str | None] | None = None
            label_norm = normalized_labels[r.id]
            for normalized, text in r.names:
                rank = _rank(normalized, query.q)
                if rank is None:
                    continue
                shown = None if normalized == label_norm else text
                if best is None or (rank, shown is not None) < (best[0], best[1] is not None):
                    best = (rank, shown)
            if best is not None:
                matched.append((r, *best))

        def type_ok(r: Record) -> bool:
            return query.types is None or r.type in query.types

        def epoch_ok(r: Record) -> bool:
            return query.epoch is None or any(e == query.epoch for e, _ in r.epochs)

        found = [m for m in matched if type_ok(m[0]) and epoch_ok(m[0])]
        types = Counter(m[0].type for m in matched if epoch_ok(m[0]))
        epoch_counts = Counter(e for m in matched if type_ok(m[0]) for e, _ in m[0].epochs)

        keys: dict[str, Callable[[tuple[Record, int, str | None]], tuple]] = {
            "label": lambda m: (sort_label(m[0]), m[0].id),
            "date": lambda m: (
                m[0].start is None,
                m[0].start or 0,
                sort_label(m[0]),
                m[0].id,
            ),
            "weight": lambda m: (-m[0].weight, sort_label(m[0]), m[0].id),
            "relevance": lambda m: (m[1], -m[0].weight, sort_label(m[0]), m[0].id),
        }
        found.sort(key=keys[sort])
        offset = (query.page - 1) * query.limit
        page = found[offset : offset + query.limit]
        return {
            "items": [self._item(r, matched_name, labels) for r, _, matched_name in page],
            "total": len(found),
            "page": query.page,
            "limit": query.limit,
            "sort": sort,
            "facets": {
                "types": {code: n for code, n in sorted(types.items()) if n},
                "epochs": [
                    {"id": e, "label": labels[e], "count": epoch_counts[e]}
                    for e in self.epochs.epochs()
                    if epoch_counts[e]
                ],
            },
            "textbook_closed": False,
        }

    def _item(self, r: Record, matched_name: str | None, labels: dict[str, str]) -> dict:
        return {
            "id": r.id,
            "type": r.type,
            "label": labels[r.id],
            "matched_name": matched_name,
            "dates": dict(r.dates) if r.dates else None,
            "epochs": [{"id": e, "label": labels[e], "basis": basis} for e, basis in r.epochs],
            "summary": dict(r.summary) if r.summary else None,
            "weight": r.weight,
        }


def _integer(value: str | None, default: int, low: int, high: int | None, reason: str) -> int:
    if value is None or value == "":
        return default
    try:
        number = int(value)
    except ValueError:
        raise CatalogRejected("bad_query", reason) from None
    if number < low or (high is not None and number > high):
        raise CatalogRejected("bad_query", reason)
    return number


class Catalog:
    """Справочник сервиса знаний: проверка параметров, снимок, индекс и журнал."""

    def __init__(
        self,
        snapshots: Snapshots,
        registry: OntologyRegistry,
        entities: Entities,
        settings: CatalogSettings | None = None,
    ) -> None:
        self.snapshots = snapshots
        self.registry = registry
        self.entities = entities
        self.settings = settings or CatalogSettings()

    def index(self, snapshot: Snapshot) -> CatalogIndex:
        return snapshot.derived(
            "catalog",
            lambda s: CatalogIndex(s, self.registry, membership(s, self.registry)),
        )

    def _types(self, codes: Iterable[str]) -> frozenset[str] | None:
        codes = [c for c in codes if c != ""]
        if not codes:
            return None
        found: set[str] = set()
        for code in codes:
            try:
                self.registry.entity_type(code)
            except RegistryError:
                raise CatalogRejected("unknown_type", "unknown_type") from None
            found |= self.registry.entity_subtypes(code)
        return frozenset(found)

    def _parse(
        self,
        index: CatalogIndex,
        *,
        q: str | None,
        types: Iterable[str],
        epoch: str | None,
        textbook: str | None,
        sort: str | None,
        page: str | None,
        limit: str | None,
        lang: str | None,
    ) -> Query:
        text = (q or "").strip()
        if len(text) > MAX_QUERY:
            raise CatalogRejected("bad_query", "query_too_long")
        limit_n = _integer(limit, DEFAULT_LIMIT, 1, MAX_LIMIT, "limit")
        page_n = _integer(page, 1, 1, None, "page")
        normalized = normalize(text)
        if sort in (None, ""):
            sort = "relevance" if normalized else "label"
        if sort not in SORTS:
            raise CatalogRejected("bad_query", "sort")
        type_set = self._types(types)
        epoch_id = None
        if epoch:
            epoch_id = self.entities.resolve(epoch)
            row = index.snapshot.entities.get(epoch_id)
            if row is None or not self.registry.is_a(row["type"], ["epoch"]):
                raise CatalogRejected("unknown_epoch", "unknown_epoch")
        if textbook and textbook not in index.known_sources:
            raise CatalogRejected("unknown_textbook", "unknown_textbook")
        return Query(
            q=normalized,
            q_len=len(text) if normalized else 0,
            types=type_set,
            epoch=epoch_id,
            textbook=textbook or None,
            sort=sort,
            page=page_n,
            limit=limit_n,
            lang=lang or "ru",
        )

    def list(
        self,
        *,
        q: str | None = None,
        types: Iterable[str] = (),
        epoch: str | None = None,
        textbook: str | None = None,
        sort: str | None = None,
        page: str | None = None,
        limit: str | None = None,
        lang: str | None = None,
        closed: Callable[[], frozenset[str]] = frozenset,
    ) -> dict[str, Any]:
        """Страница справочника. ``closed`` — закрытые для читателя источники; вызывается
        только при фильтре по разделу. Недопустимый параметр — ``CatalogRejected``."""
        snapshot, status = self.snapshots.get(max_stale=self.settings.max_stale_seconds)
        index = self.index(snapshot)
        try:
            query = self._parse(
                index,
                q=q,
                types=types,
                epoch=epoch,
                textbook=textbook,
                sort=sort,
                page=page,
                limit=limit,
                lang=lang,
            )
        except CatalogRejected as exc:
            events.emit("knowledge.catalog.rejected", reason=exc.reason)
            raise
        is_closed = query.textbook is not None and query.textbook in closed()
        result = index.query(query, closed=is_closed)
        self._emit(query, result, status)
        return result

    @staticmethod
    def _emit(query: Query, result: dict[str, Any], status: Status) -> None:
        events.emit(
            "knowledge.catalog.listed",
            total=result["total"],
            returned=len(result["items"]),
            page=query.page,
            filters=query.filters,
            q_len=query.q_len,
            sort=result["sort"],
            snapshot=status,
            textbook_closed=result["textbook_closed"],
        )
