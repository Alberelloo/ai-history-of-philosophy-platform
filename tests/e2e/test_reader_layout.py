"""Раскладка экрана чтения и плавный масштаб (этап reader-layout): T4, T5, T32, T37, T45.

Свой стенд на модуль (как у ``test_visual_design.py``): нужны библиотека, граф знаний и
ассистент. Главы демо-учебника короткие, поэтому для сценариев с прокруткой ответ главы
подменяется в браузере (``page.route``): к настоящим блокам добавляются абзацы-заполнители.
Номера Tn — по таблице 14.2 ``docs/design/features/reader-panels.md``.

Проверка ``styles.css`` без браузера (размеры в ``rem``, Р9) идёт и в быстром прогоне.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import httpx
import pytest

from ..helpers import aside
from . import visual
from .conftest import NOTICE_VERSION, TEST_RATE_BURST

req = pytest.mark.req
e2e = pytest.mark.e2e
VD = "visual-design"
AD = "assistant-dialog"
CR = "chapter-reading"
KEY = "philograph:v4"
ROOT = Path(__file__).resolve().parents[2]
STYLES = ROOT / "web" / "src" / "styles.css"
CHAPTER_3 = "Глава 3. Ответ Канта"
CHAPTER_2 = "Глава 2. Юм и проблема индукции"
SECTION = "Привычка и ожидание"


@pytest.fixture(scope="module")
def site(request, tmp_path_factory):
    if os.environ.get("PHILOGRAPH_E2E_URL"):
        yield request.getfixturevalue("stack")
        return
    if not (ROOT / "web" / "dist" / "index.html").exists():
        pytest.skip("клиент не собран: npm run build в web/")
    import dev_stack

    os.environ.setdefault("PHILOGRAPH_RATE_BURST", TEST_RATE_BURST)
    running = dev_stack.start(tmp_path_factory.mktemp("layout-stack"))
    yield running
    running.stop()


@pytest.fixture(scope="module")
def ids(site) -> dict[str, str]:
    source = httpx.get(site.url + "/api/v1/current").json()["source_id"]
    toc = httpx.get(f"{site.url}/api/v1/sources/{source}/toc").json()

    def walk(items):
        for item in items:
            yield item
            yield from walk(item.get("children", []))

    flat = list(walk(toc))
    chapter3 = next(i["chapter_id"] for i in flat if i["title"] == CHAPTER_3)
    chapter2 = next(i["chapter_id"] for i in flat if i["title"] == CHAPTER_2)
    section = next(i["id"] for i in flat if i["title"] == SECTION)
    kant = httpx.get(site.url + "/api/knowledge/v1/entities", params={"name": "Кант"}).json()
    return {
        "source": source,
        "chapter3": chapter3,
        "chapter2": chapter2,
        "section": section,
        "kant": kant[0]["id"],
    }


def open_context(browser, *, width, pinned=False, motion="reduce", theme="light"):
    """Читатель с закрытым уведомлением; окно фиксированной ширины."""
    context = browser.new_context(
        viewport={"width": width, "height": 860}, locale="ru-RU", reduced_motion=motion
    )
    state = {"version": 3, "theme": theme, "sidebarPinned": pinned, "notice": NOTICE_VERSION}
    context.add_init_script(
        f"if (!localStorage.getItem('{KEY}')) localStorage.setItem('{KEY}', "
        f"{json.dumps(json.dumps(state))});"
    )
    page = context.new_page()
    page.set_default_timeout(15000)
    aside(page)
    return context, page


def filler(n: int, prefix: str) -> list[dict]:
    return [
        {
            "type": "block",
            "id": f"p-fill-{prefix}-{i}",
            "kind": "paragraph",
            "text": f"Абзац-заполнитель {i}: рассуждение о чувственности, рассудке и опыте, "
            "которое занимает несколько строк, чтобы глава прокручивалась.",
            "lang": "ru",
            "pages": [],
            "notes": [],
            "detail": None,
            "detail_code": None,
            "page": None,
        }
        for i in range(n)
    ]


def route_chapter(page, site, ids, chapter_key: str, *, before: int = 0, after: int = 0) -> None:
    """Подменяет ответ главы: ``before`` заполнителей до настоящих блоков, ``after`` — после."""
    source, chapter = ids["source"], ids[chapter_key]
    data = httpx.get(f"{site.url}/api/v1/sources/{source}/chapters/{chapter}").json()
    real = data["blocks"]
    data["blocks"] = filler(before, "a") + real + filler(after, "b")
    page.route(f"**/sources/{source}/chapters/{chapter}", lambda r: r.fulfill(json=data))


def open_chapter(page, site, ids, chapter_key: str, title: str) -> None:
    page.goto(f"{site.url}/read/{ids['source']}/{ids[chapter_key]}")
    page.wait_for_selector(f"h1:text('{title}')")
    page.evaluate("document.fonts.ready.then(() => true)")
    aside(page)


def top_of(page, selector: str) -> float:
    return page.locator(selector).first.evaluate("el => el.getBoundingClientRect().top")


def root_px(page) -> float:
    return page.evaluate("parseFloat(getComputedStyle(document.documentElement).fontSize)")


def stored(page) -> dict:
    return json.loads(page.evaluate(f"localStorage.getItem('{KEY}')") or "null") or {}


def open_assistant(page):
    page.get_by_role("button", name="Ассистент", exact=True).first.click()
    panel = page.get_by_role("complementary", name="Ассистент")
    panel.wait_for()
    return panel


def close_assistant(page):
    page.get_by_role("button", name="Закрыть ассистента").click()
    page.locator(".side-panel").wait_for(state="detached")


# --- T45: размеры в rem без браузера ----------------------------------------------------

# Свойства, которые по 9.7 остаются в px: толщины линий, радиусы, тени, подчёркивания, сдвиги,
# штриховка и линии фоном (background-image/-size), размытие подложки.
PX_ALLOWED = re.compile(
    r"^(-webkit-)?(border[\w-]*|outline[\w-]*|[\w-]*radius|box-shadow|text-underline-offset|"
    r"text-decoration-thickness|transform|clip-path|backdrop-filter|background-image|"
    r"background-size)$"
)
STYLESHEETS = [STYLES, ROOT / "web" / "src" / "styles" / "components.css"]


def px_offenders(css: str) -> list[str]:
    """Объявления с размерами в px больше 1.5px: разбор по блокам и объявлениям ``prop: value``
    (в одной строке может быть несколько объявлений); условия ``@media`` — вне блоков."""
    text = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    offenders = []
    for block in re.findall(r"\{([^{}]*)\}", text):
        for declaration in block.split(";"):
            prop, colon, value = declaration.partition(":")
            if not colon or PX_ALLOWED.match(prop.strip()):
                continue
            sizes = re.findall(r"(?<![\w.-])-?(\d+(?:\.\d+)?)px\b", value)
            if any(float(size) > 1.5 for size in sizes):
                offenders.append(" ".join(declaration.split()))
    return offenders


def test_px_offenders_parses_declarations():
    """Разбор по объявлениям: px после разрешённого свойства в той же строке находится."""
    css = ".a { border: 1px solid; padding: 12px; } @media (min-width: 1921px) { .b { gap: 1px; } }"
    assert px_offenders(css) == ["padding: 12px"]


@req(VD, "Раскладка экрана чтения")
@pytest.mark.parametrize("sheet", STYLESHEETS, ids=lambda p: p.name)
def test_styles_sizes_in_rem(sheet):
    """T45 (Р9): размеры — в rem; px только у линий, радиусов, теней и 1px."""
    offenders = px_offenders(sheet.read_text(encoding="utf-8"))
    assert not offenders, f"размеры в px вместо rem ({sheet.name}):\n" + "\n".join(offenders)


# --- T45: плавный масштаб во всём продукте ---------------------------------------------


def library(page, site, ids):
    page.goto(site.url + "/")
    page.wait_for_selector(".source")


def graph(page, site, ids):
    page.goto(f"{site.url}/graph/{ids['kant']}?recipe=genesis")
    page.wait_for_selector(".graph-page h1")
    page.wait_for_function("() => !document.querySelector('.graph-page .loading')")


def settings(page, site, ids):
    page.goto(site.url + "/settings")
    page.wait_for_selector("h1:text('Настройки')")


def chapter(page, site, ids):
    open_chapter(page, site, ids, "chapter3", CHAPTER_3)


# Экран, его области без наложений и величины из styles.css (селектор, свойство, rem при 16px).
SCREENS = {
    "library": (
        library,
        [".sidebar", ".page"],
        [(".filters__search", "width", 22.5), (".page", "max-width", 75)],
    ),
    "graph": (graph, [".sidebar", ".graph-page"], [(".graph-recipe", "width", 15)]),
    "settings": (
        settings,
        [".sidebar", ".settings__toc", ".settings__sections"],
        [(".settings__layout", "grid-template-columns", 13.75), (".settings", "max-width", 67.5)],
    ),
    "chapter": (chapter, [".sidebar", ".toc", ".chapter", ".margin-col"], []),
}
EXPECTED_ROOT = {1280: 16.0, 1920: 16.0, 2560: 18.48}


def chapter_measure(page) -> float:
    return page.evaluate(
        "() => { const c = document.querySelector('.chapter');"
        " const el = document.createElement('span');"
        " el.style.cssText = 'position:absolute;visibility:hidden;width:1ch;"
        "font:var(--type-read-body)';"
        " document.body.appendChild(el);"
        " const ch = el.getBoundingClientRect().width; el.remove();"
        " return c.getBoundingClientRect().width / ch; }"
    )


def css_px(page, selector: str, prop: str) -> float:
    """Вычисленное значение свойства в px (первое число: у колонок сетки — первая колонка)."""
    value = page.locator(selector).first.evaluate(
        "(el, p) => getComputedStyle(el).getPropertyValue(p)", prop
    )
    match = re.search(r"-?\d+(?:\.\d+)?", value)
    assert match, (selector, prop, value)
    return float(match.group(0))


@e2e
@req(VD, "Раскладка экрана чтения")
@req(VD, "Раскладка без наложений")
@pytest.mark.parametrize("screen", list(SCREENS))
def test_scale_across_product(browser, site, ids, screen):
    """T45 (Р9, 9.7): корневой кегль по ширине окна, размеры растут вместе с ним."""
    open_screen, regions, sizes = SCREENS[screen]
    for width, expected in EXPECTED_ROOT.items():
        context, page = open_context(browser, width=width)
        try:
            open_screen(page, site, ids)
            visual.settle(page)
            root = root_px(page)
            assert abs(root - expected) <= 0.1, (screen, width, root)
            # Навигация — 3.5rem: её ширина кратна корневому кеглю.
            sidebar = visual.sidebar_width(page)
            assert abs(sidebar - 3.5 * root) <= 0.5, (screen, width, sidebar, root)
            for selector, prop, rem in sizes:
                value = css_px(page, selector, prop)
                assert abs(value - rem * root) <= 0.5, (screen, width, selector, prop, value)
            present = [s for s in regions if page.locator(s).count()]
            visual.assert_no_overlap(page, present)
            visual.assert_no_horizontal_scroll(page)
            if screen == "chapter":
                measure = chapter_measure(page)
                assert 62 - 0.5 <= measure <= 68 + 0.5, (width, measure)
            if screen == "graph":
                # Рисунок растёт с корневым кеглем (узлы, ручки, подписи), viewBox прежний;
                # шире холста он не становится (max-width: 100%).
                ratio, canvas = page.evaluate(
                    "() => { const s = document.querySelector('svg.graph');"
                    " const c = document.querySelector('.graph-canvas');"
                    " return [s.getBoundingClientRect().width / s.viewBox.baseVal.width,"
                    " c.clientWidth / s.viewBox.baseVal.width]; }"
                )
                expected_ratio = min(root / 16, canvas)
                assert abs(ratio - expected_ratio) <= 0.01, (width, ratio, expected_ratio)
                if width == 2560:
                    assert ratio > 1.1, (width, ratio)  # на 2560 граф крупнее, чем на 1920
                label = page.locator(".graph-label").first.evaluate(
                    "el => el.getBoundingClientRect().height"
                )
                assert label <= 13 * 1.6 * ratio, (width, label)  # кегль не умножен дважды
        finally:
            context.close()


# --- T5: временное сворачивание закреплённой навигации ----------------------------------


@e2e
@req(VD, "Раскладка экрана чтения")
def test_pinned_sidebar_folds_while_panel_open(browser, site, ids):
    """T5: 1440, навигация закреплена; панель открыта — 56px и «Закрепить» aria-disabled."""
    context, page = open_context(browser, width=1440, pinned=True)
    try:
        chapter(page, site, ids)
        visual.settle(page)
        assert visual.sidebar_state(page) == "pinned"
        assert round(visual.sidebar_width(page)) == 280
        open_assistant(page)
        page.wait_for_function("document.querySelector('.sidebar').dataset.state !== 'pinned'")
        visual.settle(page)
        assert round(visual.sidebar_width(page)) == 56
        pin = page.locator(".sidebar__pin")
        assert pin.get_attribute("aria-disabled") == "true"
        assert pin.get_attribute("aria-pressed") == "true"  # выбор читателя не сброшен
        visual.assert_no_overlap(page, [".sidebar", ".chapter", ".side-panel"])
        assert stored(page)["sidebarPinned"] is True
        close_assistant(page)
        page.wait_for_function("document.querySelector('.sidebar').dataset.state === 'pinned'")
        visual.settle(page)
        assert round(visual.sidebar_width(page)) == 280
        assert pin.get_attribute("aria-disabled") is None
        assert stored(page)["sidebarPinned"] is True
    finally:
        context.close()


# --- T37: колонки без анимации ширины ----------------------------------------------------

RECORD_WIDTHS = """
() => {
  window.__widths = [];
  const tick = () => {
    const c = document.querySelector('article.chapter');
    if (c) window.__widths.push(Math.round(c.getBoundingClientRect().width * 10) / 10);
    window.__rec = requestAnimationFrame(tick);
  };
  tick();
}
"""
# Свойства, у которых переход действительно длится (длительности повторяются по кругу).
TRANSITIONS = """
el => {
  const s = getComputedStyle(el);
  const props = s.transitionProperty.split(', ');
  const durs = s.transitionDuration.split(', ').map(parseFloat);
  return props.filter((p, i) => durs[i % durs.length] > 0);
}
"""


@e2e
@req(AD, "Место в тексте не теряется")
@req(VD, "Раскладка экрана чтения")
def test_columns_do_not_animate(browser, site, ids):
    """T37 (Р7): ширина колонки при открытии и закрытии панели — только два значения."""
    context, page = open_context(browser, width=1440, motion="no-preference")
    try:
        chapter(page, site, ids)
        visual.settle(page)
        # У колонок нет перехода по ширине; у панели есть появление 240ms.
        for selector in (".reader", ".toc", ".chapter", ".app-content"):
            animated = page.locator(selector).first.evaluate(TRANSITIONS)
            for prop in ("width", "flex-basis", "grid-template-columns", "all"):
                assert prop not in animated, (selector, animated)
        before = page.locator("article.chapter").evaluate("el => el.getBoundingClientRect().width")
        page.evaluate(RECORD_WIDTHS)
        open_assistant(page)
        page.wait_for_timeout(400)
        animation = page.locator(".side-panel").evaluate(
            "el => { const s = getComputedStyle(el);"
            " return [s.animationName, s.animationDuration]; }"
        )
        assert animation == ["panel-in", "0.24s"], animation
        close_assistant(page)
        page.wait_for_timeout(400)
        widths = page.evaluate("cancelAnimationFrame(window.__rec), window.__widths")
        distinct = sorted(set(widths))
        assert len(widths) > 10, widths
        assert len(distinct) == 2, f"промежуточные ширины колонки: {distinct}"
        assert before in distinct or min(abs(before - w) for w in distinct) <= 0.1
    finally:
        context.close()


# --- T4: место чтения при открытии панелей и смене ширины --------------------------------


@e2e
@req(AD, "Место в тексте не теряется")
def test_reading_place_kept(browser, site, ids):
    """T4: 20-й абзац у верха окна; ассистент, полная карточка, 1440 → 1280 — сдвиг ≤ 4px."""
    context, page = open_context(browser, width=1440)
    try:
        route_chapter(page, site, ids, "chapter3", before=19, after=30)
        chapter(page, site, ids)
        target = page.locator("p.block", has_text="догматического сна")
        mention = target.locator(".mention", has_text="Юм")
        mention.wait_for()
        index = page.evaluate(
            "() => [...document.querySelectorAll('[data-paragraph]')]"
            ".findIndex(p => p.textContent.includes('догматического сна'))"
        )
        assert index >= 19, index  # опорный абзац — не раньше 20-го
        target.evaluate(
            "el => window.scrollTo(0, window.scrollY + el.getBoundingClientRect().top - 120)"
        )
        page.wait_for_timeout(300)
        visual.settle(page)
        anchor = target.evaluate("el => el.getBoundingClientRect().top")

        def drift(step: str) -> None:
            page.wait_for_timeout(300)
            now = target.evaluate("el => el.getBoundingClientRect().top")
            assert abs(now - anchor) <= 4, f"{step}: {anchor:.0f} → {now:.0f}"

        open_assistant(page)
        drift("ассистент открыт")
        close_assistant(page)
        drift("ассистент закрыт")
        mention.click()
        card = page.get_by_role("dialog", name="Карточка")
        card.locator("h3:text('Юм')").wait_for()
        card.get_by_role("button", name="Открыть карточку").click()
        page.get_by_role("complementary", name="Карточка").wait_for()
        drift("полная карточка")
        page.set_viewport_size({"width": 1280, "height": 860})
        page.wait_for_function("document.querySelector('.reader').dataset.layout !== 'K1'")
        drift("ширина 1440 → 1280")
    finally:
        context.close()


@e2e
@req(AD, "Место в тексте не теряется")
@req(VD, "Раскладка экрана чтения")
def test_reading_place_kept_k2_to_k4_at_top(browser, site, ids):
    """T4 на 1280 (раунд 3): глава у верха окна, панель переводит K2 → K4 — заголовок и текст
    не сдвигаются (≤ 4px), хотя прокрутке некуда компенсировать; кнопка «Оглавление» над
    заголовком видна и его не задевает."""
    context, page = open_context(browser, width=1280)
    try:
        chapter(page, site, ids)
        visual.settle(page)
        assert page.evaluate("window.scrollY") == 0
        assert page.locator(".reader").get_attribute("data-layout") == "K2"
        heading = page.locator("article.chapter h1")
        first = page.locator("article.chapter [data-paragraph]").first
        before = (
            top_of(page, "article.chapter h1"),
            first.evaluate("el => el.getBoundingClientRect().top"),
        )

        def drift(step: str) -> None:
            page.wait_for_function("document.querySelector('.reader').dataset.layout === 'K4'")
            visual.settle(page)
            now = (
                heading.evaluate("el => el.getBoundingClientRect().top"),
                first.evaluate("el => el.getBoundingClientRect().top"),
            )
            assert abs(now[0] - before[0]) <= 4, f"{step}, h1: {before[0]:.0f} → {now[0]:.0f}"
            assert abs(now[1] - before[1]) <= 4, f"{step}, абзац: {before[1]:.0f} → {now[1]:.0f}"
            toc = page.locator(".toc-open").bounding_box()
            h1 = heading.bounding_box()
            assert toc and h1 and toc["y"] >= 0 and toc["y"] + toc["height"] <= h1["y"], (toc, h1)

        open_assistant(page)
        drift("ассистент открыт")
        close_assistant(page)
        page.wait_for_function("document.querySelector('.reader').dataset.layout === 'K2'")
        mention = page.locator("article.chapter .mention", has_text="Юм").first
        mention.click()
        card = page.get_by_role("dialog", name="Карточка")
        card.locator("h3:text('Юм')").wait_for()
        card.get_by_role("button", name="Открыть карточку").click()
        page.get_by_role("complementary", name="Карточка").wait_for()
        drift("полная карточка")
    finally:
        context.close()


# --- T32: слой оглавления на 1024 ---------------------------------------------------------


@e2e
@req(CR, "Оглавление")
def test_toc_layer_marks_section(browser, site, ids):
    """T32 (K3): выбор раздела в слое оглавления — раздел у верха, отмечен, фокус на заголовке."""
    context, page = open_context(browser, width=1024)
    try:
        route_chapter(page, site, ids, "chapter2", after=30)
        open_chapter(page, site, ids, "chapter2", CHAPTER_2)
        assert page.locator(".reader").get_attribute("data-layout") == "K3"
        page.locator(".rail button[aria-controls='reader-toc-layer']").click()
        layer = page.locator("#reader-toc-layer")
        layer.wait_for()
        layer.get_by_role("link", name=SECTION).click()
        layer.wait_for(state="detached")
        heading = page.locator(f"#s-{ids['section']}")
        page.wait_for_function(
            "id => document.activeElement && document.activeElement.id === id",
            arg=f"s-{ids['section']}",
        )
        top = heading.evaluate("el => el.getBoundingClientRect().top")
        padding = page.evaluate(
            "parseFloat(getComputedStyle(document.documentElement).scrollPaddingTop) || 0"
        )
        assert abs(top - padding) <= 4, (top, padding)
        # Отметка текущего места: раздел в слое оглавления — aria-current="location".
        page.locator(".rail button[aria-controls='reader-toc-layer']").click()
        layer.wait_for()
        current = layer.locator("a[aria-current='location']")
        assert current.inner_text().strip() == SECTION
    finally:
        context.close()


@e2e
@req(CR, "Оглавление")
def test_toc_marks_section_on_scroll(browser, site, ids):
    """T32 (K1): при прокрутке в оглавлении отмечен раздел у верхнего края окна."""
    context, page = open_context(browser, width=1440)
    try:
        route_chapter(page, site, ids, "chapter2", after=30)
        open_chapter(page, site, ids, "chapter2", CHAPTER_2)
        toc = page.locator("nav.toc")
        # Текущая глава — "page" всегда; выше первого раздела раздела-«location» нет.
        assert toc.locator("a[aria-current='page']").inner_text().strip() == CHAPTER_2
        assert toc.locator("a[aria-current='location']").count() == 0
        heading = page.locator(f"#s-{ids['section']}")
        heading.evaluate(
            "el => window.scrollTo(0, window.scrollY + el.getBoundingClientRect().top)"
        )
        page.wait_for_function(
            "() => { const a = document.querySelector(\"nav.toc a[aria-current='location']\");"
            f" return a && a.textContent.trim() === '{SECTION}'; }}"
        )
        assert toc.locator("a[aria-current='page']").inner_text().strip() == CHAPTER_2
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_function(
            "() => !document.querySelector(\"nav.toc a[aria-current='location']\")"
        )
    finally:
        context.close()
