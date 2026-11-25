"""Слияние вариантов персоны (спецификация person-quality, «Слияние вариантов персоны»).

Одно правило тождества ``same_person`` — для извлечения, очереди и миграции. Пары-кандидаты
находятся по индексу нормализованных названий (без перебора всех пар); рёбра ``merge:*``
собираются в связные компоненты, компонента с разными QID, решением «разные» или
противоречащими датами целиком уходит в очередь проверки. Итог зависит только от множества
входа, а не от порядка.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any, Literal

from sqlalchemy import func, select

from philograph.knowledge import schema as t
from philograph.knowledge.naming import normalize
from philograph.platform import events

DATE_SLACK = 2  # допуск дат, лет, на краях интервалов неопределённости
QID = "wikidata"
PERSON = "person"

Kind = Literal["merge", "review", "apart"]
_MERGE_RANK = {"merge:qid_confirmed": 0, "merge:name": 1, "merge:model_pair": 2}


@dataclass(frozen=True)
class Verdict:
    kind: Kind
    reason: str

    @classmethod
    def of(cls, code: str) -> Verdict:
        return cls(code.split(":", 1)[0], code)  # type: ignore[arg-type]


@dataclass(frozen=True)
class Entity:
    id: str
    type: str
    names: tuple[tuple[str, str], ...]  # (вид, нормализованное)
    dates: Mapping[str, Any] | None = None
    qid: str | None = None

    @property
    def primaries(self) -> set[str]:
        return {n for kind, n in self.names if kind == "primary" and n}

    @property
    def variants(self) -> set[str]:
        return {n for kind, n in self.names if kind != "primary" and n}

    @property
    def all_names(self) -> set[str]:
        return {n for _, n in self.names if n}


@dataclass(frozen=True)
class Plan:
    merges: list[tuple[str, list[str], str]] = field(default_factory=list)  # kept, removed, reason
    review: list[tuple[str, str, str]] = field(default_factory=list)  # a, b, reason
    apart: int = 0


def _pair(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a <= b else (b, a)


def dates_conflict(a: Mapping[str, Any] | None, b: Mapping[str, Any] | None) -> bool:
    """Даты противоречат, если у обеих есть и при допуске не пересекаются интервалы начала
    или интервалы конца. Даты у одной стороны — не противоречие."""
    if not a or not b:
        return False

    def apart(lo1: int, hi1: int, lo2: int, hi2: int) -> bool:
        return hi1 + DATE_SLACK < lo2 - DATE_SLACK or hi2 + DATE_SLACK < lo1 - DATE_SLACK

    return apart(
        a["earliest_start"], a["latest_start"], b["earliest_start"], b["latest_start"]
    ) or apart(a["earliest_end"], a["latest_end"], b["earliest_end"], b["latest_end"])


def same_person(
    a: Entity,
    b: Entity,
    *,
    paired_by_model: bool = False,
    qid_confirmed: bool = False,
    decided_apart: bool = False,
) -> Verdict:
    """Вердикт по паре — шаги 1–9 правила спецификации, первый сработавший."""
    if a.type != PERSON or b.type != PERSON:
        return Verdict.of("apart:type")
    if a.qid and b.qid:
        return Verdict.of("apart:qid")
    if decided_apart:
        return Verdict.of("apart:decided")
    if dates_conflict(a.dates, b.dates):
        return Verdict.of("review:dates")
    if qid_confirmed:
        return Verdict.of("merge:qid_confirmed")
    if a.primaries & b.primaries:
        return Verdict.of("merge:name")
    if paired_by_model:
        return Verdict.of("merge:model_pair")
    shared = (a.primaries & b.variants) | (b.primaries & a.variants)
    if shared:
        one_word = any(len(n.split()) == 1 for n in shared)
        return Verdict.of("review:single_name" if one_word else "review:variant")
    return Verdict.of("apart:none")


def choose_kept(component: Iterable[Entity], counts: Mapping[str, int]) -> str:
    """Оставшаяся: с QID; иначе с большим числом ссылок; иначе с меньшим идентификатором."""
    members = sorted(component, key=lambda e: e.id)
    with_qid = [e for e in members if e.qid]
    if with_qid:
        return with_qid[0].id
    return min(members, key=lambda e: (-counts.get(e.id, 0), e.id)).id


class _Union:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            lo, hi = sorted((ra, rb))
            self.parent[hi] = lo


def candidate_pairs(entities: Iterable[Entity]) -> set[tuple[str, str]]:
    """Пары одного типа, где основное одной совпадает с любым названием другой — по индексу."""
    by_name: dict[tuple[str, str], set[str]] = defaultdict(set)
    items = list(entities)
    for e in items:
        for n in e.all_names:
            by_name[(e.type, n)].add(e.id)
    pairs = set()
    for e in items:
        for n in e.primaries:
            for other in by_name[(e.type, n)]:
                if other != e.id:
                    pairs.add(_pair(e.id, other))
    return pairs


def plan(
    entities: Iterable[Entity],
    pairs_by_model: Iterable[tuple[str, str]] = (),
    confirmed: Iterable[tuple[str, str]] = (),
    distinct: Iterable[tuple[str, str]] = (),
    counts: Mapping[str, int] | None = None,
) -> Plan:
    """Чистая функция: что слить и что поставить в очередь. Итог не зависит от порядка входа."""
    by_id = {e.id: e for e in entities}
    model = {_pair(*p) for p in pairs_by_model if p[0] in by_id and p[1] in by_id}
    sure = {_pair(*p) for p in confirmed if p[0] in by_id and p[1] in by_id}
    decided = {_pair(*p) for p in distinct}
    counts = counts or {}

    def verdict(p: tuple[str, str]) -> Verdict:
        return same_person(
            by_id[p[0]],
            by_id[p[1]],
            paired_by_model=p in model,
            qid_confirmed=p in sure,
            decided_apart=p in decided,
        )

    pairs = sorted(candidate_pairs(by_id.values()) | model | sure)
    verdicts = {p: verdict(p) for p in pairs}
    union = _Union()
    for p, v in verdicts.items():
        if v.kind == "merge":
            union.union(*p)
    components: dict[str, list[str]] = defaultdict(list)
    for x in sorted({x for p, v in verdicts.items() if v.kind == "merge" for x in p}):
        components[union.find(x)].append(x)
    merges: list[tuple[str, list[str], str]] = []
    review: dict[tuple[str, str], str] = {}
    merged_with: dict[str, str] = {}
    for members in components.values():
        inner = {p: verdicts.get(p) or verdict(p) for p in combinations(sorted(members), 2)}
        qids = {by_id[x].qid for x in members if by_id[x].qid}
        kinds = {v.reason for v in inner.values()}
        if len(qids) >= 2 or kinds & {"apart:qid", "apart:decided", "review:dates"}:
            if len(qids) >= 2 or "apart:qid" in kinds:
                reason = "review:qid_cluster"
            elif "review:dates" in kinds:
                reason = "review:dates"
            else:
                # Единственная преграда — решение «разные» по другой паре компоненты: сама
                # решённая пара в очередь не идёт, нерешённые рёбра — с собственной причиной.
                reason = "review:decided_conflict"
            for p, v in inner.items():
                if v.kind == "merge" and p not in decided:
                    review[p] = reason
            continue
        kept = choose_kept((by_id[x] for x in members), counts)
        removed = [x for x in members if x != kept]
        for x in removed:
            merged_with[x] = kept
        merged_with[kept] = kept
        edge = [inner[p].reason for p in inner if inner[p].kind == "merge" and kept in p] or sorted(
            v.reason for v in inner.values() if v.kind == "merge"
        )
        reason = min(edge, key=lambda r: _MERGE_RANK.get(r, 9))
        merges.append((kept, removed, reason))
    apart = 0
    for p, v in verdicts.items():
        if v.kind == "review" and p not in review:
            mapped = _pair(merged_with.get(p[0], p[0]), merged_with.get(p[1], p[1]))
            if mapped[0] == mapped[1] or mapped in decided:
                continue  # обе стороны слиты в одну сущность или человек решил «разные»
            review.setdefault(mapped, v.reason)
        elif v.kind == "apart":
            apart += 1
    return Plan(
        merges=sorted(merges),
        review=sorted((a, b, r) for (a, b), r in review.items()),
        apart=apart,
    )


# --- запуск по базе ---------------------------------------------------------------------


def load_persons(engine: Any, ids: Iterable[str] | None = None) -> list[Entity]:
    """Действующие персоны (или выбранные сущности) в виде входа правила."""
    with engine.begin() as conn:
        query = select(t.entities).where(t.entities.c.redirect_to.is_(None))
        if ids is None:
            query = query.where(t.entities.c.type == PERSON)
        else:
            query = query.where(t.entities.c.id.in_(list(ids)))
        rows = conn.execute(query).mappings().all()
        wanted = [r["id"] for r in rows]
        names: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for r in conn.execute(select(t.names).where(t.names.c.entity_id.in_(wanted))).mappings():
            names[r["entity_id"]].append((r["kind"], normalize(r["text"])))
        qids = dict(
            conn.execute(
                select(t.external_ids.c.entity_id, t.external_ids.c.value)
                .where(t.external_ids.c.system == QID)
                .where(t.external_ids.c.entity_id.in_(wanted))
                .order_by(t.external_ids.c.value.desc())
            ).all()
        )
    return [
        Entity(
            id=r["id"],
            type=r["type"],
            names=tuple(sorted(names.get(r["id"], []))),
            dates=r["primary"].get("dates"),
            qid=qids.get(r["id"]),
        )
        for r in rows
    ]


def link_counts(engine: Any, ids: Iterable[str]) -> dict[str, int]:
    """Ссылки на сущность: субъект и объект утверждений плюс атрибуции-автор."""
    ids = list(ids)
    counts: dict[str, int] = defaultdict(int)
    with engine.begin() as conn:
        for column in (t.statements.c.subject, t.statements.c.object):
            for entity_id, n in conn.execute(
                select(column, func.count()).where(column.in_(ids)).group_by(column)
            ):
                counts[entity_id] += n
        for entity_id, n in conn.execute(
            select(t.attributions.c.who, func.count())
            .where(t.attributions.c.who_kind == "entity")
            .where(t.attributions.c.who.in_(ids))
            .group_by(t.attributions.c.who)
        ):
            counts[entity_id] += n
    return dict(counts)


def duplicate_items(engine: Any) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    """Пары пунктов ``duplicate``: открытые и закрытые решением «разные»."""
    open_, distinct = set(), set()
    with engine.begin() as conn:
        for r in conn.execute(
            select(t.review_items).where(t.review_items.c.kind == "duplicate")
        ).mappings():
            pair = _pair(*r["payload"]["pair"])
            if r["status"] == "open":
                open_.add(pair)
            elif (r["resolution"] or {}).get("merge") is False:
                distinct.add(pair)
    return open_, distinct


def propose(engine: Any, a: str, b: str, reason: str, open_: set[tuple[str, str]]) -> bool:
    """Пункт очереди ``duplicate`` с причиной, если открытого по паре нет."""
    pair = _pair(a, b)
    if pair in open_:
        return False
    with engine.begin() as conn:
        conn.execute(
            t.review_items.insert().values(
                kind="duplicate",
                status="open",
                resolution=None,
                payload={"pair": [a, b], "reason": reason},
            )
        )
    open_.add(pair)
    events.emit("knowledge.entity.merge_proposed", kept=a, removed=b, reason=reason)
    return True


class Dedupe:
    """Запуск слияния вариантов по базе: сливает компоненты, сомнительное — в очередь."""

    def __init__(self, statements: Any, review: Any = None) -> None:
        self.statements = statements
        self.review = review
        self.engine = statements.engine

    def plan(self, confirmed: Iterable[tuple[str, str]] = ()) -> Plan:
        persons = load_persons(self.engine)
        resolve = self.statements.entities.resolve
        confirmed = [(resolve(a), resolve(b)) for a, b in confirmed]
        _, distinct = duplicate_items(self.engine)
        counts = link_counts(self.engine, [p.id for p in persons])
        return plan(persons, confirmed=confirmed, distinct=distinct, counts=counts)

    def run(
        self,
        *,
        dry_run: bool = False,
        run_id: str | None = None,
        confirmed: Iterable[tuple[str, str]] = (),
    ) -> dict[str, int]:
        result = self.plan(confirmed)
        merged = sum(len(removed) for _, removed, _ in result.merges)
        if dry_run:
            return {"merged": merged, "proposed": len(result.review), "apart": result.apart}
        for kept, removed, reason in result.merges:
            for other in removed:
                self.statements.merge_entities(kept, other, reason=reason, run_id=run_id)
        open_, _ = duplicate_items(self.engine)
        proposed = sum(propose(self.engine, a, b, r, open_) for a, b, r in result.review)
        return {"merged": merged, "proposed": proposed, "apart": result.apart}
