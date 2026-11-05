"""Очистка служебных частей сайта перед хешированием.

Сайты пересобирают файлы: меняется дата в шапке, список правщиков, отметка времени
в архиве. Текст при этом тот же. Очистка убирает такие части и пересобирает EPUB
детерминированно, чтобы хеш менялся только вместе с текстом.
"""

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Callable

from lxml import etree, html

FIXED_TIME = (1980, 1, 1, 0, 0, 0)
_OPF_VOLATILE = re.compile(
    rb"<meta[^>]*(?:dcterms:modified|calibre:timestamp)[^>]*>(?:[^<]*</meta>)?|"
    rb"<dc:date[^>]*>[^<]*</dc:date>|<dc:identifier[^>]*>urn:uuid:[^<]*</dc:identifier>",
    re.IGNORECASE,
)


def _rewrite_epub(data: bytes, transform: Callable[[str, bytes], bytes | None]) -> bytes:
    """Пересобирает EPUB. ``transform(имя, байты)`` — новые байты или ``None`` (без изменений)."""
    source = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as target:
        names = source.namelist()
        # mimetype — первым и без сжатия, как требует EPUB
        ordered = (["mimetype"] if "mimetype" in names else []) + sorted(
            n for n in names if n != "mimetype"
        )
        for name in ordered:
            body = source.read(name)
            if name.lower().endswith(".opf"):
                body = _OPF_VOLATILE.sub(b"", body)
            changed = transform(name, body)
            if changed is not None:
                body = changed
            info = zipfile.ZipInfo(name, date_time=FIXED_TIME)
            info.compress_type = zipfile.ZIP_STORED if name == "mimetype" else zipfile.ZIP_DEFLATED
            target.writestr(info, body)
    return out.getvalue()


def _drop(body: bytes, xpath: str) -> bytes | None:
    try:
        root = etree.fromstring(body, parser=etree.XMLParser(recover=True, resolve_entities=False))
    except etree.XMLSyntaxError:
        return None
    if root is None:
        return None
    found = root.xpath(xpath)
    if not found:
        return None
    for el in found:
        parent = el.getparent()
        if parent is not None:
            parent.remove(el)
    return etree.tostring(root, xml_declaration=True, encoding="utf-8")


# --- Project Gutenberg ----------------------------------------------------------------

_PG_START = re.compile(rb"^\*\*\*\s*START OF (?:THE|THIS) PROJECT GUTENBERG.*$", re.M | re.I)
_PG_END = re.compile(rb"^\*\*\*\s*END OF (?:THE|THIS) PROJECT GUTENBERG.*$", re.M | re.I)
_PG_SECTIONS = (
    "//*[@id='pg-header' or @id='pg-footer' or "
    "contains(concat(' ', @class, ' '), ' pg-boilerplate ')]"
)


def gutenberg(data: bytes) -> bytes:
    """Текст без шапки и лицензии Project Gutenberg; для EPUB — без разделов pg-header/pg-footer."""
    if data.startswith(b"PK\x03\x04"):

        def transform(name: str, body: bytes) -> bytes | None:
            if name.lower().endswith((".xhtml", ".html", ".htm")):
                return _drop(body, _PG_SECTIONS)
            return None

        return _rewrite_epub(data, transform)
    start = _PG_START.search(data)
    end = _PG_END.search(data)
    if start and end and end.start() > start.end():
        return data[start.end() : end.start()].strip() + b"\n"
    return data


# --- Wikisource ---------------------------------------------------------------------------


def wikisource(data: bytes) -> bytes:
    """HTML страницы без шапки, навигации и служебных блоков; EPUB — без страницы участников."""
    if data.startswith(b"PK\x03\x04"):

        def transform(name: str, body: bytes) -> bytes | None:
            lower = name.lower()
            if lower.endswith(("about.xhtml", "credits.xhtml")):
                # список правщиков меняется при каждой правке вики: оставляем пустую страницу
                return (
                    b'<?xml version="1.0" encoding="utf-8"?>\n'
                    b'<html xmlns="http://www.w3.org/1999/xhtml"><head><title></title></head>'
                    b"<body></body></html>"
                )
            if lower.endswith((".xhtml", ".html")):
                return _drop(
                    body,
                    "//*[contains(concat(' ', @class, ' '), ' ws-noexport ') or "
                    "contains(concat(' ', @class, ' '), ' mw-editsection ')]",
                )
            return None

        return _rewrite_epub(data, transform)
    if b"<" in data[:200]:
        tree = html.fromstring(data)
        for el in tree.xpath(
            "//*[contains(@class,'ws-noexport') or contains(@class,'mw-editsection') or "
            "contains(@class,'headertemplate') or @id='ws-data' or @id='toc' or "
            "contains(@class,'printfooter') or contains(@class,'mw-cite-backlink')]"
        ):
            el.getparent().remove(el)
        # Подстраница «Книга/Глава 1»: заголовок главы — последняя часть названия страницы.
        title = tree.find(".//title")
        body = tree.find(".//body")
        if title is not None and title.text and body is not None:
            short = title.text.rsplit("/", 1)[-1].strip()
            title.text = short
            if not body.xpath(".//h1|.//h2"):
                heading = html.Element("h2")
                heading.text = short
                body.insert(0, heading)
        return html.tostring(tree, encoding="utf-8")
    return data


CLEANERS: dict[str, Callable[[bytes], bytes]] = {"gutenberg": gutenberg, "wikisource": wikisource}
