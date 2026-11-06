"""Раунд 2, регрессия: вопрос ассистенту до принятия уведомления (ru и en, обе темы)."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
BASE = "http://127.0.0.1:8099"
OUT = Path(__file__).resolve().parent
import urllib.request
src = json.loads(urllib.request.urlopen(BASE + "/api/v1/current").read())["source_id"]
toc = json.loads(urllib.request.urlopen(f"{BASE}/api/v1/sources/{src}/toc").read())
ch = next(i["chapter_id"] for i in toc if i["title"] == "Глава 3. Ответ Канта")
res = {}
with sync_playwright() as p:
    b = p.chromium.launch()
    for loc, lang in [("ru-RU", "ru"), ("en-US", "en")]:
        for theme in ["light", "dark"]:
            ctx = b.new_context(viewport={"width": 1440, "height": 900}, locale=loc)
            ctx.add_init_script(f"if(!localStorage.getItem('philograph:v2')) localStorage.setItem('philograph:v2', JSON.stringify({{version:2, theme:'{theme}'}}));")
            page = ctx.new_page()
            requests = []
            page.on("request", lambda r: requests.append(r.url) if "/api/" in r.url and ("assist" in r.url) else None)
            page.goto(f"{BASE}/read/{src}/{ch}")
            page.wait_for_selector(".chapter p")
            page.locator(".toc__assistant").click()
            panel = page.locator("aside.assistant")
            panel.wait_for()
            panel.locator("textarea").fill("что Кант взял у Юма?")
            panel.locator("button[type=submit]").click()
            page.wait_for_timeout(800)
            problem = panel.inner_text()
            notice_cls = page.locator(".first-run").get_attribute("class")
            info = page.evaluate("""() => { const n = document.querySelector('.first-run'); const s = document.querySelector('aside.assistant');
              const a = n.getBoundingClientRect(), c = s.getBoundingClientRect();
              const ov = a.left < c.right && c.left < a.right && a.top < c.bottom && c.top < a.bottom;
              return { overlapsAssistant: ov, bg: getComputedStyle(n).backgroundColor };}""")
            page.screenshot(path=str(OUT / f"gate-{lang}-{theme}.png"), full_page=False)
            res[f"{lang}-{theme}"] = {"notice_class": notice_cls, "assistant_request_sent": len(requests), **info,
                                      "panel_text_head": problem[:300]}
            ctx.close()
    b.close()
(OUT / "gate.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps(res, ensure_ascii=False, indent=1))
