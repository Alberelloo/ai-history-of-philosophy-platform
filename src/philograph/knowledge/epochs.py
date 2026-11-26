"""Принадлежность сущности к эпохе — одно правило для справочника, карты и контекста.

Правило — требование «Принадлежность к эпохе» возможности ``epochs``:

1. Явное важнее дат. Если у сущности есть действующие утверждения «относится к эпохе»
   (``belongs_to_epoch`` и его подтипы; в снимке уже нет отклонённых и «устаревших»),
   принадлежность берётся только из них, основание ``explicit``.
2. Иначе — по датам, основание ``dates``: персона, труд, событие (с подтипами, в том числе
   идейное событие) и явление относятся к эпохам, в пролёт которых попадает середина их
   жизни или датировки (``dates.middle``). Пролёт эпохи — ``dates.span``, полуинтервал
   ``[начало, конец)``.
3. Без датировки — только явное: у сущности без дат и у эпохи без дат принадлежности по
   датам нет. Группы, идеи, термины, места и сами эпохи по датам не относятся ни к чему.
4. Эпоха не относится к себе.

Выведенное не записывается в базу (ontology.md, О-8): ``EpochMembership`` строится в памяти
из снимка, один раз на снимок (``Snapshot.derived``).

Список эпох (``EpochList``, требование «Список эпох», ``GET /v1/epochs``) строится из того же
снимка справочника: пролёт — ``dates.span``, нечёткие границы — пары «самое раннее, самое
позднее», источник — по атрибуции основной датировки, счётчики — ``members`` по видам карты.
"""

from __future__ import annotations

import copy
from collections import defaultdict
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Literal

from philograph.knowledge.dates import middle, span
from philograph.knowledge.graph import wikidata_qid
from philograph.knowledge.registry import OntologyRegistry
from philograph.knowledge.snapshot import Snapshot
from philograph.platform import events

if TYPE_CHECKING:  # справочник импортирует этот модуль; здесь — только для типов
    from philograph.knowledge.catalog import Catalog

Basis = Literal["explicit", "dates"]
BELONGS = "belongs_to_epoch"
EPOCH = "epoch"
# Типы, которые относятся к эпохе по датам (с подтипами по реестру).
DATED_TYPES = ["person", "work", "event", "phenomenon"]


class EpochMembership:
    def __init__(self, snapshot: Snapshot, registry: OntologyRegistry) -> None:
        entities = snapshot.entities
        self._epochs = [e for e, row in entities.items() if registry.is_a(row["type"], [EPOCH])]
        epoch_set = set(self._epochs)
        spans = {
            e: span(entities[e]["primary"]["dates"])
            for e in self._epochs
            if entities[e]["primary"].get("dates")
        }
        self._spans = spans
        labels = snapshot.labels
        self._order = {
            e: (spans[e][0] if e in spans else None, labels.get(e, e), e) for e in self._epochs
        }

        explicit: dict[str, set[str]] = defaultdict(set)
        relations = registry.relation_subtypes(BELONGS)
        for s in snapshot.statements:
            if s["type"] in relations and s["object"] in epoch_set and s["object"] != s["subject"]:
                explicit[s["subject"]].add(s["object"])

        dated_type: dict[str, bool] = {}
        of: dict[str, list[tuple[str, Basis]]] = {}
        for entity_id, row in entities.items():
            if entity_id in explicit:
                of[entity_id] = [(e, "explicit") for e in self._sorted(explicit[entity_id])]
                continue
            type_ = row["type"]
            if type_ not in dated_type:
                dated_type[type_] = registry.is_a(type_, DATED_TYPES)
            dates = row["primary"].get("dates")
            if not dated_type[type_] or not dates:
                continue
            mid = middle(dates)
            found = [e for e, (start, end) in spans.items() if start <= mid < end]
            if found:
                of[entity_id] = [(e, "dates") for e in self._sorted(found)]
        self._of = of
        members: dict[str, list[tuple[str, Basis]]] = defaultdict(list)
        for entity_id in sorted(of):
            for epoch_id, basis in of[entity_id]:
                members[epoch_id].append((entity_id, basis))
        self._members = dict(members)

    def _sorted(self, epochs) -> list[str]:
        """Эпохи по началу датировки, без датировки — в конце; затем по названию и id."""
        return sorted(
            epochs,
            key=lambda e: (self._order[e][0] is None, self._order[e][0] or 0, *self._order[e][1:]),
        )

    def epochs(self) -> list[str]:
        """Все эпохи снимка в порядке показа."""
        return self._sorted(self._epochs)

    def span(self, epoch_id: str) -> tuple[int, int] | None:
        return self._spans.get(epoch_id)

    def of(self, entity_id: str) -> list[tuple[str, Basis]]:
        """Эпохи сущности с основанием, в порядке показа."""
        return list(self._of.get(entity_id, ()))

    def members(self, epoch_id: str) -> list[tuple[str, Basis]]:
        """Сущности эпохи с основанием, по идентификатору."""
        return list(self._members.get(epoch_id, ()))


def membership(snapshot: Snapshot, registry: OntologyRegistry) -> EpochMembership:
    """Принадлежность для снимка — одна на снимок."""
    return snapshot.derived("epochs", lambda s: EpochMembership(s, registry))


