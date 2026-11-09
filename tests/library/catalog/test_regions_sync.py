"""Синхронизация каталога: смена регионов вида лицензии доходит до источников событием."""

from __future__ import annotations

import pytest
import yaml

from philograph.library.catalog import model

req = pytest.mark.req
SR = "source-registry"
RA = "regional-access"


def set_kind_regions(env, code: str, regions: list[str] | None) -> None:
    path = env.catalog.licenses_path
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    for kind in data:
        if kind["code"] != code:
            continue
        if regions is None:
            kind.pop("regions", None)
        else:
            kind["regions"] = regions
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


@req(RA, "Смена регионов у опубликованного источника")
def test_sync_region_change_emits_events(env, events):
    env.service.ensure_license_kinds()
    env.entry()
    source_id = env.sync("test-book")["test-book"].source_id
    assert env.registry.regions(source_id) is None  # в licenses.yaml регионов ещё нет
    before = env.registry.outbox_pending()

    set_kind_regions(env, "public-domain", ["RU"])
    events.clear()
    env.service.ensure_license_kinds()

    added = env.registry.outbox_pending()[len(before) :]
    assert [event["kind"] for event in added] == ["source.access_changed"]
    assert added[0]["payload"]["source_id"] == source_id
    assert added[0]["payload"]["regions"] == ["RU"]
    assert env.registry.regions(source_id) == frozenset({"RU"})
    events.one("library.access.changed")


@req(RA, "Смена регионов у опубликованного источника")
def test_sync_without_region_change_emits_nothing(env):
    env.service.ensure_license_kinds()
    env.entry()
    env.sync("test-book")
    before = len(env.registry.outbox_pending())

    env.service.ensure_license_kinds()
    assert len(env.registry.outbox_pending()) == before


@req(SR, "Виды лицензий как данные")
def test_entry_regions_pass_validation_and_reach_registry(env):
    env.service.ensure_license_kinds()
    env.entry(
        license={
            "kind": "public-domain",
            "basis": "public_domain",
            "evidence": "ум. 1704",
            "regions": ["RU"],
        }
    )
    errors = [p for p in model.validate(env.catalog, year=2026) if p.level == "error"]
    assert errors == []

    outcome = env.sync("test-book")["test-book"]
    assert env.registry.get(outcome.source_id).license.regions == ["RU"]
    assert env.registry.regions(outcome.source_id) == frozenset({"RU"})
