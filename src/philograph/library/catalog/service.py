"""Каталог ↔ библиотека: добавление по ссылке, сбор метаданных, синхронизация, проверка обновлений.

Синхронизация обрабатывает только одобренные записи. Для каждой:
1. связь с источником учёта (таблица ``catalog_links``) или регистрация;
2. описание, лицензия и файлы приводятся к записи;
3. обработка конвейером (версия не создаётся, если входы те же);
4. правило публикации: см. ``Policy``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select

from philograph.library import schema as t
from philograph.library.catalog import model
from philograph.library.catalog.adapters import Wikidata, adapter_for, slugify, suggest_license
from philograph.library.catalog.fetcher import Fetcher, FetchError, now_iso
from philograph.library.processing import Pipeline, ProcessingBusy, StepFailed
from philograph.library.registry import OPTIONAL, Registry, RegistryError, normalize_regions
from philograph.platform import events
from philograph.platform.clock import Clock, SystemClock

events.define(
    "library.catalog.synced",
    "info",
    "Запись каталога синхронизирована",
    required=("catalog_id", "outcome"),
    optional=("source_id", "version_id"),
)
events.define(
    "library.catalog.needs_decision",
    "warning",
    "Новая версия источника ждёт решения оператора",
    required=("catalog_id", "source_id", "version_id", "reason"),
)
events.define(
    "library.catalog.withdrawn",
    "info",
    "Источник снят с публикации по каталогу",
    required=("catalog_id", "source_id"),
)

AUTO_REMOVED_SHARE = 0.02  # доля удалённых абзацев, до которой обновление публикуется само
# Поля файла, которые уходят в реестр источника; missing — подстраницы нет на сайте.
FILE_KEYS = ("name", "url", "clean", "api", "missing")


@dataclass
class Outcome:
    catalog_id: str
    outcome: str  # короткий код итога
    detail: str = ""
    source_id: str | None = None
    version_id: str | None = None
    state: str | None = None

    def row(self) -> list[str]:
        return [
            self.catalog_id,
            self.outcome,
            self.state or "",
            self.version_id or "",
            self.detail,
        ]


OUTCOMES = {
    "unchanged": "изменений нет",
    "published": "опубликовано",
    "published_same_text": "опубликовано: текст тот же",
    "waiting_operator": "ждёт публикации оператором",
    "waiting_quality": "нужно решение по качеству",
    "deferred": "отложено",
    "failed": "ошибка",
    "blocked": "лицензия не позволяет",
    "draft": "ждёт одобрения",
    "rejected": "отклонена",
    "withdrawn": "снято с публикации",
    "withdrawn_already": "отозвана",
    "dry_run": "будет обработана",
}


@dataclass
class Change:
    field: str
    old: Any
    new: Any


@dataclass
class CatalogService:
    catalog: model.Catalog
    registry: Registry
    pipeline: Pipeline
    fetcher: Fetcher
    clock: Clock = field(default_factory=SystemClock)
    actor: str = "catalog"

    # --- связь с учётом -------------------------------------------------------------

    def linked(self, catalog_id: str) -> str | None:
        with self.registry.engine.begin() as conn:
            row = conn.execute(
                select(t.catalog_links.c.source_id).where(
                    t.catalog_links.c.catalog_id == catalog_id
                )
            ).first()
        return row[0] if row else None

    def _link(self, catalog_id: str, source_id: str) -> None:
        with self.registry.engine.begin() as conn:
            conn.execute(
                t.catalog_links.insert().values(
                    catalog_id=catalog_id, source_id=source_id, linked_at=self.clock.now()
                )
            )

    def ensure_license_kinds(self) -> None:
        for kind in self.catalog.licenses():
            current = self.registry.license_kind(kind["code"])
            regions = normalize_regions(kind.get("regions"))
            if (
                current is None
                or current["permissions"] != kind["permissions"]
                or current["title"] != kind["title"]
                or list(current["regions"] or []) != (regions or [])
            ):
                self.registry.add_license_kind(
                    kind["code"], kind["title"], kind.get("url"), kind["permissions"], regions
                )

    # --- добавление и сбор метаданных -------------------------------------------------

    def add(
        self, url: str, *, kind: str, section: str | None = None, adapter: str | None = None
    ) -> tuple[dict[str, Any], bool]:
        """Черновик записи по ссылке. Возвращает запись и признак «новая»."""
        existing = self.catalog.by_url(url)
        if existing:
            return existing, False
        chosen = adapter_for(url, adapter)
        harvest = chosen.harvest(url, self.fetcher)
        entry: dict[str, Any] = {
            "id": self.catalog.unique_id(slugify(harvest.slug_hint)),
            "landing_url": url,
            "adapter": chosen.name,
            "kind": kind,
            "section": section,
            "harvested": {
                "at": now_iso(self.clock),
                "adapter_version": chosen.version,
                "metadata": harvest.metadata,
                "files": harvest.files,
                "license_hint": harvest.license_hint,
            },
            "override": {},
            "license": suggest_license(harvest, self.clock.now().year),
            "review": {"status": "draft", "by": None, "at": None, "note": None},
            "publish": "auto" if chosen.name != "direct" else "manual",
        }
        self.catalog.entries.append(entry)
        return entry, True

    def harvest(self, entry: dict[str, Any]) -> list[Change]:
        """Обновляет данные с сайта; правки человека не трогает. Возвращает изменения."""
        chosen = adapter_for(entry["landing_url"], entry["adapter"])
        before = model.metadata(entry), model.files(entry)
        result = chosen.harvest(entry["landing_url"], self.fetcher)
        entry["harvested"] = {
            "at": now_iso(self.clock),
            "adapter_version": chosen.version,
            "metadata": result.metadata,
            "files": result.files,
            "license_hint": result.license_hint,
        }
        after = model.metadata(entry), model.files(entry)
        changes = [
            Change(key, before[0].get(key), after[0].get(key))
            for key in sorted(set(before[0]) | set(after[0]))
            if before[0].get(key) != after[0].get(key)
        ]
        if before[1] != after[1]:
            changes.append(Change("files", before[1], after[1]))
        return changes

    def fill_death_years(self, entry: dict[str, Any]) -> None:
        """Дописывает годы смерти из Wikidata тем, у кого их нет (в данных сайта)."""
        meta = (entry.get("harvested") or {}).get("metadata") or {}
        wikidata = Wikidata(self.fetcher)
        people = list(meta.get("authors") or [])
        if meta.get("translator"):
            people.append(meta["translator"])
        for person in people:
            if person.get("death_year") is None and person.get("name"):
                try:
                    found = wikidata.find_person(person["name"], meta.get("language") or "en")
                except FetchError:
                    found = None
                if found:
                    person["death_year"] = found["death_year"]
                    person["wikidata"] = found["wikidata"]

    # --- синхронизация ----------------------------------------------------------------

    def sync(self, ids: list[str] | None = None, *, dry_run: bool = False) -> list[Outcome]:
        self.ensure_license_kinds()
        outcomes = []
        for entry in self.catalog.entries:
            if ids and entry["id"] not in ids:
                continue
            outcome = self._sync_entry(entry, dry_run=dry_run)
            events.emit(
                "library.catalog.synced",
                catalog_id=outcome.catalog_id,
                outcome=outcome.outcome,
                source_id=outcome.source_id,
                version_id=outcome.version_id,
            )
            outcomes.append(outcome)
        return outcomes

    def _desired(self, entry: dict[str, Any]) -> dict[str, Any]:
        fields = model.registry_fields(entry)
        return {
            **fields,
            "license": model.license_of(entry),
            "files": [
                {k: v for k, v in f.items() if k in FILE_KEYS and v} for f in model.files(entry)
            ],
            "settings": {"languages": [fields["language"]]},
        }

    def _sync_entry(self, entry: dict[str, Any], *, dry_run: bool) -> Outcome:
        cid = entry["id"]
        status = entry["review"]["status"]
        source_id = self.linked(cid)
        if status in ("draft", "rejected"):
            return Outcome(cid, status, source_id=source_id)
        if status == "withdrawn":
            if source_id and self.registry.get(source_id).status == "active":
                if not dry_run:
                    self.registry.unpublish(self.actor, source_id, reason="catalog_withdrawn")
                    events.emit("library.catalog.withdrawn", catalog_id=cid, source_id=source_id)
                return Outcome(cid, "withdrawn", source_id=source_id)
            return Outcome(cid, "withdrawn_already", source_id=source_id)
        if dry_run:
            return Outcome(
                cid, "dry_run", "новая" if source_id is None else "", source_id=source_id
            )

        desired = self._desired(entry)
        try:
            if source_id is None:
                source_id = self.registry.register(
                    self.actor,
                    confirm_duplicate=True,
                    scope="public",
                    **{k: v for k, v in desired.items() if v is not None},
                )
                self._link(cid, source_id)
            else:
                self._update(source_id, desired)
        except RegistryError as exc:
            return Outcome(cid, "failed", str(exc), source_id=source_id)
        blocked = self.registry.blocked_reason(source_id)
        if blocked:
            return Outcome(cid, "blocked", blocked, source_id=source_id)
        source = self.registry.get(source_id)
        if source.status == "unpublished" and source.published_version:
            # запись снова одобрена после отзыва: возвращаем прежнюю публикацию
            self.registry.republish(self.actor, source_id)
        return self.process(entry, source_id)

    def _update(self, source_id: str, desired: dict[str, Any]) -> None:
        source = self.registry.get(source_id)
        changes = {
            key: desired.get(key)
            for key in ("title", "authors", "language", "year", *OPTIONAL)
            if getattr(source, key) != desired.get(key)
        }
        if changes:
            self.registry.update_metadata(self.actor, source_id, **changes)
        if desired["license"] is not None and source.license != desired["license"]:
            self.registry.change_license(self.actor, source_id, desired["license"])
        if [dict(f) for f in source.files] != desired["files"]:
            self.registry.replace_files(self.actor, source_id, desired["files"])
        if source.settings.get("languages") != desired["settings"]["languages"]:
            self.registry.update_settings(self.actor, source_id, **desired["settings"])

    def process(self, entry: dict[str, Any], source_id: str) -> Outcome:
        cid = entry["id"]
        try:
            version_id = self.pipeline.start(self.actor, source_id)
        except (StepFailed, RegistryError, ProcessingBusy, OSError) as exc:
            return Outcome(cid, "failed", str(exc), source_id=source_id)
        if version_id is None:
            return Outcome(cid, "unchanged", source_id=source_id)
        return Policy(self.registry, self.actor).apply(entry, source_id, version_id)

    # --- решение по качеству распознавания ----------------------------------------------

    def latest_version(self, entry_id: str) -> dict[str, Any] | None:
        source_id = self.linked(entry_id)
        versions = self.registry.versions(source_id) if source_id else []
        return max(versions, key=lambda v: v["number"]) if versions else None

    def decide(self, entry_id: str, decision: str, reason: str | None = None) -> Outcome:
        """Решение оператора по выборке страниц; при «принять» обработка идёт дальше."""
        entry = self.catalog.find(entry_id)
        version = self.latest_version(entry_id)
        if entry is None or version is None:
            raise RegistryError(f"у записи {entry_id} нет версии")
        self.pipeline.decide_quality(self.actor, version["id"], decision, reason)
        return Policy(self.registry, self.actor).apply(entry, version["source_id"], version["id"])

    # --- плановая проверка ------------------------------------------------------------

    def check_updates(self) -> list[Outcome]:
        """Проверяет одобренные и связанные записи: файлы по ссылкам, затем правило публикации."""
        outcomes = []
        for entry in self.catalog.entries:
            source_id = self.linked(entry["id"])
            if entry["review"]["status"] != "approved" or source_id is None:
                continue
            if self.registry.get(source_id).status != "active":
                continue
            outcomes.append(self.process(entry, source_id))
        return outcomes

    # --- состояние --------------------------------------------------------------------

    def status(self) -> list[dict[str, Any]]:
        rows = []
        for entry in self.catalog.entries:
            source_id = self.linked(entry["id"])
            row: dict[str, Any] = {
                "id": entry["id"],
                "review": entry["review"]["status"],
                "source_id": source_id,
                "published": None,
                "latest_state": None,
                "error": None,
                "fetch_failures": 0,
            }
            if source_id:
                source = self.registry.get(source_id)
                versions = self.registry.versions(source_id)
                latest = max(versions, key=lambda v: v["number"]) if versions else None
                row["published"] = source.published_version
                row["latest_state"] = latest["state"] if latest else None
                row["error"] = (latest or {}).get("error")
                with self.registry.engine.begin() as conn:
                    for f in model.files(entry):
                        state = conn.execute(
                            select(t.fetch_state.c.failures).where(t.fetch_state.c.url == f["url"])
                        ).first()
                        row["fetch_failures"] = max(row["fetch_failures"], state[0] if state else 0)
            rows.append(row)
        return rows


@dataclass
class Policy:
    """Когда новая версия публикуется сама.

    - Правило записи «auto» или тот же текст, что у опубликованной; проверки пройдены,
      решение по качеству не нужно; удалено не больше 2% абзацев опубликованной версии
      (первая версия — без этого условия). Тот же текст ещё не значит та же разбивка:
      новая версия конвейера может иначе делить абзацы, поэтому порог действует всегда.
    Остальное ждёт оператора и даёт предупреждение.
    """

    registry: Registry
    actor: str = "catalog"

    def apply(self, entry: dict[str, Any], source_id: str, version_id: str) -> Outcome:
        cid = entry["id"]
        version = self.registry.version(version_id)
        state = version["state"]
        base = {"source_id": source_id, "version_id": version_id, "state": state}
        if version["error"]:
            error = version["error"]
            detail = error.get("message", str(error)) if isinstance(error, dict) else str(error)
            return Outcome(cid, "failed", detail, **base)
        if state == "awaiting_quality":
            self._warn(cid, source_id, version_id, "нужно решение по качеству распознавания")
            return Outcome(cid, "waiting_quality", **base)
        if state == "deferred":
            return Outcome(cid, "deferred", version.get("deferred_reason") or "", **base)
        if state != "checked":
            return Outcome(cid, "failed", f"неожиданное состояние {state}", **base)
        source = self.registry.get(source_id)
        published = (
            self.registry.version(source.published_version) if source.published_version else None
        )
        same_text = bool(published and published["text_digest"] == version["text_digest"])
        if not same_text and entry.get("publish") != "auto":
            self._warn(cid, source_id, version_id, "правило записи: публикует оператор")
            return Outcome(cid, "waiting_operator", **base)
        if published:
            total = len(list(self.registry.load_document(published["id"]).blocks()))
            removed = (version["summary"] or {}).get("counts", {}).get("removed", 0)
            if total and removed / total > AUTO_REMOVED_SHARE:
                reason = f"удалено {removed} из {total} абзацев"
                self._warn(cid, source_id, version_id, reason)
                return Outcome(cid, "waiting_operator", reason, **base)
        return self._publish(
            cid, version_id, "published_same_text" if same_text else "published", base
        )

    def _publish(self, cid: str, version_id: str, code: str, base: dict[str, Any]) -> Outcome:
        try:
            self.registry.publish(self.actor, version_id)
        except RegistryError as exc:
            return Outcome(cid, "failed", f"публикация отклонена: {exc}", **base)
        return Outcome(cid, code, **{**base, "state": "published"})

    def _warn(self, cid: str, source_id: str, version_id: str, reason: str) -> None:
        events.emit(
            "library.catalog.needs_decision",
            catalog_id=cid,
            source_id=source_id,
            version_id=version_id,
            reason=reason,
        )
