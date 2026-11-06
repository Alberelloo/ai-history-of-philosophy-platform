"""Сквозные тесты оформления (visual-design): проверки по DOM и снимки основных экранов.

Свой стенд на модуль: снимки не зависят от того, что поменяли другие сценарии (например,
отклонённое на проверке утверждение исчезает из графа). Эталоны снимков —
``tests/e2e/visual/baselines/<платформа>/``; обновление — ``PHILOGRAPH_UPDATE_SNAPSHOTS=1``
(одной командой: ``python scripts/visual_check.py --update``).
"""

from __future__ import annotations

import json
import os

import httpx
import pytest

from . import visual
from .conftest import NOTICE_VERSION, TEST_RATE_BURST

req = pytest.mark.req
VD = "visual-design"
pytestmark = pytest.mark.e2e
KEY = "philograph:v2"
TEXTBOOK = "Теория познания: демонстрационный учебник"
LIGHT_PAPER, DARK_PAPER = "#eff1ec", "#13171e"


@pytest.fixture(scope="module")
def site(request, tmp_path_factory):
    if os.environ.get("PHILOGRAPH_E2E_URL"):
        yield request.getfixturevalue("stack")
        return
    from pathlib import Path

    if not (Path(__file__).resolve().parents[2] / "web" / "dist" / "index.html").exists():
        pytest.skip("клиент не собран: npm run build в web/")
    import dev_stack

    os.environ.setdefault("PHILOGRAPH_RATE_BURST", TEST_RATE_BURST)
    running = dev_stack.start(tmp_path_factory.mktemp("visual-stack"))
    yield running
    running.stop()


@pytest.fixture(scope="module")
def ids(site) -> dict[str, str]:
    source = httpx.get(site.url + "/api/v1/current").json()["source_id"]
    toc = httpx.get(f"{site.url}/api/v1/sources/{source}/toc").json()
    chapter = next(i["chapter_id"] for i in toc if i["title"] == "Глава 3. Ответ Канта")
    kant = httpx.get(site.url + "/api/knowledge/v1/entities", params={"name": "Кант"}).json()
    return {"source": source, "chapter": chapter, "kant": kant[0]["id"]}


def open_context(browser, *, theme="light", width=1280, lang=None, accepted=True, **options):
    """Страница читателя: фиксированное окно, без движения, с выбранной темой и языком."""
    options.setdefault("locale", "ru-RU")
    options.setdefault("reduced_motion", "reduce")
    context = browser.new_context(viewport={"width": width, "height": 860}, **options)
    state = {"version": 2, "theme": theme}
    if accepted:
        state["notice"] = NOTICE_VERSION
    if lang:
        state["lang"] = lang
    context.add_init_script(
        f"if (!localStorage.getItem('{KEY}')) localStorage.setItem('{KEY}', "
        f"{json.dumps(json.dumps(state))});"
    )
    page = context.new_page()
    page.set_default_timeout(15000)
    return context, page


# --- экраны ---------------------------------------------------------------------------


def library(page, site, ids):
    page.goto(site.url + "/")
    page.wait_for_selector(".source")


def chapter(page, site, ids):
    page.goto(f"{site.url}/read/{ids['source']}/{ids['chapter']}")
    page.wait_for_selector("h1:text('Глава 3. Ответ Канта')")
    page.locator(".mention").first.wait_for()
    page.locator(".topbar__link--source").wait_for()


def card(page, site, ids):
    chapter(page, site, ids)
    page.locator("p.block", has_text="догматического сна").locator(
        ".mention", has_text="Юм"
    ).click()
    popup = page.get_by_role("dialog", name="Карточка")
    popup.locator("h3:text('Юм')").wait_for()
    popup.locator(".card-description").wait_for()
    page.wait_for_function(
        "() => { const d = document.querySelector('.card-description');"
        " return d && d.textContent.trim().endsWith('.'); }"
    )


def assistant(page, site, ids):
    chapter(page, site, ids)
    page.get_by_role("button", name="Ассистент", exact=True).click()
    panel = page.get_by_role("complementary", name="Ассистент")
    panel.get_by_label("Вопрос ассистенту").fill("что Кант взял у Юма?")
    panel.get_by_role("button", name="Спросить").click()
    panel.locator(".copy-answer").wait_for()


