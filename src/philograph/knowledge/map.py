"""Карта раздела (synchro-map): сущности области с датами, группы, влияния между людьми.

Карта строится из сохранённых утверждений одним проходом по базе, без модели и без обхода
по рецепту: ось времени — годы жизни, датировки трудов, событий и эпох. Идея ставится на год
самого раннего датированного труда, где она высказана или рассматривается; без такого труда
она уходит в «без даты». Членство в эпохе клиент считает по датам сам: здесь — только пролёты.

Ответ кэшируется в памяти процесса по области и отпечатку базы (число и последние записи
утверждений, атрибуций, упоминаний, слияний, версия реестра) — пока данные не менялись,
повторный запрос базу целиком не читает. Портреты к ответу добавляются каждый раз: их
проверка оператором отпечаток не меняет.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlencode

from sqlalchemy import and_, func, select

from philograph.knowledge import schema as t
from philograph.knowledge.dates import span
from philograph.knowledge.entities import EntityNotFound
from philograph.knowledge.statements import INFLUENCE, STRENGTH, Statements
from philograph.platform import events

events.define(
    "knowledge.map.built",
    "info",
    "Построена карта раздела",
    required=("entities", "links", "truncated", "cached"),
)

# Вид значка труда или идеи на карте; концепция, учение и проблема рисуются понятием.
IDEA_KIND = {
    "concept": "concept",
    "conception": "concept",
    "doctrine": "concept",
    "problem": "concept",
    "position": "position",
    "argument": "argument",
}
VALUE_TYPES = ("lifespan", "dating", "person_role", "group_kind", "event_kind", "description")


@dataclass(frozen=True)
class MapSettings:
    max_entities: int = 400  # больше — остаются самые весомые, ``truncated``


def _start(dates: dict[str, Any]) -> int:
    return span(dates)[0]


def _end(dates: dict[str, Any]) -> int:
    return span(dates)[1]


def _short(label: str) -> str:
    """Короткая подпись ленты: последнее слово имени («Иммануил Кант» → «Кант»)."""
    words = label.split()
    return words[-1] if words else label


def _best(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Основное из нескольких: предпочтённое, затем более сильное по статусу."""
    if not rows:
        return None
    return sorted(rows, key=lambda s: (s["rank"] != "preferred", -STRENGTH[s["status"]]))[0]


