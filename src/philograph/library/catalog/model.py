"""Каталог источников: чтение, запись, итоговые метаданные и проверка.

Каталог — ``sources/catalog.yaml``. В записи метаданные с сайта (``harvested``) и правки
человека (``override``) лежат раздельно: адаптер перезаписывает только первые, итоговое
значение поля — правка, если она есть.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from philograph.library.registry import COPYRIGHT_YEARS, License

HEADER = (
    "# Каталог источников PhiloGraph. Формат: sources/catalog.schema.json,\n"
    "# процесс: docs/architecture/source-ingestion.md. Тексты здесь не хранятся.\n"
    "# harvested пишет адаптер (python -m philograph.library.catalog harvest),\n"
    "# override и review — человек.\n"
)
REGISTRY_FIELDS = ("year", "edition", "publisher", "editor", "isbn")


@dataclass
class Problem:
    level: str  # error | warning
    entry: str | None
    message: str

    def __str__(self) -> str:
        where = f"[{self.entry}] " if self.entry else ""
        return f"{self.level}: {where}{self.message}"


@dataclass
class Catalog:
    path: Path
    entries: list[dict[str, Any]] = field(default_factory=list)

    @property
    def root(self) -> Path:
        return self.path.parent

    @property
    def lock_path(self) -> Path:
        return self.path.with_name("catalog.lock.json")

    @property
    def schema_path(self) -> Path:
        return self.path.with_name("catalog.schema.json")

    @property
    def licenses_path(self) -> Path:
        return self.path.with_name("licenses.yaml")

    @classmethod
    def load(cls, path: Path) -> Catalog:
        path = Path(path)
        if not path.exists():
            return cls(path, [])
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls(path, list(data.get("entries") or []))

    def save(self) -> None:
        body = yaml.safe_dump(
            {"version": 1, "entries": self.entries},
            allow_unicode=True,
            sort_keys=False,
            width=100,
        )
        self.path.write_text(HEADER + body, encoding="utf-8", newline="\n")
        issued = sorted(set(self.issued()) | {e["id"] for e in self.entries})
        self.lock_path.write_text(
            json.dumps({"issued": issued}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )

    def issued(self) -> list[str]:
        if not self.lock_path.exists():
            return []
        return list(json.loads(self.lock_path.read_text(encoding="utf-8")).get("issued", []))

    def find(self, entry_id: str) -> dict[str, Any] | None:
        return next((e for e in self.entries if e["id"] == entry_id), None)

    def by_url(self, url: str) -> dict[str, Any] | None:
        norm = normalize_url(url)
        return next((e for e in self.entries if normalize_url(e["landing_url"]) == norm), None)

    def licenses(self) -> list[dict[str, Any]]:
        if not self.licenses_path.exists():
            return []
        return list(yaml.safe_load(self.licenses_path.read_text(encoding="utf-8")) or [])

    def unique_id(self, base: str) -> str:
        taken = {e["id"] for e in self.entries} | set(self.issued())
        candidate, n = base, 2
        while candidate in taken:
            candidate, n = f"{base}-{n}", n + 1
        return candidate


def normalize_url(url: str) -> str:
    url = url.strip()
    if url.startswith("http://"):
        url = "https://" + url[len("http://") :]
    return url.rstrip("/")


# --- итоговые значения --------------------------------------------------------------


def metadata(entry: dict[str, Any]) -> dict[str, Any]:
    """Итоговые метаданные: правка человека важнее значения с сайта."""
    harvested = (entry.get("harvested") or {}).get("metadata") or {}
    override = (entry.get("override") or {}).get("metadata") or {}
    return {**harvested, **override}


def files(entry: dict[str, Any]) -> list[dict[str, Any]]:
    override = (entry.get("override") or {}).get("files")
    if override:
        return list(override)
    return list((entry.get("harvested") or {}).get("files") or [])


def license_of(entry: dict[str, Any]) -> License | None:
    lic = entry.get("license")
    if not lic:
        return None
    meta = metadata(entry)
    deaths = list(lic.get("author_death_years") or [])
    if not deaths and lic["basis"] == "public_domain":
        deaths = [a["death_year"] for a in meta.get("authors") or [] if a.get("death_year")]
    translator_year = lic.get("translator_death_year")
    if translator_year is None and lic["basis"] == "public_domain":
        translator_year = (meta.get("translator") or {}).get("death_year")
    return License(
        kind=lic["kind"],
        basis=lic["basis"],
        author_death_years=deaths,
        translator_death_year=translator_year,
        document_url=lic.get("document_url"),
        narrowed=dict(lic.get("narrowed") or {}),
        regions=list(lic["regions"]) if lic.get("regions") else None,
    )


def registry_fields(entry: dict[str, Any]) -> dict[str, Any]:
    """Поля для учёта источников из записи каталога."""
    meta = metadata(entry)
    fields: dict[str, Any] = {
        "title": meta.get("title"),
        "authors": [a["name"] for a in meta.get("authors") or []],
        "language": meta.get("language"),
        "kind": entry["kind"],
        "original_url": entry["landing_url"],
    }
    translator = meta.get("translator")
    fields["translator"] = translator["name"] if translator else None
    for key in REGISTRY_FIELDS:
        fields[key] = meta.get(key)
    return fields


# --- проверка -----------------------------------------------------------------------


def validate(catalog: Catalog, *, year: int) -> list[Problem]:
    problems: list[Problem] = []
    raw = {"version": 1, "entries": catalog.entries}
    if catalog.schema_path.exists():
        schema = json.loads(catalog.schema_path.read_text(encoding="utf-8"))
        validator = jsonschema.Draft202012Validator(schema)
        for error in sorted(validator.iter_errors(raw), key=lambda e: [str(p) for p in e.path]):
            if error.context:
                # у oneOf («объект или null») показываем ошибку в ветке объекта
                branch = [e for e in error.context if e.validator != "type"] or error.context
                error = jsonschema.exceptions.best_match(branch)
            path = list(error.absolute_path)
            entry = None
            if len(path) >= 2 and path[0] == "entries" and isinstance(path[1], int):
                entry = (
                    catalog.entries[path[1]].get("id") if path[1] < len(catalog.entries) else None
                )
                path = path[2:]
            where = ".".join(str(p) for p in path) or "запись"
            problems.append(Problem("error", entry, f"{where}: {error.message}"))
    if any(p.level == "error" for p in problems):
        return problems  # дальнейшие правила полагаются на форму записей

    ids = Counter(e["id"] for e in catalog.entries)
    for entry_id, n in ids.items():
        if n > 1:
            problems.append(Problem("error", entry_id, f"идентификатор повторяется {n} раза"))
    urls = Counter(normalize_url(e["landing_url"]) for e in catalog.entries)
    for url, n in urls.items():
        if n > 1:
            problems.append(Problem("error", None, f"ссылка повторяется {n} раза: {url}"))
    for entry_id in sorted(set(catalog.issued()) - set(ids)):
        problems.append(
            Problem(
                "error",
                entry_id,
                "запись исчезла из каталога; чтобы снять источник, пометьте её "
                "review.status: withdrawn",
            )
        )

    kinds = {k["code"] for k in catalog.licenses()}
    seen_titles: dict[tuple[str, str], str] = {}
    for entry in catalog.entries:
        meta = metadata(entry)
        status = entry["review"]["status"]
        key = (
            str(meta.get("title", "")).lower(),
            str((meta.get("authors") or [{}])[0].get("name", "")).lower(),
        )
        if key[0] and key in seen_titles:
            problems.append(
                Problem(
                    "warning",
                    entry["id"],
                    f"то же название и автор, что у {seen_titles[key]}: "
                    "проверьте, что это другое издание",
                )
            )
        seen_titles.setdefault(key, entry["id"])
        if status != "approved":
            continue
        lic = entry.get("license")
        if not lic:
            problems.append(
                Problem("error", entry["id"], "license: у одобренной записи нет лицензии")
            )
            continue
        if lic["kind"] not in kinds:
            problems.append(
                Problem("error", entry["id"], f"license.kind: нет в licenses.yaml: {lic['kind']}")
            )
        for name in ("title", "language"):
            if not meta.get(name):
                problems.append(Problem("error", entry["id"], f"metadata.{name}: не заполнено"))
        if not meta.get("authors"):
            problems.append(Problem("error", entry["id"], "metadata.authors: не заполнено"))
        if not files(entry):
            problems.append(Problem("error", entry["id"], "files: нет ссылок на файлы"))
        if lic["basis"] == "public_domain":
            built = license_of(entry)
            assert built is not None
            if not built.author_death_years:
                problems.append(
                    Problem(
                        "error",
                        entry["id"],
                        "license: для общественного достояния нужны годы смерти авторов",
                    )
                )
            elif any(y + COPYRIGHT_YEARS >= year for y in built.author_death_years):
                problems.append(
                    Problem(
                        "error",
                        entry["id"],
                        "license: права автора ещё действуют, это не общественное достояние",
                    )
                )
            if meta.get("translator"):
                ty = built.translator_death_year
                if ty is None:
                    problems.append(
                        Problem("error", entry["id"], "license: нужен год смерти переводчика")
                    )
                elif ty + COPYRIGHT_YEARS >= year:
                    problems.append(
                        Problem("error", entry["id"], "license: права переводчика ещё действуют")
                    )
        if lic["basis"] == "rightsholder_permission" and not lic.get("document_url"):
            problems.append(
                Problem("error", entry["id"], "license.document_url: нужна ссылка на разрешение")
            )
    return problems


def counts(catalog: Catalog) -> dict[str, int]:
    return dict(Counter(e["review"]["status"] for e in catalog.entries))
