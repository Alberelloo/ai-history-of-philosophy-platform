"""Требования спецификации text-quality-check."""

from __future__ import annotations

import pytest

from philograph.library import quality
from philograph.library.extract import extract_txt
from philograph.library.model import RawDocument, RawLine, RawPage

from .builders import BODY, epub, pdf

req = pytest.mark.req
QC = "text-quality-check"
GOOD = "Всякое знание начинается с опыта, но не всё оно происходит из опыта и чувств."


def scan_pdf(pages: int) -> bytes:
    return pdf([[] for _ in range(pages)])


@req(QC, "Какие версии проверяются")
def test_which_versions_need_human_review(lib):
    lib.files["scan.pdf"] = scan_pdf(3)
    scan = lib.pipeline.start(
        "operator", lib.register(title="Скан", files=[{"name": "s", "path": "scan.pdf"}])
    )
    assert lib.registry.version(scan)["state"] == "awaiting_quality"

    lib.files["layer.pdf"] = pdf([[("Knowledge begins with experience and the senses.", BODY)]])
    layer = lib.pipeline.start(
        "operator",
        lib.register(title="Слой", language="en", files=[{"name": "l", "path": "layer.pdf"}]),
    )
    assert lib.registry.version(layer)["state"] == "awaiting_quality"

    lib.files["book.epub"] = epub([("Глава 1", f"<p>{GOOD}</p>")])
    clean = lib.pipeline.start(
        "operator", lib.register(title="EPUB", files=[{"name": "e", "path": "book.epub"}])
    )
    assert lib.registry.version(clean)["state"] == "checked"


@req(QC, "Автоматические метрики")
def test_page_metrics(events):
    broken = extract_txt(GOOD.encode("utf-8").decode("latin-1").encode("utf-8"))
    metrics = quality.page_metrics(broken.pages[0], ["ru"])
    assert metrics.mojibake_share > 0.2

    prereform = RawPage(0, [RawLine("Познаніе есть дѣло разума и опыта, а не однихъ чувствъ.")])
    assert quality.page_metrics(prereform, ["ru"]).dictionary_share == pytest.approx(1.0)

    good = quality.page_metrics(RawPage(0, [RawLine(GOOD, confidence=0.9)]), ["ru"])
    assert good.confidence == 0.9 and good.garbage_share == 0 and not good.empty


@req(QC, "Отсев явно плохого текста")
def test_bad_text_deferred_automatically(lib, events):
    lib.ocr.text = "Пзн ние ывк рдпл зщшк ьъщ шгнр квфр тнгл щзх прлд вкнр"
    lib.files["bad.pdf"] = scan_pdf(2)
    version_id = lib.pipeline.start(
        "operator", lib.register(files=[{"name": "b", "path": "bad.pdf"}])
    )
    version = lib.registry.version(version_id)
    assert version["state"] == "deferred"
    assert version["deferred_reason"] == "низкое качество распознавания"
    assert events.one("library.quality.assessed")["defer_reason"] == version["deferred_reason"]

    strict = quality.QualitySettings(min_dictionary_share=0.99)
    page = RawDocument([RawPage(0, [RawLine("Кант пишет о вещах в себе ябвгд.")])], "txt", False)
    assert quality.assess(page, ["ru"], strict, seed="x").defer_reason is not None


@req(QC, "Выборка страниц для просмотра")
def test_review_sample(lib):
    lib.files["scan.pdf"] = scan_pdf(12)
    version_id = lib.pipeline.start(
        "operator", lib.register(files=[{"name": "s", "path": "scan.pdf"}])
    )
    sample = lib.pipeline.review_sample(version_id)
    settings = lib.pipeline.settings.quality
    assert settings.random_pages <= len(sample) <= settings.random_pages + settings.worst_pages
    page = sample[0]
    assert page["image"] and lib.pipeline.files.exists(page["image"])
    assert page["text"].startswith("Распознанный текст")
    assert "suspicious" in page


@req(QC, "Решение по качеству")
def test_quality_decision(lib, events):
    lib.files["scan.pdf"] = scan_pdf(2)
    accept = lib.pipeline.start("operator", lib.register(files=[{"name": "s", "path": "scan.pdf"}]))
    assert lib.pipeline.decide_quality("operator", accept, "accept") == "checked"
    decision = lib.registry.version(accept)["quality"]["decision"]
    assert decision["actor"] == "operator" and decision["time"]

    lib.ocr.text = "Другой распознанный текст о скептицизме Юма и привычке ума."
    defer = lib.pipeline.start(
        "operator", lib.register(title="Другой", files=[{"name": "s", "path": "scan.pdf"}])
    )
    lib.pipeline.decide_quality("operator", defer, "defer", "много ошибок в греческих цитатах")
    version = lib.registry.version(defer)
    assert version["state"] == "deferred"
    assert version["deferred_reason"] == "много ошибок в греческих цитатах"
    assert [e["decision"] for e in events.of("library.quality.decided")] == ["accept", "defer"]


@req(QC, "Отложенные версии")
def test_deferred_versions_retry(lib):
    lib.files["scan.pdf"] = scan_pdf(2)
    source_id = lib.register(files=[{"name": "s", "path": "scan.pdf"}])
    first = lib.pipeline.start("operator", source_id)
    lib.pipeline.decide_quality("operator", first, "defer", "нет греческого")
    assert [d["id"] for d in lib.pipeline.deferred()] == [first]
    lib.registry.update_settings("operator", source_id, ocr_languages=["rus", "grc"])
    second = lib.pipeline.start("operator", source_id)
    assert second != first
    assert lib.registry.version(first)["state"] == "deferred"  # осталась в истории


@req(QC, "Перенос решения на неизменённый текст")
def test_decision_carried_over(lib, events):
    lib.files["scan.pdf"] = scan_pdf(2)
    source_id = lib.register(files=[{"name": "s", "path": "scan.pdf"}])
    v1 = lib.pipeline.start("operator", source_id)
    lib.pipeline.decide_quality("operator", v1, "accept")
    lib.registry.publish("operator", v1)
    lib.registry.update_settings("operator", source_id, header_patterns=[r"^НИКОГДА$"])
    calls = lib.ocr.calls
    v2 = lib.pipeline.start("operator", source_id)
    assert lib.registry.version(v2)["state"] == "checked"
    assert lib.ocr.calls == calls  # распознавание не повторялось
    carried = events.where("library.quality.decided", carried_over=v1)
    assert carried and carried[0]["actor"] == "system"


@req(QC, "Эталонные страницы")
def test_golden_pages_error_rates(lib):
    lib.files["scan.pdf"] = scan_pdf(2)
    source_id = lib.register(files=[{"name": "s", "path": "scan.pdf"}])
    version_id = lib.pipeline.start("operator", source_id)
    lib.pipeline.save_golden_page(
        "operator", source_id, 0, "Распознанный текст страницы о познании и опыте."
    )
    lib.pipeline.save_golden_page(
        "operator", source_id, 1, "Распознанный текст страницы о познании и разуме."
    )
    report = lib.pipeline.golden_report(version_id)
    assert report["pages"][0] == {"cer": 0.0, "wer": 0.0}
    assert report["pages"][1]["wer"] == pytest.approx(1 / 7, abs=1e-3)
    assert report["wer"] == pytest.approx(report["pages"][1]["wer"] / 2, abs=1e-3)
    assert quality.error_rates("кот", "кит") == {"cer": round(1 / 3, 4), "wer": 1.0}
