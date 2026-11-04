"""Автоматические проверки структуры перед публикацией.

Ошибки блокируют публикацию, предупреждения нет. Пороги длины абзацев — настройка: числа
уточним на реальных источниках.
"""

from __future__ import annotations

import itertools
from collections import Counter
from dataclasses import dataclass

from philograph.library.model import Document, Issue


@dataclass(frozen=True)
class CheckSettings:
    long_paragraph_chars: int = 6000
    short_paragraph_chars: int = 3
    suspicious_share: float = 0.2  # доля подозрительных абзацев, после которой предупреждаем
    hidden_text_share: float = 0.3  # доля текста в непоказываемых разделах


def _numeric(label: str | None) -> int | None:
    return int(label) if label and label.isdigit() else None


def check(
    doc: Document, settings: CheckSettings | None = None, unapplied_corrections: int = 0
) -> list[Issue]:
    settings = settings or CheckSettings()
    issues: list[Issue] = list(doc.issues)
    sections = list(doc.walk())
    if not sections:
        issues.append(Issue("error", "no_sections", "В документе нет ни одного раздела"))
        return issues
    ids = Counter()
    pages: list[int] = []
    total = hidden = 0
    suspicious = paragraphs = 0
    for section in sections:
        for block in section.blocks:
            ids[block.id] += 1
            if block.kind != "unrendered" and not block.text.strip():
                issues.append(Issue("error", "empty_block", "Пустой абзац", block_id=block.id))
            if block.kind == "paragraph":
                paragraphs += 1
                if not (
                    settings.short_paragraph_chars < len(block.text) < settings.long_paragraph_chars
                ):
                    suspicious += 1
            total += len(block.text)
            if not section.visible:
                hidden += len(block.text)
            pages.extend(n for m in block.pages if (n := _numeric(m.label)) is not None)
        for note in section.footnotes:
            ids[note.id] += 1
    for ident, count in ids.items():
        if count > 1:
            issues.append(
                Issue("error", "duplicate_id", f"Идентификатор {ident} повторяется", block_id=ident)
            )
    for previous, current in itertools.pairwise(pages):
        if current < previous:
            issues.append(
                Issue(
                    "error",
                    "page_order",
                    f"Нарушен порядок страниц: {current} после {previous}",
                    page=str(current),
                )
            )
            break
    if paragraphs and suspicious / paragraphs > settings.suspicious_share:
        issues.append(
            Issue(
                "warning",
                "suspicious_paragraphs",
                f"Подозрительно длинных или коротких абзацев: {suspicious}",
            )
        )
    if total and hidden / total > settings.hidden_text_share:
        issues.append(
            Issue(
                "warning",
                "hidden_text",
                "Много текста в разделах, которые не показываются при чтении",
            )
        )
    if unapplied_corrections:
        issues.append(
            Issue(
                "warning", "unapplied_corrections", f"Неприменённых правок: {unapplied_corrections}"
            )
        )
    return issues


def has_errors(issues: list[Issue]) -> bool:
    return any(issue.level == "error" for issue in issues)
