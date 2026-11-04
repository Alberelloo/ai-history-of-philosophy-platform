"""Построители тестовых документов: сырые страницы «как со скана», EPUB, PDF."""

from __future__ import annotations

import io
import itertools
import zipfile

from philograph.library.model import RawDocument, RawLine, RawPage, RawSpan
from philograph.library.parse import ParseSettings, parse

BODY = 11.0
SMALL = 9.0
TITLE = 16.0


def ids():
    counter = itertools.count(1)
    return lambda prefix: f"{prefix}{next(counter)}"


def line(
    text: str,
    *,
    size: float = BODY,
    start: bool = False,
    indent: bool = False,
    note_at: int | None = None,
    kind: str | None = None,
) -> RawLine:
    spans = []
    if note_at is not None:
        spans.append(RawSpan(note_at, note_at + 1, "note_ref"))
    return RawLine(text, size=size, block_break=start, indent=indent, spans=spans, kind=kind)


def scan(*pages: list[RawLine]) -> RawDocument:
    return RawDocument(
        pages=[RawPage(i, list(p)) for i, p in enumerate(pages)], fmt="pdf", paginated=True
    )


def parse_raw(raw: RawDocument, **settings):
    return parse(raw, ParseSettings(**settings), ids())


def epub(chapters: list[tuple[str, str]]) -> bytes:
    """Минимальный EPUB: список (заголовок, тело XHTML)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:'
            'xmlns:container" version="1.0"><rootfiles><rootfile full-path="OEBPS/'
            'content.opf" media-type="application/oebps-package+xml"/></rootfiles>'
            "</container>",
        )
        items = "".join(
            f'<item id="c{i}" href="c{i}.xhtml" media-type="application/xhtml+xml"/>'
            for i in range(len(chapters))
        )
        spine = "".join(f'<itemref idref="c{i}"/>' for i in range(len(chapters)))
        zf.writestr(
            "OEBPS/content.opf",
            '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" '
            f'version="3.0"><manifest>{items}</manifest><spine>{spine}</spine>'
            "</package>",
        )
        for i, (title, body) in enumerate(chapters):
            zf.writestr(
                f"OEBPS/c{i}.xhtml",
                '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf'
                f'.org/2007/ops"><body><h1>{title}</h1>{body}</body></html>',
            )
    return buffer.getvalue()


def pdf(pages: list[list[tuple]]) -> bytes:
    """PDF с текстовым слоем: страницы — списки (текст, размер шрифта[, x])."""
    import pymupdf

    doc = pymupdf.open()
    for page_lines in pages:
        page = doc.new_page()
        y = 60
        for text, size, *x in page_lines:
            page.insert_text((x[0] if x else 60, y), text, fontsize=size, fontname="helv")
            y += size * 1.6
    data = doc.tobytes()
    doc.close()
    return data
