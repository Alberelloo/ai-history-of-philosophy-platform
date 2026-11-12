"""Требования source-registry «Виды лицензий как данные» и regional-access о регионах показа."""

from __future__ import annotations

import pytest

from philograph.library.reading import NotVisible, Reader, Reading, parse_region
from philograph.library.registry import License, RegistryError

req = pytest.mark.req
SR = "source-registry"
RA = "regional-access"
RU_KIND = "public-domain-ru"


def add_ru_kind(lib, regions: list[str] | None = None) -> None:
    lib.registry.add_license_kind(
        RU_KIND,
        "Общественное достояние по праву РФ",
        None,
        {"display": True, "external_processing": True, "quoting": True},
        regions=["RU"] if regions is None else regions,
    )


def ru_license(**overrides) -> License:
    params = {
        "kind": RU_KIND,
        "basis": "public_domain",
        "author_death_years": [1804],
    }
    params.update(overrides)
    return License(**params)


@req(SR, "Виды лицензий как данные")
def test_empty_region_list_means_everywhere(lib):
    add_ru_kind(lib, regions=[])
    source_id = lib.register(license=ru_license())

    assert lib.registry.license_kind(RU_KIND)["regions"] is None
    assert lib.registry.regions(source_id) is None
    assert lib.registry.permissions(source_id)["display"] is True


@req(SR, "Виды лицензий как данные")
def test_bad_region_code_rejected(lib):
    for bad in ("RU1", "РФ", ""):
        with pytest.raises(RegistryError) as info:
            lib.registry.add_license_kind(
                "bad-kind",
                "Плохой вид",
                None,
                {"display": True, "external_processing": True, "quoting": True},
                regions=[bad],
            )
        assert info.value.fields == ["license.regions"]
    add_ru_kind(lib, regions=["RU"])
    with pytest.raises(RegistryError):
        lib.register(license=ru_license(regions=["RU1"]))


@req(SR, "Виды лицензий как данные")
def test_regions_columns_and_repeat_migration(lib):
    from sqlalchemy import inspect

    from philograph.library import schema

    engine = lib.registry.engine
    for table in ("license_kinds", "sources"):
        columns = {c["name"] for c in inspect(engine).get_columns(table, schema="library")}
        assert "regions" in columns
    schema.migrations.upgrade(engine)  # повторный прогон на готовой базе не ломается


@req(SR, "Виды лицензий как данные")
def test_kind_regions_apply_to_sources(lib):
    add_ru_kind(lib, regions=["rU"])  # код приводится к верхнему регистру
    source_id = lib.register(license=ru_license())

    assert lib.registry.license_kind(RU_KIND)["regions"] == ["RU"]
    assert lib.registry.regions(source_id) == frozenset({"RU"})


@req(SR, "Виды лицензий как данные")
def test_source_regions_narrow_kind(lib):
    add_ru_kind(lib, regions=["RU", "BY"])
    narrowed = lib.register(license=ru_license(regions=["RU"]))
    inherited = lib.register(title="Другой", license=ru_license())

    assert lib.registry.regions(narrowed) == frozenset({"RU"})
    assert lib.registry.regions(inherited) == frozenset({"RU", "BY"})


@req(SR, "Виды лицензий как данные")
def test_widening_regions_rejected(lib):
    add_ru_kind(lib, regions=["RU"])
    with pytest.raises(RegistryError) as info:
        lib.register(license=ru_license(regions=["RU", "DE"]))
    assert info.value.fields == ["license.regions"]

    source_id = lib.register(license=ru_license())
    with pytest.raises(RegistryError):
        lib.registry.change_license("operator", source_id, ru_license(regions=["DE"]))
    assert lib.registry.regions(source_id) == frozenset({"RU"})


@req(SR, "Виды лицензий как данные")
def test_regions_are_stored_and_survive_reading(lib):
    add_ru_kind(lib, regions=["RU", "BY"])
    source_id = lib.register(license=ru_license(regions=["BY"]))
    source = lib.registry.get(source_id)

    assert source.license.regions == ["BY"]  # регионы читаются из своего столбца
    assert lib.registry.regions(source_id) == frozenset({"BY"})


@req(SR, "Виды лицензий как данные")
def test_empty_intersection_is_no_display(lib, events):
    add_ru_kind(lib, regions=["RU", "BY"])
    source_id = lib.register(license=ru_license(regions=["BY"]))
    version_id = lib.pipeline.start("operator", source_id)
    lib.registry.publish("operator", version_id)

    # Вид сузили до РФ: у источника из BY действующие регионы стали пустыми.
    events.clear()
    add_ru_kind(lib, regions=["RU"])
    assert lib.registry.regions(source_id) == frozenset()
    assert lib.registry.permissions(source_id)["display"] is False
    events.one("library.access.changed")


@req(RA, "Смена регионов у опубликованного источника")
def test_change_license_emits_access_changed(lib, events):
    add_ru_kind(lib, regions=["RU", "BY"])
    source_id = lib.register(license=ru_license())
    version_id = lib.publish_new(source_id)
    events.clear()

    lib.registry.change_license("operator", source_id, ru_license(regions=["RU"]))
    pending = lib.registry.outbox_pending()
    assert pending[-1]["kind"] == "source.access_changed"
    payload = pending[-1]["payload"]
    assert payload["source_id"] == source_id
    assert payload["regions"] == ["RU"]
    assert payload["permissions"]["display"] is True
    assert lib.registry.get(source_id).published_version == version_id  # публикация не тронута
    assert lib.registry.regions(source_id) == frozenset({"RU"})


