"""Отбор портретов персон из Wikidata и Wikimedia Commons.

``python -m philograph.knowledge.portraits_source <команда>``:

  harvest --persons Q1,Q2 [--limit 7]   собрать кандидатов в манифест (сеть)
  sync --root DIR                       скачать принятые файлы в FileStore и завести черновики
  validate                              проверить манифест без сети
  list                                  сводка по манифесту

Сеть ходит только здесь, как в каталоге источников: сервис знаний во время работы читателя
ничего не качает. Все функции, которые ходят в сеть, принимают ``fetch`` (``url -> dict``) и
``download`` (``url -> bytes``), чтобы тесты работали офлайн на фикстурах ответов API.

Манифест — ``sources/portraits.yaml``: для каждой персоны список кандидатов с атрибуцией и
решением. ``phash`` хранится шестнадцатеричной строкой из 16 знаков (dHash 64 бита), ``year`` —
строкой года из ``DateTimeOriginal`` (``null``, если не распознан); при ``sync`` год
преобразуется в целое для таблицы ``portraits``.
"""

from __future__ import annotations

import argparse
import html
import io
import os
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
import yaml
from PIL import Image

from philograph.platform.files import FileStore

USER_AGENT = (
    "PhiloGraph-portraits/1.0 (https://github.com/Alberelloo/ai-history-of-philosophy-platform)"
)

ALLOWED_MIMES = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGES = 7
MAX_SIDE = 480
# Мельче этого в карточке уже мыло: медальон 56–112 px, галерея 400 px по ширине.
MIN_SIDE = 400
# Предел скачивания: эскиз Commons 480 px весит десятки-сотни килобайт, оригиналы — мегабайты.
MAX_BYTES = 8 * 1024 * 1024
DUP_DISTANCE = 6
DEFAULT_CATEGORY_LIMIT = 50

REJECT_REASONS = {
    "nc",
    "nd",
    "no-license",
    "no-source",
    "duplicate",
    "bad-mime",
    "too-small",
    "too-large",
}

DEFAULT_MANIFEST = Path("sources/portraits.yaml")


# --- лицензии и атрибуция -------------------------------------------------------------


_ALLOWED_LICENSE_RE = re.compile(r"cc-by(-sa)?(-\d+(\.\d+)?)?")


def is_allowed_license(code: str | None) -> bool:
    """Код из допустимого набора: ``pd``, ``cc0``, ``cc-by-*``, ``cc-by-sa-*``."""
    if code in ("pd", "cc0"):
        return True
    return bool(code) and _ALLOWED_LICENSE_RE.fullmatch(code) is not None


def normalize_license(short_name: str | None) -> tuple[str | None, str | None]:
    """``LicenseShortName`` в нормализованный код; ``(код, причина_отказа)``.

    Один из элементов всегда ``None``. Допустимы только ``pd``, ``cc0``, ``cc-by-*`` и
    ``cc-by-sa-*``; NC и ND отклоняются, нераспознанное — ``no-license``.
    """
    if not short_name:
        return None, "no-license"
    tokens = re.sub(r"[-_]+", " ", str(short_name).lower()).split()
    if tokens in (["public", "domain"], ["pd"], ["pdm"], ["public", "domain", "mark"]):
        return "pd", None
    if tokens == ["cc0"]:
        return "cc0", None
    if not tokens or tokens[0] != "cc":
        return None, "no-license"
    if "nc" in tokens:
        return None, "nc"
    if "nd" in tokens:
        return None, "nd"
    if "by" not in tokens:
        return None, "no-license"
    sa = "sa" in tokens
    version = next((t for t in tokens if re.fullmatch(r"\d+(\.\d+)?", t)), None)
    code = "cc-by" + ("-sa" if sa else "")
    if version:
        code += f"-{version}"
    return code, None


_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")
_YEAR_RE = re.compile(r"\b(1[0-9]{3}|2[0-9]{3})\b")


def clean_author(value: str | None) -> str | None:
    """Автор из HTML ``Artist``: без тегов и сущностей, схлопнутые пробелы."""
    if not value:
        return None
    text = _TAG_RE.sub("", str(value))
    text = html.unescape(text).replace("\xa0", " ")
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text or None


def extract_year(value: str | None) -> str | None:
    """Год из ``DateTimeOriginal``: первое четырёхзначное число, иначе ``None``."""
    if not value:
        return None
    match = _YEAR_RE.search(str(value))
    return match.group(1) if match else None


