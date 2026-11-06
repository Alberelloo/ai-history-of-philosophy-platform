"""Фокус с клавиатуры: кольцо на кнопке, переключателе, поле, упоминании и чекбоксе фильтра."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8099"
OUT = Path(__file__).resolve().parent
KEY = "philograph:v2"
STATE = json.dumps({"version": 2, "theme": "light", "notice": "2026-11"})
SRC = None
import urllib.request
src = json.loads(urllib.request.urlopen(BASE + "/api/v1/current").read())["source_id"]
toc = json.loads(urllib.request.urlopen(f"{BASE}/api/v1/sources/{src}/toc").read())
chap = next(i["chapter_id"] for i in toc if i["title"] == "Глава 3. Ответ Канта")

CASES = [
    ("library", "/", ".filter__input", "чекбокс фильтра"),
    ("library", "/", "input[type=search], .search input, input.pg-input", "поле поиска"),
    ("chapter", f"/read/{src}/{chap}", ".toc__assistant", "кнопка Ассистент (pg-btn)"),
    ("chapter", f"/read/{src}/{chap}", ".chapter-nav__next, .pg-btn--secondary", "кнопка навигации по главам"),
    ("settings", "/settings", ".pg-switch__input", "переключатель (Switch)"),
    ("settings", "/settings", ".pg-seg__item", "сегмент (SegmentedControl)"),
]

out = {}
with sync_playwright() as p:
    b = p.chromium.launch()
    for theme in ["light", "dark"]:
        ctx = b.new_context(viewport={"width": 1440, "height": 900}, locale="ru-RU")
        ctx.add_init_script(f"if(!localStorage.getItem('{KEY}')) localStorage.setItem('{KEY}', JSON.stringify({{version:2, theme:'{theme}', notice:'2026-11'}}));")
        page = ctx.new_page()
        for name, path, sel, label in CASES:
            page.goto(BASE + path)
            page.wait_for_selector(".source, .chapter p, h1", timeout=15000)
            page.wait_for_timeout(300)
            # Фокус ставим клавишей Tab со старта страницы: так срабатывает :focus-visible.
            page.evaluate("() => document.activeElement && document.activeElement.blur()")
            hit = None
            for _ in range(60):
                page.keyboard.press("Tab")
                ok = page.evaluate("(s) => { const e = document.activeElement; return !!e && e.matches(s) && e.matches(':focus-visible'); }", sel)
                if ok:
                    hit = True
                    page.wait_for_timeout(700)
                    break
            key = f"{name}-{theme}-{label}"
            if not hit:
                out[key] = {"found": False}
                continue
            info = page.evaluate("(s) => { const e = document.activeElement; const cs = getComputedStyle(e);"
                                 " return { tag: e.tagName, cls: String(e.className).slice(0,50), shadow: cs.boxShadow, outline: cs.outlineStyle + ' ' + cs.outlineWidth }; }", sel)
            box = page.locator(":focus").first.bounding_box()
            clip = {"x": max(box["x"] - 12, 0), "y": max(box["y"] - 12, 0), "width": box["width"] + 24, "height": box["height"] + 24}
            fname = f"focus-{name}-{theme}-{CASES.index(next(c for c in CASES if c[3]==label))}.png"
            page.screenshot(path=str(OUT / fname), clip=clip)
            info["shot"] = fname
            out[key] = {"found": True, **info}
        ctx.close()
    b.close()
print(json.dumps(out, ensure_ascii=False, indent=1))
