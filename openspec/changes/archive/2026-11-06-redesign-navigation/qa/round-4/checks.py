"""QA раунд 4: D1 (мультивыбор фильтров), D2 (название книги в панели целиком), контраст автора.

Стенд: PHILOGRAPH_RATE_BURST=2000 .venv/Scripts/python scripts/dev_stack.py --port 8099
Запуск: .venv/Scripts/python openspec/changes/redesign-navigation/qa/round-4/checks.py
Результат: round-4/checks.json, снимки round-4/d1-*.png, round-4/d2-*.png.
"""

from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8099"
OUT = Path(__file__).resolve().parent
KEY = "philograph:v3"
NOTICE = "2026-11"
READ_RE = re.compile(r"^(Читать|Read)$")
RESULTS: dict = {}


def get(path: str):
    return json.loads(urllib.request.urlopen(BASE + path).read())


SRC = get("/api/v1/current")["source_id"]
TITLE_RU = "Теория познания: демонстрационный учебник"


def ctx_page(browser, width=1440, state=None, lang="ru-RU"):
    ctx = browser.new_context(viewport={"width": width, "height": 900}, locale=lang, reduced_motion="reduce")
    st = state or {"version": 3, "theme": "light", "openSources": [], "sidebarPinned": False, "notice": NOTICE}
    ctx.add_init_script(f"if(!localStorage.getItem('{KEY}')) localStorage.setItem('{KEY}', JSON.stringify({json.dumps(st)}));")
    page = ctx.new_page()
    page.set_default_timeout(15000)
    return ctx, page


def titles(page) -> list[str]:
    return page.locator(".source h2, .source .source__title, .source [class*=title]").all_inner_texts()


def visible_sources(page) -> list[str]:
    page.wait_for_timeout(350)
    return [t.strip() for t in page.locator("li.source h2").all_inner_texts()]


def open_filter(page, index):
    page.locator(".pg-filter__button").nth(index).click()
    page.wait_for_selector(".pg-filter-menu")
    page.wait_for_timeout(150)


def tick(page, label):
    page.locator(".pg-filter-menu label", has_text=label).click()
    page.wait_for_timeout(250)


def clear_all(page):
    btn = page.get_by_role("button", name="Снять все")
    if btn.is_enabled():
        btn.click()
        page.wait_for_timeout(200)


def close_menu(page):
    page.keyboard.press("Escape")
    page.wait_for_timeout(200)


def count_label(page, index):
    return page.locator(".pg-filter__count").nth(index).inner_text() if page.locator(".pg-filter__count").count() > index else ""


