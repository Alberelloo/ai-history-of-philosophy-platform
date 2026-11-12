"""Раунд 4: независимый стенд проверки ru-only-sources (группы 4, 8.2 и фикс группы 1).

Поднимает ``scripts/dev_stack.py`` в-process (демо-источники + собственные источники
тестировщика), затем проверяет:

- миграцию 4 поиска на «старой» базе (схема до регионов);
- шлюз с ``PHILOGRAPH_REGION_FALLBACK=RU``: ограниченный источник открыт, клиентский
  заголовок региона и заголовок страны не подменяют регион;
- поиск: абзацы источника [RU] не отдаются для DE и без региона, лимит заполняется открытыми;
- событие ``source.access_changed``: смена регионов без вызовов эмбеддера, повтор безвреден,
  ``regions: []`` закрывает всем;
- сверку индексов: расхождение регионов чинится, закрытый источник не гасится;
- ``change_license`` уносит действующие регионы (вид [RU], сужения нет) — TC-38/EC-33;
- браузер (Playwright) через шлюз и через библиотеку напрямую, со скриншотами.

Код, тесты и спецификации не меняются: артефакты только в ``qa/round-4/``.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
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

RU_TITLE = "Ограниченный учебник [RU]"
OPEN_TITLE = "Открытый сборник о разуме"
MARKER = "РЕГИОННЫЙМАРКЕР"

FILES = {
    "restricted_ru.txt": (
        "Глава 1. Разум и рассудок\n\n"
        "Рассудок и разум различаются: рассудок есть способность правил.\n\n"
        "Разум есть способность принципов, учил Кант.\n\n"
        f"{MARKER}: этот абзац доступен только читателям из РФ.\n"
    ).encode(),
    "open_extra.txt": (
        "Глава 1. Разум\n\n"
        "Разум в широком смысле слова.\n\n"
        "Разум как способность принципов в античной философии.\n\n"
        "Разум и опыт у эмпириков.\n\n"
        "Разум в немецкой классической философии.\n"
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
    print(("PASS " if ok else "FAIL ") + cid + " :: " + item["actual"][:300])
    return item


# --- 0. миграция 4 на старой базе поиска -------------------------------------------


def migration_check(tmp: Path) -> None:
    from sqlalchemy import inspect, text

    from philograph.platform.db import make_engine
    from philograph.search import schema as s

    db = tmp / "old-search.db"
    engine = make_engine(f"sqlite:///{db.as_posix()}", [s.SCHEMA])
    items = s.migrations._items
    saved = list(items)
    try:
        items[:] = [m for m in saved if m.version <= 3]  # база «до регионов»
        applied_old = s.migrations.upgrade(engine)
        with engine.begin() as conn:
            conn.execute(
                text(
                    f"INSERT INTO {s.SCHEMA}.docs "
                    "(paragraph_id, source_id, version_id, lang, scope, text, text_hash, "
                    "length, embedded, active, ord) VALUES "
                    "('old-p1', 'old-s1', 'old-v1', 'ru', 'public', 'старый текст', 'h1', 2, 1, 1, 1)"
                )
            )
    finally:
        items[:] = saved
    applied_new = s.migrations.upgrade(engine)  # то, что сделает сервис при старте
    with engine.begin() as conn:
        row = conn.execute(
            text(f"SELECT regions, external FROM {s.SCHEMA}.docs WHERE paragraph_id='old-p1'")
        ).one()
        columns = {c["name"] for c in inspect(conn).get_columns("docs", schema=s.SCHEMA)}
        version = conn.execute(
            text(f"SELECT MAX(version) FROM {s.SCHEMA}.schema_migrations")
        ).scalar()
    ok = (
        applied_old == [1, 2, 3]
        and applied_new == [4]
        and {"regions", "external"} <= columns
        and row.regions == "*"
        and bool(row.external) is True
        and version == 4
    )
    record(
        "TC-33",
        ok,
        "на базе версии 3 миграция 4 добавляет regions/external; старые строки — '*' и TRUE",
        {
            "applied_before": applied_old,
            "applied_by_start": applied_new,
            "columns": sorted(columns),
            "old_row": {"regions": row.regions, "external": bool(row.external)},
            "schema_version": version,
        },
        [str(ROUND / "live-report.json")],
    )


# --- 1. источники тестировщика до старта стенда ------------------------------------


def pre_seed(data: Path) -> dict[str, str]:
    from philograph.library import schema as lib_schema
    from philograph.library.processing import Pipeline
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
    registry.add_license_kind("demo-open", "Открытая демонстрация", None, dict(permissions))
    registry.add_license_kind("demo-ru", "Только РФ", None, dict(permissions), regions=["RU"])
    pipeline = Pipeline(
        registry,
        FileStore(data / "files"),
        lambda spec: FILES[spec["path"]],
    )
    ids: dict[str, str] = {}
    for key, title, kind, path in (
        ("open", OPEN_TITLE, "demo-open", "open_extra.txt"),
        ("restricted", RU_TITLE, "demo-ru", "restricted_ru.txt"),
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
    pipeline.dispatch_outbox(Queue(engine))
    return ids


# --- 2. общие помощники ------------------------------------------------------------


def lib_engine(data: Path):
    from philograph.library import schema as lib_schema
    from philograph.operator.access import migrations as op_migrations
    from philograph.platform.db import make_engine
    from philograph.platform.queue import migrations as q_migrations

    db = f"sqlite:///{(data / 'stack.db').as_posix()}"
    return make_engine(db, [lib_schema.migrations.schema, op_migrations.schema, q_migrations.schema])


def search_engine(data: Path):
    from philograph.platform.db import make_engine
    from philograph.search import schema

    db = f"sqlite:///{(data / 'stack.db').as_posix()}"
    return make_engine(db, [schema.SCHEMA])


def dispatch_outbox(data: Path) -> int:
    from philograph.library.processing import Pipeline
    from philograph.library.registry import Registry
    from philograph.platform.files import FileStore
    from philograph.platform.queue import Queue

    engine = lib_engine(data)
    pipeline = Pipeline(Registry(engine), FileStore(data / "files"), lambda spec: b"")
    return pipeline.dispatch_outbox(Queue(engine))


def outbox_payloads(data: Path) -> list[dict]:
    from sqlalchemy import select

    from philograph.library import schema as lib_schema

    engine = lib_engine(data)
    with engine.begin() as conn:
        rows = conn.execute(
            select(lib_schema.outbox).order_by(lib_schema.outbox.c.id.desc()).limit(5)
        ).mappings()
        return [dict(r) for r in rows]


def blocked_sources(data: Path, source_id: str) -> dict:
    from sqlalchemy import select

    from philograph.search import schema as s

    engine = search_engine(data)
    with engine.begin() as conn:
        rows = conn.execute(
            select(s.docs.c.regions, s.docs.c.active).where(s.docs.c.source_id == source_id)
        ).all()
    return {"regions": sorted({r.regions for r in rows}), "active": [bool(r.active) for r in rows]}


def set_regions_stale(data: Path, source_id: str) -> None:
    from sqlalchemy import update

    from philograph.search import schema as s

    engine = search_engine(data)
    with engine.begin() as conn:
        conn.execute(update(s.docs).where(s.docs.c.source_id == source_id).values(regions="*"))


def embedding_calls(stack) -> int:
    return len(
        [
            e
            for e in stack.logs("llm")
            if e.get("event") == "llm.call.completed"
            and e.get("role") == "embeddings"
            and e.get("budget") == "filling"
        ]
    )


def found_sources(payload: dict) -> list[str]:
    return [r["source_id"] for r in payload.get("results", [])]


def sources_by_id(payload: dict) -> dict[str, dict]:
    return {row["id"]: row for row in payload.get("sources", [])}


# --- 3. браузер --------------------------------------------------------------------


def browser_checks(web_url: str, library_url: str, source_title: str, results: list[dict]) -> None:
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

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        # UC-19 / UC-12: стенд с PHILOGRAPH_REGION_FALLBACK=RU — ограниченный источник открыт.
        context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="ru-RU")
        page = context.new_page()
        attach(page)
        page.goto(web_url + "/", wait_until="networkidle")
        page.wait_for_selector("li.source", timeout=20000)
        rows = page.locator("li.source").all()
        row_texts = [r.inner_text() for r in rows]
        restricted_rows = page.locator("li.source--restricted").count()
        shot = SHOTS / "UC-19-1-library-fallback-ru.png"
        page.screenshot(path=str(shot), full_page=True)
        results.append(
            record(
                "UC-19",
                restricted_rows == 0 and any(source_title in t for t in row_texts),
                "через шлюз с запасным регионом RU ограниченный источник открыт (без пометки "
                "«доступен в РФ», есть кнопка «Читать»)",
                {
                    "restricted_rows": restricted_rows,
                    "rows": row_texts,
                    "url": web_url,
                    "console_errors": console_errors[:5],
                    "failed_requests": failed_requests[:5],
                },
                [str(shot)],
            )
        )
        # Чтение ограниченного источника: текст виден, пометки о регионе нет.
        row = page.locator("li.source", has_text=source_title).first
        read = row.locator("button", has_text="Читать")
        read_count = read.count()
        body_text = ""
        if read_count:
            read.first.click()
            page.wait_for_selector("text=" + MARKER, timeout=20000)
            body_text = page.inner_text("body")
        shot2 = SHOTS / "UC-19-3-restricted-source-readable.png"
        page.screenshot(path=str(shot2), full_page=True)
        results.append(
            record(
                "UC-2",
                read_count == 1 and MARKER in body_text,
                "источник [RU] на стенде с запасным регионом RU читается: абзац с маркером виден",
                {"read_buttons": read_count, "marker_visible": MARKER in body_text},
                [str(shot2)],
            )
        )
        context.close()

        # Подмена заголовка клиентом: шлюз отбрасывает и X-Philograph-Region, и заголовок страны.
        spoof_context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            locale="ru-RU",
            extra_http_headers={"X-Philograph-Region": "DE", "CF-IPCountry": "DE"},
        )
        spoof_page = spoof_context.new_page()
        attach(spoof_page)
        spoof_page.goto(web_url + "/", wait_until="networkidle")
        spoof_page.wait_for_selector("li.source", timeout=20000)
        spoof_restricted = spoof_page.locator("li.source--restricted").count()
        spoof_rows = [r.inner_text() for r in spoof_page.locator("li.source").all()]
        shot3 = SHOTS / "UC-19-2-client-header-ignored.png"
        spoof_page.screenshot(path=str(shot3), full_page=True)
        results.append(
            record(
                "UC-10",
                spoof_restricted == 0 and any(source_title in t for t in spoof_rows),
                "клиентские заголовки X-Philograph-Region: DE и CF-IPCountry: DE не меняют регион: "
                "источник по-прежнему открыт по запасному RU",
                {"restricted_rows": spoof_restricted, "rows": spoof_rows},
                [str(shot3)],
            )
        )
        spoof_context.close()

        # Библиотека напрямую (без шлюза): регион неизвестен, строка закрыта.
        direct_context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="ru-RU")
        direct_page = direct_context.new_page()
        attach(direct_page)
        direct_page.goto(library_url + "/", wait_until="networkidle")
        direct_page.wait_for_selector("li.source", timeout=20000)
        direct_restricted = direct_page.locator("li.source--restricted").count()
        badge = (
            direct_page.locator("li.source--restricted .badge", has_text="Доступен в РФ").count()
        )
        shot4 = SHOTS / "UC-19-4-library-direct-unknown-region.png"
        direct_page.screenshot(path=str(shot4), full_page=True)
        results.append(
            record(
                "UC-3",
                direct_restricted == 1 and badge == 1,
                "напрямую в библиотеке без шлюза регион неизвестен: источник показан строкой "
                "«Доступен в РФ»",
                {"restricted_rows": direct_restricted, "badges": badge, "url": library_url},
                [str(shot4)],
            )
        )
        direct_context.close()
        browser.close()

    results.append(
        record(
            "EC-console",
            not console_errors and not failed_requests,
            "в браузере нет ошибок консоли и сетевых сбоев",
            {"console_errors": console_errors[:10], "failed_requests": failed_requests[:10]},
            [str(SHOTS / "UC-19-1-library-fallback-ru.png")],
        )
    )


# --- 4. основной прогон ------------------------------------------------------------


def main() -> int:
    import httpx

    if STAND.exists():
        shutil.rmtree(STAND, ignore_errors=True)
    STAND.mkdir(parents=True, exist_ok=True)
    migration_check(STAND)

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
    stack = dev_stack.start(STAND, None, demo=True)
    names = ["llm", "library", "search", "assistant", "knowledge", "gateway"]
    port_of = dict(zip(names, ports, strict=False))
    gateway = stack.url
    library = f"http://127.0.0.1:{port_of['library']}"
    search = f"http://127.0.0.1:{port_of['search']}"
    print("стенд:", gateway, port_of)

    restricted = ids["restricted"]
    open_id = ids["open"]
    evidence = [str(ROUND / "live-report.json"), str(STAND / "logs")]

    def api(path: str, **kwargs):
        with httpx.Client(timeout=30) as client:
            response = client.get(gateway + path, **kwargs)
            response.raise_for_status()
            return response

    def search_api(query: str, **body):
        with httpx.Client(timeout=30) as client:
            response = client.post(search + "/v1/search", json={"query": query, **body})
            response.raise_for_status()
            return response.json()

    try:
        # Ожидаем индексацию наших источников (события публикации идут из очереди).
        deadline = time.time() + 90
        ru_hit = None
        while time.time() < deadline:
            ru_hit = search_api("рассудок и разум", region="RU", limit=10)
            if restricted in found_sources(ru_hit):
                break
            time.sleep(1.0)

        # TC-28/UC-14: абзацы источника [RU] находятся для RU (и по словам, и по смыслу).
        record(
            "TC-28/RU",
            bool(ru_hit) and restricted in found_sources(ru_hit),
            "поиск с регионом RU возвращает абзацы источника [RU]",
            {"sources": found_sources(ru_hit or {}), "semantic_used": (ru_hit or {}).get(
                "semantic_used")},
            evidence,
        )
        # TC-28/UC-15: для DE их нет.
        de_hit = search_api("рассудок и разум", region="DE", limit=10)
        record(
            "TC-28/DE",
            restricted not in found_sources(de_hit) and open_id in found_sources(de_hit),
            "поиск с регионом DE не возвращает абзацы источника [RU], открытые — возвращает",
            {
                "sources": found_sources(de_hit),
                "semantic_used": de_hit.get("semantic_used"),
                "found_by": sorted({f for r in de_hit["results"] for f in r["found_by"]}),
            },
            evidence,
        )
        # TC-28/UC-16: без региона — как неизвестный регион.
        none_hit = search_api("рассудок и разум", limit=10)
        record(
            "TC-28/none",
            restricted not in found_sources(none_hit),
            "поиск без региона не возвращает абзацы источника [RU]",
            {"sources": found_sources(none_hit), "semantic_used": none_hit.get("semantic_used")},
            evidence,
        )
        # TC-29/EC-27: лимит заполняется открытыми абзацами.
        limit_hit = search_api("рассудок и разум", region="DE", limit=3)
        record(
            "TC-29",
            len(limit_hit["results"]) == 3 and restricted not in found_sources(limit_hit),
            "поиск из DE с limit=3 отдаёт ровно 3 результата, все — открытые источники",
            {"count": len(limit_hit["results"]), "sources": found_sources(limit_hit)},
            evidence,
        )
        # Уникальное слово нашего источника: для DE его абзацев нет ни по словам, ни по смыслу.
        # Смысловой канал на демо-эмбеддингах возвращает почти все открытые абзацы, поэтому
        # проверяем именно отсутствие источника [RU], а не пустоту выдачи.
        marker_hit = search_api(MARKER, region="DE", limit=10)
        marker_ru = search_api(MARKER, region="RU", limit=10)
        marker_none = search_api(MARKER, limit=10)
        record(
            "TC-30",
            restricted not in found_sources(marker_hit)
            and restricted not in found_sources(marker_none)
            and restricted in found_sources(marker_ru),
            "абзац по уникальному слову [RU]-источника: для DE и без региона нет, для RU найден",
            {"DE": found_sources(marker_hit), "none": found_sources(marker_none),
             "RU": found_sources(marker_ru)},
            evidence,
        )

        # UC-19/UC-12: шлюз со запасным регионом RU.
        via_gateway = api("/api/v1/sources").json()
        rows = sources_by_id(via_gateway)
        gateway_row = rows.get(restricted)
        record(
            "UC-19/gateway",
            gateway_row is not None and not gateway_row.get("restricted"),
            "через шлюз источник [RU] открыт (нет restricted, есть год/лицензия)",
            {"row": gateway_row},
            evidence,
        )
        spoofed = api(
            "/api/v1/sources",
            headers={"X-Philograph-Region": "DE", "CF-IPCountry": "DE"},
        ).json()
        spoof_row = sources_by_id(spoofed).get(restricted)
        record(
            "UC-10/gateway",
            spoof_row is not None and not spoof_row.get("restricted"),
            "клиентские заголовки не подменяют регион: источник открыт по запасному RU",
            {"row": spoof_row},
            evidence,
        )
        headers = api("/api/v1/sources").headers
        cache_values = headers.get_list("cache-control")
        record(
            "TC-25",
            cache_values == ["private"],
            "ответ API через шлюз помечен одним Cache-Control: private",
            {"cache_control": cache_values},
            evidence,
        )

        # Библиотека напрямую: регион неизвестен, строка закрыта.
        with httpx.Client(timeout=30) as client:
            direct = client.get(library + "/api/v1/sources").json()
            direct_ru = client.get(
                library + "/api/v1/sources", headers={"X-Philograph-Region": "RU"}
            ).json()
        direct_row = sources_by_id(direct).get(restricted)
        record(
            "UC-3/direct",
            direct_row is not None and direct_row.get("restricted") is True,
            "напрямую в библиотеке без заголовка региона источник [RU] закрыт",
            {"row": direct_row},
            evidence,
        )
        record(
            "TC-9",
            not sources_by_id(direct_ru).get(restricted, {}).get("restricted"),
            "прямой запрос с X-Philograph-Region: RU открывает источник",
            {"row": sources_by_id(direct_ru).get(restricted)},
            evidence,
        )

        # Внутренние интерфейсы не фильтруют по региону (R7).
        with httpx.Client(timeout=30) as client:
            published = client.get(library + "/api/v1/internal/published").json()
            closed = client.get(library + "/api/v1/internal/access", params={"region": "DE"}).json()
            allowed = client.get(library + "/api/v1/internal/access", params={"region": "RU"}).json()
            version = client.get(
                library + f"/api/v1/internal/versions/{published_item(published, restricted)}/paragraphs"
            ).json()
        record(
            "TC-14",
            any(p["source_id"] == restricted for p in published),
            "GET /internal/published содержит ограниченный источник",
            {"sources": [p["source_id"] for p in published]},
            evidence,
        )
        record(
            "TC-15",
            restricted in closed.get("closed", [])
            and restricted not in allowed.get("closed", []),
            "GET /internal/access: для DE закрытый идентификатор есть, для RU — нет",
            {"DE": closed, "RU": allowed},
            evidence,
        )
        paragraph_id = version["paragraphs"][0]["id"]
        record(
            "TC-16",
            {"regions", "permissions", "external_processing"} <= set(version),
            "внутренний ответ версии несёт regions, permissions, external_processing",
            {"fields": sorted(version)},
            evidence,
        )
        # UC-4: ссылка на абзац из другого региона.
        with httpx.Client(timeout=30) as client:
            de_paragraph = client.get(
                library + f"/api/v1/paragraphs/{paragraph_id}",
                headers={"X-Philograph-Region": "DE"},
            ).json()
            ru_paragraph = client.get(
                library + f"/api/v1/paragraphs/{paragraph_id}",
                headers={"X-Philograph-Region": "RU"},
            ).json()
        record(
            "TC-12",
            de_paragraph.get("status") == "source_unavailable"
            and de_paragraph.get("reason") == "region"
            and "text" not in de_paragraph,
            "GET /paragraphs/{id} из DE: source_unavailable с причиной region, без текста",
            {"DE": de_paragraph, "RU_status": ru_paragraph.get("status")},
            evidence,
        )

        # TC-38/EC-33: change_license уносит действующие регионы (вид [RU], сужения нет).
        from philograph.library.registry import License, Registry

        engine = lib_engine(STAND)
        registry = Registry(engine)
        before_embedding = embedding_calls(stack)
        registry.change_license("operator", restricted, License("demo-ru", "public_domain",
                                                              author_death_years=[1900]))
        payload = outbox_payloads(STAND)[0]
        event = json.loads(payload["payload"]) if isinstance(payload["payload"], str) else payload["payload"]
        record(
            "TC-38",
            payload["kind"] == "source.access_changed" and event["regions"] == ["RU"],
            "change_license у вида [RU] без сужения источника: в событии regions == ['RU']",
            {"kind": payload["kind"], "regions": event.get("regions"),
             "permissions": event.get("permissions")},
            evidence,
        )
        dispatch_outbox(STAND)

        # TC-31/UC-17: смена регионов по событию, эмбеддинги не пересчитываются.
        hidden_for_de = restricted not in found_sources(search_api(MARKER, region="DE", limit=10))
        # Снимаем ограничение (вид открыт) — источник становится виден всем.
        registry.change_license("operator", restricted, License("demo-open", "open_license"))
        dispatch_outbox(STAND)
        deadline = time.time() + 60
        opened = False
        while time.time() < deadline:
            hit = search_api(MARKER, region="DE", limit=10)
            if restricted in found_sources(hit):
                opened = True
                break
            time.sleep(1.0)
        after_embedding = embedding_calls(stack)
        record(
            "TC-31",
            hidden_for_de and opened and after_embedding == before_embedding,
            "событие source.access_changed меняет видимость для DE без вызовов эмбеддера",
            {"hidden_before": hidden_for_de, "visible_for_DE": opened,
             "embedding_calls_before": before_embedding,
             "embedding_calls_after": after_embedding},
            [str(STAND / "logs" / "llm.log"), str(ROUND / "live-report.json")],
        )
        stale = blocked_sources(STAND, restricted)
        record(
            "TC-34/live",
            stale["regions"] == ["*"],
            "снятие ограничения записывает в индекс регионы '*'",
            stale,
            evidence,
        )

        # TC-36/EC-30: повтор события безвреден, эмбеддер не вызывается.
        from philograph.platform.queue import Queue

        queue_engine = lib_engine(STAND)
        queue = Queue(queue_engine)
        duplicate = {
            "event_id": "qa-dup-event",
            "source_id": restricted,
            "regions": ["RU"],
            "permissions": {"display": True, "external_processing": True, "quoting": True},
        }
        queue.enqueue("search:source.access_changed", duplicate, key="qa-dup-1")
        queue.enqueue("search:source.access_changed", duplicate, key="qa-dup-2")
        deadline = time.time() + 60
        duplicate_logged = False
        while time.time() < deadline:
            if any(e.get("event") == "search.index.duplicate" for e in stack.logs("search")):
                duplicate_logged = True
                break
            time.sleep(1.0)
        still_hidden = restricted not in found_sources(search_api(MARKER, region="DE", limit=10))
        record(
            "TC-36",
            duplicate_logged and still_hidden and embedding_calls(stack) == before_embedding,
            "повторное событие — дубликат: работа не повторяется, эмбеддер не вызывается, "
            "видимость для DE прежняя",
            {"duplicate_logged": duplicate_logged, "hidden_for_DE": still_hidden,
             "embedding_calls": embedding_calls(stack)},
            [str(STAND / "logs" / "search.log")],
        )

        # TC-37/EC-28: regions: [] закрывает источник всем регионам.
        queue = Queue(lib_engine(STAND))
        queue.enqueue(
            "search:source.access_changed",
            {
                "event_id": "qa-empty-event",
                "source_id": restricted,
                "regions": [],
                "permissions": {"display": False, "external_processing": True, "quoting": True},
            },
            key="qa-empty-1",
        )
        deadline = time.time() + 60
        closed_all = False
        close_state: dict = {}
        while time.time() < deadline:
            de = search_api(MARKER, region="DE", limit=10)
            ru = search_api(MARKER, region="RU", limit=10)
            none = search_api(MARKER, limit=10)
            if all(restricted not in found_sources(x) for x in (de, ru, none)):
                closed_all = True
                close_state = blocked_sources(STAND, restricted)
                break
            time.sleep(1.0)
        record(
            "TC-37",
            closed_all and close_state["regions"] == [","],
            "regions: [] закрывает источник всем: ни RU, ни DE, ни без региона; в индексе ','",
            {"closed_all": closed_all, "state": close_state},
            [str(STAND / "logs" / "search.log")],
        )

        # Возвращаем ограничение и проверяем сверку индексов (TC-32/UC-18).
        registry.change_license(
            "operator", restricted, License("demo-ru", "public_domain", author_death_years=[1900])
        )
        dispatch_outbox(STAND)
        deadline = time.time() + 60
        while time.time() < deadline:
            if restricted in found_sources(search_api(MARKER, region="RU", limit=10)):
                break
            time.sleep(1.0)
        set_regions_stale(STAND, restricted)  # расхождение: в индексе '*', в библиотеке [RU]
        with httpx.Client(timeout=60) as client:
            first = client.post(search + "/v1/internal/reconcile").json()
            second = client.post(search + "/v1/internal/reconcile").json()
        fixed = blocked_sources(STAND, restricted)
        de_after = search_api(MARKER, region="DE", limit=10)
        ru_after = search_api(MARKER, region="RU", limit=10)
        record(
            "TC-32",
            first == {"missing": 0, "extra": 0}
            and second == {"missing": 0, "extra": 0}
            and fixed["regions"] == [",RU,"]
            and all(fixed["active"])
            and restricted not in found_sources(de_after)
            and restricted in found_sources(ru_after),
            "сверка чинит регионы (',RU,'), не гасит закрытый источник, повтор без изменений",
            {"first": first, "second": second, "state": fixed,
             "DE": found_sources(de_after), "RU": found_sources(ru_after)},
            [str(STAND / "logs" / "search.log")],
        )
        record(
            "EC-31",
            second == {"missing": 0, "extra": 0},
            "повторная сверка без расхождений: {missing: 0, extra: 0}",
            second,
            evidence,
        )

        # TC-35/EC-29: провайдер эмбеддингов недоступен — поиск по словам, регион соблюдается.
        llm_process = stack.processes["llm"]
        llm_process.terminate()
        try:
            llm_process.wait(10)
        except Exception:  # noqa: BLE001
            llm_process.kill()
        degraded_de = search_api(MARKER, region="DE", limit=10)
        degraded_ru = search_api(MARKER, region="RU", limit=10)
        degraded_none = search_api(MARKER, limit=10)
        record(
            "TC-35",
            degraded_de.get("semantic_used") is False
            and degraded_ru.get("semantic_used") is False
            and restricted not in found_sources(degraded_de)
            and restricted not in found_sources(degraded_none)
            and restricted in found_sources(degraded_ru),
            "провайдер эмбеддингов недоступен: ответ только по словам, ограниченный источник "
            "по-прежнему виден только RU",
            {"semantic_used_DE": degraded_de.get("semantic_used"), "DE": found_sources(degraded_de),
             "none": found_sources(degraded_none), "RU": found_sources(degraded_ru)},
            [str(STAND / "logs" / "search.log")],
        )

        # Второй шлюз: имя заголовка страны задано, прокси не доверенный, запасной RU.
        env = {**os.environ}
        env.update(
            {
                "PHILOGRAPH_DATABASE_URL": f"sqlite:///{(STAND / 'stack.db').as_posix()}",
                "PHILOGRAPH_LIBRARY_URL": library,
                "PHILOGRAPH_ASSISTANT_URL": f"http://127.0.0.1:{port_of['assistant']}",
                "PHILOGRAPH_KNOWLEDGE_URL": f"http://127.0.0.1:{port_of['knowledge']}",
                "PHILOGRAPH_REGION_HEADER": "CF-IPCountry",
                "PHILOGRAPH_REGION_FALLBACK": "RU",
                "PHILOGRAPH_WEB_ROOT": str(REPO / "web" / "dist"),
            }
        )
        env.pop("PHILOGRAPH_TRUSTED_PROXY", None)
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            alt_port = s.getsockname()[1]
        log = open(ROUND / "gateway-alt.log", "w", encoding="utf-8")  # noqa: SIM115
        proc = __import__("subprocess").Popen(
            [sys.executable, "-m", "uvicorn", "philograph.gateway.app:app",
             "--port", str(alt_port), "--log-level", "warning"],
            cwd=str(REPO),
            env=env,
            stdout=log,
            stderr=__import__("subprocess").STDOUT,
        )
        alt_url = f"http://127.0.0.1:{alt_port}"
        try:
            deadline = time.time() + 60
            ready = False
            while time.time() < deadline:
                try:
                    if httpx.get(alt_url + "/health/ready", timeout=2).status_code == 200:
                        ready = True
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(0.3)
            spoof_alt = httpx.get(
                alt_url + "/api/v1/sources",
                headers={"CF-IPCountry": "DE", "X-Philograph-Region": "DE"},
                timeout=30,
            ).json()
            alt_row = sources_by_id(spoof_alt).get(restricted)
            record(
                "EC-19/alt-gateway",
                ready and alt_row is not None and not alt_row.get("restricted"),
                "заголовок страны от клиента при недоверенном прокси игнорируется: работает "
                "запасной RU, источник открыт",
                {"ready": ready, "row": alt_row, "port": alt_port},
                [str(ROUND / "gateway-alt.log")],
            )
        finally:
            proc.terminate()
            try:
                proc.wait(10)
            except Exception:  # noqa: BLE001
                proc.kill()
            log.close()

        # Браузерные сценарии.
        browser_checks(gateway, library, RU_TITLE, CHECKS)

    finally:
        # Браузерные проверки попадают в список дважды (record + results): оставляем по одной.
        unique = {(c["id"], c["expected"], c["actual"]): c for c in CHECKS}
        CHECKS[:] = list(unique.values())
        report = {
            "stack": {
                "url": gateway,
                "ports": port_of,
                "sources": ids,
                "logs": str(STAND / "logs"),
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


def published_item(published: list[dict], source_id: str) -> str:
    return next(p["version_id"] for p in published if p["source_id"] == source_id)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        (ROUND / "live-crash.log").write_text(traceback.format_exc(), encoding="utf-8")
        raise
