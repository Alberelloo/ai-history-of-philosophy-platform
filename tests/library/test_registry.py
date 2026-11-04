"""Требования спецификации source-registry."""

from __future__ import annotations

import pytest

from philograph.library.processing import StepFailed
from philograph.library.registry import DuplicateSource, License, RegistryError

req = pytest.mark.req
SR = "source-registry"


@req(SR, "Регистрация источника")
def test_registration_requires_fields(lib, events):
    source_id = lib.register(authors=["А. Первый", "Б. Второй", "В. Третий"], year=1999)
    source = lib.registry.get(source_id)
    assert source.authors == ["А. Первый", "Б. Второй", "В. Третий"]
    assert source.published_version is None  # в библиотеке читателя его нет
    events.one("library.source.registered")
    assert lib.registry.actions.entries()[-1]["action"] == "register_source"

    with pytest.raises(RegistryError) as info:
        lib.registry.register(
            "operator",
            title="Без лицензии",
            authors=["X"],
            language="ru",
            kind="textbook",
            scope="public",
            license=None,
        )
    assert info.value.fields == ["license"]
    assert events.one("library.source.rejected")["fields"] == ["license"]


@req(SR, "Лицензия с основанием и разрешениями")
def test_license_basis_and_permissions(lib):
    with pytest.raises(RegistryError) as info:
        lib.register(license=lib.license(author_death_years=[]))
    assert "годы смерти" in str(info.value)
    with pytest.raises(RegistryError) as info:
        lib.register(license=License("cc-by", "rightsholder_permission"))
    assert "ссылка на документ" in str(info.value)
    source_id = lib.register(license=License("cc-by", "open_license"))
    assert lib.registry.permissions(source_id) == {
        "display": True,
        "external_processing": True,
        "quoting": True,
    }


@req(SR, "Права на перевод")
def test_translation_rights_block_processing(lib, events):
    with pytest.raises(RegistryError):
        lib.register(translator="Н. Лосский")  # нет года смерти переводчика
    source_id = lib.register(
        translator="Переводчик", license=lib.license(translator_death_year=1990)
    )
    assert "перевод" in lib.registry.blocked_reason(source_id)
    assert events.one("library.license.blocked")["source_id"] == source_id
    with pytest.raises(RegistryError):
        lib.pipeline.start("operator", source_id)  # в обработку не идёт
    assert lib.fetched == []


@req(SR, "Разрешения управляют обработкой и показом")
def test_permissions_drive_events_and_publication(lib, events):
    narrowed = lib.register(
        license=License("cc-by", "open_license", narrowed={"external_processing": False})
    )
    lib.publish_new(narrowed)
    payload = lib.registry.outbox_pending()[-1]["payload"]
    assert payload["external_processing"] is False

    hidden = lib.register(title="Скрытый", license=License("no-display", "open_license"))
    version_id = lib.pipeline.start("operator", hidden)
    with pytest.raises(RegistryError) as info:
        lib.registry.publish("operator", version_id)
    assert "показывать" in str(info.value)
    assert events.where("library.publish.refused", version_id=version_id)


@req(SR, "Виды лицензий как данные")
def test_license_kinds_are_data(lib):
    lib.registry.add_license_kind(
        "cc-by-nc",
        "CC BY-NC 4.0",
        None,
        {"display": True, "external_processing": True, "quoting": True},
    )
    first = lib.register(
        license=License("cc-by-nc", "open_license", narrowed={"external_processing": False})
    )
    second = lib.register(title="Другой", license=License("cc-by-nc", "open_license"))
    assert lib.registry.permissions(first)["external_processing"] is False
    assert lib.registry.permissions(second)["external_processing"] is True
    with pytest.raises(RegistryError):
        lib.register(
            title="Шире", license=License("no-display", "open_license", narrowed={"display": True})
        )


@req(SR, "Проверка на дубликаты")
def test_duplicates_by_description_and_file(lib, events):
    first = lib.register(year=1999)
    with pytest.raises(DuplicateSource) as info:
        lib.register(year=1999)
    assert info.value.other == first
    other_edition = lib.register(year=2005)
    assert other_edition != first
    confirmed = lib.register(year=1999, confirm_duplicate=True)

    lib.pipeline.start("operator", first)
    events.clear()
    lib.pipeline.start("operator", confirmed)  # тот же файл
    assert events.where("library.source.duplicate", other_source_id=first, by="file")


@req(SR, "Область видимости источника")
def test_scope_public_only_and_logged(lib, events):
    source_id = lib.register()
    assert lib.registry.get(source_id).scope == "public"
    with pytest.raises(RegistryError):
        lib.register(title="Группа", scope="group:students")
    lib.registry.restricted_scopes = True
    lib.registry.change_scope("operator", source_id, "group:students")
    history = lib.registry.scope_history(source_id)
    assert [(h["old"], h["new"]) for h in history] == [
        (None, "public"),
        ("public", "group:students"),
    ]
    assert history[-1]["actor"] == "operator" and history[-1]["time"]
    events.one("library.scope.changed")


@req(SR, "Версии источника")
def test_versions_do_not_disturb_readers(lib):
    source_id = lib.register()
    v1 = lib.publish_new(source_id)
    lib.files["book.txt"] += "\nНовый абзац о схематизме.\n".encode()
    v2 = lib.pipeline.start("operator", source_id)
    assert lib.registry.get(source_id).published_version == v1
    lib.registry.publish("operator", v2)
    states = {v["id"]: v["state"] for v in lib.registry.versions(source_id)}
    assert states == {v1: "replaced", v2: "published"}