def main() -> None:
    with sync_playwright() as p:
        b = p.chromium.launch()

        # D1: фильтры видов и языков.
        ctx, page = ctx_page(b)
        page.goto(BASE + "/")
        page.wait_for_selector(".source")
        page.mouse.move(700, 450)
        all_sources = visible_sources(page)
        out: dict = {"all": all_sources}

        open_filter(page, 0)
        page.get_by_role("button", name="Выбрать все").click()
        page.wait_for_timeout(300)
        out["kind_select_all"] = {"count_badge": count_label(page, 0), "sources": visible_sources(page)}
        page.screenshot(path=str(OUT / "d1-kind-select-all-light-ru-1440.png"))
        clear_all(page)
        page.wait_for_timeout(250)
        out["kind_clear_all"] = {"count_badge": count_label(page, 0), "sources": visible_sources(page)}
        tick(page, "Учебник")
        tick(page, "Первоисточник")
        out["kind_textbook_primary"] = {"count_badge": count_label(page, 0), "sources": visible_sources(page)}
        page.screenshot(path=str(OUT / "d1-kind-two-light-ru-1440.png"))
        tick(page, "Первоисточник")
        out["kind_textbook_only"] = {"count_badge": count_label(page, 0), "sources": visible_sources(page)}
        close_menu(page)

        # Язык: русский и английский вместе, затем по одному (вид снят, чтобы проверять язык отдельно).
        open_filter(page, 0)
        clear_all(page)
        close_menu(page)
        open_filter(page, 1)
        page.get_by_role("button", name="Выбрать все").click()
        page.wait_for_timeout(300)
        out["lang_select_all"] = {"count_badge": count_label(page, 1), "sources": visible_sources(page)}
        clear_all(page)
        tick(page, "английский")
        out["lang_en_only"] = {"count_badge": count_label(page, 1), "sources": visible_sources(page)}
        tick(page, "английский")
        tick(page, "русский")
        out["lang_ru_and_en"] = {"count_badge": count_label(page, 1), "sources": visible_sources(page)}
        close_menu(page)

        # Вид и язык вместе: учебник на английском — пусто, учебник на русском — один.
        open_filter(page, 0)
        clear_all(page)
        tick(page, "Учебник")
        close_menu(page)
        out["kind_textbook_and_lang_ru"] = {"sources": visible_sources(page)}
        open_filter(page, 1)
        clear_all(page)
        tick(page, "английский")
        close_menu(page)
        out["kind_textbook_and_lang_en"] = {"sources": visible_sources(page), "empty_text": page.locator("main").inner_text()[:160]}
        RESULTS["D1"] = out
        ctx.close()

        # D2: название книги целиком в раскрытой и закреплённой панели.
        st_open = {"version": 3, "theme": "light", "openSources": [{"id": SRC, "openedAt": 2}], "sidebarPinned": False, "notice": NOTICE, "currentSource": SRC}
        for width, mode in [(1024, "hover"), (1440, "pinned"), (1920, "pinned")]:
            for theme in ["light", "dark"]:
                st = dict(st_open, theme=theme, sidebarPinned=(mode == "pinned"))
                ctx, page = ctx_page(b, width=width, state=st)
                page.goto(f"{BASE}/read/{SRC}/" if False else BASE + "/")
                page.wait_for_selector(".source")
                page.mouse.move(700, 450)
                page.wait_for_timeout(300)
                if mode == "hover":
                    page.mouse.move(20, 300)
                    page.wait_for_timeout(400)
                page.wait_for_timeout(300)
                info = page.evaluate("""() => {
                  const t = document.querySelector('.sidebar__book-title');
                  if (!t) return null;
                  const a = document.querySelector('.sidebar__book.is-current .sidebar__book-author');
                  const cur = document.querySelector('.sidebar__book.is-current a') || document.querySelector('.sidebar__book.is-current');
                  const pick = (el) => el ? getComputedStyle(el).color : null;
                  const bg = cur ? getComputedStyle(cur).backgroundColor : null;
                  const r = t.getBoundingClientRect();
                  return { text: t.textContent, lineH: parseFloat(getComputedStyle(t).lineHeight) || null,
                           clientH: t.clientHeight, scrollH: t.scrollHeight, rectH: Math.round(r.height),
                           clipped: t.scrollHeight > t.clientHeight + 1, ellipsis: getComputedStyle(t).textOverflow,
                           clamp: getComputedStyle(t).webkitLineClamp, author: a ? a.textContent : null,
                           authorColor: pick(a), currentBg: bg, state: document.querySelector('.sidebar').dataset.state,
                           overflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth };
                }""")
                tag = f"{theme}-{width}"
                RESULTS.setdefault("D2", {})[tag] = info
                if info and info.get("authorColor") and info.get("currentBg"):
                    def rgb(s):
                        return tuple(float(x) for x in re.findall(r"[\d.]+", s)[:3])
                    def lum(c):
                        c = [x / 255 for x in c]
                        c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
                        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
                    la, lb = lum(rgb(info["authorColor"])), lum(rgb(info["currentBg"]))
                    info["author_contrast"] = round((max(la, lb) + 0.05) / (min(la, lb) + 0.05), 2)
                page.screenshot(path=str(OUT / f"d2-{mode}-{tag}.png"), clip={"x": 0, "y": 0, "width": 290, "height": 320})
                ctx.close()

        b.close()
    (OUT / "checks.json").write_text(json.dumps(RESULTS, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(RESULTS, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
