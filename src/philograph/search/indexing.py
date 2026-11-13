"""Индексация абзацев по событиям конвейера источника.

Индексы — производные данные: их всегда можно пересобрать из библиотеки. Поэтому индексация
только догоняет библиотеку: по событию, по сверке или при смене модели эмбеддингов.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy import Engine, and_, delete, func, or_, select, update

from philograph.platform import events
from philograph.search import schema as t
from philograph.search.text import terms
from philograph.search.vectors import DimensionMismatch, VectorStore

events.define(
    "search.index.rebuilt",
    "info",
    "Индексы восстановлены из библиотеки",
    required=("versions", "indexed", "embedded", "removed"),
)
events.define(
    "search.index.event",
    "info",
    "Индексация обработала событие библиотеки",
    required=("event_id", "kind", "source_id", "indexed", "embedded", "removed"),
)
events.define("search.index.duplicate", "debug", "Событие уже обработано", required=("event_id",))
events.define(
    "search.index.external_forbidden",
    "info",
    "Внешняя обработка запрещена: только полнотекстовый индекс",
    required=("source_id",),
)
events.define(
    "search.index.reconciled",
    "info",
    "Индексы сверены с библиотекой",
    required=("missing", "extra"),
)
events.define(
    "search.index.estimate",
    "info",
    "Оценка стоимости переиндексации",
    required=("paragraphs", "tokens", "estimate_usd"),
)
events.define(
    "search.index.switched",
    "info",
    "Поиск переключён на новый смысловой индекс",
    required=("collection", "model"),
)
events.define(
    "search.index.dimension_mismatch",
    "error",
    "Размерность эмбеддингов не совпадает с коллекцией",
    required=("collection", "collection_dimension", "embedder_dimension"),
)


class LibraryPort(Protocol):
    def version_paragraphs(self, version_id: str) -> dict[str, Any]: ...

    def published(self) -> list[dict[str, str]]: ...


class EmbedPort(Protocol):
    model: str
    dimension: int

    def embed(self, texts: list[str], *, budget: str) -> list[list[float]]: ...


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def regions_column(regions: list[str] | tuple[str, ...] | frozenset[str] | None) -> str:
    """Регионы показа в формате столбца ``docs.regions``.

    ``*`` — везде; ``,RU,BY,`` — перечень (подстрока ``LIKE '%,RU,%'`` безопасна, коды —
    двухбуквенные латинские); ``','`` — пустое пересечение («нигде»): не совпадает ни с
    ``regions = '*'``, ни с ``LIKE '%,RU,%'``.
    """
    if regions is None:
        return "*"
    codes = sorted(regions)
    if not codes:
        return ","
    return "," + ",".join(codes) + ","


def regions_payload(
    regions: list[str] | tuple[str, ...] | frozenset[str] | None,
) -> list[str]:
    """Регионы показа для полезной нагрузки Qdrant: ``["*"]`` — везде, иначе список кодов.

    Пустое пересечение — пустой список: ``MatchAny`` по такому полю не совпадёт ни с одним
    регионом, источник закрыт для всех.
    """
    if regions is None:
        return ["*"]
    return sorted(regions)


def chunks(text: str, size: int, overlap: int) -> list[str]:
    """Перекрывающиеся фрагменты длинного абзаца; результат поиска всё равно — абзац."""
    if len(text) <= size:
        return [text]
    parts, start = [], 0
    while start < len(text):
        parts.append(text[start : start + size])
        if start + size >= len(text):
            break
        start += size - overlap
    return parts


@dataclass
class IndexSettings:
    chunk_chars: int = 2000
    chunk_overlap: int = 200
    price_per_million_tokens: float = 0.02
    batch_size: int = 64  # абзацев на вызов: после каждой пачки продвижение сохранено


class Indexer:
    def __init__(
        self,
        engine: Engine,
        library: LibraryPort,
        embedder: EmbedPort,
        vectors: VectorStore,
        settings: IndexSettings | None = None,
    ) -> None:
        self.engine = engine
        self.library = library
        self.embedder = embedder
        self.vectors = vectors
        self.settings = settings or IndexSettings()

    # --- состояние ---

    def _state(self, key: str) -> str | None:
        with self.engine.begin() as conn:
            return conn.scalar(select(t.state.c.value).where(t.state.c.key == key))

    def _set_state(self, key: str, value: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(delete(t.state).where(t.state.c.key == key))
            conn.execute(t.state.insert().values(key=key, value=value))

    def collection_for(self, model: str) -> str:
        return "paragraphs__" + "".join(c if c.isalnum() else "_" for c in model)

    @property
    def active_collection(self) -> str:
        collection = self._state("active_collection")
        if collection is None:
            collection = self.collection_for(self.embedder.model)
            self.vectors.ensure(collection, self.embedder.dimension)
            self._set_state("active_collection", collection)
            self._set_state("active_model", self.embedder.model)
        return collection

    # --- события ---

    def handle(self, kind: str, payload: dict[str, Any]) -> None:
        event_id = payload["event_id"]
        with self.engine.begin() as conn:
            if conn.scalar(
                select(t.processed.c.event_id).where(t.processed.c.event_id == event_id)
            ):
                events.emit("search.index.duplicate", event_id=event_id)
                return
        source_id = payload["source_id"]
        counts = {"indexed": 0, "embedded": 0, "removed": 0}
        if kind == "source.published":
            counts = self.index_version(payload["version_id"])
        elif kind == "source.unpublished":
            self._set_source_active(source_id, False)
        elif kind == "source.deleted":
            counts["removed"] = self._drop_source(source_id)
        elif kind == "source.access_changed":
            # Регионы показа сменились без повторной публикации: эмбеддинги не пересчитываются.
            self._set_source_regions(source_id, payload)
        with self.engine.begin() as conn:
            conn.execute(t.processed.insert().values(event_id=event_id))
        events.emit(
            "search.index.event", event_id=event_id, kind=kind, source_id=source_id, **counts
        )

    def index_version(
        self, version_id: str, *, embedder: EmbedPort | None = None, collection: str | None = None
    ) -> dict[str, int]:
        embedder = embedder or self.embedder
        collection = collection or self.active_collection
        data = self.library.version_paragraphs(version_id)
        source_id = data["source_id"]
        # Вторая проверка разрешения: событие могло устареть, библиотека знает текущее.
        external = bool(data["permissions"].get("external_processing"))
        if not external:
            events.emit("search.index.external_forbidden", source_id=source_id)
        wanted = [p for p in data["paragraphs"] if p["searchable"]]
        wanted_ids = {p["id"] for p in wanted}
        with self.engine.begin() as conn:
            existing = {
                r.paragraph_id: r
                for r in conn.execute(select(t.docs).where(t.docs.c.source_id == source_id))
            }
        stale = [pid for pid in existing if pid not in wanted_ids]
        self._remove(stale, collection)
        indexed = embedded = 0
        to_embed: list[dict[str, Any]] = []
        for p in wanted:
            digest = text_hash(p["text"])
            old = existing.get(p["id"])
            if old is None or old.text_hash != digest:
                self._write_doc(p, data, digest)
                indexed += 1
            else:
                with self.engine.begin() as conn:
                    conn.execute(
                        update(t.docs)
                        .where(t.docs.c.paragraph_id == p["id"])
                        .values(
                            active=True,
                            version_id=version_id,
                            ord=p["ord"],
                            chapter_id=p["chapter_id"],
                            section_title=p["section_title"],
                            source_title=data.get("source_title"),
                            quoting=bool(data["permissions"].get("quoting", True)),
                            regions=regions_column(data.get("regions")),
                            external=bool(data.get("external_processing", True)),
                        )
                    )
            if external and (old is None or old.text_hash != digest or not old.embedded):
                to_embed.append({**p, "hash": digest})
        embedded = self._embed(to_embed, data, embedder, collection)
        if not external:
            self.vectors.delete(collection, list(wanted_ids))
            with self.engine.begin() as conn:
                conn.execute(
                    update(t.docs).where(t.docs.c.source_id == source_id).values(embedded=False)
                )
        else:
            self.vectors.set_active(collection, list(wanted_ids), True)
        return {"indexed": indexed, "embedded": embedded, "removed": len(stale)}

    def _write_doc(self, p: dict[str, Any], data: dict[str, Any], digest: str) -> None:
        counted = Counter(terms(p["text"]))
        with self.engine.begin() as conn:
            conn.execute(delete(t.postings).where(t.postings.c.paragraph_id == p["id"]))
            conn.execute(delete(t.docs).where(t.docs.c.paragraph_id == p["id"]))
            conn.execute(
                t.docs.insert().values(
                    paragraph_id=p["id"],
                    source_id=data["source_id"],
                    version_id=data["version_id"],
                    chapter_id=p["chapter_id"],
                    section_id=p["section_id"],
                    section_title=p["section_title"],
                    source_title=data.get("source_title"),
                    ord=p["ord"],
                    lang=p["lang"],
                    scope=data["scope"],
                    text=p["text"],
                    text_hash=digest,
                    length=sum(counted.values()),
                    embedded=False,
                    active=True,
                    quoting=bool(data["permissions"].get("quoting", True)),
                    regions=regions_column(data.get("regions")),
                    external=bool(data.get("external_processing", True)),
                )
            )
            if counted:
                conn.execute(
                    t.postings.insert(),
                    [
                        {"term": term[:100], "paragraph_id": p["id"], "tf": tf}
                        for term, tf in counted.items()
                    ],
                )

    def _embed(
        self,
        items: list[dict[str, Any]],
        data: dict[str, Any],
        embedder: EmbedPort,
        collection: str,
    ) -> int:
        """Считает эмбеддинги только для нового текста; тот же текст той же моделью — готов."""
        if not items:
            return 0
        # Размерность проверяется до любого вызова эмбеддера и до записи: иначе абзац был бы
        # помечен готовым с векторами другой формы, а сбой повторился бы бесконечно.
        existing = self.vectors.collection_dimension(collection)
        if existing is not None and existing != embedder.dimension:
            events.emit(
                "search.index.dimension_mismatch",
                collection=collection,
                collection_dimension=existing,
                embedder_dimension=embedder.dimension,
                error_kind="dimension_mismatch",
            )
            raise DimensionMismatch(collection, existing, embedder.dimension)
        fresh: list[tuple[dict[str, Any], list[str]]] = []
        computed = 0
        for item in items:
            with self.engine.begin() as conn:
                done = conn.scalar(
                    select(t.vectors_done.c.chunks).where(
                        and_(
                            t.vectors_done.c.text_hash == item["hash"],
                            t.vectors_done.c.model == embedder.model,
                            or_(
                                t.vectors_done.c.dimension == embedder.dimension,
                                t.vectors_done.c.dimension.is_(None),
                            ),
                        )
                    )
                )
            reused = self._copy_vectors(item, data, collection) if done else False
            if not reused:
                fresh.append(
                    (
                        item,
                        chunks(
                            item["text"], self.settings.chunk_chars, self.settings.chunk_overlap
                        ),
                    )
                )
        done_ids = [i["id"] for i in items if all(i is not f for f, _ in fresh)]
        self._mark_embedded(done_ids)
        size = self.settings.batch_size
        for start in range(0, len(fresh), size):
            batch = fresh[start : start + size]
            flat = [c for _, parts in batch for c in parts]
            vectors = embedder.embed(flat, budget="filling")
            position = 0
            for item, parts in batch:
                own = vectors[position : position + len(parts)]
                position += len(parts)
                self.vectors.upsert(collection, item["id"], own, self._payload(item, data))
                with self.engine.begin() as conn:
                    conn.execute(
                        delete(t.vectors_done).where(
                            and_(
                                t.vectors_done.c.text_hash == item["hash"],
                                t.vectors_done.c.model == embedder.model,
                            )
                        )
                    )
                    conn.execute(
                        t.vectors_done.insert().values(
                            text_hash=item["hash"],
                            model=embedder.model,
                            dimension=embedder.dimension,
                            chunks=len(parts),
                        )
                    )
            self._mark_embedded([item["id"] for item, _ in batch])
            computed += len(batch)
        return computed

    def _mark_embedded(self, ids: list[str]) -> None:
        if ids:
            with self.engine.begin() as conn:
                conn.execute(
                    update(t.docs).where(t.docs.c.paragraph_id.in_(ids)).values(embedded=True)
                )

    @staticmethod
    def _payload(item: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
        return {
            "source_id": data["source_id"],
            "lang": item["lang"],
            "scope": data["scope"],
            "active": True,
            "text_hash": item["hash"],
            "regions": regions_payload(data.get("regions")),
        }

    def _copy_vectors(self, item: dict[str, Any], data: dict[str, Any], collection: str) -> bool:
        """Берёт готовые векторы того же текста у другой точки коллекции."""
        from qdrant_client.http import models as qm

        points, _ = self.vectors.client.scroll(
            collection,
            limit=64,
            with_vectors=True,
            scroll_filter=qm.Filter(
                must=[qm.FieldCondition(key="text_hash", match=qm.MatchValue(value=item["hash"]))]
            ),
        )
        if not points:
            return False
        if any(p.payload["paragraph_id"] == item["id"] for p in points):
            return True
        donor = points[0].payload["paragraph_id"]
        own = sorted(
            (p for p in points if p.payload["paragraph_id"] == donor),
            key=lambda p: p.payload["chunk"],
        )
        self.vectors.upsert(
            collection, item["id"], [p.vector for p in own], self._payload(item, data)
        )
        return True

    def _remove(self, paragraph_ids: list[str], collection: str) -> None:
        if not paragraph_ids:
            return
        with self.engine.begin() as conn:
            conn.execute(delete(t.postings).where(t.postings.c.paragraph_id.in_(paragraph_ids)))
            conn.execute(delete(t.docs).where(t.docs.c.paragraph_id.in_(paragraph_ids)))
        self.vectors.delete(collection, paragraph_ids)

    def _set_source_active(self, source_id: str, active: bool) -> None:
        with self.engine.begin() as conn:
            ids = list(
                conn.scalars(select(t.docs.c.paragraph_id).where(t.docs.c.source_id == source_id))
            )
            conn.execute(
                update(t.docs).where(t.docs.c.source_id == source_id).values(active=active)
            )
        self.vectors.set_active(self.active_collection, ids, active)

    def _set_source_regions(self, source_id: str, payload: dict[str, Any]) -> None:
        """Обновляет регионы показа источника в таблице и в полезной нагрузке Qdrant.

        Эмбеддинги не пересчитываются: текст абзацев не менялся, меняется только фильтр.
        """
        regions = payload.get("regions")
        with self.engine.begin() as conn:
            ids = list(
                conn.scalars(select(t.docs.c.paragraph_id).where(t.docs.c.source_id == source_id))
            )
            conn.execute(
                update(t.docs)
                .where(t.docs.c.source_id == source_id)
                .values(regions=regions_column(regions))
            )
        self.vectors.set_regions(self.active_collection, ids, regions_payload(regions))

    def _drop_source(self, source_id: str) -> int:
        with self.engine.begin() as conn:
            ids = list(
                conn.scalars(select(t.docs.c.paragraph_id).where(t.docs.c.source_id == source_id))
            )
        self._remove(ids, self.active_collection)
        return len(ids)

    # --- сверка, оценка, смена модели ---

    def reconcile(self) -> dict[str, int]:
        """Догоняет библиотеку, если событие потерялось: недостающее индексирует, лишнее гасит.

        Закрытые по региону источники «лишними» не считаются: ``published()`` отдаёт их без
        фильтра региона. Отдельный шаг сверяет регионы индекса с библиотекой и чинит расхождение
        (например, после миграции, задавшей значения по умолчанию).
        """
        published = self.library.published()
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(t.docs.c.source_id, t.docs.c.version_id, t.docs.c.active)
            ).all()
        indexed_versions = {(r.source_id, r.version_id) for r in rows if r.active}
        missing = [
            p for p in published if (p["source_id"], p["version_id"]) not in indexed_versions
        ]
        for item in missing:
            self.index_version(item["version_id"])
        live = {p["source_id"] for p in published}
        extra = sorted({r.source_id for r in rows if r.active and r.source_id not in live})
        for source_id in extra:
            self._set_source_active(source_id, False)
        # Сверка регионов: источники, которые уже проиндексированы, сравниваются с библиотекой.
        for item in published:
            if (item["source_id"], item["version_id"]) not in indexed_versions:
                continue  # только что проиндексирован: регионы уже актуальные
            data = self.library.version_paragraphs(item["version_id"])
            want = regions_column(data.get("regions"))
            with self.engine.begin() as conn:
                stored = conn.scalar(
                    select(t.docs.c.regions).where(t.docs.c.source_id == item["source_id"]).limit(1)
                )
            if stored is not None and stored != want:
                self._set_source_regions(item["source_id"], data)
        events.emit("search.index.reconciled", missing=len(missing), extra=len(extra))
        return {"missing": len(missing), "extra": len(extra)}

    def reindex(self) -> dict[str, int]:
        """Восстановление производных индексов из библиотеки после потери векторной базы.

        Полнотекстовый индекс пересобирается, отметки «есть вектор» снимаются, смысловой индекс
        строится заново. Поиск по словам работает всё это время: таблица абзацев не пустеет.
        """
        collection = self.active_collection
        self.vectors.ensure(collection, self.embedder.dimension)
        with self.engine.begin() as conn:
            conn.execute(update(t.docs).values(embedded=False, text_hash=""))
        totals = {"versions": 0, "indexed": 0, "embedded": 0, "removed": 0}
        for item in self.library.published():
            counts = self.index_version(item["version_id"], collection=collection)
            totals["versions"] += 1
            for key in ("indexed", "embedded", "removed"):
                totals[key] += counts[key]
        events.emit("search.index.rebuilt", **totals)
        return totals

    def estimate(self) -> dict[str, float]:
        with self.engine.begin() as conn:
            count, chars = conn.execute(
                select(func.count(), func.coalesce(func.sum(func.length(t.docs.c.text)), 0)).where(
                    t.docs.c.active
                )
            ).one()
        tokens = int(chars) // 4
        cost = round(tokens * self.settings.price_per_million_tokens / 1_000_000, 6)
        events.emit("search.index.estimate", paragraphs=count, tokens=tokens, estimate_usd=cost)
        return {"paragraphs": count, "tokens": tokens, "estimate_usd": cost}

    def rebuild_with(self, embedder: EmbedPort) -> str:
        """Строит смысловой индекс новой моделью рядом со старым и переключается в конце."""
        collection = self.collection_for(embedder.model)
        self.vectors.ensure(collection, embedder.dimension)
        for item in self.library.published():
            data = self.library.version_paragraphs(item["version_id"])
            if not data["permissions"].get("external_processing"):
                continue
            wanted = [
                {**p, "hash": text_hash(p["text"])} for p in data["paragraphs"] if p["searchable"]
            ]
            self._embed(wanted, data, embedder, collection)
        self._set_state("active_collection", collection)
        self._set_state("active_model", embedder.model)
        self.embedder = embedder
        events.emit("search.index.switched", collection=collection, model=embedder.model)
        return collection