@req(SR, "Публикация версии")
def test_publication_atomic_with_summary(lib, events):
    source_id = lib.register()
    v1 = lib.publish_new(source_id)
    events.assert_sequence(
        "library.publish.started", "library.outbox.recorded", "library.version.switched"
    )
    lib.files["book.txt"] = lib.files["book.txt"].replace(
        "Рассудок даёт правила явлениям.".encode(),
        "Рассудок даёт правила явлениям природы.".encode(),
    )
    v2 = lib.pipeline.start("operator", source_id)
    summary = lib.registry.version(v2)["summary"]
    assert summary["counts"] == {"added": 0, "changed": 1, "removed": 0, "redirected": 0}

    lib.registry.update_version(
        v2, issues=[{"level": "error", "code": "x", "message": "m", "page": None, "block_id": None}]
    )
    with pytest.raises(RegistryError):
        lib.registry.publish("operator", v2)
    assert lib.registry.get(source_id).published_version == v1
    lib.registry.update_version(v2, issues=[])
    lib.registry.publish("operator", v2)
    doc = lib.registry.load_document(lib.registry.get(source_id).published_version)
    assert any("природы" in b.text for _, b in doc.blocks())  # новая версия целиком


@req(SR, "Откат к прежней версии")
def test_rollback(lib, events):
    source_id = lib.register()
    v1 = lib.publish_new(source_id)
    lib.files["book.txt"] += "\nОшибочный абзац разбора.\n".encode()
    v2 = lib.publish_new(source_id)
    events.clear()
    lib.registry.rollback("operator", source_id, v1)
    assert lib.registry.get(source_id).published_version == v1
    published = lib.registry.outbox_pending()[-1]
    assert published["kind"] == "source.published"
    assert published["payload"]["previous_version_id"] == v2
    assert len(published["payload"]["removed"]) == 1
    events.one("library.version.switched")


@req(SR, "Изменение описания и лицензии")
def test_metadata_and_license_changes(lib, events):
    source_id = lib.register(title="Критика чистого розума")
    v1 = lib.publish_new(source_id)
    lib.registry.update_metadata("operator", source_id, title="Критика чистого разума")
    assert lib.registry.get(source_id).title == "Критика чистого разума"
    assert len(lib.registry.versions(source_id)) == 1 and v1

    lib.registry.change_license("operator", source_id, License("no-display", "open_license"))
    assert lib.registry.get(source_id).status == "unpublished"
    assert events.where("library.source.unpublished", reason="license_forbids_display")
    assert lib.registry.outbox_pending()[-1]["kind"] == "source.unpublished"


@req(SR, "Снятие с публикации")
def test_unpublish_and_republish_keep_ids(lib, events):
    source_id = lib.register()
    v1 = lib.publish_new(source_id)
    ids = [b.id for _, b in lib.registry.load_document(v1).blocks()]
    lib.registry.unpublish("operator", source_id)
    assert lib.registry.resolve_paragraph(ids[0])["status"] == "source_unavailable"
    assert lib.registry.outbox_pending()[-1]["kind"] == "source.unpublished"
    lib.registry.republish("operator", source_id)
    assert lib.registry.resolve_paragraph(ids[0])["status"] == "found"
    assert [b.id for _, b in lib.registry.load_document(v1).blocks()] == ids
    events.one("library.source.unpublished")


@req(SR, "Удаление источника")
def test_delete_only_unpublished_leaves_record(lib, events):
    source_id = lib.register()
    v1 = lib.publish_new(source_id)
    paragraph = next(b.id for _, b in lib.registry.load_document(v1).blocks())
    with pytest.raises(RegistryError):
        lib.registry.delete("operator", source_id)
    digest = lib.registry.version(v1)["files"][0]["sha256"]
    lib.registry.unpublish("operator", source_id)
    lib.pipeline.delete_source("operator", source_id)
    assert lib.registry.versions(source_id) == []
    assert not lib.pipeline.files.exists(digest)
    assert lib.registry.get(source_id).status == "deleted"
    assert lib.registry.get(source_id).title == "Критика чистого разума"
    assert lib.registry.resolve_paragraph(paragraph)["status"] == "source_unavailable"
    events.one("library.source.deleted")


@req(SR, "Обзор источников для оператора")
def test_overview_needs_decision(lib):
    ready = lib.register(title="Готов к публикации")
    lib.pipeline.start("operator", ready)
    broken = lib.register(title="Сломанный", files=[{"name": "x", "path": "missing.txt"}])
    with pytest.raises(StepFailed):
        lib.pipeline.start("operator", broken)
    published = lib.register(title="Опубликован")
    lib.files["other.txt"] = "Глава 1\n\nДругой текст о скептицизме Юма.\n".encode()
    lib.registry.update_metadata("operator", published, title="Опубликован")
    lib.publish_new(lib.register(title="Ещё", files=[{"name": "o", "path": "other.txt"}]))
    waiting = {item["title"] for item in lib.registry.overview(needs_decision=True)}
    assert waiting == {"Готов к публикации"}
    assert {item["title"] for item in lib.registry.overview()} >= {"Сломанный", "Опубликован"}
