"""Требования спецификации document-structure, которые проверяются на уровне разбора."""

from __future__ import annotations

import pytest

from philograph.library import checks, corrections
from philograph.library.extract import extract, extract_epub
from philograph.library.matching import Item, match
from philograph.library.model import Block, Document, Section

from .builders import BODY, SMALL, TITLE, epub, ids, line, parse_raw, pdf, scan

req = pytest.mark.req
DS = "document-structure"


def texts(doc):
    return [b.text for _, b in doc.blocks()]


@req(DS, "Единая структура документа")
def test_formats_share_one_structure():
    book = epub(
        [
            (
                "Глава 1. Опыт",
                "<p>Всякое знание начинается с опыта.</p>"
                "<blockquote><p>Мысли без содержания пусты.</p></blockquote>"
                '<pre class="verse">Строка первая\nСтрока вторая</pre>',
            )
        ]
    )
    from_epub = parse_raw(extract_epub(book))
    from_scan = parse_raw(
        scan(
            [
                line("Глава 1. Опыт", size=TITLE, start=True),
                line("Всякое знание начинается с опыта.", start=True),
            ]
        )
    )
    for doc in (from_epub, from_scan):
        assert [s.title for s in doc.walk()] == ["Глава 1. Опыт"]
        assert doc.sections[0].blocks[0].text == "Всякое знание начинается с опыта."
    kinds = [b.kind for _, b in from_epub.blocks()]
    assert kinds == ["paragraph", "quote", "verse"]
    assert from_epub.sections[0].blocks[2].text == "Строка первая\nСтрока вторая"


@req(DS, "Виды разделов")
def test_section_kinds_control_reading_and_search():
    doc = parse_raw(
        extract(
            "Глава 1. Опыт\n\nТекст главы.\n\nСписок литературы\n\nЮм Д. Трактат.\n\n"
            "Именной указатель\n\nКант 12, 15\n".encode(),
            "txt",
        )
    )
    by_title = {s.title: s for s in doc.walk()}
    assert by_title["Список литературы"].kind == "bibliography"
    assert by_title["Список литературы"].visible and not by_title["Список литературы"].searchable
    index = by_title["Именной указатель"]
    assert index.kind == "index" and not index.visible and not index.searchable
    searchable = parse_raw(
        extract("Именной указатель\n\nКант 12\n".encode(), "txt"), section_kinds={"index": True}
    )
    assert searchable.sections[0].searchable


@req(DS, "Оглавление источника")
def test_printed_toc_compared_with_headings():
    text = (
        "Оглавление\n\nГлава 1. Опыт ........ 5\n\nГлава 2. О скептицизме ........ 20\n\n"
        "Глава 1. Опыт\n\nТекст.\n"
    )
    doc = parse_raw(extract(text.encode(), "txt"))
    warnings = [i for i in doc.issues if i.code == "toc_mismatch"]
    assert len(warnings) == 1 and "О скептицизме" in warnings[0].message

    flat = parse_raw(extract("Просто текст без заголовков.\n\nЕщё абзац.\n".encode(), "txt"))
    assert len(flat.sections) == 1
    assert any(i.code == "no_structure" for i in flat.issues)


@req(DS, "Склейка абзацев")
def test_lines_and_hyphens_joined():
    doc = parse_raw(
        scan(
            [
                line("Глава 1", size=TITLE, start=True),
                line("Теория позна-", start=True),
                line("ния и кто-"),
                line("то ещё, кто про-"),
            ],
            [line("должает мысль.", start=True)],
        )
    )
    assert texts(doc) == ["Теория познания и кто-то ещё, кто продолжает мысль."]
    block = doc.sections[0].blocks[0]
    assert [m.label for m in block.pages][-1] is None or len(block.pages) == 2
    assert block.pages[1].offset == block.text.index("должает")


@req(DS, "Язык абзаца")
def test_paragraph_language():
    doc = parse_raw(
        extract(
            (
                "Глава 1\n\nКант пишет о познании и опыте разума весьма подробно.\n\n"
                "Cogito ergo sum, et nihil est in intellectu quod non fuerit in sensu.\n\n"
                "Декарт формулирует (cogito ergo sum) как первую достоверность.\n"
            ).encode(),
            "txt",
        )
    )
    assert [b.lang for _, b in doc.blocks()] == ["ru", "la", "ru"]


