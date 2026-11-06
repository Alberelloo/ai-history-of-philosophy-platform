"""QA раунд 3 (навигация): снимки экранов и состояний боковой панели.

Стенд: PHILOGRAPH_RATE_BURST=2000 .venv/Scripts/python scripts/dev_stack.py --port 8099
Запуск: .venv/Scripts/python openspec/changes/redesign-navigation/qa/round-3/shoot.py [width ...]
Тема и язык переключаются кликами в настройках (группы «Тема» и «Язык интерфейса»).
"""

from __future__ import annotations

import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8099"
OUT = Path(__file__).resolve().parent
HEIGHT = 900
NOTICE = "2026-11"
READ_RE = re.compile(r"^(Читать|Read)$")


def get(path: str):
    return json.loads(urllib.request.urlopen(BASE + path).read())


def ids():
    src = get("/api/v1/current")["source_id"]
    toc = get(f"/api/v1/sources/{src}/toc")
    chapter = next(i["chapter_id"] for i in toc if i["title"] == "Глава 3. Ответ Канта")
    return src, chapter, None


def state_init(theme: str, lang: str | None, pinned: bool = False, notice: bool = True) -> str:
    st = {"version": 3, "theme": theme, "openSources": [], "sidebarPinned": pinned}
    if lang:
        st["lang"] = lang
    if notice:
        st["notice"] = NOTICE
    return (f"if(!localStorage.getItem('philograph:v3')) localStorage.setItem('philograph:v3', "
            f"JSON.stringify({json.dumps(st)}));")


def new_page(browser, width: int, init: str):
    ctx = browser.new_context(viewport={"width": width, "height": HEIGHT}, locale="ru-RU", reduced_motion="reduce")
    ctx.add_init_script(init)
    page = ctx.new_page()
    page.set_default_timeout(15000)
    return ctx, page


def shot(page, name: str, results: list, **info) -> None:
    path = OUT / f"{name}.png"
    try:
        page.wait_for_timeout(350)
        page.screenshot(path=str(path), full_page=True)
        results.append({"shot": path.name, "ok": True, **info})
    except Exception as exc:  # noqa: BLE001
        results.append({"shot": path.name, "ok": False, "error": str(exc)[:300], **info})


def set_theme_lang(page, theme: str, lang: str) -> None:
    """Переключение через интерфейс: раздел «Внешний вид» в настройках."""
    page.goto(BASE + "/settings#appearance")
    page.wait_for_selector("h1")
    if theme != "system":
        name = {"light": "Светлая", "dark": "Тёмная"}[theme]
        page.get_by_role("group", name="Тема").get_by_role("button", name=name).click()
    if lang == "en":
        page.get_by_role("group", name="Язык интерфейса").get_by_role("button", name="EN", exact=True).click()
        page.wait_for_function("() => document.documentElement.lang === 'en'")


def leave(page) -> None:
    page.mouse.move(700, 450)


def hover_panel(page) -> None:
    page.mouse.move(20, 300)
    page.wait_for_timeout(400)