class SectionMap:
    def __init__(self, statements: Statements, settings: MapSettings | None = None) -> None:
        self.statements = statements
        self.registry = statements.registry
        self.engine = statements.engine
        self.settings = settings or MapSettings()
        self._cache: dict[tuple[str | None, bool], tuple[tuple, dict[str, Any]]] = {}

    # --- кэш ---

    def _fingerprint(self) -> tuple:
        """Меняется при любой записи, влияющей на карту: новые и изменённые утверждения
        (журнал), атрибуции и подтверждения, события библиотеки (снятие источника), имена,
        слияния, упоминания и версия реестра."""
        count = func.count
        with self.engine.begin() as conn:
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
                    )
                ).one()
            )

    def build(self, textbook: str | None = None, only_textbook: bool = False) -> dict[str, Any]:
        """``textbook`` — выбранный учебник: пометка ``in_textbook`` у связей; с
        ``only_textbook`` область — только сущности, упомянутые или атрибутированные в нём."""
        only_textbook = bool(only_textbook and textbook)
        key = (textbook, only_textbook)
        fingerprint = self._fingerprint()
        cached = self._cache.get(key)
        if cached is not None and cached[0] == fingerprint:
            result = cached[1]
        else:
            result = self._build(textbook, only_textbook)
            self._cache[key] = (fingerprint, result)
        events.emit(
            "knowledge.map.built",
            entities=len(result["people"]) + len(result["works"]) + len(result["events"]),
            links=len(result["links"]),
            truncated=result["truncated"],
            cached=cached is not None and cached[0] == fingerprint,
        )
        return self._with_portraits(result)

    # --- чтение базы ---

    def _load(self) -> tuple[dict[str, dict[str, Any]], dict[str, str], list[dict[str, Any]]]:
        """Сущности, подписи и действующие утверждения: не отклонённые, не отвергнутые
        (ранг «устаревшее»), не основанные только на снятом источнике — как в ``about``."""
        with self.engine.begin() as conn:
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
            statements.append(s)
        return entities, labels, statements

    def _textbook_entities(self, textbook: str) -> set[str]:
        with self.engine.begin() as conn:
            return set(
                conn.scalars(
                    select(t.mentions.c.entity_id).where(t.mentions.c.source_id == textbook)
                )
            )

    # --- сборка ---

    def _build(self, textbook: str | None, only_textbook: bool) -> dict[str, Any]:
        entities, labels, statements = self._load()
        attributed = self.statements._attributed
        is_a = self.registry.is_a

        def category(entity_type: str) -> str | None:
            if entity_type == "person":
                return "person"
            if entity_type == "work":
                return "work"
            if entity_type in IDEA_KIND:
                return "idea"
            if is_a(entity_type, ["event", "phenomenon"]):
                return "event"
            if entity_type == "epoch":
                return "era"
            if entity_type == "group":
                return "group"
            return None  # термины, места, источники библиотеки на карту не попадают

        # Область: вся библиотека или то, что упомянуто и атрибутировано в учебнике.
        in_scope = (
            [s for s in statements if attributed(s, textbook)] if only_textbook else statements
        )
        if only_textbook:
            scope = self._textbook_entities(textbook)
            for s in in_scope:
                scope.add(s["subject"])
                if s["object"]:
                    scope.add(s["object"])
        else:
            scope = set(entities)
        cats = {e: c for e in scope if e in entities and (c := category(entities[e]["type"]))}

        weight: dict[str, int] = defaultdict(int)
        for s in in_scope:
            weight[s["subject"]] += 1
            if s["object"]:
                weight[s["object"]] += 1

        # Факты о сущностях берутся из всех действующих утверждений, а не только из области:
        # годы жизни Канта общеизвестны, даже если учебник их не называет.
        values: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        authors: dict[str, list[dict[str, Any]]] = defaultdict(list)
        expressed_in: dict[str, set[str]] = defaultdict(set)
        members: dict[str, set[str]] = defaultdict(set)
        for s in statements:
            if s["type"] in VALUE_TYPES:
                values[(s["subject"], s["type"])].append(s)
            elif s["type"] == "author":
                authors[s["subject"]].append(s)
            elif s["type"] in ("expresses", "discusses"):
                expressed_in[s["object"]].add(s["subject"])
            elif s["type"] in ("member_of", "founded"):
                members[s["object"]].add(s["subject"])

        def dates(entity_id: str) -> dict[str, Any] | None:
            return entities[entity_id]["primary"].get("dates")

        def value(entity_id: str, type_: str) -> Any:
            best = _best(values.get((entity_id, type_), []))
            return best["value"] if best else None

        def author(work_id: str) -> str | None:
            best = _best(authors.get(work_id, []))
            return best["object"] if best else None

        items: list[tuple[str, dict[str, Any]]] = []  # (раздел ответа, запись)
        for entity_id, cat in cats.items():
            label = labels[entity_id]
            d = dates(entity_id) if cat != "idea" else None
            base = {"id": entity_id, "label": label}
            if cat == "group":
                items.append(("groups", {**base, "kind": value(entity_id, "group_kind")}))
            elif cat == "idea":
                dated = [w for w in expressed_in.get(entity_id, ()) if w in entities and dates(w)]
                if not dated:
                    items.append(("undated", {**base, "type": entities[entity_id]["type"]}))
                    continue
                first = min(dated, key=lambda w: (_start(dates(w)), w))
                items.append(
                    (
                        "works",
                        {
                            **base,
                            "type": entities[entity_id]["type"],
                            "kind": IDEA_KIND[entities[entity_id]["type"]],
                            "year": _start(dates(first)),
                            "author": author(first),
                            "via": first,
                        },
                    )
                )
            elif d is None:
                items.append(("undated", {**base, "type": entities[entity_id]["type"]}))
            elif cat == "person":
                roles = sorted({s["value"] for s in values.get((entity_id, "person_role"), [])})
                items.append(
                    (
                        "people",
                        {
                            **base,
                            "short": _short(label),
                            "birth": _start(d),
                            "death": _end(d),
                            "precision": d["precision"],
                            "roles": roles,
                        },
                    )
                )
            elif cat == "work":
                items.append(
                    (
                        "works",
                        {
                            **base,
                            "type": "work",
                            "kind": "work",
                            "year": _start(d),
                            "author": author(entity_id),
                        },
                    )
                )
            elif cat == "event":
                event = {**base, "year": _start(d)}
                kind = value(entity_id, "event_kind")
                if kind:
                    event["kind"] = kind
                items.append(("events", event))
            else:  # эпоха
                items.append(("eras", {**base, "from": _start(d), "to": _end(d)}))

        # Предел: остаются самые весомые (вес — число утверждений сущности в области).
        limit = self.settings.max_entities
        truncated = len(items) > limit
        if truncated:
            items = sorted(items, key=lambda it: (-weight[it[1]["id"]], it[1]["label"]))[:limit]
        sections: dict[str, list[dict[str, Any]]] = {
            k: [] for k in ("people", "works", "events", "eras", "groups", "undated")
        }
        for section, item in items:
            if section in ("people", "works"):
                item["weight"] = weight[item["id"]]
            sections[section].append(item)
        people = {p["id"] for p in sections["people"]}
        for work in sections["works"]:
            work.pop("via", None)
        for group in sections["groups"]:
            group["members"] = sorted(m for m in members.get(group["id"], ()) if m in people)

        # Линии только между людьми: влияние и его подтипы, «учился у».
        influence = self.registry.relation_subtypes(INFLUENCE)
        links = [
            {
                "id": s["id"],
                "subject": s["subject"],
                "object": s["object"],
                "type": s["type"],
                "status": s["status"],
                "generated": s["status"] == "generated",
                "in_textbook": attributed(s, textbook) if textbook else None,
            }
            for s in in_scope
            if s["type"] in influence and s["subject"] in people and s["object"] in people
        ]

        years = [y for p in sections["people"] for y in (p["birth"], p["death"])]
        years += [w["year"] for w in sections["works"]]
        years += [e["year"] for e in sections["events"]]
        years += [y for e in sections["eras"] for y in (e["from"], e["to"])]
        order = {
            "people": lambda p: (p["birth"], p["label"]),
            "works": lambda w: (w["year"], w["label"]),
            "events": lambda e: (e["year"], e["label"]),
            "eras": lambda e: (e["from"], e["label"]),
            "groups": lambda g: g["label"],
            "undated": lambda u: u["label"],
        }
        for section, sort_key in order.items():
            sections[section].sort(key=sort_key)
        return {
            "range": [min(years), max(years)] if years else None,
            "truncated": truncated,
            "limit": limit,
            **sections,
            "links": sorted(links, key=lambda link: link["id"]),
        }

    def _with_portraits(self, result: dict[str, Any]) -> dict[str, Any]:
        """Главный подтверждённый и нескрытый портрет персоны — ссылкой, как в карточке."""
        ids = [p["id"] for p in result["people"]]
        if not ids:
            return result
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(t.portraits.c.id, t.portraits.c.entity_id)
                .where(
                    t.portraits.c.entity_id.in_(ids),
                    t.portraits.c.status == "approved",
                    t.portraits.c.hidden.is_(False),
                )
                .order_by(t.portraits.c.position, t.portraits.c.id)
            ).all()
        main: dict[str, int] = {}
        for portrait_id, entity_id in rows:
            main.setdefault(entity_id, portrait_id)
        if not main:
            return result
        people = [
            {**p, "portrait": f"/api/knowledge/v1/portraits/{main[p['id']]}"}
            if p["id"] in main
            else p
            for p in result["people"]
        ]
        return {**result, "people": people}


