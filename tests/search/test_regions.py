"""Регион запроса в поиске: ``regional-access`` и ``paragraph-search`` «Видимость и публикация»."""

from __future__ import annotations

import pytest
from sqlalchemy import inspect, select, text, update

from philograph.library.registry import License
from philograph.platform.db import make_engine
from philograph.search import schema as s
from philograph.search.indexing import regions_column, regions_payload

req = pytest.mark.req
RA = "regional-access"
PS = "paragraph-search"

RESTRICTED_TEXT = "Глава 1\n\nРассудок есть способность правил, разум — способность принципов.\n"
OPEN_PERMISSIONS = {"display": True, "external_processing": True, "quoting": True}


def add_restricted(rig) -> str:
    """Регистрирует и публикует источник только для РФ, возвращает его идентификатор."""
    rig.registry.add_license_kind(
        "ru-only", "Только РФ", None, dict(OPEN_PERMISSIONS), regions=["RU"]
    )
    lic = License("ru-only", "public_domain", author_death_years=[1900])
    source_id = rig.registry.register(
        "operator",
        title="Ограниченная книга",
        authors=["К"],
        language="ru",
        kind="textbook",
        license=lic,
        scope="public",
        files=[{"name": "r", "path": "restricted.txt"}],
    )
    rig.files["restricted.txt"] = RESTRICTED_TEXT.encode()
    rig.ids["restricted"] = source_id
    return source_id


def found_sources(result):
    return {r["source_id"] for r in result["results"]}


NO_EXTERNAL_TEXT = "Глава 1\n\nРассудок даёт правила, а разум — принципы познания.\n"


def add_no_external(rig) -> str:
    """Регистрирует и публикует источник только для РФ без внешней обработки."""
    rig.registry.add_license_kind(
        "ru-no-external",
        "Только РФ без внешней обработки",
        None,
        {"display": True, "external_processing": False, "quoting": True},
        regions=["RU"],
    )
    lic = License("ru-no-external", "public_domain", author_death_years=[1900])
    source_id = rig.registry.register(
        "operator",
        title="Без внешней обработки",
        authors=["Н"],
        language="ru",
        kind="textbook",
        license=lic,
        scope="public",
        files=[{"name": "n", "path": "noexternal.txt"}],
    )
    rig.files["noexternal.txt"] = NO_EXTERNAL_TEXT.encode()
    rig.ids["no_external"] = source_id
    return source_id


def test_regions_column_format():
    """Формат хранения регионов: ``*`` — везде, ``,RU,BY,`` — перечень, ``','`` — нигде."""
    assert regions_column(None) == "*"
    assert regions_column(["RU"]) == ",RU,"
    assert regions_column(["RU", "BY"]) == ",BY,RU,"
    assert regions_column([]) == ","
    assert regions_payload(None) == ["*"]
    assert regions_payload(["RU", "BY"]) == ["BY", "RU"]
    assert regions_payload([]) == []


def test_migration_4_adds_regions_and_external(tmp_path):
    """Миграция 4 добавляет ``regions`` и ``external`` со значениями по умолчанию."""
    engine = make_engine(f"sqlite:///{(tmp_path / 's.db').as_posix()}", [s.SCHEMA])
    with engine.begin() as conn:
        conn.execute(
            text(
                f"CREATE TABLE {s.SCHEMA}.docs ("
                "paragraph_id VARCHAR(40) PRIMARY KEY, source_id VARCHAR(40) NOT NULL, "
                "version_id VARCHAR(40) NOT NULL, text TEXT NOT NULL, length INTEGER NOT NULL, "
                "embedded BOOLEAN NOT NULL, active BOOLEAN NOT NULL, "
                "quoting BOOLEAN NOT NULL DEFAULT 1, source_title TEXT)"
            )
        )
        conn.execute(
            text(
                f"INSERT INTO {s.SCHEMA}.docs "
                "(paragraph_id, source_id, version_id, text, length, embedded, active) "
                "VALUES ('p1', 's1', 'v1', 'текст', 1, 0, 1)"
            )
        )
        s._add_regions_and_external(conn)
        s._add_regions_and_external(conn)  # повторный прогон безвреден
        columns = {c["name"] for c in inspect(conn).get_columns("docs", schema=s.SCHEMA)}
        row = conn.execute(text(f"SELECT regions, external FROM {s.SCHEMA}.docs")).one()
    assert {"regions", "external"} <= columns
    assert row.regions == "*"
    assert bool(row.external) is True
    assert s.migrations.latest() == 4


@req(PS, "Видимость и публикация")
def test_restricted_source_hidden_from_other_region(rig):
    restricted = add_restricted(rig)
    rig.publish("ru")
    rig.publish("restricted")

    result = rig.search("рассудок и разум", region="DE")
    assert result["results"]  # открытые абзацы Канта находятся
    assert restricted not in found_sources(result)


@req(RA, "Поиск учитывает регион запроса")
def test_search_respects_region(rig):
    restricted = add_restricted(rig)
    rig.publish("ru")
    rig.publish("restricted")

    assert restricted in found_sources(rig.search("рассудок и разум", region="RU"))
    assert restricted not in found_sources(rig.search("рассудок и разум", region="DE"))
    assert restricted not in found_sources(rig.search("рассудок и разум"))


@req(RA, "Поиск учитывает регион запроса")
def test_limit_filled_with_open_sources(rig):
    restricted = add_restricted(rig)
    rig.publish("ru")
    rig.publish("restricted")

    de = rig.search("рассудок и разум", region="DE", limit=3)
    assert len(de["results"]) == 3
    assert restricted not in found_sources(de)