@req(RA, "Смена регионов у опубликованного источника")
def test_access_changed_carries_effective_regions(lib, events):
    """Событие уносит действующие регионы, а не сужение: вид ограничен РФ, сужения нет."""
    add_ru_kind(lib)  # вид: regions ["RU"]
    source_id = lib.register(license=ru_license())  # источник без собственного сужения
    lib.publish_new(source_id)
    events.clear()

    lib.registry.change_license("operator", source_id, ru_license())
    payload = lib.registry.outbox_pending()[-1]["payload"]
    # `null` здесь означал бы «везде» и открыл бы текст всем регионам до следующей сверки.
    assert payload["regions"] == ["RU"]
    assert payload["permissions"]["display"] is True
    assert lib.registry.regions(source_id) == frozenset({"RU"})


@req(RA, "Библиотека закрывает текст ограниченных источников")
def test_list_marks_restricted_rows(lib, events):
    add_ru_kind(lib)
    open_id = lib.register(title="Открытая книга")
    restricted_id = lib.register(title="Русская книга", license=ru_license())
    lib.publish_new(open_id)
    lib.publish_new(restricted_id)
    reading = Reading(lib.registry, lib.registry.engine)
    reading.set_default("operator", open_id)

    data = reading.sources(Reader(region="DE"))
    rows = {s["id"]: s for s in data["sources"]}
    assert set(rows) == {open_id, restricted_id}
    assert "restricted" not in rows[open_id]
    assert rows[restricted_id] == {
        "id": restricted_id,
        "title": "Русская книга",
        "authors": ["И. Кант"],
        "restricted": True,
        "regions": ["RU"],
    }
    assert data["default_source_id"] == open_id


@req(RA, "Библиотека закрывает текст ограниченных источников")
def test_filters_apply_to_restricted_rows(lib):
    add_ru_kind(lib)
    open_id = lib.register(title="Открытая книга")
    restricted_id = lib.register(title="Русская книга", license=ru_license())
    lib.publish_new(open_id)
    lib.publish_new(restricted_id)
    reading = Reading(lib.registry, lib.registry.engine)

    found = reading.sources(Reader(region="DE"), query="русская")["sources"]
    assert [s["id"] for s in found] == [restricted_id]
    found = reading.sources(Reader(region="DE"), kinds=["textbook"])["sources"]
    assert {s["id"] for s in found} == {open_id, restricted_id}
    found = reading.sources(Reader(region="DE"), kinds=["primary"])["sources"]
    assert found == []


@req(RA, "Библиотека закрывает текст ограниченных источников")
def test_reader_in_region_opens_source(lib):
    add_ru_kind(lib)
    source_id = lib.register(license=ru_license())
    lib.publish_new(source_id)
    reading = Reading(lib.registry, lib.registry.engine)
    reader = Reader(region="RU")

    rows = reading.sources(reader)["sources"]
    assert "restricted" not in rows[0]
    toc = reading.toc(source_id, reader)
    chapter = reading.chapter(source_id, toc[0]["id"], reader)
    assert chapter["blocks"]


@req(RA, "Неизвестный регион закрывает ограниченные источники")
def test_unknown_region_closes_restricted(lib):
    add_ru_kind(lib)
    open_id = lib.register(title="Открытая книга")
    restricted_id = lib.register(title="Русская книга", license=ru_license())
    lib.publish_new(open_id)
    lib.publish_new(restricted_id)
    reading = Reading(lib.registry, lib.registry.engine)

    rows = {s["id"]: s for s in reading.sources(Reader())["sources"]}
    assert "restricted" not in rows[open_id]
    assert rows[restricted_id]["restricted"] is True
    with pytest.raises(NotVisible):
        reading.toc(restricted_id, Reader())


@req(RA, "Библиотека закрывает текст ограниченных источников")
def test_remembered_restricted_is_not_current(lib):
    add_ru_kind(lib)
    open_id = lib.register(title="Открытая книга")
    restricted_id = lib.register(title="Русская книга", license=ru_license())
    lib.publish_new(open_id)
    lib.publish_new(restricted_id)
    reading = Reading(lib.registry, lib.registry.engine)
    reading.set_default("operator", open_id)

    current = reading.resolve_current(restricted_id, Reader(region="DE"))
    assert current == {"source_id": open_id, "notice": "previous_unavailable"}
    assert reading.resolve_current(restricted_id, Reader(region="RU"))["source_id"] == restricted_id


@req(RA, "Ссылка на абзац закрытого источника")
def test_paragraph_link_from_other_region(lib):
    add_ru_kind(lib)
    source_id = lib.register(license=ru_license())
    version_id = lib.publish_new(source_id)
    paragraph = next(b.id for _, b in lib.registry.load_document(version_id).blocks())
    reading = Reading(lib.registry, lib.registry.engine)

    closed = reading.resolve_paragraph(paragraph, Reader(region="DE"))
    assert closed == {
        "status": "source_unavailable",
        "reason": "region",
        "source": {"id": source_id, "title": "Критика чистого разума", "authors": ["И. Кант"]},
    }
    assert reading.resolve_paragraph(paragraph, Reader(region="RU"))["status"] == "found"


@req(RA, "Неизвестный регион закрывает ограниченные источники")
def test_region_header_is_two_latin_letters():
    assert parse_region("ru") == "RU"
    assert parse_region(" DE ") == "DE"
    for bad in (None, "", "XX1", "РФ", "T1", "R", "XX", "xx"):
        assert parse_region(bad) is None
