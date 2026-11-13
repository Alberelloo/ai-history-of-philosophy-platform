"""Разбор сырого документа в структуру: разделы, блоки, сноски, страницы.

Порядок: служебные элементы вёрстки → номера страниц → сноски → блоки с отметками страниц →
разделы по заголовкам → виды разделов → языки → оглавление. Все решения, которые нельзя
принять уверенно, становятся предупреждениями для оператора, а не молчаливыми догадками.
"""

from __future__ import annotations

import itertools
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field

from philograph.library import lang
from philograph.library.model import (
    SECTION_KIND_DEFAULTS,
    Block,
    Document,
    Footnote,
    NoteRef,
    PageMark,
    RawDocument,
    RawLine,
    RawPage,
    Section,
)


@dataclass
class ParseSettings:
    language: str = "ru"
    header_patterns: list[str] = field(default_factory=list)  # регулярные выражения
    page_offset: int | None = None  # номер = индекс страницы + сдвиг, если номеров нет
    section_kinds: dict[str, bool] = field(default_factory=dict)  # вид: участвует в поиске
    volume_titles: list[str] = field(default_factory=list)  # названия томов по файлам


_ROMAN_RE = re.compile(r"^[ivxlcdm]+$", re.IGNORECASE)
_PAGE_NUMBER_RE = re.compile(r"^[-–—\s]*(\d{1,4}|[ivxlcdm]{1,7})[-–—\s]*$", re.IGNORECASE)
_SEPARATOR_RE = re.compile(r"^[_\-–—=*\s]{3,}$")
_NOTE_LINE_RE = re.compile(r"^(\d{1,3}|\*{1,3})[\s).]+(\S.*)$")
_TERMINAL = tuple('.!?…:;»")”')
_TOC_LINE_RE = re.compile(r"^(?P<title>.+?)[\s.…·]{2,}(?P<page>\d{1,4}|[ivxlcdm]+)$", re.IGNORECASE)
# Части слов, перед которыми дефис в конце строки настоящий, а не перенос.
_HYPHEN_SUFFIXES = ("то", "либо", "нибудь", "ка", "таки", "де", "с")
_HYPHEN_PREFIXES = {"кое", "кой", "из", "по", "во", "в", "экс", "вице", "лейб", "обер"}

SECTION_KIND_WORDS: list[tuple[str, re.Pattern[str]]] = [
    ("preface", re.compile(r"^(предисловие|от автора|от редакции|preface|foreword)", re.I)),
    ("introduction", re.compile(r"^(введение|introduction|einleitung)", re.I)),
    ("notes", re.compile(r"^(примечания|комментарии|notes|anmerkungen)\b", re.I)),
    ("appendix", re.compile(r"^(приложени|appendix)", re.I)),
    (
        "bibliography",
        re.compile(r"^(список литературы|литература|библиография|bibliography|references)", re.I),
    ),
    ("index", re.compile(r"^(именной указатель|предметный указатель|указатель|index)", re.I)),
    ("toc", re.compile(r"^(оглавление|содержание|contents|table of contents)$", re.I)),
]


def section_kind(title: str) -> str:
    for kind, pattern in SECTION_KIND_WORDS:
        if pattern.match(title.strip()):
            return kind
    return "main"


# --- 1. служебные элементы и номера страниц -----------------------------------------


def _shape(text: str) -> str:
    return re.sub(r"\d+", "#", text.strip().lower())


# Строки-заглушки извлечения: то, что не передано текстом, и почему.
PLACEHOLDERS = ("blank_page", "missing")


def strip_furniture(raw: RawDocument, settings: ParseSettings) -> None:
    """Убирает колонтитулы и номера страниц; номера запоминает как номера страниц."""
    patterns = [re.compile(p) for p in settings.header_patterns]
    pages = [p for p in raw.pages if p.lines]
    if raw.paginated and len(pages) >= 3:
        edges: Counter[str] = Counter()
        for page in pages:
            candidates = {_shape(line.text) for line in page.lines[:2] + page.lines[-2:]}
            edges.update(candidates)
        threshold = max(3, int(0.4 * len(pages)))
        repeated = {
            shape
            for shape, count in edges.items()
            if count >= threshold and not _PAGE_NUMBER_RE.match(shape.replace("#", "1"))
        }
    else:
        repeated = set()
    for page in raw.pages:
        kept: list[RawLine] = []
        for position, line in enumerate(page.lines):
            if line.kind in PLACEHOLDERS:
                kept.append(line)  # заглушка не колонтитул, даже если таких страниц много
                continue
            text = line.text.strip()
            edge = position < 2 or position >= len(page.lines) - 2
            if any(p.search(text) for p in patterns):
                _take_label(page, text)
                continue
            if edge and raw.paginated and _shape(text) in repeated:
                _take_label(page, text)
                continue
            if edge and raw.paginated and _PAGE_NUMBER_RE.match(text) and line.kind is None:
                if page.printed_label is None:
                    page.printed_label = _PAGE_NUMBER_RE.match(text).group(1)
                continue
            if _SEPARATOR_RE.match(text) and line.kind is None:
                continue
            kept.append(line)
        page.lines = kept