def run_context(browser, theme: str, lang: str, width: int, results: list, extras: bool) -> None:
    src, chapter, _ = ids()
    tag = f"{theme}-{lang}-{width}"
    ctx, page = new_page(browser, width, state_init(theme, "ru"))
    try:
        set_theme_lang(page, theme, lang)
        # Библиотека без открытых книг, панель свёрнута.
        page.goto(BASE + "/")
        page.wait_for_selector(".source")
        leave(page)
        page.wait_for_timeout(300)
        shot(page, f"lib-collapsed-{tag}", results, screen="lib-collapsed", theme=theme, lang=lang, width=width)
        hover_panel(page)
        shot(page, f"lib-expanded-{tag}", results, screen="lib-expanded", theme=theme, lang=lang, width=width)
        leave(page)
        # Фильтры: вид и язык.
        page.locator(".pg-filter__button").nth(0).click()
        page.wait_for_selector(".pg-filter-menu")
        shot(page, f"lib-filter-kind-{tag}", results, screen="lib-filter-kind", theme=theme, lang=lang, width=width)
        page.keyboard.press("Escape")
        page.locator(".pg-filter__button").nth(1).click()
        page.wait_for_selector(".pg-filter-menu")
        shot(page, f"lib-filter-lang-{tag}", results, screen="lib-filter-lang", theme=theme, lang=lang, width=width)
        page.keyboard.press("Escape")
        # Открываем первую книгу: читать.
        page.goto(BASE + "/")
        page.wait_for_selector(".source")
        page.get_by_role("button", name=READ_RE).first.click()
        page.wait_for_selector(".chapter p, .toc")
        page.wait_for_timeout(300)
        page.goto(f"{BASE}/read/{src}/{chapter}")
        page.wait_for_selector(".chapter p")
        leave(page)
        shot(page, f"reader-collapsed-{tag}", results, screen="reader-collapsed", theme=theme, lang=lang, width=width)
        hover_panel(page)
        shot(page, f"reader-expanded-{tag}", results, screen="reader-expanded", theme=theme, lang=lang, width=width)
        if width >= 1280:
            page.locator(".sidebar__pin").click()
            leave(page)
            page.wait_for_timeout(500)
            shot(page, f"reader-pinned-{tag}", results, screen="reader-pinned", theme=theme, lang=lang, width=width)
            page.locator(".sidebar__pin").click()
            leave(page)
            page.wait_for_timeout(300)
        else:
            hover_panel(page)
            shot(page, f"reader-pin-disabled-{tag}", results, screen="reader-pin-disabled", theme=theme, lang=lang, width=width)
            leave(page)
        # Карточка и ассистент.
        page.locator("p.block", has_text="догматического сна").locator(".mention", has_text="Юм").click()
        page.wait_for_selector(".card-description")
        page.wait_for_timeout(500)
        shot(page, f"reader-card-{tag}", results, screen="reader-card", theme=theme, lang=lang, width=width)
        page.keyboard.press("Escape")
        page.goto(f"{BASE}/read/{src}/{chapter}")
        page.wait_for_selector(".chapter p")
        leave(page)
        page.locator(".toc__assistant").click()
        page.wait_for_selector("aside.assistant")
        leave(page)
        page.wait_for_timeout(400)
        shot(page, f"reader-assistant-{tag}", results, screen="reader-assistant", theme=theme, lang=lang, width=width)
        page.goto(f"{BASE}/read/{src}/{chapter}")
        page.wait_for_selector(".chapter p")
        # Вторая книга: в библиотеке второе «Читать».
        page.goto(BASE + "/")
        page.wait_for_selector(".source")
        page.get_by_role("button", name=READ_RE).nth(1).click()
        page.wait_for_selector(".chapter p, .toc")
        page.wait_for_timeout(300)
        leave(page)
        hover_panel(page)
        shot(page, f"books-two-{tag}", results, screen="books-two", theme=theme, lang=lang, width=width)
        leave(page)
        # Настройки: разделы.
        page.goto(BASE + "/settings#appearance")
        page.wait_for_selector("h1")
        page.wait_for_timeout(300)
        shot(page, f"settings-appearance-{tag}", results, screen="settings-appearance", theme=theme, lang=lang, width=width)
        page.goto(BASE + "/settings#books")
        page.wait_for_selector("h1")
        page.wait_for_timeout(400)
        shot(page, f"settings-books-{tag}", results, screen="settings-books", theme=theme, lang=lang, width=width)
        # Заглушки.
        for code in ["graph", "assistant"]:
            page.goto(f"{BASE}/soon/{code}")
            page.wait_for_selector("h1")
            leave(page)
            shot(page, f"soon-{code}-{tag}", results, screen=f"soon-{code}", theme=theme, lang=lang, width=width)
        if extras:
            pass
    finally:
        ctx.close()


def run_notice(browser, theme: str, lang_loc: str, width: int, results: list) -> None:
    tag = f"{theme}-{lang_loc[:2]}-{width}"
    ctx = browser.new_context(viewport={"width": width, "height": HEIGHT}, locale=lang_loc, reduced_motion="reduce")
    ctx.add_init_script(state_init(theme, None, notice=False))
    page = ctx.new_page()
    page.set_default_timeout(15000)
    try:
        page.goto(BASE + "/")
        page.wait_for_selector(".first-run")
        leave(page)
        shot(page, f"notice-{tag}", results, screen="notice", theme=theme, lang=lang_loc[:2], width=width)
    finally:
        ctx.close()


def main() -> None:
    widths = [int(w) for w in sys.argv[1:]] or [1440, 1024]
    results: list = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for width in widths:
            for theme in ["light", "dark"]:
                for lang in ["ru", "en"]:
                    run_context(browser, theme, lang, width, results, extras=False)
            for theme in ["light", "dark"]:
                run_notice(browser, theme, "ru-RU", width, results)
                run_notice(browser, theme, "en-US", width, results)
        if 1280 in widths or 1920 in widths:
            pass
        browser.close()
    (OUT / f"shots-{'-'.join(map(str, widths))}.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    bad = [r for r in results if not r["ok"]]
    print(f"снимков: {len(results)}, ошибок: {len(bad)}")
    for r in bad:
        print(r)


if __name__ == "__main__":
    main()