# --- вид карты от ассистента (assistant-map-view) ---

events.define(
    "knowledge.map_view.normalized",
    "info",
    "Проверен вид карты",
    required=("dropped", "shown", "relaxed"),
)

STRATA = ("events", "eras", "people", "works")
WORK_KINDS = ("work", "concept", "position", "argument")
FILTER_GROUP_KINDS = ("direction", "school")  # группы, которые есть в фильтрах карты
# Порядок, в котором снимаются фильтры, если вид дал пустую карту.
RELAX_ORDER = ("ekinds", "kinds", "roles", "years", "groups")
LIST_FIELDS = ("groups", "roles", "kinds", "ekinds")


def map_href(view: dict[str, Any], via: str | None = "assistant") -> str:
    """Адрес карты для вида — тот же, что пишет клиент (``web/src/map/types.ts`` →
    ``writeState`` и запись адреса в ``MapPage``): выбор в пути, списки через запятую,
    значения по умолчанию не пишутся, служебный ``via`` — последним."""
    params: list[tuple[str, str]] = []
    if view.get("from") is not None:
        params.append(("from", str(view["from"])))
    if view.get("to") is not None:
        params.append(("to", str(view["to"])))
    for key in LIST_FIELDS:
        if view.get(key):
            params.append((key, ",".join(view[key])))
    if view.get("verified"):
        params.append(("verified", "1"))
    lens = [k for k in STRATA if k in (view.get("lens") or [])]
    if lens:
        params.append(("lens", ",".join(lens)))
    if via:
        params.append(("via", via))
    path = "/graph" + (f"/{quote(view['sel'], safe='')}" if view.get("sel") else "")
    query = urlencode(params).replace("%2C", ",")
    return path + (f"?{query}" if query else "")