def _take_label(page: RawPage, text: str) -> None:
    """В колонтитуле часто стоит номер страницы: «12   Глава 1» или «Глава 1   13»."""
    if page.printed_label is not None:
        return
    for token in text.split()[:1] + text.split()[-1:]:
        if token.isdigit() or _ROMAN_RE.match(token):
            page.printed_label = token
            return


UNRELIABLE_LABELS = 0.1  # доля нарушений порядка, после которой номера страниц не показываются


def infer_labels(raw: RawDocument, settings: ParseSettings) -> list[str | None]:
    """Номер страницы как напечатан; нераспознанный выводится, только если нумерация непрерывна."""
    labels = [p.printed_label for p in raw.pages]
    if not raw.paginated:
        return [None] * len(labels)
    if all(label is None for label in labels) and settings.page_offset is not None:
        return [str(p.index + settings.page_offset) for p in raw.pages]
    numbers = [int(x) if x and x.isdigit() else None for x in labels]

    def neighbours(i: int) -> tuple[tuple[int, int] | None, tuple[int, int] | None]:
        prev = next(((j, numbers[j]) for j in range(i - 1, -1, -1) if numbers[j] is not None), None)
        nxt = next(
            ((j, numbers[j]) for j in range(i + 1, len(numbers)) if numbers[j] is not None), None
        )
        return prev, nxt

    # Выброс: соседи согласованы между собой, а номер между ними нет («2022» из колонтитула
    # с годом между 107 и 109). Такой номер не напечатанный, а ошибочно взятый.
    for i, value in enumerate(numbers):
        if value is None:
            continue
        prev, nxt = neighbours(i)
        if (
            prev
            and nxt
            and nxt[1] - prev[1] == nxt[0] - prev[0]
            and value != prev[1] + (i - prev[0])
        ):
            numbers[i] = None
            labels[i] = None
    # Номера часто идут не по порядку — это не нумерация страниц, а случайные числа
    # колонтитулов: неверный номер хуже отсутствующего.
    known = [n for n in numbers if n is not None]
    drops = sum(1 for a, b in itertools.pairwise(known) if b < a)
    if known and drops > max(1, UNRELIABLE_LABELS * len(known)):
        return [None] * len(labels)
    for i, value in enumerate(numbers):
        if value is not None or labels[i] is not None:
            continue
        prev, nxt = neighbours(i)
        if prev and nxt and nxt[1] - prev[1] == nxt[0] - prev[0]:
            labels[i] = str(prev[1] + (i - prev[0]))
    return labels


def body_size(raw: RawDocument) -> float | None:
    """Размер основного шрифта: тот, которым набрано больше всего символов."""
    weights: Counter[float] = Counter()
    for page in raw.pages:
        for ln in page.lines:
            if ln.size:
                weights[round(ln.size, 1)] += len(ln.text)
    return weights.most_common(1)[0][0] if weights else None


# --- 2. сноски ----------------------------------------------------------------------


@dataclass
class _RawNote:
    key: str  # маркер или идентификатор HTML
    text: str
    page_pos: int  # индекс страницы
    order: int


