"""Требование document-structure «Оглавление источника»: структура PDF по закладкам.

Цифровой PDF с оглавлением-закладками (`doc.get_toc`) должен разбиваться на главы по закладкам,
а не по размеру шрифта. Расхождения между закладками и текстом — предупреждения.
"""

from __future__ import annotations

import pytest

from philograph.library.extract import extract_pdf

from .builders import parse_raw

req = pytest.mark.req
DS = "document-structure"

BODY = "All knowledge begins with experience, but it does not all arise from the senses."


def _pdf(pages: list[list[tuple[str, float]]], bookmarks: list | None = None) -> bytes:
    """PDF с текстовым слоем: ``pages`` — списки строк (текст, размер шрифта)."""
    import pymupdf

    doc = pymupdf.open()
    for lines in pages:
        page = doc.new_page()
        y = 60.0
        for text, size in lines:
            page.insert_text((60, y), text, fontsize=size, fontname="helv")
            y += size * 1.6
    if bookmarks is not None:
        doc.set_toc(bookmarks)
    data = doc.tobytes()
    doc.close()
    return data


@req(DS, "Оглавление источника")
def test_chapters_follow_bookmarks_not_font_size():
    # «Ancient Philosophy» крупнее остальных: по шрифту оно стало бы верхним уровнем.
    data = _pdf(
        [
            [("Introduction to Philosophy", 16.0), (f"{BODY} First.", 11.0)],
            [("Ancient Philosophy", 24.0), (f"{BODY} Second.", 11.0)],
            [("Modern Philosophy", 16.0), (f"{BODY} Third.", 11.0)],
        ],
        [
            [1, "Introduction to Philosophy", 1],
            [1, "Ancient Philosophy", 2],
            [1, "Modern Philosophy", 3],
        ],
    )
    doc = parse_raw(extract_pdf(data, languages=["eng"], ocr=None))
    assert [(s.title, s.level) for s in doc.walk()] == [
        ("Introduction to Philosophy", 1),
        ("Ancient Philosophy", 1),
        ("Modern Philosophy", 1),
    ]
    assert not [i for i in doc.issues if i.code == "toc_mismatch"]


@req(DS, "Оглавление источника")
def test_bookmark_without_text_warns_with_title_and_page():
    data = _pdf(
        [
            [("Introduction to Philosophy", 16.0), (f"{BODY} First.", 11.0)],
            [("Ancient Philosophy", 16.0), (f"{BODY} Second.", 11.0)],
        ],
        [
            [1, "Introduction to Philosophy", 1],
            [1, "Ancient Philosophy", 2],
            [1, "Ghost Chapter", 2],
        ],
    )
    doc = parse_raw(extract_pdf(data, languages=["eng"], ocr=None))
    warnings = [i for i in doc.issues if i.code == "toc_mismatch"]
    assert len(warnings) == 1
    assert "Ghost Chapter" in warnings[0].message and "2" in warnings[0].message


@req(DS, "Оглавление источника")
def test_bookmark_on_wrong_page_warns():
    """Заголовок нашёлся, но не там, куда указывает закладка: это расхождение (EC-16).

    Молча брать структуру по шрифту нельзя: печатное оглавление разошлось с текстом,
    и оператор должен об этом узнать — с обеими страницами.
    """
    data = _pdf(
        [
            [("Chapter One", 16.0), (f"{BODY} First.", 11.0)],
            [("Chapter Two", 16.0), (f"{BODY} Second.", 11.0)],
        ],
        [
            [1, "Chapter One", 1],
            [1, "Chapter Two", 1],  # закладка врёт: заголовок на второй странице
        ],
    )
    doc = parse_raw(extract_pdf(data, languages=["eng"], ocr=None))
    messages = [i.message for i in doc.issues if i.code == "toc_mismatch"]
    assert any("Chapter Two" in m and "страницу 1" in m and "странице 2" in m for m in messages), (
        messages
    )


@req(DS, "Оглавление источника")
def test_bookmark_beyond_document_without_technical_page():
    """Закладка на удалённую страницу (PyMuPDF отдаёт −1) не показывает оператору «-1»."""
    from philograph.library.model import RawDocument, RawPage

    raw = RawDocument(pages=[RawPage(0, [], printed_label="1")], fmt="pdf", paginated=True)
    raw.printed_toc = [(1, "Conclusion", -1)]
    doc = parse_raw(raw)
    messages = [i.message for i in doc.issues if i.code == "toc_mismatch"]
    assert messages and all("-1" not in m for m in messages)
    assert any(i.page is None for i in doc.issues if i.code == "toc_mismatch")


