"""Отбор портретов: лицензии, атрибуция, дедупликация, манифест, ``sync``.

Требования ``entity-portraits`` «Отбор портретов персоны», «Лицензии и атрибуция» и
«Хранение и раздача изображений» в части, которую делает модуль отбора (задача 2). Сеть в
тестах запрещена: все функции получают ``fetch``/``download`` и работают на фикстурах
``tests/knowledge/fixtures/portraits``.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from PIL import Image, ImageDraw

from philograph.knowledge.portraits_source import (
    MAX_BYTES,
    build_candidate,
    cap_accepted,
    clean_author,
    dhash,
    extract_year,
    harvest,
    is_duplicate,
    merge_person_images,
    normalize_license,
    resize_image,
    sync,
    validate_manifest,
)
from philograph.platform.files import FileStore

req = pytest.mark.req
EP = "entity-portraits"
FIXTURES = Path(__file__).parent / "fixtures" / "portraits"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def info(fixture: dict) -> dict:
    """Первый ``imageinfo`` из ответа Commons API."""
    page = next(iter(fixture["query"]["pages"].values()))
    return page["imageinfo"][0]


def make_fetch(wikidata: dict, imageinfo_by_file: dict, category: dict | None = None):
    """``fetch(url)``, раздающий фикстуры по адресу, как это делает живая сеть."""

    def fetch(url: str) -> dict:
        if "EntityData" in url:
            return wikidata
        query = parse_qs(urlsplit(url).query)
        if query.get("list") == ["categorymembers"]:
            return category or {"query": {"categorymembers": []}}
        if "titles" in query:
            title = query["titles"][0]
            return imageinfo_by_file[title.removeprefix("File:")]
        raise AssertionError(f"неожиданный URL: {url}")

    return fetch


def portrait(size=(320, 400), tint=(120, 90, 70)) -> Image.Image:
    """Детерминированная «фотография»: полосы и овал, чтобы dHash не был пустым."""
    image = Image.new("RGB", size, tint)
    draw = ImageDraw.Draw(image)
    for y in range(0, size[1], 8):
        draw.line([(0, y), (size[0], y + 4)], fill=((y * 7) % 256, (y * 3) % 256, 128))
    draw.ellipse(
        [size[0] // 4, size[1] // 5, 3 * size[0] // 4, 4 * size[1] // 5], fill=(150, 130, 110)
    )
    return image


def other(size=(320, 400)) -> Image.Image:
    """Заметно другое изображение — шахматная сетка на тёмном фоне."""
    image = Image.new("RGB", size, (20, 30, 40))
    draw = ImageDraw.Draw(image)
    for y in range(0, size[1], 16):
        for x in range(0, size[0], 16):
            if (x // 16 + y // 16) % 2:
                draw.rectangle([x, y, x + 15, y + 15], fill=(230, 220, 200))
    return image


def to_bytes(image: Image.Image, fmt: str = "PNG") -> bytes:
    buf = io.BytesIO()
    image.save(buf, format=fmt)
    return buf.getvalue()


class FakePortraits:
    """Объект с ``add_draft`` вместо базы: запоминает вызовы."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def add_draft(self, entity_id: str, **fields) -> int:
        self.calls.append({"entity_id": entity_id, **fields})
        return len(self.calls)


# --- лицензии и атрибуция -------------------------------------------------------------


@req(EP, "Лицензии и атрибуция")
@pytest.mark.parametrize(
    ("short_name", "code", "reason"),
    [
        ("Public domain", "pd", None),
        ("PD", "pd", None),
        ("CC0", "cc0", None),
        ("CC BY 4.0", "cc-by-4.0", None),
        ("CC BY 3.0", "cc-by-3.0", None),
        ("CC BY", "cc-by", None),
        ("CC BY-SA 4.0", "cc-by-sa-4.0", None),
        ("CC BY-SA", "cc-by-sa", None),
        ("CC BY-NC 4.0", None, "nc"),
        ("CC BY-ND 4.0", None, "nd"),
        ("CC BY-NC-SA 4.0", None, "nc"),
        ("All rights reserved", None, "no-license"),
        ("", None, "no-license"),
        (None, None, "no-license"),
    ],
)
def test_normalize_license(short_name, code, reason):
    assert normalize_license(short_name) == (code, reason)