def split_footnotes(raw: RawDocument) -> list[_RawNote]:
    """Выделяет текст сносок из потока страниц."""
    notes: list[_RawNote] = []
    counter = itertools.count()
    html_like = raw.fmt in ("html", "epub")
    base = body_size(raw)
    in_notes = False
    for pos, page in enumerate(raw.pages):
        body: list[RawLine] = []
        if html_like:
            for line in page.lines:
                if line.note_id is not None:
                    text = (
                        _NOTE_LINE_RE.sub(r"\2", line.text)
                        if _NOTE_LINE_RE.match(line.text)
                        else line.text
                    )
                    if notes and notes[-1].key == line.note_id:
                        notes[-1].text += " " + text
                    else:
                        notes.append(_RawNote(line.note_id, text, pos, next(counter)))
                else:
                    body.append(line)
            page.lines = body
            continue
        current: _RawNote | None = None
        tail_start = len(page.lines)
        for i in range(len(page.lines) - 1, -1, -1):
            line = page.lines[i]
            small = base is not None and line.size is not None and line.size < base * 0.92
            if not in_notes and (line.kind == "footnote" or (small and i >= len(page.lines) // 2)):
                tail_start = i
                continue
            break
        for i, line in enumerate(page.lines):
            text = line.text.strip()
            heading = line.heading_level is not None or (
                base is not None and line.size is not None and line.size > base * 1.15
            )
            if heading:
                # Раздел «Примечания»: дальше идут концевые примечания, пока не начнётся другой.
                in_notes = section_kind(text) == "notes"
                current = None
                body.append(line)
                continue
            match = _NOTE_LINE_RE.match(text)
            if in_notes or i >= tail_start:
                if match:
                    current = _RawNote(match.group(1), match.group(2), pos, next(counter))
                    notes.append(current)
                    continue
                if current is not None:
                    current.text = _join(current.text, line.text)
                    continue
            body.append(line)  # мелкий шрифт без маркера — не сноска
        page.lines = body
    return notes


# --- 3. строки → блоки --------------------------------------------------------------


def _join(left: str, right: str) -> str:
    """Склейка строк: перенос по слогам убирается, настоящий дефис остаётся."""
    left = left.rstrip()
    right = right.lstrip()
    if left.endswith("­"):
        return left[:-1] + right
    if left.endswith("-") and right[:1].isalpha():
        head = re.findall(r"[^\W\d_]+-$", left)
        stem = head[0][:-1].lower() if head else ""
        tail = re.match(r"[^\W\d_]+", right)
        next_word = tail.group(0).lower() if tail else ""
        if (
            right[:1].islower()
            and next_word not in _HYPHEN_SUFFIXES
            and (stem not in _HYPHEN_PREFIXES)
        ):
            return left[:-1] + right
        return left + right
    return f"{left} {right}"


@dataclass
class _Draft:
    kind: str
    text: str
    pages: list[PageMark]
    notes: list[tuple[int, str, int, str]]  # позиция, ключ, страница знака, текст знака
    page_pos: int = 0  # страница, где блок начинается
    heading_level: int | None = None
    detail: str | None = None
    detail_code: str | None = None
    page: str | None = None


def build_blocks(raw: RawDocument, labels: list[str | None], base: float | None) -> list[_Draft]:
    drafts: list[_Draft] = []
    heading_sizes = sorted(
        {
            round(ln.size)
            for p in raw.pages
            for ln in p.lines
            if ln.size and base and ln.size > base * 1.15
        },
        reverse=True,
    )
    current: _Draft | None = None
    for pos, page in enumerate(raw.pages):
        label = labels[pos]
        page_started = raw.paginated
        for line in page.lines:
            level = line.heading_level
            if (
                level is None
                and base
                and line.size
                and line.size > base * 1.15
                and (len(line.text) < 120 and not line.text.rstrip().endswith("."))
            ):
                level = heading_sizes.index(round(line.size)) + 1
            if level is not None:
                current = _Draft(
                    "heading", line.text.strip(), [], [], page_pos=pos, heading_level=level
                )
                drafts.append(current)
                current = None
                # Отметка начала страницы достанется первому блоку после заголовка.
                continue
            if line.kind in PLACEHOLDERS:
                blank = line.kind == "blank_page"
                page = str(label) if (label and blank) else (str(pos + 1) if blank else None)
                detail = (
                    f"страница {page}: текст не распознан"
                    if blank
                    else "глава не оцифрована на сайте"
                )
                drafts.append(
                    _Draft(
                        "unrendered",
                        "",
                        [],
                        [],
                        page_pos=pos,
                        detail=detail,
                        detail_code="blank_page" if blank else "missing",
                        page=page,
                    )
                )
                current = None
                continue
            if line.kind in ("figure", "table") and not (line.kind == "table" and line.text):
                what = "иллюстрация" if line.kind == "figure" else "таблица"
                where = f", с. {label}" if label else ""
                drafts.append(
                    _Draft(
                        "unrendered",
                        line.text.strip(),
                        [],
                        [],
                        page_pos=pos,
                        detail=f"{what}{where}",
                        detail_code=line.kind,
                        page=str(label) if label else None,
                    )
                )
                current = None
                continue
            kind = {"quote": "quote", "verse": "verse", "list": "list"}.get(
                line.kind or "", "paragraph"
            )
            continues = (
                current is not None
                and current.kind == kind
                and not line.indent
                and (
                    not line.block_break
                    or (
                        page_started
                        and not current.text.rstrip().endswith(_TERMINAL)
                        and line.text[:1].islower()
                    )
                )
            )
            if (
                kind == "verse"
                and current is not None
                and current.kind == "verse"
                and (not line.block_break)
            ):
                continues = True
            if continues:
                assert current is not None
                joined = (
                    (current.text + "\n" + line.text.strip())
                    if kind == "verse"
                    else (_join(current.text, line.text))
                )
                shift = len(joined) - len(line.text.strip())
                if page_started and raw.paginated:
                    current.pages.append(PageMark(shift, label))
                current.notes.extend(
                    (
                        shift + s.start,
                        s.target or line.text[s.start : s.end],
                        pos,
                        line.text[s.start : s.end],
                    )
                    for s in line.spans
                )
                current.text = joined
            else:
                marks = [PageMark(0, label)] if page_started and raw.paginated else []
                current = _Draft(
                    kind,
                    line.text.strip(),
                    marks,
                    [
                        (
                            s.start,
                            s.target or line.text[s.start : s.end],
                            pos,
                            line.text[s.start : s.end],
                        )
                        for s in line.spans
                    ],
                    page_pos=pos,
                )
                drafts.append(current)
            page_started = False
        if page_started and raw.paginated and current is not None:
            # Пустая страница (вклейка) — отметка без текста, нумерация не сдвигается.
            current.pages.append(PageMark(len(current.text), label))
    return drafts


# --- 4. блоки → разделы -------------------------------------------------------------


def parse(raw: RawDocument, settings: ParseSettings, new_id: Callable[[str], str]) -> Document:
    strip_furniture(raw, settings)
    labels = infer_labels(raw, settings)
    base = body_size(raw)
    raw_notes = split_footnotes(raw)
    drafts = build_blocks(raw, labels, base)
    doc = Document(sections=[])

    roots: list[Section] = []
    stack: list[Section] = []
    preamble: Section | None = None
    page_owner: dict[int, Section] = {}  # страница → глава, к которой она относится
    ref_pages: dict[tuple[str, int], int] = {}  # (блок, позиция знака) → страница
    ref_markers: dict[tuple[str, int], str] = {}  # (блок, позиция знака) → текст знака

    def attach(section: Section) -> None:
        while stack and stack[-1].level >= section.level:
            stack.pop()
        (stack[-1].children if stack else roots).append(section)
        stack.append(section)

    for draft in drafts:
        if draft.kind == "heading":
            level = draft.heading_level if draft.heading_level is not None else 1
            attach(Section(new_id("sec"), section_kind(draft.text), draft.text, level))
            page_owner.setdefault(draft.page_pos, stack[-1])
            continue
        if not stack and preamble is None:
            preamble = Section(new_id("sec"), "main", "", 1)
            roots.append(preamble)
            stack.append(preamble)
        target = stack[-1]
        block = Block(
            new_id("p"),
            draft.kind,
            draft.text,
            lang.detect(draft.text, settings.language),
            pages=draft.pages,
            detail=draft.detail,
            detail_code=draft.detail_code,
            page=draft.page,
        )
        block.notes = [NoteRef(offset, key) for offset, key, _, _ in draft.notes]
        ref_pages.update({(block.id, offset): page for offset, _, page, _ in draft.notes})
        ref_markers.update({(block.id, offset): text for offset, _, _, text in draft.notes})
        target.blocks.append(block)
        page_owner.setdefault(draft.page_pos, target)

    for section in [s for root in roots for s in root.walk()]:
        visible, searchable = SECTION_KIND_DEFAULTS[section.kind]
        section.visible = visible
        section.searchable = settings.section_kinds.get(section.kind, searchable)

    if not any(s.title for root in roots for s in root.walk()):
        doc.warn(
            "no_structure", "Нет ни заголовков, ни печатного оглавления: источник одним разделом"
        )
    doc.sections = roots
    owners: dict[int, Section] = {}
    last: Section | None = None
    for pos in range(len(raw.pages)):
        last = page_owner.get(pos, last)
        if last is not None:
            owners[pos] = last
    _link_footnotes(doc, raw_notes, new_id, owners, ref_pages, ref_markers)
    _compare_toc(doc)
    _compare_bookmarks(doc, raw)
    return doc


def _link_footnotes(
    doc: Document,
    raw_notes: list[_RawNote],
    new_id: Callable[[str], str],
    owners: dict[int, Section],
    ref_pages: dict[tuple[str, int], int],
    ref_markers: dict[tuple[str, int], str],
) -> None:
    """Связывает знаки с текстами сносок.

    Идентификаторы HTML и EPUB совпадают точно. Номера ищутся по порядку следования и с
    предпочтением той же страницы: нумерация может начинаться заново в каждой главе.
    """
    used: set[int] = set()
    for section, block in list(doc.blocks()):
        kept: list[NoteRef] = []
        for ref in block.notes:
            page = ref_pages.get((block.id, ref.offset))
            candidates = [n for n in raw_notes if n.key == ref.footnote_id and n.order not in used]
            same_page = [n for n in candidates if n.page_pos == page]
            later = [n for n in candidates if page is None or n.page_pos >= page]
            note = (same_page or later or candidates or [None])[0]
            if note is None:
                doc.warn(
                    "unlinked_marker",
                    f"Знак сноски «{ref.footnote_id}» без текста сноски",
                    block_id=block.id,
                )
                continue
            used.add(note.order)
            marker = ref_markers.get((block.id, ref.offset)) or note.key
            footnote = Footnote(new_id("f"), marker, note.text.strip(), True)
            section.footnotes.append(footnote)
            kept.append(NoteRef(ref.offset, footnote.id))
        block.notes = kept
    for note in raw_notes:
        if note.order in used:
            continue
        owner = owners.get(note.page_pos) or (doc.sections[0] if doc.sections else None)
        if owner is None:
            continue
        owner.footnotes.append(
            Footnote(new_id("f"), note.key if len(note.key) <= 3 else "*", note.text.strip(), False)
        )
        doc.warn("unlinked_note", f"Текст сноски «{note.key}» без знака в тексте")


def printed_toc(doc: Document) -> list[str]:
    titles = []
    for section in doc.walk():
        if section.kind != "toc":
            continue
        for block in section.blocks:
            for line in block.text.split("\n") if "\n" in block.text else [block.text]:
                match = _TOC_LINE_RE.match(line.strip())
                if match:
                    titles.append(match.group("title").strip())
    return titles


def _compare_toc(doc: Document) -> None:
    toc = printed_toc(doc)
    if not toc:
        return
    headings = {lang.normalize_text(s.title) for s in doc.walk() if s.title and s.kind != "toc"}
    for title in toc:
        if lang.normalize_text(title) not in headings:
            doc.warn(
                "toc_mismatch",
                f"В печатном оглавлении есть «{title}», в тексте такого заголовка нет",
            )


def _compare_bookmarks(doc: Document, raw: RawDocument) -> None:
    """Закладки PDF (printed_toc) сверяются с заголовками; расхождения — предупреждения.

    Закладка вне документа и заголовок, которого нет в тексте, — предупреждение с названием и
    страницей из закладки.
    """
    if not raw.printed_toc:
        return
    titles = {lang.normalize_text(s.title) for s in doc.walk() if s.title and s.kind != "toc"}
    # Где заголовок встретился в тексте на самом деле: имя закладки → фактическая страница.
    actual_pages = _heading_pages(raw)
    for entry in raw.printed_toc:
        title = entry[1]
        page = entry[2] if len(entry) > 2 else None
        if page is not None and not (1 <= page <= len(raw.pages)):
            doc.warn(
                "toc_mismatch",
                f"Закладка «{title}» указывает на страницу {page}, которой нет в документе",
                page=str(page),
            )
            continue
        key = lang.normalize_text(title)
        if key not in titles:
            where = f", с. {page}" if page is not None else ""
            doc.warn(
                "toc_mismatch",
                f"В печатном оглавлении есть «{title}», в тексте такого заголовка нет{where}",
                page=str(page) if page is not None else None,
            )
            continue
        # Заголовок нашёлся, но не там, куда указывает закладка: печатное оглавление
        # разошлось с текстом — об этом и предупреждаем (сценарий «Расхождение»).
        actual = actual_pages.get(key)
        if page is not None and actual is not None and actual != page:
            doc.warn(
                "toc_mismatch",
                f"Закладка «{title}» указывает на страницу {page}, "
                f"а заголовок в тексте на странице {actual}",
                page=str(page),
            )


def _heading_pages(raw: RawDocument) -> dict[str, int]:
    """Нормализованный текст заголовка → номер напечатанной страницы, где он встретился."""
    pages: dict[str, int] = {}
    for index, page in enumerate(raw.pages):
        number = _page_number(page.printed_label) if page.printed_label else index + 1
        if number < 0:
            number = index + 1
        for line in page.lines:
            if line.heading_level:
                pages.setdefault(lang.normalize_text(line.text), number)
    return pages


def _page_number(label: str) -> int:
    """Номер страницы из подписи: «12» → 12; римские и пустые цифр не дают."""
    digits = re.sub(r"\D", "", str(label))
    return int(digits) if digits else -1
