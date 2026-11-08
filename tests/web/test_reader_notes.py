"""chapter-reading «Сноски» и «Страницы печатного издания»: поле в K1, окно в K2–K4, плашки."""

from __future__ import annotations

import itertools

import httpx
import pytest

from ..helpers import reader_context

req = pytest.mark.req
CR = "chapter-reading"


def open_chapter(page, site):
    page.goto(f"{site.url}/read/{site.ids['textbook']}")
    page.wait_for_selector("article.chapter p.block")


@req(CR, "Сноски")
def test_footnotes_on_field_in_k1(browser, site):
    context = reader_context(browser, viewport={"width": 1920, "height": 900})
    page = context.new_page()
    try:
        open_chapter(page, site)
        page.wait_for_selector(".field-note")
        # Сноска на поле: номер и текст, без наведения.
        assert page.locator(".field-note").count() >= 1
        assert "Критика чистого разума" in page.locator(".field-note").first.inner_text()
        # Знак в тексте — ссылка на сноску на поле, не кнопка.
        sign = page.locator(".note-ref").first
        assert sign.evaluate("el => el.tagName") == "A"
        assert (sign.get_attribute("href") or "").startswith("#fn-")
        # Сноска на уровне своей строки: верх сноски не выше верха знака; ниже — только на каскад
        # (над ней номер страницы той же строки), без «↑».
        page.wait_for_timeout(100)
        note_top = page.locator(".field-note").first.evaluate(
            "el => el.getBoundingClientRect().top"
        )
        sign_top = page.locator(".note-ref").first.evaluate("el => el.getBoundingClientRect().top")
        assert sign_top - 4 <= note_top <= sign_top + 240, (note_top, sign_top)
        assert page.locator(".field-note__up").count() == 0
        # Наведение на знак подсвечивает пару.
        sign.hover()
        assert "is-active" in (page.locator(".field-note").first.get_attribute("class") or "")
    finally:
        context.close()


@req(CR, "Сноски")
def test_footnote_popup_in_compact(browser, site):
    context = reader_context(browser, viewport={"width": 1024, "height": 900})
    page = context.new_page()
    try:
        open_chapter(page, site)
        page.wait_for_selector(".note-ref")
        sign = page.locator(".note-ref").first
        # Без поля знак — кнопка, открывающая окно.
        assert sign.evaluate("el => el.tagName") == "BUTTON"
        sign.hover()
        page.wait_for_selector(".note-popup")
        assert "Критика чистого разума" in page.locator(".note-popup").first.inner_text()
    finally:
        context.close()


@req(CR, "Страницы печатного издания")
def test_page_numbers_field_vs_text(browser, site):
    # K1 (1920): номер страницы на поле, в тексте его нет.
    context = reader_context(browser, viewport={"width": 1920, "height": 900})
    page = context.new_page()
    try:
        open_chapter(page, site)
        page.wait_for_selector(".field-page")
        assert page.locator(".field-page").count() >= 1
        assert page.locator(".page-mark").count() == 0
    finally:
        context.close()
    # K3 (1024): номер страницы в тексте, поля нет.
    context = reader_context(browser, viewport={"width": 1024, "height": 900})
    page = context.new_page()
    try:
        open_chapter(page, site)
        page.wait_for_selector(".page-mark")
        assert page.locator(".page-mark").count() >= 1
        assert page.locator(".field-page").count() == 0
    finally:
        context.close()


