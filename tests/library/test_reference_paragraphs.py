"""Справочные статьи: где в источнике реально проходят границы абзацев.

Решение владельца (раунд 1 `source-quality-followups`): источник бывает двух видов.
EB1911 размечает абзацы тегом `<p>`, а `\\n` внутри `<p>` — переносы строк скана, их склеиваем.
ЭСБЕ же присылает тело статьи одной строкой на 6–60 тыс. знаков без единого переноса: границ
абзацев в данных нет, поэтому такое тело остаётся одним абзацем — разбивка по точкам была бы
выдумкой (сценарий «Текст как в источнике»).
"""

from __future__ import annotations

import pytest

from philograph.library.extract import extract_html

req = pytest.mark.req
DS = "document-structure"


def html_of(body: str) -> bytes:
    return f"<html><body>{body}</body></html>".encode()


def paragraphs_of(body: str) -> list[str]:
    """Текст абзацев после извлечения HTML: границы блоков и склейка — как в конвейере."""
    pages, _ = extract_html(html_of(body))
    return [line.text for page in pages for line in page.lines if line.block_break]


@req(DS, "Склейка абзацев")
def test_eb1911_paragraphs_follow_p_tags_and_join_scan_lines():
    """EB1911: абзац — это `<p>`, а перенос строки внутри `<p>` — склейка скана."""
    body = (
        "<p>Idealism was born at\nKönigsberg.</p>"
        "<p>Its author wrote long notes.</p>"
        "<p>Readers still argue.</p>"
    )
    lines = paragraphs_of(body)
    assert len(lines) == 3
    assert "Königsberg" in lines[0]  # перенос скана склеен внутри абзаца


@req(DS, "Текст как в источнике")
def test_single_line_reference_article_stays_one_paragraph():
    """ЭСБЕ: тело одной строкой — один абзац, по предложениям не режем."""
    sentence = "Сенсуализмом принято называть известное направление в гносеологии. " * 40
    paragraphs = paragraphs_of(f"<p>{sentence.strip()}</p>")
    assert len(paragraphs) == 1
    assert paragraphs[0].count(".") > 20  # точек много, а абзац всё равно один


@req(DS, "Склейка абзацев")
def test_paragraph_boundaries_are_kept_between_p_tags():
    """Соседние `<p>` не склеиваются между собой, даже короткие."""
    assert paragraphs_of("<p>1. Крайний.</p><p>2. Умеренный.</p>") == [
        "1. Крайний.",
        "2. Умеренный.",
    ]
