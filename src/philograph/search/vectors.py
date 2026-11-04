"""Смысловой индекс в Qdrant: точка — фрагмент абзаца, у точки ссылка на абзац.

Коллекция своя для каждой модели эмбеддингов, поэтому новая модель строит индекс рядом со
старым, а поиск переключается на неё только после полной готовности.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

_NS = uuid.UUID("6f0d4f2c-1d1e-4a8e-9a55-5e1b0b6c7a11")


def point_id(paragraph_id: str, chunk: int) -> str:
    return str(uuid.uuid5(_NS, f"{paragraph_id}:{chunk}"))


@dataclass(frozen=True)
class Hit:
    paragraph_id: str
    score: float


class VectorStore:
    def __init__(self, client: QdrantClient) -> None:
        self.client = client

    def ensure(self, collection: str, dimension: int) -> None:
        if not self.client.collection_exists(collection):
            self.client.create_collection(
                collection,
                vectors_config=qm.VectorParams(size=dimension, distance=qm.Distance.COSINE),
            )

    def exists(self, collection: str) -> bool:
        return self.client.collection_exists(collection)

    def upsert(
        self, collection: str, paragraph_id: str, vectors: list[list[float]], payload: dict
    ) -> None:
        self.delete(collection, [paragraph_id])  # число фрагментов могло измениться
        self.client.upsert(
            collection,
            points=[
                qm.PointStruct(
                    id=point_id(paragraph_id, i),
                    vector=v,
                    payload={**payload, "paragraph_id": paragraph_id, "chunk": i},
                )
                for i, v in enumerate(vectors)
            ],
        )

    def _match(self, paragraph_ids: list[str]) -> qm.Filter:
        return qm.Filter(
            must=[qm.FieldCondition(key="paragraph_id", match=qm.MatchAny(any=paragraph_ids))]
        )

    def set_active(self, collection: str, paragraph_ids: list[str], active: bool) -> None:
        if paragraph_ids and self.exists(collection):
            self.client.set_payload(
                collection, payload={"active": active}, points=self._match(paragraph_ids)
            )

    def delete(self, collection: str, paragraph_ids: list[str]) -> None:
        if paragraph_ids and self.exists(collection):
            self.client.delete(
                collection, points_selector=qm.FilterSelector(filter=self._match(paragraph_ids))
            )

    def search(
        self,
        collection: str,
        vector: list[float],
        *,
        sources: list[str] | None,
        languages: list[str] | None,
        exclude: list[str] | None,
        scopes: list[str],
        limit: int,
    ) -> list[Hit]:
        must = [
            qm.FieldCondition(key="active", match=qm.MatchValue(value=True)),
            qm.FieldCondition(key="scope", match=qm.MatchAny(any=scopes)),
        ]
        if sources:
            must.append(qm.FieldCondition(key="source_id", match=qm.MatchAny(any=sources)))
        if languages:
            must.append(qm.FieldCondition(key="lang", match=qm.MatchAny(any=languages)))
        must_not = (
            [qm.FieldCondition(key="paragraph_id", match=qm.MatchAny(any=exclude))]
            if exclude
            else []
        )
        points = self.client.query_points(
            collection,
            query=vector,
            limit=limit * 3,
            query_filter=qm.Filter(must=must, must_not=must_not),
        ).points
        best: dict[str, float] = {}
        for point in points:  # несколько фрагментов одного абзаца — один результат
            pid = point.payload["paragraph_id"]
            best[pid] = max(best.get(pid, -1.0), point.score)
        ranked = sorted(best.items(), key=lambda kv: -kv[1])[:limit]
        return [Hit(pid, score) for pid, score in ranked]

    def paragraph_ids(self, collection: str) -> set[str]:
        if not self.exists(collection):
            return set()
        ids, offset = set(), None
        while True:
            points, offset = self.client.scroll(
                collection, limit=512, offset=offset, with_payload=["paragraph_id"]
            )
            ids.update(p.payload["paragraph_id"] for p in points)
            if offset is None:
                return ids