def visible_counts(data: dict[str, Any], view: dict[str, Any]) -> dict[str, int]:
    """Сколько персон и трудов видно при фильтрах вида — как ``visible`` клиента
    (``web/src/map/model.ts``)."""
    lo, hi = data["range"] or (0, 1)
    start = view["from"] if view.get("from") is not None else lo
    end = view["to"] if view.get("to") is not None else hi
    groups = [g for g in data["groups"] if g["id"] in view["groups"]]
    roles = view["roles"]
    people = [
        p
        for p in data["people"]
        if (not groups or any(p["id"] in g["members"] for g in groups))
        and (not roles or any(r in roles for r in p["roles"]))
        and p["death"] >= start
        and p["birth"] <= end
    ]
    shown = {p["id"] for p in people}
    known = {p["id"] for p in data["people"]}

    def author_shown(w: dict[str, Any]) -> bool:
        if w.get("author") is not None and w["author"] in known:
            return w["author"] in shown
        return not groups and not roles

    works = [
        w
        for w in data["works"]
        if author_shown(w)
        and (not view["kinds"] or w["kind"] in view["kinds"])
        and start <= w["year"] <= end
    ]
    return {"people": len(people), "works": len(works)}


class MapViews:
    """Проверка черновика вида карты: оставляет только то, что есть на карте раздела и в
    реестре, и ослабляет фильтры, если карта вышла пустой. Модель не вызывается."""

    def __init__(self, section_map: SectionMap) -> None:
        self.section_map = section_map

    def _label(self, entity_id: str) -> str:
        try:
            return self.section_map.statements.entities.label(entity_id)
        except EntityNotFound:  # неизвестный id: подписью остаётся он сам
            return entity_id

    def options(
        self, entity_ids: list[str], textbook: str | None = None, only_textbook: bool = False
    ) -> dict[str, Any]:
        """Что ассистент может выбрать: сущности вопроса, которые есть на карте (с датами и
        разделом), коды фильтров, встречающиеся на карте, и пределы раздела."""
        data = self.section_map.build(textbook=textbook, only_textbook=only_textbook)
        placed: dict[str, dict[str, Any]] = {}
        for p in data["people"]:
            placed[p["id"]] = {"kind": "person", "from": p["birth"], "to": p["death"]}
        for w in data["works"]:
            placed[w["id"]] = {"kind": w["kind"], "from": w["year"], "to": w["year"]}
        for e in data["events"]:
            placed[e["id"]] = {"kind": "event", "from": e["year"], "to": e["year"]}
        for e in data["eras"]:
            placed[e["id"]] = {"kind": "era", "from": e["from"], "to": e["to"]}
        for g in data["groups"]:
            if g["kind"] in FILTER_GROUP_KINDS:
                people = {p["id"]: p for p in data["people"]}
                years = [
                    y
                    for m in g["members"]
                    if m in people
                    for y in (people[m]["birth"], people[m]["death"])
                ]
                placed[g["id"]] = {
                    "kind": "group",
                    "from": min(years) if years else None,
                    "to": max(years) if years else None,
                }
        candidates = []
        for entity_id in dict.fromkeys(entity_ids):
            if entity_id in placed:
                candidates.append(
                    {"id": entity_id, "label": self._label(entity_id), **placed[entity_id]}
                )
        return {
            "candidates": candidates,
            "range": data["range"],
            "codes": {
                "roles": sorted({r for p in data["people"] for r in p["roles"]}),
                "kinds": [k for k in WORK_KINDS if any(w["kind"] == k for w in data["works"])],
                "ekinds": sorted({e["kind"] for e in data["events"] if e.get("kind")}),
            },
        }

    def normalize(
        self, draft: dict[str, Any], textbook: str | None = None, only_textbook: bool = False
    ) -> dict[str, Any]:
        data = self.section_map.build(textbook=textbook, only_textbook=only_textbook)
        dropped: list[dict[str, Any]] = []

        def drop(field: str, value: Any, reason: str) -> None:
            item: dict[str, Any] = {"field": field, "value": value, "reason": reason}
            if field in ("sel", "groups"):
                item["label"] = self._label(value)
            dropped.append(item)

        on_map = {
            item["id"]
            for section in ("people", "works", "events", "eras", "groups")
            for item in data[section]
        }
        groups_on_map = {g["id"] for g in data["groups"] if g["kind"] in FILTER_GROUP_KINDS}
        codes = {
            "roles": {r for p in data["people"] for r in p["roles"]},
            "kinds": {w["kind"] for w in data["works"]},
            "ekinds": {e["kind"] for e in data["events"] if e.get("kind")},
        }
        view: dict[str, Any] = {"sel": None, "from": None, "to": None, "verified": False}

        sel = draft.get("sel")
        if isinstance(sel, str) and sel:
            if sel in on_map:
                view["sel"] = sel
            else:
                drop("sel", sel, "not_on_map")

        def strings(value: Any) -> list[str]:
            if not isinstance(value, list):
                return []
            return list(dict.fromkeys(v for v in value if isinstance(v, str) and v))

        view["groups"] = []
        for g in strings(draft.get("groups")):
            if g in groups_on_map:
                view["groups"].append(g)
            else:
                drop("groups", g, "not_on_map")
        for key in ("roles", "kinds", "ekinds"):
            view[key] = []
            for code in strings(draft.get(key)):
                if code in codes[key]:
                    view[key].append(code)
                else:
                    drop(key, code, "unknown_code")

        lo, hi = data["range"] or (None, None)

        def year(value: Any) -> int | None:
            return value if isinstance(value, int) and not isinstance(value, bool) else None

        start, end = year(draft.get("from")), year(draft.get("to"))
        if lo is not None:
            # Граница на краю раздела или за ним ничего не ограничивает — как на клиенте.
            if start is not None and start <= lo:
                start = None
            if end is not None and end >= hi:
                end = None
            if start is not None and start >= hi:
                drop("from", start, "out_of_range")
                start = None
            if end is not None and end <= lo:
                drop("to", end, "out_of_range")
                end = None
            if start is not None and end is not None and start >= end:
                drop("from", start, "out_of_range")
                drop("to", end, "out_of_range")
                start = end = None
        else:
            start = end = None
        view["from"], view["to"] = start, end
        view["verified"] = draft.get("verified") is True

        lens = [k for k in STRATA if k in strings(draft.get("lens"))]
        if len(lens) >= len(STRATA):
            for k in lens:
                drop("lens", k, "all_strata")
            lens = []
        view["lens"] = lens

        # Пустая карта: фильтры снимаются по одному, пока не появится хоть кто-то.
        relaxed: list[str] = []
        base = visible_counts(
            data, {**view, **{k: [] for k in LIST_FIELDS}, "from": None, "to": None}
        )
        shown = visible_counts(data, view)
        if base["people"] + base["works"] > 0:
            for step in RELAX_ORDER:
                if shown["people"] + shown["works"] > 0:
                    break
                if step == "years":
                    for key in ("from", "to"):
                        if view[key] is not None:
                            drop(key, view[key], "empty_result")
                            view[key] = None
                            relaxed.append(key)
                else:
                    for value in view[step]:
                        drop(step, value, "empty_result")
                    if view[step]:
                        relaxed.append(step)
                    view[step] = []
                shown = visible_counts(data, view)
        reasons: dict[str, int] = defaultdict(int)
        for item in dropped:
            reasons[item["reason"]] += 1
        events.emit(
            "knowledge.map_view.normalized",
            dropped=dict(reasons),
            shown=shown,
            relaxed=relaxed,
        )
        return {"view": view, "href": map_href(view), "dropped": dropped, "shown": shown}
