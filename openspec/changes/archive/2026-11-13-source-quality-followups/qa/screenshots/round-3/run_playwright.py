"""Раунд 3, живые проверки через Playwright: стенд, оглавление, главы, карточки.

Скрипт ничего не меняет в продукте: только открывает страницы, кликает и снимает скриншоты.
Результат — JSON с фактами (тексты, селекторы, ошибки консоли и сети) рядом со скриншотами.
"""

from __future__ import annotations

import json
import pathlib
import sys

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8080"
OUT = pathlib.Path("openspec/changes/source-quality-followups/qa/screenshots/round-3")
OUT.mkdir(parents=True, exist_ok=True)

facts: dict[str, object] = {"base": BASE, "pages": []}


def record(name: str, **data) -> None:
    data["shot"] = str(OUT / name)
    facts["pages"].append(data)  # type: ignore[union-attr]
    print(json.dumps({"page": name, **data}, ensure_ascii=False))


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="ru-RU")
        page = context.new_page()
        console: list[str] = []
        failures: list[str] = []
        page.on("console", lambda m: console.append(f"{m.type}: {m.text}") if m.type in {"error", "warning"} else None)
        page.on("pageerror", lambda e: failures.append(f"pageerror: {e}"))
        page.on("requestfailed", lambda r: failures.append(f"requestfailed: {r.url} {r.failure}"))

        # --- SITE-01: главная
        page.goto(BASE + "/", wait_until="networkidle")
        page.screenshot(path=str(OUT / "SITE-01-home.png"), full_page=True)
        record("SITE-01-home", title=page.title(), h1=[t.strip() for t in page.locator("h1").all_inner_texts()][:3],
               console=list(console), failures=list(failures))

        # --- TOC-01: источники и оглавление
        page.goto(BASE + "/", wait_until="networkidle")
        sources = page.evaluate(
            "async () => (await (await fetch('/api/v1/sources')).json())"
        )
        facts["sources"] = sources
        default_id = sources["default_source_id"]
        toc = page.evaluate(
            "async (sid) => (await (await fetch(`/api/v1/sources/${sid}/toc`)).json())", default_id
        )
        facts["toc"] = toc

        def count(items):
            return sum(1 + count(i.get("children") or []) for i in items)

        record(
            "TOC-01-sources",
            default_source_id=default_id,
            source_titles=[s["title"] for s in sources["sources"]],
            toc_items=count(toc),
            toc_root_titles=[i.get("title") for i in toc],
        )

        # --- READ-01: открыть первый раздел через интерфейс
        page.goto(f"{BASE}/read/{default_id}", wait_until="networkidle")
        page.wait_for_timeout(1500)
        page.screenshot(path=str(OUT / "READ-01-chapter.png"), full_page=False)

        def chapters_of(items):
            out = []
            for i in items:
                if i.get("chapter_id"):
                    out.append({"id": i["chapter_id"], "title": i.get("title")})
                out.extend(chapters_of(i.get("children") or []))
            return out

        chapters = chapters_of(toc)
        facts["chapters"] = chapters
        record(
            "READ-01-chapter",
            url=page.url,
            section_headings=[t.strip() for t in page.locator("h1,h2,h3").all_inner_texts()][:12],
            paragraphs=page.locator("p").count(),
            toc_visible=page.locator("nav, [class*=toc], [class*=Toc]").count(),
            console=list(console), failures=list(failures),
        )

        # --- READ-02/03: остальные главы, модель «заголовки по шрифту создают разделы»
        for n, ch in enumerate(chapters[:3], start=1):
            page.goto(f"{BASE}/read/{default_id}/{ch['id']}", wait_until="networkidle")
            page.wait_for_timeout(800)
            name = f"READ-0{n + 1}-chapter-{n}"
            page.screenshot(path=str(OUT / f"{name}.png"), full_page=False)
            record(
                name,
                chapter=ch,
                headings=[t.strip() for t in page.locator("h1,h2,h3").all_inner_texts()][:8],
                paragraphs=page.locator("p").count(),
                console=list(console), failures=list(failures),
            )

        # --- CARDS-01: оглавление в читалке + карточка понятия
        page.goto(f"{BASE}/read/{default_id}/{chapters[0]['id']}", wait_until="networkidle")
        page.wait_for_timeout(1200)
        toggle = page.locator("button, a, summary").filter(has_text="/Оглавлен|Содержан|TOC/")
        used_toggle = toggle.count() > 0
        if used_toggle:
            try:
                toggle.first.click(timeout=3000)
                page.wait_for_timeout(600)
            except Exception as exc:  # noqa: BLE001 — фиксируем факт, не падаем
                failures.append(f"toc toggle click: {exc}")
        page.screenshot(path=str(OUT / "CARDS-01-toc.png"), full_page=False)
        record(
            "CARDS-01-toc",
            toggle_found=used_toggle,
            toc_entry_texts=[t.strip() for t in page.locator("nav a, [role=navigation] a").all_inner_texts()][:15],
            console=list(console), failures=list(failures),
        )

        # --- CARDS-02/03: клик по упоминанию → карточка
        mentions = page.locator("[data-entity-id], .mention, button.mention-ref, [class*=mention]")
        record("CARDS-02-mentions", mention_count=mentions.count())
        if mentions.count():
            try:
                mentions.first.click(timeout=3000)
                page.wait_for_timeout(1500)
            except Exception as exc:  # noqa: BLE001
                failures.append(f"mention click: {exc}")
            page.screenshot(path=str(OUT / "CARDS-03-mention-card.png"), full_page=False)
            record(
                "CARDS-03-mention-card",
                dialog=page.locator("[role=dialog], .card, [class*=Card]").count(),
                dialog_text=[t.strip()[:160] for t in page.locator("[role=dialog], .card").all_inner_texts()][:3],
                console=list(console), failures=list(failures),
            )
        else:
            record("CARDS-03-mention-card", note="упоминаний на странице не найдено")

        # --- SEARCH-01: страница поиска, если есть
        page.goto(BASE + "/", wait_until="networkidle")
        search = page.locator("input[type=search], input[placeholder*='оиск'], input[name=q]")
        record("SEARCH-01-home-search", search_inputs=search.count())
        if search.count():
            try:
                search.first.fill("опыт")
                search.first.press("Enter")
                page.wait_for_timeout(2000)
            except Exception as exc:  # noqa: BLE001
                failures.append(f"search: {exc}")
            page.screenshot(path=str(OUT / "SEARCH-02-results.png"), full_page=True)
            record(
                "SEARCH-02-results",
                url=page.url,
                result_links=page.locator("a[href*='/read/']").count(),
                console=list(console), failures=list(failures),
            )

        facts["console_all"] = console
        facts["failures_all"] = failures
        browser.close()
    (OUT / "R3-playwright-facts.json").write_text(
        json.dumps(facts, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
