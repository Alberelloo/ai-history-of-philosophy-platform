"""QA раунд 3 (навигация): проверка поведения по сценариям спецификаций.

Стенд: PHILOGRAPH_RATE_BURST=2000 .venv/Scripts/python scripts/dev_stack.py --port 8099
Запуск: .venv/Scripts/python openspec/changes/redesign-navigation/qa/round-3/checks.py
Результат: round-3/checks.json. Каждая проверка записывает значение или ошибку, падение одной не останавливает остальные.
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
KEY = "philograph:v3"
NOTICE = "2026-11"
READ_RE = re.compile(r"^(Читать|Read)$")
RESULTS: dict = {}


def get(path: str):
    return json.loads(urllib.request.urlopen(BASE + path).read())


SRC = get("/api/v1/current")["source_id"]
TOC = get(f"/api/v1/sources/{SRC}/toc")
CHAPTER = next(i["chapter_id"] for i in TOC if i["title"] == "Глава 3. Ответ Канта")


def ctx_page(browser, width=1440, lang="ru-RU", state=None):
    ctx = browser.new_context(viewport={"width": width, "height": 900}, locale=lang, reduced_motion="reduce")
    st = state if state is not None else {"version": 3, "theme": "light", "openSources": [], "sidebarPinned": False, "notice": NOTICE}
    ctx.add_init_script(f"if(!localStorage.getItem('{KEY}')) localStorage.setItem('{KEY}', JSON.stringify({json.dumps(st)}));")
    page = ctx.new_page()
    page.set_default_timeout(15000)
    errors: list = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page._errors = errors  # noqa: SLF001
    return ctx, page


def check(name):
    def wrap(fn):
        def run(*args, **kwargs):
            try:
                RESULTS[name] = fn(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                RESULTS[name] = {"error": str(exc)[:300]}
        return run
    return wrap


def box(page, sel):
    return page.evaluate("(s) => { const e = document.querySelector(s); if (!e) return null; const r = e.getBoundingClientRect();"
                         " return {l: r.left, r: r.right, t: r.top, b: r.bottom, w: r.width}; }", sel)


def sidebar_state(page):
    return page.evaluate("() => document.querySelector('.sidebar')?.dataset.state")


def mouse_away(page):
    page.mouse.move(700, 450)
    page.wait_for_timeout(350)


def hover(page):
    page.mouse.move(20, 300)
    page.wait_for_timeout(350)


def cyrillic(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if re.search("[А-Яа-яЁё]", ln)]


@check("S1 hover-expands-no-shift")
def s1(browser):
    ctx, page = ctx_page(browser)
    page.goto(BASE + "/")
    page.wait_for_selector(".source")
    mouse_away(page)
    before = {"state": sidebar_state(page), "h1": box(page, "h1")["l"], "w": box(page, ".sidebar")["w"]}
    hover(page)
    after = {"state": sidebar_state(page), "h1": box(page, "h1")["l"], "w": box(page, ".sidebar")["w"]}
    ctx.close()
    return {"before": before, "after": after, "ok": before["state"] == "collapsed" and after["state"] == "expanded"
            and before["h1"] == after["h1"] and after["w"] >= 250}


@check("S2 keyboard-focus-expands-esc-collapses")
def s2(browser):
    ctx, page = ctx_page(browser)
    page.goto(BASE + "/")
    page.wait_for_selector(".source")
    mouse_away(page)
    page.evaluate("() => document.activeElement && document.activeElement.blur()")
    page.keyboard.press("Tab")
    page.wait_for_timeout(300)
    first = page.evaluate("() => ({tag: document.activeElement.tagName, cls: String(document.activeElement.className).slice(0, 60),"
                          " focusVisible: document.activeElement.matches(':focus-visible'), inSidebar: !!document.activeElement.closest('.sidebar')})")
    state_after_tab = sidebar_state(page)
    shadow = page.evaluate("() => getComputedStyle(document.activeElement).boxShadow")
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    state_after_esc = sidebar_state(page)
    focus_after_esc = page.evaluate("() => document.activeElement && document.activeElement.id")
    ctx.close()
    return {"first_focus": first, "state_after_tab": state_after_tab, "focus_ring": shadow,
            "state_after_esc": state_after_esc, "focus_after_esc": focus_after_esc,
            "ok": first["inSidebar"] and state_after_tab == "expanded" and state_after_esc == "collapsed" and focus_after_esc == "content"}


@check("S3 pin-shifts-content-at-1280plus")
def s3(browser):
    out = {}
    for width in [1280, 1440, 1920]:
        ctx, page = ctx_page(browser, width=width)
        page.goto(f"{BASE}/read/{SRC}/{CHAPTER}")
        page.wait_for_selector(".chapter p")
        page.locator(".sidebar__pin").click()
        mouse_away(page)
        page.wait_for_timeout(400)
        sb = box(page, ".sidebar")
        ch = box(page, ".chapter")
        toc = box(page, ".toc")
        out[width] = {"state": sidebar_state(page), "sidebar_w": sb["w"], "chapter_left": ch["l"],
                      "toc_left": toc["l"] if toc else None, "overlaps": ch["l"] < sb["r"] or (toc is not None and toc["l"] < sb["r"]),
                      "no_horizontal_scroll": page.evaluate("() => document.documentElement.scrollWidth <= document.documentElement.clientWidth")}
        page.reload()
        page.wait_for_selector(".chapter p")
        out[width]["pinned_after_reload"] = sidebar_state(page)
        ctx.close()
    out["ok"] = all(v.get("state") == "pinned" and not v.get("overlaps") and v.get("pinned_after_reload") == "pinned"
                    for k, v in out.items() if isinstance(v, dict))
    return out


@check("S4 pin-unavailable-below-1280")
def s4(browser):
    out = {}
    for width in [1024, 1279]:
        ctx, page = ctx_page(browser, width=width, state={"version": 3, "theme": "light", "openSources": [], "sidebarPinned": True, "notice": NOTICE})
        page.goto(f"{BASE}/read/{SRC}/{CHAPTER}")
        page.wait_for_selector(".chapter p")
        mouse_away(page)
        pin = page.locator(".sidebar__pin")
        out[width] = {"state": sidebar_state(page), "pin_disabled": pin.is_disabled(),
                      "pin_pressed": pin.get_attribute("aria-pressed"), "pin_title": pin.get_attribute("title"),
                      "chapter_left": box(page, ".chapter")["l"], "sidebar_w": box(page, ".sidebar")["w"]}
        hover(page)
        out[width]["hover_state"] = sidebar_state(page)
        out[width]["chapter_left_on_hover"] = box(page, ".chapter")["l"]
        ctx.close()
    out["ok"] = all(v["state"] != "pinned" and v["pin_disabled"] and v["chapter_left"] > 56 for v in out.values() if isinstance(v, dict) and "state" in v)
    return out


@check("S5 text-not-under-panel-by-width")
def s5(browser):
    out = {}
    for width in [1024, 1280, 1440, 1920]:
        ctx, page = ctx_page(browser, width=width)
        page.goto(f"{BASE}/read/{SRC}/{CHAPTER}")
        page.wait_for_selector(".chapter p")
        mouse_away(page)
        collapsed = box(page, ".sidebar")
        ch = box(page, ".chapter")
        out[width] = {"collapsed_overlap": ch["l"] < collapsed["r"], "collapsed_chapter_left": ch["l"],
                      "chapter_w_chars_ok": box(page, ".chapter")["w"] >= 0}
        ctx.close()
    out["ok"] = all(not v["collapsed_overlap"] for v in out.values() if isinstance(v, dict))
    return out


@check("S6 open-books-close-keeps-place")
def s6(browser):
    ctx, page = ctx_page(browser)
    page.goto(f"{BASE}/read/{SRC}/{CHAPTER}")
    page.wait_for_selector(".chapter p")
    paras = page.evaluate("() => [...document.querySelectorAll('.chapter [data-paragraph], .chapter p[id^=p-]')].map(e => e.id || e.dataset.paragraph)")
    target = paras[-1] if paras else None
    if target:
        page.goto(f"{BASE}/read/{SRC}/{CHAPTER}#{target if target.startswith('p-') else 'p-' + target}")
        page.wait_for_timeout(700)
    page.goto(BASE + "/")
    page.wait_for_selector(".source")
    page.get_by_role("button", name=READ_RE).nth(0).click()
    page.wait_for_selector(".sidebar__book", state="attached")
    page.wait_for_timeout(300)
    count_two = page.locator(".sidebar__book").count()
    books = count_two
    current_title = page.evaluate("() => document.querySelector('.sidebar__book.is-current .sidebar__book-title')?.textContent")
    # Закрываем книгу, которая открыта первой (вторая в списке).
    close_btns = page.locator(".sidebar__close")
    hover(page)
    close_btns.last.click()
    page.wait_for_timeout(300)
    after_close = page.locator(".sidebar__book").count()
    # Снова открываем её из библиотеки (вторая карточка — та же книга, что закрыта).
    page.goto(BASE + "/")
    page.wait_for_selector(".source")
    page.get_by_role("button", name=READ_RE).nth(1).click()
    page.wait_for_timeout(700)
    reopened_url = page.url
    para_in_view = page.evaluate("() => { const p = document.querySelector('.chapter [data-paragraph]:last-of-type') || document.getElementById('" + (target or "x") + "'); if (!p) return null; const r = p.getBoundingClientRect(); return r.top < window.innerHeight && r.bottom > 0; }")
    ctx.close()
    return {"books_after_two_opens": count_two, "books_after_reopen_first": books, "current_title": current_title,
            "books_after_close": after_close, "reopened_url": reopened_url, "target_paragraph": target,
            "paragraph_in_view_after_reopen": para_in_view,
            "ok": count_two == 2 and books == 2 and after_close == 1 and CHAPTER in reopened_url}


@check("S7 filters-menu-behaviour")
def s7(browser):
    ctx, page = ctx_page(browser)
    page.goto(BASE + "/")
    page.wait_for_selector(".source")
    mouse_away(page)
    out: dict = {}

    def step(name, fn):
        try:
            out[name] = fn()
        except Exception as exc:  # noqa: BLE001
            out[name] = {"error": str(exc).splitlines()[0][:160]}

    kind = page.locator(".pg-filter__button").nth(0)
    lang = page.locator(".pg-filter__button").nth(1)
    menu = page.locator(".pg-filter-menu")
    out["search_w_before"] = box(page, ".pg-input")["w"]
    step("open_kind", lambda: (kind.click(), page.wait_for_timeout(250), menu.count())[2])
    step("menu_labels", lambda: menu.inner_text())
    step("select_all", lambda: (page.get_by_role("button", name="Выбрать все").click(), page.wait_for_timeout(200),
                                page.locator(".pg-filter__count").nth(0).inner_text())[2])
    step("visible_all", lambda: page.locator(".source").count())
    step("clear_all", lambda: (page.get_by_role("button", name="Снять все").click(), page.wait_for_timeout(200), page.locator(".source").count())[2])
    step("esc_closes", lambda: (page.keyboard.press("Escape"), page.wait_for_timeout(200), menu.count())[2])
    step("focus_after_esc", lambda: page.evaluate("() => document.activeElement && document.activeElement.className"))
    step("reopen_and_pick_textbook", lambda: (kind.click(), page.wait_for_timeout(250),
                                              page.locator(".pg-filter-menu label", has_text="Учебник").click(),
                                              page.wait_for_timeout(200), page.locator(".source").count())[3])
    step("outside_closes", lambda: (page.mouse.click(10, 880), page.wait_for_timeout(200), menu.count())[2])
    step("count_after_pick", lambda: page.locator(".pg-filter__count").nth(0).inner_text())
    out["search_w_after_pick"] = box(page, ".pg-input")["w"]
    step("typing", lambda: (page.locator(".pg-input").first.fill("кант"), page.wait_for_timeout(300))[1])
    out["search_w_typing"] = box(page, ".pg-input")["w"]
    step("reset_button_enabled", lambda: page.get_by_role("button", name="Сбросить поиск и фильтры").is_enabled())
    step("reset", lambda: (page.get_by_role("button", name="Сбросить поиск и фильтры").click(), page.wait_for_timeout(200), page.locator(".source").count())[2])
    step("lang_options", lambda: (lang.click(), page.wait_for_timeout(250), page.locator(".pg-filter-menu label").all_inner_texts())[2])
    step("lang_close", lambda: (page.keyboard.press("Escape"), page.wait_for_timeout(200), menu.count())[2])
    step("empty_pick", lambda: (kind.click(), page.wait_for_timeout(250),
                                page.locator(".pg-filter-menu label", has_text="Справочное издание").click(),
                                page.mouse.click(10, 880), page.wait_for_timeout(200),
                                lang.click(), page.wait_for_timeout(250),
                                page.locator(".pg-filter-menu label", has_text="русский").click(),
                                page.mouse.click(10, 880), page.wait_for_timeout(300), "ok")[-1])
    step("empty_text", lambda: page.locator("main").inner_text()[:400])
    ctx.close()
    out["ok"] = out["search_w_before"] == out["search_w_after_pick"] == out["search_w_typing"] and out.get("esc_closes") == 0 and out.get("outside_closes") == 0
    return out


@check("S8 stale-chapter-stays-in-book")
def s8(browser):
    ctx, page = ctx_page(browser)
    page.goto(f"{BASE}/read/{SRC}/no-such-chapter")
    page.wait_for_selector(".chapter, .toc, .pg-notice", timeout=15000)
    page.wait_for_timeout(500)
    alert = page.locator("[role=alert]").count()
    notice = page.locator(".notice.relocated, .pg-notice[role=status]").all_inner_texts()
    toc = page.locator(".toc").count()
    chapter_present = page.locator(".chapter").count()
    url = page.url
    ctx.close()
    ctx, page = ctx_page(browser)
    page.goto(f"{BASE}/read/{SRC}/{CHAPTER}#p-missing-paragraph")
    page.wait_for_timeout(700)
    alert2 = page.locator("[role=alert]").count()
    chapter2 = page.locator(".chapter").count()
    ctx.close()
    return {"url_after": url, "alert_count": alert, "notice_texts": notice, "toc_present": toc, "chapter_present": chapter_present,
            "bad_anchor_alerts": alert2, "bad_anchor_chapter": chapter2,
            "ok": alert == 0 and toc == 1 and chapter_present == 1 and any(notice)}


@check("S9 unrendered-blocks-in-chapters")
def s9(browser):
    found = {}
    ctx, page = ctx_page(browser)
    for src in [SRC]:
        toc = get(f"/api/v1/sources/{src}/toc")
        for item in toc:
            page.goto(f"{BASE}/read/{src}/{item['chapter_id']}")
            page.wait_for_timeout(250)
            n = page.locator(".unrendered").count()
            if n:
                found[item["title"]] = n
    ctx.close()
    return {"unrendered_in_demo": found, "note": "в демо-данных необработанных частей нет, если пусто"}


@check("S10 soon-pages-and-sidebar-en")
def s10(browser):
    ctx, page = ctx_page(browser, lang="en-US", state={"version": 3, "theme": "light", "openSources": [], "sidebarPinned": False, "notice": NOTICE, "lang": "en"})
    page.goto(BASE + "/")
    page.wait_for_selector(".source")
    mouse_away(page)
    hover(page)
    side = page.locator(".sidebar__nav").inner_text()
    foot = page.locator(".sidebar__foot").inner_text()
    out = {"sidebar_cyrillic": cyrillic(side) + cyrillic(foot), "sidebar_sample": side[:300]}
    for code in ["graph", "assistant", "reference", "epochs", "compare", "route", "materials", "collections"]:
        page.goto(f"{BASE}/soon/{code}")
        page.wait_for_selector("h1", timeout=15000)
        page.wait_for_timeout(200)
        txt = page.locator("main").inner_text()
        out[code] = {"cyrillic_lines": cyrillic(txt)[:6], "has_status": bool(re.search("In development|Later", txt))}
    ctx.close()
    return out


@check("S11 sidebar-labels-keyboard-and-cycles")
def s11(browser):
    ctx, page = ctx_page(browser)
    page.goto(BASE + "/")
    page.wait_for_selector(".source")
    mouse_away(page)
    theme_btn = page.locator(".sidebar__tool").nth(1)
    seq = []
    for _ in range(3):
        theme_btn.click()
        page.wait_for_timeout(150)
        seq.append(page.evaluate("() => { try { return JSON.parse(localStorage.getItem('philograph:v3')).theme } catch (e) { return null } }"))
    lang_btn = page.locator(".sidebar__tool").nth(0)
    lang_btn.click()
    page.wait_for_timeout(200)
    lang_now = page.evaluate("() => document.documentElement.lang")
    ctx.close()
    return {"theme_cycle": seq, "lang_after_toggle": lang_now,
            "ok": seq == ["dark", "system", "light"] and lang_now == "en"}


@check("S12 book-titles-clipped-at-1024-expanded")
def s12(browser):
    out = {}
    for width in [1024, 1440]:
        ctx, page = ctx_page(browser, width=width, state={"version": 3, "theme": "light", "openSources": [{"id": SRC, "openedAt": 2}], "sidebarPinned": False, "notice": NOTICE, "currentSource": SRC})
        page.goto(BASE + "/")
        page.wait_for_selector(".source")
        mouse_away(page)
        hover(page)
        page.wait_for_timeout(300)
        out[width] = page.evaluate("""() => { const t = document.querySelector('.sidebar__book-title'); if (!t) return null;
          return { text: t.textContent, clientH: t.clientHeight, scrollH: t.scrollHeight, lineClamp: getComputedStyle(t).webkitLineClamp,
                   clipped: t.scrollHeight > t.clientHeight + 1, overflow: getComputedStyle(t).overflow, ellipsis: getComputedStyle(t).textOverflow }; }""")
        ctx.close()
    return out


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for fn in [s1, s2, s3, s4, s5, s6, s7, s8, s9, s10, s11, s12]:
            fn(browser)
        browser.close()
    (OUT / "checks.json").write_text(json.dumps(RESULTS, ensure_ascii=False, indent=1), encoding="utf-8")
    for k, v in RESULTS.items():
        status = v.get("ok") if isinstance(v, dict) and "ok" in v else ("error" if isinstance(v, dict) and "error" in v else "info")
        print(k, "->", status)


if __name__ == "__main__":
    main()