# --- список эпох (``GET /v1/epochs``) -------------------------------------------------

events.define(
    "knowledge.epochs.listed",
    "info",
    "Отдан список эпох",
    required=("epochs", "undated", "truncated", "snapshot"),
)

MAX_EPOCHS = 500
DATING = "dating"
# Виды счётчиков эпохи — те же категории, что на карте раздела.
IDEA_TYPES = ("concept", "conception", "doctrine", "problem", "position", "argument")
COUNT_KINDS = ("people", "works", "ideas", "events", "groups")


def count_kind(registry: OntologyRegistry, entity_type: str) -> str | None:
    if entity_type == "person":
        return "people"
    if entity_type == "work":
        return "works"
    if entity_type in IDEA_TYPES:
        return "ideas"
    if registry.is_a(entity_type, ["event", "phenomenon"]):
        return "events"
    if entity_type == "group":
        return "groups"
    return None


def dating_source(statement: dict[str, Any] | None) -> dict[str, Any]:
    """Источник основной датировки по её атрибуции (требование «Список эпох»):
    ``wikidata:Q…`` — ``wikidata``; источник библиотеки или подтверждающий абзац — ``source``;
    общее мнение — ``common``; без атрибуции — ``manual``. QID — только по шаблону."""
    if statement is None:
        return {"status": None, "source": "manual", "wikidata": None}
    shown = [a for a in statement["attributions"] if not a["hidden"]]
    qid = next((q for a in shown if (q := wikidata_qid(a))), None)
    if qid is not None:
        source = "wikidata"
    elif any(a["who_kind"] in ("source", "entity") for a in shown) or any(
        not e["lost"] for e in statement["evidence"]
    ):
        source = "source"
    elif any(a["who_kind"] == "common" for a in shown):
        source = "common"
    else:
        source = "manual"
    return {"status": statement["status"], "source": source, "wikidata": qid}


def _main_dating(rows: list[dict[str, Any]], primary: Mapping[str, Any]) -> dict[str, Any] | None:
    """Утверждение основной датировки — то, чьё значение скопировано в ``primary.dates``
    (``Statements._update_primary``: предпочтённое, иначе первое записанное)."""
    same = [s for s in rows if s["value"] == primary]
    pool = same or rows
    if not pool:
        return None
    return sorted(pool, key=lambda s: s["rank"] != "preferred")[0]


class EpochList:
    """Список эпох из снимка справочника (окно устарелости справочника), без модели.

    Описание — то же, что в записи справочника (``CatalogIndex``), счётчики — по
    ``EpochMembership.members``, по видам карты."""

    def __init__(self, catalog: Catalog, max_epochs: int = MAX_EPOCHS) -> None:
        self.catalog = catalog
        self.max_epochs = max_epochs

    def _build(self, snapshot: Snapshot) -> dict[str, Any]:
        registry = self.catalog.registry
        epochs = membership(snapshot, registry)
        index = self.catalog.index(snapshot)
        summaries = {r.id: r.summary for r in index.records}
        datings: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for s in snapshot.statements:
            if s["type"] == DATING:
                datings[s["subject"]].append(s)
        kinds: dict[str, str | None] = {}

        def counts(epoch_id: str) -> dict[str, int]:
            found = dict.fromkeys(COUNT_KINDS, 0)
            for entity_id, _ in epochs.members(epoch_id):
                type_ = snapshot.entities[entity_id]["type"]
                if type_ not in kinds:
                    kinds[type_] = count_kind(registry, type_)
                if kinds[type_]:
                    found[kinds[type_]] += 1
            return found

        ordered = epochs.epochs()
        truncated = len(ordered) > self.max_epochs
        dated, undated = [], []
        for epoch_id in ordered[: self.max_epochs]:
            label = snapshot.labels[epoch_id]
            primary = snapshot.entities[epoch_id]["primary"].get("dates")
            if not primary:
                undated.append({"id": epoch_id, "label": label, "counts": counts(epoch_id)})
                continue
            start, end = span(primary)
            summary = summaries.get(epoch_id)
            dated.append(
                {
                    "id": epoch_id,
                    "label": label,
                    "from": start,
                    "to": end,
                    "fuzzy": fuzzy(primary),
                    "precision": primary.get("precision"),
                    "original": primary.get("original"),
                    "dating": dating_source(_main_dating(datings.get(epoch_id, []), primary)),
                    "summary": dict(summary) if summary else None,
                    "counts": counts(epoch_id),
                }
            )
        return {"epochs": dated, "undated": undated, "truncated": truncated}

    def list(self) -> dict[str, Any]:
        snapshot, status = self.catalog.snapshots.get(
            max_stale=self.catalog.settings.max_stale_seconds
        )
        result = snapshot.derived("epoch_list", self._build)
        events.emit(
            "knowledge.epochs.listed",
            epochs=len(result["epochs"]),
            undated=len(result["undated"]),
            truncated=result["truncated"],
            snapshot=status,
        )
        return copy.deepcopy(result)


def fuzzy(dates: Mapping[str, Any]) -> dict[str, list[int]]:
    """Нечёткие границы пролёта: пары «самое раннее, самое позднее» начала и конца."""
    return {
        "from": [dates["earliest_start"], dates["latest_start"]],
        "to": [dates["earliest_end"], dates["latest_end"]],
    }