@req(CR, "Необработанные части в тексте")
def test_unrendered_plate_localized(browser, site):
    source = site.ids["textbook"]
    toc = httpx.get(f"{site.url}/api/v1/sources/{source}/toc").json()
    chapter_id = next(i["chapter_id"] for i in toc if i["chapter_id"])
    real = httpx.get(f"{site.url}/api/v1/sources/{source}/chapters/{chapter_id}").json()
    real["blocks"].insert(
        0,
        {
            "type": "block",
            "id": "p-blank",
            "kind": "unrendered",
            "text": "",
            "lang": "ru",
            "pages": [],
            "notes": [],
            "detail": "страница 5: текст не распознан",
            "detail_code": "blank_page",
            "page": "5",
        },
    )
    for lang, expect in (
        ("ru", "Страница 5: текст не распознан"),
        ("en", "Page 5: text not recognized"),
    ):
        context = reader_context(browser, locale="en-US" if lang == "en" else "ru-RU")
        page = context.new_page()
        try:
            page.route(
                f"**/sources/{source}/chapters/{chapter_id}",
                lambda route: route.fulfill(json=real),
            )
            page.goto(f"{site.url}/read/{source}/{chapter_id}")
            figure = page.locator("figure.unrendered")
            figure.wait_for()
            assert expect in figure.inner_text()
            # Плашка — figure, не абзац; без кнопки «Спросить об абзаце»; не попадает в выделение.
            assert page.locator("figure.unrendered p.block").count() == 0
            assert page.locator("figure.unrendered .ask-selection").count() == 0
            assert figure.get_attribute("data-nontext") is not None
        finally:
            context.close()


# --- T28, T29: каскад сносок, клавиатура, номер страницы вне выделения ----------------------

LONG_NOTE = "Длинное примечание переводчика о терминах и изданиях. " * 12


def chapter_with_three_notes(site) -> tuple[str, str, dict, list[str]]:
    """Первая глава учебника, где в абзаце со сноской ещё две длинные сноски (каскад на поле)."""
    source = site.ids["textbook"]
    toc = httpx.get(f"{site.url}/api/v1/sources/{source}/toc").json()
    chapter_id = next(i["chapter_id"] for i in toc if i["chapter_id"])
    real = httpx.get(f"{site.url}/api/v1/sources/{source}/chapters/{chapter_id}").json()
    block = next(b for b in real["blocks"] if b.get("type") == "block" and b.get("notes"))
    at, first = block["notes"][0]
    end = len(block["text"])
    real["footnotes"]["n-cascade-2"] = {"marker": "2", "text": LONG_NOTE, "linked": True}
    real["footnotes"]["n-cascade-3"] = {"marker": "3", "text": LONG_NOTE, "linked": True}
    block["notes"] = [[at, first], [at + 2, "n-cascade-2"], [end, "n-cascade-3"]]
    return source, chapter_id, real, [first, "n-cascade-2", "n-cascade-3"]


def open_routed(page, site, source, chapter_id, data) -> None:
    page.route(f"**/sources/{source}/chapters/{chapter_id}", lambda r: r.fulfill(json=data))
    page.goto(f"{site.url}/read/{source}/{chapter_id}")
    page.wait_for_selector("article.chapter p.block")
    page.evaluate("document.fonts.ready.then(() => true)")


def rect(page, selector: str) -> dict:
    return page.locator(selector).first.evaluate(
        "el => { const r = el.getBoundingClientRect();"
        " return {top: r.top, bottom: r.bottom, left: r.left, right: r.right}; }"
    )


def active_id(page) -> str:
    return page.evaluate("() => document.activeElement && document.activeElement.id")


def active_has(page, cls: str) -> bool:
    return page.evaluate("c => document.activeElement.classList.contains(c)", cls)