@req(DS, "Колонтитулы и служебные элементы")
def test_running_headers_removed_and_page_number_kept():
    bodies = [
        "Юм начинает с впечатлений",
        "Кант отвечает Юму",
        "Локк говорит об опыте",
        "Лейбниц возражает Локку",
        "Беркли отрицает материю",
    ]
    pages = []
    for n, body in enumerate(bodies):
        pages.append(
            [
                line(f"Глава 1. Опыт   {40 + n}", size=SMALL),
                line(f"{body}.", start=True),
                line("и далее развивает мысль.", start=False),
                line("Ещё одно предложение текста.", start=True),
                line("______", size=SMALL),
            ]
        )
    doc = parse_raw(scan(*pages))
    assert all("Глава 1. Опыт" not in t and "____" not in t for t in texts(doc))
    labels = [m.label for _, b in doc.blocks() for m in b.pages]
    assert labels == ["40", "41", "42", "43", "44"]
    assert texts(doc)[0] == "Юм начинает с впечатлений. и далее развивает мысль."


@req(DS, "Страницы печатного издания")
def test_page_labels_roman_spreads_and_plates():
    doc = parse_raw(
        scan(
            [
                line("Предисловие", size=TITLE, start=True),
                line("Текст предисловия начинается", start=True),
                line("xi"),
            ],
            [line("и продолжается.", start=False), line("xii")],
        )
    )
    assert [m.label for m in doc.sections[0].blocks[0].pages] == ["xi", "xii"]

    plate = parse_raw(
        scan(
            [line("Начало абзаца на странице", start=True), line("64")],
            [line("", kind="figure", start=True)],
            [line("и его конец.", start=False), line("65")],
        )
    )
    labels = [m.label for _, b in plate.blocks() for m in b.pages]
    assert "65" in labels and "64" in labels  # нумерация после вклейки не сдвинулась
    assert "66" not in labels

    from philograph.library.extract import extract_pdf

    spread = pdf([[("Left page text.", BODY), ("Right page text.", BODY, 400)]])
    raw = extract_pdf(spread, languages=["eng"], ocr=None, spreads=True)
    assert len(raw.pages) == 2
    assert [p.lines[0].text for p in raw.pages] == ["Left page text.", "Right page text."]


@req(DS, "Сноски")
def test_footnotes_removed_from_flow_and_linked():
    doc = parse_raw(
        scan(
            [
                line("Глава 1", size=TITLE, start=True),
                line("Кант пишет о вещи в себе1 и затем", start=True, note_at=24),
                line("1 Критика чистого разума, B XXVI.", size=SMALL),
            ],
            [line("продолжает рассуждение.")],
        )
    )
    block = doc.sections[0].blocks[0]
    assert block.text == "Кант пишет о вещи в себе1 и затем продолжает рассуждение."
    note = doc.sections[0].footnotes[0]
    assert note.text == "Критика чистого разума, B XXVI." and note.linked
    assert block.notes[0].footnote_id == note.id

    endnotes = parse_raw(
        scan(
            [
                line("Глава 1", size=TITLE, start=True),
                line("Первая1 мысль.", start=True, note_at=6),
            ],
            [
                line("Глава 2", size=TITLE, start=True),
                line("Вторая1 мысль.", start=True, note_at=6),
            ],
            [
                line("Примечания", size=TITLE, start=True),
                line("1 К первой главе.", size=SMALL),
                line("1 Ко второй главе.", size=SMALL),
            ],
        )
    )
    first, second = endnotes.sections[0], endnotes.sections[1]
    assert first.footnotes[0].text == "К первой главе."
    assert second.footnotes[0].text == "Ко второй главе."


@req(DS, "Сноски")
def test_footnote_in_continued_line_is_linked():
    # знак сноски во второй строке абзаца (нашлось на настоящем скане archive.org)
    doc = parse_raw(
        scan(
            [
                line("Глава 1", size=TITLE, start=True),
                line("Гераклит, которого за любовь", start=True),
                line("к парадоксам звали Тёмным,1 жил в Эфесе.", note_at=26),
                line("1 Диоген Лаэртский, IX.", size=SMALL),
            ]
        )
    )
    block = doc.sections[0].blocks[0]
    assert block.text.startswith("Гераклит, которого за любовь к парадоксам")
    note = doc.sections[0].footnotes[0]
    assert note.text == "Диоген Лаэртский, IX." and note.linked
    assert block.notes[0].footnote_id == note.id


