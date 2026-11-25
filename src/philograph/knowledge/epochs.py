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
"""

from __future__ import annotations

from collections import defaultdict
from typing import Literal

from philograph.knowledge.dates import middle, span
from philograph.knowledge.registry import OntologyRegistry
from philograph.knowledge.snapshot import Snapshot

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