def graph(page, site, ids):
    # Выбранный учебник — для подписи источника в верхней панели и пометок «есть в учебнике».
    page.goto(f"{site.url}/read/{ids['source']}/{ids['chapter']}")
    page.wait_for_selector(".chapter p")
    page.goto(f"{site.url}/graph/{ids['kant']}?recipe=genesis")
    page.wait_for_selector("h1:text('Генезис: Кант')")
    page.wait_for_function(
        "() => document.querySelectorAll('.graph-edge').length >= 3"
        " && !document.querySelector('.graph-page .loading')"
    )
    page.get_by_role("button", name="Кант — испытал влияние — Юм").click()
    page.get_by_role("region", name="Связь").wait_for()
    page.mouse.move(0, 0)


def settings(page, site, ids):
    page.goto(site.url + "/settings")
    page.wait_for_selector("h1:text('Настройки')")


SCREENS = {
    "library": library,
    "chapter": chapter,
    "card": card,
    "assistant": assistant,
    "graph": graph,
    "settings": settings,
}


def check_screen(page, theme: str) -> None:
    """Проверки по DOM на любом экране."""
    visual.settle(page)
    visual.assert_color(page, "body", "backgroundColor", "paper")
    visual.assert_color(page, "body", "color", "ink")
    assert visual.token(page, "paper") == (LIGHT_PAPER if theme == "light" else DARK_PAPER)
    assert not visual.unstyled_buttons(page), visual.unstyled_buttons(page)
    visual.assert_no_horizontal_scroll(page)
    visual.assert_contrast(page)


# --- требования -----------------------------------------------------------------------


@req(VD, "Токены оформления")
@req(VD, "Компоненты дизайн-системы")
@req(VD, "Визуальная проверка")
@req(VD, "Доступность оформления")
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_main_screens_in_both_themes(browser, site, ids, theme):
    """Основные экраны: токены, оформленные кнопки, контраст и снимки при 1280."""
    for name, open_screen in SCREENS.items():
        context, page = open_context(browser, theme=theme)
        try:
            open_screen(page, site, ids)
            check_screen(page, theme)
            visual.snap(page, f"{name}-{theme}-1280")
        finally:
            context.close()


@req(VD, "Раскладка без наложений")
@req(VD, "Визуальная проверка")
@pytest.mark.parametrize("width", visual.WIDTHS)
def test_layout_at_supported_widths(browser, site, ids, width):
    """Чтение и библиотека: без прокрутки по горизонтали, наложений и обрезанного текста."""
    context, page = open_context(browser, width=width)
    try:
        chapter(page, site, ids)
        visual.settle(page)
        visual.assert_no_horizontal_scroll(page)
        visual.assert_no_overlap(page, [".topbar", ".toc", ".chapter"])
        visual.assert_no_overlap(page, [".topbar__brand", ".topbar__nav", ".topbar__tools"])
        visual.assert_no_clipped_text(page)
        measure = page.evaluate(
            "() => { const c = document.querySelector('.chapter');"
            " const ch = parseFloat(getComputedStyle(c).fontSize) * 0.5;"
            " return c.getBoundingClientRect().width / ch; }"
        )
        assert measure >= 60, f"колонка текста уже 60 знаков: {measure:.0f}"
        if width != 1280:
            visual.snap(page, f"chapter-light-{width}")
        library(page, site, ids)
        visual.settle(page)
        visual.assert_no_horizontal_scroll(page)
        visual.assert_no_clipped_text(page)
        visual.assert_fills_width(page, ".sources")
        if width == 1024:
            dark, dark_page = open_context(browser, theme="dark", width=width)
            try:
                for name in ("chapter", "card", "assistant", "graph"):
                    SCREENS[name](dark_page, site, ids)
                    check_screen(dark_page, "dark")
                    visual.snap(dark_page, f"{name}-dark-{width}")
            finally:
                dark.close()
    finally:
        context.close()


