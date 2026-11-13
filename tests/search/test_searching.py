"""Требования спецификации paragraph-search."""

from __future__ import annotations

import pytest

req = pytest.mark.req
PS = "paragraph-search"


@pytest.fixture
def ready(rig):
    rig.publish("ru")
    rig.publish("en")
    return rig


def texts(result):
    return [r["text"] for r in result["results"]]


@req(PS, "Гибридный поиск")
def test_hybrid_finds_by_meaning_and_words(ready):
    meaning = ready.search("почему из прошлого нельзя вывести будущее")
    top = meaning["results"][0]
    assert "проблема индукции" in top["text"] and "semantic" in top["found_by"]
    for key in ("paragraph_id", "source_id", "chapter_id", "text", "score", "found_by"):
        assert key in top
    exact = ready.search("tabula rasa")
    assert "Образ tabula rasa" in texts(exact)[0] and "lexical" in exact["results"][0]["found_by"]


@req(PS, "Нормализация слов")
def test_morphology_case_and_old_spelling(ready, rig):
    found = texts(ready.search("Канту", languages=["ru"], per_chapter=10))
    assert any("Кант отвечает" in t for t in found)
    assert any("Кантом" in t for t in found) and any("Канту важно" in t for t in found)
    rig.files["ru.txt"] = "Глава 1\n\nПознаніе начинается съ опыта.\n".encode()
    rig.publish("ru")
    assert any("Познаніе" in t for t in texts(rig.search("познание", languages=["ru"])))


@req(PS, "Запросы на других языках")
def test_cross_language(ready):
    found = ready.search("чистая доска", languages=["en"])
    assert any("blank slate" in t for t in texts(found))


@req(PS, "Фильтры")
def test_filters(ready):
    only_ru = ready.search("опыт", sources=[ready.ids["ru"]])
    assert only_ru["results"] and {r["source_id"] for r in only_ru["results"]} == {ready.ids["ru"]}
    excluded = ready.search("tabula rasa", exclude=[ready.paragraph("ru", "tabula rasa")])
    assert all("Образ tabula" not in t for t in texts(excluded))


@req(PS, "Видимость и публикация")
def test_unpublished_not_returned(ready):
    ready.registry.unpublish("operator", ready.ids["en"])
    ready.sync()
    assert all(r["source_id"] != ready.ids["en"] for r in ready.search("blank slate")["results"])


@req(PS, "Соседний контекст")
def test_neighbors_and_section_title(ready):
    result = ready.search("привычка ума", sources=[ready.ids["ru"]], neighbors=1)
    top = result["results"][0]
    assert top["section_title"] == "Глава 1. Юм"
    assert "проблема индукции" in top["neighbors"]["before"][0]["text"]
    assert "Хьюм" in top["neighbors"]["after"][0]["text"]


@req(PS, "Разнообразие результатов")
def test_per_chapter_limit(ready):
    result = ready.search("Кант категории рассудок разум", sources=[ready.ids["ru"]], per_chapter=2)
    chapters = [r["chapter_id"] for r in result["results"]]
    assert max(chapters.count(c) for c in set(chapters)) <= 2


@req(PS, "Расширение запроса")
def test_query_expansion(ready, events):
    result = ready.search("Юм в переводах", extra_terms=["Хьюм"], sources=[ready.ids["ru"]])
    hit = next(r for r in result["results"] if "Хьюм" in r["text"])
    assert "expansion" in hit["found_by"] or "lexical" in hit["found_by"]
    plain = ready.search("Юм", sources=[ready.ids["ru"]])
    assert all("expansion" not in r["found_by"] for r in plain["results"])
    expanded = ready.search("Юм", extra_terms=["Хьюм"], sources=[ready.ids["ru"]])
    assert any("expansion" in r["found_by"] for r in expanded["results"]) or any(
        "Хьюм" in r["text"] for r in expanded["results"]
    )
    assert events.of("search.query.completed")[-1]["expanded"] >= 0


@req(PS, "Деградация")
def test_lexical_only_when_embeddings_down(ready, events):
    ready.provider.fail = True
    result = ready.search("привычка ума")
    assert result["semantic_used"] is False and result["results"]
    assert all(r["found_by"] == ["lexical"] for r in result["results"])
    events.one("search.semantic.unavailable")


@req(PS, "Пустой результат")
def test_empty_when_nothing_relevant(ready):
    assert ready.search("добродетель и благо в этике стоиков")["results"] == []


@req(PS, "Скорость поиска")
def test_timings_logged(ready, events):
    ready.search("причинность")
    event = events.of("search.query.completed")[-1]
    for part in ("embed_ms", "semantic_ms", "lexical_ms", "fusion_ms"):
        assert event[part] >= 0


@req(PS, "Деградация")
def test_dimension_mismatch_degrades_with_reason(ready, events):
    """Коллекция другой размерности: смысловая часть деградирует с причиной, текст работает."""
    from dataclasses import dataclass

    @dataclass
    class WrongDim:
        model: str = "concept-v1"
        dimension: int = 4

        def embed(self, texts, *, budget):
            return [[0.0] * self.dimension for _ in texts]

    ready.searcher.embedder = WrongDim()
    result = ready.search("привычка ума")
    assert result["semantic_used"] is False
    assert result["results"]
    assert all(r["found_by"] == ["lexical"] for r in result["results"])
    event = events.one("search.semantic.unavailable")
    assert event["reason"] == "dimension_mismatch"
    assert event["model"] == "concept-v1"
    assert event["collection_dimension"] == 7
    assert event["embedder_dimension"] == 4


@req(PS, "Гибридный поиск")
def test_search_is_hybrid_again_after_dimension_fixed(ready, events):
    """После исправления модели поиск снова гибридный, событие больше не выдаётся."""
    from dataclasses import dataclass

    @dataclass
    class WrongDim:
        model: str = "concept-v1"
        dimension: int = 4

        def embed(self, texts, *, budget):
            return [[0.0] * self.dimension for _ in texts]

    ready.searcher.embedder = WrongDim()
    assert ready.search("привычка ума")["semantic_used"] is False
    events.clear()

    ready.searcher.embedder = ready.indexer.embedder  # исправленная модель
    result = ready.search("привычка ума")
    assert result["semantic_used"] is True
    assert any("semantic" in r["found_by"] for r in result["results"])
    events.assert_none("search.semantic.unavailable")
