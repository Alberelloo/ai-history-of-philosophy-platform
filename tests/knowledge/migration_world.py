"""Мир для тестов migrate-ontology-quality (tasks.md 3.1): «старая» онтология с симптомами
П1–П4, фейковая модель перевода, поверхность API и независимые оракулы.

Оракулы (сохранность, А1–А8, ожидаемые снятия, переименования и слияния) построены из того,
как собран вход, и из спецификации ``ontology-migration``. Модули ``naming``, ``dedupe``,
``integrity``, ``quality_report`` оракулы не импортируют. Столбец ``normalized`` «старых» названий
считается по определению спецификации (``strategies.search_form``) или задаётся устаревшим
(О24: названия в NFD, с пробелами по краям и с прежним ключом поиска).
"""

from __future__ import annotations

import json
import re
import unicodedata
import uuid
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import httpx
from fastapi.testclient import TestClient
from hypothesis import strategies as hst
from sqlalchemy import delete, select

from philograph.knowledge import schema as t
from philograph.knowledge.dates import lifespan
from philograph.knowledge.statements import Attribution, Evidence, Provenance
from tests.knowledge.strategies import search_form

# --- правила из спецификаций (entity-naming, ontology-migration) --------------------------

ROMAN = re.compile(r"^[IVXLCDM]+$")


def is_ru(text: str) -> bool:
    """«Русское название» (entity-naming): есть кириллическая буква, латинских нет вне слов
    из римских цифр."""
    text = unicodedata.normalize("NFC", text)
    if not any("CYRILLIC" in unicodedata.name(ch, "") for ch in text if ch.isalpha()):
        return False
    for word in re.split(r"[^\w]+", text):
        latin = any("LATIN" in unicodedata.name(ch, "") for ch in word if ch.isalpha())
        if latin and not ROMAN.fullmatch(word):
            return False
    return True


def is_number(label: str) -> bool:
    """Причина ``number`` (entity-naming): букв нет, цифры есть."""
    label = label.strip()
    return not any(ch.isalpha() for ch in label) and any(ch.isdigit() for ch in label)


# --- пулы входа: (тип, название) → причина правила названий по спецификации ---------------

GARBAGE: dict[tuple[str, str], str] = {
    ("concept", "20.1"): "number",
    ("concept", "3.2.1"): "number",
    ("position", "12"): "number",
    ("term", ""): "empty",
    ("term", "   "): "empty",
    ("term", "Every"): "stopword",
    ("concept", "some"): "stopword",
    ("person", "your Lordship"): "not_a_name",
    ("person", "children"): "not_a_name",
    ("person", "blind mathematician"): "not_a_name",
    ("person", "Kepler and Des Cartes"): "not_a_name",
    ("person", "logicians"): "not_a_name",
    ("position", "one two three four five six seven"): "sentence",
}
GARBAGE_KEYS = tuple(GARBAGE)

# Латинские персоны с QID: подпись ru записи Wikidata и русский двойник без QID.
LATIN_QID = (
    ("Hume", "Q41568", "Юм"),
    ("Locke", "Q9353", "Локк"),
    ("Leibniz", "Q9047", "Лейбниц"),
    ("Newton", "Q935", "Ньютон"),
)
LATIN_NOQID = (("Berkeley", "Беркли"), ("Hobbes", "Гоббс"), ("Reid", "Рид"))
LATIN_CONCEPTS = (
    ("causality", "Причинность"),
    ("substance", "Субстанция"),
    ("experience", "Опыт"),
    ("space", "Пространство"),
    ("mind", "Ум"),
    ("intuition", "Интуиция"),
)
RU_PERSONS = (
    "Кант", "Декарт", "Спиноза", "Платон", "Аристотель", "Гегель", "Фихте", "Паскаль",
    "Йоганн", "Шлейермахер",  # й, ё: NFD ≠ NFC (О24)
)  # fmt: skip
RU_CONCEPTS = ("Априори", "Душа", "Материя", "Форма")
RU_POSITIONS = ("Эмпиризм", "Рационализм")
SOURCES = ("s_a", "s_b")
# Источники библиотеки: правило названий их не проверяет, А1/А2 их не считают.
SOURCE_NAMES = ("A Treatise of Human Nature", "3.1")
STANCES = ("asserts", "disputes", "mentions")
HUMAN = ("Q5",)

# Отношения реестра и допустимые концы (registry_data: IDEAS, AGENTS).
IDEA_TYPES = ("concept", "position")
RELATIONS = {
    "studied_with": (("person",), ("person",)),
    "influenced_by": (("person", "concept", "position"), ("person", "concept", "position")),
    "opposed_to": (IDEA_TYPES, IDEA_TYPES),
}


def name_form(text: str) -> str:
    """«Название» (entity-naming): ``strip()`` и NFC — форма хранения (О22, О24)."""
    return unicodedata.normalize("NFC", text.strip())


PADS = hst.sampled_from(["", " ", "  ", "\t", "\u00a0", "\u2003"])


def old_form(text: str, nfd: bool, left: str, right: str) -> tuple[str, str]:
    """«Старое» название до О22: NFD и пробелы по краям; ключ поиска прежнего правила —
    нижний регистр сырого текста (без NFC и обрезки), то есть устаревший."""
    raw = left + (unicodedata.normalize("NFD", text) if nfd else text) + right
    return raw, raw.lower()


