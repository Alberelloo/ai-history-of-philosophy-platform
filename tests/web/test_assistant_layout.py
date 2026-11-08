"""Раскладка диалога ассистента: сессии на виду, рабочая область на всю высоту, сообщения не
уходят под поле вопроса (reader-panels.md 5.8–5.10, решение владельца 2026-11-08).

Проверки геометрические: прямоугольники элементов в браузере на ширинах 1024–2560.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from ..assistant.browser import AskStub, answer, ask, fragment, new_session, panel
from .test_assistant_dialogs import open_book

req = pytest.mark.req
AD = "assistant-dialog"
VD = "visual-design"
SHOTS = os.environ.get("PHILOGRAPH_LAYOUT_SHOTS")

# Высокий ответ: заведомо выше области диалога на любом окне.
LONG = " ".join(f"Абзац ответа номер {i} о Канте, Юме и причинности в опыте." for i in range(120))
WIDTHS = [1024, 1280, 1440, 1920, 2560]


def open_assistant(page) -> None:
    """Кнопка «Ассистент» оглавления или его полосы (на узком окне оглавление свёрнуто)."""
    page.locator(".toc__assistant:visible, button[aria-label='Ассистент']:visible").first.click()
    box = panel(page)
    box.wait_for()
    if box.get_attribute("data-mode") == "strip":
        box.get_by_label("Вопрос ассистенту").wait_for()


def rect(locator) -> dict:
    return locator.evaluate(
        "e => { const r = e.getBoundingClientRect();"
        " return {top: r.top, bottom: r.bottom, left: r.left, right: r.right,"
        " width: r.width, height: r.height}; }"
    )


def shot(page, name: str) -> None:
    if SHOTS:
        Path(SHOTS).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(SHOTS) / f"{name}.png"))


def assert_last_message_above_input(page, box, scroller) -> None:
    """Нижний край последнего сообщения — не ниже верхнего края поля ввода; сообщения не под
    рамкой ввода, область диалога прокручивается сама и стоит внизу."""
    page.wait_for_function(
        "s => { const e = document.querySelector(s);"
        " return e && Math.abs(e.scrollHeight - e.scrollTop - e.clientHeight) < 2; }",
        arg=scroller,
    )
    last = box.locator(".turn").last
    dock = box.locator(".assistant__dock")
    field = box.get_by_label("Вопрос ассистенту")
    last_r, dock_r, field_r = rect(last), rect(dock), rect(field)
    scroll_r = rect(box.locator(".assistant__scroll"))
    assert last_r["bottom"] <= field_r["top"] + 0.5, (last_r, field_r)
    assert last_r["bottom"] <= dock_r["top"] + 0.5, (last_r, dock_r)
    # Видимая часть истории кончается над рамкой ввода: прокрутка не заходит под неё.
    assert scroll_r["bottom"] <= dock_r["top"] + 0.5, (scroll_r, dock_r)
    # Конец последнего ответа виден целиком: внутри видимой области прокрутки.
    assert last_r["bottom"] <= scroll_r["bottom"] + 0.5
    # Поле ввода не position: fixed/sticky поверх истории.
    position = box.locator(".assistant__form").evaluate("e => getComputedStyle(e).position")
    assert position == "static"


@pytest.mark.parametrize("width", WIDTHS)
@req(AD, "Раздел «Ассистент»")
@req(VD, "Раскладка без наложений")
def test_page_fills_area_and_input_never_covers_messages(page, site, width):
    """Страница «Ассистент»: сессии слева, диалог на всю высоту, поле прижато к низу; высокий
    ответ не уходит под поле."""
    page.set_viewport_size({"width": width, "height": 900})
    stub = AskStub(page)
    page.goto(f"{site.url}/assistant")
    box = page.locator(".assistant-page")
    box.wait_for()
    stub.reply(answer(fragment("Короткий ответ.", grounded=False)))
    ask(box, "Первый вопрос")
    box.locator(".copy-answer").wait_for()
    stub.reply(answer(fragment(LONG, grounded=False)))
    ask(box, "Второй вопрос с длинным ответом")
    page.wait_for_function("() => document.querySelectorAll('.copy-answer').length === 2")
    assert_last_message_above_input(page, box, ".assistant-page .assistant__scroll")
    # Страница целиком не прокручивается: прокручивается только область диалога.
    assert page.evaluate("() => document.documentElement.scrollHeight <= innerHeight + 1")
    shot(page, f"page-{width}")

    vw = page.evaluate("() => innerWidth")
    vh = page.evaluate("() => innerHeight")
    rail = rect(box.locator(".assistant__sessions-box"))
    main = rect(box.locator(".assistant__main"))
    dock = rect(box.locator(".assistant__dock"))
    thread = rect(box.locator(".assistant__thread"))
    # Колонка сессий слева от диалога, диалог доходит до правого края области.
    assert rail["right"] <= main["left"] + 1
    assert main["right"] >= vw - 48, (main, vw)
    # Поле ввода прижато к низу окна, область диалога — от заголовка до поля.
    assert dock["bottom"] >= vh - 2, (dock, vh)
    assert main["height"] >= vh * 0.7
    # Строка ответа ограничена для чтения, но без больших полей: колонка диалога занимает
    # большую часть ширины области (кроме очень широких окон, где действует предел строки).
    root = page.evaluate("() => parseFloat(getComputedStyle(document.documentElement).fontSize)")
    assert thread["width"] >= min(main["width"] - 6 * root, 68 * root) - 2, (thread, main)


@pytest.mark.parametrize("width", WIDTHS)
@req(AD, "Память диалога")
@req(VD, "Раскладка без наложений")
def test_panel_fills_height_and_input_never_covers_messages(page, site, width):
    """Панель при чтении: диалог на всю высоту панели, поле внизу, сообщения над полем."""
    page.set_viewport_size({"width": width, "height": 900})
    stub = AskStub(page)
    open_book(page, site)
    open_assistant(page)
    box = panel(page)
    stub.reply(answer(fragment("Короткий ответ.", grounded=False)))
    ask(box, "Первый вопрос")
    box.locator(".copy-answer").wait_for()
    stub.reply(answer(fragment(LONG, grounded=False)))
    ask(box, "Второй вопрос с длинным ответом")
    page.wait_for_function("() => document.querySelectorAll('.copy-answer').length === 2")
    assert_last_message_above_input(page, box, "#side-panel .assistant__scroll")
    shot(page, f"panel-{width}")

    aside = rect(box)
    dock = rect(box.locator(".assistant__dock"))
    scroller = rect(box.locator(".assistant__scroll"))
    assert dock["bottom"] >= aside["bottom"] - 1  # поле прижато к низу панели
    assert scroller["height"] >= aside["height"] * 0.4  # история — основная часть панели


@req(AD, "Память диалога")
def test_new_message_scrolls_into_view(page, site):
    """Отмотал историю вверх и задал вопрос — область диалога снова внизу, ответ виден."""
    page.set_viewport_size({"width": 1440, "height": 900})
    stub = AskStub(page)
    open_book(page, site)
    open_assistant(page)
    box = panel(page)
    stub.reply(answer(fragment(LONG, grounded=False)))
    ask(box, "Длинный")
    box.locator(".copy-answer").wait_for()
    box.locator(".assistant__scroll").evaluate("e => { e.scrollTop = 0; }")
    stub.reply(answer(fragment("Новый ответ в конце.", grounded=False)))
    ask(box, "Ещё вопрос")
    page.wait_for_function("() => document.querySelectorAll('.copy-answer').length === 2")
    assert_last_message_above_input(page, box, "#side-panel .assistant__scroll")
    assert "Новый ответ в конце." in box.locator(".turn").last.inner_text()


# --- Сессии всегда на виду ------------------------------------------------------


def seed_two_sessions(page, box, stub) -> None:
    stub.reply(answer(fragment("Первый ответ.", grounded=False)))
    ask(box, "Вопрос о причинности")
    box.locator(".copy-answer").wait_for()
    new_session(box)


@req(AD, "Раздел «Ассистент»")
def test_sessions_always_visible_on_page(page, site):
    """На странице список сессий — постоянная колонка: после «+» старая сессия видна, у строк
    название и дата, активная отмечена, переключение одним щелчком."""
    page.set_viewport_size({"width": 1440, "height": 900})
    stub = AskStub(page)
    page.goto(f"{site.url}/assistant")
    box = page.locator(".assistant-page")
    box.wait_for()
    sessions = box.get_by_role("list", name="Сессии", exact=True)
    assert sessions.is_visible()
    # Кнопки «Сессии» нет: список не прячется.
    assert box.get_by_role("button", name="Сессии", exact=True).count() == 0
    seed_two_sessions(page, box, stub)
    rows = sessions.locator(".assistant__session")
    assert rows.count() == 2
    new_row, old_row = rows.nth(0), rows.nth(1)
    assert new_row.get_attribute("aria-current") == "true"
    assert "Новая сессия" in new_row.inner_text()
    assert "Вопрос о причинности" in old_row.inner_text()
    # Дата «8 нояб., 14:32» у каждой строки.
    date = re.compile(r"\d{1,2} [а-я]+\.?,? \d{2}:\d{2}")
    for i in range(2):
        assert date.search(rows.nth(i).locator(".assistant__session-meta").inner_text())
    rail = rect(box.locator(".assistant__sessions-box"))
    main = rect(box.locator(".assistant__main"))
    assert rail["right"] <= main["left"] + 1  # колонка слева от диалога
    # Один щелчок — переключение; список остаётся на виду.
    old_row.locator(".assistant__session-title").click()
    assert sessions.is_visible()
    assert "Вопрос о причинности" in box.locator(".turns").inner_text()
    active = sessions.locator(".assistant__session[aria-current=true]")
    assert active.count() == 1 and "Вопрос о причинности" in active.inner_text()
    # Пустая сессия, с которой ушли, удалилась сама (5.8).
    assert rows.count() == 1


@req(AD, "Память диалога")
def test_sessions_always_visible_in_panel_and_collapse(page, site):
    """В панели книги список виден сразу (≥1280); «Сессии» сворачивает его до строки активной
    сессии; на узком окне (<1280) он свёрнут, но активная сессия и число видны."""
    page.set_viewport_size({"width": 1440, "height": 900})
    stub = AskStub(page)
    open_book(page, site)
    open_assistant(page)
    box = panel(page)
    toggle = box.get_by_role("button", name="Сессии", exact=True)
    sessions = box.get_by_role("list", name="Сессии", exact=True)
    assert toggle.get_attribute("aria-expanded") == "true" and sessions.is_visible()
    seed_two_sessions(page, box, stub)
    rows = sessions.locator(".assistant__session")
    assert rows.count() == 2  # после «+» старая сессия на виду
    assert "Вопрос о причинности" in rows.nth(1).inner_text()
    assert rows.nth(0).get_attribute("aria-current") == "true"
    # Сессии — над историей, под шапкой; история всё равно основная часть панели.
    assert (
        rect(box.locator(".assistant__sessions-box"))["bottom"]
        <= rect(box.locator(".assistant__scroll"))["top"] + 1
    )
    rows.nth(1).locator(".assistant__session-title").click()
    assert "Вопрос о причинности" in box.locator(".turns").inner_text()
    assert sessions.is_visible()
    # Esc в списке сворачивает его, фокус — на «Сессии» (10.4); панель остаётся открытой.
    sessions.locator(".assistant__session-title").first.focus()
    page.keyboard.press("Escape")
    assert sessions.count() == 0 and box.is_visible()
    assert toggle.evaluate("e => e === document.activeElement")
    assert toggle.get_attribute("aria-expanded") == "false"
    current = box.locator(".assistant__sessions-current")
    assert "Вопрос о причинности" in current.inner_text()
    toggle.click()
    assert sessions.is_visible()
    # Узкое окно: панель в полоске, список свёрнут по умолчанию, активная сессия видна.
    page.set_viewport_size({"width": 1100, "height": 800})
    page.reload()
    page.wait_for_selector(".chapter [data-paragraph]")
    open_assistant(page)
    box = panel(page)
    toggle = box.get_by_role("button", name="Сессии", exact=True)
    assert toggle.get_attribute("aria-expanded") == "false"
    assert "Вопрос о причинности" in box.locator(".assistant__sessions-current").inner_text()
    toggle.click()
    assert box.get_by_role("list", name="Сессии", exact=True).is_visible()


@req(AD, "Память диалога")
def test_rename_returns_focus_to_rename_button(page, site):
    """10.4: Enter и Esc в поле переименования возвращают фокус на «Переименовать» строки."""
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{site.url}/assistant")
    box = page.locator(".assistant-page")
    box.wait_for()
    rename = box.get_by_role("button", name=re.compile("^Переименовать"))
    rename.click()
    field = box.get_by_label("Название сессии")
    field.fill("Черновик")
    field.press("Enter")
    rename = box.get_by_role("button", name="Переименовать: Черновик")
    assert rename.evaluate("e => e === document.activeElement")
    rename.click()
    box.get_by_label("Название сессии").press("Escape")
    assert rename.evaluate("e => e === document.activeElement")