@req(EP, "Лицензии и атрибуция")
def test_clean_author_strips_html_and_collapses_spaces():
    assert (
        clean_author('<a href="//commons">Johann Gottlieb Becker</a>') == "Johann Gottlieb Becker"
    )
    assert clean_author("  Multiple   spaces &amp; <b>bold</b>  ") == "Multiple spaces & bold"
    assert clean_author(None) is None
    assert clean_author("") is None


@req(EP, "Лицензии и атрибуция")
@pytest.mark.parametrize(
    ("value", "year"),
    [
        ("1790", "1790"),
        ("1 January 1790", "1790"),
        ("1790-01-01 00:00:00", "1790"),
        ("unknown", None),
        ("", None),
        (None, None),
    ],
)
def test_extract_year(value, year):
    assert extract_year(value) == year


@req(EP, "Лицензии и атрибуция")
def test_build_candidate_accepts_pd_with_attribution():
    candidate = build_candidate(
        "Immanuel_Kant_(painted_portrait).jpg", info(load("commons_imageinfo_kant.json"))
    )
    assert candidate["decision"] == "accepted"
    assert candidate["license"] == "pd"
    assert candidate["author"] == "Johann Gottlieb Becker"
    assert candidate["year"] == "1790"
    assert candidate["source_url"].endswith("Immanuel_Kant_(painted_portrait).jpg")


@req(EP, "Лицензии и атрибуция")
def test_build_candidate_rejects_nc_nd_missing_source_and_bad_mime():
    nc = build_candidate("Kant_gemalde_2.jpg", info(load("commons_imageinfo_nc.json")))
    assert nc["decision"] == "rejected" and nc["reason"] == "nc"

    nd = build_candidate("Kant_zeichnung.jpg", info(load("commons_imageinfo_nd.json")))
    assert nd["decision"] == "rejected" and nd["reason"] == "nd"

    no_source = build_candidate(
        "Kant_ohne_quelle.jpg", info(load("commons_imageinfo_no_source.json"))
    )
    assert no_source["decision"] == "rejected" and no_source["reason"] == "no-source"

    bad_mime = build_candidate("Kant_signatur.svg", info(load("commons_imageinfo_bad_mime.json")))
    assert bad_mime["decision"] == "rejected" and bad_mime["reason"] == "bad-mime"


# --- дедупликация, лимит и отбор ------------------------------------------------------


@req(EP, "Отбор портретов персоны")
def test_dhash_detects_duplicate_across_resolutions():
    original = portrait(size=(600, 700))
    smaller = original.resize((300, 350), Image.Resampling.LANCZOS)
    assert is_duplicate(dhash(original), dhash(smaller))
    assert not is_duplicate(dhash(original), dhash(other(size=(600, 700))))


@req(EP, "Отбор портретов персоны")
def test_cap_accepted_keeps_seven():
    images = [{"decision": "accepted", "commons_file": f"{i}.jpg"} for i in range(8)]
    capped = cap_accepted(images, 7)
    assert len([i for i in capped if i["decision"] == "accepted"]) == 7
    assert capped[-1]["commons_file"] == "6.jpg"