def name_forms_broken(state) -> list[tuple[str, str]]:
    """Инвариант О24: у действующей сущности текст = strip+NFC, ``normalized`` = нормализация
    текста по определению спецификации."""
    return [
        (e, n["text"])
        for e in state.active()
        for n in state.names.get(e, [])
        if n["text"] != name_form(n["text"]) or n["normalized"] != search_form(n["text"])
    ]


# --- язык по письменности (entity-naming «Письменность и язык», пп. 1–5) -----------------

_EDGE = ".,;:!?()[]«»\"'„“”"
_ROMAN_WORD = re.compile(r"^[IVXLCDM]+$")
_LANG_SCRIPT = {
    "ru": "cyr",
    "en": "lat",
    "de": "lat",
    "fr": "lat",
    "la": "lat",
    "it": "lat",
    "el": "grc",
    "grc": "grc",
}
_SCRIPT_LANG = {"cyr": "ru", "lat": "en", "grc": "el"}


def _script(text: str) -> str | None:
    counts = {"cyr": 0, "lat": 0, "grc": 0, "other": 0}
    for word in text.split():
        word = word.strip(_EDGE)
        if _ROMAN_WORD.match(word):
            continue
        for ch in word:
            if not unicodedata.category(ch).startswith("L"):
                continue
            code = ord(ch)
            if 0x0400 <= code <= 0x052F:
                counts["cyr"] += 1
            elif unicodedata.name(ch, "").startswith("LATIN"):
                counts["lat"] += 1
            elif 0x0370 <= code <= 0x03FF or 0x1F00 <= code <= 0x1FFF:
                counts["grc"] += 1
            else:
                counts["other"] += 1
    top = max(counts.values())
    leaders = [k for k, v in counts.items() if v == top]
    if top == 0 or len(leaders) > 1:
        return None
    return leaders[0]


def lang_by_spec(text: str, given: str | None) -> str:
    script = _script(text)
    if script is not None and given is not None and _LANG_SCRIPT.get(given) == script:
        return given
    return _SCRIPT_LANG.get(script, "und")


def langs_broken(state, *, scripted_only: bool = False) -> list[tuple[str, str, str]]:
    """Шаг 3 ``lang_fix``: после миграции язык каждого названия действующей сущности —
    по правилу entity-naming (неподвижная точка правила). ``scripted_only`` — только
    названия с письменностью (без них — отдельный сценарий, Д3-mig)."""
    return [
        (e, n["text"], n["lang"])
        for e in state.active()
        for n in state.names.get(e, [])
        if (not scripted_only or _script(n["text"]) is not None)
        and n["lang"] != lang_by_spec(n["text"], n["lang"])
    ]


def reason_of(type_: str, label: str) -> str | None:
    """Причина правила названий для названий пулов (по построению входа)."""
    return GARBAGE.get((type_, name_form(label)), GARBAGE.get((type_, label)))


# --- сборка «старой» онтологии ------------------------------------------------------------


def raw_entity(onto, type_: str, names: list[tuple], qid: str | None = None) -> str:
    """Сущность «старых данных» в обход правила названий — как на стенде до миграции.

    Название — ``(lang, text, kind)`` или ``(lang, text, kind, normalized)`` с устаревшим ключом."""
    entity_id = f"e_{uuid.uuid4().hex[:12]}"
    with onto.entities.engine.begin() as conn:
        conn.execute(
            t.entities.insert().values(id=entity_id, type=type_, primary={}, redirect_to=None)
        )
        for lang, text, kind, *stale in names:
            conn.execute(
                t.names.insert().values(
                    entity_id=entity_id,
                    lang=lang,
                    text=text,
                    normalized=stale[0] if stale else search_form(text),
                    kind=kind,
                )
            )
        if qid:
            conn.execute(
                t.external_ids.insert().values(entity_id=entity_id, system="wikidata", value=qid)
            )
    return entity_id


def add_statement(onto, subject: str, rel: str, obj: str, attrs: list[Attribution]) -> str:
    """Утверждение «из извлечения» (статус не «проверено»): цитата из абзаца ``p2``."""
    return onto.statements.add(
        subject,
        rel,
        obj=obj,
        attributions=attrs,
        evidence=[Evidence("p2", "Кант испытал влияние Юма", source_id="s_a")],
        provenance=Provenance("extracted"),
    )


def add_dates(onto, entity_id: str, birth: str, death: str) -> str:
    return onto.statements.add(
        entity_id,
        "lifespan",
        value=lifespan(birth, death).to_json(),
        attributions=[Attribution("common")],
    )


def add_role(onto, entity_id: str, role: str = "philosopher") -> str:
    return onto.statements.add(
        entity_id, "person_role", value=role, attributions=[Attribution("common")]
    )


def add_mention(onto, entity_id: str, n: int) -> None:
    with onto.statements.engine.begin() as conn:
        conn.execute(
            t.mentions.insert().values(
                target_id=f"p{n}",
                target_kind="paragraph",
                source_id="s_a",
                chapter_id="c1",
                source_title="Учебник",
                chapter_title="Глава",
                entity_id=entity_id,
                start=0,
                end=3,
                method="name",
                position=n,
            )
        )


