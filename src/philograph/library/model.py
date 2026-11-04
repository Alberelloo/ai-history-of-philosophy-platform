"""Модель: сырой документ (вход разбора) и структура документа (результат).

Любой извлекатель — TXT, HTML, EPUB, текстовый слой PDF, распознавание — выдаёт сырой документ:
страницы со строками и подсказками вёрстки. Разбор работает только с ним и не знает формата.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# --- сырой документ -----------------------------------------------------------------


@dataclass
class RawSpan:
    """Кусок строки с особым оформлением: знак сноски или ссылка на неё."""

    start: int
    end: int
    kind: Literal["note_ref"]
    target: str | None = None  # для HTML и EPUB — идентификатор сноски


@dataclass
class RawLine:
    text: str
    # Подсказки вёрстки. Текстовые форматы знают их точно, сканы — приблизительно.
    heading_level: int | None = None
    size: float | None = None
    bold: bool = False
    indent: bool = False  # красная строка: начало абзаца
    block_break: bool = False  # явная граница блока (пустая строка, конец <p>)
    kind: str | None = None  # quote | verse | list | footnote | figure | table
    note_id: str | None = None  # у строк текста сноски в HTML и EPUB
    spans: list[RawSpan] = field(default_factory=list)
    confidence: float | None = None  # уверенность распознавания строки


@dataclass
class RawPage:
    index: int  # порядковый номер страницы в файле, с нуля
    lines: list[RawLine]
    file_index: int = 0
    printed_label: str | None = None  # номер, если извлекатель его знает точно
    has_text_layer: bool = True
    ocr_confidence: float | None = None
    image_ref: str | None = None  # отпечаток изображения страницы в файловом хранилище


@dataclass
class RawDocument:
    pages: list[RawPage]
    fmt: str  # txt | html | epub | pdf
    paginated: bool  # есть ли у формата страницы печатного издания
    printed_toc: list[tuple[int, str]] = field(default_factory=list)  # (уровень, заголовок)


# --- структура документа ------------------------------------------------------------

SectionKind = Literal[
    "main", "preface", "introduction", "notes", "appendix", "bibliography", "index", "toc"
]
BlockKind = Literal["paragraph", "heading", "quote", "verse", "list", "unrendered"]

SECTION_KIND_DEFAULTS: dict[str, tuple[bool, bool]] = {
    # вид: (показывать при чтении, участвует в поиске и извлечении)
    "main": (True, True),
    "preface": (True, True),
    "introduction": (True, True),
    "notes": (True, True),
    "appendix": (True, True),
    "bibliography": (True, False),
    "index": (False, False),
    "toc": (False, False),
}


@dataclass
class PageMark:
    offset: int  # позиция в тексте блока, где начинается страница
    label: str | None  # номер как напечатан; None — номер неизвестен


@dataclass
class NoteRef:
    offset: int
    footnote_id: str


@dataclass
class Block:
    id: str
    kind: BlockKind
    text: str
    lang: str
    pages: list[PageMark] = field(default_factory=list)
    notes: list[NoteRef] = field(default_factory=list)
    detail: str | None = None  # у непереданного элемента: вид и подпись


@dataclass
class Footnote:
    id: str
    marker: str
    text: str
    linked: bool  # найден ли знак в тексте


@dataclass
class Section:
    id: str
    kind: SectionKind
    title: str
    level: int  # 0 — том, 1 — часть или глава, дальше глубже
    blocks: list[Block] = field(default_factory=list)
    children: list[Section] = field(default_factory=list)
    footnotes: list[Footnote] = field(default_factory=list)
    visible: bool = True
    searchable: bool = True

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()


@dataclass
class Issue:
    level: Literal["error", "warning"]
    code: str
    message: str
    page: str | None = None
    block_id: str | None = None


@dataclass
class Document:
    sections: list[Section]
    issues: list[Issue] = field(default_factory=list)

    def walk(self):
        for section in self.sections:
            yield from section.walk()

    def blocks(self):
        for section in self.walk():
            for block in section.blocks:
                yield section, block

    def footnotes(self):
        for section in self.walk():
            for note in section.footnotes:
                yield section, note

    def warn(self, code: str, message: str, **where: str | None) -> None:
        self.issues.append(Issue("warning", code, message, **where))

    def error(self, code: str, message: str, **where: str | None) -> None:
        self.issues.append(Issue("error", code, message, **where))