@req(VD, "Шрифты")
def test_fonts_served_by_site(browser, site, ids):
    context, page = open_context(browser)
    hosts: list[str] = []
    page.on("request", lambda r: hosts.append(httpx.URL(r.url).host))
    try:
        chapter(page, site, ids)
        visual.settle(page)
        families = visual.loaded_families(page)
        assert "Literata Variable" in families and "Onest" in families, families
        assert visual.font_family(page, "p.block").startswith('"Literata Variable"')
        assert visual.font_family(page, ".chapter h1").startswith('"Literata Variable"')
        assert visual.font_family(page, ".toc__assistant").startswith("Onest")
        assert page.evaluate("document.fonts.check('19px \"Literata Variable\"')")
        assert page.evaluate("document.fonts.check('500 14px Onest')")
        site_host = httpx.URL(site.url).host
        assert set(hosts) == {site_host}, set(hosts)
        assert "fonts.googleapis.com" not in hosts
    finally:
        context.close()


@req(VD, "Тема")
def test_dark_theme_chosen_and_kept(browser, site, ids):
    context, page = open_context(browser, theme="system")
    try:
        library(page, site, ids)
        visual.assert_color(page, "body", "backgroundColor", "paper")
        assert visual.token(page, "paper") == LIGHT_PAPER
        page.get_by_role("group", name="Тема").get_by_role("button", name="Тёмная").click()
        visual.settle(page)
        assert page.evaluate("document.documentElement.dataset.theme") == "dark"
        assert visual.token(page, "paper") == DARK_PAPER
        visual.assert_color(page, "body", "backgroundColor", "paper")
        visual.assert_contrast(page)
        page.reload()
        page.wait_for_selector(".source")
        visual.settle(page)
        assert visual.token(page, "paper") == DARK_PAPER
        settings(page, site, ids)
        main = page.get_by_role("main")
        assert main.get_by_role("button", name="Тёмная").get_attribute("aria-pressed") == "true"
        main.get_by_role("button", name="Светлая").click()
        visual.settle(page)
        assert visual.token(page, "paper") == LIGHT_PAPER
        assert json.loads(page.evaluate(f"localStorage.getItem('{KEY}')"))["theme"] == "light"
    finally:
        context.close()


@req(VD, "Тема")
def test_theme_applied_before_first_paint(browser, site, ids):
    """Тема ставится скриптом в <head> до загрузки приложения: без мигания светлой темой."""
    html = httpx.get(site.url + "/").text
    head = html.split("</head>")[0]
    assert KEY in head and head.index(KEY) < html.index('type="module"')
    context, page = open_context(browser, theme="dark")
    try:
        # Приложение не загружается вовсе, а страница уже в тёмной теме.
        page.route("**/assets/*.js", lambda route: route.abort())
        page.goto(site.url + "/")
        page.wait_for_load_state("load")
        assert page.evaluate("document.documentElement.dataset.theme") == "dark"
        assert visual.token(page, "paper") == DARK_PAPER
        assert page.evaluate("document.documentElement.lang") == "ru"
    finally:
        context.close()


@req(VD, "Тема")
def test_system_theme_follows_os(browser, site, ids):
    context, page = open_context(browser, theme="system", color_scheme="dark")
    try:
        library(page, site, ids)
        assert page.evaluate("document.documentElement.hasAttribute('data-theme')") is False
        assert visual.token(page, "paper") == DARK_PAPER
        visual.assert_color(page, "body", "backgroundColor", "paper")
        group = page.get_by_role("group", name="Тема")
        assert group.get_by_role("button", name="Как в системе").get_attribute("aria-pressed") == (
            "true"
        )
    finally:
        context.close()


@req(VD, "Язык интерфейса")
def test_english_interface(browser, site, ids):
    context, page = open_context(browser)
    try:
        chapter(page, site, ids)
        # Абзац без номера страницы: «с. 45» — подпись интерфейса и переводится.
        text = page.locator("p.block", has_text="Ответ Канта Юму")
        paragraph = text.inner_text()
        page.get_by_role("group", name="Язык интерфейса").get_by_role("button", name="EN").click()
        nav = page.get_by_role("navigation", name="Sections")
        assert nav.get_by_role("link", name="Library").is_visible()
        assert nav.get_by_role("link", name="Settings").is_visible()
        assert page.get_by_role("button", name="Assistant", exact=True).is_visible()
        assert page.get_by_role("navigation", name="Chapters").is_visible()
        assert page.evaluate("document.documentElement.lang") == "en"
        assert text.inner_text() == paragraph  # текст источника не переводится
        page.reload()
        page.wait_for_selector(".chapter p")
        assert page.evaluate("document.documentElement.lang") == "en"
        nav.get_by_role("link", name="Settings").click()
        page.wait_for_selector("h1:text('Settings')")
        assert page.get_by_role("main").get_by_role("button", name="EN", exact=True).get_attribute(
            "aria-pressed"
        ) == ("true")
        visual.snap(page, "settings-en-light-1280")
    finally:
        context.close()


