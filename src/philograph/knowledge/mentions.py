"""Упоминания сущностей в тексте библиотеки (ontology.md, раздел 10.3).

Названия и варианты сущностей ищутся в абзацах, заголовках и сносках по леммам, поэтому
«Канту» и «трансцендентального идеализма» находятся в любой форме. Общеупотребительные слова
(«опыт», «знание») ставятся, только если в тексте они употреблены как термин. Неоднозначное
название решается по контексту главы; при неуверенности упоминание не ставится: лучше
пропустить термин, чем отправить читателя не туда.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from itertools import product
from typing import Any

from sqlalchemy import delete, select, update

from philograph.knowledge import schema as t
from philograph.knowledge.statements import Statements
from philograph.platform import events
from philograph.platform.client import ServiceClient
from philograph.platform.morphology import forms

events.define(
    "knowledge.mentions.indexed",
    "info",
    "Упоминания пересчитаны",
    required=("source_id", "targets", "mentions"),
)
events.define(
    "knowledge.mentions.unresolved",
    "info",
    "Неоднозначное упоминание не поставлено",
    required=("surface", "candidates"),
)

Resolver = Callable[[str, list[str], str], str | None]  # название, кандидаты, текст → сущность
SKIP_TYPES = {"source"}


class Mentions:
    def __init__(
        self, statements: Statements, library: ServiceClient, resolver: Resolver | None = None
    ) -> None:
        self.statements = statements
        self.entities = statements.entities
        self.engine = statements.engine
        self.library = library
        self.resolver = resolver

    # --- указатель названий ---

    def _index(self, only: set[str] | None = None) -> tuple[dict[tuple, set[str]], int]:
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(t.names.c.entity_id, t.names.c.text, t.entities.c.type)
                .join(t.entities, t.entities.c.id == t.names.c.entity_id)
                .where(t.entities.c.redirect_to.is_(None))
            ).all()
        index: dict[tuple, set[str]] = defaultdict(set)
        longest = 1
        for entity_id, text, type_ in rows:
            if type_ in SKIP_TYPES or (only is not None and entity_id not in only):
                continue
            words = forms(text)
            for key in product(*(k for k, _, _ in words)) if words else ():
                index[key].add(entity_id)
            longest = max(longest, len(words))
        return index, longest

    def _common(self, entity_id: str) -> bool:
        return bool(self.entities.get(entity_id)["primary"].get("common_word"))

    # --- поиск в тексте ---

    def scan(
        self,
        text: str,
        index: dict[tuple, set[str]],
        longest: int,
        chapter: set[str],
        *,
        keep_ambiguous: bool = False,
    ) -> list[dict[str, Any]]:
        """Упоминания в тексте. ``keep_ambiguous`` — вместо пропуска неоднозначного названия
        вернуть всех кандидатов с пометкой: так ассистент ищет по всем с пониженным весом."""
        words = forms(text)
        found: list[dict[str, Any]] = []
        seen: set[str] = set()
        i = 0
        while i < len(words):
            match = None
            for size in range(min(longest, len(words) - i), 0, -1):
                hits: set[str] = set()
                for key in product(*(w[0] for w in words[i : i + size])):
                    hits |= index.get(key, set())
                if hits:
                    match = (size, hits)
                    break
            if match is None:
                i += 1
                continue
            size, candidates = match
            start, end = words[i][1], words[i + size - 1][2]
            entity, method = self._choose(text[start:end], sorted(candidates), chapter, text)
            if entity is None and keep_ambiguous:
                for candidate in sorted(candidates):
                    if candidate not in seen:
                        found.append(
                            {
                                "entity_id": candidate,
                                "start": start,
                                "end": end,
                                "method": "ambiguous",
                                "surface": text[start:end],
                            }
                        )
                        seen.add(candidate)
            if entity and entity not in seen:
                found.append(
                    {
                        "entity_id": entity,
                        "start": start,
                        "end": end,
                        "method": method,
                        "surface": text[start:end],
                    }
                )
                seen.add(entity)  # кликабельно только первое вхождение в абзаце
            i += size
        # Общеупотребительное слово — термин, только если рядом есть другие термины или
        # слово выделено кавычками.
        strong = [m for m in found if not self._common(m["entity_id"])]
        result = []
        for m in found:
            if self._common(m["entity_id"]):
                quoted = text[max(0, m["start"] - 1) : m["start"]] in '«"' and m["start"] > 0
                if not strong and not quoted:
                    continue
            result.append(m)
        return result

    def _choose(
        self, surface: str, candidates: list[str], chapter: set[str], text: str
    ) -> tuple[str | None, str]:
        if len(candidates) == 1:
            return candidates[0], "name"
        # Контекст главы: кандидат, связанный утверждениями с сущностями этой главы
        # или живший одновременно с людьми этой главы.
        linked = []
        for candidate in candidates:
            related = {s["object"] for s in self.statements.about(candidate, derived=False)} | {
                s["subject"] for s in self.statements.about(candidate, derived=False)
            }
            contemporary = any(
                self.statements.contemporaries(candidate, other)
                for other in chapter
                if other not in candidates
            )
            if related & chapter or contemporary:
                linked.append(candidate)
        if len(linked) == 1:
            return linked[0], "context"
        if self.resolver is not None:
            chosen = self.resolver(surface, candidates, text)
            if chosen in candidates:
                return chosen, "model"
        events.emit("knowledge.mentions.unresolved", surface=surface, candidates=len(candidates))
        return None, "unresolved"

    # --- индексация ---

    def _targets(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        # Абзацы идут в порядке документа: их номер в списке — ``position`` (первый абзац главы
        # с упоминанием для «Где читать»).
        targets = [
            {"id": p["id"], "kind": "paragraph", "text": p["text"], "chapter_id": p["chapter_id"]}
            for p in data["paragraphs"]
        ]
        targets += [
            {"id": h["id"], "kind": "heading", "text": h["text"], "chapter_id": h["chapter_id"]}
            for h in data.get("headings", [])
        ]
        targets += [
            {"id": n["id"], "kind": "footnote", "text": n["text"], "chapter_id": n["chapter_id"]}
            for n in data.get("footnotes", [])
        ]
        return targets

    def index_version(
        self,
        version_id: str,
        *,
        only_targets: set[str] | None = None,
        only_entities: set[str] | None = None,
    ) -> int:
        data = self.library.get(f"internal/versions/{version_id}/paragraphs").json()
        targets = self._targets(data)
        index, longest = self._index()
        # Сначала однозначные упоминания по главам — контекст для неоднозначных.
        unambiguous = {k: v for k, v in index.items() if len(v) == 1}
        chapters: dict[str | None, set[str]] = defaultdict(set)
        for target in targets:
            for m in self.scan(target["text"], unambiguous, longest, set()):
                chapters[target["chapter_id"]].add(m["entity_id"])
        for position, target in enumerate(targets):
            target["position"] = position
        selected = [x for x in targets if only_targets is None or x["id"] in only_targets]
        count = 0
        with self.engine.begin() as conn:
            ids = [x["id"] for x in selected]
            cond = t.mentions.c.target_id.in_(ids)
            if only_entities is not None:
                cond = cond & t.mentions.c.entity_id.in_(list(only_entities))
            conn.execute(delete(t.mentions).where(cond))
        for target in selected:
            found = self.scan(target["text"], index, longest, chapters[target["chapter_id"]])
            if only_entities is not None:
                found = [m for m in found if m["entity_id"] in only_entities]
            if not found:
                continue
            with self.engine.begin() as conn:
                conn.execute(
                    t.mentions.insert(),
                    [
                        {
                            "target_id": target["id"],
                            "target_kind": target["kind"],
                            "source_id": data["source_id"],
                            "chapter_id": target["chapter_id"],
                            "source_title": data.get("source_title"),
                            "chapter_title": data.get("chapters", {}).get(target["chapter_id"]),
                            "entity_id": m["entity_id"],
                            "start": m["start"],
                            "end": m["end"],
                            "method": m["method"],
                            "position": target["position"],
                        }
                        for m in found
                    ],
                )
            count += len(found)
        events.emit(
            "knowledge.mentions.indexed",
            source_id=data["source_id"],
            targets=len(selected),
            mentions=count,
        )
        return count

    def handle_published(self, payload: dict[str, Any]) -> None:
        """Новая версия: пересчёт только для добавленных и изменённых абзацев."""
        with self.engine.begin() as conn:
            if payload.get("removed"):
                conn.execute(
                    delete(t.mentions).where(t.mentions.c.target_id.in_(payload["removed"]))
                )
            for old, new in (payload.get("redirected") or {}).items():
                conn.execute(
                    update(t.mentions).where(t.mentions.c.target_id == old).values(target_id=new)
                )
        if payload.get("previous_version_id") is None:
            self.index_version(payload["version_id"])
        else:
            changed = set(payload.get("added", [])) | set(payload.get("changed", []))
            # Заголовки и сноски версии пересчитываются всегда: их мало.
            data = self.library.get(f"internal/versions/{payload['version_id']}/paragraphs").json()
            changed |= {h["id"] for h in data.get("headings", [])}
            changed |= {n["id"] for n in data.get("footnotes", [])}
            self.index_version(payload["version_id"], only_targets=changed)

    def recompute_entity(self, entity_id: str) -> int:
        """Новая сущность или новое название: пересчёт только для её названий везде."""
        total = 0
        for item in self.library.get("internal/published").json():
            total += self.index_version(item["version_id"], only_entities={entity_id})
        return total

    def find_in_text(self, text: str, chapter: set[str]) -> list[dict[str, Any]]:
        """Сущности в произвольном тексте (вопрос читателя): неоднозначные — все кандидаты."""
        index, longest = self._index()
        return self.scan(text, index, longest, chapter, keep_ambiguous=True)

    def chapter_entities(self, target_ids: list[str]) -> set[str]:
        """Сущности глав, к которым относятся абзацы: контекст для неоднозначных названий."""
        with self.engine.begin() as conn:
            chapters = set(
                conn.scalars(
                    select(t.mentions.c.chapter_id).where(t.mentions.c.target_id.in_(target_ids))
                )
            )
            if not chapters:
                return set()
            return set(
                conn.scalars(
                    select(t.mentions.c.entity_id).where(t.mentions.c.chapter_id.in_(chapters))
                )
            )

    def paragraphs_of(self, entity_ids: list[str], limit: int = 300) -> list[str]:
        """Абзацы, где упомянуты сущности: им ассистент даёт приоритет в поиске."""
        with self.engine.begin() as conn:
            rows = conn.scalars(
                select(t.mentions.c.target_id)
                .where(
                    t.mentions.c.entity_id.in_(entity_ids)
                    & (t.mentions.c.target_kind == "paragraph")
                )
                .limit(limit)
            )
            return list(dict.fromkeys(rows))

    # --- чтение ---

    def for_targets(
        self, target_ids: list[str], closed: frozenset[str] = frozenset()
    ) -> list[dict[str, Any]]:
        with self.engine.begin() as conn:
            rows = (
                conn.execute(select(t.mentions).where(t.mentions.c.target_id.in_(target_ids)))
                .mappings()
                .all()
            )
        rows = [r for r in rows if r["source_id"] not in closed]
        types = self.entities.types([r["entity_id"] for r in rows])
        return [
            {
                "target_id": r["target_id"],
                "entity_id": self.entities.resolve(r["entity_id"]),
                "entity_type": types.get(r["entity_id"]),
                "start": r["start"],
                "end": r["end"],
                "kind": r["target_kind"],
            }
            for r in rows
        ]

    def where_to_read(
        self, entity_id: str, closed: frozenset[str] = frozenset()
    ) -> list[dict[str, Any]]:
        """Главы, где упомянута сущность, с первым абзацем упоминания (N10): «Где читать» ведёт
        к нему, а не к началу главы. Порядок абзацев — ``position`` (строки до миграции 6 без
        него идут после, в порядке вставки); упоминание только в заголовке или сноске абзаца
        не даёт, тогда ``first_paragraph_id`` пуст. Источники, закрытые для региона читателя,
        в списке не показываются."""
        entity_id = self.entities.resolve(entity_id)
        with self.engine.begin() as conn:
            rows = (
                conn.execute(
                    select(t.mentions)
                    .where(t.mentions.c.entity_id == entity_id)
                    .order_by(t.mentions.c.id)
                )
                .mappings()
                .all()
            )
        rows = [r for r in rows if r["source_id"] not in closed]
        grouped: dict[tuple, list[str]] = defaultdict(list)
        titles: dict[tuple, tuple] = {}
        first: dict[tuple, tuple[tuple[int, int], str]] = {}
        for r in rows:
            key = (r["source_id"], r["chapter_id"])
            grouped[key].append(r["target_id"])
            titles[key] = (r["source_title"], r["chapter_title"])
            if r["target_kind"] == "paragraph":
                order = (0, r["position"]) if r["position"] is not None else (1, r["id"])
                if key not in first or order < first[key][0]:
                    first[key] = (order, r["target_id"])
        result = [
            {
                "source_id": s,
                "source_title": titles[(s, c)][0],
                "chapter_id": c,
                "chapter_title": titles[(s, c)][1],
                "count": len(ids),
                "targets": ids,
                "first_paragraph_id": first[(s, c)][1] if (s, c) in first else None,
            }
            for (s, c), ids in grouped.items()
        ]
        return sorted(result, key=lambda x: -x["count"])


def mention_metrics(
    expected: set[tuple[str, int, str]], found: set[tuple[str, int, str]], ambiguous: int = 0
) -> dict[str, float | None]:
    """Точность и полнота упоминаний на размеченных абзацах: (абзац, позиция, сущность)."""
    hit = len(expected & found)
    return {
        "precision": round(hit / len(found), 4) if found else None,
        "recall": round(hit / len(expected), 4) if expected else None,
        "ambiguous_share": round(ambiguous / (len(found) + ambiguous), 4)
        if (found or ambiguous)
        else None,
    }
