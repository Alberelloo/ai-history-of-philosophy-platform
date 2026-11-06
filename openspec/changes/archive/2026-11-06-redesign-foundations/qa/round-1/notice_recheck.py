"""Повторная съёмка уведомления при первом входе после окончания анимации появления."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8099"
OUT = Path(__file__).resolve().parent
res = {}
with sync_playwright() as p:
    b = p.chromium.launch()
    for loc, lang in [("ru-RU", "ru"), ("en-US", "en")]:
        for scheme in ["light", "dark"]:
            for width in [1440, 1024]:
                ctx = b.new_context(viewport={"width": width, "height": 900}, locale=loc, color_scheme=scheme)
                page = ctx.new_page()
                page.goto(BASE + "/")
                page.wait_for_selector(".first-run__title")
                page.wait_for_timeout(1500)
                info = page.evaluate("""() => { const n = document.querySelector('.first-run'); const cs = getComputedStyle(n);
                    const r = n.getBoundingClientRect();
                    return { opacity: cs.opacity, bg: cs.backgroundColor, animation: cs.animationName, box: [r.left, r.top, r.width, r.height] }; }""")
                tag = f"{scheme}-{lang}-{width}"
                page.screenshot(path=str(OUT / f"notice-recheck-{tag}.png"))
                res[tag] = info
                ctx.close()
    b.close()
print(json.dumps(res, ensure_ascii=False, indent=1))
