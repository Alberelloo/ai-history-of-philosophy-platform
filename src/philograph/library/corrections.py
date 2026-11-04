"""Ручные правки оператора как операции с якорем.

Правка хранится отдельно от результата разбора и применяется после каждого разбора заново.
Якорь — идентификатор абзаца и цитата с контекстом до и после (как селектор цитаты в
W3C Web Annotation). Если цитата не нашлась, правка не теряется, а становится неприменённой.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from philograph.library.model import Block, Document, Section

Op = Literal[
    "replace_text",
    "set_block_kind",
    "set_section_kind",
    "merge_with_next",
    "split_at",
    "delete_block",
]


@dataclass(frozen=True)
class Anchor:
    block_id: str | None = None
    exact: str = ""  # цитата, к которой привязана правка
    prefix: str = ""
    suffix: str = ""
    section_title: str | None = None  # для правок раздела


@dataclass(frozen=True)
class Correction:
    id: int
    op: Op
    anchor: Anchor
    payload: dict[str, Any] = field(default_factory=dict)


def _fits(block: Block, anchor: Anchor) -> int | None:
    """Позиция цитаты в блоке с учётом контекста; ``None`` — не подходит."""
    if not anchor.exact:
        return 0 if block.id == anchor.block_id else None
    start = 0
    while (pos := block.text.find(anchor.exact, start)) != -1:
        before = block.text[max(0, pos - len(anchor.prefix)) : pos]
        after = block.text[pos + len(anchor.exact) : pos + len(anchor.exact) + len(anchor.suffix)]
        if before.endswith(anchor.prefix) and after.startswith(anchor.suffix):
            return pos
        start = pos + 1
    return None


def locate(doc: Document, anchor: Anchor) -> tuple[Section, int, int] | None:
    """Раздел, индекс блока и позиция цитаты. Сначала свой абзац, затем единственный другой."""
    found: list[tuple[Section, int, int]] = []
    for section in doc.walk():
        for index, block in enumerate(section.blocks):
            pos = _fits(block, anchor)
            if pos is None:
                continue
            if block.id == anchor.block_id:
                return section, index, pos
            found.append((section, index, pos))
    return found[0] if len(found) == 1 else None


def apply(doc: Document, corrections: list[Correction], new_id) -> list[Correction]:
    """Применяет правки по порядку. Возвращает неприменённые."""
    unapplied: list[Correction] = []
    for correction in corrections:
        if not _apply_one(doc, correction, new_id):
            unapplied.append(correction)
    return unapplied


def _apply_one(doc: Document, c: Correction, new_id) -> bool:
    if c.op == "set_section_kind":
        for section in doc.walk():
            if section.title == c.anchor.section_title:
                section.kind = c.payload["kind"]
                if "searchable" in c.payload:
                    section.searchable = bool(c.payload["searchable"])
                return True
        return False
    where = locate(doc, c.anchor)
    if where is None:
        return False
    section, index, pos = where
    block = section.blocks[index]
    if c.op == "replace_text":
        block.text = block.text[:pos] + c.payload["text"] + block.text[pos + len(c.anchor.exact) :]
        return True
    if c.op == "set_block_kind":
        if c.payload["kind"] == "heading":
            # Абзац стал заголовком: всё после него — новый подраздел.
            child = Section(
                new_id("sec"),
                section.kind,
                block.text,
                section.level + 1,
                blocks=section.blocks[index + 1 :],
            )
            section.blocks = section.blocks[:index]
            section.children.insert(0, child)
        else:
            block.kind = c.payload["kind"]
        return True
    if c.op == "merge_with_next":
        if index + 1 >= len(section.blocks):
            return False
        nxt = section.blocks.pop(index + 1)
        shift = len(block.text) + 1
        block.text = f"{block.text} {nxt.text}"
        block.pages += [type(m)(m.offset + shift, m.label) for m in nxt.pages]
        block.notes += [type(r)(r.offset + shift, r.footnote_id) for r in nxt.notes]
        return True
    if c.op == "split_at":
        cut = pos
        head, tail = block.text[:cut].rstrip(), block.text[cut:].lstrip()
        if not head or not tail:
            return False
        second = Block(
            new_id("p"),
            block.kind,
            tail,
            block.lang,
            pages=[type(m)(m.offset - cut, m.label) for m in block.pages if m.offset >= cut],
            notes=[type(r)(r.offset - cut, r.footnote_id) for r in block.notes if r.offset >= cut],
        )
        block.text = head
        block.pages = [m for m in block.pages if m.offset < cut]
        block.notes = [r for r in block.notes if r.offset < cut]
        section.blocks.insert(index + 1, second)
        return True
    if c.op == "delete_block":
        section.blocks.pop(index)
        return True
    return False
