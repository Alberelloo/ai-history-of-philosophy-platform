"""QA раунд 5: N1 (Esc после «Выбрать все» / «Снять все») и кнопка «Сбросить поиск и фильтры».

Стенд: PHILOGRAPH_RATE_BURST=2000 .venv/Scripts/python scripts/dev_stack.py --port 8099
Запуск: .venv/Scripts/python openspec/changes/redesign-navigation/qa/round-5/checks.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8099"
OUT = Path(__file__).resolve().parent
STATE = '{"version":3,"theme":"light","openSources":[],"sidebarPinned":false,"notice":"2026-11"}'
RESULTS: dict = {}


def new(b, theme="light", lang="ru-RU"):
    ctx = b.new_context(viewport={"width": 1440, "height": 900}, locale=lang, reduced_motion="reduce")
    st = STATE.replace('"light"', f'"{theme}"')
    ctx.add_init_script(f"if(!localStorage.getItem('philograph:v3')) localStorage.setItem('philograph:v3', '{st}');")
    pg = ctx.new_page()
    pg.set_default_timeout(5000)
    pg.goto(BASE + "/")
    pg.wait_for_selector(".source")
    pg.mouse.move(700, 450)
    pg.wait_for_timeout(300)
    return ctx, pg


def state(pg):
    return pg.evaluate("""() => { const e = document.activeElement; return {tag: e.tagName, cls: String(e.className).slice(0, 50),
        text: (e.textContent || '').trim().slice(0, 30), disabled: e.disabled, ariaDisabled: e.getAttribute('aria-disabled')}; }""")


def sources(pg):
    pg.wait_for_timeout(300)
    return [t.strip() for t in pg.locator("li.source h2").all_inner_texts()]


def menu_open(pg):
    return pg.locator(".pg-filter-menu").count() == 1


def run_filter(b, index, label):
    out = {}
    ctx, pg = new(b)
    btn = pg.locator(".pg-filter__button").nth(index)
    btn.click()
    pg.wait_for_selector(".pg-filter-menu")
    pg.wait_for_timeout(150)
    for action in ["Выбрать все", "Снять все"]:
        pg.get_by_role("button", name=action).click()
        pg.wait_for_timeout(250)
        out[action] = {
            "focus_after_click": state(pg),
            "select_all_aria_disabled": pg.get_by_role("button", name="Выбрать все").get_attribute("aria-disabled"),
            "clear_all_aria_disabled": pg.get_by_role("button", name="Снять все").get_attribute("aria-disabled"),
            "sources": sources(pg),
        }
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(250)
        out[action]["menu_open_after_esc"] = menu_open(pg)
        out[action]["focus_after_esc"] = state(pg)
        # Для следующего действия открываем окно снова, если Esc закрыл его.
        if not menu_open(pg):
            btn.click()
            pg.wait_for_selector(".pg-filter-menu")
            pg.wait_for_timeout(150)
    pg.locator(".pg-filter__button").nth(index).click() if menu_open(pg) is False else None
    pg.wait_for_timeout(150)
    if menu_open(pg):
        pg.get_by_role("button", name="Выбрать все").click()
        pg.wait_for_timeout(250)
        pg.screenshot(path=str(OUT / f"n1-{label}-after-select-all-light-ru-1440.png"), clip={"x": 500, "y": 160, "width": 340, "height": 260})
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(250)
        pg.screenshot(path=str(OUT / f"n1-{label}-after-esc-light-ru-1440.png"), clip={"x": 500, "y": 160, "width": 340, "height": 260})
    ctx.close()
    return out


def reset_check(b):
    ctx, pg = new(b)
    # Задаём запрос и фильтр, потом сбрасываем кнопкой.
    pg.locator(".pg-input").first.fill("кант")
    pg.wait_for_timeout(300)
    pg.locator(".pg-filter__button").nth(0).click()
    pg.wait_for_selector(".pg-filter-menu")
    pg.locator(".pg-filter-menu label", has_text="Учебник").click()
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(250)
    reset = pg.get_by_role("button", name="Сбросить поиск и фильтры").first
    before = {"enabled": reset.is_enabled(), "aria_disabled": reset.get_attribute("aria-disabled")}
    reset.click()
    pg.wait_for_timeout(300)
    after = {"focus": state(pg), "search": pg.locator(".pg-input").first.input_value(),
             "sources": sources(pg), "url": pg.url,
             "reset_aria_disabled": pg.get_by_role("button", name="Сбросить поиск и фильтры").first.get_attribute("aria-disabled")}
    # Когда сбрасывать нечего, кнопка неактивна, а фокус не уходит со своей позиции.
    reset_btn = pg.get_by_role("button", name="Сбросить поиск и фильтры").first
    reset_btn.focus()
    pg.keyboard.press("Enter")
    pg.wait_for_timeout(200)
    after["enter_when_empty_focus"] = state(pg)
    after["url_after_enter"] = pg.url
    pg.screenshot(path=str(OUT / "reset-after-click-light-ru-1440.png"))
    ctx.close()
    return {"before": before, "after": after}


def main() -> None:
    with sync_playwright() as p:
        b = p.chromium.launch()
        RESULTS["N1-kind"] = run_filter(b, 0, "kind")
        RESULTS["N1-lang"] = run_filter(b, 1, "lang")
        RESULTS["reset"] = reset_check(b)
        b.close()
    (OUT / "checks.json").write_text(json.dumps(RESULTS, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(RESULTS, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
