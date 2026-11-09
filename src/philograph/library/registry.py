"""Учёт источников: описание, лицензии, видимость, версии и публикация.

Публикация, откат, снятие и удаление выполняются одной транзакцией вместе с записью события в
исходящую таблицу: событие для следующих конвейеров не теряется при сбое между ними.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import Connection, Engine, and_, delete, func, select, update

from philograph.library import schema as t
from philograph.library.model import Block, Document, Footnote, NoteRef, PageMark, Section
from philograph.operator.access import ActionLog
from philograph.platform import events
from philograph.platform.clock import Clock, SystemClock

SourceKind = Literal["textbook", "primary", "reference"]
Basis = Literal["public_domain", "open_license", "rightsholder_permission"]
PUBLIC = "public"
PERMISSIONS = ("display", "external_processing", "quoting")
COPYRIGHT_YEARS = 70  # срок охраны после смерти автора, лет

events.define(
    "library.source.registered", "info", "Источник зарегистрирован", required=("source_id", "kind")
)
events.define(
    "library.source.rejected",
    "warning",
    "Регистрация источника отклонена",
    required=("reason",),
    optional=("fields",),
)
events.define(
    "library.source.duplicate",
    "warning",
    "Возможный дубликат источника",
    required=("other_source_id", "by"),
)
events.define(
    "library.license.blocked",
    "warning",
    "Лицензия не позволяет обрабатывать источник",
    required=("source_id", "reason"),
)
events.define(
    "library.scope.changed",
    "info",
    "Смена области видимости источника",
    required=("source_id", "old", "new"),
)
events.define(
    "library.metadata.updated",
    "info",
    "Изменено описание источника",
    required=("source_id", "fields"),
)
events.define(
    "library.access.changed",
    "info",
    "Сменились регионы показа у вида лицензии",
    required=("code", "sources"),
)
events.define(
    "library.version.created",
    "info",
    "Создана версия источника",
    required=("source_id", "version_id", "number"),
)
events.define(
    "library.publish.started",
    "info",
    "Публикация версии начата",
    required=("source_id", "version_id"),
)
events.define(
    "library.publish.refused",
    "warning",
    "Публикация версии отклонена",
    required=("source_id", "version_id", "reason"),
)
events.define(
    "library.version.switched",
    "info",
    "Опубликованная версия источника сменилась",
    required=("source_id", "version_id", "previous"),
)
events.define(
    "library.outbox.recorded",
    "info",
    "Событие для следующих конвейеров записано",
    required=("event_id", "kind", "source_id"),
)
events.define(
    "library.source.unpublished",
    "info",
    "Источник снят с публикации",
    required=("source_id", "reason"),
)
events.define("library.source.deleted", "info", "Источник удалён", required=("source_id",))


class RegistryError(Exception):
    def __init__(self, message: str, *, fields: list[str] | None = None) -> None:
        super().__init__(message)
        self.fields = fields or []


class DuplicateSource(RegistryError):
    def __init__(self, other: str, by: str) -> None:
        super().__init__(f"возможный дубликат источника {other} ({by})")
        self.other = other
        self.by = by


@dataclass
class License:
    kind: str  # код вида лицензии
    basis: Basis
    author_death_years: list[int] = field(default_factory=list)
    translator_death_year: int | None = None
    document_url: str | None = None
    narrowed: dict[str, bool] = field(default_factory=dict)  # сужение разрешений вида
    # Сужение регионов показа. В JSON лицензии не пишется: регионы живут отдельным столбцом,
    # иначе старый код при откате упал бы на неизвестном ключе License(**data).
    regions: list[str] | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "basis": self.basis,
            "author_death_years": self.author_death_years,
            "translator_death_year": self.translator_death_year,
            "document_url": self.document_url,
            "narrowed": self.narrowed,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> License:
        return cls(**data)


def normalize_regions(regions: list[str] | None) -> list[str] | None:
    """Коды стран ISO 3166-1 в верхнем регистре; ``None`` и пустой список — «везде»."""
    if not regions:
        return None
    codes: list[str] = []
    for raw in regions:
        code = str(raw).strip().upper()
        if not (len(code) == 2 and code.isascii() and code.isalpha()):
            raise RegistryError(
                f"код региона — две латинские буквы, получено {raw!r}", fields=["license.regions"]
            )
        if code not in codes:
            codes.append(code)
    return sorted(codes)


def effective_regions(
    kind_regions: list[str] | None, source_regions: list[str] | None
) -> frozenset[str] | None:
    """Действующие регионы источника: пересечение вида и источника.

    ``None`` — везде; пустое множество — нигде (равносильно запрету показа). Значения уже
    нормализованы: коды в верхнем регистре.
    """
    kind_codes = frozenset(kind_regions) if kind_regions else None
    source_codes = frozenset(source_regions) if source_regions else None
    if kind_codes is None and source_codes is None:
        return None
    if kind_codes is None:
        return source_codes
    if source_codes is None:
        return kind_codes
    return kind_codes & source_codes


def effective_permissions(
    kind_permissions: dict[str, bool],
    narrowed: dict[str, bool],
    regions: frozenset[str] | None,
) -> dict[str, bool]:
    """Разрешения с учётом сужения и регионов: пустое пересечение регионов — запрет показа."""
    effective = {p: bool(kind_permissions.get(p)) for p in PERMISSIONS}
    for key, value in narrowed.items():
        effective[key] = effective.get(key, False) and bool(value)
    if regions is not None and not regions:
        effective["display"] = False
    return effective


@dataclass
class Source:
    id: str
    title: str
    authors: list[str]
    language: str
    kind: str
    year: int | None
    license: License
    scope: str
    status: str
    published_version: str | None
    settings: dict[str, Any]
    files: list[dict[str, Any]]
    translator: str | None = None
    edition: str | None = None
    publisher: str | None = None
    editor: str | None = None
    isbn: str | None = None
    original_url: str | None = None


REQUIRED = ("title", "authors", "language", "kind", "license", "scope")
OPTIONAL = ("year", "edition", "publisher", "translator", "editor", "isbn", "original_url")


class Registry:
    def __init__(
        self,
        engine: Engine,
        clock: Clock | None = None,
        *,
        actions: ActionLog | None = None,
        restricted_scopes: bool = False,
    ) -> None:
        self.engine = engine
        self.clock = clock or SystemClock()
        self.actions = actions or ActionLog(engine, self.clock)
        self.restricted_scopes = restricted_scopes  # в первой версии только общая видимость

    # --- виды лицензий ---

    def add_license_kind(
        self,
        code: str,
        title: str,
        url: str | None,
        permissions: dict[str, bool],
        regions: list[str] | None = None,
    ) -> None:
        missing = [p for p in PERMISSIONS if p not in permissions]
        if missing:
            raise RegistryError("у вида лицензии не заданы разрешения", fields=missing)
        codes = normalize_regions(regions)
        shared = False
        with self.engine.begin() as conn:
            previous = (
                conn.execute(select(t.license_kinds).where(t.license_kinds.c.code == code))
                .mappings()
                .first()
            )
            conn.execute(delete(t.license_kinds).where(t.license_kinds.c.code == code))
            conn.execute(
                t.license_kinds.insert().values(
                    code=code, title=title, url=url, permissions=permissions, regions=codes
                )
            )
            if previous is not None and list(previous["regions"] or []) != (codes or []):
                # Регионы вида изменились: у источников этого вида меняются действующие регионы.
                self._share_kind_access(conn, code, permissions, codes)
                shared = True
        if shared:
            events.emit("library.access.changed", code=code, sources=True)

    def _share_kind_access(
        self,
        conn: Connection,
        code: str,
        kind_permissions: dict[str, bool],
        kind_regions: list[str] | None,
    ) -> None:
        """Событие ``source.access_changed`` по каждому источнику, чьи регионы зависят от вида."""
        rows = (
            conn.execute(
                select(t.sources.c.id, t.sources.c.license, t.sources.c.regions).where(
                    t.sources.c.status != "deleted"
                )
            )
            .mappings()
            .all()
        )
        for row in rows:
            license_json = row["license"] or {}
            if license_json.get("kind") != code:
                continue
            regions = effective_regions(kind_regions, row["regions"])
            self._outbox(
                conn,
                "source.access_changed",
                row["id"],
                {
                    "regions": sorted(regions) if regions is not None else None,
                    "permissions": effective_permissions(
                        kind_permissions, license_json.get("narrowed") or {}, regions
                    ),
                },
            )

    def license_kind(self, code: str) -> dict[str, Any] | None:
        with self.engine.begin() as conn:
            row = (
                conn.execute(select(t.license_kinds).where(t.license_kinds.c.code == code))
                .mappings()
                .first()
            )
        return dict(row) if row else None

    def license_kinds(self) -> dict[str, dict[str, Any]]:
        """Все виды лицензий по коду: список источников читается без запроса на каждый вид."""
        with self.engine.begin() as conn:
            rows = conn.execute(select(t.license_kinds)).mappings().all()
        return {row["code"]: dict(row) for row in rows}

    # --- регистрация ---

    def _validate_license(self, lic: License, translator: str | None) -> str | None:
        """Возвращает причину, по которой источник нельзя обрабатывать, или ``None``."""
        if self.license_kind(lic.kind) is None:
            raise RegistryError(f"неизвестный вид лицензии: {lic.kind}", fields=["license"])
        source_regions = normalize_regions(lic.regions)  # проверяет формат кодов стран
        if lic.basis == "public_domain":
            if not lic.author_death_years:
                raise RegistryError(
                    "для общественного достояния нужны годы смерти авторов",
                    fields=["license.author_death_years"],
                )
            if translator and lic.translator_death_year is None:
                raise RegistryError(
                    "для общественного достояния перевода нужен год смерти переводчика",
                    fields=["license.translator_death_year"],
                )
            year = self.clock.now().year
            if any(y + COPYRIGHT_YEARS >= year for y in lic.author_death_years):
                return "авторские права на произведение ещё действуют"
            if translator and lic.translator_death_year + COPYRIGHT_YEARS >= year:
                return "основание не покрывает перевод: права переводчика ещё действуют"
        if lic.basis == "rightsholder_permission" and not lic.document_url:
            raise RegistryError(
                "для разрешения правообладателя нужна ссылка на документ",
                fields=["license.document_url"],
            )
        kind = self.license_kind(lic.kind)
        assert kind is not None
        kind_regions = normalize_regions(kind.get("regions"))
        if (
            kind_regions is not None
            and source_regions is not None
            and not set(source_regions) <= set(kind_regions)
        ):
            raise RegistryError(
                "регионы источника нельзя расширять относительно вида лицензии",
                fields=["license.regions"],
            )
        widened = [k for k, v in lic.narrowed.items() if v and not kind["permissions"].get(k)]
        if widened:
            raise RegistryError(
                "разрешения источника нельзя расширять относительно вида лицензии", fields=widened
            )
        return None

    def register(self, actor: str, *, confirm_duplicate: bool = False, **fields: Any) -> str:
        missing = [f for f in REQUIRED if not fields.get(f)]
        if missing:
            events.emit("library.source.rejected", reason="missing_fields", fields=missing)
            raise RegistryError(f"не хватает полей: {', '.join(missing)}", fields=missing)
        unknown = set(fields) - set(REQUIRED) - set(OPTIONAL) - {"settings", "files"}
        if unknown:
            raise RegistryError(f"неизвестные поля: {', '.join(sorted(unknown))}")
        if fields["kind"] not in ("textbook", "primary", "reference"):
            raise RegistryError(
                "вид источника: учебник, первоисточник или справочное издание", fields=["kind"]
            )
        if fields["scope"] != PUBLIC and not self.restricted_scopes:
            raise RegistryError(
                "в первой версии допустима только общая видимость", fields=["scope"]
            )
        lic: License = fields["license"]
        blocked = self._validate_license(lic, fields.get("translator"))
        if not confirm_duplicate:
            other = self._same_description(fields["title"], fields["authors"], fields.get("year"))
            if other:
                events.emit("library.source.duplicate", other_source_id=other, by="description")
                raise DuplicateSource(other, "description")
        source_id = f"s_{uuid.uuid4().hex[:12]}"
        settings = dict(fields.get("settings") or {})
        settings.setdefault("languages", [fields["language"]])
        with self.engine.begin() as conn:
            conn.execute(
                t.sources.insert().values(
                    id=source_id,
                    title=fields["title"],
                    authors=list(fields["authors"]),
                    language=fields["language"],
                    kind=fields["kind"],
                    license={**lic.to_json(), "blocked": blocked},
                    regions=normalize_regions(lic.regions),
                    scope=fields["scope"],
                    settings=settings,
                    files=list(fields.get("files") or []),
                    status="active",
                    published_version=None,
                    created_at=self.clock.now(),
                    **{k: fields.get(k) for k in OPTIONAL},
                )
            )
            conn.execute(
                t.scope_log.insert().values(
                    source_id=source_id,
                    time=self.clock.now(),
                    actor=actor,
                    old=None,
                    new=fields["scope"],
                )
            )
            self.actions.record(actor, "register_source", source_id, conn=conn)
        events.emit("library.source.registered", source_id=source_id, kind=fields["kind"])
        if blocked:
            events.emit("library.license.blocked", source_id=source_id, reason=blocked)
        return source_id

    def _same_description(self, title: str, authors: list[str], year: int | None) -> str | None:
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(t.sources.c.id, t.sources.c.authors, t.sources.c.year).where(
                    and_(t.sources.c.title == title, t.sources.c.status != "deleted")
                )
            ).all()
        for row in rows:
            if list(row.authors) == list(authors) and row.year == year:
                return row.id
        return None

    def duplicate_files(self, digest: str, exclude: str | None = None) -> list[str]:
        """Источники, у которых в какой-либо версии файл с тем же отпечатком."""
        with self.engine.begin() as conn:
            rows = conn.execute(select(t.versions.c.source_id, t.versions.c.files)).all()
        found = {r.source_id for r in rows if any(f.get("sha256") == digest for f in r.files)}
        found.discard(exclude or "")
        return sorted(found)

    # --- чтение описания ---

    def get(self, source_id: str) -> Source:
        with self.engine.begin() as conn:
            row = (
                conn.execute(select(t.sources).where(t.sources.c.id == source_id))
                .mappings()
                .first()
            )
        if row is None:
            raise RegistryError(f"нет источника {source_id}")
        lic = {k: v for k, v in row["license"].items() if k != "blocked"}
        lic["regions"] = row["regions"]  # регионы — отдельный столбец, не часть JSON лицензии
        return Source(
            id=row["id"],
            title=row["title"],
            authors=list(row["authors"]),
            language=row["language"],
            kind=row["kind"],
            year=row["year"],
            license=License.from_json(lic),
            scope=row["scope"],
            status=row["status"],
            published_version=row["published_version"],
            settings=dict(row["settings"]),
            files=list(row["files"]),
            translator=row["translator"],
            edition=row["edition"],
            publisher=row["publisher"],
            editor=row["editor"],
            isbn=row["isbn"],
            original_url=row["original_url"],
        )

    def blocked_reason(self, source_id: str) -> str | None:
        with self.engine.begin() as conn:
            lic = conn.scalar(select(t.sources.c.license).where(t.sources.c.id == source_id))
        return (lic or {}).get("blocked")

    def permissions(self, source_id: str) -> dict[str, bool]:
        source = self.get(source_id)
        kind = self.license_kind(source.license.kind) or {"permissions": {}}
        regions = effective_regions(kind.get("regions"), source.license.regions)
        return effective_permissions(kind["permissions"], source.license.narrowed, regions)

    def regions(self, source_id: str) -> frozenset[str] | None:
        """Действующие регионы показа: ``None`` — везде, пустое множество — нигде."""
        source = self.get(source_id)
        kind = self.license_kind(source.license.kind) or {}
        return effective_regions(kind.get("regions"), source.license.regions)

    # --- изменения описания, лицензии, видимости ---

    def update_metadata(self, actor: str, source_id: str, **changes: Any) -> None:
        allowed = {"title", "authors", "language", "year", *OPTIONAL}
        bad = set(changes) - allowed
        if bad:
            raise RegistryError(f"эти поля так не меняются: {', '.join(sorted(bad))}")
        with self.engine.begin() as conn:
            conn.execute(update(t.sources).where(t.sources.c.id == source_id).values(**changes))
            self.actions.record(
                actor, "update_source", source_id, {"fields": sorted(changes)}, conn=conn
            )
        events.emit("library.metadata.updated", source_id=source_id, fields=sorted(changes))

    def change_license(self, actor: str, source_id: str, lic: License) -> None:
        source = self.get(source_id)
        blocked = self._validate_license(lic, source.translator)
        regions = normalize_regions(lic.regions)
        kind = self.license_kind(lic.kind) or {"permissions": {}}
        access = {
            "regions": regions,
            "permissions": effective_permissions(
                kind["permissions"], lic.narrowed, effective_regions(kind.get("regions"), regions)
            ),
        }
        with self.engine.begin() as conn:
            conn.execute(
                update(t.sources)
                .where(t.sources.c.id == source_id)
                .values(license={**lic.to_json(), "blocked": blocked}, regions=regions)
            )
            self.actions.record(actor, "change_license", source_id, {"kind": lic.kind}, conn=conn)
            # Регионы и разрешения меняются и без публикации: индексы обновляются по событию.
            self._outbox(conn, "source.access_changed", source_id, access)
        if (
            not self.permissions(source_id)["display"]
            and source.status == "active"
            and (source.published_version)
        ):
            self.unpublish(actor, source_id, reason="license_forbids_display")

    def change_scope(self, actor: str, source_id: str, new_scope: str) -> None:
        if new_scope != PUBLIC and not self.restricted_scopes:
            raise RegistryError("в первой версии допустима только общая видимость")
        old = self.get(source_id).scope
        with self.engine.begin() as conn:
            conn.execute(
                update(t.sources).where(t.sources.c.id == source_id).values(scope=new_scope)
            )
            conn.execute(
                t.scope_log.insert().values(
                    source_id=source_id, time=self.clock.now(), actor=actor, old=old, new=new_scope
                )
            )
        events.emit("library.scope.changed", source_id=source_id, old=old, new=new_scope)

    def scope_history(self, source_id: str) -> list[dict[str, Any]]:
        with self.engine.begin() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    select(t.scope_log)
                    .where(t.scope_log.c.source_id == source_id)
                    .order_by(t.scope_log.c.id)
                ).mappings()
            ]

    def update_settings(self, actor: str, source_id: str, **settings: Any) -> None:
        current = self.get(source_id).settings
        with self.engine.begin() as conn:
            conn.execute(
                update(t.sources)
                .where(t.sources.c.id == source_id)
                .values(settings={**current, **settings})
            )
            self.actions.record(
                actor, "update_settings", source_id, {"keys": sorted(settings)}, conn=conn
            )

    def replace_files(self, actor: str, source_id: str, files: list[dict[str, Any]]) -> None:
        """Новый список файлов источника; версия появится при следующей обработке."""
        if not files or any(
            not f.get("name") or not (f.get("url") or f.get("path")) for f in files
        ):
            raise RegistryError("у каждого файла нужны имя и ссылка или путь", fields=["files"])
        with self.engine.begin() as conn:
            conn.execute(update(t.sources).where(t.sources.c.id == source_id).values(files=files))
            self.actions.record(actor, "replace_files", source_id, {"count": len(files)}, conn=conn)
        events.emit("library.metadata.updated", source_id=source_id, fields=["files"])

    # --- версии ---

    def create_version(
        self,
        source_id: str,
        files: list[dict[str, Any]],
        pipeline_version: str,
        settings: dict[str, Any],
        corrections_digest: str,
    ) -> str:
        version_id = f"v_{uuid.uuid4().hex[:12]}"
        with self.engine.begin() as conn:
            number = (
                conn.scalar(
                    select(func.max(t.versions.c.number)).where(t.versions.c.source_id == source_id)
                )
                or 0
            ) + 1
            conn.execute(
                t.versions.insert().values(
                    id=version_id,
                    source_id=source_id,
                    number=number,
                    state="created",
                    files=files,
                    pipeline_version=pipeline_version,
                    settings=settings,
                    corrections_digest=corrections_digest,
                    created_at=self.clock.now(),
                )
            )
        events.emit(
            "library.version.created", source_id=source_id, version_id=version_id, number=number
        )
        return version_id

    def version(self, version_id: str) -> dict[str, Any]:
        with self.engine.begin() as conn:
            row = (
                conn.execute(select(t.versions).where(t.versions.c.id == version_id))
                .mappings()
                .first()
            )
        if row is None:
            raise RegistryError(f"нет версии {version_id}")
        return dict(row)

    def versions(self, source_id: str) -> list[dict[str, Any]]:
        with self.engine.begin() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    select(t.versions)
                    .where(t.versions.c.source_id == source_id)
                    .order_by(t.versions.c.number)
                ).mappings()
            ]

    def update_version(self, version_id: str, **values: Any) -> None:
        with self.engine.begin() as conn:
            conn.execute(update(t.versions).where(t.versions.c.id == version_id).values(**values))

    # --- структура версии ---

    def save_document(self, version_id: str, doc: Document) -> None:
        with self.engine.begin() as conn:
            for table in (t.sections, t.blocks, t.footnotes):
                conn.execute(delete(table).where(table.c.version_id == version_id))
            order = 0

            def save(section: Section, parent: str | None) -> None:
                nonlocal order
                order += 1
                conn.execute(
                    t.sections.insert().values(
                        version_id=version_id,
                        id=section.id,
                        parent_id=parent,
                        ord=order,
                        kind=section.kind,
                        title=section.title,
                        level=section.level,
                        visible=section.visible,
                        searchable=section.searchable,
                    )
                )
                for i, block in enumerate(section.blocks):
                    conn.execute(
                        t.blocks.insert().values(
                            version_id=version_id,
                            id=block.id,
                            section_id=section.id,
                            ord=i,
                            kind=block.kind,
                            text=block.text,
                            lang=block.lang,
                            pages=[[m.offset, m.label] for m in block.pages],
                            notes=[[r.offset, r.footnote_id] for r in block.notes],
                            detail=block.detail,
                            detail_code=block.detail_code,
                            page=block.page,
                        )
                    )
                for i, note in enumerate(section.footnotes):
                    conn.execute(
                        t.footnotes.insert().values(
                            version_id=version_id,
                            id=note.id,
                            section_id=section.id,
                            ord=i,
                            marker=note.marker,
                            text=note.text,
                            linked=note.linked,
                        )
                    )
                for child in section.children:
                    save(child, section.id)

            for section in doc.sections:
                save(section, None)

    def load_document(self, version_id: str) -> Document:
        with self.engine.begin() as conn:
            secs = (
                conn.execute(
                    select(t.sections)
                    .where(t.sections.c.version_id == version_id)
                    .order_by(t.sections.c.ord)
                )
                .mappings()
                .all()
            )
            blks = (
                conn.execute(
                    select(t.blocks)
                    .where(t.blocks.c.version_id == version_id)
                    .order_by(t.blocks.c.ord)
                )
                .mappings()
                .all()
            )
            notes = (
                conn.execute(
                    select(t.footnotes)
                    .where(t.footnotes.c.version_id == version_id)
                    .order_by(t.footnotes.c.ord)
                )
                .mappings()
                .all()
            )
        built: dict[str, Section] = {}
        roots: list[Section] = []
        for row in secs:
            section = Section(
                row["id"],
                row["kind"],
                row["title"],
                row["level"],
                visible=row["visible"],
                searchable=row["searchable"],
            )
            built[row["id"]] = section
            (built[row["parent_id"]].children if row["parent_id"] else roots).append(section)
        for row in blks:
            built[row["section_id"]].blocks.append(
                Block(
                    row["id"],
                    row["kind"],
                    row["text"],
                    row["lang"],
                    pages=[PageMark(o, label) for o, label in row["pages"]],
                    notes=[NoteRef(o, f) for o, f in row["notes"]],
                    detail=row["detail"],
                    detail_code=row["detail_code"],
                    page=row["page"],
                )
            )
        for row in notes:
            built[row["section_id"]].footnotes.append(
                Footnote(row["id"], row["marker"], row["text"], row["linked"])
            )
        return Document(sections=roots)

    # --- публикация ---

    def _outbox(self, conn: Connection, kind: str, source_id: str, payload: dict[str, Any]) -> str:
        event_id = uuid.uuid4().hex
        conn.execute(
            t.outbox.insert().values(
                event_id=event_id,
                kind=kind,
                payload={"source_id": source_id, **payload},
                created_at=self.clock.now(),
            )
        )
        events.emit("library.outbox.recorded", event_id=event_id, kind=kind, source_id=source_id)
        return event_id

    def _paragraph_ids(self, conn: Connection, version_id: str | None) -> set[str]:
        if version_id is None:
            return set()
        return set(conn.scalars(select(t.blocks.c.id).where(t.blocks.c.version_id == version_id)))

    def publish(self, actor: str, version_id: str) -> None:
        version = self.version(version_id)
        source_id = version["source_id"]
        events.emit("library.publish.started", source_id=source_id, version_id=version_id)
        refuse = None
        if version["state"] not in ("checked", "replaced", "withdrawn"):
            refuse = f"версия в состоянии «{version['state']}», нужна «проверена»"
        elif any(i["level"] == "error" for i in (version["issues"] or [])):
            refuse = "у версии есть ошибки автоматических проверок"
        elif not self.permissions(source_id)["display"]:
            refuse = "лицензия не разрешает показывать текст"
        elif self.blocked_reason(source_id):
            refuse = self.blocked_reason(source_id)
        if refuse:
            events.emit(
                "library.publish.refused", source_id=source_id, version_id=version_id, reason=refuse
            )
            raise RegistryError(refuse)
        summary = version["summary"] or {}
        with self.engine.begin() as conn:
            previous = conn.scalar(
                select(t.sources.c.published_version).where(t.sources.c.id == source_id)
            )
            if previous and previous != version_id:
                conn.execute(
                    update(t.versions).where(t.versions.c.id == previous).values(state="replaced")
                )
            conn.execute(
                update(t.versions).where(t.versions.c.id == version_id).values(state="published")
            )
            conn.execute(
                update(t.sources)
                .where(t.sources.c.id == source_id)
                .values(published_version=version_id, status="active")
            )
            self._record_removed(conn, source_id, previous, version_id, summary)
            changes = self._changes(conn, previous, version_id, summary)
            self._outbox(
                conn,
                "source.published",
                source_id,
                {
                    "version_id": version_id,
                    "previous_version_id": previous,
                    "external_processing": self.permissions(source_id)["external_processing"],
                    **changes,
                },
            )
            self.actions.record(actor, "publish_version", version_id, conn=conn)
        events.emit(
            "library.version.switched",
            source_id=source_id,
            version_id=version_id,
            previous=previous or "",
        )

    def _changes(
        self, conn: Connection, previous: str | None, current: str, summary: dict[str, Any]
    ) -> dict[str, list[str]]:
        now_ids = self._paragraph_ids(conn, current)
        before = self._paragraph_ids(conn, previous)
        if summary and previous and summary.get("against") == previous:
            return {
                "added": summary.get("added", []),
                "changed": summary.get("changed", []),
                "removed": summary.get("removed", []),
                "redirected": summary.get("redirected", {}),
            }
        # Откат или повторная публикация: сравниваем наборы идентификаторов.
        return {
            "added": sorted(now_ids - before),
            "changed": sorted(self._changed_text(conn, previous, current, now_ids & before)),
            "removed": sorted(before - now_ids),
            "redirected": {},
        }

    def _changed_text(self, conn: Connection, a: str | None, b: str, ids: set[str]) -> set[str]:
        if a is None:
            return set()
        texts_a = dict(
            conn.execute(
                select(t.blocks.c.id, t.blocks.c.text).where(t.blocks.c.version_id == a)
            ).all()
        )
        texts_b = dict(
            conn.execute(
                select(t.blocks.c.id, t.blocks.c.text).where(t.blocks.c.version_id == b)
            ).all()
        )
        return {i for i in ids if texts_a.get(i) != texts_b.get(i)}

    def _record_removed(
        self,
        conn: Connection,
        source_id: str,
        previous: str | None,
        current: str,
        summary: dict[str, Any],
    ) -> None:
        if previous is None:
            return
        removed = set(self._paragraph_ids(conn, previous) - self._paragraph_ids(conn, current))
        redirects = summary.get("redirected", {}) if summary.get("against") == previous else {}
        for from_id, to_id in redirects.items():
            conn.execute(delete(t.redirects).where(t.redirects.c.from_id == from_id))
            conn.execute(
                t.redirects.insert().values(from_id=from_id, to_id=to_id, source_id=source_id)
            )
        rows = conn.execute(
            select(t.blocks.c.id, t.blocks.c.section_id, t.sections.c.title)
            .join(
                t.sections,
                and_(
                    t.sections.c.version_id == t.blocks.c.version_id,
                    t.sections.c.id == t.blocks.c.section_id,
                ),
            )
            .where(and_(t.blocks.c.version_id == previous, t.blocks.c.id.in_(removed)))
        ).all()
        for row in rows:
            if row.id in redirects:
                continue
            conn.execute(
                delete(t.removed_paragraphs).where(t.removed_paragraphs.c.paragraph_id == row.id)
            )
            conn.execute(
                t.removed_paragraphs.insert().values(
                    paragraph_id=row.id,
                    source_id=source_id,
                    last_version=previous,
                    section_id=row.section_id,
                    section_title=row.title,
                )
            )
        # Вернувшиеся абзацы (откат) больше не удалены.
        back = self._paragraph_ids(conn, current)
        if back:
            conn.execute(
                delete(t.removed_paragraphs).where(t.removed_paragraphs.c.paragraph_id.in_(back))
            )

    def rollback(self, actor: str, source_id: str, version_id: str) -> None:
        version = self.version(version_id)
        if version["source_id"] != source_id or version["state"] != "replaced":
            raise RegistryError("откатиться можно только к прежней опубликованной версии")
        self.publish(actor, version_id)

    def unpublish(self, actor: str, source_id: str, reason: str = "operator") -> None:
        with self.engine.begin() as conn:
            current = conn.scalar(
                select(t.sources.c.published_version).where(t.sources.c.id == source_id)
            )
            conn.execute(
                update(t.sources).where(t.sources.c.id == source_id).values(status="unpublished")
            )
            if current:
                conn.execute(
                    update(t.versions).where(t.versions.c.id == current).values(state="withdrawn")
                )
            self._outbox(
                conn, "source.unpublished", source_id, {"version_id": current, "reason": reason}
            )
            self.actions.record(actor, "unpublish_source", source_id, {"reason": reason}, conn=conn)
        events.emit("library.source.unpublished", source_id=source_id, reason=reason)

    def republish(self, actor: str, source_id: str) -> None:
        source = self.get(source_id)
        if source.status != "unpublished" or not source.published_version:
            raise RegistryError("источник не снят с публикации")
        self.publish(actor, source.published_version)

    def delete(self, actor: str, source_id: str) -> list[str]:
        """Стирает версии, тексты и правки. Возвращает отпечатки файлов, которые больше никому
        не нужны: их удаляет из хранилища тот, кто им владеет."""
        source = self.get(source_id)
        if source.status == "active" and source.published_version:
            raise RegistryError("сначала снимите источник с публикации")
        with self.engine.begin() as conn:
            version_ids = list(
                conn.scalars(select(t.versions.c.id).where(t.versions.c.source_id == source_id))
            )
            own = {
                f["sha256"]
                for (files,) in conn.execute(
                    select(t.versions.c.files).where(t.versions.c.source_id == source_id)
                )
                for f in files
            }
            shared = {
                f["sha256"]
                for (files,) in conn.execute(
                    select(t.versions.c.files).where(t.versions.c.source_id != source_id)
                )
                for f in files
            }
            last = source.published_version
            if last:
                rows = conn.execute(
                    select(t.blocks.c.id, t.blocks.c.section_id).where(
                        t.blocks.c.version_id == last
                    )
                ).all()
                for row in rows:
                    conn.execute(
                        delete(t.removed_paragraphs).where(
                            t.removed_paragraphs.c.paragraph_id == row.id
                        )
                    )
                    conn.execute(
                        t.removed_paragraphs.insert().values(
                            paragraph_id=row.id,
                            source_id=source_id,
                            last_version=last,
                            section_id=None,
                            section_title=None,
                        )
                    )
            for table in (t.sections, t.blocks, t.footnotes, t.version_log):
                conn.execute(delete(table).where(table.c.version_id.in_(version_ids)))
            conn.execute(delete(t.versions).where(t.versions.c.source_id == source_id))
            conn.execute(delete(t.corrections).where(t.corrections.c.source_id == source_id))
            conn.execute(
                update(t.sources)
                .where(t.sources.c.id == source_id)
                .values(status="deleted", published_version=None, files=[], settings={})
            )
            self._outbox(conn, "source.deleted", source_id, {"version_id": last})
            self.actions.record(actor, "delete_source", source_id, conn=conn)
        events.emit("library.source.deleted", source_id=source_id)
        return sorted(own - shared)

    # --- ссылки на абзацы ---

    def resolve_paragraph(self, paragraph_id: str) -> dict[str, Any]:
        """Куда ведёт ссылка: абзац, перенаправление, удалённый абзац или недоступный источник."""
        with self.engine.begin() as conn:
            target = conn.scalar(
                select(t.redirects.c.to_id).where(t.redirects.c.from_id == paragraph_id)
            )
            pid = target or paragraph_id
            row = conn.execute(
                select(t.blocks.c.version_id, t.blocks.c.section_id, t.versions.c.source_id)
                .join(t.versions, t.versions.c.id == t.blocks.c.version_id)
                .join(
                    t.sources,
                    and_(
                        t.sources.c.id == t.versions.c.source_id,
                        t.sources.c.published_version == t.versions.c.id,
                    ),
                )
                .where(t.blocks.c.id == pid)
            ).first()
            if row is not None:
                status = conn.scalar(
                    select(t.sources.c.status).where(t.sources.c.id == row.source_id)
                )
                if status == "active":
                    return {
                        "status": "found",
                        "paragraph_id": pid,
                        "source_id": row.source_id,
                        "section_id": row.section_id,
                        "redirected": target is not None,
                    }
                return {"status": "source_unavailable", "source_id": row.source_id}
            gone = (
                conn.execute(
                    select(t.removed_paragraphs).where(t.removed_paragraphs.c.paragraph_id == pid)
                )
                .mappings()
                .first()
            )
        if gone is None:
            return {"status": "unknown"}
        source = self.get(gone["source_id"])
        if source.status != "active":
            return {"status": "source_unavailable", "source_id": source.id}
        return {
            "status": "removed",
            "source_id": source.id,
            "section_id": gone["section_id"],
            "section_title": gone["section_title"],
        }

    # --- обзор ---

    def overview(self, needs_decision: bool = False) -> list[dict[str, Any]]:
        with self.engine.begin() as conn:
            rows = (
                conn.execute(
                    select(t.sources)
                    .where(t.sources.c.status != "deleted")
                    .order_by(t.sources.c.created_at)
                )
                .mappings()
                .all()
            )
            result = []
            for row in rows:
                latest = (
                    conn.execute(
                        select(t.versions)
                        .where(t.versions.c.source_id == row["id"])
                        .order_by(t.versions.c.number.desc())
                        .limit(1)
                    )
                    .mappings()
                    .first()
                )
                state = latest["state"] if latest else None
                waiting = bool(
                    latest
                    and (latest["error"] or state in ("awaiting_quality", "checked"))
                    and latest["id"] != row["published_version"]
                )
                item = {
                    "source_id": row["id"],
                    "title": row["title"],
                    "status": row["status"],
                    "published_version": row["published_version"],
                    "latest_version": latest["id"] if latest else None,
                    "latest_state": state,
                    "error": latest["error"] if latest else None,
                    "needs_decision": waiting,
                }
                if not needs_decision or waiting:
                    result.append(item)
        return result

    def outbox_pending(self) -> list[dict[str, Any]]:
        with self.engine.begin() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    select(t.outbox).where(t.outbox.c.sent_at.is_(None)).order_by(t.outbox.c.id)
                ).mappings()
            ]

    def mark_sent(self, event_id: str, when: datetime) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                update(t.outbox).where(t.outbox.c.event_id == event_id).values(sent_at=when)
            )
