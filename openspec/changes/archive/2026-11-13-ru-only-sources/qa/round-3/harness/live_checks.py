"""Независимая проверка группы 3 (шлюз) на живом шлюзе и в браузере.

Поднимает поддельные сервисы и четыре настоящих шлюза (uvicorn, модуль
``philograph.gateway.app:app``) с разными настройками региона, гоняет по ним
запросы через httpx и Playwright, складывает скриншоты и JSON-отчёт.

Код продукта не меняется: только проверка. Запуск:
``.venv/Scripts/python.exe openspec/changes/ru-only-sources/qa/round-3/harness/live_checks.py``
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[6]
QA = Path(__file__).resolve().parents[1]
HARNESS = Path(__file__).resolve().parent
SHOTS = ROOT / "openspec" / "changes" / "ru-only-sources" / "qa" / "screenshots" / "round-3"
LOGS = QA / "harness" / "logs"
SHOTS.mkdir(parents=True, exist_ok=True)
LOGS.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(ROOT / "src"))

TOKEN = "служебный".encode().hex()
STEPS: list[dict] = []
PROCESSES: list[subprocess.Popen] = []


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start(name: str, module: str, port: int, env: dict[str, str]) -> str:
    path = LOGS / f"{name}.log"
    log = open(path, "w", encoding="utf-8")  # noqa: SIM115
    full_env = {
        **os.environ,
        **env,
        "PYTHONUTF8": "1",
        "PYTHONPATH": os.pathsep.join([str(ROOT / "src"), str(HARNESS)]),
    }
    PROCESSES.append(
        subprocess.Popen(
            [sys.executable, "-m", "uvicorn", module, "--port", str(port), "--log-level", "warning"],
            cwd=ROOT,
            env=full_env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    )
    return f"http://127.0.0.1:{port}"


def wait(url: str, seconds: float = 60) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            httpx.get(f"{url}/health/live", timeout=2)
            return
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    raise RuntimeError(f"не поднялся: {url}")


def shot(page, name: str) -> str:
    path = SHOTS / f"{name}.png"
    page.screenshot(path=str(path), full_page=True)
    return str(path.relative_to(ROOT)).replace("\\", "/")


def page_showing(page, title: str, lines: list[str]) -> None:
    """Страница отчёта в браузере: то, что реально пришло в ответе."""
    esc = (
        lambda s: s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")  # noqa: E731
    )
    rows = "".join(f"<li>{esc(line)}</li>" for line in lines)
    page.set_content(
        f"<!doctype html><meta charset='utf-8'><title>{esc(title)}</title>"
        f"<body style='font:14px/1.5 ui-monospace,Consolas,monospace;padding:24px'>"
        f"<h1 style='font:600 18px sans-serif'>{esc(title)}</h1><ul>{rows}</ul></body>"
    )


def record(case: str, step: str, title: str, ok: bool, expected: str, actual, evidence) -> None:
    STEPS.append(
        {
            "case": case,
            "step": step,
            "title": title,
            "ok": bool(ok),
            "expected": expected,
            "actual": actual,
            "evidence": [e for e in evidence if e],
        }
    )


def seen_headers(payload: dict) -> dict[str, str]:
    return {k.lower(): v for k, v in payload["headers"]}


def region_of(payload: dict) -> str | None:
    return seen_headers(payload).get("x-philograph-region")


def main() -> None:
    fake_port = free_port()
    fake = start("fake-services", "fake_services:app", fake_port, {})
    wait(fake)
    upstreams = {
        "PHILOGRAPH_LIBRARY_URL": f"{fake}/library",
        "PHILOGRAPH_ASSISTANT_URL": f"{fake}/assistant",
    }
    common = {
        **upstreams,
        "PHILOGRAPH_INTERNAL_TOKEN": TOKEN,
        "PHILOGRAPH_VISITOR_SECRET": "round-3",
        "PHILOGRAPH_WEB_ROOT": str(ROOT / "web" / "dist"),
    }
    trusted = start(
        "gateway-trusted",
        "philograph.gateway.app:app",
        free_port(),
        {
            **common,
            "PHILOGRAPH_REGION_HEADER": "CF-IPCountry",
            "PHILOGRAPH_TRUSTED_PROXY": "1",
        },
    )
    untrusted = start(
        "gateway-untrusted",
        "philograph.gateway.app:app",
        free_port(),
        {**common, "PHILOGRAPH_REGION_HEADER": "CF-IPCountry"},
    )
    fallback = start(
        "gateway-fallback",
        "philograph.gateway.app:app",
        free_port(),
        {
            **common,
            "PHILOGRAPH_REGION_HEADER": "CF-IPCountry",
            "PHILOGRAPH_TRUSTED_PROXY": "1",
            "PHILOGRAPH_REGION_FALLBACK": "RU",
        },
    )
    untrusted_fallback = start(
        "gateway-untrusted-fallback",
        "philograph.gateway.app:app",
        free_port(),
        {
            **common,
            "PHILOGRAPH_REGION_HEADER": "CF-IPCountry",
            "PHILOGRAPH_REGION_FALLBACK": "RU",
        },
    )
    bare = start(
        "gateway-bare",
        "philograph.gateway.app:app",
        free_port(),
        {**common, "PHILOGRAPH_TRUSTED_PROXY": "1"},
    )
    for url in (trusted, untrusted, fallback, untrusted_fallback, bare):
        wait(url)

    report = {
        "gateways": {
            "trusted": trusted,
            "untrusted": untrusted,
            "fallback": fallback,
            "untrusted_fallback": untrusted_fallback,
            "bare": bare,
            "fake": fake,
        }
    }

    with httpx.Client(timeout=10.0) as client:

        def call(base: str, headers: dict[str, str], path: str = "/api/v1/sources") -> httpx.Response:
            return client.get(f"{base}{path}", headers=headers)

        # --- TC-18: доверенный прокси, страна RU ---------------------------------------
        response = call(trusted, {"CF-IPCountry": "RU"})
        payload = response.json()
        record(
            "TC-18",
            "1",
            "доверенный прокси, заголовок страны RU",
            region_of(payload) == "RU",
            "сервис получает X-Philograph-Region: RU",
            {"status": response.status_code, "region_seen": region_of(payload)},
            [],
        )

        # --- TC-19: клиент подделал регион, CDN сообщает DE -----------------------------
        response = call(trusted, {"CF-IPCountry": "DE", "X-Philograph-Region": "RU"})
        payload = response.json()
        headers_seen = seen_headers(payload)
        record(
            "TC-19",
            "1",
            "клиент прислал X-Philograph-Region: RU, CDN сообщает DE",
            region_of(payload) == "DE" and "ru" not in headers_seen.values(),
            "сервис получает DE; клиентского заголовка в запросе нет",
            {"region_seen": region_of(payload), "cf_sent": "cf-ipcountry" in headers_seen},
            [],
        )

        # --- TC-20: только клиентский регион, страны нет --------------------------------
        response = call(trusted, {"X-Philograph-Region": "RU"})
        payload = response.json()
        record(
            "TC-20",
            "1",
            "клиентский X-Philograph-Region без страны от CDN",
            region_of(payload) is None,
            "сервис получает запрос без заголовка региона",
            {"region_seen": region_of(payload)},
            [],
        )

        # --- TC-21: прокси не доверенный ------------------------------------------------
        response = call(untrusted, {"CF-IPCountry": "RU", "X-Philograph-Region": "RU"})
        payload = response.json()
        headers_seen = seen_headers(payload)
        record(
            "TC-21",
            "1",
            "PHILOGRAPH_TRUSTED_PROXY выключен, есть страна RU",
            region_of(payload) is None and "cf-ipcountry" not in headers_seen,
            "сервис без заголовка региона; клиентский и внешний заголовки удалены",
            {"region_seen": region_of(payload), "cf_sent": "cf-ipcountry" in headers_seen},
            [],
        )

        # --- TC-18: регион доходит и до ассистента, и до знаний -------------------------
        response = call(trusted, {"CF-IPCountry": "RU"}, "/api/assistant/ask")
        record(
            "TC-18",
            "3",
            "регион передаётся в ассистента",
            region_of(response.json()) == "RU",
            "сервис ассистента получает X-Philograph-Region: RU",
            {"region_seen": region_of(response.json())},
            [],
        )
        response = call(trusted, {"CF-IPCountry": "RU"}, "/api/knowledge/cards")
        record(
            "TC-18",
            "4",
            "регион передаётся в знания (если адрес подключён)",
            response.status_code in (200, 404),
            "200 при подключённых знаниях, иначе 404 — в этом стенде знания не подключены",
            {"status": response.status_code},
            [],
        )

        # --- TC-22: запасной регион -----------------------------------------------------
        response = call(fallback, {})
        record(
            "TC-22",
            "1",
            "PHILOGRAPH_REGION_FALLBACK=RU, заголовка страны нет",
            region_of(response.json()) == "RU",
            "сервис получает RU",
            {"region_seen": region_of(response.json())},
            [],
        )
        response = call(fallback, {"CF-IPCountry": "DE"})
        record(
            "TC-22",
            "2",
            "запасной регион не перебивает страну от CDN",
            region_of(response.json()) == "DE",
            "страна от CDN важнее запасного региона",
            {"region_seen": region_of(response.json())},
            [],
        )
        # EC-19: недоверенный прокси + запасной регион.
        response = call(untrusted_fallback, {"CF-IPCountry": "DE"})
        record(
            "EC-19",
            "1",
            "недоверенный прокси при заданном запасном регионе",
            region_of(response.json()) == "RU",
            "страна игнорируется, подставляется запасной RU",
            {"region_seen": region_of(response.json())},
            [],
        )

        # EC-16: имя заголовка страны не задано.
        response = call(bare, {"CF-IPCountry": "RU"})
        payload = response.json()
        record(
            "EC-16",
            "1",
            "PHILOGRAPH_REGION_HEADER не задан, клиент прислал страну",
            region_of(payload) is None,
            "регион неизвестен: заголовка региона сервису нет",
            {"region_seen": region_of(payload), "cf_sent": "cf-ipcountry" in seen_headers(payload)},
            [],
        )

        # --- TC-23 / EC-17 / EC-18: значения заголовка страны ---------------------------
        # Не-ASCII ("РФ") и состоящее из пробелов значение HTTP-клиент не отправит
        # вовсе: HTTP такой заголовок не пропускает. Разбираем их прямой проверкой
        # функции разбора, а по проводу гоняем то, что реально может прийти.
        from philograph.gateway.region import normalize_region

        direct = {
            "РФ": normalize_region("РФ"),
            "  ": normalize_region("  "),
            " ru ": normalize_region(" ru "),
            None: normalize_region(None),
        }
        record(
            "EC-18",
            "1",
            "не-ASCII, пробелы и пустое значение в разборе региона",
            direct == {"РФ": None, "  ": None, " ru ": "RU", None: None},
            "РФ и пробелы — неизвестный регион; ' ru ' приводится к RU",
            {str(k): v for k, v in direct.items()},
            [],
        )
        matrix = ["XX", "T1", "RUS", "RU1", "R", "1R"]
        results = {}
        for value in matrix:
            response = call(trusted, {"CF-IPCountry": value})
            results[value] = region_of(response.json())
        record(
            "TC-23",
            "1",
            "служебные коды и не-двухбуквенные значения",
            all(v is None for v in results.values()),
            "для всех значений регион неизвестен",
            results,
            [],
        )
        response = call(trusted, {})
        results["<нет заголовка>"] = region_of(response.json())
        # EC-24: неверный запасной регион в настройках.
        bad_fallback = start(
            "gateway-bad-fallback",
            "philograph.gateway.app:app",
            free_port(),
            {
                **common,
                "PHILOGRAPH_REGION_HEADER": "CF-IPCountry",
                "PHILOGRAPH_TRUSTED_PROXY": "1",
                "PHILOGRAPH_REGION_FALLBACK": "XX",
            },
        )
        wait(bad_fallback)
        results["fallback=XX"] = region_of(call(bad_fallback, {}).json())
        record(
            "EC-24",
            "1",
            "неверный запасной регион XX",
            results["fallback=XX"] is None,
            "значение считается пустым, регион неизвестен",
            results,
            [],
        )

        # --- TC-24 / EC-18: нижний регистр и пробелы -----------------------------------
        lower = call(trusted, {"CF-IPCountry": "ru"})
        mixed = call(trusted, {"CF-IPCountry": "De"})
        record(
            "TC-24",
            "1",
            "значение страны в нижнем регистре",
            region_of(lower.json()) == "RU" and region_of(mixed.json()) == "DE",
            "сервис получает RU (и DE для 'De')",
            {
                "ru": region_of(lower.json()),
                "De": region_of(mixed.json()),
            },
            [],
        )

        # --- TC-25 / EC-21: кэш и Vary -------------------------------------------------
        response = call(trusted, {"CF-IPCountry": "RU"})
        payload = response.json()
        headers_out = {k.lower(): v for k, v in response.headers.items()}
        api_ok = (
            headers_out.get("cache-control") == "private"
            and "cf-ipcountry" in headers_out.get("vary", "").lower()
            and "accept-encoding" in headers_out.get("vary", "").lower()
            and "cf-ipcountry" not in seen_headers(payload)
        )
        record(
            "TC-25",
            "1",
            "ответ /api/v1/sources через шлюз",
            api_ok,
            "Cache-Control: private; Vary содержит имя заголовка страны (и прежнее значение сервиса)",
            {
                "cache_control": headers_out.get("cache-control"),
                "vary": headers_out.get("vary"),
                "country_forwarded": "cf-ipcountry" in seen_headers(payload),
            },
            [],
        )
        page_response = call(trusted, {"CF-IPCountry": "RU"}, "/")
        page_headers = {k.lower(): v for k, v in page_response.headers.items()}
        record(
            "EC-21",
            "1",
            "страница (не /api/*) через шлюз",
            page_headers.get("cache-control") != "private" and page_response.status_code == 200,
            "статика и страницы не помечены Cache-Control: private",
            {
                "status": page_response.status_code,
                "cache_control": page_headers.get("cache-control"),
            },
            [],
        )

        # --- TC-26 / EC-22: счётчик и отсутствие страны --------------------------------

        def gateway_counters() -> dict[str, float]:
            snapshot = client.get(
                f"{trusted}/internal/metrics", headers={"X-Internal-Token": TOKEN}
            ).json()
            return {
                c["labels"].get("kind", "?"): c["value"]
                for c in snapshot["counters"]
                if c["name"] == "gateway.region"
            }

        before = gateway_counters()
        call(trusted, {"CF-IPCountry": "RU"})
        call(trusted, {})
        after = gateway_counters()
        record(
            "TC-26",
            "1",
            "два запроса: с регионом и без",
            after.get("known", 0) - before.get("known", 0) == 1
            and after.get("unknown", 0) - before.get("unknown", 0) == 1,
            "gateway.region считает known/unknown",
            {"before": before, "after": after},
            [],
        )

        # --- TC-27: правило оповещений поверх живого счётчика --------------------------
        from philograph.ops.alerts import AlertSettings, UnknownRegionRule

        def live_metrics() -> dict:
            return client.get(
                f"{trusted}/internal/metrics", headers={"X-Internal-Token": TOKEN}
            ).json()

        strict = UnknownRegionRule(live_metrics, AlertSettings(unknown_region_ratio=0.1,
                                                               unknown_region_min_requests=10))
        baseline = strict()  # точка отсчёта
        for i in range(10):
            call(trusted, {"CF-IPCountry": "RU"} if i == 0 else {})
        warning = strict()
        default_rule = UnknownRegionRule(live_metrics, AlertSettings())
        default_rule()  # точка отсчёта
        for i in range(10):
            call(trusted, {"CF-IPCountry": "RU"} if i == 0 else {})
        small = default_rule()
        text = json.dumps(
            {"warning": warning.summary, "details": warning.details, "small": small.summary},
            ensure_ascii=False,
        )
        record(
            "TC-27",
            "1",
            "правило «Регион читателя» над живым счётчиком шлюза",
            warning.firing and "90.0%" in warning.summary and not small.firing,
            "при 9 неизвестных из 10 правило срабатывает; при минимуме 100 запросов — нет; стран в сообщении нет",
            {
                "baseline": baseline.summary,
                "warning": {"firing": warning.firing, "summary": warning.summary,
                            "details": warning.details},
                "default_min_100": {"firing": small.firing, "summary": small.summary},
                "country_in_message": "RU" in text or "CF-" in text,
            },
            [],
        )

        # --- EC-22: коды стран в журнале шлюза -----------------------------------------
        log_text = (LOGS / "gateway-trusted.log").read_text(encoding="utf-8", errors="replace")
        leaked = [line for line in log_text.splitlines() if '"RU"' in line or "CF-IPCountry" in line]
        record(
            "EC-22",
            "1",
            "журнал шлюза после запросов с RU",
            not leaked,
            "кода страны в событиях нет",
            {"lines_with_country": leaked[:3], "lines": len(log_text.splitlines())},
            [],
        )

    # ------------------------------------------------------------------ браузер -------
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()

        def visit(case: str, step: str, title: str, base: str, headers: dict[str, str],
                  expected_region: str | None) -> None:
            context = browser.new_context(extra_http_headers=headers, viewport={"width": 1200,
                                                                                "height": 800})
            page = context.new_page()
            response = page.goto(f"{base}/api/v1/sources", wait_until="load")
            body = page.inner_text("body")
            payload = json.loads(body)
            region = region_of(payload)
            out_headers = {k.lower(): v for k, v in response.headers.items()}
            first = shot(page, f"{case}-{step}-response")
            lines = [
                f"GET /api/v1/sources  ->  {response.status}",
                f"пришло в сервис: x-philograph-region = {region}",
                f"в сервис пришёл заголовок страны: {'cf-ipcountry' in seen_headers(payload)}",
                f"Cache-Control ответа: {out_headers.get('cache-control')}",
                f"Vary ответа: {out_headers.get('vary')}",
            ]
            page_showing(page, f"{case}: {title}", lines)
            second = shot(page, f"{case}-{step}-summary")
            # Заголовок страны забираем из браузера, не пересылая его в шлюз?
            # Нет: Playwright шлёт его как обычный заголовок запроса — ровно как CDN.
            record(
                case,
                step,
                title,
                region == expected_region,
                f"регион в сервисе: {expected_region}",
                {"status": response.status, "region_seen": region,
                 "cache_control": out_headers.get("cache-control"),
                 "vary": out_headers.get("vary")},
                [first, second],
            )
            context.close()

        visit("TC-18", "2", "браузер: страна RU от доверенного CDN", trusted,
              {"CF-IPCountry": "RU"}, "RU")
        visit("TC-19", "2", "браузер: клиент подделал регион, CDN сообщает DE", trusted,
              {"CF-IPCountry": "DE", "X-Philograph-Region": "RU"}, "DE")
        visit("TC-20", "2", "браузер: только клиентский регион", trusted,
              {"X-Philograph-Region": "RU"}, None)
        visit("TC-21", "2", "браузер: прокси не доверенный", untrusted,
              {"CF-IPCountry": "RU", "X-Philograph-Region": "RU"}, None)
        visit("TC-22", "3", "браузер: запасной регион стенда", fallback, {}, "RU")
        visit("EC-16", "2", "браузер: имя заголовка страны не задано", bare,
              {"CF-IPCountry": "RU"}, None)

        # TC-23: матрица значений в браузере.
        context = browser.new_context(viewport={"width": 1200, "height": 800})
        page = context.new_page()
        matrix_lines = []
        matrix_ok = True
        for label, value in [
            ("XX", "XX"),
            ("T1", "T1"),
            ("RUS", "RUS"),
            ("RU1", "RU1"),
            ("R", "R"),
        ]:
            page.set_extra_http_headers({"CF-IPCountry": value})
            page.goto(f"{trusted}/api/v1/sources", wait_until="load")
            region = region_of(json.loads(page.inner_text("body")))
            matrix_lines.append(f"CF-IPCountry = {label!r}  ->  регион в сервисе: {region}")
            matrix_ok = matrix_ok and region is None
        first = shot(page, "TC-23-2-browser-matrix")
        page_showing(page, "TC-23: значения заголовка страны в браузере", matrix_lines)
        second = shot(page, "TC-23-3-browser-matrix-summary")
        record(
            "TC-23",
            "2",
            "браузер: XX/T1/RUS/РФ/RU1/R",
            matrix_ok,
            "во всех случаях регион неизвестен",
            matrix_lines,
            [first, second],
        )
        context.close()

        # TC-24 в браузере: нижний регистр.
        context = browser.new_context(extra_http_headers={"CF-IPCountry": "ru"})
        page = context.new_page()
        page.goto(f"{trusted}/api/v1/sources", wait_until="load")
        region = region_of(json.loads(page.inner_text("body")))
        first = shot(page, "TC-24-2-browser-lowercase")
        page_showing(page, "TC-24: CF-IPCountry = 'ru'", [f"регион в сервисе: {region}"])
        second = shot(page, "TC-24-3-browser-lowercase-summary")
        record("TC-24", "2", "браузер: 'ru' в нижнем регистре", region == "RU", "RU",
               {"region_seen": region}, [first, second])
        context.close()

        # TC-25: заголовки ответа в браузере.
        context = browser.new_context(extra_http_headers={"CF-IPCountry": "RU"})
        page = context.new_page()
        response = page.goto(f"{trusted}/api/v1/sources", wait_until="load")
        out_headers = {k.lower(): v for k, v in response.headers.items()}
        first = shot(page, "TC-25-2-browser-api")
        page_showing(
            page,
            "TC-25: заголовки ответа /api/v1/sources",
            [
                f"status: {response.status}",
                f"cache-control: {out_headers.get('cache-control')}",
                f"vary: {out_headers.get('vary')}",
                f"content-type: {out_headers.get('content-type')}",
            ],
        )
        second = shot(page, "TC-25-3-browser-api-headers")
        record(
            "TC-25",
            "2",
            "браузер: Cache-Control и Vary",
            out_headers.get("cache-control") == "private"
            and "cf-ipcountry" in out_headers.get("vary", "").lower(),
            "Cache-Control: private, Vary с именем заголовка страны",
            {"cache_control": out_headers.get("cache-control"), "vary": out_headers.get("vary")},
            [first, second],
        )
        # EC-21: страница продукта — без private.
        page_response = page.goto(f"{trusted}/", wait_until="load")
        page_headers = {k.lower(): v for k, v in page_response.headers.items()}
        first = shot(page, "EC-21-2-browser-page")
        page_showing(
            page,
            "EC-21: заголовки страницы продукта",
            [f"status: {page_response.status}",
             f"cache-control: {page_headers.get('cache-control')}",
             f"vary: {page_headers.get('vary')}"],
        )
        second = shot(page, "EC-21-3-browser-page-headers")
        record(
            "EC-21",
            "2",
            "браузер: страница продукта не помечена private",
            page_headers.get("cache-control") != "private" and page_response.status == 200,
            "страница без Cache-Control: private",
            {"cache_control": page_headers.get("cache-control")},
            [first, second],
        )
        context.close()

        # TC-26: метрики шлюза видны с токеном и без стран.
        context = browser.new_context(extra_http_headers={"X-Internal-Token": TOKEN})
        page = context.new_page()
        response = page.goto(f"{trusted}/internal/metrics", wait_until="load")
        body = page.inner_text("body")
        text = json.dumps(json.loads(body), ensure_ascii=False)
        region_rows = [
            line for line in text.split("{") if "gateway.region" in line
        ]
        safe = '"RU"' not in text and "CF-IPCountry" not in text
        lines = [f"status: {response.status}"] + [
            line.strip()[:160] for line in region_rows[:4]
        ]
        lines.append(f"страны в дампе метрик нет: {safe}")
        shot(page, "TC-26-2-browser-metrics")
        page_showing(page, "TC-26: метрика gateway.region", lines)
        second = shot(page, "TC-26-3-browser-metrics-summary")
        record(
            "TC-26",
            "2",
            "браузер: дамп метрик шлюза",
            response.status == 200 and "gateway.region" in text and safe,
            "только known/unknown, без стран",
            {"status": response.status, "region_rows": len(region_rows), "no_country": safe},
            [second],
        )
        # Без токена дампа нет.
        anonymous = browser.new_context()
        anonymous_page = anonymous.new_page()
        anonymous_response = anonymous_page.goto(f"{trusted}/internal/metrics",
                                                 wait_until="load")
        record(
            "TC-26",
            "3",
            "метрики без служебного токена закрыты",
            anonymous_response.status == 404,
            "404",
            {"status": anonymous_response.status},
            [shot(anonymous_page, "TC-26-4-browser-metrics-no-token")],
        )
        anonymous.close()
        context.close()

        # TC-27: правило оповещений и его сообщение.
        from philograph.ops.alerts import AlertSettings, UnknownRegionRule

        screens = iter(
            [
                {"counters": [
                    {"name": "gateway.region", "labels": {"kind": "known"}, "value": 1},
                    {"name": "gateway.region", "labels": {"kind": "unknown"}, "value": 0}]},
                {"counters": [
                    {"name": "gateway.region", "labels": {"kind": "known"}, "value": 2},
                    {"name": "gateway.region", "labels": {"kind": "unknown"}, "value": 9}]},
                {"counters": [
                    {"name": "gateway.region", "labels": {"kind": "known"}, "value": 3},
                    {"name": "gateway.region", "labels": {"kind": "unknown"}, "value": 9}]},
                {"counters": [
                    {"name": "gateway.region", "labels": {"kind": "known"}, "value": 3},
                    {"name": "gateway.region", "labels": {"kind": "unknown"}, "value": 10}]},
            ]
        )
        rule = UnknownRegionRule(lambda: next(screens), AlertSettings(unknown_region_ratio=0.1,
                                                                    unknown_region_min_requests=10))
        rule()
        fired = rule()
        few = rule()
        page = browser.new_context().new_page()
        page_showing(
            page,
            "TC-27 / EC-25: правило «Регион читателя»",
            [
                f"11 запросов, 9 неизвестных: firing={fired.firing}; {fired.summary}",
                f"details: {fired.details}",
                f"мало запросов: firing={few.firing}; {few.summary}",
                f"стран в сообщении нет: {'RU' not in fired.summary and 'CF-' not in fired.summary}",
            ],
        )
        shot_path = shot(page, "TC-27-1-rule-summary")
        record(
            "TC-27",
            "2",
            "правило на подставных счётчиках: порог, минимум, приватность",
            fired.firing
            and fired.summary == "регион не определён у 90.0% из 10 запросов"
            and not few.firing
            and few.summary.startswith("мало запросов"),
            "срабатывает при превышении порога; при малом числе запросов — нет; без стран",
            {"fired": {"firing": fired.firing, "summary": fired.summary,
                       "details": fired.details},
             "few": {"firing": few.firing, "summary": few.summary}},
            [shot_path],
        )
        browser.close()

    report["steps"] = STEPS
    (QA / "live-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    failed = [s for s in STEPS if not s["ok"]]
    print(f"шагов: {len(STEPS)}, нарушений: {len(failed)}")
    for step in failed:
        print(f"  FAIL {step['case']}.{step['step']} {step['title']}: {step['actual']}")


if __name__ == "__main__":
    try:
        main()
    finally:
        for process in PROCESSES:
            process.terminate()
        for process in PROCESSES:
            try:
                process.wait(10)
            except subprocess.TimeoutExpired:
                process.kill()