# --- изображения ----------------------------------------------------------------------


def dhash(image: Image.Image) -> int:
    """dHash 64 бита: оттенки серого, 9×8, сравнение соседних пикселей по строке."""
    gray = image.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
    pixels = list(gray.tobytes())  # режим «L» — один байт на пиксель, построчно
    bits: list[str] = []
    for y in range(8):
        row = pixels[y * 9 : (y + 1) * 9]
        bits.extend("1" if row[x] > row[x + 1] else "0" for x in range(8))
    return int("".join(bits), 2)


def dhash_bytes(data: bytes) -> int:
    image = Image.open(io.BytesIO(data))
    image.load()
    return dhash(image)


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def is_duplicate(a: int, b: int, threshold: int = DUP_DISTANCE) -> bool:
    return hamming(a, b) <= threshold


def phash_to_hex(value: int) -> str:
    return f"{value:016x}"


def phash_from_hex(value: str | int) -> int:
    return value if isinstance(value, int) else int(value, 16)


def resize_image(data: bytes, max_side: int = MAX_SIDE) -> tuple[bytes, int, int]:
    """Уменьшает до ``max_side`` по длинной стороне и сохраняет в исходном формате.

    Возвращает ``(bytes, width, height)``. Неизвестный формат — ``ValueError``.
    """
    image = Image.open(io.BytesIO(data))
    image.load()
    fmt = image.format
    if not fmt:
        raise ValueError("не удалось определить формат изображения")
    width, height = image.size
    if max(width, height) > max_side:
        scale = max_side / max(width, height)
        width = max(1, round(width * scale))
        height = max(1, round(height * scale))
        image = image.resize((width, height), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    image.save(out, format=fmt)
    return out.getvalue(), width, height


def cap_accepted(images: list[dict[str, Any]], limit: int = MAX_IMAGES) -> list[dict[str, Any]]:
    """Не более ``limit`` принятых; лишние принятые отбрасываются, порядок сохраняется."""
    kept: list[dict[str, Any]] = []
    accepted = 0
    for image in images:
        if image.get("decision") == "accepted":
            if accepted >= limit:
                continue
            accepted += 1
        kept.append(image)
    return kept


# --- сеть: адреса и разбор ответов ----------------------------------------------------


def wikidata_entity_url(qid: str) -> str:
    return f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"


def commons_imageinfo_url(commons_file: str) -> str:
    params = urlencode(
        {
            "action": "query",
            "titles": f"File:{commons_file}",
            "prop": "imageinfo",
            "iiprop": "url|size|mime|extmetadata",
            # Эскиз: оригинал у части файлов (Юм, Витгенштейн) весит десятки мегабайт.
            "iiurlwidth": str(MAX_SIDE),
            "format": "json",
        }
    )
    return f"https://commons.wikimedia.org/w/api.php?{params}"


def commons_category_url(category: str) -> str:
    params = urlencode(
        {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": f"Category:{category}",
            "cmtype": "file",
            "cmlimit": DEFAULT_CATEGORY_LIMIT,
            "format": "json",
        }
    )
    return f"https://commons.wikimedia.org/w/api.php?{params}"


def _claim_value(claims: dict, prop: str) -> str | None:
    for claim in claims.get(prop, []):
        snak = claim.get("mainsnak", {})
        if snak.get("snaktype") == "value":
            value = snak.get("datavalue", {}).get("value")
            if value:
                return str(value)
    return None


def wikidata_image(entity_data: dict) -> tuple[str | None, str | None]:
    """``(P18, P373)``: основное изображение и категория Commons персоны."""
    claims = entity_data.get("claims", {})
    return _claim_value(claims, "P18"), _claim_value(claims, "P373")


def entity_label(entity_data: dict, qid: str) -> str | None:
    labels = entity_data.get("labels") or {}
    for lang in ("ru", "en"):
        value = labels.get(lang, {}).get("value")
        if value:
            return value
    return None


def imageinfo_metadata(commons_file: str, fetch: Callable[[str], dict]) -> dict | None:
    data = fetch(commons_imageinfo_url(commons_file))
    pages = (data.get("query") or {}).get("pages") or {}
    for page in pages.values():
        infos = page.get("imageinfo") or []
        if infos:
            return infos[0]
    return None


def category_files(
    category: str, fetch: Callable[[str], dict], limit: int = DEFAULT_CATEGORY_LIMIT
) -> list[str]:
    data = fetch(commons_category_url(category))
    members = (data.get("query") or {}).get("categorymembers") or []
    files = []
    for member in members[:limit]:
        title = member.get("title") or ""
        if title.startswith("File:"):
            files.append(title[len("File:") :])
    return files


# --- кандидаты и отбор ----------------------------------------------------------------


def build_candidate(commons_file: str, info: dict) -> dict[str, Any]:
    """Кандидат из ``imageinfo``: лицензия, атрибуция, размеры и предварительное решение."""
    extmeta = info.get("extmetadata") or {}

    def meta(name: str) -> str | None:
        value = extmeta.get(name)
        if isinstance(value, dict):
            value = value.get("value")
        return value or None

    width = info.get("width") if isinstance(info.get("width"), int) else None
    height = info.get("height") if isinstance(info.get("height"), int) else None
    if width is not None and width <= 0:
        width = None
    if height is not None and height <= 0:
        height = None

    code, reason = normalize_license(meta("LicenseShortName"))
    # Ссылка на страницу файла — ``descriptionurl`` верхнего уровня (у части файлов есть
    # и в extmetadata как ``DescriptionUrl``); без неё требование атрибуции не выполнено.
    source_url = info.get("descriptionurl") or meta("DescriptionUrl")
    candidate: dict[str, Any] = {
        "commons_file": commons_file,
        "source_url": source_url,
        "license": code,
        "license_url": meta("LicenseUrl"),
        "author": clean_author(meta("Artist")),
        "year": extract_year(meta("DateTimeOriginal")),
        "width": width,
        "height": height,
        "mime": info.get("mime"),
        # Эскиз, если Commons его отдал: в карточке всё равно не больше 480 px.
        "image_url": info.get("thumburl") or info.get("url"),
        "phash": None,
        "decision": "accepted",
        "reason": None,
    }
    if reason:
        candidate["decision"] = "rejected"
        candidate["reason"] = reason
    elif not source_url:
        candidate["decision"] = "rejected"
        candidate["reason"] = "no-source"
    elif info.get("mime") not in ALLOWED_MIMES:
        candidate["decision"] = "rejected"
        candidate["reason"] = "bad-mime"
    elif width is None or height is None or max(width, height) <= MIN_SIDE:
        candidate["decision"] = "rejected"
        candidate["reason"] = "too-small"
    return candidate


def serialize_image(candidate: dict[str, Any]) -> dict[str, Any]:
    """Поля манифеста в порядке вывода; ``phash`` — только когда есть."""
    out: dict[str, Any] = {
        "commons_file": candidate.get("commons_file"),
        "source_url": candidate.get("source_url"),
        "license": candidate.get("license"),
        "license_url": candidate.get("license_url"),
        "author": candidate.get("author"),
        "year": candidate.get("year"),
        "width": candidate.get("width"),
        "height": candidate.get("height"),
    }
    if candidate.get("phash") is not None:
        out["phash"] = candidate["phash"]
    out["decision"] = candidate.get("decision")
    out["reason"] = candidate.get("reason")
    return out


def harvest(
    qid: str,
    *,
    fetch: Callable[[str], dict],
    download: Callable[[str], bytes],
    limit: int = MAX_IMAGES,
    already: list[int] | None = None,
    category_limit: int = 0,
    extra_files: list[str] | None = None,
) -> dict[str, Any]:
    """Кандидаты персоны: ``{name, wikidata, images}`` для манифеста.

    ``P18`` — первым (главное), остальные из категории ``P373`` по убыванию размера оригинала.
    Дубли отсекаются по dHash (расстояние Хэмминга ≤ 6) против уже принятых в этой выборке и
    переданного списка ``already``.
    """
    entity_data = (fetch(wikidata_entity_url(qid)).get("entities") or {}).get(qid, {})
    name = entity_label(entity_data, qid) or qid
    p18, category = wikidata_image(entity_data)

    files: list[str] = []
    if p18:
        files.append(p18)
    # Дополнительные файлы вне P18: когда основное изображение Wikidata мало или плохого качества.
    for commons_file in extra_files or []:
        if commons_file not in files:
            files.append(commons_file)
    seen = set(files)
    if category and len(files) < limit:
        for commons_file in category_files(category, fetch, limit=category_limit):
            if commons_file not in seen:
                files.append(commons_file)
                seen.add(commons_file)

    candidates: list[dict[str, Any]] = []
    for commons_file in files:
        info = imageinfo_metadata(commons_file, fetch)
        if info is not None:
            candidates.append(build_candidate(commons_file, info))

    candidates.sort(
        key=lambda c: (
            0 if c["commons_file"] == p18 else 1,
            -max(c["width"] or 0, c["height"] or 0),
        )
    )

    accepted: list[int] = list(already or [])
    accepted_count = 0
    images: list[dict[str, Any]] = []
    for candidate in candidates:
        if candidate["decision"] == "rejected":
            images.append(candidate)
            continue
        if accepted_count >= limit:
            break  # лимит принятых достигнут, остальных не скачиваем
        if not candidate["image_url"]:
            continue
        try:
            data = download(candidate["image_url"])
        except Exception:
            continue  # временный сбой сети — кандидат просто не попадает в манифест
        if len(data) > MAX_BYTES:
            candidate["decision"] = "rejected"
            candidate["reason"] = "too-large"
            images.append(candidate)
            continue
        value = dhash_bytes(data)
        if any(is_duplicate(value, other) for other in accepted):
            candidate["decision"] = "rejected"
            candidate["reason"] = "duplicate"
            images.append(candidate)
            continue
        try:
            _, width, height = resize_image(data)
        except Exception:
            candidate["decision"] = "rejected"
            candidate["reason"] = "bad-mime"
            images.append(candidate)
            continue
        candidate["width"] = width
        candidate["height"] = height
        candidate["phash"] = phash_to_hex(value)
        accepted.append(value)
        accepted_count += 1
        images.append(candidate)

    return {
        "name": name,
        "wikidata": qid,
        "images": [serialize_image(i) for i in cap_accepted(images, limit)],
    }


# --- манифест -------------------------------------------------------------------------


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"persons": []}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return {"persons": []}
    data.setdefault("persons", [])
    return data


