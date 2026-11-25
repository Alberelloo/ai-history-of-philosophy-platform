"""Географический слой карты раздела (geo-timeline): где жили персоны и где шли события.

Слой строится из того же, что карта: сущности — ``people`` и ``events`` из
``SectionMap.result`` (та же область и тот же предел, что у ``/map``, без события
``knowledge.map.built``), утверждения ``lived_in``, ``happened_in`` и ``coordinates`` — из
общего снимка ``Snapshots`` (правило «действующее утверждение» одно на сервис). Модель
не вызывается, внешних запросов нет.

Правила сборки:

- размещение — утверждение «жил в» (вид места — уточнитель ``place_role``, годы — ``span``
  уточнителя ``time``) или «произошло в» (вид ``event``, годы — год события на карте);
- для пары «сущность — место» записи с видом вытесняют записи без вида (импорт P19 без
  вида и обогащение с видом описывают одно и то же);
- размещение отдаётся, только если у места есть координаты; из нескольких координат
  места берутся одни: предпочтённые, иначе более сильные по статусу, иначе раньше
  записанные (наименьший id атрибуции — атрибуция обязательна и пишется вместе
  с утверждением);
- сущность карты без единого размещения с координатами — в ``unplaced``.

Правило «где персона в год T» — в клиенте (``web/src/map/geo/timeline.ts``): сервер годы
жизни не подставляет. Ответ кэшируется по области и отпечатку снимка, LRU на
``cache_size`` областей.
"""

from __future__ import annotations

import threading
from collections import OrderedDict, defaultdict
from collections.abc import Mapping
from typing import Any

from philograph.knowledge.dates import span
from philograph.knowledge.map import SectionMap
from philograph.knowledge.snapshot import Snapshots
from philograph.knowledge.statements import STRENGTH
from philograph.platform import events

events.define(
    "knowledge.geo.built",
    "info",
    "Построен географический слой карты",
    required=("entities", "places", "placements", "unplaced", "truncated", "cached"),
)

LIVED_IN = "lived_in"
HAPPENED_IN = "happened_in"
COORDINATES = "coordinates"
EVENT_ROLE = "event"


def _years(qualifiers: Mapping[str, Any]) -> tuple[int | None, int | None]:
    """Годы размещения из уточнителя ``time`` (та же функция середины, что у карты)."""
    time = qualifiers.get("time")
    if not isinstance(time, Mapping):
        return None, None
    try:
        start, end = span(time)
    except (KeyError, TypeError):  # запись не по формату нечёткой даты
        return None, None
    return start, end


def _first_written(s: Mapping[str, Any]) -> tuple[int, str]:
    ids = [a["id"] for a in s.get("attributions") or [] if a.get("id") is not None]
    return (min(ids) if ids else 2**63, s["id"])


def best_coordinates(rows: list[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    """Одни координаты места: предпочтённые, затем по статусу, затем раньше записанные."""
    valid = [s for s in rows if isinstance(s.get("value"), Mapping)]
    if not valid:
        return None
    return min(
        valid, key=lambda s: (s["rank"] != "preferred", -STRENGTH[s["status"]], _first_written(s))
    )


class PlaceLayer:
    def __init__(
        self, section_map: SectionMap, snapshots: Snapshots, *, cache_size: int = 32
    ) -> None:
        self.section_map = section_map
        self.snapshots = snapshots
        self.cache_size = cache_size
        self._cache: OrderedDict[tuple[str | None, bool], tuple[tuple, dict[str, Any]]] = (
            OrderedDict()
        )
        self._lock = threading.Lock()

    def cached_scopes(self) -> int:
        """Сколько областей сейчас в кэше (не больше ``cache_size``)."""
        with self._lock:
            return len(self._cache)

    def build(self, textbook: str | None = None, only_textbook: bool = False) -> dict[str, Any]:
        only_textbook = bool(only_textbook and textbook)
        key = (textbook, only_textbook)
        snapshot, _ = self.snapshots.get(max_stale=0)
        with self._lock:
            cached = self._cache.get(key)
            hit = cached is not None and cached[0] == snapshot.fingerprint
            if hit:
                self._cache.move_to_end(key)
        if hit:
            result = cached[1]
        else:
            data, _ = self.section_map.result(textbook, only_textbook)
            result = self._build(data, snapshot.statements, snapshot.labels)
            with self._lock:
                self._cache[key] = (snapshot.fingerprint, result)
                self._cache.move_to_end(key)
                while len(self._cache) > self.cache_size:
                    self._cache.popitem(last=False)
        events.emit(
            "knowledge.geo.built",
            entities=result["entities"],
            places=len(result["places"]),
            placements=len(result["placements"]),
            unplaced=len(result["unplaced"]),
            truncated=result["truncated"],
            cached=hit,
        )
        return {k: v for k, v in result.items() if k != "entities"}

    @staticmethod
    def _build(
        data: Mapping[str, Any],
        statements: tuple[dict[str, Any], ...],
        labels: Mapping[str, str],
    ) -> dict[str, Any]:
        people = [p["id"] for p in data["people"]]
        event_year = {e["id"]: e["year"] for e in data["events"]}
        on_map = set(people) | set(event_year)

        coordinates: dict[str, list[dict[str, Any]]] = defaultdict(list)
        raw: list[dict[str, Any]] = []
        for s in statements:
            if s["type"] == COORDINATES:
                coordinates[s["subject"]].append(s)
            elif s["subject"] in on_map and s["object"]:
                if s["type"] == LIVED_IN and s["subject"] not in event_year:
                    start, end = _years(s["qualifiers"] or {})
                    role = (s["qualifiers"] or {}).get("place_role")
                elif s["type"] == HAPPENED_IN and s["subject"] in event_year:
                    start = end = event_year[s["subject"]]
                    role = EVENT_ROLE
                else:
                    continue
                raw.append(
                    {
                        "entity": s["subject"],
                        "place": s["object"],
                        "role": role,
                        "from": start,
                        "to": end,
                        "status": s["status"],
                        "generated": s["status"] == "generated",
                        "statement": s["id"],
                    }
                )

        places: dict[str, dict[str, Any]] = {}
        for place_id in {p["place"] for p in raw}:
            best = best_coordinates(coordinates.get(place_id, []))
            if best is None:
                continue
            places[place_id] = {
                "id": place_id,
                "label": labels.get(place_id, place_id),
                "lat": best["value"]["lat"],
                "lon": best["value"]["lon"],
                "status": best["status"],
            }

        # С видом вытесняет без вида — по паре «сущность — место».
        with_role = {(p["entity"], p["place"]) for p in raw if p["role"] is not None}
        placements = [
            p
            for p in raw
            if p["place"] in places
            and (p["role"] is not None or (p["entity"], p["place"]) not in with_role)
        ]
        placements.sort(
            key=lambda p: (
                p["entity"],
                p["from"] if p["from"] is not None else -(2**31),
                p["role"] or "",
                p["place"],
                p["statement"],
            )
        )
        placed = {p["entity"] for p in placements}
        unplaced = [e for e in [*people, *event_year] if e not in placed]
        return {
            "places": sorted(places.values(), key=lambda p: p["id"]),
            "placements": placements,
            "unplaced": unplaced,
            "truncated": data["truncated"],
            "limit": data["limit"],
            "entities": len(on_map),
        }
