"""Извлекатели: файл любого поддерживаемого формата → сырой документ.

Новый формат — новая функция здесь; разбор структуры и остальной конвейер не меняются.
"""

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from lxml import etree, html

from philograph.library.model import RawDocument, RawLine, RawPage, RawSpan


class ExtractionError(Exception):
    """Файл нельзя прочитать: повреждён, защищён паролем или формат не тот."""


def sniff_format(data: bytes) -> str | None:
    """Формат по содержимому, а не по расширению."""
    head = data[:2048]
    if head.startswith(b"%PDF-"):
        return "pdf"
    if head.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                if zf.read("mimetype").strip() == b"application/epub+zip":
                    return "epub"
        except (KeyError, zipfile.BadZipFile):
            return None
        return None
    lowered = head.lower()
    if b"<html" in lowered or b"<!doctype html" in lowered or b"<body" in lowered:
        return "html"
    if b"\x00" in head:
        return None  # двоичный файл неизвестного вида
    return "txt"


# --- TXT ----------------------------------------------------------------------------

_HEADING_RE = re.compile(
    r"^(#{1,6}\s+|(?:том|часть|глава|раздел|книга|volume|part|chapter|book)\b[\s\dIVXLCivxlc.:]*)",
    re.IGNORECASE,
)


def _is_service_title(text: str) -> bool:
    """Отдельная короткая строка «Предисловие», «Указатель» и т. п. — заголовок раздела."""
    from philograph.library.parse import SECTION_KIND_WORDS

    return (
        len(text) < 60
        and not text.endswith((".", ",", ";"))
        and any(pattern.match(text) for _, pattern in SECTION_KIND_WORDS)
    )


def decode_text(data: bytes, encoding: str | None = None) -> str:
    if encoding:
        return data.decode(encoding)
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1251", errors="replace")


def extract_txt(data: bytes, encoding: str | None = None) -> RawDocument:
    text = decode_text(data, encoding).replace("\r\n", "\n")
    pages = []
    for index, chunk in enumerate(text.split("\f")):
        lines: list[RawLine] = []
        pending_break = True
        for raw in chunk.split("\n"):
            line = raw.rstrip()
            if not line.strip():
                pending_break = True
                continue
            level = None
            stripped = line.strip()
            match = _HEADING_RE.match(stripped)
            toc_entry = re.search(r"[.…·]{3,}\s*(\d+|[ivxlc]+)$", stripped, re.IGNORECASE)
            if match is None and pending_break and _is_service_title(stripped):
                match = re.match(r"", stripped)
            if match and len(stripped) < 120 and not toc_entry:
                level = len(match.group(1).strip()) if stripped.startswith("#") else 1
                line = line.strip().lstrip("#").strip()
            lines.append(
                RawLine(
                    line.strip(),
                    heading_level=level,
                    block_break=pending_break,
                    indent=raw.startswith(("    ", "\t")),
                )
            )
            pending_break = level is not None
        pages.append(RawPage(index=index, lines=lines))
    return RawDocument(pages=pages, fmt="txt", paginated=len(pages) > 1)


# --- HTML и EPUB --------------------------------------------------------------------

_BLOCK_TAGS = {
    "p": None,
    "div": None,
    "blockquote": "quote",
    "li": "list",
    "pre": "verse",
    "dd": None,
    "dt": None,
}
_NOTE_CLASS_RE = re.compile(r"foot-?note|endnote|cite_note|\bnote\b|сноска", re.IGNORECASE)


def _epub_type(el: etree._Element) -> str:
    for key, value in el.attrib.items():
        if key.endswith("type") and "epub" in key:
            return value
    return ""


def _is_note_container(el: etree._Element, note_targets: set[str]) -> bool:
    if "footnote" in _epub_type(el) or "endnote" in _epub_type(el) or el.tag == "aside":
        return True
    ident = el.get("id")
    if not (ident and ident in note_targets):
        # Project Gutenberg: <p class="footnote"><a id="fn1.3"/> … — якорь внутри абзаца
        ident = next(
            (
                c.get("id")
                for c in el.iterchildren()
                if c.tag == "a" and c.get("id") in note_targets
            ),
            None,
        )
    return bool(
        ident
        and ident in note_targets
        # Wikisource (Parsoid): <li id="cite_note-1"> — признак сноски в идентификаторе
        and _NOTE_CLASS_RE.search((el.get("class") or "") + " " + el.tag + " " + ident)
    )


