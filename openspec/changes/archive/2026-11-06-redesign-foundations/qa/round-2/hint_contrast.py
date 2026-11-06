"""Раунд 2: контраст подсказок переключателей внутри уведомления (фактические цвета в браузере)."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
BASE = "http://127.0.0.1:8099"
OUT = Path(__file__).resolve().parent

def lum(c):
    c = [x / 255 for x in c[:3]]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]

def cr(a, b):
    la, lb = lum(a), lum(b)
    return round((max(la, lb) + 0.05) / (min(la, lb) + 0.05), 2)

def rgb(s):
    import re
    return tuple(float(x) for x in re.findall(r"[\d.]+", s)[:3])

res = {}
with sync_playwright() as p:
    b = p.chromium.launch()
    for theme in ["light", "dark"]:
        ctx = b.new_context(viewport={"width": 1440, "height": 900}, locale="ru-RU")
        ctx.add_init_script(f"if(!localStorage.getItem('philograph:v2')) localStorage.setItem('philograph:v2', JSON.stringify({{version:2, theme:'{theme}'}}));")
        page = ctx.new_page()
        page.goto(BASE + "/")
        page.wait_for_selector(".first-run")
        vals = page.evaluate("""() => { const n = document.querySelector('.first-run');
          const h = n.querySelector('.pg-switch__hint'); const t = n.querySelector('.pg-switch__text');
          const bg = getComputedStyle(n).backgroundColor;
          return { hint: getComputedStyle(h).color, hintText: h.innerText, switchText: getComputedStyle(t).color, bg }; }""")
        res[theme] = {"bg": vals["bg"], "hint_color": vals["hint"], "hint_text": vals["hintText"],
                      "hint_ratio": cr(rgb(vals["hint"]), rgb(vals["bg"])),
                      "switch_text_ratio": cr(rgb(vals["switchText"]), rgb(vals["bg"]))}
        ctx.close()
    b.close()
(OUT / "hint_contrast.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps(res, ensure_ascii=False, indent=1))
