"""QA раунд 1: снимки экранов PhiloGraph и DOM-проверки оформления.

Стенд уже поднят: PHILOGRAPH_RATE_BURST=2000 .venv/Scripts/python scripts/dev_stack.py --port 8099
Запуск: .venv/Scripts/python openspec/changes/redesign-foundations/qa/round-1/shoot.py
Тема и язык переключаются кликами по верхней панели (группы «Тема» и «Язык интерфейса»).
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
TOKENS = Path(__file__).resolve().parents[5] / "docs" / "design" / "tokens.json"
KEY = "philograph:v2"
NOTICE_VERSION = "2026-11"
THEMES = ["light", "dark"]
LANGS = ["ru", "en"]
WIDTHS = [1440, 1024]
HEIGHT = 900
THEME_BUTTON = {"light": {"ru": "Светлая", "en": "Light"}, "dark": {"ru": "Тёмная", "en": "Dark"}}


def get(path: str):
    return json.loads(urllib.request.urlopen(BASE + path).read())


def load_tokens() -> dict:
    data = json.loads(TOKENS.read_text(encoding="utf-8"))
    out = {"light": {}, "dark": {}}
    for t in data["color"]["tokens"]:
        out["light"][t["name"]] = t["value"]["light"]
        out["dark"][t["name"]] = t["value"]["dark"]
    return out


TOK = load_tokens()


def hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def lum(rgb) -> float:
    def ch(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (ch(x) for x in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = lum(hex_rgb(a[:7])), lum(hex_rgb(b[:7]))
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def contrast_table() -> list[dict]:
    """Контраст пар текст/фон и нетекстовых элементов по tokens.json, обе темы."""
    text_pairs = [
        ("ink", "paper"), ("ink", "surface"), ("ink", "sunken"), ("ink-2", "paper"), ("ink-2", "surface"),
        ("ink-2", "sunken"), ("ink-3", "paper"), ("ink-3", "surface"), ("accent", "paper"),
        ("accent", "surface"), ("accent", "sunken"), ("on-accent", "accent"), ("people", "paper"),
        ("ideas", "paper"), ("teachings", "paper"), ("texts", "paper"), ("history", "paper"),
        ("people", "people-tint"), ("ideas", "ideas-tint"), ("teachings", "teachings-tint"),
        ("texts", "texts-tint"), ("history", "history-tint"), ("ink", "accent-soft"),
        ("generated", "generated-tint"), ("ink", "generated-tint"), ("ok", "surface"),
        ("danger", "paper"), ("danger", "surface"), ("danger", "danger-tint"),
    ]
    rows = []
    for theme in THEMES:
        t = TOK[theme]
        for fg, bg in text_pairs:
            ratio = contrast(t[fg], t[bg])
            rows.append({"theme": theme, "pair": f"{fg} на {bg}", "fg": t[fg], "bg": t[bg],
                         "ratio": round(ratio, 2), "need": 4.5, "ok": ratio >= 4.5})
        for fg, bg in [("accent", "paper"), ("accent", "surface")]:
            ratio = contrast(t[fg], t[bg])
            rows.append({"theme": theme, "pair": f"фокус {fg} на {bg} (нетекст)", "fg": t[fg], "bg": t[bg],
                         "ratio": round(ratio, 2), "need": 3.0, "ok": ratio >= 3.0})
    return rows


PAGE_CHECK_JS = r"""
() => {
  const q = (s) => document.querySelector(s);
  const fam = (s) => (q(s) ? getComputedStyle(q(s)).fontFamily : null);
  const vis = (e) => e.offsetParent !== null || getComputedStyle(e).position === 'fixed';
  const de = document.documentElement;
  const overflowX = de.scrollWidth - de.clientWidth;
  const boxes = [...document.querySelectorAll('.topbar__brand, .topbar__link, .topbar__tools .pg-seg')]
    .filter(vis).map((e) => ({ sel: e.className, r: e.getBoundingClientRect() }));
  const overlaps = [];
  for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
    const a = boxes[i].r, b = boxes[j].r;
    if (a.left < b.right - 0.5 && b.left < a.right - 0.5 && a.top < b.bottom - 0.5 && b.top < a.bottom - 0.5)
      overlaps.push([boxes[i].sel, boxes[j].sel]);
  }
  const links = [...document.querySelectorAll('.topbar__nav .topbar__link')].map((e) => e.getBoundingClientRect())
    .sort((a, b) => a.left - b.left);
  const linkGaps = links.slice(1).map((r, i) => Math.round(r.left - links[i].right));
  const clipped = [...document.querySelectorAll('button, a, label, h1, h2, h3, p, span, .topbar__link')]
    .filter((e) => vis(e) && e.scrollWidth > e.clientWidth + 1 && getComputedStyle(e).overflowX !== 'visible')
    .map((e) => (e.className || e.tagName).toString().slice(0, 60)).slice(0, 12);
  const native = [...document.querySelectorAll('select, input[type=checkbox], input[type=radio], button')]
    .filter(vis).filter((e) => e.tagName !== 'BUTTON' || !e.className.includes('pg-'))
    .map((e) => `${e.tagName}.${(e.className || '').toString().slice(0, 40)} appearance=${getComputedStyle(e).appearance}`)
    .slice(0, 12);
  const loaded = [...document.fonts].filter((f) => f.status === 'loaded').map((f) => `${f.family} ${f.weight}`);
  const cs = getComputedStyle(document.body);
  const hosts = [...new Set([...performance.getEntriesByType('resource')].map((r) => new URL(r.name).host))];
  return {
    lang: de.lang,
    dataTheme: de.getAttribute('data-theme'),
    bodyBg: cs.backgroundColor,
    bodyColor: cs.color,
    overflowX,
    overlaps,
    linkGaps,
    clipped,
    native,
    fontsLoaded: loaded,
    fontFamilies: { reading: fam('.chapter p'), button: fam('.pg-btn'), topbarLink: fam('.topbar__link') },
    hosts,
  };
}
"""

SCREEN_NAMES = ["library", "chapter", "card", "assistant", "graph", "settings"]


def set_theme_lang(page, theme: str, lang: str) -> None:
    """Переключение через интерфейс: тема и язык в верхней панели."""
    page.goto(BASE + "/")
    page.wait_for_selector(".source")
    if theme != "system":
        group = page.get_by_role("group", name="Тема")
        group.get_by_role("button", name=THEME_BUTTON[theme]["ru"]).click()
    if lang == "en":
        page.get_by_role("group", name="Язык интерфейса").get_by_role("button", name="EN", exact=True).click()
        page.wait_for_function("() => document.documentElement.lang === 'en'")


def open_screen(page, name: str, ids: dict) -> None:
    if name == "library":
        page.goto(BASE + "/")
        page.wait_for_selector(".source")
    elif name in ("chapter", "card", "assistant"):
        page.goto(f"{BASE}/read/{ids['source']}/{ids['chapter']}")
        page.wait_for_selector(".chapter p")
        page.locator(".mention").first.wait_for()
        if name == "card":
            page.locator("p.block", has_text="догматического сна").locator(".mention", has_text="Юм").click()
            page.wait_for_selector(".card-description")
            page.wait_for_function(
                "() => { const d = document.querySelector('.card-description');"
                " return d && d.textContent.trim().length > 0; }"
            )
        if name == "assistant":
            page.locator(".toc__assistant").click()
            page.wait_for_selector("textarea, input[type=text]", timeout=10000)
    elif name == "graph":
        page.goto(f"{BASE}/graph/{ids['kant']}?recipe=genesis")
        page.wait_for_selector("h1")
        try:
            page.wait_for_function(
                "() => document.querySelectorAll('.graph-edge').length >= 3"
                " && !document.querySelector('.graph-page .loading')",
                timeout=20000,
            )
        except Exception:
            pass
    elif name == "settings":
        page.goto(BASE + "/settings")
        page.wait_for_selector("h1")
    page.wait_for_timeout(400)


def dump_text(page, path: Path) -> str:
    text = page.evaluate("() => document.body.innerText")
    path.write_text(text, encoding="utf-8")
    return text


def focus_probe(page) -> dict:
    """Tab с начала страницы до первого элемента оформления; кольцо фокуса и его цвет."""
    page.goto(BASE + "/")
    page.wait_for_selector(".source")
    page.evaluate("() => document.activeElement && document.activeElement.blur()")
    found = None
    for _ in range(25):
        page.keyboard.press("Tab")
        info = page.evaluate(
            """() => { const e = document.activeElement; if (!e) return null;
              const cs = getComputedStyle(e);
              return { tag: e.tagName, cls: (e.className||'').toString().slice(0,60), text: (e.innerText||e.getAttribute('aria-label')||'').slice(0,40),
                       shadow: cs.boxShadow, outline: cs.outlineStyle, focusVisible: e.matches(':focus-visible') }; }"""
        )
        if info and info["focusVisible"] and ("pg-" in info["cls"] or "topbar__link" in info["cls"]):
            found = info
            break
    return found or {"note": "фокус не найден"}


def main() -> None:
    OUT.joinpath("text").mkdir(exist_ok=True)
    source = get("/api/v1/current")["source_id"]
    toc = get(f"/api/v1/sources/{source}/toc")
    chapter = next(i["chapter_id"] for i in toc if i["title"] == "Глава 3. Ответ Канта")
    kant = get("/api/knowledge/v1/entities?" + urllib.parse.urlencode({"name": "Кант"}))[0]["id"]
    ids = {"source": source, "chapter": chapter, "kant": kant}

    results: dict = {"ids": ids, "contrast": contrast_table(), "shots": [], "errors": [], "focus": {}}

    with sync_playwright() as p:
        browser = p.chromium.launch()

        # Тема «как в системе» по умолчанию: без сохранённой темы, системная тёмная.
        for scheme in ["light", "dark"]:
            ctx = browser.new_context(viewport={"width": 1280, "height": HEIGHT}, locale="ru-RU",
                                      color_scheme=scheme, reduced_motion="reduce")
            ctx.add_init_script(
                f"if(!localStorage.getItem('{KEY}')) localStorage.setItem('{KEY}', JSON.stringify({{version:2, notice:'{NOTICE_VERSION}'}}));"
            )
            pg = ctx.new_page()
            pg.goto(BASE + "/")
            pg.wait_for_selector(".source")
            info = pg.evaluate(PAGE_CHECK_JS)
            results.setdefault("system_theme", {})[scheme] = {"bodyBg": info["bodyBg"], "dataTheme": info["dataTheme"]}
            ctx.close()

        for theme in THEMES:
            for lang in LANGS:
                for width in WIDTHS:
                    tag = f"{theme}-{lang}-{width}"
                    ctx = browser.new_context(viewport={"width": width, "height": HEIGHT}, locale="ru-RU",
                                              reduced_motion="reduce")
                    ctx.add_init_script(
                        f"if(!localStorage.getItem('{KEY}')) localStorage.setItem('{KEY}', JSON.stringify({{version:2, notice:'{NOTICE_VERSION}'}}));"
                    )
                    page = ctx.new_page()
                    page.set_default_timeout(15000)
                    hosts: set[str] = set()
                    page.on("request", lambda r: hosts.add(urllib.parse.urlparse(r.url).netloc))
                    console_errors: list[str] = []
                    page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
                    page.on("pageerror", lambda e: console_errors.append(f"pageerror: {e}"))
                    try:
                        set_theme_lang(page, theme, lang)
                    except Exception as exc:  # noqa: BLE001
                        results["errors"].append({"tag": tag, "step": "переключение", "error": str(exc)[:300]})
                        ctx.close()
                        continue
                    for name in SCREEN_NAMES:
                        shot = f"{name}-{tag}.png"
                        entry = {"screen": name, "theme": theme, "lang": lang, "width": width, "shot": f"round-1/{shot}"}
                        try:
                            open_screen(page, name, ids)
                            entry["checks"] = page.evaluate(PAGE_CHECK_JS)
                            entry["text_file"] = f"text/{name}-{tag}.txt"
                            entry["text"] = dump_text(page, OUT / entry["text_file"])
                            page.screenshot(path=str(OUT / shot), full_page=True)
                        except Exception as exc:  # noqa: BLE001
                            entry["error"] = str(exc)[:400]
                            try:
                                page.screenshot(path=str(OUT / shot), full_page=True)
                            except Exception:  # noqa: BLE001
                                pass
                        results["shots"].append(entry)
                    # Уведомление не открываем здесь: оно есть только при первом входе (см. ниже).
                    if theme == "light" and lang == "ru" and width == 1440:
                        results["focus"]["library"] = focus_probe(page)
                    results.setdefault("hosts", {})[tag] = sorted(hosts)
                    results.setdefault("console_errors", {})[tag] = console_errors[:20]
                    ctx.close()

        # Уведомление при первом входе: язык по браузеру, тема как в системе.
        for loc, lang in [("ru-RU", "ru"), ("en-US", "en")]:
            for scheme in ["light", "dark"]:
                for width in WIDTHS:
                    tag = f"{scheme}-{lang}-{width}"
                    ctx = browser.new_context(viewport={"width": width, "height": HEIGHT}, locale=loc,
                                              color_scheme=scheme, reduced_motion="reduce")
                    page = ctx.new_page()
                    page.set_default_timeout(15000)
                    shot = f"notice-{tag}.png"
                    entry = {"screen": "notice", "theme": scheme, "lang": lang, "width": width, "shot": f"round-1/{shot}"}
                    try:
                        page.goto(BASE + "/")
                        page.wait_for_selector(".first-run__title", timeout=15000)
                        entry["checks"] = page.evaluate(PAGE_CHECK_JS)
                        entry["text_file"] = f"text/notice-{tag}.txt"
                        entry["text"] = dump_text(page, OUT / entry["text_file"])
                        page.screenshot(path=str(OUT / shot), full_page=False)
                    except Exception as exc:  # noqa: BLE001
                        entry["error"] = str(exc)[:400]
                        try:
                            page.screenshot(path=str(OUT / shot), full_page=False)
                        except Exception:  # noqa: BLE001
                            pass
                    results["shots"].append(entry)
                    ctx.close()

        browser.close()

    OUT.joinpath("results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    ok = sum(1 for s in results["shots"] if "error" not in s)
    print(f"снимков: {len(results['shots'])}, без ошибок: {ok}")
    print("ошибки переключения:", results["errors"])


if __name__ == "__main__":
    main()
