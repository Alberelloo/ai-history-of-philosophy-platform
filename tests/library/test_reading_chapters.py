"""Требование chapter-reading «Оглавление»: что считается главой для чтения."""

from __future__ import annotations

import pytest

from philograph.library.model import RawDocument, RawLine, RawPage
from philograph.library.reading import Reading

from .builders import parse_raw

req = pytest.mark.req


def book(lines: list[RawLine]):
    return parse_raw(RawDocument(pages=[RawPage(0, lines)], fmt="epub", paginated=False))


def h(text: str, level: int) -> RawLine:
    return RawLine(text, heading_level=level, block_break=True)


def p(text: str) -> RawLine:
    return RawLine(text, block_break=True)


@req("chapter-reading", "Оглавление")
def test_book_title_wrapper_is_not_one_chapter():
    # EPUB Project Gutenberg: <h1>название книги</h1>, под ним <h2> главы
    doc = book(
        [
            h("An Essay Concerning Humane Understanding", 1),
            p("Dedication to the Lord President."),
            h("CHAPTER I. INTRODUCTION.", 2),
            *[p(f"First chapter paragraph {i} about ideas.") for i in range(5)],
            h("CHAPTER II. NO INNATE PRINCIPLES.", 2),
            *[p(f"Second chapter paragraph {i} about principles.") for i in range(5)],
        ]
    )
    titles = [c.title for c in Reading.chapters(doc)]
    assert titles == [
        "An Essay Concerning Humane Understanding",
        "CHAPTER I. INTRODUCTION.",
        "CHAPTER II. NO INNATE PRINCIPLES.",
    ]


@req("chapter-reading", "Оглавление")
def test_flat_chapters_with_one_sectioned_chapter_stay_chapters():
    # главы на верхнем уровне; у одной есть разделы — она остаётся одной главой
    doc = book(
        [
            h("Глава 1", 1),
            *[p(f"Текст первой главы {i}.") for i in range(5)],
            h("Глава 2", 1),
            p("Вступление."),
            h("Раздел 2.1", 2),
            p("Текст раздела."),
            h("Глава 3", 1),
            *[p(f"Текст третьей главы {i}.") for i in range(5)],
        ]
    )
    assert [c.title for c in Reading.chapters(doc)] == ["Глава 1", "Глава 2", "Глава 3"]