@req(CR, "Сноски")
def test_three_notes_cascade_on_field(browser, site):
    """T28 (K1): три сноски одной строки встают каскадом без наложений; «↑» при сдвиге > 240px."""
    source, chapter_id, data, ids = chapter_with_three_notes(site)
    for width in (1920, 1440):
        context = reader_context(browser, viewport={"width": width, "height": 900})
        page = context.new_page()
        try:
            open_routed(page, site, source, chapter_id, data)
            assert page.locator(".reader").get_attribute("data-layout") == "K1"
            page.locator(f'.field-note[data-note-id="{ids[2]}"]').wait_for()
            page.wait_for_timeout(100)  # положения на поле считаются после отрисовки
            notes = [rect(page, f'.field-note[data-note-id="{i}"]') for i in ids]
            signs = [rect(page, f'a.note-ref[data-note-id="{i}"]') for i in ids]
            for i, (note, sign) in enumerate(zip(notes, signs, strict=True)):
                # Верх сноски не выше верха её строки (знак стоит в этой строке).
                assert note["top"] >= sign["top"] - 4, (width, i, note, sign)
                shift = note["top"] - sign["top"]
                up = page.locator(f'.field-note[data-note-id="{ids[i]}"] .field-note__up')
                if shift > 250:
                    assert up.count() == 1, (width, i, shift)
                elif shift < 230:
                    assert up.count() == 0, (width, i, shift)
            # Каскад: следующая сноска ниже предыдущей с промежутком 12px, без наложений.
            for upper, lower in itertools.pairwise(notes):
                assert lower["top"] >= upper["bottom"] + 11, (width, upper, lower)
            # Длинные сноски сдвигают третью ниже строки больше чем на 240px — у неё «↑».
            assert page.locator(".field-note__up").count() >= 1
            # Подсветка пары в обе стороны: знак → сноска и сноска → знак.
            page.locator(f'a.note-ref[data-note-id="{ids[1]}"]').hover()
            note_cls = page.locator(f'.field-note[data-note-id="{ids[1]}"]').get_attribute("class")
            assert "is-active" in (note_cls or "")
            page.locator(f'.field-note[data-note-id="{ids[2]}"]').hover()
            sign_cls = page.locator(f'a.note-ref[data-note-id="{ids[2]}"]').get_attribute("class")
            assert "is-active" in (sign_cls or "")
        finally:
            context.close()


@req(CR, "Сноски")
def test_field_notes_follow_width_change(browser, site):
    """T28 (K1): при смене ширины окна сноски и номера страниц пересчитываются к своим строкам."""
    context = reader_context(browser, viewport={"width": 1920, "height": 900})
    page = context.new_page()
    try:
        open_chapter(page, site)
        page.locator(".field-page").first.wait_for()
        page.set_viewport_size({"width": 1440, "height": 900})
        page.wait_for_function("document.querySelector('.reader').dataset.layout === 'K1'")
        page.wait_for_timeout(200)
        anchors = page.locator(".page-anchor")
        for i in range(anchors.count()):
            anchor = anchors.nth(i).evaluate("el => el.getBoundingClientRect().top")
            number = (
                page.locator(".field-page").nth(i).evaluate("el => el.getBoundingClientRect().top")
            )
            assert anchor - 4 <= number <= anchor + 240, (i, anchor, number)
        sign = rect(page, "a.note-ref")
        note = rect(page, ".field-note")
        assert sign["top"] - 4 <= note["top"] <= sign["top"] + 240, (sign, note)
    finally:
        context.close()


@req(CR, "Сноски")
def test_field_note_keyboard(browser, site):
    """T28 (K1): Enter на знаке — фокус на сноску на поле; Esc и Shift+Tab — обратно на знак."""
    context = reader_context(browser, viewport={"width": 1920, "height": 900})
    page = context.new_page()
    try:
        open_chapter(page, site)
        sign = page.locator("a.note-ref").first
        note_id = sign.get_attribute("data-note-id")
        sign.focus()
        page.keyboard.press("Enter")
        assert active_id(page) == f"fn-{note_id}"
        assert "is-active" in (page.locator(".field-note").first.get_attribute("class") or "")
        page.keyboard.press("Escape")
        assert active_id(page) == f"fn-ref-{note_id}"
        page.keyboard.press("Enter")
        assert active_id(page) == f"fn-{note_id}"
        page.keyboard.press("Shift+Tab")
        assert active_id(page) == f"fn-ref-{note_id}"
        # Enter не переходил по ссылке #fn-…: адрес главы прежний.
        assert "#fn-" not in page.url
    finally:
        context.close()