def _text_with_refs(el: etree._Element, note_targets: set[str]) -> tuple[str, list[RawSpan]]:
    """Текст элемента; ссылки на сноски становятся отметками в тексте."""
    parts: list[str] = []
    spans: list[RawSpan] = []

    def walk(node: etree._Element) -> None:
        href = node.get("href", "") if node.tag == "a" else ""
        target = href.split("#", 1)[1] if "#" in href else None
        is_ref = (target is not None and target in note_targets) or "noteref" in _epub_type(node)
        if is_ref:
            marker = "".join(node.itertext()).strip()
            start = len("".join(parts))
            parts.append(marker)
            spans.append(RawSpan(start, start + len(marker), "note_ref", target))
        else:
            if node.text:
                parts.append(node.text)
            for child in node:
                if isinstance(child.tag, str) and child.tag not in ("script", "style"):
                    walk(child)
                if child.tail:  # хвост любого потомка, включая ссылку, добавляет родитель
                    parts.append(child.tail)

    walk(el)
    text = re.sub(r"\s+", " ", "".join(parts))
    return text.strip(), _shift_spans("".join(parts), text.strip(), spans)


def _shift_spans(original: str, cleaned: str, spans: list[RawSpan]) -> list[RawSpan]:
    """Пересчитывает позиции отметок после схлопывания пробелов."""
    result = []
    for span in spans:
        prefix = re.sub(r"\s+", " ", original[: span.start]).lstrip()
        marker = original[span.start : span.end]
        result.append(RawSpan(len(prefix), len(prefix) + len(marker), span.kind, span.target))
    return [s for s in result if s.end <= len(cleaned)]


def extract_html(
    data: bytes | str, *, page_index_start: int = 0, file_index: int = 0
) -> tuple[list[RawPage], bool]:
    """HTML → страницы. Разрывы страниц EPUB (``epub:type="pagebreak"``) делят на страницы."""
    if isinstance(data, bytes):
        data = data.decode("utf-8", errors="replace")
    # Объявление XML с кодировкой lxml не принимает в строке; XHTML по умолчанию в UTF-8.
    data = re.sub(r"^\s*<\?xml[^>]*\?>", "", data)
    root = html.fromstring(data)
    body = root.find("body") if root.find("body") is not None else root
    # Обратная ссылка из сноски на её знак («[3]» в начале сноски Gutenberg) — не текст.
    ref_ids = {a.get("id") for a in body.iter("a") if a.get("id") and "#" in (a.get("href") or "")}
    for a in list(body.iter("a")):
        target = (a.get("href") or "").split("#", 1)[1] if "#" in (a.get("href") or "") else None
        if target in ref_ids and a.get("id") not in ref_ids:
            a.drop_tree()
    note_targets = {
        a.get("href").split("#", 1)[1]
        for a in body.iter("a")
        if a.get("href") and "#" in a.get("href")
    }
    pages = [RawPage(index=page_index_start, lines=[], file_index=file_index)]
    paginated = False

    def new_page(label: str | None) -> None:
        nonlocal paginated
        paginated = True
        pages.append(
            RawPage(
                index=page_index_start + len(pages),
                lines=[],
                file_index=file_index,
                printed_label=label,
            )
        )

    def visit(el: etree._Element, note_id: str | None, inherited: str | None = None) -> None:
        if not isinstance(el.tag, str) or el.tag in ("script", "style", "head"):
            return
        if el.get("data-philograph") == "missing":
            # Подстраница, которой нет на сайте (каталог, «красная» ссылка Wikisource).
            pages[-1].lines.append(RawLine("", block_break=True, kind="missing"))
            return
        if "pagebreak" in _epub_type(el) or el.get("role") == "doc-pagebreak":
            new_page(el.get("title") or (el.text or "").strip() or None)
            return
        if note_id is None and _is_note_container(el, note_targets):
            note_id = el.get("id") or next(
                (c.get("id") for c in el.iter() if c.get("id") in note_targets), None
            )
            note_id = note_id or f"note-{len(pages)}-{len(pages[-1].lines)}"
        tag = el.tag.lower()
        if re.fullmatch(r"h[1-6]", tag):
            text, _ = _text_with_refs(el, note_targets)
            if text:
                pages[-1].lines.append(
                    RawLine(text, heading_level=int(tag[1]), block_break=True, note_id=note_id)
                )
            return
        if tag in ("img", "figure", "table", "svg", "math"):
            kind = "table" if tag == "table" else "figure"
            caption = " ".join(el.itertext()).strip() or el.get("alt") or ""
            if tag == "table" and caption:
                pages[-1].lines.append(
                    RawLine(
                        re.sub(r"\s+", " ", caption),
                        block_break=True,
                        kind="table",
                        note_id=note_id,
                    )
                )
            else:
                pages[-1].lines.append(
                    RawLine(caption, block_break=True, kind=kind, note_id=note_id)
                )
            return
        has_block_children = any(
            isinstance(c.tag, str)
            and (
                c.tag in _BLOCK_TAGS
                or re.fullmatch(r"h[1-6]", c.tag)
                or c.tag in ("ul", "ol", "aside", "section", "table", "figure")
            )
            for c in el
        )
        if tag == "pre" or re.search(r"verse|poem|stanza", el.get("class") or ""):
            # Стихи: переносы строк — часть текста.
            for br in el.iter("br"):
                br.tail = "\n" + (br.tail or "")
            verse_lines = [ln.strip() for ln in "".join(el.itertext()).split("\n") if ln.strip()]
            for i, text in enumerate(verse_lines):
                pages[-1].lines.append(
                    RawLine(text, block_break=i == 0, kind="verse", note_id=note_id)
                )
            return
        kind = _BLOCK_TAGS.get(tag) or inherited
        if tag in _BLOCK_TAGS and not has_block_children:
            text, spans = _text_with_refs(el, note_targets)
            if text:
                pages[-1].lines.append(
                    RawLine(text, block_break=True, kind=kind, spans=spans, note_id=note_id)
                )
            return
        for child in el:
            visit(child, note_id, kind)

    visit(body, None)
    return [p for p in pages if p.lines or p.printed_label], paginated