def add_portrait(onto, entity_id: str, n: int) -> None:
    from datetime import UTC, datetime

    with onto.statements.engine.begin() as conn:
        conn.execute(
            t.portraits.insert().values(
                entity_id=entity_id,
                file_id=f"{n:064x}",
                width=10,
                height=10,
                license="CC0",
                source_url="https://example.org/p.jpg",
                origin="commons:File:p.jpg",
                phash=f"{n:016x}",
                position=0,
                status="approved",
                hidden=False,
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )


DATA = (
    t.attributions,
    t.evidence,
    t.statements,
    t.names,
    t.external_ids,
    t.mentions,
    t.portraits,
    t.entities,
    t.merges,
    t.run_actions,
    t.review_items,
    t.statement_views,
    t.journal,
)


def wipe(onto) -> None:
    with onto.statements.engine.begin() as conn:
        for table in DATA:
            conn.execute(delete(table))


# --- строки базы для оракулов -------------------------------------------------------------


def rows(engine, table) -> list[dict[str, Any]]:
    with engine.begin() as conn:
        return [dict(r._mapping) for r in conn.execute(select(table))]


@dataclass
class State:
    """Снимок базы как данные: сущности, названия, QID, утверждения, атрибуции, очередь."""

    entities: dict[str, dict]
    names: dict[str, list[dict]]
    qids: dict[str, set[str]]
    statements: dict[str, dict]
    attributions: dict[str, list[dict]]
    review: list[dict]

    @classmethod
    def read(cls, engine) -> State:
        names: dict[str, list[dict]] = {}
        for n in sorted(rows(engine, t.names), key=lambda r: r["id"]):
            names.setdefault(n["entity_id"], []).append(n)
        qids: dict[str, set[str]] = {}
        for x in rows(engine, t.external_ids):
            if x["system"] == "wikidata":
                qids.setdefault(x["entity_id"], set()).add(x["value"])
        attrs: dict[str, list[dict]] = {}
        for a in rows(engine, t.attributions):
            attrs.setdefault(a["statement_id"], []).append(a)
        return cls(
            {e["id"]: e for e in rows(engine, t.entities)},
            names,
            qids,
            {s["id"]: s for s in rows(engine, t.statements)},
            attrs,
            rows(engine, t.review_items),
        )

    def resolve(self, entity_id: str | None) -> str | None:
        seen = set()
        while entity_id is not None and entity_id in self.entities:
            nxt = self.entities[entity_id]["redirect_to"]
            if nxt is None or entity_id in seen:
                return entity_id
            seen.add(entity_id)
            entity_id = nxt
        return entity_id

    def retired(self, entity_id: str | None) -> bool:
        return (
            entity_id is not None
            and self.entities.get(entity_id, {}).get("retired_run") is not None
        )

    def active(self) -> list[str]:
        return [
            i
            for i, e in self.entities.items()
            if e["redirect_to"] is None and e.get("retired_run") is None
        ]

    def label(self, entity_id: str) -> str:
        """«Название» сущности (спецификация «Замер»): основное ru, иначе первое основное,
        иначе первое любое."""
        names = self.names.get(entity_id, [])
        for n in names:
            if n["kind"] == "primary" and n["lang"] == "ru":
                return n["text"]
        for n in names:
            if n["kind"] == "primary":
                return n["text"]
        return names[0]["text"] if names else ""

    def name_set(self, entity_id: str) -> set[tuple[str, str, str]]:
        return {(n["lang"], n["text"], n["kind"]) for n in self.names.get(entity_id, [])}


SYMMETRIC = {"opposed_to"}  # registry_data: symmetric=True


def ends(type_: str, subj, obj) -> tuple:
    return tuple(sorted((subj, obj), key=str)) if type_ in SYMMETRIC else (subj, obj)


def statement_alive(s: dict) -> bool:
    """«Действующее» утверждение для учёта потерь: не отклонено и не устаревшее."""
    return s["status"] != "rejected" and s["rank"] != "deprecated"


def losses(before: State, after: State) -> tuple[list[str], list[tuple]]:
    """Потерянные утверждения и атрибуции по определениям спецификации «Миграция».

    Цель исходного утверждения — то же утверждение, если оно действующее, иначе действующее
    утверждение того же типа и значения с концами-образами (свёртка повтора при слиянии).
    """
    lost, lost_attrs = [], []
    by_content: dict[tuple, list[dict]] = {}
    for s in after.statements.values():
        if statement_alive(s):
            key = (
                s["type"],
                ends(s["type"], s["subject"], s["object"]),
                json.dumps(s["value"], sort_keys=True),
            )
            by_content.setdefault(key, []).append(s)
    for sid, s in before.statements.items():
        if not statement_alive(s):
            continue
        subj, obj = after.resolve(s["subject"]), after.resolve(s["object"])
        if after.retired(subj) or after.retired(obj):
            continue  # мусор: конец снят
        if obj is not None and subj == obj:
            continue  # петля при слиянии
        targets = []
        same = after.statements.get(sid)
        if same is not None and statement_alive(same):
            targets = [same]
        else:
            key = (s["type"], ends(s["type"], subj, obj), json.dumps(s["value"], sort_keys=True))
            targets = by_content.get(key, [])
        want_ends = ends(s["type"], subj, obj)
        ok = [
            x
            for x in targets
            if x["type"] == s["type"] and ends(x["type"], x["subject"], x["object"]) == want_ends
        ]
        if not ok:
            lost.append(sid)
            continue
        for a in before.attributions.get(sid, []):
            who = after.resolve(a["who"]) if a["who_kind"] == "entity" else a["who"]
            if a["who_kind"] == "entity" and after.retired(who):
                continue
            want = (a["who_kind"], who, a["stance"])
            have = {
                (
                    b["who_kind"],
                    after.resolve(b["who"]) if b["who_kind"] == "entity" else b["who"],
                    b["stance"],
                )
                for x in ok
                for b in after.attributions.get(x["id"], [])
            }
            if want not in have:
                lost_attrs.append((sid, want))
    return lost, lost_attrs


def verified_dropped(before: State, after: State) -> list[str]:
    """«Проверенное человеком не трогается»: проверенное утверждение (конец не снят, не петля)
    после запуска — проверенное, само или его цель свёртки. Не входит в определение потери
    (там только «нет / не действующее / подменено»), поэтому отдельно от ``losses``."""
    dropped = []
    for sid, s in before.statements.items():
        if s["status"] != "verified":
            continue
        subj, obj = after.resolve(s["subject"]), after.resolve(s["object"])
        if after.retired(subj) or after.retired(obj) or (obj is not None and subj == obj):
            continue
        want = (s["type"], ends(s["type"], subj, obj), json.dumps(s["value"], sort_keys=True))
        same = after.statements.get(sid)
        if same is not None and same["status"] == "verified":
            continue
        if not any(
            x["status"] == "verified"
            and (
                x["type"],
                ends(x["type"], x["subject"], x["object"]),
                json.dumps(x["value"], sort_keys=True),
            )
            == want
            for x in after.statements.values()
        ):
            dropped.append(sid)
    return dropped


# --- А1–А8 по формулам спецификации -------------------------------------------------------


def a1(state: State) -> float:
    ids = [i for i in state.active() if state.entities[i]["type"] != "source"]
    return sum(is_ru(state.label(i)) for i in ids) / len(ids) if ids else 1.0


def a2(state: State) -> int:
    return sum(
        is_number(state.label(i)) for i in state.active() if state.entities[i]["type"] != "source"
    )


def persons(state: State) -> list[str]:
    return [i for i in state.active() if state.entities[i]["type"] == "person"]


def a3(state: State) -> int:
    return sum(reason_of("person", state.label(p)) is not None for p in persons(state))


def a4_pairs(state: State) -> set[frozenset]:
    p = set(persons(state))
    # «нормализованное название» — по правилу, а не по хранимому столбцу (он может устареть)
    primary = {
        i: {search_form(n["text"]) for n in state.names.get(i, []) if n["kind"] == "primary"} - {""}
        for i in p
    }
    every = {i: {search_form(n["text"]) for n in state.names.get(i, [])} - {""} for i in p}
    names = {frozenset((a, b)) for a in p for b in p if a != b and primary[a] & every[b]}
    queue, distinct = set(), set()
    for item in state.review:
        if item["kind"] != "duplicate":
            continue
        pair = frozenset(item["payload"]["pair"])
        if item["status"] == "open" and pair <= p and len(pair) == 2:
            queue.add(pair)
        if (item.get("resolution") or {}).get("merge") is False:
            distinct.add(pair)
    return (names | queue) - distinct


def a5(state: State) -> int:
    return sum(bool((state.entities[p]["primary"] or {}).get("dates")) for p in persons(state))


THRESHOLDS = {
    "a1": lambda v: v is not None and v >= 0.90,
    "a2": lambda v: v == 0,
    "a3": lambda v: v == 0,
    "a4": lambda v: v == 0,
    "a5": lambda v: v is not None and v >= 20,
    "a6": lambda v: v is not None and v >= 10,
    "a7": lambda v: v == 0,
    "a8": lambda v: v == 0,
}


# --- фейковая модель ----------------------------------------------------------------------


class Reply:
    def __init__(self, status: int, body: Any) -> None:
        self.status_code, self._body = status, body

    def json(self) -> Any:
        return self._body


class FakeLLM:
    """Шлюз моделей с записью запросов. ``answer(items, number)`` возвращает список
    предложений ``[{n, ru}]`` или ``None`` — сбой шлюза (503)."""

    def __init__(self, answer=None, cost: float = 0.002) -> None:
        self.answer = answer or (lambda items, number: [])
        self.calls: list[dict] = []
        self.cost = cost
        self.run_ids: list[str] = []

    @classmethod
    def by_label(cls, table: dict[str, str]) -> FakeLLM:
        return cls(
            lambda items, _n: [
                {"n": i["n"], "ru": table[i["label"]]} for i in items if i["label"] in table
            ]
        )

    def items(self, call: dict) -> list[dict]:
        return json.loads(call["data"]["items"])

    def post(self, path, json=None):
        from philograph.platform import context

        self.calls.append(json)
        self.run_ids.append(context.run_id())
        reply = self.answer(self.items(json), len(self.calls))
        if reply is None:
            return Reply(503, {"kind": "unavailable"})
        return Reply(200, {"value": {"translations": reply}})

    def get(self, path, params=None):
        return Reply(200, [{"run_id": r, "cost_usd": self.cost} for r in self.run_ids])


# --- поверхность API ----------------------------------------------------------------------


class Surface:
    """Сервис знаний целиком на одном снимке без окна устарелости: справочник, карта, карточки,
    утверждения сущности, граф, поиск и контекст ассистента."""

    def __init__(self, onto, clock) -> None:
        from philograph.knowledge.app import build_app
        from philograph.knowledge.assist import AssistantKnowledge
        from philograph.knowledge.cards import Cards
        from philograph.knowledge.catalog import Catalog, CatalogSettings
        from philograph.knowledge.map import SectionMap
        from philograph.knowledge.mentions import Mentions
        from philograph.knowledge.snapshot import Snapshots
        from philograph.platform.client import ServiceClient

        def library(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/internal/access"):
                return httpx.Response(200, json={"closed": [], "hidden": []})
            return httpx.Response(404, json={"detail": "Not Found"})

        def llm(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, json={"error": "модель недоступна"})

        self.onto = onto
        lib = ServiceClient("library", "http://library/api", transport=httpx.MockTransport(library))
        self.snapshots = Snapshots(onto.statements.engine, clock)
        self.mentions = Mentions(onto.statements, lib)
        app = build_app(
            onto.statements,
            catalog=Catalog(self.snapshots, onto.registry, onto.entities, CatalogSettings(0)),
            section_map=SectionMap(onto.statements, snapshots=self.snapshots),
            cards=Cards(
                onto.statements,
                None,
                ServiceClient("llm", "http://llm", transport=httpx.MockTransport(llm)),
            ),
            library=lib,
            assistant=AssistantKnowledge(onto.statements, self.mentions),
        )
        self.client = TestClient(app, raise_server_exceptions=False)

    def catalog(self, **params) -> list[dict]:
        found, page = [], 1
        while True:
            r = self.client.get(
                "/v1/catalog", params={"lang": "ru", "limit": 60, "page": page, **params}
            )
            assert r.status_code == 200, r.text
            body = r.json()
            found += body["items"]
            if not body["items"] or len(found) >= body["total"]:
                return found
            page += 1

    def map(self) -> dict:
        r = self.client.get("/v1/map")
        assert r.status_code == 200, r.text
        return r.json()

    def card(self, entity_id: str):
        return self.client.get(f"/v1/entities/{entity_id}/card", params={"generation": "false"})

    def about(self, entity_id: str) -> list[dict]:
        r = self.client.get(f"/v1/entities/{entity_id}/statements")
        assert r.status_code == 200, r.text
        return r.json()

    def find(self, name: str):
        return self.client.get("/v1/entities", params={"name": name})

    def context(self, text: str, names: list[str] | None = None):
        return self.client.post(
            "/v1/internal/assistant/context",
            json={"text": text[:4000], "names": (names or [])[:10]},
        )

    def graph(self, start: str):
        return self.client.get("/v1/graph", params={"recipe": "genesis", "start": start})


def shown(surface: Surface, state: State) -> str:
    """Все ответы API, где может показаться сущность или утверждение, одной строкой JSON."""
    parts = [json.dumps(surface.catalog()), json.dumps(surface.map())]
    labels = []
    for e in state.active():
        label = state.label(e)
        labels.append(label)
        card = surface.card(e)
        assert card.status_code in (200,), (e, card.status_code, card.text)
        parts.append(card.text)
        parts.append(json.dumps(surface.about(e)))
        parts.append(surface.graph(e).text)
        ctx = surface.context(label, [label])
        assert ctx.status_code == 200, ctx.text
        parts.append(ctx.text)
    snap, _ = surface.snapshots.get(max_stale=0)
    parts.append(json.dumps(sorted(snap.entities)))
    parts.append(json.dumps(sorted(s["id"] for s in snap.statements)))
    parts.append(json.dumps(surface.mentions.paragraphs_of(list(state.entities))))
    return "\n".join(parts)


# --- стратегии «вход + ожидание» ----------------------------------------------------------


@dataclass
class World:
    """Собранная онтология и ожидания, построенные из того, как она собрана."""

    ids: dict[str, str] = field(default_factory=dict)
    types: dict[str, str] = field(default_factory=dict)
    garbage: dict[str, str] = field(default_factory=dict)  # ключ → причина
    expect_label: dict[str, str] = field(default_factory=dict)  # ключ → название после run
    expect_by: dict[str, str] = field(default_factory=dict)  # ключ → wikidata | model
    clusters: list[set[str]] = field(default_factory=list)  # ключи, сливаемые в одну персону
    wd: dict[str, dict] = field(default_factory=dict)
    llm_table: dict[str, str] = field(default_factory=dict)
    manifest: dict | None = None
    statements: list[str] = field(default_factory=list)
    verified: list[str] = field(default_factory=list)


@hst.composite
def ontologies(draw, *, manifest: bool = True) -> dict[str, Any]:
    """Описание онтологии с симптомами П1–П4 (design.md «Стратегии»): мусор всех причин,
    латинские понятия с языком ``ru``, кластеры дублей с QID у одной стороны, Гомер/Омир,
    0–30 утверждений с атрибуциями ``source``/``entity`` (в том числе на дубль и на мусор)/
    ``common``, проверенные, упоминания, портреты; подписи Wikidata и ответы модели."""
    spec: dict[str, Any] = {"entities": [], "wd": {}, "wd_times": {}, "llm": {}, "manifest": []}
    ents = spec["entities"]
    for gk in draw(hst.lists(hst.sampled_from(GARBAGE_KEYS), max_size=5, unique=True)):
        ents.append(
            {
                "key": f"g:{gk[1]}",
                "type": gk[0],
                "names": [("en", gk[1], "primary")],
                "garbage": GARBAGE[gk],
            }
        )
    for label, ru in draw(hst.lists(hst.sampled_from(LATIN_CONCEPTS), max_size=3, unique=True)):
        lang = draw(hst.sampled_from(["ru", "en"]))  # П1: латиница с языком ru
        translated = draw(hst.booleans())
        if translated:
            spec["llm"][label] = ru
        ents.append(
            {
                "key": f"c:{label}",
                "type": "concept",
                "names": [(lang, label, "primary")],
                "label": ru if translated else label,
                "by": "model" if translated else None,
            }
        )
    for label in draw(hst.lists(hst.sampled_from(RU_CONCEPTS), max_size=2, unique=True)):
        ents.append(
            {
                "key": f"c:{label}",
                "type": "concept",
                "names": [("ru", label, "primary")],
                "label": label,
            }
        )
    for label in draw(hst.lists(hst.sampled_from(RU_POSITIONS), max_size=1, unique=True)):
        ents.append(
            {
                "key": f"c:{label}",
                "type": "position",
                "names": [("ru", label, "primary")],
                "label": label,
            }
        )
    clusters = []
    for en, qid, ru in draw(hst.lists(hst.sampled_from(LATIN_QID), max_size=2, unique=True)):
        wd = draw(hst.sampled_from(["ru", "none", "latin", "number"]))
        spec["wd"][qid] = {"ru": ru, "none": None, "latin": en, "number": "20.1"}[wd]
        by_model = wd != "ru" and draw(hst.booleans())
        if by_model:
            spec["llm"][en] = ru
        renamed = wd == "ru" or by_model
        twin = draw(hst.booleans())
        ents.append(
            {
                "key": f"p:{en}",
                "type": "person",
                "names": [("en", en, "primary")],
                "qid": qid,
                "label": ru if renamed else en,
                "by": "wikidata" if wd == "ru" else ("model" if by_model else None),
            }
        )
        if twin:
            ents.append(
                {"key": f"p:{ru}", "type": "person", "names": [("ru", ru, "primary")], "label": ru}
            )
            if renamed:
                clusters.append({f"p:{en}", f"p:{ru}"})
    for en, _ru in draw(hst.lists(hst.sampled_from(LATIN_NOQID), max_size=1, unique=True)):
        k = draw(hst.integers(1, 3))  # Berkeley×k без QID и дат
        keys = {f"p:{en}#{i}" for i in range(k)}
        for key in sorted(keys):
            ents.append(
                {"key": key, "type": "person", "names": [("en", en, "primary")], "label": en}
            )
        if k > 1:
            clusters.append(keys)
    for label in draw(hst.lists(hst.sampled_from(RU_PERSONS), min_size=2, max_size=4, unique=True)):
        ents.append(
            {
                "key": f"p:{label}",
                "type": "person",
                "names": [("ru", label, "primary")],
                "label": label,
                "dates": draw(hst.booleans()),
            }
        )
    if manifest and draw(hst.booleans()):
        decision = draw(hst.sampled_from(["accepted", "pending", "none"]))
        spec["wd"]["Q6691"] = "Гомер"
        ents.append(
            {
                "key": "p:Гомер",
                "type": "person",
                "names": [("ru", "Гомер", "primary")],
                "qid": "Q6691",
                "label": "Гомер",
            }
        )
        ents.append(
            {
                "key": "p:Омир",
                "type": "person",
                "names": [("ru", "Омир", "primary")],
                # Слитая в «Гомер» запись показывает название оставшейся (с QID).
                "label": "Гомер" if decision == "accepted" else "Омир",
            }
        )
        if decision != "none":
            spec["manifest"].append(
                {"key": "p:Омир", "qid": "Q6691", "decision": decision, "holder": "p:Гомер"}
            )
        if decision == "accepted":
            clusters.append({"p:Гомер", "p:Омир"})
    if manifest and draw(hst.booleans()):
        # QID из манифеста пишется запуском (вместе с годами жизни из записи) — откат его снимает.
        ents.append(
            {
                "key": "p:Сократ",
                "type": "person",
                "names": [("ru", "Сократ", "primary")],
                "label": "Сократ",
            }
        )
        spec["wd"]["Q913"] = "Сократ"
        spec["wd_times"]["Q913"] = {
            "P569": ("-0469-00-00T00:00:00Z", 9),
            "P570": ("-0399-00-00T00:00:00Z", 9),
        }
        spec["manifest"].append(
            {
                "key": "p:Сократ",
                "qid": "Q913",
                "decision": draw(hst.sampled_from(["accepted", "auto"])),
                "holder": None,
            }
        )
    for label in draw(hst.lists(hst.sampled_from(SOURCE_NAMES), max_size=2, unique=True)):
        ents.append(
            {
                "key": f"s:{label}",
                "type": "source",
                "names": [("en", label, "primary")],
                "label": label,
            }
        )
    spec["clusters"] = clusters
    keys = [e["key"] for e in ents]
    types = {e["key"]: e["type"] for e in ents}
    stmts = []
    if len(keys) >= 2:
        for _ in range(draw(hst.integers(0, 25))):
            rel = draw(hst.sampled_from(sorted(RELATIONS)))
            subj_t, obj_t = RELATIONS[rel]
            subj = [k for k in keys if types[k] in subj_t]
            obj = [k for k in keys if types[k] in obj_t]
            if not subj or not obj:
                continue
            s, o = draw(hst.sampled_from(subj)), draw(hst.sampled_from(obj))
            if s == o or any(
                x["rel"] == rel
                and (
                    (x["s"], x["o"]) == (s, o) or (rel in SYMMETRIC and (x["s"], x["o"]) == (o, s))
                )
                for x in stmts
            ):
                continue
            who_persons = [k for k in keys if types[k] == "person"]
            attrs = []
            for _ in range(draw(hst.integers(1, 2))):
                kind = draw(
                    hst.sampled_from(
                        ["source", "common", "entity"] if who_persons else ["source", "common"]
                    )
                )
                who = (
                    draw(hst.sampled_from(SOURCES))
                    if kind == "source"
                    else draw(hst.sampled_from(who_persons))
                    if kind == "entity"
                    else None
                )
                attrs.append((kind, who, draw(hst.sampled_from(STANCES))))
            stmts.append(
                {"s": s, "rel": rel, "o": o, "attrs": attrs, "verified": draw(hst.booleans())}
            )
    spec["statements"] = stmts
    spec["mentions"] = (
        draw(hst.lists(hst.sampled_from(keys), max_size=3, unique=True)) if keys else []
    )
    p_keys = [k for k in keys if types[k] == "person"]
    spec["portraits"] = (
        draw(hst.lists(hst.sampled_from(p_keys), max_size=2, unique=True)) if p_keys else []
    )
    # О24: «старые» названия — NFD, пробелы по краям, устаревший ключ поиска
    plain = [e["key"] for e in spec["entities"] if e["type"] != "source"]
    spec["decorate"] = (
        draw(
            hst.dictionaries(
                hst.sampled_from(plain), hst.tuples(hst.booleans(), PADS, PADS), max_size=4
            )
        )
        if plain
        else {}
    )
    return spec


def build(onto, spec: dict[str, Any]) -> World:
    """Онтология по описанию; ожидания — из описания."""
    from tests.knowledge.wd_records import record

    w = World()
    decorate = spec.get("decorate", {})
    for e in spec["entities"]:
        names = e["names"]
        if e["key"] in decorate:
            names = [
                (lang, *old_form(text, *decorate[e["key"]]), kind) for lang, text, kind in names
            ]
            names = [(lang, text, kind, stale) for lang, text, stale, kind in names]
        eid = raw_entity(onto, e["type"], names, e.get("qid"))
        w.ids[e["key"]], w.types[e["key"]] = eid, e["type"]
        if e.get("garbage"):
            w.garbage[e["key"]] = e["garbage"]
        else:
            w.expect_label[e["key"]] = e["label"]
            if e.get("by"):
                w.expect_by[e["key"]] = e["by"]
        if e.get("dates"):
            add_dates(onto, eid, "1700", "1780")
    w.clusters = spec["clusters"]
    w.llm_table = dict(spec["llm"])
    for qid, ru in spec["wd"].items():
        w.wd[qid] = record(
            qid, ru=ru, en="Label", classes=HUMAN, times=spec.get("wd_times", {}).get(qid)
        )
    if spec["manifest"]:
        w.manifest = {
            "entities": [
                {
                    "entity": w.ids[m["key"]],
                    "wikidata": m["qid"] if m["decision"] in ("accepted", "auto") else None,
                    "decision": m["decision"],
                    "candidates": [{"qid": m["qid"], "holder": w.ids[m["holder"]]}]
                    if m["holder"]
                    else [],
                }
                for m in spec["manifest"]
            ]
        }
    for st in spec["statements"]:
        attrs = [
            Attribution(k, w.ids[who] if k == "entity" else who, stance)
            for k, who, stance in st["attrs"]
        ]
        sid = add_statement(onto, w.ids[st["s"]], st["rel"], w.ids[st["o"]], attrs)
        w.statements.append(sid)
        if st["verified"] and sid not in w.verified:
            onto.statements.confirm(sid, "operator")
            w.verified.append(sid)
    for i, k in enumerate(spec["mentions"]):
        add_mention(onto, w.ids[k], i + 1)
    for i, k in enumerate(spec["portraits"]):
        add_portrait(onto, w.ids[k], i + 1)
    return w


def name_texts(spec: dict[str, Any]) -> set[str]:
    """Тексты названий входа, которые сторожат журнал (не короче 4 знаков)."""
    out = {
        name_form(text)
        for e in spec["entities"]
        for _l, text, _k in e["names"]
        if len(text.strip()) >= 4
    }
    out |= {v for v in spec["llm"].values() if len(v) >= 4}
    return out


def event_values(events) -> str:
    """Значения полей всех событий одной строкой (ключи полей — не тексты)."""
    return "\n".join(
        json.dumps(list(e.fields.values()), ensure_ascii=False, default=str) for e in events.items
    )


def reasons_counter(world: World) -> Counter:
    return Counter(world.garbage.values())


def _e(key, type_, label, lang="en", **kw):
    return {"key": key, "type": type_, "names": [(lang, label, "primary")], "label": label, **kw}


# Явный пример инвариантов (П1–П4 целиком): мусор всех причин, латиница с языком ru и перевод,
# Hume(QID)/Юм, Berkeley×3, Гомер/Омир с решением, Сократ с QID манифеста, источники; атрибуции
# на дубль и на мусор, проверенное утверждение на дубле.
SYMPTOMS_SPEC: dict[str, Any] = {
    "entities": [
        {
            "key": "g:20.1",
            "type": "concept",
            "names": [("en", "20.1", "primary")],
            "garbage": "number",
        },
        {
            "key": "g:Every",
            "type": "term",
            "names": [("en", "Every", "primary")],
            "garbage": "stopword",
        },
        {"key": "g:", "type": "term", "names": [("en", "", "primary")], "garbage": "empty"},
        {
            "key": "g:your Lordship",
            "type": "person",
            "names": [("en", "your Lordship", "primary")],
            "garbage": "not_a_name",
        },
        _e("c:causality", "concept", "Причинность", by="model")
        | {"names": [("ru", "causality", "primary")]},
        _e("c:space", "concept", "space") | {"names": [("en", "space", "primary")]},
        _e("p:Hume", "person", "Юм", qid="Q41568", by="wikidata")
        | {"names": [("en", "Hume", "primary")]},
        _e("p:Юм", "person", "Юм", "ru"),
        _e("p:Berkeley#0", "person", "Berkeley"),
        _e("p:Berkeley#1", "person", "Berkeley"),
        _e("p:Berkeley#2", "person", "Berkeley"),
        _e("p:Кант", "person", "Кант", "ru", dates=True),
        _e("p:Декарт", "person", "Декарт", "ru"),
        _e("p:Гомер", "person", "Гомер", "ru", qid="Q6691"),
        _e("p:Омир", "person", "Гомер", "ru") | {"names": [("ru", "Омир", "primary")]},
        _e("p:Сократ", "person", "Сократ", "ru"),
        _e("p:Йоганн", "person", "Йоганн", "ru"),
        _e("s:A Treatise of Human Nature", "source", "A Treatise of Human Nature"),
        _e("s:3.1", "source", "3.1"),
    ],
    "wd": {"Q41568": "Юм", "Q6691": "Гомер", "Q913": "Сократ"},
    "wd_times": {
        "Q913": {"P569": ("-0469-00-00T00:00:00Z", 9), "P570": ("-0399-00-00T00:00:00Z", 9)}
    },
    "llm": {"causality": "Причинность"},
    # О24: NFD, пробелы и NBSP по краям, устаревший ключ поиска — у слитых и у одиночки
    "decorate": {
        "p:Йоганн": (True, " ", "\t"),
        "p:Юм": (False, "", "\u00a0"),
        "p:Berkeley#1": (True, "  ", ""),
        "c:causality": (False, "\u2003", " "),
    },
    "manifest": [
        {"key": "p:Омир", "qid": "Q6691", "decision": "accepted", "holder": "p:Гомер"},
        {"key": "p:Сократ", "qid": "Q913", "decision": "accepted", "holder": None},
    ],
    "clusters": [
        {"p:Hume", "p:Юм"},
        {"p:Berkeley#0", "p:Berkeley#1", "p:Berkeley#2"},
        {"p:Гомер", "p:Омир"},
    ],
    "statements": [
        {
            "s": "p:Кант",
            "rel": "studied_with",
            "o": "p:Berkeley#0",
            "attrs": [("source", "s_a", "asserts")],
            "verified": False,
        },
        {
            "s": "p:Кант",
            "rel": "studied_with",
            "o": "p:Berkeley#1",
            "attrs": [("source", "s_a", "asserts"), ("entity", "p:Berkeley#2", "disputes")],
            "verified": True,
        },
        {
            "s": "p:Декарт",
            "rel": "studied_with",
            "o": "g:your Lordship",
            "attrs": [("source", "s_b", "asserts")],
            "verified": False,
        },
        {
            "s": "p:Кант",
            "rel": "influenced_by",
            "o": "g:20.1",
            "attrs": [("common", None, "asserts")],
            "verified": False,
        },
        {
            "s": "p:Декарт",
            "rel": "influenced_by",
            "o": "p:Hume",
            "attrs": [("entity", "g:your Lordship", "asserts"), ("source", "s_a", "mentions")],
            "verified": False,
        },
        {
            "s": "c:causality",
            "rel": "opposed_to",
            "o": "c:space",
            "attrs": [("source", "s_b", "asserts")],
            "verified": True,
        },
        {
            "s": "p:Юм",
            "rel": "studied_with",
            "o": "p:Омир",
            "attrs": [("entity", "p:Hume", "asserts")],
            "verified": False,
        },
    ],
    "mentions": ["p:Hume", "g:20.1", "p:Омир"],
    "portraits": ["p:Юм", "p:Berkeley#1"],
}