@req(CR, "Сноски")
def test_footnote_popup_keyboard(browser, site):
    """T28 (K2): окно сноски с клавиатуры; окно не закрывает строку знака; Esc закрывает."""
    context = reader_context(browser, viewport={"width": 1280, "height": 900})
    page = context.new_page()
    try:
        open_chapter(page, site)
        assert page.locator(".reader").get_attribute("data-layout") == "K2"
        sign = page.locator("button.note-ref").first
        sign.focus()
        popup = page.locator(".note-popup")
        popup.wait_for()
        assert sign.get_attribute("aria-expanded") == "true"
        assert popup.get_attribute("id") == sign.get_attribute("aria-controls")
        # В тексте сноски ссылка: окно — dialog. Окно ниже строки знака, а не поверх неё.
        assert popup.get_attribute("role") == "dialog"
        line = rect(page, "span.note")
        box = rect(page, ".note-popup")
        assert box["top"] >= line["bottom"] - 1, (box, line)
        # Esc на знаке закрывает окно, фокус остаётся на знаке.
        page.keyboard.press("Escape")
        assert popup.count() == 0
        assert sign.get_attribute("aria-expanded") == "false"
        assert active_has(page, "note-ref")
        # Enter переводит фокус внутрь окна; Esc из окна закрывает его и возвращает фокус на знак.
        page.keyboard.press("Enter")
        page.wait_for_function("() => document.activeElement.classList.contains('note-popup')")
        page.keyboard.press("Escape")
        assert active_has(page, "note-ref")
        page.wait_for_timeout(300)  # задержка закрытия 200ms прошла: окно не открылось снова
        assert popup.count() == 0
        assert sign.get_attribute("aria-expanded") == "false"
    finally:
        context.close()


def select_contents(page, selector: str) -> str:
    """Выделяет содержимое элемента целиком и возвращает то, что попало бы в копирование."""
    return page.evaluate(
        "s => { const r = document.createRange();"
        " r.selectNodeContents(document.querySelector(s));"
        " const sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(r);"
        " return sel.toString(); }",
        selector,
    )


@req(CR, "Страницы печатного издания")
def test_page_numbers_level_and_not_selected(browser, site):
    """T29: K1 — номер на поле на уровне строки; K2 — «с. N» в тексте; в выделение не входит."""
    context = reader_context(browser, viewport={"width": 1920, "height": 900})
    page = context.new_page()
    try:
        open_chapter(page, site)
        page.locator(".field-page").first.wait_for()
        page.wait_for_timeout(100)
        anchors = page.locator(".page-anchor")
        assert anchors.count() == page.locator(".field-page").count()
        anchor_top = anchors.first.evaluate("el => el.getBoundingClientRect().top")
        first_page = rect(page, ".field-page")
        # Номер на уровне строки, где начинается страница (рядом нет сносок, каскада нет).
        assert abs(first_page["top"] - anchor_top) <= 4, (first_page, anchor_top)
        labels = [t.strip() for t in page.locator(".field-page").all_inner_texts()]
        selected = select_contents(page, ".margin-col")
        for label in labels:
            assert label not in selected, (label, selected)
    finally:
        context.close()
    context = reader_context(browser, viewport={"width": 1280, "height": 900})
    page = context.new_page()
    try:
        open_chapter(page, site)
        mark = page.locator(".page-mark").first
        mark.wait_for()
        label = mark.get_attribute("data-page")
        assert mark.inner_text().strip() == f"с. {label}"
        assert mark.get_attribute("data-nontext") is not None
        selected = select_contents(page, "article.chapter")
        assert "Кант пишет" in selected  # выделение работает
        assert f"с. {label}" not in selected, selected
    finally:
        context.close()