@req(VD, "Язык интерфейса")
def test_language_follows_browser_by_default(browser, site, ids):
    context, page = open_context(browser, locale="en-US")
    try:
        library(page, site, ids)
        assert page.evaluate("document.documentElement.lang") == "en"
        assert page.get_by_role("heading", name="Library").is_visible()
        group = page.get_by_role("group", name="Interface language")
        assert group.get_by_role("button", name="EN").get_attribute("aria-pressed") == "true"
    finally:
        context.close()


@req(VD, "Верхняя панель")
def test_top_bar_on_every_screen(browser, site, ids):
    context, page = open_context(browser, width=1024)
    try:
        paths = [
            "/",
            f"/read/{ids['source']}/{ids['chapter']}",
            "/settings",
            f"/graph/{ids['kant']}?recipe=genesis",
            "/p/missing-paragraph",
            "/internal/review",
        ]
        for path in paths:
            page.goto(site.url + path)
            bar = page.locator(".topbar")
            bar.wait_for()
            page.get_by_role("main").or_(page.locator(".reader")).first.wait_for()
            box = bar.bounding_box()
            assert box and round(box["height"]) == 56, (path, box)
            assert bar.get_by_role("link", name="PhiloGraph, библиотека").is_visible()
            assert bar.get_by_role("group", name="Язык интерфейса").is_visible()
            assert bar.get_by_role("group", name="Тема").is_visible()
            visual.assert_color(page, ".topbar", "backgroundColor", "paper")
        chapter(page, site, ids)
        visual.settle(page)
        nav = page.get_by_role("navigation", name="Разделы")
        assert nav.get_by_role("link").all_inner_texts() == ["Библиотека", TEXTBOOK, "Настройки"]
        visual.assert_separated(page, ".topbar__link")
        visual.assert_separated(page, ".topbar__tools > *")
        visual.assert_no_overlap(page, [".topbar__brand", ".topbar__nav", ".topbar__tools"])
        visual.assert_no_clipped_text(page)
        page.mouse.wheel(0, 600)
        page.wait_for_timeout(200)
        assert bar.bounding_box()["y"] == 0  # панель закреплена
    finally:
        context.close()


@req(VD, "Компоненты дизайн-системы")
@req(VD, "Доступность оформления")
def test_keyboard_focus_ring(browser, site, ids):
    context, page = open_context(browser)
    try:
        library(page, site, ids)
        visual.settle(page)
        seen = []
        for _ in range(14):
            seen.append(visual.assert_focus_ring(page))
        tags = {s["tag"] for s in seen}
        assert {"A", "BUTTON", "INPUT"} <= tags, seen
        settings(page, site, ids)
        page.locator("body").click(position={"x": 5, "y": 300})
        on_settings = [visual.assert_focus_ring(page) for _ in range(16)]
        assert any("pg-switch__input" in s["cls"] for s in on_settings), on_settings
    finally:
        context.close()


@req(VD, "Доступность оформления")
def test_reduced_motion_keeps_only_fade(browser, site, ids):
    for motion, expected in (("reduce", "pg-fade"), ("no-preference", "pg-pop-in")):
        context, page = open_context(browser, reduced_motion=motion)
        try:
            card(page, site, ids)
            animation = page.evaluate(
                "() => { const s = getComputedStyle(document.querySelector('.card-popup'));"
                " return [s.animationName, parseFloat(s.animationDuration) * 1000]; }"
            )
            assert animation[0] == expected, animation
            if motion == "reduce":
                assert animation[1] <= 120, animation
        finally:
            context.close()


@req(VD, "Визуальная проверка")
def test_first_run_notice_snapshot(browser, site, ids):
    context, page = open_context(browser, accepted=False)
    try:
        library(page, site, ids)
        page.get_by_role("dialog", name="О пометках и обработке вопросов").wait_for()
        check_screen(page, "light")
        visual.snap(page, "notice-light-1280")
    finally:
        context.close()
