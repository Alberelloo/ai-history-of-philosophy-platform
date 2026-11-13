"""Раунд 5: независимый стенд проверки ru-only-sources (группы 5–6 и сырые маршруты).

Поднимает ``scripts/dev_stack.py`` в-process (без демо-источников), добавляет свои источники
(открытый и ограниченный [RU]), сеет онтологию и упоминания, затем проверяет через настоящие
HTTP-интерфейсы сервисов и шлюза:

- карточка, граф, «где читать», упоминания и контекст ассистента скрывают подтверждения, цитаты,
  ссылки ``/p/`` и атрибуции закрытого источника, но сами утверждения и статус остаются;
- сырые маршруты ``/v1/entities/{id}/statements`` и ``/v1/graph`` через шлюз не отдают цитаты
  закрытых источников (TC-55);
- недоступная библиотека при ``internal/access`` — 503 ``knowledge_unavailable``;
- ассистент получает регион из заголовка, передаёт его в поиск и в контекст знаний, игнорирует
  выделение и ``source_id`` закрытого источника, ``grounding.verify`` — второй слой;
- служебные ``XX``/``T1`` — неизвестный регион; читатель из РФ видит всё как раньше.

Код, тесты и спецификации не меняются: артефакты только в ``qa/round-5/``.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROUND = HERE.parent
REPO = HERE.parents[5]
SHOTS = ROUND.parent / "screenshots" / ROUND.name
STAND = HERE / "stand"
TMP = HERE / "tmp"
TMP.mkdir(parents=True, exist_ok=True)
os.environ["TMP"] = os.environ["TEMP"] = str(TMP)

sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OPEN_TITLE = "Открытый сборник о рассудке"
RU_TITLE = "Закрытый учебник [RU]"
CLOSED_MARKER = "ЗЕТА-9"
OPEN_MARKER = "ОМЕГА-7"
CLOSED_PHRASE = (
    "Гуссерль различал рассудок и разум. Закрытая деталь ЗЕТА-9: рассудок есть способность правил."
)
OPEN_PHRASE = (
    "Гуссерль различал рассудок и разум. Открытая деталь ОМЕГА-7: разум есть способность принципов."
)
CLOSED_QUOTE = "Закрытая деталь ЗЕТА-9: рассудок есть способность правил."
OPEN_QUOTE = "Открытая деталь ОМЕГА-7: разум есть способность принципов."

FILES = {
    "closed_ru.txt": (
        "Глава 1. Рассудок и разум\n\n"
        f"{CLOSED_PHRASE}\n\n"
        "Второй абзац закрытого источника: рассудок и разум в теории познания.\n"
    ).encode(),
    "open.txt": (
        "Глава 1. Рассудок и разум\n\n"
        f"{OPEN_PHRASE}\n\n"
        "Второй абзац открытого источника: рассудок и разум у Канта.\n"
    ).encode(),
}

CHECKS: list[dict] = []


def record(cid: str, ok: bool, expected: str, actual, evidence=None) -> dict:
    item = {
        "id": cid,
        "ok": bool(ok),
        "expected": expected,
        "actual": actual if isinstance(actual, str) else json.dumps(
            actual, ensure_ascii=False, default=str
        ),
        "evidence": evidence or [],
    }
    CHECKS.append(item)
    print(("PASS " if ok else "FAIL ") + cid + " :: " + item["actual"][:280])
    return item


# --- 1. источники тестировщика до старта стенда ------------------------------------


def pre_seed(data: Path) -> dict[str, str]:
    from philograph.library import schema as lib_schema
    from philograph.library.processing import Pipeline
    from philograph.library.reading import Reading
    from philograph.library.registry import License, Registry
    from philograph.operator.access import migrations as op_migrations
    from philograph.platform.db import make_engine
    from philograph.platform.files import FileStore
    from philograph.platform.queue import Queue
    from philograph.platform.queue import migrations as q_migrations

    data.mkdir(parents=True, exist_ok=True)
    db = f"sqlite:///{(data / 'stack.db').as_posix()}"
    sets = (lib_schema.migrations, op_migrations, q_migrations)
    engine = make_engine(db, [m.schema for m in sets])
    for m in sets:
        m.upgrade(engine)
    registry = Registry(engine)
    permissions = {"display": True, "external_processing": True, "quoting": True}
    registry.add_license_kind("qa-open", "Открытая лицензия QA", None, dict(permissions))
    registry.add_license_kind("qa-ru", "Только РФ (QA)", None, dict(permissions), regions=["RU"])
    pipeline = Pipeline(registry, FileStore(data / "files"), lambda spec: FILES[spec["path"]])
    ids: dict[str, str] = {}
    versions: dict[str, str] = {}
    for key, title, kind, path in (
        ("open", OPEN_TITLE, "qa-open", "open.txt"),
        ("closed", RU_TITLE, "qa-ru", "closed_ru.txt"),
    ):
        source_id = registry.register(
            "qa",
            title=title,
            authors=["QA тестировщик"],
            year=2026,
            language="ru",
            kind="textbook",
            license=License(kind, "public_domain", author_death_years=[1900]),
            scope="public",
            files=[{"name": path, "path": path}],
            confirm_duplicate=True,
        )
        version = pipeline.start("qa", source_id)
        registry.publish("qa", version)
        ids[key] = source_id
        versions[key] = version
    reading = Reading(registry, engine)
    reading.set_default("qa", ids["open"])
    pipeline.dispatch_outbox(Queue(engine))
    return {**ids, **{f"version_{k}": v for k, v in versions.items()}}


def seed_ontology(
    data: Path, source_ids: dict[str, str], paragraphs: dict[str, list[dict]]
) -> dict[str, object]:
    """Сущности, утверждения и упоминания: закрытое и открытое подтверждение."""
    from philograph.knowledge import schema as ks
    from philograph.knowledge.entities import Entities
    from philograph.knowledge.registry import OntologyRegistry
    from philograph.knowledge.statements import Attribution, Evidence, Provenance, Statements

    db = f"sqlite:///{(data / 'stack.db').as_posix()}"
    engine = __import__("philograph.platform.db", fromlist=["make_engine"]).make_engine(
        db, [ks.SCHEMA]
    )
    ks.migrations.upgrade(engine)
    registry = OntologyRegistry(engine)
    registry.load_defaults()
    entities = Entities(engine, registry)

    closed_paragraphs = paragraphs[source_ids["closed"]]
    open_paragraphs = paragraphs[source_ids["open"]]
    closed_pid = closed_paragraphs[0]["id"]
    open_pid = open_paragraphs[0]["id"]
    text_of = {p["id"]: p["text"] for rows in paragraphs.values() for p in rows}
    statements = Statements(engine, registry, entities, text_of.get)

    def person(name: str) -> str:
        return entities.create("person", [("ru", name, "primary")])

    gusserl = person("Гуссерль")
    brentano = person("Брентано")
    locke = person("Локк")

    closed_statement = statements.add(
        gusserl,
        "influenced_by",
        obj=brentano,
        attributions=[Attribution("source", source_ids["closed"])],
        evidence=[Evidence(closed_pid, CLOSED_QUOTE, source_id=source_ids["closed"])],
        provenance=Provenance("extracted", actor="qa"),
    )
    open_statement = statements.add(
        gusserl,
        "influenced_by",
        obj=locke,
        attributions=[Attribution("source", source_ids["open"])],
        evidence=[Evidence(open_pid, OPEN_QUOTE, source_id=source_ids["open"])],
        provenance=Provenance("extracted", actor="qa"),
    )

    def insert_mention(paragraph: dict, source: str, title: str) -> None:
        start = paragraph["text"].index("Гуссерль")
        with engine.begin() as conn:
            conn.execute(
                ks.mentions.insert().values(
                    target_id=paragraph["id"],
                    target_kind="paragraph",
                    source_id=source,
                    chapter_id=paragraph.get("chapter_id"),
                    source_title=title,
                    chapter_title="Глава 1. Рассудок и разум",
                    entity_id=gusserl,
                    start=start,
                    end=start + len("Гуссерль"),
                    method="name",
                    position=0,
                )
            )

    insert_mention(closed_paragraphs[0], source_ids["closed"], RU_TITLE)
    insert_mention(open_paragraphs[0], source_ids["open"], OPEN_TITLE)
    return {
        "entity": gusserl,
        "other": brentano,
        "closed_pid": closed_pid,
        "open_pid": open_pid,
        "closed_statement": closed_statement,
        "open_statement": open_statement,
    }


# --- 2. помощники стенда -----------------------------------------------------------


def db_engine(data: Path, schemas):
    from philograph.platform.db import make_engine

    return make_engine(f"sqlite:///{(data / 'stack.db').as_posix()}", schemas)


def latest_prompts(data: Path, limit: int = 6) -> list[dict]:
    """Последние запросы к модели из журнала сервиса LLM (prompt_text, response_text)."""
    from sqlalchemy import select

    from philograph.llm import store

    engine = db_engine(data, [store.SCHEMA])
    with engine.begin() as conn:
        rows = conn.execute(
            select(store.calls).order_by(store.calls.c.id.desc()).limit(limit)
        ).mappings()
        return [dict(r) for r in rows]


def answer_prompt(data: Path) -> str:
    """Запрос к основной модели из последнего ответа ассистента (prompt_text)."""
    for row in latest_prompts(data, 12):
        if (row.get("template") or "").startswith("assistant.answer") and (
            row.get("caller") == "assistant"
        ):
            return row.get("prompt_text") or ""
    return ""


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_ready(url: str, seconds: float = 60) -> bool:
    import httpx

    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            if httpx.get(url + "/health/ready", timeout=2).status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.3)
    return False


def start_gateway(env_extra: dict[str, str], log_name: str) -> tuple[str, subprocess.Popen]:
    env = {**os.environ, **env_extra}
    port = free_port()
    log = open(ROUND / log_name, "w", encoding="utf-8")  # noqa: SIM115
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "philograph.gateway.app:app",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=str(REPO),
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    return f"http://127.0.0.1:{port}", proc


def ask(url: str, body: dict, headers: dict | None = None, timeout: float = 90) -> list[dict]:
    import httpx

    events: list[dict] = []
    with httpx.Client(timeout=timeout) as client:
        with client.stream("POST", url, json=body, headers=headers or {}) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if line.strip():
                    events.append(json.loads(line))
    return events


def session(url: str, headers: dict | None = None):
    """Клиент шлюза с токеном страницы: без него платные операции получают 403."""
    import httpx

    client = httpx.Client(base_url=url, headers=headers or {}, timeout=90)
    client.get("/")
    return client


def ask_via(client, body: dict, headers: dict | None = None) -> list[dict]:
    events: list[dict] = []
    with client.stream(
        "POST", "/api/assistant/v1/ask", json=body, headers=headers or {}
    ) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if line.strip():
                events.append(json.loads(line))
    return events


def answer_sources(events: list[dict]) -> set[str]:
    found = set()
    for event in events:
        for citation in event.get("citations") or []:
            if isinstance(citation, dict) and citation.get("source_id"):
                found.add(citation["source_id"])
    return found


def answer_text(events: list[dict]) -> str:
    return " ".join(event.get("text", "") for event in events if event.get("type") == "fragment")


# --- 3. проверки -------------------------------------------------------------------


def main() -> int:  # noqa: C901, PLR0915
    import httpx

    if STAND.exists():
        shutil.rmtree(STAND, ignore_errors=True)
    STAND.mkdir(parents=True, exist_ok=True)
    ids = pre_seed(STAND)
    print("источники:", ids)

    import dev_stack

    ports: list[int] = []
    original_free_port = dev_stack.free_port

    def recording_free_port() -> int:
        port = original_free_port()
        ports.append(port)
        return port

    dev_stack.free_port = recording_free_port
    stack = dev_stack.start(STAND, None, demo=False)
    names = ["llm", "library", "search", "assistant", "knowledge"]
    port_of = dict(zip(names, ports, strict=False))
    gateway = stack.url
    library = f"http://127.0.0.1:{port_of['library']}"
    knowledge = f"http://127.0.0.1:{port_of['knowledge']}"
    assistant = f"http://127.0.0.1:{port_of['assistant']}"
    print("стенд:", gateway, port_of)

    logs = STAND / "logs"
    evidence = [str(ROUND / "live-report.json"), str(logs)]

    # Параграфы своих источников: id, текст, глава.
    with httpx.Client(timeout=30) as client:
        published = client.get(library + "/api/v1/internal/published").json()
        version_of = {row["source_id"]: row["version_id"] for row in published}
        paragraphs: dict[str, list[dict]] = {}
        for source_id in (ids["open"], ids["closed"]):
            payload = client.get(
                library + f"/api/v1/internal/versions/{version_of[source_id]}/paragraphs"
            ).json()
            paragraphs[source_id] = payload["paragraphs"]
    seeded = seed_ontology(STAND, ids, paragraphs)
    closed_pid = str(seeded["closed_pid"])
    open_pid = str(seeded["open_pid"])
    gusserl = str(seeded["entity"])

    # Второй шлюз: регион приходит заголовком страны от доверенного прокси/CDN.
    proxy_url, proxy_proc = start_gateway(
        {
            "PHILOGRAPH_DATABASE_URL": f"sqlite:///{(STAND / 'stack.db').as_posix()}",
            "PHILOGRAPH_LIBRARY_URL": library,
            "PHILOGRAPH_ASSISTANT_URL": assistant,
            "PHILOGRAPH_KNOWLEDGE_URL": knowledge,
            "PHILOGRAPH_WEB_ROOT": str(REPO / "web" / "dist"),
            "PHILOGRAPH_REGION_HEADER": "CF-IPCountry",
            "PHILOGRAPH_TRUSTED_PROXY": "1",
            "PHILOGRAPH_REGION_FALLBACK": "",
        },
        "gateway-proxy.log",
    )
    proxy_ready = wait_ready(proxy_url)
    print("прокси-шлюз:", proxy_url, proxy_ready)

    def api(url: str, path: str, headers: dict | None = None, **kwargs):
        with httpx.Client(timeout=60) as client:
            return client.get(url + path, headers=headers or {}, **kwargs)

    def card(url: str, headers: dict | None = None) -> dict:
        response = api(
            url, f"/api/knowledge/v1/entities/{gusserl}/card?generation=false", headers=headers
        )
        response.raise_for_status()
        return response.json()

    def rows_by_id(card_payload: dict) -> dict[str, dict]:
        return {
            row["statement_id"]: row
            for section in card_payload.get("sections", [])
            for row in section["rows"]
        }

    def graph_edges(url: str, headers: dict | None = None) -> list[dict]:
        response = api(
            url,
            "/api/knowledge/v1/graph",
            headers=headers,
            params={"recipe": "genesis", "start": gusserl},
        )
        response.raise_for_status()
        return response.json()["edges"]

    def graph_nodes(url: str, headers: dict | None = None) -> list[str]:
        response = api(
            url,
            "/api/knowledge/v1/graph",
            headers=headers,
            params={"recipe": "genesis", "start": gusserl},
        )
        return sorted(node["id"] for node in response.json()["nodes"])

    closed_statement = str(seeded["closed_statement"])
    open_statement = str(seeded["open_statement"])
    de = {"CF-IPCountry": "DE"}
    ru = {"CF-IPCountry": "RU"}
    unknown = {}
    service_codes = {"CF-IPCountry": "XX"}
    tor = {"CF-IPCountry": "T1"}

    try:
        # Ждём индексацию своих источников.
        deadline = time.time() + 120
        indexed = False
        while time.time() < deadline:
            with httpx.Client(timeout=30) as client:
                found = client.post(
                    f"http://127.0.0.1:{port_of['search']}/v1/search",
                    json={"query": "рассудок и разум", "region": "RU", "limit": 10},
                ).json()["results"]
            if any(r["source_id"] == ids["closed"] for r in found):
                indexed = True
                break
            time.sleep(1.0)
        print("индексация:", indexed)
        # Ждём, пока сервис знаний увидит опубликованные источники (события из очереди).
        time.sleep(3.0)

        # --- карточка (UC-20, TC-41, TC-42) ---
        card_de = card(proxy_url, de)
        rows_de = rows_by_id(card_de)
        closed_row = rows_de.get(closed_statement, {})
        open_row = rows_de.get(open_statement, {})
        record(
            "TC-41",
            closed_row.get("status") == "sourced"
            and closed_row.get("evidence") == []
            and closed_row.get("attributed_to") == []
            and closed_row.get("attributions") == []
            and closed_row.get("label") == "Брентано",
            "карточка DE: утверждение из закрытого источника остаётся, статус sourced, "
            "подтверждений/атрибуций нет, факт (label) на месте",
            {
                "row": closed_row,
                "status": card_de.get("status"),
            },
            evidence + [str(SHOTS / "UC-20-2-card-de.png")],
        )
        record(
            "TC-42",
            [e["paragraph_id"] for e in open_row.get("evidence", [])] == [open_pid]
            and open_row.get("attributed_to") == [OPEN_TITLE],
            "карточка DE: подтверждение открытого источника остаётся",
            {"evidence": open_row.get("evidence"), "attributed_to": open_row.get("attributed_to")},
            evidence,
        )
        # EC-39: пустые массивы, не null; EC-38: факты не меняются.
        record(
            "EC-39",
            isinstance(closed_row.get("evidence"), list)
            and isinstance(closed_row.get("attributions"), list)
            and isinstance(closed_row.get("attributed_to"), list)
            and closed_row.get("label") == "Брентано",
            "EC-39/EC-38: скрытые поля — пустые массивы, факт утверждения и связь не меняются",
            {
                "evidence": closed_row.get("evidence"),
                "attributions": closed_row.get("attributions"),
                "attributed_to": closed_row.get("attributed_to"),
                "label": closed_row.get("label"),
                "relation": closed_row.get("relation"),
            },
            evidence,
        )

        card_ru = card(gateway)
        rows_ru = rows_by_id(card_ru)
        closed_row_ru = rows_ru.get(closed_statement, {})
        where_ru = card_ru.get("where_to_read", [])
        record(
            "TC-42/RU",
            [e["paragraph_id"] for e in closed_row_ru.get("evidence", [])] == [closed_pid]
            and closed_row_ru.get("attributed_to") == [RU_TITLE]
            and any(w.get("source_id") == ids["closed"] for w in where_ru)
            and any(w.get("source_id") == ids["open"] for w in where_ru),
            "читатель из РФ видит как раньше: подтверждение закрытого источника и «где читать» "
            "по обоим источникам",
            {
                "evidence": closed_row_ru.get("evidence"),
                "attributed_to": closed_row_ru.get("attributed_to"),
                "where": [w.get("source_id") for w in where_ru],
            },
            evidence + [str(SHOTS / "UC-26-1-card-ru.png")],
        )
        record(
            "TC-40",
            closed_row and closed_row.get("evidence") == [],
            "регион DE из заголовка CDN доходит до библиотеки: карточка DE скрывает подтверждение",
            {"card_de_row": closed_row, "gateway": proxy_url},
            evidence,
        )

        # --- «где читать» и упоминания (UC-22, TC-44) ---
        where_de = api(proxy_url, f"/api/knowledge/v1/entities/{gusserl}/where", de).json()
        record(
            "TC-44/where",
            [w.get("source_id") for w in where_de] == [ids["open"]],
            "«где читать» для DE: только открытый источник",
            {"where": where_de},
            evidence,
        )
        mentions_de = api(
            proxy_url,
            "/api/knowledge/v1/mentions",
            de,
            params={"targets": f"{closed_pid},{open_pid}"},
        ).json()
        mentions_ru = api(
            gateway,
            "/api/knowledge/v1/mentions",
            params={"targets": f"{closed_pid},{open_pid}"},
        ).json()
        record(
            "TC-44/mentions",
            [m["target_id"] for m in mentions_de] == [open_pid]
            and sorted(m["target_id"] for m in mentions_ru) == sorted([closed_pid, open_pid]),
            "упоминания DE: выделения закрытого источника не отдаются, открытые остаются; "
            "для РФ — оба",
            {"DE": [m["target_id"] for m in mentions_de], "RU": [m["target_id"] for m in mentions_ru]},
            evidence,
        )

        # --- сырые маршруты (TC-55) ---
        statements_de = api(proxy_url, f"/api/knowledge/v1/entities/{gusserl}/statements", de).json()
        statements_ru = api(gateway, f"/api/knowledge/v1/entities/{gusserl}/statements").json()
        raw_de = {row["id"]: row for row in statements_de}
        raw_ru = {row["id"]: row for row in statements_ru}
        record(
            "TC-55/statements",
            raw_de[closed_statement]["evidence"] == []
            and raw_de[closed_statement]["attributions"] == []
            and raw_de[closed_statement]["status"] == "sourced"
            and [e["paragraph_id"] for e in raw_de[open_statement]["evidence"]] == [open_pid]
            and [e["paragraph_id"] for e in raw_ru[closed_statement]["evidence"]] == [closed_pid],
            "сырые утверждения через шлюз: DE не получает цитат/атрибуций закрытого источника, "
            "RU получает; открытое подтверждение остаётся",
            {
                "DE_closed": raw_de[closed_statement],
                "DE_open_evidence": raw_de[open_statement]["evidence"],
                "RU_closed_evidence": raw_ru[closed_statement]["evidence"],
            },
            evidence,
        )
        edges_de = graph_edges(proxy_url, de)
        edges_ru = graph_edges(gateway)
        edge_de = next(e for e in edges_de if e["id"] == closed_statement)
        edge_ru = next(e for e in edges_ru if e["id"] == closed_statement)
        record(
            "TC-55/graph",
            edge_de["evidence"] == []
            and edge_de["attributions"] == []
            and edge_de["status"] == "sourced"
            and edge_ru["evidence"]
            and edge_ru["attributions"]
            and graph_nodes(proxy_url, de) == graph_nodes(gateway),
            "сырой граф через шлюз: у связи закрытого источника нет подтверждений для DE, "
            "для RU — есть; узлы те же",
            {
                "DE_edge": edge_de,
                "RU_edge": edge_ru,
                "nodes": graph_nodes(gateway),
            },
            evidence,
        )

        # --- граф build (UC-21, TC-43) ---
        de_client = session(proxy_url)
        ru_client = session(gateway)
        response = de_client.post(
            "/api/knowledge/v1/graph/build",
            json={"entity_id": gusserl, "recipe": "genesis", "generation": False},
            headers=de,
        )
        response.raise_for_status()
        build_de = [json.loads(line) for line in response.text.splitlines() if line.strip()]
        graph_de = next(item for item in build_de if item.get("type") == "graph")
        b_edge = next(e for e in graph_de["edges"] if e["id"] == closed_statement)
        record(
            "TC-43",
            b_edge["evidence"] == []
            and b_edge["attributions"] == []
            and b_edge["status"] == "sourced"
            and sorted(n["id"] for n in graph_de["nodes"])
            == sorted(node for node in graph_nodes(gateway)),
            "граф по запросу для DE: связь и узлы те же, подтверждений из закрытого источника нет",
            {
                "edge": b_edge,
                "nodes": [n["id"] for n in graph_de["nodes"]],
                "nodes_ru": graph_nodes(gateway),
            },
            evidence,
        )

        # --- контекст ассистента (UC-23, TC-45, TC-49) ---
        with httpx.Client(timeout=60) as client:
            context_de = client.post(
                knowledge + "/v1/internal/assistant/context",
                json={
                    "text": "Гуссерль",
                    "names": [],
                    "paragraphs": [closed_pid, open_pid],
                    "steps": ["entities", "recipes", "context"],
                    "recipe": "genesis",
                    "region": "DE",
                },
            ).json()
            context_ru = client.post(
                knowledge + "/v1/internal/assistant/context",
                json={
                    "text": "Гуссерль",
                    "names": [],
                    "paragraphs": [closed_pid, open_pid],
                    "steps": ["entities", "recipes", "context"],
                    "recipe": "genesis",
                    "region": "RU",
                },
            ).json()
        context_de_pids = {p["paragraph_id"] for p in context_de.get("paragraphs", [])}
        context_ru_pids = {p["paragraph_id"] for p in context_ru.get("paragraphs", [])}
        context_de_sources = {
            s for st in context_de.get("statements", []) for s in st.get("sources", [])
        }
        record(
            "TC-45",
            closed_pid not in context_de_pids
            and open_pid in context_de_pids
            and ids["closed"] not in context_de_sources
            and closed_pid in context_ru_pids,
            "контекст ассистента: абзац закрытого источника не попадает в paragraphs для DE, "
            "sources/evidence без него; для RU — попадает",
            {
                "DE_paragraphs": sorted(context_de_pids),
                "DE_sources": sorted(context_de_sources),
                "RU_paragraphs": sorted(context_ru_pids),
                "DE_statements": context_de.get("statements"),
            },
            evidence,
        )
        record(
            "TC-49",
            ids["closed"] not in context_de_sources
            and all(ids["closed"] not in st.get("sources", []) for st in context_de.get("statements", [])),
            "поле region в теле контекста знаний учитывается: источники закрытого источника "
            "не упомянуты в контексте для DE",
            {"sources": sorted(context_de_sources), "statements": context_de.get("statements")},
            evidence,
        )

        # --- ассистент: вопрос из DE и из РФ (UC-24, UC-26, UC-27, TC-47, TC-48, TC-50, TC-51) ---
        question = "Что говорится о рассудке и разуме?"
        events_de = ask_via(de_client, {"question": question}, de)
        time.sleep(0.5)
        prompt_de = answer_prompt(STAND)
        events_ru = ask_via(ru_client, {"question": question})
        time.sleep(0.5)
        prompt_ru = answer_prompt(STAND)
        record(
            "TC-50",
            CLOSED_MARKER not in prompt_de
            and ids["closed"] not in answer_sources(events_de)
            and "ЗЕТА-9" not in answer_text(events_de),
            "вопрос из DE: текста и ссылок закрытого источника нет ни в запросе к модели, ни в ответе",
            {
                "sources": sorted(answer_sources(events_de)),
                "marker_in_prompt": CLOSED_MARKER in prompt_de,
                "answer": answer_text(events_de)[:300],
                "stats": next((e.get("stats") for e in events_de if e["type"] == "done"), None),
            },
            evidence + [str(logs / "assistant.log"), str(logs / "llm.log")],
        )
        record(
            "TC-51",
            CLOSED_MARKER in prompt_ru and "ЗЕТА-9" in prompt_ru,
            "вопрос из РФ: текст закрытого источника попадает в контекст модели (как раньше)",
            {
                "marker_in_prompt": CLOSED_MARKER in prompt_ru,
                "sources": sorted(answer_sources(events_ru)),
                "prompt_excerpt": prompt_ru[:600],
            },
            evidence + [str(logs / "llm.log")],
        )
        record(
            "TC-47/TC-48",
            CLOSED_MARKER not in prompt_de and CLOSED_MARKER in prompt_ru,
            "регион из заголовка доходит до поиска: для DE закрытые абзацы не попали в контекст, "
            "для РФ попали",
            {
                "DE": CLOSED_MARKER in prompt_de,
                "RU": CLOSED_MARKER in prompt_ru,
                "sources_DE": sorted(answer_sources(events_de)),
                "sources_RU": sorted(answer_sources(events_ru)),
            },
            evidence,
        )
        # Без заголовка региона и со служебным XX — как неизвестный регион.
        events_none = ask_via(de_client, {"question": question}, {})
        time.sleep(0.5)
        prompt_none = answer_prompt(STAND)
        events_xx = ask_via(de_client, {"question": question}, service_codes)
        time.sleep(0.5)
        prompt_xx = answer_prompt(STAND)
        events_t1 = ask_via(de_client, {"question": question}, tor)
        time.sleep(0.5)
        prompt_t1 = answer_prompt(STAND)
        record(
            "EC-34/EC-44",
            CLOSED_MARKER not in prompt_none
            and CLOSED_MARKER not in prompt_xx
            and CLOSED_MARKER not in prompt_t1
            and all(ids["closed"] not in answer_sources(e) for e in (events_none, events_xx, events_t1)),
            "без заголовка региона, со служебными XX и T1 — неизвестный регион: закрытый источник "
            "не попадает в контекст модели",
            {
                "none_marker": CLOSED_MARKER in prompt_none,
                "XX_marker": CLOSED_MARKER in prompt_xx,
                "T1_marker": CLOSED_MARKER in prompt_t1,
            },
            evidence,
        )
        # Нижний регистр и пробелы в коде страны — это регион РФ.
        events_lower = ask_via(de_client, {"question": question}, {"CF-IPCountry": "ru"})
        time.sleep(0.5)
        prompt_lower = answer_prompt(STAND)
        record(
            "EC-44/lowercase",
            CLOSED_MARKER in prompt_lower,
            "код страны « ru » приводится к RU: закрытый источник снова в контексте",
            {"marker_in_prompt": CLOSED_MARKER in prompt_lower},
            evidence,
        )

        # --- выделение и source_id закрытого источника (UC-25, TC-52, TC-54) ---
        events_selection = ask_via(
            de_client,
            {
                "question": "Объясни этот фрагмент",
                "selection": CLOSED_PHRASE,
                "selection_paragraphs": [closed_pid],
                "source_id": ids["closed"],
                "context": "book",
            },
            de,
        )
        time.sleep(0.5)
        prompt_selection = answer_prompt(STAND)
        record(
            "TC-52",
            CLOSED_MARKER not in prompt_selection
            and ids["closed"] not in answer_sources(events_selection),
            "выделение из закрытого источника для DE: абзацы не попали в passages, текста закрытого "
            "источника нет в запросе к модели",
            {
                "marker_in_prompt": CLOSED_MARKER in prompt_selection,
                "sources": sorted(answer_sources(events_selection)),
                "prompt_excerpt": prompt_selection[:500],
            },
            evidence,
        )
        events_current = ask_via(
            de_client,
            {
                "question": question,
                "source_id": ids["closed"],
                "scope": "current",
            },
            de,
        )
        notice = [e for e in events_current if e["type"] == "notice"]
        record(
            "TC-54",
            any(e.get("kind") == "no_library_support" for e in notice)
            and ids["closed"] not in answer_sources(events_current),
            "scope=current и source_id закрытого источника для DE: ответ без опоры на библиотеку, "
            "ссылок на закрытый источник нет",
            {
                "notice": notice,
                "sources": sorted(answer_sources(events_current)),
                "stats": next((e.get("stats") for e in events_current if e["type"] == "done"), None),
            },
            evidence,
        )

        # --- регион не хранится между запросами (EC-37, EC-42, EC-43) ---
        again_de = card(proxy_url, de)
        again_ru = card(gateway)
        rows_again_de = rows_by_id(again_de).get(closed_statement, {})
        rows_again_ru = rows_by_id(again_ru).get(closed_statement, {})
        record(
            "EC-37/EC-43",
            rows_again_de.get("evidence") == []
            and rows_again_ru.get("evidence")
            and rows_by_id(card(proxy_url, de))[closed_statement]["evidence"] == [],
            "два запроса подряд с разными регионами: каждый считается по своему региону, "
            "состояние не переносится",
            {
                "DE": rows_again_de.get("evidence"),
                "RU": rows_again_ru.get("evidence"),
            },
            evidence,
        )
        repeated = ask_via(de_client, {"question": question}, de)
        time.sleep(0.5)
        prompt_repeat = answer_prompt(STAND)
        record(
            "EC-42",
            CLOSED_MARKER not in prompt_repeat
            and ids["closed"] not in answer_sources(repeated),
            "повтор вопроса из DE детерминирован: регион читается из заголовка каждый раз",
            {"marker_in_prompt": CLOSED_MARKER in prompt_repeat},
            evidence,
        )

        # --- grounding.verify: ссылка на непереданный абзац (TC-53, R23) ---
        config = ROUND / "llm-invented.yaml"
        base = (REPO / "config" / "llm.demo.yaml").read_text(encoding="utf-8")
        config.write_text(
            base.replace(
                "[1].",
                "[99].",
            ),
            encoding="utf-8",
        )
        llm_port = free_port()
        for stale in HERE.glob("invented*.db*"):
            stale.unlink()
        llm_log = open(ROUND / "llm-invented.log", "w", encoding="utf-8")  # noqa: SIM115
        llm_proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "philograph.llm.main:app",
                "--port",
                str(llm_port),
                "--log-level",
                "warning",
            ],
            cwd=str(REPO),
            env={
                **os.environ,
                "PHILOGRAPH_LLM_CONFIG": str(config),
                # Своя база: иначе кэш ответов демо-модели вернёт прежнюю ссылку [1].
                "PHILOGRAPH_DATABASE_URL": f"sqlite:///{(HERE / 'invented.db').as_posix()}",
            },
            stdout=llm_log,
            stderr=subprocess.STDOUT,
        )
        inv_port = free_port()
        inv_log = open(ROUND / "assistant-invented.log", "w", encoding="utf-8")  # noqa: SIM115
        inv_proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "philograph.assistant.main:app",
                "--port",
                str(inv_port),
                "--log-level",
                "warning",
            ],
            cwd=str(REPO),
            env={
                **os.environ,
                "PHILOGRAPH_LLM_URL": f"http://127.0.0.1:{llm_port}",
                "PHILOGRAPH_SEARCH_URL": f"http://127.0.0.1:{port_of['search']}",
                "PHILOGRAPH_LIBRARY_URL": library,
                "PHILOGRAPH_KNOWLEDGE_URL": knowledge,
            },
            stdout=inv_log,
            stderr=subprocess.STDOUT,
        )
        try:
            ready = wait_ready(f"http://127.0.0.1:{inv_port}")
            invented = ask(
                f"http://127.0.0.1:{inv_port}/v1/ask",
                {"question": question},
                {"X-Philograph-Region": "DE"},
            ) if ready else []
            stats = next((e.get("stats") for e in invented if e["type"] == "done"), None)
            fragments = [e for e in invented if e["type"] == "fragment"]
            invented_log = (ROUND / "assistant-invented.log").read_text(encoding="utf-8")
            record(
                "TC-53",
                ready
                and bool(fragments)
                and all(not f.get("citations") for f in fragments)
                and bool(stats and stats.get("removed_citations", 0) >= 1)
                and "assistant.citation.invented" in invented_log,
                "ссылка модели на непереданный абзац удалена, фрагмент неподтверждён "
                "(второй слой grounding.verify)",
                {
                    "ready": ready,
                    "fragments": fragments,
                    "stats": stats,
                    "invented_event": "assistant.citation.invented" in invented_log,
                },
                evidence + [str(ROUND / "assistant-invented.log"), str(ROUND / "llm-invented.log")],
            )
        finally:
            for proc in (inv_proc, llm_proc):
                proc.terminate()
                try:
                    proc.wait(10)
                except Exception:  # noqa: BLE001
                    proc.kill()
            inv_log.close()
            llm_log.close()

        # --- браузер: карточка у читателя из РФ и из DE ---
        browser_checks(
            gateway,
            proxy_url,
            ids["open"],
            gusserl,
            closed_pid,
            open_pid,
            CHECKS,
        )

        # --- библиотека недоступна: 503 knowledge_unavailable (TC-46, EC-41) ---
        library_proc = stack.processes["library"]
        library_proc.terminate()
        try:
            library_proc.wait(10)
        except Exception:  # noqa: BLE001
            library_proc.kill()
        time.sleep(1.0)
        with httpx.Client(timeout=60) as client:
            unavailable = client.get(
                proxy_url + f"/api/knowledge/v1/entities/{gusserl}/card?generation=false",
                headers=de,
            )
            body = unavailable.json() if unavailable.headers.get("content-type", "").startswith(
                "application/json"
            ) else {}
            context_unavailable = client.post(
                knowledge + "/v1/internal/assistant/context",
                json={"text": "Гуссерль", "steps": ["entities"], "region": "DE"},
            )
            answer_by_search = de_client.post(
                "/api/assistant/v1/ask", json={"question": question}, headers=de
            ).text
        answer_events = [
            json.loads(line) for line in answer_by_search.splitlines() if line.strip()
        ]
        assistant_log = (logs / "assistant.log").read_text(encoding="utf-8", errors="replace")
        record(
            "TC-46",
            unavailable.status_code == 503
            and body.get("kind") == "knowledge_unavailable"
            and context_unavailable.status_code == 503,
            "недоступная библиотека при internal/access: сервис знаний отвечает 503 "
            "knowledge_unavailable и не отдаёт непроверенные подтверждения",
            {
                "status": unavailable.status_code,
                "body": body,
                "context_status": context_unavailable.status_code,
                "context_body": context_unavailable.text[:300],
            },
            evidence + [str(logs / "knowledge.log")],
        )
        record(
            "EC-41/knowledge",
            answer_events
            and not any(e["type"] == "error" for e in answer_events)
            and "knowledge_unavailable" in assistant_log,
            "сервис знаний недоступен: шаг онтологии пропущен, ассистент отвечает по поиску",
            {
                "types": [e["type"] for e in answer_events],
                "notice": [e for e in answer_events if e["type"] == "notice"],
                "stats": next((e.get("stats") for e in answer_events if e["type"] == "done"), None),
            },
            evidence + [str(logs / "assistant.log")],
        )

        # --- поиск недоступен: ответ unavailable (EC-41) ---
        search_proc = stack.processes["search"]
        search_proc.terminate()
        try:
            search_proc.wait(10)
        except Exception:  # noqa: BLE001
            search_proc.kill()
        time.sleep(1.0)
        search_down = de_client.post(
            "/api/assistant/v1/ask", json={"question": question}, headers=de
        ).text
        search_events = [json.loads(line) for line in search_down.splitlines() if line.strip()]
        record(
            "EC-41/search",
            any(
                e.get("type") == "unavailable" and e.get("reason") == "search_unavailable"
                for e in search_events
            ),
            "поиск недоступен: ответ unavailable с reason search_unavailable",
            {"events": search_events[:3]},
            evidence + [str(logs / "assistant.log")],
        )
    finally:
        unique = {(c["id"], c["expected"], c["actual"]): c for c in CHECKS}
        CHECKS[:] = list(unique.values())
        proxy_proc.terminate()
        try:
            proxy_proc.wait(10)
        except Exception:  # noqa: BLE001
            proxy_proc.kill()
        report = {
            "stack": {
                "url": gateway,
                "proxy_url": proxy_url,
                "ports": port_of,
                "sources": ids,
                "seeded": {k: v for k, v in seeded.items()},
                "logs": str(logs),
            },
            "checks": CHECKS,
            "failures": len([c for c in CHECKS if not c["ok"]]),
        }
        (ROUND / "live-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        stack.stop()
    print("ИТОГО проверок:", len(CHECKS), "провалов:", report["failures"])
    return 1 if report["failures"] else 0


# --- 4. браузер --------------------------------------------------------------------


def browser_checks(  # noqa: PLR0913
    gateway: str,
    proxy_url: str,
    open_source: str,
    entity_id: str,
    closed_pid: str,
    open_pid: str,
    results: list[dict],
) -> None:
    from playwright.sync_api import sync_playwright

    SHOTS.mkdir(parents=True, exist_ok=True)
    console_errors: list[str] = []
    failed_requests: list[str] = []

    def attach(page) -> None:
        page.on(
            "console",
            lambda msg: console_errors.append(f"{msg.type}: {msg.text}")
            if msg.type == "error"
            else None,
        )
        page.on("pageerror", lambda exc: console_errors.append(f"pageerror: {exc}"))
        page.on("requestfailed", lambda req: failed_requests.append(f"{req.url} {req.failure}"))

    def open_card(page, base: str, shot_name: str) -> dict:
        page.goto(base + f"/read/{open_source}", wait_until="networkidle")
        mention = page.locator(f'span.pg-mention[data-entity="{entity_id}"]').first
        mention.wait_for(timeout=30000)
        mention.click()
        page.wait_for_selector(".card-popup__facts", timeout=30000)
        page.locator('button:has-text("Открыть карточку")').first.click()
        page.wait_for_selector(".card-section", timeout=30000)
        page.wait_for_timeout(800)
        shot = SHOTS / shot_name
        page.screenshot(path=str(shot), full_page=True)
        citations = page.locator('a.citation[href^="/p/"]').all()
        hrefs = [c.get_attribute("href") for c in citations]
        body = page.inner_text("body")
        where = page.locator('[data-section="where"]')
        where_text = where.inner_text() if where.count() else ""
        return {
            "shot": str(shot),
            "citations": hrefs,
            "where_text": where_text,
            "body": body,
            "console_errors": list(console_errors),
            "failed_requests": list(failed_requests),
        }

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ru_context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="ru-RU")
        ru_page = ru_context.new_page()
        attach(ru_page)
        try:
            ru = open_card(ru_page, gateway, "UC-20-1-card-ru.png")
            results.append(
                record(
                    "UC-20/RU-browser",
                    f"/p/{closed_pid}" in ru["citations"]
                    and "Брентано" in ru["body"]
                    and RU_TITLE in ru["where_text"],
                    "читатель из РФ: карточка показывает подтверждение закрытого источника "
                    "ссылкой /p/<id> и «где читать» по обоим источникам",
                    {
                        "citations": ru["citations"],
                        "where": ru["where_text"],
                        "console_errors": ru["console_errors"][:5],
                    },
                    [ru["shot"]],
                )
            )
        except Exception as exc:  # noqa: BLE001
            shot = SHOTS / "UC-20-1-card-ru-FAILED.png"
            try:
                ru_page.screenshot(path=str(shot), full_page=True)
            except Exception:  # noqa: BLE001
                pass
            results.append(
                record(
                    "UC-20/RU-browser",
                    False,
                    "читатель из РФ: карточка показывает подтверждение закрытого источника",
                    {"error": f"{type(exc).__name__}: {exc}", "console": console_errors[:5]},
                    [str(shot)],
                )
            )
        ru_context.close()

        de_context = browser.new_context(
            viewport={"width": 1440, "height": 1000},
            locale="ru-RU",
            extra_http_headers={"CF-IPCountry": "DE"},
        )
        de_page = de_context.new_page()
        attach(de_page)
        try:
            de = open_card(de_page, proxy_url, "UC-20-2-card-de.png")
            results.append(
                record(
                    "UC-20/DE-browser",
                    f"/p/{closed_pid}" not in de["citations"]
                    and "Брентано" in de["body"]
                    and RU_TITLE not in de["where_text"]
                    and "ЗЕТА-9" not in de["body"],
                    "читатель из DE: утверждение и связь на месте, цитаты, ссылки /p/ и атрибуции "
                    "закрытого источника скрыты; «где читать» — только открытый источник",
                    {
                        "citations": de["citations"],
                        "where": de["where_text"],
                        "console_errors": de["console_errors"][:5],
                    },
                    [de["shot"]],
                )
            )
        except Exception as exc:  # noqa: BLE001
            shot = SHOTS / "UC-20-2-card-de-FAILED.png"
            try:
                de_page.screenshot(path=str(shot), full_page=True)
            except Exception:  # noqa: BLE001
                pass
            results.append(
                record(
                    "UC-20/DE-browser",
                    False,
                    "читатель из DE: карточка без подтверждений закрытого источника",
                    {"error": f"{type(exc).__name__}: {exc}", "console": console_errors[:5]},
                    [str(shot)],
                )
            )
        de_context.close()
        browser.close()

    results.append(
        record(
            "EC-console",
            not console_errors and not failed_requests,
            "в браузере нет ошибок консоли и сетевых сбоев",
            {"console_errors": console_errors[:10], "failed_requests": failed_requests[:10]},
            [str(SHOTS / "UC-20-1-card-ru.png")],
        )
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        raise SystemExit(2) from None
