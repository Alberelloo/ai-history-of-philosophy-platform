"""Раскладка экрана чтения K1–K4 и режимы правой панели (visual-design «Раскладка экрана чтения»).

Проверяет фактическую раскладку в браузере: выбранный режим, ширину колонки текста в знаках
шрифта чтения, отсутствие горизонтальной прокрутки, сдвиг колонок панелью и полоску на узком
окне.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import expect

from ..helpers import reader_context

req = pytest.mark.req
VD = "visual-design"


def open_chapter(page, site) -> None:
    page.goto(f"{site.url}/read/{site.ids['textbook']}")
    page.wait_for_selector("article.chapter p.block")


def text_ch(page) -> float:
    """Ширина одного ``ch`` шрифта чтения в px — та же мера, что и в T1 документа."""
    return page.evaluate(
        "() => {"
        "  const el = document.createElement('span');"
        "  el.style.cssText = 'position:absolute;visibility:hidden;width:1ch;font:var(--type-read-body)';"
        "  document.body.appendChild(el);"
        "  const w = el.getBoundingClientRect().width;"
        "  el.remove();"
        "  return w;"
        "}"
    )


def assert_no_horizontal_scroll(page, width: int) -> None:
    scroll_w = page.evaluate("() => document.documentElement.scrollWidth")
    assert scroll_w <= width + 1, f"горизонтальная прокрутка: {scroll_w} > {width}"


@req(VD, "Раскладка экрана чтения")
def test_layout_modes_and_text_measure(browser, site):
    cases = [
        (1920, "K1"),  # оглавление + поле сносок
        (1440, "K1"),
        (1280, "K2"),  # оглавление, без поля
        (1024, "K3"),  # полоса оглавления
    ]
    for width, mode in cases:
        context = reader_context(browser, viewport={"width": width, "height": 900})
        page = context.new_page()
        try:
            open_chapter(page, site)
            expect(page.locator(".reader")).to_have_attribute("data-layout", mode)
            ch = text_ch(page)
            text_w = page.locator("article.chapter").evaluate("el => el.getBoundingClientRect().width")
            assert 62 * ch - 1 <= text_w <= 68 * ch + 1, f"{width}px: {text_w / ch:.1f}ch"
            assert_no_horizontal_scroll(page, width)
        finally:
            context.close()


@req(VD, "Раскладка экрана чтения")
def test_panel_shifts_columns_on_wide_screen(browser, site):
    context = reader_context(browser, viewport={"width": 1440, "height": 900})
    page = context.new_page()
    try:
        open_chapter(page, site)
        page.locator(".toc__assistant").click()
        page.wait_for_selector(".side-panel")
        # Панель сдвигает колонки: правый край текста не заходит под левый край панели.
        text_right = page.locator("article.chapter").evaluate("el => el.getBoundingClientRect().right")
        panel_left = page.locator(".side-panel").evaluate("el => el.getBoundingClientRect().left")
        assert text_right <= panel_left + 1, f"текст {text_right:.0f} заходит под панель {panel_left:.0f}"
        assert_no_horizontal_scroll(page, 1440)
    finally:
        context.close()


@req(VD, "Раскладка экрана чтения")
def test_panel_strip_on_narrow_screen(browser, site):
    context = reader_context(browser, viewport={"width": 1024, "height": 900})
    page = context.new_page()
    try:
        open_chapter(page, site)
        page.locator('.rail button[aria-label="Ассистент"]').click()
        page.wait_for_selector('.side-panel[data-mode="strip"]')
        # Свернуть развёрнутую полоску — появляется полоска 48px у правого края.
        page.locator(".side-panel__collapse").click()
        page.wait_for_selector(".side-panel__strip")
        box = page.locator(".side-panel__strip").bounding_box()
        assert box is not None and abs(box["x"] + box["width"] - 1024) <= 1, box
        assert_no_horizontal_scroll(page, 1024)
    finally:
        context.close()
