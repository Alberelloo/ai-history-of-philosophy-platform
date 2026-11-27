"""Карточки сущностей (ontology.md, раздел 11.1).

Каждая строка карточки — утверждение, поэтому у каждой видны атрибуция, подтверждающий абзац
и природа знания: проверено, по источникам или сгенерировано. Пустые разделы не показываются.
Описание модель пишет только если его нет, генерация включена и модель доступна; написанное
сохраняется со статусом «сгенерировано» и второй раз не запрашивается.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from philograph.knowledge.entities import EntityNotFound
from philograph.knowledge.graph import (
    attribution_label,
    attribution_link,
    hidden_by_region,
    recipes_for,
)
from philograph.knowledge.mentions import Mentions
from philograph.knowledge.polities import PolitiesUnavailable, PolityLayer
from philograph.knowledge.portraits import Portraits
from philograph.knowledge.statements import STRENGTH, Attribution, Provenance, Statements
from philograph.platform import events
from philograph.platform.client import ServiceClient, ServiceUnavailable

events.define(
    "knowledge.card.served",
    "info",
    "Отдана карточка сущности",
    required=("entity_id", "type", "sections", "rows", "layout", "empty", "inferred", "polity"),
)
events.define(
    "knowledge.card.description", "info", "Описание карточки", required=("entity_id", "result")
)

INFLUENCE_FAMILY = "influenced_by"
# Отметка строки — единая шкала карточки (redesign-entity-cards): сила для выбора строки и
# порядка; «спорное» слабее всех.
MARK_ORDER = ("verified", "sourced", "generated", "disputed")
MARK_RANK = {"verified": 4, "sourced": 3, "generated": 2, "disputed": 1}
# Сколько трудов просматривает вывод (интересы, «к кому относится»): стоимость постоянна.
INFER_SCAN = 30
VIA_LIMIT = 3
# Основное место персоны: роль места по убыванию веса (``place_role`` у ``lived_in``).
PLACE_ROLE_RANK = {"activity": 4, "residence": 3, "birth": 2, "death": 1}
INTEREST_TYPES = ("concept", "problem")
# Не показываются строками ни в одном разделе: годы и роль — в шапке персоны, координаты —
# в поле ``geo``, описание — отдельным полем.
NOT_ROWS = frozenset({"description", "lifespan", "person_role", "coordinates"})


@dataclass(frozen=True)
class Section:
    """Раздел карточки — данные: связи, направление (out | in | both), вид показа
    (facts | list | inline), сколько строк видно, одна строка на сущность, вывод."""

    code: str
    title: str
    relations: tuple[str, ...] = ()
    direction: str = "out"
    display: str = "list"
    visible: int | None = 5
    dedupe: bool = False
    derive: str | None = None  # interests | relates_to
    exclude: tuple[str, ...] = ()
    only: tuple[str, ...] = ()  # только для этих типов сущности (идейное событие)


@dataclass(frozen=True)
class Template:
    layout: str  # person | entity | epoch
    sections: tuple[Section, ...]
    where: bool = True  # «Где читать»
    other: bool = True  # «Другие связи»


def _s(code, title, relations=(), direction="out", display="list", visible=5, **kw) -> Section:
    return Section(code, title, tuple(relations), direction, display, visible, **kw)


# «Исторический контекст»: события и явления, которые стимулировали сущность (epoch-context).
CONTEXT = _s("context", "Исторический контекст", ["stimulated"], "in", visible=None)
EPOCH = _s("epoch", "Эпоха", ["belongs_to_epoch"], "out", "inline", None)
OTHER = _s("other", "Другие связи", visible=5)
IN_WORKS = _s("in_works", "В трудах", ["discusses"], "in")
RELATES_TO = _s(
    "relates_to",
    "К кому относится",
    ["holds", "advanced"],
    "in",
    "inline",
    5,
    dedupe=True,
    derive="relates_to",
)

IDEA = Template(
    "entity",
    (
        _s("facts", "Сведения", ["part_of", "conception_of"], "out", "facts", None),
        RELATES_TO,
        _s("parts", "Состав", ["part_of"], "in"),
        _s("answers", "Ответы", ["answers"], "both"),
        _s("arguments", "Аргументы за и против", ["supports", "attacks"], "in"),
        _s("in_works", "В трудах", ["expresses", "discusses"], "in"),
        _s("influence", "Влияния", [INFLUENCE_FAMILY], "both"),
        EPOCH,
        CONTEXT,
    ),
)
EVENT = Template(
    "entity",
    (
        _s("when", "Дата и место", ["event_kind", "dating", "happened_in"], "out", "facts", None),
        _s("participants", "Участники", ["participated"], "in", "inline", 6),
        _s(
            "genesis",
            "Как возникло",
            ["source_material", "result", "in_work", "circumstance"],
            only=("idea_event",),
        ),
        _s("effects", "На что повлияло", ["stimulated"], "out"),
        EPOCH,
    ),
)

# Разделы по типам (redesign-entity-cards, design.md «Разделы по типам»).
TEMPLATES: dict[str, Template] = {
    "person": Template(
        "person",
        (
            _s("places", "Где жил", ["lived_in"], "out", "inline", 3, dedupe=True),
            _s(
                "influenced_by",
                "Повлияли",
                [INFLUENCE_FAMILY],
                "out",
                dedupe=True,
                exclude=("studied_with",),
            ),
            _s(
                "influenced",
                "Повлиял на",
                [INFLUENCE_FAMILY],
                "in",
                dedupe=True,
                exclude=("studied_with",),
            ),
            _s("teachers", "Учителя и ученики", ["studied_with"], "both", dedupe=True),
            _s("schools", "Школа и направление", ["member_of", "founded"], "out", "inline", None),
            _s("positions", "Учения", ["holds", "advanced"], "out"),
            _s("interests", "Интересы", (), "out", "inline", 6, derive="interests"),
            _s("works", "Труды", ["author"], "in", "list", 6, dedupe=True),
            _s("biography", "Биография", ["participated", "worked_at"], "out"),
            EPOCH,
            CONTEXT,
        ),
        where=False,
    ),
    "concept": Template(
        "entity",
        (
            _s("definitions", "Определения", ["definition"], "out", visible=3),
            RELATES_TO,
            _s("words", "Термины", ["denotes"], "in", "inline", None),
            _s("conceptions", "История: концепции", ["conception_of"], "in"),
            _s(
                "related",
                "Связанные понятия",
                ["narrower", "opposed_to", "similar_to", "presupposes"],
                "both",
            ),
            _s("problems", "Проблемы", ["answers", "part_of"], "both"),
            IN_WORKS,
            EPOCH,
            CONTEXT,
        ),
    ),
    "term": Template(
        "entity",
        (
            _s(
                "facts",
                "Сведения",
                ["denotes", "introduced_by", "derives_from"],
                "out",
                "facts",
                None,
            ),
            _s("translations", "Переводы", ["translated_as"], "both", "inline", None),
            IN_WORKS,
            EPOCH,
        ),
    ),
    "work": Template(
        "entity",
        (
            _s("facts", "Сведения", ["author", "dating", "work_part_of"], "out", "facts", None),
            _s("topics", "Вопросы и сферы", ["discusses", "expresses"], "out", "inline", 8),
            _s("cites", "Ссылается на", ["cites"], "both"),
            _s("response", "Ответы и отклики", ["written_in_response"], "both"),
            _s(
                "influence",
                "Влияния",
                [INFLUENCE_FAMILY],
                "both",
                exclude=("written_in_response",),
            ),
            _s("parts", "Состав", ["work_part_of"], "in"),
            EPOCH,
            CONTEXT,
        ),
    ),
    "group": Template(
        "entity",
        (
            _s("facts", "Сведения", ["group_kind"], "out", "facts", None),
            _s("membership", "Состав", ["member_of"], "in", "inline", 8),
            _s("founders", "Основатели", ["founded"], "in", "inline", None),
            _s("positions", "Учения", ["holds"], "out"),
            _s("debated", "Полемика", ["debated"], "both"),
            _s("staff", "Работали", ["worked_at"], "in", "inline", 6),
            EPOCH,
            CONTEXT,
        ),
    ),
    "place": Template(
        "entity",
        (
            _s("residents", "Жили здесь", ["lived_in"], "in", "inline", 8),
            _s("events", "Что произошло", ["happened_in"], "in"),
        ),
    ),
    # Эпоха: только явные утверждения; принадлежность по датам — вывод (О-8), её показывают
    # страница эпох и справочник. Код ``dating``, а не ``when``: ``when`` — «Дата и место».
    "epoch": Template(
        "epoch",
        (
            _s("dating", "Датировка", ["dating"], "out", visible=None),
            _s("members", "Относятся к эпохе", ["belongs_to_epoch"], "in", visible=None),
        ),
        other=False,
    ),
    "doctrine": IDEA,
    "event": EVENT,
}
for _type in ("problem", "position", "argument", "conception"):
    TEMPLATES[_type] = IDEA
TEMPLATES["phenomenon"] = EVENT
TEMPLATES["idea_event"] = EVENT
DEFAULT_TEMPLATE = Template("entity", (EPOCH,))
# Раздел «что часто путают» собирается отдельно (_misconceptions).
MISCONCEPTIONS_TITLE = "Часто считают, но…"
# Код раздела → заголовок по типам (одно название на код: переводы на клиенте — по коду).
SECTIONS: dict[str, list[tuple[str, str, tuple[str, ...], str]]] = {
    code: [
        (x.code, x.title, x.relations, x.direction)
        for x in (*t.sections, *((OTHER,) if t.other else ()))
    ]
    for code, t in TEMPLATES.items()
}


def mark_of(status: str, consensus: str | None) -> str:
    """Отметка строки по единой шкале: «спорное» важнее статуса."""
    return "disputed" if consensus == "disputed" else status


def _weakest(chain: list[dict[str, Any]]) -> tuple[str, str]:
    """Статус и согласие цепочки утверждений — по самому слабому звену."""
    status = min((s["status"] for s in chain), key=lambda x: STRENGTH.get(x, 0))
    disputed = any(s.get("consensus") == "disputed" for s in chain)
    consensus = "disputed" if disputed else (chain[-1].get("consensus") or "single")
    return status, consensus


def _birth_year(dates: dict[str, Any] | None) -> int | None:
    if not dates:
        return None
    lo, hi = dates.get("earliest_start"), dates.get("latest_start")
    if lo is None and hi is None:
        return None
    if lo is None or hi is None:
        return lo if hi is None else hi
    return (lo + hi) // 2


class Cards:
    def __init__(
        self,
        statements: Statements,
        mentions: Mentions | None = None,
        llm: ServiceClient | None = None,
        on_view=None,
        *,
        portraits: Portraits | None = None,
        polities: PolityLayer | None = None,
    ) -> None:
        self.statements = statements
        self.entities = statements.entities
        self.registry = statements.registry
        self.mentions = mentions
        self.llm = llm
        self.on_view = on_view  # приоритет очереди проверки: что чаще видят читатели
        self.portraits = portraits
        self.polities = polities

    def _row(
        self,
        s: dict[str, Any],
        entity_id: str,
        textbook: str | None = None,
        closed: frozenset[str] = frozenset(),
    ) -> dict[str, Any]:
        spec = self.registry.relation(s["type"])
        outward = s["subject"] == entity_id
        other = s["object"] if outward else s["subject"]
        visible = [
            a for a in s["attributions"] if not a["hidden"] and not hidden_by_region(a, closed)
        ]
        who = list(dict.fromkeys(attribution_label(self.statements, a) for a in visible))
        disputers = [
            attribution_label(self.statements, a) for a in visible if a["stance"] == "disputes"
        ]
        return {
            "statement_id": s["id"],
            "type": s["type"],
            "relation": spec["title"]
            if outward or spec.get("symmetric")
            else spec.get("inverse_title") or spec["title"],
            # Коды для перевода на клиенте: связь читается от другого конца (обратная подпись).
            "inverse": not outward and not spec.get("symmetric"),
            "entity_id": other,
            "label": self.entities.label(other) if other else None,
            "value": s.get("value"),
            # Уточнители (механизм «стимулировало» и др.) — проверены реестром при записи.
            "qualifiers": dict(s.get("qualifiers") or {}),
            "status": s["status"],
            "consensus": s["consensus"],
            "disputed": s["consensus"] == "disputed",
            "disputed_by": disputers,
            "generated": s["status"] == "generated",
            "derived": s.get("derived", False),
            # Есть ли строка в выбранном учебнике: для сравнения «как у меня и у других».
            "in_textbook": self.statements._attributed(s, textbook) if textbook else None,
            "attributed_to": who,
            "attributions": [
                {
                    "who": attribution_label(self.statements, a),
                    "kind": a["who_kind"],
                    "stance": a["stance"],
                    # Ссылка — только у Wikidata и только из проверенного QID.
                    **({"link": link} if (link := attribution_link(a)) else {}),
                }
                for a in visible
            ],
            "evidence": [
                {
                    "paragraph_id": e["paragraph_id"],
                    "quote": e["quote"],
                    "link": f"/p/{e['paragraph_id']}",
                }
                for e in s["evidence"]
                if not e["lost"] and e["source_id"] not in closed
            ],
            "mark": mark_of(s["status"], s["consensus"]),
            "inferred": False,
            "via": [],
            "note": None,
            "geo": None,
            "also": [],
        }

    def _inferred_row(
        self,
        code: str,
        entity_id: str,
        type_: str,
        inverse: bool,
        chain: list[dict[str, Any]],
        via: list[str],
    ) -> dict[str, Any]:
        """Выведенная строка: полная строка карточки, отметка — по самому слабому звену."""
        spec = self.registry.relation(type_)
        status, consensus = _weakest(chain)
        return {
            "statement_id": f"inferred:{code}:{entity_id}",
            "type": type_,
            "relation": spec.get("inverse_title") or spec["title"] if inverse else spec["title"],
            "inverse": inverse,
            "entity_id": entity_id,
            "label": self.entities.label(entity_id),
            "value": None,
            "qualifiers": {},
            "status": status,
            "consensus": consensus,
            "disputed": consensus == "disputed",
            "disputed_by": [],
            "generated": status == "generated",
            "derived": True,  # не утверждение: в очередь проверки не идёт
            "in_textbook": None,
            "attributed_to": [],
            "attributions": [],
            "evidence": [],
            "mark": mark_of(status, consensus),
            "inferred": True,
            "via": [{"entity_id": v, "label": self.entities.label(v)} for v in via[:VIA_LIMIT]],
            "note": None,
            "geo": None,
            "also": [],
        }

    @staticmethod
    def _strength(row: dict[str, Any]) -> tuple[int, int]:
        return MARK_RANK.get(row["mark"], 0), len(row["evidence"])

    def _dedupe(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Одна строка на сущность: остаётся самая сильная, прочие — в ``also``."""
        best: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        result: list[dict[str, Any]] = []
        for row in rows:
            key = row["entity_id"]
            if key is None:
                result.append(row)
                continue
            if key not in best:
                best[key] = row
                order.append(key)
                continue
            keep, drop = best[key], row
            if self._strength(row) > self._strength(keep):
                keep, drop = row, keep
            keep["also"] = [*keep["also"], drop["statement_id"], *drop["also"]]
            drop["also"] = []
            best[key] = keep
        return [best[k] for k in order] + result

    def _matches(self, section: Section, s: dict[str, Any]) -> bool:
        if s["type"] in section.exclude:
            return False
        if not any(s["type"] in self.registry.relation_subtypes(x) for x in section.relations):
            return False
        return (
            section.direction == "both"
            or (section.direction == "out") == (s["direction"] == "out")
            or bool(self.registry.relation(s["type"]).get("symmetric"))
        )

    def _coordinates(self, place_id: str) -> dict[str, float] | None:
        for s in self.statements.about(place_id, types=["coordinates"], derived=False):
            v = s.get("value")
            if s["direction"] == "out" and isinstance(v, dict) and "lat" in v and "lon" in v:
                return {"lat": v["lat"], "lon": v["lon"]}
        return None

    def _work_facts(self, work_id: str, attributed_to: str | None) -> list[dict[str, Any]]:
        # Звенья вывода в режиме «только выбранный учебник» проходят тот же фильтр
        # атрибуции, что и утверждения о самой сущности (source-scope).
        return self.statements.about(work_id, attributed_to=attributed_to, derived=False)

    def card(
        self,
        entity_id: str,
        *,
        attributed_to: str | None = None,
        generation: bool = True,
        textbook: str | None = None,
        closed: frozenset[str] = frozenset(),
    ) -> dict[str, Any]:
        """``attributed_to`` — режим «только выбранный учебник», ``textbook`` — пометка строк,
        которые есть в выбранном учебнике, в режиме «все источники»."""
        entity = self.entities.get(entity_id)
        if "retired" in entity:  # снятая миграцией — как неизвестная (404)
            raise EntityNotFound(entity_id)
        entity_id = entity["id"]  # перенаправление слитой сущности
        etype = entity["type"]
        template = TEMPLATES.get(etype, DEFAULT_TEMPLATE)
        statements = self.statements.about(entity_id, attributed_to=attributed_to)
        works_cache: dict[str, list[dict[str, Any]]] = {}

        def work_statements(work_id: str) -> list[dict[str, Any]]:
            if work_id not in works_cache:
                works_cache[work_id] = self._work_facts(work_id, attributed_to)
            return works_cache[work_id]

        used: set[str] = set()
        built: dict[str, list[dict[str, Any]]] = {}
        sections = []
        for section in template.sections:
            if section.only and etype not in section.only:
                continue
            chosen = [
                s
                for s in statements
                if s["id"] not in used and s["type"] not in NOT_ROWS and self._matches(section, s)
            ]
            used |= {s["id"] for s in chosen}
            rows = [self._row(s, entity_id, textbook, closed) for s in chosen]
            if section.code == "places":
                for r in rows:
                    r["geo"] = self._coordinates(r["entity_id"]) if r["entity_id"] else None
                rows.sort(key=self._place_key, reverse=True)
            if section.code == "works":
                for r in rows:
                    r["note"] = self._work_year(work_statements(r["entity_id"]))
            if section.dedupe:
                rows = self._dedupe(rows)
            if section.display == "facts":
                rows.sort(key=lambda r: self._relation_index(section, r["type"]))
            elif section.code != "places":  # места — по правилу основного места
                rows.sort(key=lambda r: -MARK_RANK.get(r["mark"], 0))
            if section.derive == "relates_to":
                rows += self._relates_to(
                    entity_id, etype, statements, rows, work_statements, attributed_to
                )
            elif section.derive == "interests":
                rows = self._interests(built, statements, work_statements)
            built[section.code] = rows
            if rows:  # пустой раздел не показывается заголовком
                sections.append(self._section(section, rows))
        if template.other:
            leftover = [
                s
                for s in statements
                if s["id"] not in used and s["type"] not in NOT_ROWS and not s.get("derived")
            ]
            if leftover:
                rows = [self._row(s, entity_id, textbook, closed) for s in leftover]
                sections.append(self._section(OTHER, rows))
        description = next(
            (s for s in statements if s["type"] == "description" and s["direction"] == "out"), None
        )
        myths = self._misconceptions(entity_id, closed)
        if myths:
            sections.append(
                {
                    "code": "misconceptions",
                    "title": MISCONCEPTIONS_TITLE,
                    "rows": myths,
                    "display": "list",
                    "visible": None,
                    "total": len(myths),
                    "inferred": False,
                }
            )
        summary, polity = None, "skipped"
        if template.layout == "person":
            summary, polity = self._summary(entity, statements, built.get("places", []), closed)
        geo = self._coordinates(entity_id) if etype == "place" else None
        rows_all = [r for s in sections for r in s["rows"]]
        shown = [x for r in rows_all if not r["derived"] for x in (r["statement_id"], *r["also"])]
        if self.on_view and shown:
            self.on_view(shown)
        description_row = self._row(description, entity_id, closed=closed) if description else None
        marks = {r["mark"] for r in rows_all}
        if summary:
            marks |= {r["mark"] for r in summary["roles"]}
            if summary["place"]:
                marks.add(summary["place"]["mark"])
            if summary["years_row"]:
                marks.add(summary["years_row"]["mark"])
        if description_row and description_row["generated"]:
            marks.add("generated")
        summary_filled = bool(
            summary and (summary["roles"] or summary["place"] or summary["years"])
        )
        # Координаты места — тоже сведения: по ним клиент показывает страну в инфобоксе.
        empty = not rows_all and description_row is None and not summary_filled and geo is None
        where = (
            self.mentions.where_to_read(entity_id, closed)
            if self.mentions and template.where
            else []
        )
        result = {
            "id": entity_id,
            "type": etype,
            "title": self.entities.label(entity_id),
            "names": entity["names"],
            "dates": entity["primary"].get("dates"),
            # Портреты — только подтверждённые и видимые; для не-персон их нет по определению.
            "portraits": self.portraits.visible(entity_id)
            if self.portraits is not None and etype == "person"
            else [],
            "description": description_row,
            "description_pending": description is None
            and generation
            and self.llm is not None
            and attributed_to is None,
            "sections": sections,
            "where_to_read": where[:10],
            "recipes": recipes_for(self.registry, etype),
            "layout": template.layout,
            "summary": summary,
            "geo": geo,
            "legend": [m for m in MARK_ORDER if m in marks],
            "empty": empty,
        }
        events.emit(
            "knowledge.card.served",
            entity_id=entity_id,
            type=etype,
            sections=len(sections),
            rows=len(rows_all),
            layout=template.layout,
            empty=empty,
            inferred=sum(1 for r in rows_all if r["inferred"]),
            polity=polity,
        )
        return result

    @staticmethod
    def _section(section: Section, rows: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "code": section.code,
            "title": section.title,
            "rows": rows,
            "display": section.display,
            "visible": section.visible,
            "total": len(rows),
            "inferred": any(r["inferred"] for r in rows),
        }

    def _relation_index(self, section: Section, type_: str) -> int:
        for i, base in enumerate(section.relations):
            if type_ in self.registry.relation_subtypes(base):
                return i
        return len(section.relations)

    @staticmethod
    def _place_key(row: dict[str, Any]) -> tuple[int, int, int]:
        role = (row.get("qualifiers") or {}).get("place_role")
        return (PLACE_ROLE_RANK.get(role, 0), *Cards._strength(row))

    @staticmethod
    def _work_year(work: list[dict[str, Any]]) -> str | None:
        for s in work:
            if s["type"] == "dating" and s["direction"] == "out":
                v = s.get("value")
                if isinstance(v, dict) and v.get("original"):
                    return str(v["original"])
                return str(v) if v else None
        return None

    def _summary(
        self,
        entity: dict[str, Any],
        statements: list[dict[str, Any]],
        places: list[dict[str, Any]],
        closed: frozenset[str],
    ) -> tuple[dict[str, Any], str]:
        """Сводка персоны: роли, основное место (первое в «Где жил»), годы, образование."""
        roles = [
            self._row(s, entity["id"], closed=closed)
            for s in statements
            if s["type"] == "person_role" and s["direction"] == "out"
        ]
        dates = entity["primary"].get("dates")
        years_row = self._years_row(entity["id"], statements, dates, closed)
        place = places[0] if places else None
        polity, outcome = None, "skipped"
        year = _birth_year(dates)
        if place and place["geo"] and year is not None and self.polities is not None:
            try:
                found = self.polities.at(place["geo"]["lat"], place["geo"]["lon"], year)
            except PolitiesUnavailable:
                outcome = "unavailable"
            else:
                outcome = "found" if found else "none"
                if found:
                    polity = {
                        "name": found["name"],
                        "name_status": found["name_status"],
                        "year": year,
                    }
        elif place and place["geo"] and year is not None:
            outcome = "unavailable"
        summary = {
            "roles": roles,
            "place": place,
            "years": dates.get("original") if dates else None,
            # Отметка годов — строка утверждения ``lifespan`` (та же шкала, что у ролей и места);
            # ``None``, если годы есть только в записи сущности без видимого утверждения.
            "years_row": years_row if dates else None,
            "polity": polity,
        }
        return summary, outcome

    def _years_row(
        self,
        entity_id: str,
        statements: list[dict[str, Any]],
        dates: dict[str, Any] | None,
        closed: frozenset[str],
    ) -> dict[str, Any] | None:
        """Строка утверждения ``lifespan`` для годов сводки: та, чьё значение совпадает с
        показанными годами, иначе самая сильная по отметке."""
        rows = [
            self._row(s, entity_id, closed=closed)
            for s in statements
            if s["type"] == "lifespan" and s["direction"] == "out"
        ]
        if not rows:
            return None
        shown = dates.get("original") if dates else None
        same = [
            r for r in rows if isinstance(r["value"], dict) and r["value"].get("original") == shown
        ]
        return max(same or rows, key=self._strength)

    def _interests(
        self,
        built: dict[str, list[dict[str, Any]]],
        statements: list[dict[str, Any]],
        work_statements,
    ) -> list[dict[str, Any]]:
        """Интересы персоны: понятия и проблемы, которые рассматривают её труды (вывод)."""
        authored = [s for s in statements if s["type"] == "author" and s["direction"] == "in"]
        skip = {r["entity_id"] for r in built.get("positions", [])}
        found: dict[str, list[tuple[list[dict[str, Any]], str]]] = {}
        for link in authored[:INFER_SCAN]:
            work = link["subject"]
            topics = [
                s
                for s in work_statements(work)
                if s["type"] in ("discusses", "expresses") and s["direction"] == "out"
            ]
            types = self.entities.types([s["object"] for s in topics if s["object"]])
            for s in topics:
                target = s["object"]
                if types.get(target) in INTEREST_TYPES and target not in skip:
                    found.setdefault(target, []).append(([link, s], work))
        return self._ranked("interests", found, inverse=False)

    def _ranked(
        self,
        code: str,
        found: dict[str, list[tuple[list[dict[str, Any]], str]]],
        inverse: bool,
    ) -> list[dict[str, Any]]:
        """Строка на сущность по лучшей цепочке; порядок — по числу оснований, затем по
        названию."""
        rows = []
        for target, chains in found.items():
            chains = sorted(chains, key=lambda c: -MARK_RANK[mark_of(*_weakest(c[0]))])
            vias = list(dict.fromkeys(work for _, work in chains))
            best = chains[0][0]
            row = self._inferred_row(code, target, best[-1]["type"], inverse, best, vias)
            rows.append((-len(vias), row["label"], row))
        rows.sort(key=lambda x: x[:2])
        return [r for *_, r in rows]

    def _relates_to(
        self,
        entity_id: str,
        etype: str,
        statements: list[dict[str, Any]],
        direct: list[dict[str, Any]],
        work_statements,
        attributed_to: str | None = None,
    ) -> list[dict[str, Any]]:
        """«К кому относится»: авторы трудов об идее и персоны через термин (вывод)."""
        have = {r["entity_id"] for r in direct}
        found: dict[str, list[tuple[list[dict[str, Any]], str]]] = {}
        works = [
            s
            for s in statements
            if s["type"] in ("discusses", "expresses") and s["direction"] == "in"
        ]
        for link in works[:INFER_SCAN]:
            for a in work_statements(link["subject"]):
                if a["type"] == "author" and a["direction"] == "out" and a["object"] not in have:
                    found.setdefault(a["object"], []).append(([link, a], link["subject"]))
        rows = self._ranked("relates_to", found, inverse=False)
        if etype == "concept":
            terms: dict[str, list[tuple[list[dict[str, Any]], str]]] = {}
            for link in [s for s in statements if s["type"] == "denotes"][:INFER_SCAN]:
                if link["direction"] != "in":
                    continue
                for a in self.statements.about(
                    link["subject"],
                    types=["introduced_by"],
                    attributed_to=attributed_to,
                    derived=False,
                ):
                    who = a["object"]
                    if a["direction"] == "out" and who not in have and who not in found:
                        terms.setdefault(who, []).append(([link, a], link["subject"]))
            rows += self._ranked("relates_to", terms, inverse=True)
        return rows

    def _misconceptions(
        self, entity_id: str, closed: frozenset[str] = frozenset()
    ) -> list[dict[str, Any]]:
        """Отвергнутые утверждения с атрибуцией «распространённое мнение»."""
        rows = []
        for s in self.statements.about(entity_id, include_deprecated=True, derived=False):
            if s["rank"] != "deprecated":
                continue
            if any(
                a["who_kind"] == "common" and a["stance"] == "asserts" for a in s["attributions"]
            ):
                rows.append(self._row(s, entity_id, closed=closed))
        return rows

    def describe(self, entity_id: str, *, generation: bool = True) -> Iterator[dict[str, Any]]:
        """Поток описания от модели; сохранённое описание отдаётся без вызова модели."""
        entity_id = self.entities.resolve(entity_id)
        existing = next(
            (
                s
                for s in self.statements.about(entity_id, derived=False)
                if s["type"] == "description" and s["direction"] == "out"
            ),
            None,
        )
        if existing is not None:
            events.emit("knowledge.card.description", entity_id=entity_id, result="stored")
            yield {
                "type": "done",
                "text": existing["value"],
                "generated": existing["status"] == "generated",
            }
            return
        if not generation or self.llm is None:
            events.emit("knowledge.card.description", entity_id=entity_id, result="disabled")
            yield {"type": "unavailable", "reason": "generation_disabled"}
            return
        entity = self.entities.get(entity_id)
        body = {
            "role": "main",
            "template": "card.description",
            "caller": "knowledge",
            "operation": "card_description",
            "budget": "site",
            "data": {"name": self.entities.label(entity_id), "type": entity["type"]},
        }
        text = ""
        try:
            with self.llm.stream("POST", "stream", json=body) as response:
                if response.status_code != 200:
                    response.read()
                    reason = response.json().get("kind", "error")
                    events.emit("knowledge.card.description", entity_id=entity_id, result=reason)
                    yield {"type": "unavailable", "reason": reason}
                    return
                for line in response.iter_lines():
                    if not line.strip():
                        continue
                    item = json.loads(line)
                    if item["type"] == "delta":
                        text += item["text"]
                        yield {"type": "delta", "text": item["text"]}
                    elif item["type"] == "error":
                        yield {"type": "unavailable", "reason": "stream_broken"}
                        return
        except ServiceUnavailable:
            events.emit("knowledge.card.description", entity_id=entity_id, result="unavailable")
            yield {"type": "unavailable", "reason": "llm_unavailable"}
            return
        self.statements.add(
            entity_id,
            "description",
            value=text.strip(),
            attributions=[Attribution("common", stance="mentions")],
            provenance=Provenance("generated", model="main", template="card.description"),
        )
        events.emit("knowledge.card.description", entity_id=entity_id, result="generated")
        yield {"type": "done", "text": text.strip(), "generated": True}
