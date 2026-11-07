"""chapter-reading «Необработанные части в тексте»: пустая страница PDF не пропадает молча."""

from __future__ import annotations

import pytest

from philograph.library.model import RawLine
from philograph.library.processing import PIPELINE_VERSION, STEP_VERSIONS

from .builders import BODY, parse_raw, pdf, scan

req = pytest.mark.req
CR = "chapter-reading"
SENTENCE = "All our knowledge begins with experience, but it does not all arise from it."


@req(CR, "Необработанные части в тексте")
def test_blank_pdf_page_leaves_placeholder(lib):
    # цифровой PDF: на пятой странице нет ни текста, ни изображений
    pages = [[(f"{SENTENCE} Page {i}.", BODY) for _ in range(12)] for i in range(1, 20)]
    pages.insert(4, [])
    lib.files["book.pdf"] = pdf(pages)
    source_id = lib.register(
        files=[{"name": "b", "path": "book.pdf"}], language="en", settings={"languages": ["en"]}
    )
    lib.pipeline.ocr = None
    version = lib.pipeline.start("operator", source_id)
    if lib.registry.version(version)["state"] == "awaiting_quality":
        lib.pipeline.decide_quality("operator", version, "accept")  # оператор смотрит качество
    assert lib.registry.version(version)["state"] == "checked"
    blocks = [b for _, b in lib.registry.load_document(version).blocks()]
    placeholders = [b for b in blocks if b.kind == "unrendered"]
    assert [b.detail for b in placeholders] == ["страница 5: текст не распознан"]
    assert [b.detail_code for b in placeholders] == ["blank_page"]  # N7: код пояснения
    assert [b.page for b in placeholders] == ["5"]  # N7: номер страницы отдельно
    # заглушка стоит на месте пятой страницы: между текстом соседних страниц
    at = blocks.index(placeholders[0])
    assert "Page 4." in blocks[at - 1].text and "Page 5." in blocks[at + 1].text


@req(CR, "Необработанные части в тексте")
def test_placeholder_survives_furniture_and_uses_printed_label():
    # заглушки на многих страницах не принимаются за колонтитул; номер — печатный, если известен
    blank = [RawLine("", block_break=True, kind="blank_page")]
    text = [RawLine(f"{SENTENCE} Line {i}.", block_break=i == 0, size=BODY) for i in range(6)]
    raw = scan(text, blank, text, blank, text, blank)
    raw.pages[1].printed_label = "xii"
    doc = parse_raw(raw)
    details = [b.detail for _, b in doc.blocks() if b.kind == "unrendered"]
    assert details == [
        "страница xii: текст не распознан",
        "страница 4: текст не распознан",
        "страница 6: текст не распознан",
    ]


def test_pipeline_version_raised_for_placeholders():
    """Источники обрабатываются заново, чтобы заглушки появились и в опубликованных книгах."""
    assert PIPELINE_VERSION == "4"
    assert STEP_VERSIONS == {"extract": "3", "parse": "4"}
