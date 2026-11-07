"""chapter-reading «Сноски» и «Страницы печатного издания»: поле в K1, окно в K2–K4, плашки."""

from __future__ import annotations

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
        # Сноска на уровне своей строки: верх сноски не ниже верха знака (с каскадом).
        note_top = page.locator(".field-note").first.evaluate(
            "el => el.getBoundingClientRect().top"
        )
        sign_top = page.locator(".note-ref").first.evaluate("el => el.getBoundingClientRect().top")
        assert note_top <= sign_top + 4
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
