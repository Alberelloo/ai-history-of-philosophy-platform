"""Требование source-registry «Правовой статус источника»."""

from __future__ import annotations

import pytest

from philograph.library.registry import License, RegistryError

req = pytest.mark.req
SR = "source-registry"


@req(SR, "Правовой статус источника")
def test_in_copyright_source_registers_and_publishes_internally(lib, events):
    lib.registry.add_license_kind(
        "in-copyright",
        "Под охраной",
        None,
        {"display": False, "external_processing": True, "quoting": False},
        tier="in_copyright",
    )
    source_id = lib.register(license=License("in-copyright", "in_copyright"))
    source = lib.registry.get(source_id)
    assert source.rights_tier == "in_copyright"
    assert lib.registry.permissions(source_id)["display"] is False
    assert lib.registry.blocked_reason(source_id) is None
    lib.publish_new(source_id)  # без показа публикуется для онтологии
    payload = lib.registry.outbox_pending()[-1]["payload"]
    assert payload["display"] is False
    assert payload["external_processing"] is True


@req(SR, "Правовой статус источника")
def test_change_rights_tier_records_history(lib, events):
    source_id = lib.register()  # public-domain → public_domain
    lib.registry.change_rights_tier("operator", source_id, "in_copyright", evidence="срок не истёк")
    history = lib.registry.rights_history(source_id)
    assert history[-1]["old_tier"] == "public_domain"
    assert history[-1]["new_tier"] == "in_copyright"
    assert history[-1]["evidence"] == "срок не истёк"
    events.one("library.rights_tier.changed")


@req(SR, "Правовой статус источника")
def test_widening_to_open_tier_requires_evidence(lib):
    lib.registry.add_license_kind(
        "in-copyright",
        "Под охраной",
        None,
        {"display": False, "external_processing": True, "quoting": False},
        tier="in_copyright",
    )
    source_id = lib.register(license=License("in-copyright", "in_copyright"))
    with pytest.raises(RegistryError):
        lib.registry.change_rights_tier("operator", source_id, "public_domain")
    lib.registry.change_rights_tier("operator", source_id, "public_domain", evidence="ум. 1804")
    assert lib.registry.get(source_id).rights_tier == "public_domain"
