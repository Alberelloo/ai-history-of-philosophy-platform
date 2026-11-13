"""Стенд + браузерные проверки кейсов ru-only-sources (группы 1-2).

Стенд — как в tests/web/conftest.py: настоящий шлюз раздаёт собранный клиент и проксирует
запросы библиотеке (httpx.ASGITransport), библиотека в SQLite с тестовыми источниками.
Дополнительно зарегистрирован источник с регионами показа [RU].

Скриншоты — в openspec/changes/ru-only-sources/qa/screenshots/round-1/.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from pathlib import Path

import httpx
import uvicorn
from playwright.sync_api import sync_playwright

from philograph.gateway.app import build_app as gateway_app
from philograph.library import schema
from philograph.library.app import build_app
from philograph.library.processing import Pipeline
from philograph.library.reading import Reader, Reading
from philograph.library.registry import License, Registry
from philograph.operator.access import migrations as operator_migrations
from philograph.platform.db import make_engine
from philograph.platform.files import FileStore
from tests.web.conftest import PRIMARY, REFERENCE, TEXTBOOK

def _repo_root(start: Path) -> Path:
    """Корень репозитория: вверх до каталога с pyproject.toml."""
    for candidate in [start, *start.parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    raise RuntimeError("не найден корень репозитория (pyproject.toml)")


ROOT = _repo_root(Path(__file__).resolve().parent)
DIST = ROOT / "web" / "dist"
QA = ROOT / "openspec" / "changes" / "ru-only-sources" / "qa"
SHOTS = QA / "screenshots" / "round-2"
WORK = Path(__file__).resolve().parent / "stand"

CHECKS: list[dict] = []
CONSOLE: list[dict] = []


def report(case_id: str, step: str, ok: bool, expected: str, actual: str, evidence: list[str]) -> None:
    CHECKS.append(
        {
            "case": case_id,
            "step": step,
            "ok": ok,
            "expected": expected,
            "actual": actual,
            "evidence": evidence,
        }
    )
    print(("PASS " if ok else "FAIL ") + case_id + " / " + step + " :: " + actual[:300])


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Stand:
    def __init__(self) -> None:
        WORK.mkdir(parents=True, exist_ok=True)
        for stale in WORK.glob("site*.db*"):
            stale.unlink()
        db = WORK / "site.db"
        self.engine = make_engine(
            f"sqlite:///{db.as_posix()}", [schema.SCHEMA, operator_migrations.schema]
        )
        schema.migrations.upgrade(self.engine)
        operator_migrations.upgrade(self.engine)
        self.registry = Registry(self.engine)
        self.registry.add_license_kind(
            "public-domain",
            "Общественное достояние",
            "https://example.org/public-domain",
            {"display": True, "external_processing": True, "quoting": True},
        )
        self.registry.add_license_kind(
            "public-domain-ru",
            "Общественное достояние по праву РФ",
            None,
            {"display": True, "external_processing": True, "quoting": True},
            regions=["RU"],
        )
        files = {"textbook.epub": TEXTBOOK, "primary.txt": PRIMARY, "reference.txt": REFERENCE}
        self.pipeline = Pipeline(
            self.registry, FileStore(WORK / "files"), lambda spec: files[spec["path"]]
        )
        lic = License("public-domain", "public_domain", author_death_years=[1900])
        self.ids: dict[str, str] = {}
        self.ids["textbook"] = self.registry.register(
            "operator",
            title="История теории познания",
            authors=["В. Ф. Асмус"],
            year=1950,
            language="ru",
            kind="textbook",
            license=lic,
            scope="public",
            files=[{"name": "t", "path": "textbook.epub"}],
        )
        self.ids["primary"] = self.registry.register(
            "operator",
            title="Critique of Pure Reason",
            authors=["I. Kant"],
            year=1781,
            language="en",
            kind="primary",
            license=lic,
            scope="public",
            files=[{"name": "p", "path": "primary.txt"}],
        )
        self.ids["reference"] = self.registry.register(
            "operator",
            title="Философский словарь",
            authors=["Коллектив авторов"],
            language="ru",
            kind="reference",
            license=lic,
            scope="public",
            files=[{"name": "r", "path": "reference.txt"}],
        )
        for source_id in list(self.ids.values()):
            version = self.pipeline.start("operator", source_id)
            self.registry.publish("operator", version)
        self.ids["limited"] = self.registry.register(
            "operator",
            title="Русский учебник",
            authors=["П. Д. Юркевич"],
            year=1865,
            language="ru",
            kind="textbook",
            license=License("public-domain-ru", "public_domain", author_death_years=[1900]),
            scope="public",
            files=[{"name": "r2", "path": "reference.txt"}],
        )
        version = self.pipeline.start("operator", self.ids["limited"])
        self.registry.publish("operator", version)
        self.reading = Reading(self.registry, self.engine)
        self.reading.set_default("operator", self.ids["textbook"])
        self.version_id = self.registry.get(self.ids["limited"]).published_version or ""
        port = free_port()
        gateway = gateway_app(
            {"library": "http://library", "assistant": "http://assistant"},
            DIST,
            transport=httpx.ASGITransport(app=build_app(self.reading)),
        )
        self.server = uvicorn.Server(
            uvicorn.Config(gateway, host="127.0.0.1", port=port, log_level="warning")
        )
        threading.Thread(target=self.server.run, daemon=True).start()
        while not self.server.started:
            time.sleep(0.05)
        self.url = f"http://127.0.0.1:{port}"

    def chapter_of_limited(self) -> str:
        toc = self.reading.toc(self.ids["limited"], Reader(region="RU"))
        return toc[0]["id"]

    def paragraph_of_limited(self) -> str:
        from philograph.library.reading import Internal

        payload = Internal(self.registry, self.reading).version_paragraphs(self.version_id)
        return payload["paragraphs"][0]["id"]


NOTICE_ACCEPTED = """
if (!localStorage.getItem("philograph:v4")) {
  localStorage.setItem("philograph:v4", JSON.stringify({version: 4, notice: "2026-11"}));
}
"""


def new_page(browser, storage: dict | None = None):
    context = browser.new_context(locale="ru-RU", viewport={"width": 1440, "height": 900})
    context.add_init_script(NOTICE_ACCEPTED)
    if storage is not None:
        payload = json.dumps(storage, ensure_ascii=False)
        context.add_init_script(
            "localStorage.setItem('philograph:v4', %s);" % json.dumps(payload)
        )
    page = context.new_page()
    page.set_default_timeout(10000)
    page.on(
        "console",
        lambda msg: CONSOLE.append({"type": msg.type, "text": msg.text})
        if msg.type in ("error", "warning")
        else None,
    )
    page.on("pageerror", lambda err: CONSOLE.append({"type": "pageerror", "text": str(err)}))
    page.on(
        "response",
        lambda r: CONSOLE.append({"type": "http", "text": f"{r.status} {r.url}"})
        if r.status >= 400
        else None,
    )
    return context, page


def shot(page, name: str) -> str:
    SHOTS.mkdir(parents=True, exist_ok=True)
    path = SHOTS / f"{name}.png"
    page.screenshot(path=str(path), full_page=True)
    return str(path.relative_to(ROOT)).replace("\\", "/")


def main() -> None:
    stand = Stand()
    print("URL:", stand.url)
    text_of_limited = "Познание — процесс постижения мира."
    summary: dict = {}

    with sync_playwright() as pw:
        browser = pw.chromium.launch()

        # --- TC-17 / UC-1 / EC-14: список библиотеки, строка закрытого источника ---
        context, page = new_page(browser)
        responses: list[dict] = []

        def on_response(resp):
            if "/api/v1/sources" in resp.url:
                try:
                    responses.append({"url": resp.url, "status": resp.status, "json": resp.json()})
                except Exception as exc:  # noqa: BLE001
                    responses.append({"url": resp.url, "status": resp.status, "error": str(exc)})

        page.on("response", on_response)
        page.goto(stand.url + "/")
        page.locator(".sources .source").first.wait_for()
        shot(page, "TC-17-1-library-list")

        row = page.locator("li.source--restricted")
        count = row.count()
        payload = responses[-1]["json"] if responses else {}
        api_restricted = [
            s for s in payload.get("sources", []) if s.get("id") == stand.ids["limited"]
        ]
        report(
            "TC-17",
            "строка закрытого источника в списке",
            count == 1 and bool(api_restricted),
            "одна строка li.source--restricted; в /api/v1/sources строка с restricted:true",
            f"строк в DOM: {count}; строка в API: {api_restricted}",
            [shot(page, "TC-17-1-library-list")],
        )
        if count:
            text = row.inner_text()
            badge = row.locator(".badge")
            dd = row.locator("dd").all_inner_texts()
            report(
                "TC-17",
                "пометка, авторы, без года и лицензии",
                badge.count() == 1
                and badge.inner_text().strip() == "Доступен в РФ"
                and any("Юркевич" in d for d in dd)
                and row.locator("dt", has_text="Год").count() == 0
                and row.locator("dt", has_text="Лицензия").count() == 0,
                "пометка «Доступен в РФ», автор в dd, нет dt «Год» и «Лицензия»",
                f"текст строки: {text!r}; бейдж: {badge.all_inner_texts()}; dd: {dd}",
                [shot(page, "TC-17-2-restricted-row-fields")],
            )
            report(
                "TC-17",
                "нет кнопки «Читать» и переходов",
                row.locator("button", has_text="Читать").count() == 0
                and row.locator("button, a").count() == 0,
                "в строке закрытого источника нет кнопок и ссылок",
                f"button/a в строке: {row.locator('button, a').count()}",
                [shot(page, "TC-17-3-no-read-button")],
            )
            report(
                "EC-14",
                "пометка доступна, фокус в строку не уходит",
                badge.get_attribute("title") is not None,
                "у пометки есть title (описание для чтения с экрана)",
                f"title={badge.get_attribute('title')!r}",
                [shot(page, "EC-14-restricted-badge-title")],
            )
            # --- EC-14: обход по Tab не заходит в строку закрытого источника ---
            page.keyboard.press("Tab")
            focused: list[str] = []
            for _ in range(45):
                page.keyboard.press("Tab")
                info = page.evaluate(
                    """() => {
                        const el = document.activeElement;
                        if (!el || el === document.body) return null;
                        const li = el.closest("li.source--restricted");
                        return (li ? "restricted:" : "") + el.tagName + ":" + (el.innerText || "").trim().slice(0, 40);
                    }"""
                )
                if info:
                    focused.append(info)
            report(
                "EC-14",
                "Tab не попадает в строку закрытого источника, «Читать» достижима",
                not any(f.startswith("restricted:") for f in focused)
                and any("Читать" in f for f in focused),
                "ни один Tab не ставит фокус в закрытую строку; кнопки «Читать» достижимы",
                f"последовательность фокуса: {focused[:12]}…; всего {len(focused)}",
                [shot(page, "EC-14-tab-order")],
            )
            # клик по строке: перехода нет
            before = page.url
            row.locator("h2").click()
            page.wait_for_timeout(400)
            report(
                "UC-1",
                "по строке нельзя открыть источник",
                page.url == before,
                "адрес не меняется после клика по строке закрытого источника",
                f"до: {before}; после: {page.url}",
                [shot(page, "UC-1-click-restricted-stays")],
            )
        open_reads = page.locator("li.source button", has_text="Читать").count()
        report(
            "UC-1",
            "открытые источники по-прежнему открываются",
            open_reads == 3,
            "три кнопки «Читать» у трёх открытых источников",
            f"кнопок «Читать»: {open_reads}",
            [shot(page, "UC-1-open-sources")],
        )
        report(
            "UC-3",
            "запрос без заголовка региона",
            responses[-1]["status"] == 200
            and bool(api_restricted)
            and payload.get("default_source_id") == stand.ids["textbook"],
            "регион неизвестен: ограниченный закрыт, по умолчанию — открытый учебник",
            f"status={responses[-1]['status']}, default={payload.get('default_source_id')}, "
            f"ограниченный={bool(api_restricted)}",
            [],
        )
        context.close()

        # --- UC-2 / TC-9: открытый источник читается ---
        context, page = new_page(browser)
        page.goto(stand.url + "/")
        page.locator(".sources .source").first.wait_for()
        page.locator("li.source", has_text="История теории познания").locator(
            "button", has_text="Читать"
        ).click()
        page.locator(".chapter").wait_for()
        body = page.locator("#content").inner_text()
        report(
            "UC-2",
            "открытый учебник читается",
            "Всякое знание начинается с опыта" in body,
            "глава открытого учебника показывает текст",
            f"адрес: {page.url}; первые строки: {body[:120]!r}",
            [shot(page, "UC-2-open-source-readable")],
        )
        context.close()

        # --- UC-1(гл.) / TC-12: прямой адрес главы закрытого источника ---
        context, page = new_page(browser)
        chapter = stand.chapter_of_limited()
        chapter_resp: list[dict] = []

        def on_chapter(resp):
            if "/chapters/" in resp.url:
                try:
                    chapter_resp.append({"url": resp.url, "status": resp.status, "json": resp.json()})
                except Exception as exc:  # noqa: BLE001
                    chapter_resp.append({"url": resp.url, "status": resp.status, "error": str(exc)})

        page.on("response", on_chapter)
        page.goto(f"{stand.url}/read/{stand.ids['limited']}/{chapter}")
        page.locator(".reader-problem").wait_for()
        problem = page.locator(".reader-problem").inner_text()
        report(
            "TC-12",
            "прямой адрес главы закрытого источника",
            "Источник недоступен" in problem and text_of_limited not in problem,
            "«Источник недоступен», текст главы не показан",
            f"сообщение: {problem!r}; ответы: {chapter_resp}",
            [shot(page, "TC-12-chapter-unavailable")],
        )
        report(
            "TC-12",
            "HTTP-ответ на главу — 404 source_unavailable",
            bool(chapter_resp)
            and chapter_resp[-1]["status"] == 404
            and chapter_resp[-1].get("json", {}).get("kind") == "source_unavailable",
            "404, kind=source_unavailable",
            f"ответы: {chapter_resp}",
            [],
        )
        context.close()

        # --- UC-4 / TC-12: ссылка на абзац закрытого источника ---
        context, page = new_page(browser)
        paragraph = stand.paragraph_of_limited()
        para_resp: list[dict] = []

        def on_paragraph(resp):
            if "/api/v1/paragraphs/" in resp.url:
                try:
                    para_resp.append({"url": resp.url, "status": resp.status, "json": resp.json()})
                except Exception as exc:  # noqa: BLE001
                    para_resp.append({"url": resp.url, "status": resp.status, "error": str(exc)})

        page.on("response", on_paragraph)
        page.goto(f"{stand.url}/p/{paragraph}")
        page.locator(".reader-problem").wait_for()
        problem = page.locator(".reader-problem").inner_text()
        body = page.locator("#content").inner_text()
        report(
            "UC-4",
            "ссылка на абзац: причина «регион»",
            "Источник доступен только в России" in problem and text_of_limited not in body,
            "«Источник доступен только в России.», текст абзаца не раскрыт",
            f"сообщение: {problem!r}; текст страницы: {body[:200]!r}",
            [shot(page, "UC-4-paragraph-region")],
        )
        body_json = para_resp[-1]["json"] if para_resp else {}
        report(
            "UC-4",
            "ответ API: source_unavailable + reason region + название/авторы",
            body_json.get("status") == "source_unavailable"
            and body_json.get("reason") == "region"
            and body_json.get("source", {}).get("title") == "Русский учебник"
            and body_json.get("source", {}).get("authors") == ["П. Д. Юркевич"]
            and "text" not in body_json
            and "chapter_id" not in body_json
            and "section_id" not in body_json,
            "status=source_unavailable, reason=region, название и авторы, без text/chapter_id/section_id",
            f"ответ: {body_json}",
            [],
        )
        context.close()

        # --- UC-5 / TC-11: запомненный закрытый источник ---
        remembered = {
            "version": 4,
            "currentSource": stand.ids["limited"],
            "openSources": [{"id": stand.ids["limited"], "openedAt": 1}],
            "positions": {stand.ids["limited"]: {"chapterId": chapter}},
        }
        context, page = new_page(browser, storage=remembered)
        current_resp: list[dict] = []

        def on_current(resp):
            if "/api/v1/current" in resp.url:
                try:
                    current_resp.append({"url": resp.url, "status": resp.status, "json": resp.json()})
                except Exception as exc:  # noqa: BLE001
                    current_resp.append({"url": resp.url, "status": resp.status, "error": str(exc)})

        page.on("response", on_current)
        page.goto(stand.url + "/read")
        page.wait_for_function(
            "document.body.innerText.includes('Прежний источник недоступен')",
            timeout=10000,
        )
        noticed = page.locator(".pg-notice.notice", has_text="Прежний источник недоступен")
        report(
            "UC-5",
            "уведомление previous_unavailable и переход к учебнику по умолчанию",
            noticed.count() == 1 and f"/read/{stand.ids['textbook']}" in page.url,
            "пометка «Прежний источник недоступен…», адрес — учебник по умолчанию",
            f"адрес: {page.url}; ответ /current: {current_resp[-1] if current_resp else None}",
            [shot(page, "UC-5-remembered-closed")],
        )
        context.close()

        # --- TC-8 / EC-13: фильтр по запросу и локаль пометки ---
        context, page = new_page(browser)
        page.goto(stand.url + "/")
        page.locator(".sources .source").first.wait_for()
        search = page.locator('input[type="search"]')
        search.fill("Юркевич")
        page.wait_for_timeout(600)
        report(
            "TC-8",
            "поиск по названию действует на закрытую строку",
            page.locator("li.source--restricted").count() == 1
            and page.locator(".sources .source").count() == 1,
            "по запросу «Юркевич» остаётся одна строка — закрытый источник",
            f"строк всего: {page.locator('.sources .source').count()}",
            [shot(page, "TC-8-search-restricted")],
        )
        context.close()

        context, page = new_page(
            browser, storage={"version": 4, "notice": "2026-11", "lang": "en"}
        )
        page.goto(stand.url + "/")
        page.locator("li.source--restricted").wait_for()
        badge_text = page.locator("li.source--restricted .badge").inner_text().strip()
        title_text = page.locator("li.source--restricted h2").inner_text()
        report(
            "EC-13",
            "пометка локализуется, данные источника — нет",
            badge_text == "Available in Russia only" and title_text == "Русский учебник",
            "пометка на языке интерфейса, название источника не переводится",
            f"бейдж: {badge_text!r}; название: {title_text!r}",
            [shot(page, "EC-13-restricted-en")],
        )
        context.close()

        browser.close()

    findings = [c for c in CHECKS if not c["ok"]]
    summary = {
        "url": stand.url,
        "ids": stand.ids,
        "version_id": stand.version_id,
        "checks": CHECKS,
        "failed": findings,
        "console": CONSOLE,
    }
    out = Path(__file__).resolve().parent / "browser-report.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\nИтог: проверок", len(CHECKS), ", провалено", len(findings))
    for item in findings:
        print("FAILED:", item["case"], item["step"], "|", item["actual"][:400])
    print("Консоль (error/warning):", len(CONSOLE))
    for item in CONSOLE[:20]:
        print(" ", item["type"], item["text"][:300])


if __name__ == "__main__":
    main()