@req(DS, "Оглавление источника")
def test_duplicate_heading_on_two_pages_does_not_cry_wolf():
    """Одноимённый заголовок на двух страницах: закладка на второе вхождение — не расхождение."""
    data = _pdf(
        [
            [("Notes", 16.0), (f"{BODY} First.", 11.0)],
            [("Notes", 16.0), (f"{BODY} Second.", 11.0)],
        ],
        [[1, "Notes", 2]],
    )
    doc = parse_raw(extract_pdf(data, languages=["eng"], ocr=None))
    assert not [i for i in doc.issues if i.code == "toc_mismatch"]


@req(DS, "Оглавление источника")
def test_bookmark_matching_heading_produces_no_warning():
    """Закладка, совпадающая с заголовком на её странице, предупреждений не даёт."""
    data = _pdf(
        [[("Chapter One", 16.0), (f"{BODY} First.", 11.0)]],
        [[1, "Chapter One", 1]],
    )
    doc = parse_raw(extract_pdf(data, languages=["eng"], ocr=None))
    assert not [i for i in doc.issues if i.code == "toc_mismatch"]


@req(DS, "Оглавление источника")
def test_without_bookmarks_uses_font_sizes():
    data = _pdf(
        [
            [("Introduction to Philosophy", 16.0), (f"{BODY} First.", 11.0)],
            [("Ancient Philosophy", 24.0), (f"{BODY} Second.", 11.0)],
            [("Modern Philosophy", 16.0), (f"{BODY} Third.", 11.0)],
        ]
    )
    doc = parse_raw(extract_pdf(data, languages=["eng"], ocr=None))
    by_title = {s.title: s.level for s in doc.walk()}
    assert by_title == {
        "Introduction to Philosophy": 2,
        "Ancient Philosophy": 1,  # крупнее → верхний уровень
        "Modern Philosophy": 2,
    }
    assert not [i for i in doc.issues if i.code == "toc_mismatch"]


@req(DS, "Оглавление источника")
def test_empty_bookmarks_fall_back_to_font_sizes():
    data = _pdf(
        [[("Introduction to Philosophy", 16.0), (f"{BODY} Only.", 11.0)]],
        bookmarks=[],
    )
    doc = parse_raw(extract_pdf(data, languages=["eng"], ocr=None))
    assert [s.title for s in doc.walk()] == ["Introduction to Philosophy"]
    assert not [i for i in doc.issues if i.code == "toc_mismatch"]


@req(DS, "Оглавление источника")
def test_bookmark_beyond_document_is_ignored_and_warns():
    raw = extract_pdf(
        _pdf([[("Introduction to Philosophy", 16.0), (f"{BODY} Only.", 11.0)]]),
        languages=["eng"],
        ocr=None,
    )
    # set_toc прижимает номер страницы к последней, поэтому закладку вне документа подставляем
    # в printed_toc напрямую — так она доходит до разбора и выдаёт предупреждение.
    raw.printed_toc = [(1, "Introduction to Philosophy", 1), (1, "Off the Edge", 5)]
    doc = parse_raw(raw)
    assert [s.title for s in doc.walk()] == ["Introduction to Philosophy"]
    warnings = [i for i in doc.issues if i.code == "toc_mismatch"]
    assert len(warnings) == 1 and "Off the Edge" in warnings[0].message
    assert warnings[0].page == "5"


@req(DS, "Оглавление источника")
def test_two_bookmarks_on_one_page_keep_order():
    data = _pdf(
        [
            [
                ("Chapter One", 16.0),
                (f"{BODY} First.", 11.0),
                ("Chapter Two", 16.0),
                (f"{BODY} Second.", 11.0),
            ]
        ],
        [[1, "Chapter One", 1], [1, "Chapter Two", 1]],
    )
    doc = parse_raw(extract_pdf(data, languages=["eng"], ocr=None))
    assert [s.title for s in doc.walk()] == ["Chapter One", "Chapter Two"]
    assert not [i for i in doc.issues if i.code == "toc_mismatch"]