def save_manifest(manifest: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )


def accepted_phash_ints(manifest: dict[str, Any]) -> list[int]:
    out: list[int] = []
    for person in manifest.get("persons", []):
        for image in person.get("images", []):
            if image.get("decision") == "accepted" and image.get("phash") is not None:
                out.append(phash_from_hex(image["phash"]))
    return out


def merge_person_images(
    existing: list[dict[str, Any]], harvested: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Дополняет существующие изображения новыми; повторный ``commons_file`` не дублируется."""
    result = list(existing)
    seen = {image.get("commons_file") for image in existing}
    for image in harvested:
        commons_file = image.get("commons_file")
        if commons_file in seen:
            continue
        seen.add(commons_file)
        result.append(image)
    return result


def harvest_persons(
    manifest: dict[str, Any],
    qids: list[str],
    *,
    fetch: Callable[[str], dict],
    download: Callable[[str], bytes],
    limit: int = MAX_IMAGES,
    extras: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Дополняет манифест результатами ``harvest`` — идемпотентно по ``commons_file``."""
    persons = manifest.setdefault("persons", [])
    by_wikidata = {p.get("wikidata"): p for p in persons if p.get("wikidata")}
    already = accepted_phash_ints(manifest)
    for qid in qids:
        person = harvest(
            qid,
            fetch=fetch,
            download=download,
            limit=limit,
            already=already,
            extra_files=(extras or {}).get(qid),
        )
        existing = by_wikidata.get(qid)
        if existing:
            existing.setdefault("name", person["name"])
            existing["images"] = merge_person_images(existing.get("images", []), person["images"])
        else:
            persons.append(person)
            by_wikidata[qid] = person
        for image in person["images"]:
            if image.get("decision") == "accepted" and image.get("phash") is not None:
                already.append(phash_from_hex(image["phash"]))
    return manifest


# --- проверка и синхронизация ---------------------------------------------------------


def validate_manifest(manifest: dict[str, Any]) -> list[str]:
    """Проверяет манифест без сети; возвращает список сообщений об ошибках."""
    problems: list[str] = []
    persons = manifest.get("persons")
    if not isinstance(persons, list):
        return ["persons: ожидается список"]
    seen_wikidata: set[str] = set()
    global_phash: dict[str, str] = {}
    for person_index, person in enumerate(persons):
        if not isinstance(person, dict):
            problems.append(f"persons[{person_index}]: ожидается словарь")
            continue
        label = person.get("name") or person.get("wikidata") or f"persons[{person_index}]"
        wikidata = person.get("wikidata")
        if not wikidata:
            problems.append(f"{label}: нет wikidata")
        elif wikidata in seen_wikidata:
            problems.append(f"{label}: повторный wikidata {wikidata}")
        else:
            seen_wikidata.add(wikidata)
        images = person.get("images")
        if not isinstance(images, list):
            problems.append(f"{label}: images — не список")
            continue
        accepted = 0
        seen_files: set[str] = set()
        for image_index, image in enumerate(images):
            if not isinstance(image, dict):
                problems.append(f"{label}[{image_index}]: ожидается словарь")
                continue
            ilabel = f"{label}[{image_index}]"
            decision = image.get("decision")
            reason = image.get("reason")
            if decision == "accepted":
                accepted += 1
                if reason is not None:
                    problems.append(f"{ilabel}: accepted с причиной {reason!r}")
            elif decision == "rejected":
                if reason not in REJECT_REASONS:
                    problems.append(f"{ilabel}: rejected с неверной причиной {reason!r}")
            else:
                problems.append(f"{ilabel}: неверный decision {decision!r}")
                continue
            commons_file = image.get("commons_file")
            if not commons_file:
                problems.append(f"{ilabel}: нет commons_file")
            elif commons_file in seen_files:
                problems.append(f"{ilabel}: повторный файл {commons_file}")
            else:
                seen_files.add(commons_file)
            if decision == "accepted":
                # ``license_url`` не обязателен: у общественного достояния Commons его не отдаёт.
                for field in ("source_url", "license"):
                    if not image.get(field):
                        problems.append(f"{ilabel}: accepted без {field}")
                if not is_allowed_license(image.get("license")):
                    problems.append(f"{ilabel}: недопустимая лицензия {image.get('license')!r}")
                width, height = image.get("width"), image.get("height")
                if not (
                    isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0
                ):
                    problems.append(f"{ilabel}: неверные размеры {width!r}×{height!r}")
                phash = image.get("phash")
                if phash is not None:
                    key = str(phash)
                    if key in global_phash:
                        problems.append(f"{ilabel}: дубль phash с {global_phash[key]}")
                    else:
                        global_phash[key] = ilabel
        if accepted > MAX_IMAGES:
            problems.append(f"{label}: принятых {accepted}, максимум {MAX_IMAGES}")
    return problems


def sync(
    manifest: dict[str, Any],
    files: FileStore,
    portraits: Any,
    *,
    resolve_entity: Callable[[str], str | None],
    fetch: Callable[[str], dict],
    download: Callable[[str], bytes],
    save: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, int]:
    """Скачивает принятые файлы в ``FileStore`` и заводит черновики через ``add_draft``.

    Идемпотентно: у синхронизированного кандидата в манифест пишется ``file_id``, повторный
    запуск без изменений пропускает его. ``portraits`` — объект с методом ``add_draft``
    (duck typing), чтобы тест подставлял фейк без базы.
    """
    created = 0
    skipped = 0
    unlinked = 0
    for person in manifest.get("persons", []):
        qid = person.get("wikidata")
        entity_id = resolve_entity(qid) if qid else None
        for entry in person.get("images", []):
            if entry.get("decision") != "accepted":
                continue
            file_id = entry.get("file_id")
            if file_id and files.exists(file_id):
                skipped += 1
                continue
            if entity_id is None:
                unlinked += 1
                continue
            if not entry.get("license") or not entry.get("source_url") or not entry.get("phash"):
                continue
            info = imageinfo_metadata(entry["commons_file"], fetch)
            source = (info or {}).get("thumburl") or (info or {}).get("url")
            if not source:
                continue
            data = download(source)
            if len(data) > MAX_BYTES:
                entry["decision"] = "rejected"
                entry["reason"] = "too-large"
                continue
            try:
                resized, width, height = resize_image(data)
            except Exception:
                entry["decision"] = "rejected"
                entry["reason"] = "bad-mime"
                continue
            file_id = files.put(resized)
            portraits.add_draft(
                entity_id,
                file_id=file_id,
                width=width,
                height=height,
                author=entry.get("author"),
                year=entry.get("year"),
                license=entry["license"],
                license_url=entry.get("license_url"),
                source_url=entry["source_url"],
                origin=f"commons:File:{entry['commons_file']}",
                phash=entry["phash"],
            )
            entry["file_id"] = file_id
            entry["width"] = width
            entry["height"] = height
            created += 1
    if save is not None:
        save(manifest)
    return {"created": created, "skipped": skipped, "unlinked": unlinked}


def summary(manifest: dict[str, Any]) -> str:
    lines: list[str] = []
    for person in manifest.get("persons", []):
        images = person.get("images", [])
        accepted = [i for i in images if i.get("decision") == "accepted"]
        synced = [i for i in accepted if i.get("file_id")]
        lines.append(
            f"{person.get('name')} ({person.get('wikidata')}): принято {len(accepted)}, "
            f"отклонено {len(images) - len(accepted)}, синхронизировано {len(synced)}"
        )
    return "\n".join(lines)


# --- CLI ------------------------------------------------------------------------------


def _make_http() -> tuple[Callable[[str], dict], Callable[[str], bytes]]:
    client = httpx.Client(
        headers={"User-Agent": USER_AGENT},
        timeout=httpx.Timeout(120.0, connect=30.0),
        follow_redirects=True,
    )

    def fetch(url: str) -> dict:
        response = client.get(url)
        response.raise_for_status()
        return response.json()

    def download(url: str) -> bytes:
        response = client.get(url)
        response.raise_for_status()
        return response.content

    return fetch, download


def _service(files_root: Path):
    """Сервис знаний для ``sync``: сущности для связи по внешнему ключу и ``Portraits``."""
    from philograph.knowledge import schema
    from philograph.knowledge.entities import Entities
    from philograph.knowledge.portraits import Portraits
    from philograph.knowledge.registry import OntologyRegistry
    from philograph.platform.db import make_engine

    engine = make_engine(os.environ["PHILOGRAPH_DATABASE_URL"], [schema.SCHEMA])
    schema.migrations.upgrade(engine)
    registry = OntologyRegistry(engine)
    registry.load_defaults()
    entities = Entities(engine, registry)
    files = FileStore(files_root)
    return entities, Portraits(engine, files), files


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        prog="python -m philograph.knowledge.portraits_source",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("harvest", help="собрать кандидатов в манифест")
    p.add_argument("--persons", required=True, help="Q-идентификаторы через запятую: Q9312,Q9061")
    p.add_argument("--limit", type=int, default=MAX_IMAGES)
    p.add_argument(
        "--extra",
        action="append",
        default=[],
        metavar="QID=File:Имя.jpg",
        help="дополнительный файл Commons вне P18 (когда основное изображение мало)",
    )

    p = sub.add_parser("sync", help="скачать принятые файлы и завести черновики")
    p.add_argument("--root", type=Path, required=True, help="каталог FileStore")

    sub.add_parser("validate", help="проверить манифест без сети")
    sub.add_parser("list", help="сводка по манифесту")

    args = parser.parse_args(argv)
    manifest_path = args.manifest
    manifest = load_manifest(manifest_path)

    if args.command == "validate":
        problems = validate_manifest(manifest)
        for problem in problems:
            print(f"  ✗ {problem}")
        print(f"ошибок: {len(problems)}")
        return 1 if problems else 0

    if args.command == "list":
        print(summary(manifest))
        return 0

    if args.command == "harvest":
        qids = [q.strip() for q in args.persons.split(",") if q.strip()]
        extras: dict[str, list[str]] = {}
        for item in args.extra:
            qid, _, commons_file = item.partition("=")
            name = commons_file.strip()
            if name.startswith("File:"):  # в подсказке пишут «File:Имя», в API — без префикса
                name = name[len("File:") :]
            if not qid or not name:
                print(f"пропущено дополнение {item!r}: ожидается QID=File:Имя", file=sys.stderr)
                continue
            extras.setdefault(qid.strip(), []).append(name)
        fetch, download = _make_http()
        harvest_persons(
            manifest,
            qids,
            fetch=fetch,
            download=download,
            limit=args.limit,
            extras=extras,
        )
        save_manifest(manifest, manifest_path)
        for person in manifest["persons"]:
            if person.get("wikidata") in qids:
                images = person.get("images", [])
                accepted = sum(1 for i in images if i.get("decision") == "accepted")
                print(f"{person.get('name')} ({person.get('wikidata')}): принято {accepted}")
        return 0

    entities, portraits, files = _service(args.root)
    fetch, download = _make_http()
    result = sync(
        manifest,
        files,
        portraits,
        resolve_entity=lambda qid: entities.by_external("wikidata", qid),
        fetch=fetch,
        download=download,
        save=lambda m: save_manifest(m, manifest_path),
    )
    print(
        f"создано: {result['created']}, пропущено: {result['skipped']}, "
        f"без сущности: {result['unlinked']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