@req(EP, "Отбор портретов персоны")
def test_harvest_p18_first_filters_licenses_and_records_phash():
    by_file = {
        "Immanuel_Kant_(painted_portrait).jpg": load("commons_imageinfo_kant.json"),
        "Kant_gemalde_2.jpg": load("commons_imageinfo_nc.json"),
        "Kant_portrait_3.png": load("commons_imageinfo_ccbysa.json"),
    }
    fetch = make_fetch(load("wikidata_kant.json"), by_file, load("commons_category_kant.json"))
    url_to_bytes = {
        info(by_file["Immanuel_Kant_(painted_portrait).jpg"])["url"]: to_bytes(
            portrait(size=(600, 700))
        ),
        info(by_file["Kant_portrait_3.png"])["url"]: to_bytes(other(size=(600, 700))),
    }
    download = url_to_bytes.__getitem__

    result = harvest("Q9312", fetch=fetch, download=download, category_limit=50)

    assert result["name"] == "Иммануил Кант"
    images = result["images"]
    assert images[0]["commons_file"] == "Immanuel_Kant_(painted_portrait).jpg"
    assert images[0]["decision"] == "accepted" and images[0]["license"] == "pd"

    nc = next(i for i in images if i["commons_file"] == "Kant_gemalde_2.jpg")
    assert nc["decision"] == "rejected" and nc["reason"] == "nc"

    sa = next(i for i in images if i["commons_file"] == "Kant_portrait_3.png")
    assert sa["decision"] == "accepted" and sa["license"] == "cc-by-sa-4.0"
    assert isinstance(sa["phash"], str) and len(sa["phash"]) == 16


@req(EP, "Отбор портретов персоны")
def test_merge_person_images_skips_existing():
    existing = [{"commons_file": "a.jpg", "decision": "accepted"}]
    harvested = [
        {"commons_file": "a.jpg", "decision": "duplicate"},
        {"commons_file": "b.jpg", "decision": "accepted"},
    ]
    merged = merge_person_images(existing, harvested)
    assert [m["commons_file"] for m in merged] == ["a.jpg", "b.jpg"]


# --- манифест и validate --------------------------------------------------------------


def accepted(commons_file, *, phash=None, **overrides):
    base = {
        "commons_file": commons_file,
        "source_url": f"https://commons.wikimedia.org/wiki/File:{commons_file}",
        "license": "pd",
        "license_url": "https://creativecommons.org/publicdomain/mark/1.0/",
        "author": "Автор",
        "year": "1800",
        "width": 100,
        "height": 120,
        "decision": "accepted",
        "reason": None,
    }
    if phash is not None:
        base["phash"] = phash
    return {**base, **overrides}


@req(EP, "Лицензии и атрибуция")
def test_validate_license_and_required_fields():
    manifest = {
        "persons": [
            {
                "name": "Кант",
                "wikidata": "Q9312",
                "images": [
                    accepted("a.jpg", source_url=None, license="cc-by-nc-4.0", license_url=None),
                    {"commons_file": "b.jpg", "decision": "rejected", "reason": "wrong"},
                    accepted("c.jpg", reason="nc"),
                ],
            }
        ]
    }
    problems = "\n".join(validate_manifest(manifest))
    assert "accepted без source_url" in problems
    assert "недопустимая лицензия 'cc-by-nc-4.0'" in problems
    assert "rejected с неверной причиной 'wrong'" in problems
    assert "accepted с причиной 'nc'" in problems


@req(EP, "Отбор портретов персоны")
def test_validate_duplicate_phash_and_limit():
    images = [accepted(f"p{i}.jpg", phash="0123456789abcdef") for i in range(8)]
    manifest = {"persons": [{"name": "Кант", "wikidata": "Q9312", "images": images}]}
    problems = "\n".join(validate_manifest(manifest))
    assert "дубль phash" in problems
    assert "принятых 8, максимум 7" in problems


@req(EP, "Лицензии и атрибуция")
def test_validate_clean_manifest_has_no_problems():
    manifest = {
        "persons": [
            {
                "name": "Кант",
                "wikidata": "Q9312",
                "images": [accepted("a.jpg", phash="0123456789abcdef")],
            }
        ]
    }
    assert validate_manifest(manifest) == []


# --- sync -----------------------------------------------------------------------------


def accepted_entry(**overrides):
    base = {
        "commons_file": "Immanuel_Kant_(painted_portrait).jpg",
        "source_url": "https://commons.wikimedia.org/wiki/File:Immanuel_Kant_(painted_portrait).jpg",
        "license": "pd",
        "license_url": "https://creativecommons.org/publicdomain/mark/1.0/",
        "author": "Johann Gottlieb Becker",
        "year": "1790",
        "width": 480,
        "height": 600,
        "phash": "0123456789abcdef",
        "decision": "accepted",
        "reason": None,
    }
    return {**base, **overrides}


