"""Раунд 7: независимый стенд проверки ru-only-sources — исправление F-1 (TC-65) и регресс.

Основа — стенд раунда 6 (``qa/round-6/harness/live_checks.py``); проверки группы 7 оставлены
как регресс. Браузерная часть заменена на ``browser_checks_round7``: две пометки за один ход
(``found_not_retold`` со ссылкой и ``no_library_support``), переход по ссылке на абзац, старая
сессия формата 3 с единственным ``message`` и обычные пометки (``no_library_support``,
``no_answer``, ошибка соединения).

Раунд 6: независимый стенд проверки ru-only-sources (группа 7 и данные задачи 8.4).

Поднимает ``scripts/dev_stack.py`` в-process (без демо-источников), готовит три своих источника
через настоящий конвейер библиотеки:

- ``open`` — вид без регионов, внешняя обработка разрешена (контроль, «как раньше»);
- ``nonext`` — **настоящий** вид ``public-domain-ru`` из ``sources/licenses.yaml``: регионы ``[RU]``,
  ``external_processing: false`` (задача 8.4);
- ``extru`` — вид ``[RU]`` с ``external_processing: true`` (обратная совместимость).

События публикации передаются в очередь после старта стека: индексацию, извлечение знаний и
упоминания делает настоящий worker. Проверяются через настоящие HTTP-интерфейсы и браузер:

- индексация: ``docs.external = false``, ``embedded = false``, эмбеддер не зовётся (TC-56, UC-30);
- поиск: RU видит абзац с ``external: false``, DE и запрос без региона — нет (TC-57);
- ответ ассистента RU: текст без внешней обработки не уходит модели, в потоке
  ``found_not_retold`` со ссылками (TC-58, TC-59, TC-64, EC-46, EC-49);
- упоминания: для источника без внешней обработки модель-разрешитель не вызывается, упоминание
  остаётся неоднозначным; для ``external_processing: true`` — «как раньше» (TC-61, TC-63);
- читатель из DE: источник закрыт целиком (регионы), текста нет нигде (UC-28/DE);
- клиент: пометка со ссылкой, клик ведёт на абзац (TC-62, EC-50, EC-51);
- данные 8.4: ``catalog validate`` и смена учёта при ``sync`` (ensure_license_kinds).

Код, тесты и спецификации не меняются: артефакты только в ``qa/round-6/``.
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
NONEXT_TITLE = "Закрытый учебник без внешней обработки"
EXTRU_TITLE = "Закрытый учебник с внешней обработкой"
NONEXT_MARK = "СИГМА-3"
OPEN_MARK = "ОМЕГА-7"
EXTRU_MARK = "ДЕЛЬТА-5"

NONEXT_PHRASE = (
    "Каллистика — учение о прекрасном. Рассудок даёт правила. "
    f"Закрытая деталь {NONEXT_MARK}: рассудок подчиняет разум правилам."
)
OPEN_PHRASE = (
    "Рассудок и разум. Открытая деталь "
    f"{OPEN_MARK}: разум задаёт принципы, а рассудок следует правилам."
)
EXTRU_PHRASE = (
    "Гилеморфизм у Аристотеля. Рассудок и разум. "
    f"Закрытая деталь {EXTRU_MARK}: внешняя обработка разрешена."
)
# Однозначное упоминание в источнике без внешней обработки: словарный поиск упоминаний
# локален и обязан продолжать работать (спека, сценарий «Разбор упоминаний»).
NONEXT_PLAIN_MENTION = "Кант"

FILES = {
    "nonext.txt": (
        "Глава 1. Рассудок и разум\n\n"
        f"{NONEXT_PHRASE}\n\n"
        f"Второй абзац: {NONEXT_PLAIN_MENTION} писал о рассудке и правилах.\n"
    ).encode(),
    "open.txt": (
        "Глава 1. Рассудок и разум\n\n"
        f"{OPEN_PHRASE}\n\n"
        "Второй абзац открытого источника: рассудок и разум у Канта.\n"
    ).encode(),
    "extru.txt": (
        "Глава 1. Рассудок и разум\n\n"
        f"{EXTRU_PHRASE}\n\n"
        "Второй абзац: Бэкон писал об оптике.\n"
    ).encode(),
}

QUESTIONS = {
    "only": "Что такое Каллистика и какие у неё правила?",
    "mixed": "Как соотносятся рассудок и разум?",
    "ext": "Что такое Гилеморфизм у Аристотеля?",
    "none": "Сколько весит луна в граммах?",
}

CHECKS: list[dict] = []
SEEDED: dict[str, str] = {}


def record(cid: str, ok: bool, expected: str, actual, evidence=None) -> dict:
    item = {
        "id": cid,
        "ok": bool(ok),
        "expected": expected,
        "actual": actual
        if isinstance(actual, str)
        else json.dumps(actual, ensure_ascii=False, default=str),
        "evidence": evidence or [],
    }
    CHECKS.append(item)
    print(("PASS " if ok else "FAIL ") + cid + " :: " + item["actual"][:300])
    return item


# --- 1. данные задачи 8.4 ----------------------------------------------------------


def catalog_check() -> dict:
    """Команда проверки каталога из задачи 8.4 и данные вида ``public-domain-ru``."""
    from philograph.library.catalog import model

    proc = subprocess.run(
        [sys.executable, "-m", "philograph.library.catalog", "validate"],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    catalog = model.Catalog.load(REPO / "sources" / "catalog.yaml")
    try:
        kinds = {k["code"]: k for k in catalog.licenses()}
    except Exception as exc:  # noqa: BLE001
        kinds = {}
        print("licenses.yaml:", exc)
    kind = kinds.get("public-domain-ru", {})
    return {
        "validate_exit": proc.returncode,
        "validate_tail": ((proc.stdout or "") + (proc.stderr or "")).strip()[-600:],
        "kind": kind,
        "codes": sorted(kinds),
    }


def sync_accounting() -> dict:
    """Смена учёта при ``sync``: старый вид без регионов → настоящие данные licenses.yaml."""
    from philograph.library import schema as lib_schema
    from philograph.library.catalog import model
    from philograph.library.catalog.fetcher import Fetcher
    from philograph.library.catalog.service import CatalogService
    from philograph.library.processing import Pipeline
    from philograph.library.registry import License, Registry
    from philograph.operator.access import migrations as op_migrations
    from philograph.platform.db import make_engine
    from philograph.platform.files import FileStore
    from philograph.platform.queue import migrations as q_migrations

    data = HERE / "sync-accounting"
    if data.exists():
        shutil.rmtree(data, ignore_errors=True)
    data.mkdir(parents=True, exist_ok=True)
    db = f"sqlite:///{(data / 'lib.db').as_posix()}"
    engine = make_engine(db, [m.schema for m in (lib_schema.migrations, op_migrations, q_migrations)])
    for m in (lib_schema.migrations, op_migrations, q_migrations):
        m.upgrade(engine)
    registry = Registry(engine)
    # Старое состояние: вид без регионов и с разрешённой внешней обработкой.
    old = {"display": True, "external_processing": True, "quoting": True}
    registry.add_license_kind("public-domain-ru", "Старые данные", None, dict(old))
    pipeline = Pipeline(registry, FileStore(data / "files"), lambda spec: FILES[spec["path"]])
    source_id = registry.register(
        "qa",
        title="Источник старого вида",
        authors=["QA тестировщик"],
        year=2026,
        language="ru",
        kind="textbook",
        license=License("public-domain-ru", "public_domain", author_death_years=[1900]),
        scope="public",
        files=[{"name": "open.txt", "path": "open.txt"}],
        confirm_duplicate=True,
    )
    version = pipeline.start("qa", source_id)
    registry.publish("qa", version)
    before = {
        "regions": sorted(registry.regions(source_id) or []),
        "permissions": registry.permissions(source_id),
    }
    catalog = model.Catalog.load(REPO / "sources" / "catalog.yaml")
    service = CatalogService(catalog, registry, pipeline, Fetcher())
    service.ensure_license_kinds()  # то же, что делает sync
    kinds = registry.license_kinds()
    pending = [
        item
        for item in registry.outbox_pending()
        if item["kind"] == "source.access_changed"
        and item["payload"].get("source_id") == source_id
    ]
    return {
        "source_id": source_id,
        "before": before,
        "after": {
            "regions": sorted(registry.regions(source_id) or []),
            "permissions": registry.permissions(source_id),
        },
        "kind_regions": kinds.get("public-domain-ru", {}).get("regions"),
        "kind_permissions": kinds.get("public-domain-ru", {}).get("permissions"),
        "events": [item["payload"] for item in pending],
    }


# --- 2. источники тестировщика до старта стенда ------------------------------------


def pre_seed(data: Path) -> dict[str, str]:
    from philograph.library import schema as lib_schema
    from philograph.library.catalog import model
    from philograph.library.catalog.fetcher import Fetcher
    from philograph.library.catalog.service import CatalogService
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
    registry.add_license_kind("qa-ru-ext", "Только РФ, внешняя обработка (QA)", None, dict(permissions), regions=["RU"])
    pipeline = Pipeline(registry, FileStore(data / "files"), lambda spec: FILES[spec["path"]])
    # Настоящие данные каталога: вид public-domain-ru приходит из sources/licenses.yaml.
    catalog = model.Catalog.load(REPO / "sources" / "catalog.yaml")
    CatalogService(catalog, registry, pipeline, Fetcher()).ensure_license_kinds()
    ids: dict[str, str] = {}
    versions: dict[str, str] = {}
    for key, title, kind, path in (
        ("open", OPEN_TITLE, "qa-open", "open.txt"),
        ("nonext", NONEXT_TITLE, "public-domain-ru", "nonext.txt"),
        ("extru", EXTRU_TITLE, "qa-ru-ext", "extru.txt"),
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
    SEEDED.update(seed_ontology(data))
    return {**ids, **{f"version_{k}": v for k, v in versions.items()}}


def seed_ontology(data: Path) -> dict[str, str]:
    """Два однофамильца «Бэкон» (неоднозначное упоминание) и однозначный «Кант»."""
    from philograph.knowledge import schema as ks
    from philograph.knowledge.entities import Entities
    from philograph.knowledge.registry import OntologyRegistry
    from philograph.platform.db import make_engine

    db = f"sqlite:///{(data / 'stack.db').as_posix()}"
    engine = make_engine(db, [ks.SCHEMA])
    ks.migrations.upgrade(engine)
    registry = OntologyRegistry(engine)
    registry.load_defaults()
    entities = Entities(engine, registry)
    bacon_a = entities.create("person", [("ru", "Бэкон", "primary")])
    bacon_b = entities.create("person", [("ru", "Бэкон", "primary")])
    kant = entities.create("person", [("ru", NONEXT_PLAIN_MENTION, "primary")])
    return {"bacon_a": bacon_a, "bacon_b": bacon_b, "kant": kant}


# --- 3. помощники стенда -----------------------------------------------------------


def db_engine(data: Path, schemas):
    from philograph.platform.db import make_engine

    return make_engine(f"sqlite:///{(data / 'stack.db').as_posix()}", schemas)


def all_prompts(data: Path) -> list[dict]:
    from sqlalchemy import select

    from philograph.llm import store

    engine = db_engine(data, [store.SCHEMA])
    with engine.begin() as conn:
        rows = conn.execute(select(store.calls).order_by(store.calls.c.id.desc()).limit(200))
        return [dict(r) for r in rows.mappings()]


def answer_prompt(data: Path, question: str) -> str:
    """Запрос основной модели для ответа на конкретный вопрос."""
    head = question[:18]
    for row in all_prompts(data):
        if (
            (row.get("template") or "").startswith("assistant.answer")
            and row.get("caller") == "assistant"
            and head in (row.get("prompt_text") or "")
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


def ask(url: str, body: dict, headers: dict | None = None, timeout: float = 120) -> list[dict]:
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

    client = httpx.Client(base_url=url, headers=headers or {}, timeout=120)
    client.get("/")
    return client


def ask_via(client, body: dict, headers: dict | None = None) -> list[dict]:
    events: list[dict] = []
    with client.stream("POST", "/api/assistant/v1/ask", json=body, headers=headers or {}) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if line.strip():
                events.append(json.loads(line))
    return events


def notices(events: list[dict]) -> list[dict]:
    return [e for e in events if e.get("type") == "notice"]


def citations(events: list[dict]) -> list[str]:
    found: list[str] = []
    for event in events:
        for citation in event.get("citations") or []:
            if isinstance(citation, dict) and citation.get("paragraph_id"):
                found.append(citation["paragraph_id"])
    return found


# --- 4. проверки -------------------------------------------------------------------


def main() -> int:  # noqa: C901, PLR0915
    import httpx

    if STAND.exists():
        shutil.rmtree(STAND, ignore_errors=True)
    STAND.mkdir(parents=True, exist_ok=True)
    ids = pre_seed(STAND)
    print("источники:", ids)
    counts = catalog_check()
    sync = sync_accounting()
    print("каталог:", counts["validate_exit"], counts["kind"].get("regions"))
    print("sync:", json.dumps(sync["after"], ensure_ascii=False))

    # --- 8.4: данные и смена учёта при sync ---
    kind = counts["kind"]
    record(
        "TC-8.4/data",
        counts["validate_exit"] == 0
        and kind.get("regions") == ["RU"]
        and kind.get("permissions", {}).get("external_processing") is False
        and kind.get("permissions", {}).get("display") is True,
        "`catalog validate` зелёный; у вида public-domain-ru регионы [RU], external_processing "
        "false, display true",
        {
            "validate_exit": counts["validate_exit"],
            "validate_tail": counts["validate_tail"],
            "kind": kind,
        },
        [str(ROUND / "catalog-validate.log")],
    )
    record(
        "TC-8.4/sync",
        sync["before"]["regions"] == []
        and sync["after"]["regions"] == ["RU"]
        and sync["after"]["permissions"].get("external_processing") is False
        and any(
            e.get("regions") == ["RU"]
            and e.get("permissions", {}).get("external_processing") is False
            for e in sync["events"]
        ),
        "sync вида меняет учёт источника: действующие регионы [RU], внешняя обработка "
        "выключена, записано source.access_changed",
        sync,
        [str(ROUND / "sync-accounting.json")],
    )

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
    search_url = f"http://127.0.0.1:{port_of['search']}"
    knowledge = f"http://127.0.0.1:{port_of['knowledge']}"
    assistant = f"http://127.0.0.1:{port_of['assistant']}"
    print("стенд:", gateway, port_of)

    logs = STAND / "logs"
    evidence = [str(ROUND / "live-report.json"), str(logs)]

    # События публикации — в очередь после старта стека: их обрабатывает настоящий worker.
    from philograph.library import schema as lib_schema
    from philograph.library.processing import Pipeline
    from philograph.library.registry import Registry
    from philograph.operator.access import migrations as op_migrations
    from philograph.platform.files import FileStore
    from philograph.platform.queue import Queue
    from philograph.platform.queue import migrations as q_migrations

    engine = db_engine(
        STAND, [m.schema for m in (lib_schema.migrations, op_migrations, q_migrations)]
    )
    pipeline = Pipeline(Registry(engine), FileStore(STAND / "files"), lambda spec: FILES[spec["path"]])
    print("события в очередь:", pipeline.dispatch_outbox(Queue(engine)))

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

    try:
        with httpx.Client(timeout=30) as client:
            published = client.get(library + "/api/v1/internal/published").json()
            version_of = {row["source_id"]: row["version_id"] for row in published}
            paragraphs: dict[str, list[dict]] = {}
            payloads: dict[str, dict] = {}
            for source_id in (ids["open"], ids["nonext"], ids["extru"]):
                payload = client.get(
                    library + f"/api/v1/internal/versions/{version_of[source_id]}/paragraphs"
                ).json()
                payloads[source_id] = payload
                paragraphs[source_id] = payload["paragraphs"]
        pids = {key: [p["id"] for p in paragraphs[source]] for key, source in ids.items() if source in paragraphs}
        print("абзацы:", {k: len(v) for k, v in pids.items()})

        # Ждём индексацию всех трёх источников и упоминания.
        deadline = time.time() + 150
        indexed: set[str] = set()
        mentions_ready = False
        while time.time() < deadline:
            with httpx.Client(timeout=30) as client:
                found = client.post(
                    search_url + "/v1/search",
                    json={"query": "рассудок и разум", "region": "RU", "limit": 20},
                ).json()["results"]
            indexed = {r["source_id"] for r in found}
            knowledge_events = [
                line
                for line in (logs / "knowledge.log").read_text(encoding="utf-8", errors="replace").splitlines()
                if '"event"' in line
            ]
            mentions_ready = any('"knowledge.mentions.' in line for line in knowledge_events)
            if {ids["open"], ids["nonext"], ids["extru"]} <= indexed and mentions_ready:
                break
            time.sleep(1.0)
        print("индексация:", sorted(indexed))
        time.sleep(2.0)

        search_calls = [
            json.loads(line)
            for line in (logs / "search.log").read_text(encoding="utf-8", errors="replace").splitlines()
            if line.startswith("{")
        ]
        knowledge_log = [
            json.loads(line)
            for line in (logs / "knowledge.log").read_text(encoding="utf-8", errors="replace").splitlines()
            if line.startswith("{")
        ]

        with httpx.Client(timeout=30) as client:
            search_ru = client.post(
                search_url + "/v1/search",
                json={"query": "Каллистика прекрасном", "region": "RU", "limit": 10},
            ).json()
            search_de = client.post(
                search_url + "/v1/search",
                json={"query": "Каллистика прекрасном", "region": "DE", "limit": 10},
            ).json()
            search_none = client.post(
                search_url + "/v1/search",
                json={"query": "Каллистика прекрасном", "limit": 10},
            ).json()
            search_ru_mixed = client.post(
                search_url + "/v1/search",
                json={"query": "Каллистика рассудок", "region": "RU", "limit": 10},
            ).json()

        # --- TC-56 / UC-30: индексация без внешней обработки ---
        from sqlalchemy import select

        from philograph.search import schema as search_schema

        se = db_engine(STAND, [search_schema.SCHEMA])
        with se.begin() as conn:
            rows = conn.execute(
                select(
                    search_schema.docs.c.source_id,
                    search_schema.docs.c.external,
                    search_schema.docs.c.embedded,
                )
            ).all()
        by_source: dict[str, list[tuple[bool, bool]]] = {}
        for source_id, external, embedded in rows:
            by_source.setdefault(source_id, []).append((bool(external), bool(embedded)))
        nonext_rows = by_source.get(ids["nonext"], [])
        open_rows = by_source.get(ids["open"], [])
        record(
            "TC-56",
            bool(nonext_rows)
            and all(not external and not embedded for external, embedded in nonext_rows)
            and bool(open_rows)
            and all(embedded for _, embedded in open_rows),
            "абзацы источника без внешней обработки: docs.external = false, embedded = false; "
            "у открытого источника они в смысловом индексе; событие external_forbidden",
            {
                "nonext": nonext_rows,
                "open": open_rows,
                "forbidden_events": [
                    e for e in search_calls if e.get("event") == "search.index.external_forbidden"
                ][:3],
            },
            [str(logs / "search.log"), str(logs / "library.log")],
        )
        record(
            "EC-48",
            bool(nonext_rows)
            and all(not embedded for _, embedded in nonext_rows)
            and not any(e.get("event") == "search.index.embed_failed" for e in search_calls),
            "индексация не зовёт эмбеддер и не падает: строки есть, embedded = false",
            {"nonext": nonext_rows},
            [str(logs / "search.log")],
        )

        # --- TC-57 / UC-30: поиск по регионам ---
        def found_ids(payload: dict) -> dict[str, str]:
            return {r["paragraph_id"]: r for r in payload["results"]}

        ru_rows = found_ids(search_ru)
        de_rows = found_ids(search_de)
        no_rows = found_ids(search_none)
        nonext_pid = pids["nonext"][0]
        record(
            "TC-57",
            nonext_pid in ru_rows
            and ru_rows[nonext_pid].get("external") is False
            and nonext_pid not in de_rows
            and nonext_pid not in no_rows
            and any(r["source_id"] == ids["nonext"] for r in search_ru_mixed["results"]),
            "поиск из РФ отдаёт абзац с external: false; из DE и без региона — не отдаёт",
            {
                "ru": ru_rows.get(nonext_pid),
                "de_has": nonext_pid in de_rows,
                "none_has": nonext_pid in no_rows,
                "semantic_used_ru": search_ru.get("semantic_used"),
                "mixed_has_nonext": [
                    r["source_id"] for r in search_ru_mixed["results"]
                ],
            },
            evidence,
        )

        # --- ответы ассистента (RU — запасной регион стенда) ---
        ru_client = session(gateway)
        events_mixed = ask_via(ru_client, {"question": QUESTIONS["only"]})
        prompt_mixed = answer_prompt(STAND, QUESTIONS["only"])
        events_ext = ask_via(ru_client, {"question": QUESTIONS["ext"]})
        prompt_ext = answer_prompt(STAND, QUESTIONS["ext"])
        events_none = ask_via(ru_client, {"question": QUESTIONS["none"]})
        prompt_none = answer_prompt(STAND, QUESTIONS["none"])
        events_current = ask_via(
            ru_client,
            {
                "question": QUESTIONS["only"],
                "scope": "current",
                "source_id": ids["nonext"],
            },
        )
        prompt_current = answer_prompt(STAND, QUESTIONS["only"])

        def notice_kinds(events: list[dict]) -> list[str]:
            return [n.get("kind") for n in notices(events)]

        mixed_hidden = [
            n for n in notices(events_mixed) if n.get("kind") == "found_not_retold"
        ]
        record(
            "TC-58",
            bool(mixed_hidden)
            and NONEXT_MARK not in prompt_mixed
            and nonext_pid
            in [s.get("paragraph_id") for s in (mixed_hidden[0].get("suggestions") or [])]
            and nonext_pid not in citations(events_mixed),
            "вопрос из РФ, лучший абзац без внешней обработки: текста нет в промпте, "
            "в потоке found_not_retold со ссылкой, в citations его нет",
            {
                "notices": notice_kinds(events_mixed),
                "suggestions": [n.get("suggestions") for n in mixed_hidden],
                "citations": citations(events_mixed),
                "prompt_has_mark": NONEXT_MARK in prompt_mixed,
                "prompt_tail": prompt_mixed[-400:],
            },
            evidence + [str(logs / "assistant.log"), str(logs / "llm.log")],
        )
        record(
            "TC-59",
            bool(mixed_hidden)
            and OPEN_MARK in prompt_mixed
            and NONEXT_MARK not in prompt_mixed
            and nonext_pid
            in [s.get("paragraph_id") for s in (mixed_hidden[0].get("suggestions") or [])],
            "смешанная выдача: открытый абзац уходит модели, абзац без внешней обработки — "
            "только ссылкой с пометкой",
            {
                "notices": notice_kinds(events_mixed),
                "suggestions": [n.get("suggestions") for n in mixed_hidden],
                "open_mark_in_prompt": OPEN_MARK in prompt_mixed,
                "nonext_mark_in_prompt": NONEXT_MARK in prompt_mixed,
                "prompt_tail": prompt_mixed[-500:],
            },
            evidence + [str(logs / "llm.log")],
        )
        done_current = next((e for e in events_current if e.get("type") == "done"), {})
        current_hidden = [
            n for n in notices(events_current) if n.get("kind") == "found_not_retold"
        ]
        record(
            "TC-64",
            notice_kinds(events_current)[:2] == ["found_not_retold", "no_library_support"]
            and done_current.get("passages") == 0
            and bool(current_hidden)
            and not any(
                text for text in [NONEXT_MARK, OPEN_MARK, EXTRU_MARK] if text in prompt_current
            ),
            "найдены только непересказываемые абзацы: контекст модели пуст, в потоке "
            "found_not_retold и no_library_support",
            {
                "notices": notice_kinds(events_current),
                "passages": done_current.get("passages"),
                "suggestions": [n.get("suggestions") for n in current_hidden],
                "prompt_has_mark": NONEXT_MARK in prompt_current,
                "prompt_len": len(prompt_current),
            },
            evidence,
        )
        events_strict = ask_via(
            ru_client,
            {
                "question": QUESTIONS["only"],
                "scope": "current",
                "source_id": ids["nonext"],
                "sources_only": True,
            },
        )
        record(
            "EC-47",
            notice_kinds(events_strict)[:1] == ["found_not_retold"]
            and any(e.get("type") == "no_answer" for e in events_strict),
            "«только по источникам»: все найденные абзацы непересказываемые — пометка со "
            "ссылками и no_answer",
            {
                "types": [e.get("type") for e in events_strict],
                "notices": notice_kinds(events_strict),
            },
            evidence,
        )
        record(
            "EC-49",
            notice_kinds(events_repeat := ask_via(ru_client, {"question": QUESTIONS["only"]}))[:2]
            == notice_kinds(events_mixed)[:2]
            and [s.get("paragraph_id") for n in notices(events_repeat) for s in n.get("suggestions") or []]
            == [s.get("paragraph_id") for n in notices(events_mixed) for s in n.get("suggestions") or []],
            "повтор вопроса: регион и признак читаются на каждый запрос, выдача та же",
            {
                "repeat": notice_kinds(events_repeat),
                "first": notice_kinds(events_mixed),
            },
            evidence,
        )
        record(
            "TC-63",
            EXTRU_MARK in prompt_ext
            and not any(n.get("kind") == "found_not_retold" for n in notices(events_ext))
            and not any(
                e.get("event") == "knowledge.extraction.skipped"
                and e.get("source_id") == ids["extru"]
                for e in knowledge_log
            ),
            "источник с external_processing: true ведёт себя как раньше: текст уходит модели, "
            "пометки нет, извлечение знаний не пропущено",
            {
                "notices": notice_kinds(events_ext),
                "mark_in_prompt": EXTRU_MARK in prompt_ext,
                "extraction_skipped": [
                    e for e in knowledge_log if e.get("event") == "knowledge.extraction.skipped"
                ],
                "prompt_tail": prompt_ext[-400:],
            },
            evidence + [str(logs / "llm.log")],
        )

        # --- TC-61: разбор неоднозначных упоминаний ---
        from philograph.knowledge import schema as ks

        ke = db_engine(STAND, [ks.SCHEMA])
        with ke.begin() as conn:
            mention_rows = conn.execute(
                select(ks.mentions.c.target_id, ks.mentions.c.entity_id, ks.mentions.c.method)
            ).all()
        nonext_targets = [
            (target, entity, method) for target, entity, method in mention_rows if target in pids["nonext"]
        ]
        kant_mentions = [row for row in nonext_targets if row[2] == "name"]
        bacon_mentions = [
            row
            for row in mention_rows
            if row[1] in {SEEDED["bacon_a"], SEEDED["bacon_b"]}
        ]
        unresolved = [e for e in knowledge_log if e.get("event") == "knowledge.mentions.unresolved"]
        record(
            "TC-61",
            bool(unresolved)
            and not bacon_mentions
            and all(method != "model" for _, _, method in mention_rows)
            and bool(kant_mentions),
            "без external_processing модель-разрешитель не вызывается, неоднозначное упоминание "
            "не поставлено, однозначное — по словарю",
            {
                "unresolved": unresolved[:3],
                "nonext_mentions": nonext_targets[:6],
                "bacon_mentions": bacon_mentions[:3],
            },
            [str(logs / "knowledge.log")],
        )
        knowledge_calls = [
            row
            for row in all_prompts(STAND)
            if (row.get("caller") or "") == "knowledge"
            and NONEXT_MARK in (row.get("prompt_text") or "")
        ]
        record(
            "TC-61/no-text",
            not knowledge_calls,
            "текста источника без внешней обработки нет ни в одном запросе к модели "
            "(извлечение и разбор упоминаний пропущены)",
            {"knowledge_calls_with_mark": len(knowledge_calls)},
            [str(logs / "llm.log"), str(logs / "knowledge.log")],
        )

        # --- читатель из DE: источник закрыт целиком ---
        de_client = session(proxy_url, {"CF-IPCountry": "DE"})
        de_sources = de_client.get("/api/v1/sources").json()
        de_rows = {row["id"]: row for row in de_sources.get("sources", [])}
        events_de = ask_via(de_client, {"question": QUESTIONS["only"]})
        prompt_de = answer_prompt(STAND, QUESTIONS["only"])
        de_search = httpx.post(
            search_url + "/v1/search",
            json={"query": "Каллистика прекрасном", "region": "DE", "limit": 10},
            timeout=30,
        ).json()
        record(
            "UC-28/DE",
            de_rows.get(ids["nonext"], {}).get("restricted") is True
            and de_rows.get(ids["nonext"], {}).get("regions") == ["RU"]
            and "year" not in de_rows.get(ids["nonext"], {})
            and not any(
                r["source_id"] == ids["nonext"] for r in de_search["results"]
            ),
            "для читателя из DE источник закрыт целиком: строка restricted с regions [RU] без "
            "года и лицензии, поиск его не отдаёт",
            {"row": de_rows.get(ids["nonext"]), "search": de_search["results"][:3]},
            evidence,
        )
        record(
            "UC-28/DE-no-text",
            NONEXT_MARK not in prompt_de
            and not any(n.get("kind") == "found_not_retold" for n in notices(events_de)),
            "вопрос из DE: текста закрытого источника нет в промпте и нет пометки о найденном "
            "в закрытом источнике",
            {
                "notices": notice_kinds(events_de),
                "mark_in_prompt": NONEXT_MARK in prompt_de,
            },
            evidence + [str(logs / "llm.log")],
        )

        # --- запрос без заголовка страны: регион неизвестен (TC-60) ---
        unknown_client = session(proxy_url)
        events_unknown = ask_via(unknown_client, {"question": QUESTIONS["only"]})
        prompt_unknown = answer_prompt(STAND, QUESTIONS["only"])
        record(
            "TC-60",
            NONEXT_MARK not in prompt_unknown
            and not any(n.get("kind") == "found_not_retold" for n in notices(events_unknown)),
            "вопрос без региона: источник [RU] закрыт на поиске, текста нет в passages и "
            "пометки о найденном нет",
            {
                "notices": notice_kinds(events_unknown),
                "mark_in_prompt": NONEXT_MARK in prompt_unknown,
                "prompt_tail": prompt_unknown[-300:],
            },
            evidence + [str(logs / "llm.log")],
        )

        # --- EC-50/EC-51: строки пометки и роль в интерфейсе ---
        record(
            "EC-50",
            bool(mixed_hidden)
            and mixed_hidden[0].get("message") == "Найдено в источниках, не пересказывается."
            and mixed_hidden[0].get("kind") == "found_not_retold",
            "пометка приходит строкой i18n (assistant.found_not_retold), данные источника "
            "не переводятся",
            {"notice": mixed_hidden[0] if mixed_hidden else None},
            evidence,
        )

        # --- браузер ---
        browser_checks_round7(
            gateway,
            ids,
            pids,
            QUESTIONS,
            NONEXT_MARK,
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
                "pids": pids,
                "logs": str(logs),
            },
            "catalog": counts,
            "sync": sync,
            "checks": CHECKS,
            "failures": len([c for c in CHECKS if not c["ok"]]),
        }
        (ROUND / "live-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (ROUND / "catalog-validate.log").write_text(
            f"exit={counts['validate_exit']}\n{counts['validate_tail']}\n", encoding="utf-8"
        )
        (ROUND / "sync-accounting.json").write_text(
            json.dumps(sync, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        stack.stop()
    print("ИТОГО проверок:", len(CHECKS), "провалов:", report["failures"])
    return 1 if report["failures"] else 0


# --- 5. браузер --------------------------------------------------------------------


def browser_checks(  # noqa: PLR0913
    gateway: str,
    ids: dict[str, str],
    pids: dict[str, list[str]],
    questions: dict[str, str],
    nonext_mark: str,
) -> None:
    from playwright.sync_api import sync_playwright

    SHOTS.mkdir(parents=True, exist_ok=True)
    console_errors: list[str] = []
    failed_requests: list[str] = []
    nonext_pid = pids["nonext"][0]

    def attach(page) -> None:
        page.on(
            "console",
            lambda msg: console_errors.append(f"{msg.type}: {msg.text}")
            if msg.type == "error"
            else None,
        )
        page.on("pageerror", lambda exc: console_errors.append(f"pageerror: {exc}"))
        page.on("requestfailed", lambda req: failed_requests.append(f"{req.url} {req.failure}"))

    def open_reader(page) -> None:
        page.goto(gateway + f"/read/{ids['nonext']}", wait_until="networkidle")
        page.wait_for_selector(".chapter [data-paragraph]", timeout=30000)
        page.locator(".toc__assistant").click()
        panel = page.get_by_role("complementary", name="Ассистент")
        panel.wait_for(timeout=30000)
        panel.get_by_label("Вопрос ассистенту").wait_for(timeout=30000)
        # Уведомление первого запуска закрывает вопрос ассистенту: пока оно не принято,
        # «Спросить» не отправляет запрос.
        first_run = page.locator("section.first-run")
        if first_run.count():
            first_run.get_by_role("button", name="Понятно").click()
            page.wait_for_timeout(500)

    def ask(page, question: str) -> None:
        panel = page.get_by_role("complementary", name="Ассистент")
        panel.get_by_label("Вопрос ассистенту").fill(question)
        panel.get_by_role("button", name="Спросить", exact=True).click()
        panel.locator(".copy-answer").last.wait_for(timeout=90000)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="ru-RU")
        page = context.new_page()
        attach(page)
        try:
            open_reader(page)
            ask(page, questions["only"])
            panel = page.get_by_role("complementary", name="Ассистент")
            turn = panel.locator(".turn").last
            notice = turn.locator(".assistant-notice")
            notice.wait_for(timeout=30000)
            link = turn.locator(".assistant__suggestions a").first
            link.wait_for(timeout=30000)
            href = link.get_attribute("href")
            shot1 = SHOTS / "TC-62-1-notice-with-link.png"
            page.screenshot(path=str(shot1), full_page=True)
            record(
                "TC-62",
                href == f"/p/{nonext_pid}"
                and "Найдено в источниках, не пересказывается." in turn.inner_text(),
                "клиент: пометка «найдено в источниках, не пересказывается» со ссылкой на абзац",
                {
                    "href": href,
                    "notice": notice.inner_text(),
                    "role": notice.get_attribute("role"),
                    "console_errors": console_errors[:5],
                },
                [str(shot1)],
            )
            link.click()
            page.wait_for_timeout(1500)
            shot2 = SHOTS / "TC-62-2-link-opened.png"
            page.screenshot(path=str(shot2), full_page=True)
            record(
                "TC-62/link",
                page.url.endswith(f"#p-{nonext_pid}") or f"/p/{nonext_pid}" in page.url,
                "клик по ссылке пометки ведёт на абзац источника",
                {"url": page.url},
                [str(shot2)],
            )
        except Exception as exc:  # noqa: BLE001
            shot = SHOTS / "TC-62-FAILED.png"
            try:
                page.screenshot(path=str(shot), full_page=True)
            except Exception:  # noqa: BLE001
                pass
            record(
                "TC-62",
                False,
                "клиент: пометка со ссылкой на абзац",
                {"error": f"{type(exc).__name__}: {exc}", "console": console_errors[:5]},
                [str(shot)],
            )
        try:
            context2 = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="ru-RU")
            page2 = context2.new_page()
            attach(page2)
            open_reader(page2)
            # «Только выбранный учебник»: поиск ограничен источником без внешней обработки —
            # все найденные абзацы непересказываемые (TC-64).
            page2.locator('label.pg-switch:has-text("Только выбранный учебник") input').check()
            page2.wait_for_timeout(300)
            ask(page2, questions["only"])
            turn = page2.get_by_role("complementary", name="Ассистент").locator(".turn").last
            turn.locator(".assistant-notice").first.wait_for(timeout=30000)
            page2.wait_for_timeout(1500)
            shot = SHOTS / "TC-64-1-only-hidden-client.png"
            page2.screenshot(path=str(shot), full_page=True)
            text = turn.inner_text()
            links = turn.locator(".assistant__suggestions a").count()
            record(
                "TC-64/client",
                "Найдено в источниках, не пересказывается." in text and links > 0,
                "найдены только непересказываемые абзацы: клиент показывает пометку со ссылкой "
                "и «без опоры на библиотеку»",
                {"text": text[:400], "links": links, "console": console_errors[:5]},
                [str(shot)],
            )
        except Exception as exc:  # noqa: BLE001
            shot = SHOTS / "TC-64-1-only-hidden-FAILED.png"
            try:
                page2.screenshot(path=str(shot), full_page=True)
            except Exception:  # noqa: BLE001
                pass
            record(
                "TC-64/client",
                False,
                "только непересказываемые: пометка со ссылкой",
                {"error": f"{type(exc).__name__}: {exc}", "console": console_errors[:5]},
                [str(shot)],
            )
        context.close()
        browser.close()

    record(
        "EC-console",
        not console_errors and not failed_requests,
        "в браузере нет ошибок консоли и сетевых сбоев",
        {"console_errors": console_errors[:10], "failed_requests": failed_requests[:10]},
        [str(SHOTS / "TC-62-1-notice-with-link.png")],
    )


# --- 6. браузер: раунд 7 (TC-65 и обычные пометки) ---------------------------------


NOT_RETOLD = "Найдено в источниках, не пересказывается."
NO_LIBRARY = "Ответ составлен без опоры на библиотеку."
NO_ANSWER = "В источниках ответа не нашлось."
BROKEN = "Ответ оборвался. Можно повторить."


def _open_reader(page, gateway: str, source_id: str) -> None:
    page.goto(gateway + f"/read/{source_id}", wait_until="networkidle")
    page.wait_for_selector(".chapter [data-paragraph]", timeout=30000)
    page.locator(".toc__assistant").click()
    panel = page.get_by_role("complementary", name="Ассистент")
    panel.wait_for(timeout=30000)
    panel.get_by_label("Вопрос ассистенту").wait_for(timeout=30000)
    # Уведомление первого запуска закрывает вопрос ассистенту.
    first_run = page.locator("section.first-run")
    if first_run.count():
        first_run.get_by_role("button", name="Понятно").click()
        page.wait_for_timeout(500)


def _send_question(page, question: str) -> None:
    panel = page.get_by_role("complementary", name="Ассистент")
    panel.get_by_label("Вопрос ассистенту").fill(question)
    panel.get_by_role("button", name="Спросить", exact=True).click()


def _wait_notices(turn, count: int, seconds: float = 60) -> int:
    deadline = time.time() + seconds
    while time.time() < deadline:
        found = turn.locator(".assistant-notice").count()
        if found >= count:
            return found
        time.sleep(0.3)
    return turn.locator(".assistant-notice").count()


def browser_checks_round7(  # noqa: PLR0913, PLR0915
    gateway: str,
    ids: dict[str, str],
    pids: dict[str, list[str]],
    questions: dict[str, str],
    nonext_mark: str,
) -> None:
    import re

    from playwright.sync_api import sync_playwright

    SHOTS.mkdir(parents=True, exist_ok=True)
    console_errors: list[str] = []
    page_errors: list[str] = []
    failed_requests: list[str] = []
    nonext_pid = pids["nonext"][0]

    def attach(page) -> None:
        page.on(
            "console",
            lambda msg: console_errors.append(f"{msg.type}: {msg.text}")
            if msg.type == "error"
            else None,
        )
        page.on("pageerror", lambda exc: page_errors.append(f"pageerror: {exc}"))
        page.on("requestfailed", lambda req: failed_requests.append(f"{req.url} {req.failure}"))

    with sync_playwright() as pw:
        browser = pw.chromium.launch()

        # --- A. TC-65: две пометки за один ход в сценарии «Только выбранный учебник» ---
        context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="ru-RU")
        page = context.new_page()
        attach(page)
        shot_two = SHOTS / "TC-65-1-two-notices.png"
        shot_link = SHOTS / "TC-65-2-link-opened.png"
        try:
            _open_reader(page, gateway, ids["nonext"])
            toggle = page.locator('label.pg-switch:has-text("Только выбранный учебник") input')
            toggle.check()
            page.wait_for_timeout(300)
            _send_question(page, questions["only"])
            panel = page.get_by_role("complementary", name="Ассистент")
            turn = panel.locator(".turn").last
            turn.locator(".copy-answer").wait_for(timeout=120000)
            found = _wait_notices(turn, 2)
            page.wait_for_timeout(800)
            notices = [
                {
                    "text": turn.locator(".assistant-notice").nth(i).inner_text(),
                    "role": turn.locator(".assistant-notice").nth(i).get_attribute("role"),
                    "class": turn.locator(".assistant-notice").nth(i).get_attribute("class"),
                }
                for i in range(found)
            ]
            links = turn.locator(".assistant__suggestions a")
            hrefs = [links.nth(i).get_attribute("href") for i in range(links.count())]
            answer_top = turn.locator(".answer").bounding_box()
            notice_tops = [
                turn.locator(".assistant-notice").nth(i).bounding_box() for i in range(found)
            ]
            page.screenshot(path=str(shot_two), full_page=True)
            texts = [n["text"] for n in notices]
            both = any(NOT_RETOLD in text for text in texts) and any(
                NO_LIBRARY in text for text in texts
            )
            first_is_retold = bool(texts) and NOT_RETOLD in texts[0]
            record(
                "TC-65/two-notices",
                found == 2
                and both
                and first_is_retold
                and f"/p/{nonext_pid}" in hrefs
                and all(n["role"] == "status" for n in notices)
                and answer_top is not None
                and all(t is not None and t["y"] < answer_top["y"] for t in notice_tops),
                "в одном ходе две пометки: «Найдено в источниках, не пересказывается.» со ссылкой "
                "на абзац и «Ответ составлен без опоры на библиотеку.» — видны обе, по порядку, "
                "над ответом, роль status",
                {"count": found, "notices": notices, "hrefs": hrefs},
                [str(shot_two)],
            )
            link = turn.locator(".assistant__suggestions a").first
            link.wait_for(timeout=30000)
            link.click()
            page.wait_for_url(re.compile(rf"#p-{re.escape(nonext_pid)}$"), timeout=60000)
            page.wait_for_timeout(1200)
            rect = page.evaluate(
                """id => { const el = document.getElementById('p-' + id);
                if (!el) return null; const r = el.getBoundingClientRect();
                return {top: r.top, height: r.height}; }""",
                nonext_pid,
            )
            viewport = page.viewport_size or {"height": 1000}
            page.screenshot(path=str(shot_link), full_page=True)
            record(
                "TC-65/link",
                page.url.endswith(f"#p-{nonext_pid}")
                and rect is not None
                and -150 <= rect["top"] <= viewport["height"],
                "клик по ссылке пометки ведёт на этот абзац: адрес оканчивается #p-<абзац>, "
                "абзац в окне просмотра",
                {"url": page.url, "rect": rect},
                [str(shot_link)],
            )
        except Exception as exc:  # noqa: BLE001
            shot = SHOTS / "TC-65-1-two-notices-FAILED.png"
            try:
                page.screenshot(path=str(shot), full_page=True)
            except Exception:  # noqa: BLE001
                pass
            record(
                "TC-65/two-notices",
                False,
                "две пометки за один ход со ссылкой на абзац",
                {"error": f"{type(exc).__name__}: {exc}", "console": console_errors[-5:]},
                [str(shot)],
            )
            record(
                "TC-65/link",
                False,
                "клик по ссылке ведёт на абзац",
                {"error": "проверка не дошла: см. TC-65/two-notices"},
                [str(shot)],
            )

        # --- B. TC-65: старая сессия (формат 3) с единственным ``message`` ---
        shot_legacy = SHOTS / "TC-65-3-legacy-v3-session.png"
        context2 = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="ru-RU")
        legacy_turn = {
            "id": "t-legacy",
            "question": "Старый вопрос",
            "fragments": [],
            "status": "done",
            "message": {"code": "no_library_support", "text": NO_LIBRARY},
        }
        legacy_link_turn = {
            "id": "t-legacy-2",
            "question": "Старый вопрос со ссылкой",
            "fragments": [],
            "status": "done",
            "message": {
                "code": "found_not_retold",
                "text": NOT_RETOLD,
                "suggestions": [{"paragraph_id": nonext_pid, "title": "Глава 1. Рассвет"}],
            },
        }
        legacy_state = {"version": 3, "dialogs": [[legacy_turn, legacy_link_turn]]}
        (ROUND / "legacy-v3-state.json").write_text(
            json.dumps(legacy_state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        context2.add_init_script(
            f"""if (!sessionStorage.getItem('seeded')) {{
            sessionStorage.setItem('seeded', '1');
            localStorage.removeItem('philograph:v4');
            localStorage.setItem('philograph:v3', {json.dumps(json.dumps(legacy_state))});
        }}"""
        )
        page2 = context2.new_page()
        attach(page2)
        try:
            page2.goto(gateway + "/assistant", wait_until="networkidle")
            page2.locator(".turn").first.wait_for(timeout=60000)
            page2.wait_for_timeout(800)
            turns = page2.locator(".turn")
            texts = [turns.nth(i).inner_text() for i in range(turns.count())]
            legacy_notices = [
                turns.nth(i).locator(".assistant-notice").count() for i in range(turns.count())
            ]
            legacy_links = page2.locator(".assistant__suggestions a").count()
            page2.screenshot(path=str(shot_legacy), full_page=True)
            record(
                "TC-65/legacy",
                len(texts) == 2
                and "Старый вопрос" in texts[0]
                and NO_LIBRARY in texts[0]
                and NOT_RETOLD in texts[1]
                and legacy_links >= 1
                and all(count >= 1 for count in legacy_notices),
                "старая сессия формата 3 с единственным message открывается без ошибок: вопросы, "
                "пометки и ссылки на месте",
                {
                    "turns": len(texts),
                    "texts": [text[:200] for text in texts],
                    "notices_per_turn": legacy_notices,
                    "links": legacy_links,
                    "page_errors": page_errors[-5:],
                },
                [str(shot_legacy), str(ROUND / "legacy-v3-state.json")],
            )
        except Exception as exc:  # noqa: BLE001
            shot = SHOTS / "TC-65-3-legacy-v3-session-FAILED.png"
            try:
                page2.screenshot(path=str(shot), full_page=True)
            except Exception:  # noqa: BLE001
                pass
            record(
                "TC-65/legacy",
                False,
                "старая сессия с единственным message открывается без ошибок",
                {"error": f"{type(exc).__name__}: {exc}", "page_errors": page_errors[-5:]},
                [str(shot)],
            )
        context2.close()
        # Ошибки консоли до шага «ошибка соединения»: шаг намеренно обрывает запрос, Chromium
        # пишет об этом `net::ERR_FAILED`, к продукту это не относится.
        normal_flow_errors = list(console_errors)

        # --- C. обычные пометки: no_library_support, no_answer, ошибка соединения ---
        shot_notices = SHOTS / "TC-65-4-ordinary-notices.png"
        shot_error = SHOTS / "TC-65-5-error-notice.png"
        try:
            _open_reader(page, gateway, ids["nonext"])
            _send_question(page, questions["none"])
            panel = page.get_by_role("complementary", name="Ассистент")
            turn = panel.locator(".turn").last
            turn.locator(".copy-answer").wait_for(timeout=120000)
            _wait_notices(turn, 1)
            page.wait_for_timeout(500)
            text = turn.inner_text()
            page.screenshot(path=str(shot_notices), full_page=True)
            record(
                "TC-65/notice-no-library-support",
                NO_LIBRARY in text and turn.locator(".assistant-notice").count() >= 1,
                "обычная пометка no_library_support по-прежнему показывается",
                {"text": text[:300], "notices": turn.locator(".assistant-notice").count()},
                [str(shot_notices)],
            )
        except Exception as exc:  # noqa: BLE001
            shot = SHOTS / "TC-65-4-ordinary-notices-FAILED.png"
            try:
                page.screenshot(path=str(shot), full_page=True)
            except Exception:  # noqa: BLE001
                pass
            record(
                "TC-65/notice-no-library-support",
                False,
                "обычная пометка no_library_support показывается",
                {"error": f"{type(exc).__name__}: {exc}", "console": console_errors[-5:]},
                [str(shot)],
            )

        # no_answer: на подставном провайдере эмбеддингов смысловая выдача находится на любой
        # вопрос, поэтому «поиск ничего не нашёл» живьём не воспроизводится. Проверяем отрисовку
        # пометки клиентом по подставному потоку NDJSON (тот же приём, что в tests/web).
        stub_no_answer = (
            json.dumps(
                {
                    "type": "notice",
                    "kind": "no_answer",
                    "message": NO_ANSWER,
                    "suggestions": [{"paragraph_id": nonext_pid, "title": "Глава 1. Рассвет"}],
                },
                ensure_ascii=False,
            )
            + "\n"
            + json.dumps({"type": "done"}, ensure_ascii=False)
            + "\n"
        )
        (ROUND / "notices-stub-no-answer.ndjson").write_text(stub_no_answer, encoding="utf-8")
        shot_no_answer = SHOTS / "TC-65-6-no-answer-notice.png"
        try:
            page.route(
                "**/api/assistant/v1/ask",
                lambda route: route.fulfill(
                    status=200,
                    headers={"content-type": "application/x-ndjson; charset=utf-8"},
                    body=stub_no_answer,
                ),
            )
            _send_question(page, "Что было в источниках про единорогов?")
            turn = page.get_by_role("complementary", name="Ассистент").locator(".turn").last
            turn.locator(".assistant-notice").first.wait_for(timeout=60000)
            page.wait_for_timeout(500)
            text = turn.inner_text()
            page.screenshot(path=str(shot_no_answer), full_page=True)
            record(
                "TC-65/notice-no-answer",
                NO_ANSWER in text and turn.locator(".assistant__suggestions a").count() >= 1,
                "пометка no_answer с «Близкое в библиотеке» показывается (клиент, подставной поток)",
                {"text": text[:300]},
                [str(shot_no_answer), str(ROUND / "notices-stub-no-answer.ndjson")],
            )
            page.unroute("**/api/assistant/v1/ask")
        except Exception as exc:  # noqa: BLE001
            shot = SHOTS / "TC-65-6-no-answer-notice-FAILED.png"
            try:
                page.screenshot(path=str(shot), full_page=True)
            except Exception:  # noqa: BLE001
                pass
            record(
                "TC-65/notice-no-answer",
                False,
                "пометка no_answer показывается",
                {"error": f"{type(exc).__name__}: {exc}", "console": console_errors[-5:]},
                [str(shot)],
            )

        # Ошибка соединения: запрос ассистента не уходит, клиент показывает «broken».
        try:
            page.route("**/api/assistant/v1/ask", lambda route: route.abort())
            _send_question(page, "Что такое Каллистика?")
            turn = page.get_by_role("complementary", name="Ассистент").locator(".turn").last
            turn.locator(".pg-notice--danger").first.wait_for(timeout=60000)
            page.wait_for_timeout(500)
            text = turn.inner_text()
            retry = turn.get_by_role("button", name="Повторить").count()
            page.screenshot(path=str(shot_error), full_page=True)
            record(
                "TC-65/notice-error",
                BROKEN in text and retry >= 1,
                "ошибка соединения по-прежнему показывается: «Ответ оборвался. Можно повторить.» "
                "и кнопка «Повторить»",
                {"text": text[:300], "retry_buttons": retry},
                [str(shot_error)],
            )
            page.unroute("**/api/assistant/v1/ask")
        except Exception as exc:  # noqa: BLE001
            shot = SHOTS / "TC-65-5-error-notice-FAILED.png"
            try:
                page.screenshot(path=str(shot), full_page=True)
            except Exception:  # noqa: BLE001
                pass
            record(
                "TC-65/notice-error",
                False,
                "ошибка соединения показывается",
                {"error": f"{type(exc).__name__}: {exc}", "console": console_errors[-5:]},
                [str(shot)],
            )

        context.close()
        browser.close()

    record(
        "TC-65/console",
        not normal_flow_errors and not page_errors,
        "в сценариях двух пометок, перехода по ссылке и старой сессии нет ошибок консоли "
        "и необработанных исключений страницы",
        {"console_errors": normal_flow_errors[:10], "page_errors": page_errors[:10]},
        [str(SHOTS / "TC-65-1-two-notices.png")],
    )
    record(
        "EC-console",
        not normal_flow_errors and not page_errors,
        "в браузере нет ошибок консоли и необработанных исключений страницы (кроме ожидаемого "
        "`net::ERR_FAILED` от намеренно оборванного запроса в проверке ошибки соединения)",
        {
            "console_errors_normal_flow": normal_flow_errors[:10],
            "console_errors_total": console_errors[:10],
            "page_errors": page_errors[:10],
            "failed_requests": [r for r in failed_requests if "/api/assistant/v1/ask" not in r][:10],
        },
        [str(SHOTS / "TC-65-1-two-notices.png")],
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        raise SystemExit(2) from None
