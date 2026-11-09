"""Требования спецификаций entity-mentions и entity-cards."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from philograph.knowledge.app import build_app, library_paragraphs, subscribe
from philograph.knowledge.cards import Cards
from philograph.knowledge.mentions import Mentions, mention_metrics
from philograph.knowledge.statements import Attribution, Evidence, Provenance
from philograph.library.app import build_app as library_app
from philograph.library.reading import Reading
from philograph.llm import store as llm_store
from philograph.llm.app import build_app as llm_app
from philograph.llm.config import GatewayConfig
from philograph.llm.gateway import LLMGateway
from philograph.llm.providers import FakeProvider
from philograph.llm.templates import Template, TemplateRegistry
from philograph.platform.client import ServiceClient
from philograph.platform.queue import Queue
from philograph.platform.queue import migrations as queue_migrations
from philograph.prompts import PROMPTS

from ..helpers import asgi_transport
from ..library.conftest import lib  # noqa: F401

req = pytest.mark.req
EM = "entity-mentions"
EC = "entity-cards"

TEXT = (
    "Глава 1. Новое время\n\nСогласно Канту, причинности нельзя научиться из опыта.\n\n"
    "Юм возражал: Юм считал причинность привычкой, Юм был последователен.\n\n"
    "У него был большой опыт преподавания.\n\n"
    "Бэкон спорил с Гоббсом и Локком о методе.\n\n"
    "Трансцендентального идеализма придерживался Кант.\n\n"
    "Глава 2. Средние века\n\nБэкон писал об оптике.\n\n"
    "Глава 3. Кант о Юме\n\nСпор продолжался.\n"
)


@pytest.fixture
def mx(onto, lib, engine_for, clock):
    lib.files["book.txt"] = TEXT.encode()
    library = ServiceClient(
        "library",
        "http://library/api",
        transport=asgi_transport(library_app(Reading(lib.registry, lib.registry.engine))),
    )
    onto.statements.paragraph_text = library_paragraphs(library)
    ids = {}
    ids["kant"] = onto.person("Кант", "1724", "1804")
    ids["hume"] = onto.person("Юм", "1711", "1776")
    ids["causality"] = onto.thing("concept", "Причинность")
    ids["experience"] = onto.thing("concept", "Опыт")
    onto.entities.set_primary(ids["experience"], "common_word", True)
    ids["idealism"] = onto.thing("doctrine", "Трансцендентальный идеализм")
    ids["francis"] = onto.person("Бэкон", "1561", "1626")
    ids["roger"] = onto.person("Бэкон", "1214", "1292")
    ids["hobbes"] = onto.person("Гоббс", "1588", "1679")
    ids["locke"] = onto.person("Локк", "1632", "1704")
    mentions = Mentions(onto.statements, library)
    engine = engine_for(llm_store.migrations, queue_migrations)
    templates = TemplateRegistry()
    for spec in PROMPTS:
        templates.register(Template(spec.name, spec.instructions, spec.data_slots))
    provider = FakeProvider(default="Немецкий философ, автор трёх «Критик».")
    gateway = LLMGateway(
        GatewayConfig.model_validate(
            {
                "providers": {"fake": {"kind": "fake"}},
                "roles": {"main": {"provider": "fake", "model": "flash"}},
                "prices": {
                    "flash": {"input_cache_miss": 0.3, "input_cache_hit": 0.03, "output": 1.2}
                },
                "budgets": {"site": {"daily_limit_usd": 2.0}, "filling": {}},
            }
        ),
        {"fake": provider},
        templates,
        llm_store.Store(engine),
        clock=clock,
    )
    llm = ServiceClient("llm", "http://llm", transport=asgi_transport(llm_app(gateway)))
    cards = Cards(onto.statements, mentions, llm)
    queue = Queue(engine, clock)
    subscribe(queue, onto.statements, None, mentions)
    source = lib.register()

    def publish():
        lib.publish_new(source)
        lib.pipeline.dispatch_outbox(queue)
        queue.run_until_empty()

    def paragraph(needle):
        doc = lib.registry.load_document(lib.registry.get(source).published_version)
        return next(b for _, b in doc.blocks() if needle in b.text)

    return type(
        "MX",
        (),
        {
            "onto": onto,
            "lib": lib,
            "ids": ids,
            "mentions": mentions,
            "cards": cards,
            "provider": provider,
            "publish": publish,
            "paragraph": paragraph,
            "source": source,
            "gateway": gateway,
            "library": library,
        },
    )


def found(mx, needle):
    p = mx.paragraph(needle)
    return p, mx.mentions.for_targets([p.id])


# --- entity-mentions -----------------------------------------------------------------


@req(EM, "Поиск упоминаний с учётом склонений")
def test_inflected_and_phrase_mentions(mx):
    mx.publish()
    p, items = found(mx, "Согласно Канту")
    entities = {m["entity_id"] for m in items}
    assert {mx.ids["kant"], mx.ids["causality"]} <= entities
    kant = next(m for m in items if m["entity_id"] == mx.ids["kant"])
    assert p.text[kant["start"] : kant["end"]] == "Канту"
    _, phrase = found(mx, "Трансцендентального")
    idealism = [m for m in phrase if m["entity_id"] == mx.ids["idealism"]]
    assert len(idealism) == 1  # словосочетание — одно упоминание
    # Иностранные фамилии в косвенных падежах, которых нет в словаре или которые словарь
    # принимает за другое слово («Юма» — топоним).
    _, debate = found(mx, "Бэкон спорил")
    assert {mx.ids["hobbes"], mx.ids["locke"]} <= {m["entity_id"] for m in debate}
    for text in ("Критика Юма", "ответ Юму", "спор с Гоббсом", "книга Локка"):
        index, longest = mx.mentions._index()
        hits = {m["entity_id"] for m in mx.mentions.scan(text, index, longest, set())}
        assert hits & {mx.ids["hume"], mx.ids["hobbes"], mx.ids["locke"]}, text
    index, longest = mx.mentions._index()
    assert mx.mentions.scan("я верю в опыт", index, longest, set()) == []


@req(EM, "Общеупотребительные слова")
def test_common_word_only_as_term(mx):
    mx.publish()
    _, plain = found(mx, "большой опыт преподавания")
    assert all(m["entity_id"] != mx.ids["experience"] for m in plain)
    _, term = found(mx, "нельзя научиться из опыта")
    assert any(m["entity_id"] == mx.ids["experience"] for m in term)


@req(EM, "Неоднозначность")
def test_ambiguity_by_chapter_context(mx, events):
    statements = mx.onto.statements
    assert statements.contemporaries(mx.ids["francis"], mx.ids["hobbes"]) is True
    assert statements.contemporaries(mx.ids["roger"], mx.ids["hobbes"]) is False
    vague = mx.onto.thing("person", "Анонимный схоласт")
    statements.add(
        vague,
        "lifespan",
        value={
            "earliest_start": 1200,
            "latest_start": 1300,
            "earliest_end": 1250,
            "latest_end": 1350,
            "precision": "century",
            "original": "XIII в.",
        },
        attributions=[Attribution("common")],
    )
    assert statements.contemporaries(vague, mx.ids["roger"]) is None  # даты слишком размыты
    mx.publish()
    _, modern = found(mx, "Бэкон спорил")
    assert any(m["entity_id"] == mx.ids["francis"] for m in modern)  # рядом Гоббс и Локк
    _, medieval = found(mx, "Бэкон писал об оптике")
    assert medieval == []  # контекста нет — ссылку не ставим
    assert events.where("knowledge.mentions.unresolved", surface="Бэкон")


@req(EM, "Плотность упоминаний")
def test_first_occurrence_and_headings(mx):
    mx.publish()
    _, items = found(mx, "Юм возражал")
    assert len([m for m in items if m["entity_id"] == mx.ids["hume"]]) == 1
    version = mx.lib.registry.get(mx.source).published_version
    data = mx.library.get(f"internal/versions/{version}/paragraphs").json()
    heading = next(h for h in data["headings"] if h["text"] == "Глава 3. Кант о Юме")
    marks = mx.mentions.for_targets([heading["id"]])
    assert {m["entity_id"] for m in marks} == {mx.ids["kant"], mx.ids["hume"]}
    assert all(m["kind"] == "heading" for m in marks)


@req(EM, "Пересчёт")
def test_recompute_for_new_entity_only(mx, events):
    mx.publish()
    hobbes_before = mx.mentions.where_to_read(mx.ids["hobbes"])
    malebranche = mx.onto.person("Мальбранш")
    mx.lib.files["book.txt"] += "\nМальбранш учил об окказионализме.\n".encode()
    mx.publish()
    events.clear()
    count = mx.mentions.recompute_entity(malebranche)
    assert count == 1
    assert events.where("knowledge.mentions.indexed", mentions=1)
    assert mx.mentions.where_to_read(mx.ids["hobbes"]) == hobbes_before
    # Слияние переносит упоминания на оставшуюся сущность.
    hume_places = mx.mentions.where_to_read(mx.ids["hume"])
    kept = mx.onto.person("Дэвид Юм")
    merge_id = mx.onto.entities.merge(kept, mx.ids["hume"])
    assert hume_places and mx.mentions.where_to_read(kept) == hume_places
    mx.onto.entities.undo_merge(merge_id)
    assert mx.mentions.where_to_read(mx.ids["hume"]) == hume_places
    assert mx.mentions.where_to_read(kept) == []


@req(EM, "Показ при чтении")
def test_mentions_endpoint_and_degradation(mx):
    mx.publish()
    client = TestClient(build_app(mx.onto.statements, mentions=mx.mentions))
    p = mx.paragraph("Согласно Канту")
    response = client.get("/v1/mentions", params={"targets": p.id})
    assert response.status_code == 200 and response.json()
    kant = next(m for m in response.json() if m["entity_id"] == mx.ids["kant"])
    assert kant["entity_type"] == "person"  # N1: клиент красит подчёркивание цветом семьи
    # Без сервиса знаний клиент получает ошибку соединения и показывает главу без выделений:
    # это проверяет сквозной тест; здесь — что неизвестные абзацы дают пустой список.
    assert client.get("/v1/mentions", params={"targets": "nope"}).json() == []


@req(EM, "Где читать")
def test_where_to_read(mx):
    mx.publish()
    where = mx.mentions.where_to_read(mx.ids["kant"])
    assert len(where) == 2 and all(w["source_id"] == mx.source for w in where)
    assert [w["chapter_title"] for w in where] == ["Глава 1. Новое время", "Глава 3. Кант о Юме"]
    assert where[0]["source_title"] == mx.lib.registry.get(mx.source).title
    assert [w["count"] for w in where] == [2, 1]  # самые насыщенные главы первыми
    client = TestClient(build_app(mx.onto.statements, mentions=mx.mentions))
    assert client.get(f"/v1/entities/{mx.ids['kant']}/where").json() == where


@req(EM, "Где читать")
def test_where_to_read_first_paragraph(mx):
    """N10: «Где читать» ведёт к первому абзацу главы с упоминанием, а не к началу главы."""
    mx.publish()
    where = {w["chapter_title"]: w for w in mx.mentions.where_to_read(mx.ids["kant"])}
    first = mx.paragraph("Согласно Канту")
    assert where["Глава 1. Новое время"]["first_paragraph_id"] == first.id
    # В главе 3 Кант только в заголовке: абзаца нет, клиент ведёт к началу главы.
    assert where["Глава 3. Кант о Юме"]["first_paragraph_id"] is None
    # Пересчёт изменённого абзаца ниже по тексту порядок не ломает.
    mx.lib.files["book.txt"] = TEXT.replace(
        "Трансцендентального идеализма придерживался Кант.",
        "Трансцендентального идеализма придерживался именно Кант.",
    ).encode()
    mx.publish()
    where = {w["chapter_title"]: w for w in mx.mentions.where_to_read(mx.ids["kant"])}
    assert where["Глава 1. Новое время"]["first_paragraph_id"] == mx.paragraph("Согласно Канту").id
    # Карточка отдаёт то же поле.
    card = mx.cards.card(mx.ids["kant"], generation=False)
    assert {w["first_paragraph_id"] for w in card["where_to_read"]} == {
        mx.paragraph("Согласно Канту").id,
        None,
    }


@req(EM, "Где читать")
def test_where_to_read_without_position(mx):
    """Строки до миграции 6 без ``position``: первым считается вставленный раньше."""
    from sqlalchemy import update

    from philograph.knowledge import schema as ks

    mx.publish()
    with mx.onto.statements.engine.begin() as conn:
        conn.execute(update(ks.mentions).values(position=None))
    where = {w["chapter_title"]: w for w in mx.mentions.where_to_read(mx.ids["kant"])}
    assert where["Глава 1. Новое время"]["first_paragraph_id"] == mx.paragraph("Согласно Канту").id


@req(EM, "Где читать")
def test_migration_6_adds_mention_position(tmp_path):
    """Миграция 6 добавляет ``position`` в таблицу упоминаний прежнего вида и повторно безвредна."""
    from sqlalchemy import inspect, text

    from philograph.knowledge import schema as ks
    from philograph.platform.db import make_engine

    engine = make_engine(f"sqlite:///{(tmp_path / 'k.db').as_posix()}", [ks.SCHEMA])
    with engine.begin() as conn:
        conn.execute(
            text(
                f"CREATE TABLE {ks.SCHEMA}.mentions (id INTEGER PRIMARY KEY, target_id VARCHAR(40))"
            )
        )
        ks._mention_position(conn)
        ks._mention_position(conn)
        columns = {c["name"] for c in inspect(conn).get_columns("mentions", schema=ks.SCHEMA)}
    assert "position" in columns
    assert ks.migrations.latest() == 6


@req(EM, "Метрики упоминаний")
def test_mention_metrics():
    expected = {("p1", 0, "kant"), ("p1", 10, "hume")}
    found_set = {("p1", 0, "kant"), ("p2", 5, "locke")}
    assert mention_metrics(expected, found_set, ambiguous=2) == {
        "precision": 0.5,
        "recall": 0.5,
        "ambiguous_share": 0.5,
    }


# --- entity-cards --------------------------------------------------------------------


@req(EC, "Карточка рядом с текстом")
def test_card_navigation_links(mx):
    mx.onto.statements.add(
        mx.ids["kant"], "criticizes", obj=mx.ids["hume"], attributions=[Attribution("common")]
    )
    card = mx.cards.card(mx.ids["hume"])
    row = next(r for s in card["sections"] for r in s["rows"] if r["entity_id"] == mx.ids["kant"])
    assert row["label"] == "Кант" and row["relation"] == "подвергся критике"


@req(EC, "Карточка рядом с текстом")
def test_card_not_found_returns_404(mx):
    client = TestClient(build_app(mx.onto.statements, cards=mx.cards, mentions=mx.mentions))
    response = client.get("/v1/entities/nonexistent/card")
    assert response.status_code == 404
    assert response.json()["kind"] == "entity_not_found"


@req(EC, "Портреты в карточке")
def test_card_has_portraits_field(mx):
    mx.publish()
    card = mx.cards.card(mx.ids["kant"])
    # N3 отложен: поле есть и пустое, клиент показывает монограмму и «Изображений нет».
    assert card["portraits"] == []


@req(EC, "Разделы карточки по типу")
def test_sections_by_type(mx):
    mx.publish()
    paragraph = mx.paragraph("Согласно Канту")
    mx.onto.statements.add(
        mx.ids["causality"],
        "definition",
        value="связь причины и следствия",
        attributions=[Attribution("source", mx.source)],
    )
    mx.onto.statements.add(
        mx.ids["kant"],
        "holds",
        obj=mx.ids["idealism"],
        attributions=[Attribution("source", mx.source)],
        evidence=[Evidence(paragraph.id, "причинности нельзя научиться", source_id=mx.source)],
        provenance=Provenance("extracted"),
    )
    concept = mx.cards.card(mx.ids["causality"])
    assert next(s["code"] for s in concept["sections"]) == "definitions"
    assert concept["where_to_read"]
    person = mx.cards.card(mx.ids["kant"])
    codes = [s["code"] for s in person["sections"]]
    assert "life" in codes and "positions" in codes


@req(EC, "Природа каждой строки")
def test_row_attribution_status_and_dispute(mx):
    sid = mx.onto.statements.add(
        mx.ids["kant"],
        "influenced_by",
        obj=mx.ids["hume"],
        attributions=[
            Attribution("source", "s_a"),
            Attribution("source", "s_b", stance="disputes"),
        ],
    )
    generated = mx.onto.statements.add(
        mx.ids["kant"], "develops", obj=mx.ids["locke"], provenance=Provenance("generated")
    )
    rows = {
        r["statement_id"]: r for s in mx.cards.card(mx.ids["kant"])["sections"] for r in s["rows"]
    }
    assert rows[sid]["disputed"] and rows[sid]["disputed_by"] == ["s_b"]
    assert rows[sid]["attributed_to"] == ["s_a", "s_b"]
    assert rows[generated]["generated"] is True


@req(EC, "Пустые разделы")
def test_no_empty_sections(mx):
    mx.publish()
    card = mx.cards.card(mx.ids["hobbes"])
    assert all(section["rows"] for section in card["sections"])
    assert [s["code"] for s in card["sections"]] == ["life"]
    assert card["where_to_read"][0]["count"] == 1


@req(EC, "Описание моделью")
def test_generated_description_saved(mx, events):
    card = mx.cards.card(mx.ids["kant"])
    assert card["description"] is None and card["description_pending"]
    first = list(mx.cards.describe(mx.ids["kant"]))
    assert first[-1]["generated"] and "Критик" in first[-1]["text"]
    calls = len(mx.provider.calls)
    second = list(mx.cards.describe(mx.ids["kant"]))
    assert second == [{"type": "done", "text": first[-1]["text"], "generated": True}]
    assert len(mx.provider.calls) == calls  # модель не вызывалась второй раз
    assert mx.cards.card(mx.ids["kant"])["description"]["generated"] is True
    off = list(mx.cards.describe(mx.ids["hume"], generation=False))
    assert off == [{"type": "unavailable", "reason": "generation_disabled"}]


@req(EC, "Скорость карточки")
def test_card_without_model_and_streamed_description(mx):
    calls = len(mx.provider.calls)
    mx.cards.card(mx.ids["hume"])  # карточка — из готовых данных
    assert len(mx.provider.calls) == calls
    client = TestClient(build_app(mx.onto.statements, cards=mx.cards))
    lines = client.post(f"/v1/entities/{mx.ids['hume']}/description").text.splitlines()
    kinds = [json.loads(line)["type"] for line in lines]
    assert kinds[0] == "delta" and kinds[-1] == "done"


@req(EC, "Отклонённое и скрытое")
def test_rejected_hidden_and_misconceptions(mx):
    tabula = mx.onto.thing("term", "Чистая доска")
    rejected = mx.onto.statements.add(
        tabula, "introduced_by", obj=mx.ids["kant"], attributions=[Attribution("common")]
    )
    mx.onto.statements.reject(rejected, "operator")
    myth = mx.onto.statements.add(
        tabula,
        "introduced_by",
        obj=mx.ids["locke"],
        rank="deprecated",
        attributions=[
            Attribution("common", stance="asserts"),
            Attribution("source", "s_textbook", stance="disputes"),
        ],
    )
    card = mx.cards.card(tabula)
    rows = [r["statement_id"] for s in card["sections"] for r in s["rows"]]
    assert rejected not in rows
    myths = next(s for s in card["sections"] if s["code"] == "misconceptions")
    assert myths["title"] == "Часто считают, но…" and myths["rows"][0]["statement_id"] == myth
    # То же заблуждение в карточке Локка, с источником, который его опровергает.
    locke = mx.cards.card(mx.ids["locke"])
    row = next(s for s in locke["sections"] if s["code"] == "misconceptions")["rows"][0]
    assert row["statement_id"] == myth and row["disputed_by"] == ["s_textbook"]
    others = [
        r["statement_id"]
        for s in locke["sections"]
        if s["code"] != "misconceptions"
        for r in s["rows"]
    ]
    assert myth not in others  # отвергнутое не попадает в обычные разделы


@req(EC, "Перенаправления")
def test_card_of_merged_entity(mx):
    duplicate = mx.onto.person("Иммануил Кант")
    mx.onto.entities.merge(mx.ids["kant"], duplicate)
    assert mx.cards.card(duplicate)["id"] == mx.ids["kant"]
