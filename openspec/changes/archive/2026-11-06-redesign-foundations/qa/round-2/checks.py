"""QA раунд 2: проверки исправлений D1–D6, З1, З2 и регрессий (уведомление, ассистент, контраст, переводы).

Стенд: PHILOGRAPH_RATE_BURST=2000 .venv/Scripts/python scripts/dev_stack.py --port 8099
Запуск: .venv/Scripts/python openspec/changes/redesign-foundations/qa/round-2/checks.py
Результат: round-2/checks.json, снимки round-2/regress-*.png.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8099"
OUT = Path(__file__).resolve().parent
REPO = OUT.parents[4]
KEY = "philograph:v2"
NOTICE = "2026-11"


def get(path: str):
    return json.loads(urllib.request.urlopen(BASE + path).read())


src = get("/api/v1/current")["source_id"]
toc = get(f"/api/v1/sources/{src}/toc")
chapter = next(i["chapter_id"] for i in toc if i["title"] == "Глава 3. Ответ Канта")
kant = get("/api/knowledge/v1/entities?" + urllib.parse.urlencode({"name": "Кант"}))[0]["id"]
yum = get("/api/knowledge/v1/entities?" + urllib.parse.urlencode({"name": "Юм"}))[0]["id"]

RESULTS: dict = {}


def ctx_for(browser, *, lang_loc="ru-RU", theme="light", accepted=True, width=1440, scheme=None):
    kwargs = {"viewport": {"width": width, "height": 900}, "locale": lang_loc}
    if scheme:
        kwargs["color_scheme"] = scheme
    ctx = browser.new_context(**kwargs)
    state = {"version": 2, "theme": theme}
    if accepted:
        state["notice"] = NOTICE
    ctx.add_init_script(
        f"if(!localStorage.getItem('{KEY}')) localStorage.setItem('{KEY}', JSON.stringify({json.dumps(state)}));"
    )
    page = ctx.new_page()
    page.set_default_timeout(15000)
    hosts: set[str] = set()
    page.on("request", lambda r: hosts.add(urllib.parse.urlparse(r.url).netloc))
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page._hosts = hosts  # noqa: SLF001
    page._errors = errors  # noqa: SLF001
    return ctx, page


def text_of(page) -> str:
    return page.evaluate("() => document.body.innerText")


def contrast(c1: tuple, c2: tuple) -> float:
    def lum(c):
        def ch(v):
            v /= 255
            return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
        r, g, b = (ch(x) for x in c[:3])
        return 0.2126 * r + 0.7152 * g + 0.0722 * b
    a, b = lum(c1), lum(c2)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def rgb(s: str) -> tuple:
    nums = [float(x) for x in re.findall(r"[\d.]+", s)]
    return tuple(nums[:3]) if len(nums) >= 3 else (0, 0, 0)


def main() -> None:
    with sync_playwright() as p:
        b = p.chromium.launch()

        # --- D3: сетка библиотеки на 1440: первый ряд доходит до правого края ---
        for theme in ["light"]:
            for loc in ["ru-RU", "en-US"]:
                ctx, page = ctx_for(b, lang_loc=loc, theme=theme, width=1440)
                page.goto(BASE + "/")
                page.wait_for_selector(".source")
                info = page.evaluate("""() => {
                  const grid = document.querySelector('.source')?.parentElement;
                  const cards = [...document.querySelectorAll('.source')].map(e => e.getBoundingClientRect());
                  const cs = getComputedStyle(grid);
                  const gr = grid.getBoundingClientRect();
                  const rowRight = Math.max(...cards.filter(r => Math.abs(r.top - cards[0].top) < 4).map(r => r.right));
                  return { columns: cs.gridTemplateColumns, gridRight: gr.right, firstRowRight: rowRight,
                           cards: cards.length, emptyRight: Math.round(gr.right - rowRight) };
                }""")
                RESULTS[f"D3-{loc}"] = info
                page.screenshot(path=str(OUT / f"lib-{loc[:2]}-1440.png"), full_page=True)
                ctx.close()

        # --- D4: уведомление в потоке страницы; не закрывает карточки и не fixed ---
        for loc in ["ru-RU", "en-US"]:
            for width in [1440, 1024]:
                ctx, page = ctx_for(b, lang_loc=loc, accepted=False, width=width)
                page.goto(BASE + "/")
                page.wait_for_selector(".first-run")
                page.wait_for_timeout(800)
                info = page.evaluate("""() => {
                  const n = document.querySelector('.first-run');
                  const cs = getComputedStyle(n);
                  const r = n.getBoundingClientRect();
                  const cards = [...document.querySelectorAll('.source')].map(e => e.getBoundingClientRect());
                  const overlapping = cards.filter(c => c.left < r.right && r.left < c.right && c.top < r.bottom && r.top < c.bottom).length;
                  const topbar = document.querySelector('.topbar').getBoundingClientRect();
                  return { position: cs.position, boxShadow: cs.boxShadow, background: cs.backgroundColor,
                           top: Math.round(r.top), height: Math.round(r.height), belowTopbar: r.top >= topbar.bottom - 1,
                           overlapsCards: overlapping, dismissButton: !!n.querySelector('button') };
                }""")
                RESULTS[f"D4-{loc}-{width}"] = info
                page.screenshot(path=str(OUT / f"notice-{loc[:2]}-{width}.png"), full_page=True)
                ctx.close()

        # --- D4 регрессия: уведомление + открытая панель ассистента на экране чтения ---
        for theme in ["light", "dark"]:
            ctx, page = ctx_for(b, accepted=False, theme=theme, width=1440)
            page.goto(f"{BASE}/read/{src}/{chapter}")
            page.wait_for_selector(".chapter p")
            page.wait_for_selector(".first-run")
            page.locator(".toc__assistant").click()
            page.wait_for_timeout(600)
            info = page.evaluate("""() => {
              const n = document.querySelector('.first-run').getBoundingClientRect();
              const a = document.querySelector('aside[aria-label], aside.assistant');
              const ar = a ? a.getBoundingClientRect() : null;
              const chap = document.querySelector('.chapter').getBoundingClientRect();
              const send = document.querySelector('.assistant-panel button[type=submit], form button[type=submit]');
              const ov = (x, y) => !!y && x.left < y.right && y.left < x.right && x.top < y.bottom && y.top < x.bottom;
              return { notice: [Math.round(n.left), Math.round(n.top), Math.round(n.width), Math.round(n.height)],
                       assistant: ar ? [Math.round(ar.left), Math.round(ar.top), Math.round(ar.width), Math.round(ar.height)] : null,
                       noticeOverlapsAssistant: ov(n, ar), noticeOverlapsChapter: ov(n, chap),
                       sendDisabled: send ? send.disabled : null };
            }""")
            RESULTS[f"D4-assistant-{theme}"] = info
            page.screenshot(path=str(OUT / f"regress-notice-assistant-{theme}.png"), full_page=True)
            ctx.close()

        # --- D5: подписи языка в настройках ---
        ctx, page = ctx_for(b, lang_loc="ru-RU")
        page.goto(BASE + "/settings")
        page.wait_for_selector("h1")
        labels = page.get_by_role("group", name="Язык интерфейса").locator("button").all_inner_texts()
        RESULTS["D5-ru"] = labels
        ctx.close()

        # --- D6: годы без пробелов на карточке и графе ---
        ctx, page = ctx_for(b, lang_loc="ru-RU")
        page.goto(f"{BASE}/graph/{kant}?recipe=genesis")
        page.wait_for_selector("h1")
        try:
            page.wait_for_function("() => document.querySelectorAll('.graph-edge').length >= 3", timeout=20000)
        except Exception:
            pass
        page.wait_for_timeout(500)
        t = text_of(page)
        RESULTS["D6-graph"] = {"with_spaces": re.findall(r"\d{4} – \d{4}", t)[:5],
                               "no_spaces": re.findall(r"\d{4}–\d{4}", t)[:5]}
        page.screenshot(path=str(OUT / "graph-ru-1440.png"), full_page=True)
        ctx.close()

        ctx, page = ctx_for(b, lang_loc="ru-RU")
        page.goto(f"{BASE}/read/{src}/{chapter}")
        page.wait_for_selector(".chapter p")
        page.locator("p.block", has_text="догматического сна").locator(".mention", has_text="Юм").click()
        page.wait_for_selector(".card-description")
        page.wait_for_timeout(600)
        t = text_of(page)
        RESULTS["D6-card-ru"] = {"with_spaces": re.findall(r"\d{4} – \d{4}", t)[:5],
                                 "no_spaces": re.findall(r"\d{4}–\d{4}", t)[:5]}
        page.screenshot(path=str(OUT / "card-ru-1440.png"), full_page=False)
        ctx.close()

        # --- D1 / D2 / З2: английский интерфейс: карточка, граф ---
        ctx, page = ctx_for(b, lang_loc="en-US")
        page.goto(f"{BASE}/read/{src}/{chapter}")
        page.wait_for_selector(".chapter p")
        page.locator("p.block", has_text="догматического сна").locator(".mention", has_text="Юм").click()
        page.wait_for_selector(".card-description")
        page.wait_for_timeout(800)
        card_en = text_of(page)
        page.screenshot(path=str(OUT / "card-en-1440.png"), full_page=False)
        ctx.close()
        RESULTS["D1-card-en"] = {
            "russian_phrases": [s for s in ["Годы и места", "Влияния", "распространённое мнение", "испытал влияние",
                                            "повлиял на", "годы жизни", "Часто считают"] if s in card_en],
            "cyrillic_lines": [ln for ln in card_en.splitlines() if re.search("[А-Яа-яЁё]", ln)][:12],
            "З2_config_text": "config/llm" in card_en or "демонстрационный ответ" in card_en,
        }

        ctx, page = ctx_for(b, lang_loc="en-US")
        page.goto(f"{BASE}/graph/{kant}?recipe=genesis")
        page.wait_for_selector("h1")
        try:
            page.wait_for_function("() => document.querySelectorAll('.graph-edge').length >= 3", timeout=20000)
        except Exception:
            pass
        page.wait_for_timeout(500)
        graph_en = text_of(page)
        page.screenshot(path=str(OUT / "graph-en-1440.png"), full_page=True)
        RESULTS["D2-graph-en"] = {
            "cyrillic_lines": [ln for ln in graph_en.splitlines() if re.search("[А-Яа-яЁё]", ln)][:12],
            "has_genesis_en": "Genesis" in graph_en,
        }
        ctx.close()

        # --- З2 (карточка RU): описание не содержит служебного текста ---
        RESULTS["З2-card-ru"] = {"config_text": "config/llm" in t or "демонстрационный ответ" in t}

        # --- Регрессия: переводы ассистента и подсказок с ответами на EN ---
        ctx, page = ctx_for(b, lang_loc="en-US", accepted=True)
        page.goto(f"{BASE}/read/{src}/{chapter}")
        page.wait_for_selector(".chapter p")
        page.locator(".toc__assistant").click()
        page.wait_for_selector("aside.assistant")
        page.wait_for_timeout(500)
        panel_en = page.locator("aside.assistant").first.inner_text()
        RESULTS["assistant-en"] = {"cyrillic_lines": [ln for ln in panel_en.splitlines() if re.search("[А-Яа-яЁё]", ln)][:8]}
        page.screenshot(path=str(OUT / "regress-assistant-en-1440.png"), full_page=False)
        ctx.close()

        # --- Регрессия: контраст текста уведомления на его подложке (обе темы) ---
        for theme, scheme in [("light", "light"), ("dark", "dark")]:
            ctx, page = ctx_for(b, accepted=False, theme=theme, width=1440)
            page.goto(BASE + "/")
            page.wait_for_selector(".first-run")
            page.wait_for_timeout(600)
            vals = page.evaluate("""() => {
              const n = document.querySelector('.first-run');
              const pick = (sel) => { const e = n.querySelector(sel) || n; return getComputedStyle(e).color; };
              const bg = getComputedStyle(n).backgroundColor;
              return { body: pick('.notice-text, p, div'), title: pick('.first-run__title'), button: pick('button'), bg,
                       hint: pick('.generation-settings') };
            }""")
            RESULTS[f"contrast-notice-{theme}"] = {k: (vals[k], round(contrast(rgb(vals[k]), rgb(vals["bg"])), 2)) for k in ["body", "title", "button", "hint"]}
            ctx.close()

        # --- Сеть: внешние хосты ---
        ctx, page = ctx_for(b, lang_loc="ru-RU")
        page.goto(f"{BASE}/settings")
        page.wait_for_selector("h1")
        page.wait_for_timeout(500)
        RESULTS["hosts"] = sorted(page._hosts)  # noqa: SLF001
        RESULTS["console_errors"] = page._errors[:10]  # noqa: SLF001
        ctx.close()
        b.close()

    # --- З1: @import Google Fonts в документе дизайна ---
    css = (REPO / "docs" / "design" / "system" / "components.css").read_text(encoding="utf-8")
    RESULTS["З1"] = {"googleapis_import": "fonts.googleapis.com" in css, "first_line": css.splitlines()[0][:80]}

    (OUT / "checks.json").write_text(json.dumps(RESULTS, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(RESULTS, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