def test_region_filter_applies_when_embeddings_down(rig):
    restricted = add_restricted(rig)
    rig.publish("ru")
    rig.publish("restricted")

    rig.provider.fail = True  # провайдер эмбеддингов недоступен: остаётся поиск по словам
    de = rig.search("рассудок и разум", region="DE")
    assert de["semantic_used"] is False
    assert de["results"]  # открытые абзацы Канта находятся по словам
    assert restricted not in found_sources(de)


@req(RA, "Смена регионов у опубликованного источника")
def test_access_changed_updates_regions_without_embedding(rig):
    restricted = add_restricted(rig)
    rig.publish("ru")
    rig.publish("restricted")

    assert restricted not in found_sources(rig.search("рассудок и разум", region="DE"))
    calls = len(rig.provider.calls)
    rig.indexer.handle(
        "source.access_changed",
        {
            "event_id": "evt-open",
            "source_id": restricted,
            "regions": None,  # ограничение снято: виден всем
            "permissions": dict(OPEN_PERMISSIONS),
        },
    )
    assert len(rig.provider.calls) == calls  # эмбеддер не вызывался
    assert restricted in found_sources(rig.search("рассудок и разум", region="DE"))

    # Обратно сузили до РФ: читатель из DE снова не видит источник.
    rig.indexer.handle(
        "source.access_changed",
        {
            "event_id": "evt-close",
            "source_id": restricted,
            "regions": ["RU"],
            "permissions": dict(OPEN_PERMISSIONS),
        },
    )
    assert restricted not in found_sources(rig.search("рассудок и разум", region="DE"))
    assert restricted in found_sources(rig.search("рассудок и разум", region="RU"))


def test_access_changed_duplicate_event_is_noop(rig, events):
    restricted = add_restricted(rig)
    rig.publish("ru")
    rig.publish("restricted")

    payload = {
        "event_id": "evt-dup",
        "source_id": restricted,
        "regions": None,
        "permissions": dict(OPEN_PERMISSIONS),
    }
    calls = len(rig.provider.calls)
    rig.indexer.handle("source.access_changed", payload)
    rig.indexer.handle("source.access_changed", payload)  # повтор не повторяет работу
    assert len(rig.provider.calls) == calls
    events.one("search.index.duplicate")


def test_access_changed_empty_regions_closes(rig):
    restricted = add_restricted(rig)
    rig.publish("ru")
    rig.publish("restricted")

    rig.indexer.handle(
        "source.access_changed",
        {
            "event_id": "evt-empty",
            "source_id": restricted,
            "regions": [],  # пустое пересечение: нигде
            "permissions": {"display": False, "external_processing": True, "quoting": True},
        },
    )
    for region in (None, "RU", "DE"):
        assert restricted not in found_sources(rig.search("рассудок и разум", region=region))


@req(RA, "Внешняя обработка закрытых источников")
def test_indexing_source_without_external_processing(rig, events):
    """7.1: абзацы без ``external_processing`` есть в полнотекстовом индексе и отсутствуют в
    смысловом; провайдер эмбеддингов не вызывается; поиск отдаёт ``external`` в результате."""
    source = add_no_external(rig)
    rig.publish("ru")
    calls = len(rig.provider.calls)
    rig.publish("no_external")
    assert len(rig.provider.calls) == calls  # эмбеддинги не считались

    with rig.indexer.engine.begin() as conn:
        rows = conn.execute(select(s.docs).where(s.docs.c.source_id == source)).all()
    assert rows  # полнотекстовый индекс есть
    assert all(bool(r.external) is False for r in rows)
    assert all(bool(r.embedded) is False for r in rows)  # смыслового индекса нет

    # Поиск из РФ находит абзац по словам и сообщает, что внешняя обработка запрещена.
    ru = rig.search("рассудок и разум", region="RU")
    assert source in found_sources(ru)
    assert all(r["external"] is False for r in ru["results"] if r["source_id"] == source)
    # Вне РФ источник закрыт по региону, как и прежде.
    assert source not in found_sources(rig.search("рассудок и разум", region="DE"))


@req(RA, "Внутренние интерфейсы не фильтруют по региону")
def test_reconcile_keeps_restricted_and_fixes_regions(rig, events):
    restricted = add_restricted(rig)
    rig.publish("ru")
    rig.publish("restricted")

    # Расхождение: регионы в индексе устарели (как после миграции до сверки).
    with rig.indexer.engine.begin() as conn:
        conn.execute(update(s.docs).where(s.docs.c.source_id == restricted).values(regions="*"))

    assert rig.indexer.reconcile() == {"missing": 0, "extra": 0}  # не счёл источник лишним
    assert rig.indexer.reconcile() == {"missing": 0, "extra": 0}  # повторная сверка безвредна

    with rig.indexer.engine.begin() as conn:
        stored = set(conn.scalars(select(s.docs.c.regions).where(s.docs.c.source_id == restricted)))
        active = list(conn.scalars(select(s.docs.c.active).where(s.docs.c.source_id == restricted)))
    assert stored == {",RU,"}
    assert active and all(active)
    # Сверка починила утечку: DE не видит, RU видит.
    assert restricted not in found_sources(rig.search("рассудок и разум", region="DE"))
    assert restricted in found_sources(rig.search("рассудок и разум", region="RU"))
    assert len(events.of("search.index.reconciled")) == 2