@req(DS, "Несвязанные сноски")
def test_unlinked_footnote_kept_at_chapter_end():
    doc = parse_raw(
        scan(
            [
                line("Глава 3", size=TITLE, start=True),
                line("Текст без распознанного знака.", start=True),
                line("1 Потерянная сноска.", size=SMALL),
            ]
        )
    )
    note = doc.sections[0].footnotes[0]
    assert note.text == "Потерянная сноска." and not note.linked
    assert any(i.code == "unlinked_note" for i in doc.issues)


@req(DS, "Непереданные элементы")
def test_unrendered_elements_leave_placeholder():
    doc = parse_raw(
        scan(
            [
                line("Глава 1", size=TITLE, start=True),
                line("Портрет Канта", kind="figure", start=True),
                line("120"),
            ]
        )
    )
    block = doc.sections[0].blocks[0]
    assert block.kind == "unrendered" and block.detail == "иллюстрация, с. 120"
    assert block.text == "Портрет Канта"


@req(DS, "Текст как в источнике")
def test_original_orthography_preserved():
    text = "Глава I\n\nПознаніе есть дѣло разума, а не чувствъ.\n"
    doc = parse_raw(extract(text.encode(), "txt"))
    assert texts(doc) == ["Познаніе есть дѣло разума, а не чувствъ."]


@req(DS, "Сопоставление с прежней версией")
def test_matching_keeps_ids_for_minor_changes():
    old = [Item("p-a", "Теория познания изучает познапие."), Item("p-b", "Второй абзац.")]
    new = [
        Item("t1", "Теория познания изучает познание."),
        Item("t2", "Совсем другой текст о логике Гегеля."),
    ]
    result = match(old, new, ids())
    assert result.ids["t1"] == "p-a" and "p-a" in result.changed
    assert result.ids["t2"] not in {"p-a", "p-b"} and result.removed == ["p-b"]


@req(DS, "Разбиение и слияние абзацев")
def test_split_and_merge():
    old = [
        Item("A", "Первая половина мысли о причинности у Юма"),
        Item("B", "и вторая половина той же мысли о привычке."),
    ]
    merged = [
        Item(
            "t1",
            "Первая половина мысли о причинности у Юма и вторая половина той же мысли о привычке.",
        )
    ]
    result = match(old, merged, ids())
    assert result.ids["t1"] == "A" and result.redirected == {"B": "A"} and not result.removed

    whole = [
        Item(
            "C",
            "Кант отвечает Юму в первой Критике и затем развивает ответ в Пролегоменах подробно.",
        )
    ]
    split = [
        Item("t1", "Кант отвечает Юму в первой Критике"),
        Item("t2", "и затем развивает ответ в Пролегоменах подробно."),
    ]
    result = match(whole, split, ids())
    assert (
        result.ids["t1"] == "C" and result.ids["t2"] != "C" and result.ids["t2"] in (result.added)
    )


@req(DS, "Сводка изменений версии")
def test_change_summary():
    old = [Item("p1", "Один."), Item("p2", "Два с опечаткой познапие."), Item("p3", "Три.")]
    new = [
        Item("t1", "Один."),
        Item("t2", "Два с опечаткой познание."),
        Item("t4", "Четыре новых слова."),
    ]
    result = match(old, new, ids())
    assert result.summary() == {
        "added": 1,
        "changed": 1,
        "removed": 1,
        "redirected": 0,
        "unchanged": 1,
    }
    assert result.changed == ["p2"]


def _doc() -> Document:
    return Document(
        sections=[
            Section(
                "s1",
                "main",
                "Глава 1",
                1,
                blocks=[
                    Block("p1", "paragraph", "Ложный заголовок жирным", "ru"),
                    Block("p2", "paragraph", "Текст с опечаткой познапие.", "ru"),
                ],
            )
        ]
    )


@req(DS, "Ручные правки")
def test_operator_corrections_applied():
    doc = _doc()
    fix = corrections.Correction(
        1,
        "replace_text",
        corrections.Anchor("p2", exact="познапие", prefix="опечаткой "),
        {"text": "познание"},
    )
    kind = corrections.Correction(2, "set_block_kind", corrections.Anchor("p1"), {"kind": "quote"})
    assert corrections.apply(doc, [fix, kind], ids()) == []
    assert doc.sections[0].blocks[1].text == "Текст с опечаткой познание."
    assert doc.sections[0].blocks[0].kind == "quote"


