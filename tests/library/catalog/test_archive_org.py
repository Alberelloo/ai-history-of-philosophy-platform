"""archive_org: метаданные без лицензии и издателя не роняют добавление записи."""

from __future__ import annotations

import json

from philograph.library.catalog.adapters import ArchiveOrg, suggest_license

ITEM = "1911-2523026-0120"


def test_item_without_license_gives_null_hint(env):
    meta = {
        "metadata": {
            "title": "Философия свободы",
            "creator": "Бердяев, Н. А.",
            "language": "rus",
            "date": "1911",
        },
        "files": [{"name": "book_djvu.txt", "format": "DjVuTXT"}],
    }
    env.web.routes[f"https://archive.org/metadata/{ITEM}"] = (
        200,
        json.dumps(meta).encode(),
        {"content-type": "application/json"},
    )
    harvest = ArchiveOrg().harvest(f"https://archive.org/details/{ITEM}", env.service.fetcher)
    assert harvest.license_hint is None
    assert harvest.metadata["publisher"] is None
    assert suggest_license(harvest, 2026) is None