def extract_epub(data: bytes) -> RawDocument:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        container = etree.fromstring(zf.read("META-INF/container.xml"))
    except (zipfile.BadZipFile, KeyError, etree.XMLSyntaxError) as exc:
        raise ExtractionError(f"повреждённый EPUB: {exc}") from exc
    if any(info.flag_bits & 0x1 for info in zf.infolist()):
        raise ExtractionError("файл защищён паролем")
    opf_path = container.find(".//{*}rootfile").get("full-path")
    opf = etree.fromstring(zf.read(opf_path))
    base = opf_path.rsplit("/", 1)[0] + "/" if "/" in opf_path else ""
    manifest = {item.get("id"): item.get("href") for item in opf.iter("{*}item")}
    pages: list[RawPage] = []
    paginated = False
    for ref in opf.iter("{*}itemref"):
        href = manifest.get(ref.get("idref"))
        if not href:
            continue
        chapter_pages, chapter_paginated = extract_html(
            zf.read(base + href), page_index_start=len(pages)
        )
        if pages and chapter_pages and chapter_pages[0].printed_label is None:
            # Новый файл главы продолжает текущую страницу печатного издания.
            pages[-1].lines.extend(chapter_pages[0].lines)
            chapter_pages = chapter_pages[1:]
        pages.extend(chapter_pages)
        paginated = paginated or chapter_paginated
    for i, page in enumerate(pages):
        page.index = i
    return RawDocument(pages=pages, fmt="epub", paginated=paginated)


# --- PDF ----------------------------------------------------------------------------


class OcrEngine(Protocol):
    """Распознавание страницы: строки с уверенностью и общая уверенность страницы."""

    def recognize(self, image: bytes, languages: list[str]) -> tuple[list[RawLine], float]: ...


@dataclass
class PdfPageImage:
    index: int
    png: bytes


TEXTLESS_SHARE = 0.1  # доля страниц без текстового слоя, после которой без распознавания нельзя