@req(DS, "Правки переживают повторную обработку")
def test_corrections_reapplied_or_reported():
    fix = corrections.Correction(
        1, "replace_text", corrections.Anchor("p2", exact="познапие"), {"text": "познание"}
    )
    reparsed = _doc()
    reparsed.sections[0].blocks[1].id = "p2"
    assert corrections.apply(reparsed, [fix], ids()) == []
    assert "познание" in reparsed.sections[0].blocks[1].text

    gone = Document(
        sections=[
            Section(
                "s1",
                "main",
                "Глава 1",
                1,
                blocks=[Block("p9", "paragraph", "Совсем другой разбор.", "ru")],
            )
        ]
    )
    assert corrections.apply(gone, [fix], ids()) == [fix]


@req(DS, "Автоматические проверки структуры")
def test_checks_errors_and_warnings():
    doc = _doc()
    doc.sections[0].blocks.append(Block("p3", "paragraph", "  ", "ru"))
    issues = checks.check(doc)
    assert checks.has_errors(issues)
    assert any(i.code == "empty_block" and i.block_id == "p3" for i in issues)

    clean = _doc()
    clean.warn("unlinked_note", "Текст сноски «1» без знака")
    clean.warn("unlinked_note", "Текст сноски «2» без знака")
    issues = checks.check(clean)
    assert not checks.has_errors(issues) and len(issues) == 2


@req(DS, "Сноски")
def test_footnotes_of_gutenberg_and_wikisource_html():
    from philograph.library.extract import extract_html
    from philograph.library.model import RawDocument

    gutenberg = (
        "<html><body><h2>PART I</h2>"
        '<p>Mr. Locke has proved it<a href="ch1.xhtml#fn1.3" id="fnref1.3">[3]</a> long ago.</p>'
        '<p class="footnote"><a id="fn1.3"/> <a href="ch1.xhtml#fnref1.3">[3]</a> '
        "Dr. Berkeley, Introduction.</p></body></html>"
    )
    wikisource = (
        "<html><body><h2>Essay 1</h2>"
        '<p>Philosophy may be treated<sup class="mw-ref reference">'
        '<a href="./Essays#cite_note-1">[1]</a></sup> after two manners.</p>'
        '<ol class="mw-references references"><li id="cite_note-1">'
        '<span class="mw-reference-text">See the Treatise.</span></li></ol></body></html>'
    )
    for page, expected in (
        (gutenberg, "Dr. Berkeley, Introduction."),
        (wikisource, "See the Treatise."),
    ):
        pages, _ = extract_html(page)
        doc = parse_raw(RawDocument(pages=pages, fmt="html", paginated=False))
        notes = [f for s in doc.sections for f in s.footnotes]
        assert [n.text for n in notes] == [expected], [b.text for _, b in doc.blocks()]
        assert notes[0].linked
        assert all(expected not in b.text for _, b in doc.blocks())


@req(DS, "Страницы печатного издания")
def test_page_label_outlier_from_running_footer_is_ignored():
    from philograph.library.model import RawDocument, RawPage
    from philograph.library.parse import ParseSettings, infer_labels

    # колонтитул с годом «2022» дал ложный номер между 107 и 109
    labels = ["105", "106", "107", "2022", "109", "110"]
    raw = RawDocument(
        pages=[RawPage(i, [], printed_label=x) for i, x in enumerate(labels)],
        fmt="pdf",
        paginated=True,
    )
    assert infer_labels(raw, ParseSettings()) == ["105", "106", "107", "108", "109", "110"]


@req(DS, "Страницы печатного издания")
def test_chaotic_numbers_are_not_page_labels():
    from philograph.library.model import RawDocument, RawPage
    from philograph.library.parse import ParseSettings, infer_labels

    # числа из колонтитулов цифрового учебника вразнобой: это не нумерация страниц
    labels = ["2022", "108", "110", "370", "373", "1", "5", "6", "300", "12"]
    raw = RawDocument(
        pages=[RawPage(i, [], printed_label=x) for i, x in enumerate(labels)],
        fmt="pdf",
        paginated=True,
    )
    assert infer_labels(raw, ParseSettings()) == [None] * len(labels)
