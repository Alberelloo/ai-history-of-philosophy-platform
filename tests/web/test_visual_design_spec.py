"""visual-design: сценарии и нормативные правила, которых не хватало существующим тестам.

Проверки по DOM и по сравнению снимков: у оформления нет события журнала, поэтому
``nolog`` с причиной. Стенд — модульный ``site`` из ``tests/web/conftest.py``.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import expect

from ..e2e import visual
from ..helpers import reader_context

req = pytest.mark.req
VD = "visual-design"
NOLOG = "оформление: проверка по DOM и снимкам, у неё нет события журнала"


def open_chapter(page, site) -> None:
    page.goto(f"{site.url}/read/{site.ids['textbook']}")
    page.wait_for_selector("article.chapter p.block")
    visual.settle(page)


def make_page(browser, width: int, height: int = 900, **options):
    context = reader_context(browser, viewport={"width": width, "height": height}, **options)
    return context, context.new_page()


def ch_px(page) -> float:
    return page.evaluate(
        "() => { const el = document.createElement('span');"
        " el.style.cssText = 'position:absolute;visibility:hidden;width:1ch;"
        "font:var(--type-read-body)'; document.body.appendChild(el);"
        " const w = el.getBoundingClientRect().width; el.remove(); return w; }"
    )


def rect(page, selector: str) -> dict:
    return page.locator(selector).first.evaluate(
        "el => { const r = el.getBoundingClientRect();"
        " return {left: r.left, right: r.right, top: r.top, bottom: r.bottom,"
        " width: r.width, height: r.height}; }"
    )


def present(page, selector: str) -> bool:
    """Колонка есть на экране: найдена и ширина больше нуля (пустое поле сносок не видно по
    высоте, но место под него занято)."""
    return page.locator(selector).count() > 0 and rect(page, selector)["width"] > 0


def open_assistant_panel(page) -> None:
    page.locator(".toc__assistant").click()
    page.wait_for_selector(".side-panel")


# --- Раскладка экрана чтения ----------------------------------------------------------


@req(VD, "Раскладка экрана чтения", scenario="Состав раскладок", nolog=NOLOG)
@pytest.mark.parametrize(("width", "mode"), [(1920, "K1"), (1280, "K2"), (1024, "K3"), (800, "K4")])
def test_layout_composition(browser, site, width, mode):
    context, page = make_page(browser, width)
    try:
        open_chapter(page, site)
        expect(page.locator(".reader")).to_have_attribute("data-layout", mode)
        shown = {
            "toc": present(page, ".toc"),
            "rail": present(page, ".rail"),
            "margin": present(page, ".margin-col"),
            "toc_button": page.locator(".toc-open").is_visible(),
        }
        expected = {
            "K1": {"toc": True, "rail": False, "margin": True, "toc_button": False},
            "K2": {"toc": True, "rail": False, "margin": False, "toc_button": False},
            "K3": {"toc": False, "rail": True, "margin": False, "toc_button": False},
            "K4": {"toc": False, "rail": False, "margin": False, "toc_button": True},
        }[mode]
        assert shown == expected, (mode, shown)
        assert page.locator("article.chapter").is_visible()
    finally:
        context.close()


@req(VD, "Раскладка экрана чтения", scenario="Колонка текста в пределах меры", nolog=NOLOG)
@pytest.mark.parametrize("width", [1024, 1280, 1440, 1920, 2560])
def test_text_measure_within_62_68_ch(browser, site, width):
    context, page = make_page(browser, width)
    try:
        open_chapter(page, site)
        measure = rect(page, "article.chapter")["width"] / ch_px(page)
        assert 62 - 0.1 <= measure <= 68 + 0.1, f"{width}px: {measure:.2f}ch"
    finally:
        context.close()


@req(VD, "Раскладка экрана чтения", scenario="Оглавление важнее поля", nolog=NOLOG)
def test_toc_stays_when_margin_dropped(browser, site):
    context, page = make_page(browser, 1600)
    try:
        open_chapter(page, site)
        expect(page.locator(".reader")).to_have_attribute("data-layout", "K1")
        assert present(page, ".margin-col") and present(page, ".toc")
        open_assistant_panel(page)
        expect(page.locator(".reader")).to_have_attribute("data-layout", "K2")
        assert present(page, ".toc")
        assert not present(page, ".margin-col")
        # Сноски — во всплывающих окнах.
        page.locator(".note-ref").first.hover()
        expect(page.get_by_text("Критика чистого разума, B XXVI", exact=False)).to_be_visible()
    finally:
        context.close()


@req(VD, "Раскладка экрана чтения", scenario="Панель сдвигает колонки", nolog=NOLOG)
@req(VD, "Раскладка без наложений", scenario="Открытая панель", nolog=NOLOG)
@pytest.mark.parametrize("width", [1280, 1440, 1920])
def test_panel_shifts_columns_without_overlap(browser, site, width):
    context, page = make_page(browser, width)
    try:
        open_chapter(page, site)
        before = max(
            rect(page, s)["right"] for s in (".margin-col", "article.chapter") if present(page, s)
        )
        open_assistant_panel(page)
        visual.settle(page)
        panel = rect(page, ".side-panel")
        assert panel["width"] == pytest.approx(448, abs=1) and panel["right"] == width
        assert before > panel["left"]  # без сдвига колонки зашли бы под панель
        # Колонки пересчитаны: вся рабочая область слева от панели.
        after = max(
            rect(page, s)["right"] for s in (".margin-col", "article.chapter") if present(page, s)
        )
        assert after <= panel["left"] + 1, (after, panel)
        # Колонка текста не заходит под панель и держит запас 24px.
        assert rect(page, "article.chapter")["right"] <= panel["left"] - 24 + 1
        visual.assert_no_horizontal_scroll(page)
        columns = [
            s
            for s in (".sidebar", ".toc", ".rail", "article.chapter", ".margin-col", ".side-panel")
            if present(page, s)
        ]
        visual.assert_no_overlap(page, columns)
    finally:
        context.close()


@req(VD, "Раскладка экрана чтения", scenario="Панель сдвигает колонки", nolog=NOLOG)
def test_columns_recalculated_in_one_step(browser, site):
    context, page = make_page(browser, 1440)
    try:
        open_chapter(page, site)
        page.evaluate(
            "() => { window.__w = []; const tick = () => {"
            " const c = document.querySelector('article.chapter');"
            " window.__w.push(Math.round(c.getBoundingClientRect().width * 10) / 10);"
            " window.__raf = requestAnimationFrame(tick); }; tick(); }"
        )
        open_assistant_panel(page)
        visual.settle(page)
        widths = page.evaluate("() => { cancelAnimationFrame(window.__raf); return window.__w; }")
        assert len(set(widths)) <= 2, sorted(set(widths))
    finally:
        context.close()


@req(VD, "Раскладка экрана чтения", scenario="Полоска справа", nolog=NOLOG)
@pytest.mark.parametrize("width", [1024, 1279])
def test_strip_on_narrow_window(browser, site, width):
    context, page = make_page(browser, width, reduced_motion="reduce")
    try:
        open_chapter(page, site)
        mode = page.locator(".reader").get_attribute("data-layout")
        page.locator('.rail button[aria-label="Ассистент"], .toc__assistant').first.click()
        page.wait_for_selector('.side-panel[data-mode="strip"]')
        page.locator(".side-panel__collapse").click()
        page.wait_for_selector(".side-panel__strip")
        visual.settle(page)
        text_before = rect(page, "article.chapter")
        strip = rect(page, ".side-panel__strip")
        assert strip["width"] == pytest.approx(48, abs=1), strip
        assert strip["right"] == pytest.approx(width, abs=1), strip
        assert strip["top"] == pytest.approx(0, abs=1)
        assert strip["height"] == pytest.approx(900, abs=1)
        assert page.locator(".reader").get_attribute("data-layout") == mode
        # Щелчок разворачивает панель 448px поверх правой части текста; раскладка прежняя.
        page.locator(".side-panel__strip").click()
        page.wait_for_selector(".side-panel:not(:has(.side-panel__strip))")
        visual.settle(page)
        panel = rect(page, ".side-panel")
        assert panel["width"] == pytest.approx(448, abs=1), panel
        assert panel["right"] == pytest.approx(width, abs=1), panel
        assert panel["left"] < rect(page, "article.chapter")["right"]  # лежит над текстом
        assert page.locator(".reader").get_attribute("data-layout") == mode
        assert rect(page, "article.chapter") == text_before
        visual.assert_no_horizontal_scroll(page)
    finally:
        context.close()


# --- Визуальная проверка ----------------------------------------------------------------


class _FakePage:
    """Страница-заглушка для ``visual.snap``: экран — готовый файл."""

    viewport_size = {"width": 10, "height": 10}

    def __init__(self, image) -> None:
        self.image = image

    def screenshot(self, *, path, **options) -> None:
        self.image.save(path)

    def locator(self, selector):
        return selector


@req(
    VD,
    "Визуальная проверка",
    invariant="эталоны обновляются только явной командой",
    nolog=NOLOG,
)
def test_baselines_written_only_on_explicit_update(tmp_path, monkeypatch):
    from PIL import Image

    monkeypatch.setattr(visual, "settle", lambda *a, **k: None)
    monkeypatch.setattr(visual, "RESULTS", tmp_path / "results")
    monkeypatch.setattr(visual, "BASELINES", tmp_path / "baselines")
    monkeypatch.setattr(visual, "UPDATE", False)
    red = Image.new("RGB", (40, 40), (200, 0, 0))
    blue = Image.new("RGB", (40, 40), (0, 0, 200))
    baseline = tmp_path / "baselines" / "screen.png"

    assert visual.snap(_FakePage(red), "screen") is None  # эталона нет: ничего не пишется
    assert not baseline.exists()

    monkeypatch.setattr(visual, "UPDATE", True)
    assert visual.snap(_FakePage(red), "screen") == 0.0  # явная команда пишет эталон
    original = baseline.read_bytes()

    monkeypatch.setattr(visual, "UPDATE", False)
    with pytest.raises(visual.SnapshotMismatch):  # расхождение эталон не перезаписывает
        visual.snap(_FakePage(blue), "screen")
    assert baseline.read_bytes() == original


@req(
    VD,
    "Визуальная проверка",
    invariant="явная команда обновления — только переменная окружения",
    nolog=NOLOG,
)
def test_update_flag_comes_only_from_environment(monkeypatch):
    import importlib

    monkeypatch.delenv("PHILOGRAPH_UPDATE_SNAPSHOTS", raising=False)
    try:
        assert importlib.reload(visual).UPDATE is False
        monkeypatch.setenv("PHILOGRAPH_UPDATE_SNAPSHOTS", "1")
        assert importlib.reload(visual).UPDATE is True
    finally:
        monkeypatch.undo()
        importlib.reload(visual)


# --- Проверки по DOM не пустые ------------------------------------------------------------


@req(VD, "Доступность оформления", scenario="Контраст", nolog=NOLOG)
def test_contrast_check_flags_low_contrast(browser, site):
    """Проверка контраста видит испорченный текст (иначе «все экраны проходят» ничего не значит)."""
    context, page = make_page(browser, 1280)
    try:
        open_chapter(page, site)
        assert visual.low_contrast(page) == []
        page.add_style_tag(content="article.chapter p.block { color: #c8c8c8 !important; }")
        found = visual.low_contrast(page)
        assert found
        assert all(item["ratio"] < 4.5 for item in found), found
    finally:
        context.close()


@req(VD, "Компоненты дизайн-системы", scenario="Кнопки", nolog=NOLOG)
def test_unstyled_button_is_flagged(browser, site):
    context, page = make_page(browser, 1280)
    try:
        open_chapter(page, site)
        assert visual.unstyled_buttons(page) == []
        page.evaluate(
            "() => { const b = document.createElement('button'); b.textContent = 'x';"
            " document.body.appendChild(b); }"
        )
        assert len(visual.unstyled_buttons(page)) == 1
    finally:
        context.close()