@req(EP, "Хранение и раздача изображений")
def test_sync_downloads_adds_draft_and_is_idempotent(tmp_path):
    manifest = {"persons": [{"name": "Кант", "wikidata": "Q9312", "images": [accepted_entry()]}]}
    files = FileStore(tmp_path / "files")
    fake = FakePortraits()
    fetch = lambda url: load("commons_imageinfo_kant.json")  # noqa: E731
    download = lambda url: to_bytes(portrait(size=(600, 700)))  # noqa: E731
    resolve = lambda qid: "e_kant"  # noqa: E731

    first = sync(manifest, files, fake, resolve_entity=resolve, fetch=fetch, download=download)
    second = sync(manifest, files, fake, resolve_entity=resolve, fetch=fetch, download=download)

    assert first == {"created": 1, "skipped": 0, "unlinked": 0}
    assert second == {"created": 0, "skipped": 1, "unlinked": 0}
    assert len(fake.calls) == 1

    entry = manifest["persons"][0]["images"][0]
    assert entry["file_id"] and files.exists(entry["file_id"])

    call = fake.calls[0]
    assert call["entity_id"] == "e_kant"
    assert call["file_id"] == entry["file_id"]
    assert call["year"] == "1790"  # строка года из манифеста → целое для таблицы
    assert call["license"] == "pd"
    assert call["origin"] == "commons:File:Immanuel_Kant_(painted_portrait).jpg"
    assert call["phash"] == "0123456789abcdef"


# --- ресайз ---------------------------------------------------------------------------


@req(EP, "Хранение и раздача изображений")
def test_resize_reduces_large_image_and_keeps_format():
    large = portrait(size=(1000, 800))
    data = to_bytes(large, fmt="JPEG")
    resized, width, height = resize_image(data)
    assert (width, height) == (480, 384)  # 1000×800 → 480 по длинной стороне
    reopened = Image.open(io.BytesIO(resized))
    assert reopened.format == "JPEG"
    assert reopened.size == (width, height)


@req(EP, "Отбор портретов персоны")
def test_harvest_rejects_oversized_download():
    """Предел скачивания: файл больше 8 МБ не сохраняется."""
    by_file = {
        "Immanuel_Kant_(painted_portrait).jpg": load("commons_imageinfo_kant.json"),
        "Kant_gemalde_2.jpg": load("commons_imageinfo_nc.json"),
        "Kant_portrait_3.png": load("commons_imageinfo_ccbysa.json"),
    }
    fetch = make_fetch(load("wikidata_kant.json"), by_file, load("commons_category_kant.json"))
    huge = b"\xff\xd8\xff" + b"0" * (MAX_BYTES + 1)
    result = harvest("Q9312", fetch=fetch, download=lambda url: huge)
    image = result["images"][0]
    assert image["decision"] == "rejected" and image["reason"] == "too-large"


@req(EP, "Отбор портретов персоны")
def test_candidate_prefers_thumbnail():
    """Скачиваем эскиз Commons, если он есть: оригинал в карточку не нужен."""
    fixture = load("commons_imageinfo_kant.json")
    metadata = info(fixture)
    metadata["thumburl"] = "https://upload.wikimedia.org/thumb.jpg"
    assert build_candidate("x.jpg", metadata)["image_url"] == metadata["thumburl"]


@req(EP, "Отбор портретов персоны")
def test_harvest_does_not_expand_category_by_default():
    """Категория Commons по умолчанию не подмешивается: там бывают посторонние фотографии."""
    by_file = {
        "Immanuel_Kant_(painted_portrait).jpg": load("commons_imageinfo_kant.json"),
        "Kant_gemalde_2.jpg": load("commons_imageinfo_nc.json"),
        "Kant_portrait_3.png": load("commons_imageinfo_ccbysa.json"),
    }
    fetch = make_fetch(load("wikidata_kant.json"), by_file, load("commons_category_kant.json"))
    images = harvest("Q9312", fetch=fetch, download=lambda url: to_bytes(portrait()))["images"]
    assert [i["commons_file"] for i in images] == ["Immanuel_Kant_(painted_portrait).jpg"]
