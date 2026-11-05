"""Увеличенный снимок фокуса на чекбоксе фильтра (светлая тема, 1440): рамка чипа и кольцо."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
BASE = "http://127.0.0.1:8099"
OUT = Path(__file__).resolve().parent
with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1440, "height": 900}, locale="ru-RU", device_scale_factor=3)
    ctx.add_init_script("if(!localStorage.getItem('philograph:v2')) localStorage.setItem('philograph:v2', JSON.stringify({version:2, theme:'light', notice:'2026-11'}));")
    page = ctx.new_page()
    page.goto(BASE + "/")
    page.wait_for_selector(".source")
    chip = page.locator(".filter").first
    before = chip.evaluate("e => getComputedStyle(e).borderColor + ' | ' + getComputedStyle(e).boxShadow")
    page.locator(".filter__input").first.focus()
    page.keyboard.press("Shift+Tab"); page.keyboard.press("Tab")
    page.wait_for_timeout(700)
    after = chip.evaluate("e => getComputedStyle(e).borderColor + ' | ' + getComputedStyle(e).boxShadow")
    focused = page.evaluate("() => [document.activeElement.className, document.activeElement.matches(':focus-visible')]")
    box = chip.bounding_box()
    page.screenshot(path=str(OUT / "focus-filter-zoom-light.png"), clip={"x": box["x"]-8, "y": box["y"]-8, "width": box["width"]+16, "height": box["height"]+16})
    print(json.dumps({"before": before, "after": after, "focused": focused}, ensure_ascii=False))
    b.close()