def extract_pdf(
    data: bytes,
    *,
    languages: list[str],
    ocr: OcrEngine | None,
    skip_pages: set[int] | None = None,
    on_page: Callable[[RawPage], None] | None = None,
    done_pages: dict[int, RawPage] | None = None,
    store_image: Callable[[bytes], str] | None = None,
    spreads: bool = False,
) -> RawDocument:
    """Текстовый слой берётся как есть, страницы без него распознаются.

    ``done_pages`` — страницы, уже обработанные прежним запуском: их не трогаем, так обработка
    продолжается с первой необработанной страницы после сбоя.
    """
    import pymupdf

    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise ExtractionError(f"повреждённый PDF: {exc}") from exc
    if doc.needs_pass:
        raise ExtractionError("файл защищён паролем")
    pages: list[RawPage] = []
    textless: list[int] = []
    for index in range(doc.page_count):
        if skip_pages and index in skip_pages:
            continue
        if done_pages and index in done_pages:
            pages.append(done_pages[index])
            continue
        page = doc.load_page(index)
        # Разворот: на изображении две страницы рядом — делим по середине.
        rect = page.rect
        clips = (
            [
                pymupdf.Rect(rect.x0, rect.y0, rect.x1 / 2, rect.y1),
                pymupdf.Rect(rect.x1 / 2, rect.y0, rect.x1, rect.y1),
            ]
            if spreads
            else [None]
        )
        for clip in clips:
            lines = _pdf_text_lines(page, clip)
            label = (page.get_label() or None) if clip is None else None
            raw = RawPage(
                index=len(pages), lines=lines, printed_label=label, has_text_layer=bool(lines)
            )
            if store_image is not None:
                raw.image_ref = store_image(page.get_pixmap(dpi=150, clip=clip).tobytes("png"))
            if not lines and ocr is None:
                # Обложка или иллюстрация во всю страницу в цифровом PDF: страница остаётся
                # пустой. Если таких страниц много, это скан — см. проверку после цикла.
                textless.append(index)
            elif not lines:
                image = page.get_pixmap(dpi=300, clip=clip).tobytes("png")
                raw.lines, raw.ocr_confidence = ocr.recognize(image, languages)
            if not any(line.text.strip() or line.kind == "figure" for line in raw.lines):
                # Ни текста, ни иллюстраций: страница не пропадает молча — на её месте в тексте
                # будет заглушка «текст не распознан».
                raw.lines.append(RawLine("", block_break=True, kind="blank_page"))
            pages.append(raw)
            if on_page is not None:
                on_page(raw)
    if textless and len(textless) > max(1, TEXTLESS_SHARE * doc.page_count):
        raise ExtractionError(
            f"{len(textless)} из {doc.page_count} страниц без текста (первая — страница "
            f"{textless[0] + 1}), распознавание не задано"
        )
    return RawDocument(pages=pages, fmt="pdf", paginated=True)


def _pdf_text_lines(page, clip=None) -> list[RawLine]:
    lines: list[RawLine] = []
    data = page.get_text("dict", clip=clip)
    for block in data.get("blocks", []):
        if block.get("type") != 0:
            lines.append(RawLine("", block_break=True, kind="figure"))
            continue
        first = True
        for line in block.get("lines", []):
            text = ""
            spans: list[RawSpan] = []
            sizes = []
            bold = True
            for span in line.get("spans", []):
                chunk = span.get("text", "")
                if not chunk:
                    continue
                if span.get("flags", 0) & 1 and chunk.strip().isdigit():  # надстрочный индекс
                    spans.append(RawSpan(len(text), len(text) + len(chunk.strip()), "note_ref"))
                    chunk = chunk.strip()
                text += chunk
                sizes.append(span.get("size", 0))
                bold = bold and bool(span.get("flags", 0) & 16)
            if text.strip():
                lines.append(
                    RawLine(
                        text.rstrip(),
                        size=max(sizes) if sizes else None,
                        bold=bold,
                        block_break=first,
                        spans=spans,
                    )
                )
                first = False
    return lines


def extract(
    data: bytes,
    fmt: str,
    *,
    languages: list[str] | None = None,
    ocr: OcrEngine | None = None,
    encoding: str | None = None,
) -> RawDocument:
    if fmt == "txt":
        return extract_txt(data, encoding)
    if fmt == "html":
        pages, paginated = extract_html(data)
        return RawDocument(pages=pages, fmt="html", paginated=paginated)
    if fmt == "epub":
        return extract_epub(data)
    if fmt == "pdf":
        return extract_pdf(data, languages=languages or ["rus"], ocr=ocr)
    raise ExtractionError(f"формат не поддерживается: {fmt}")


class TesseractOcr:
    """Распознавание через Tesseract 5 (``pytesseract``). Нужен установленный ``tesseract``.

    Коды языков Tesseract: rus, lat, grc, eng, deu, fra. Уверенность строки — среднее по словам.
    """

    def recognize(self, image: bytes, languages: list[str]) -> tuple[list[RawLine], float]:
        import pytesseract
        from PIL import Image

        data = pytesseract.image_to_data(
            Image.open(io.BytesIO(image)),
            lang="+".join(languages),
            output_type=pytesseract.Output.DICT,
        )
        lines: dict[tuple[int, int, int], list[tuple[str, float]]] = {}
        for i, word in enumerate(data["text"]):
            if word.strip() and float(data["conf"][i]) >= 0:
                key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
                lines.setdefault(key, []).append((word, float(data["conf"][i]) / 100))
        result: list[RawLine] = []
        previous_par = None
        for (block, par, _), words_conf in sorted(lines.items()):
            text = " ".join(w for w, _ in words_conf)
            confidence = sum(c for _, c in words_conf) / len(words_conf)
            result.append(
                RawLine(text, block_break=(block, par) != previous_par, confidence=confidence)
            )
            previous_par = (block, par)
        overall = sum(ln.confidence or 0 for ln in result) / len(result) if result else 0.0
        return result, overall
