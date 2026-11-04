"""Сопоставление абзацев новой версии с опубликованной.

Идентификатор абзаца случайный и переходит к новой версии, только если содержание то же:
1. совпадение нормализованного текста;
2. сходство с соседями в окне (исправленные опечатки распознавания);
3. слияние: новый абзац покрывает несколько прежних подряд — берёт идентификатор первого,
   остальные перенаправляются на него;
4. разбиение: несколько новых подряд покрывают один прежний — первый берёт его идентификатор,
   остальные новые.
Оставшиеся прежние абзацы удалены, оставшиеся новые добавлены.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher

from philograph.library.lang import normalize_text


@dataclass(frozen=True)
class Item:
    id: str
    text: str


@dataclass
class MatchResult:
    ids: dict[str, str] = field(default_factory=dict)  # временный идентификатор → постоянный
    added: list[str] = field(default_factory=list)  # постоянные идентификаторы новых
    changed: list[str] = field(default_factory=list)  # идентификатор сохранён, текст другой
    unchanged: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)  # прежние без пары
    redirected: dict[str, str] = field(default_factory=dict)  # прежний → новый при слиянии

    def summary(self) -> dict[str, int]:
        return {
            "added": len(self.added),
            "changed": len(self.changed),
            "removed": len(self.removed),
            "redirected": len(self.redirected),
            "unchanged": len(self.unchanged),
        }


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


def _covered(part: str, whole: str) -> float:
    """Какая доля слов ``part`` встречается в ``whole`` подряд идущими кусками."""
    pw, ww = part.split(), whole.split()
    if not pw:
        return 0.0
    matcher = SequenceMatcher(None, pw, ww, autojunk=False)
    return sum(block.size for block in matcher.get_matching_blocks()) / len(pw)


def match(
    old: list[Item], new: list[Item], new_id, *, threshold: float = 0.85, window: int = 12
) -> MatchResult:
    result = MatchResult()
    old_norm = [normalize_text(o.text) for o in old]
    new_norm = [normalize_text(n.text) for n in new]
    old_taken: dict[int, int] = {}  # индекс прежнего → индекс нового
    new_taken: dict[int, int] = {}

    # 1. Точные совпадения по порядку.
    by_text: dict[str, list[int]] = {}
    for i, text in enumerate(old_norm):
        by_text.setdefault(text, []).append(i)
    for j, text in enumerate(new_norm):
        queue = by_text.get(text)
        while queue and queue[0] in old_taken:
            queue.pop(0)
        if queue:
            i = queue.pop(0)
            old_taken[i], new_taken[j] = j, i

    def expected(j: int) -> int:
        """Где ожидать прежний абзац для нового ``j``: рядом с ближайшим сопоставленным."""
        before = [k for k in new_taken if k < j]
        if not before:
            return j
        k = max(before)
        return new_taken[k] + (j - k)

    # 2. Сходство в окне.
    for j in range(len(new)):
        if j in new_taken:
            continue
        centre = expected(j)
        best, best_score = None, threshold
        for i in range(max(0, centre - window), min(len(old), centre + window + 1)):
            if i in old_taken:
                continue
            score = _similarity(old_norm[i], new_norm[j])
            if score >= best_score:
                best, best_score = i, score
        if best is not None:
            old_taken[best], new_taken[j] = j, best

    # 3. Слияние: новый абзац покрывает несколько прежних подряд.
    for j in range(len(new)):
        if j in new_taken:
            continue
        centre = expected(j)
        run: list[int] = []
        for i in range(max(0, centre - window), min(len(old), centre + window + 1)):
            if i in old_taken or not old_norm[i]:
                continue
            if _covered(old_norm[i], new_norm[j]) >= 0.9:
                run.append(i)
        if len(run) >= 1 and sum(len(old_norm[i].split()) for i in run) >= 0.9 * len(
            new_norm[j].split()
        ):
            first = run[0]
            old_taken[first], new_taken[j] = j, first
            for i in run[1:]:
                old_taken[i] = j
                result.redirected[old[i].id] = old[first].id

    # 4. Разбиение: несколько новых подряд покрывают один прежний.
    for i in range(len(old)):
        if i in old_taken:
            continue
        parts = [
            j
            for j in range(max(0, i - window), min(len(new), i + window + 1))
            if j not in new_taken and new_norm[j] and _covered(new_norm[j], old_norm[i]) >= 0.9
        ]
        if parts and sum(len(new_norm[j].split()) for j in parts) >= 0.9 * len(old_norm[i].split()):
            old_taken[i], new_taken[parts[0]] = parts[0], i

    for j, item in enumerate(new):
        if j in new_taken:
            i = new_taken[j]
            stable = old[i].id
            result.ids[item.id] = stable
            (
                result.unchanged
                if old_norm[i] == new_norm[j] and old[i].text == item.text
                else result.changed
            ).append(stable)
        else:
            stable = new_id("p")
            result.ids[item.id] = stable
            result.added.append(stable)
    redirected_targets = set(result.redirected)
    result.removed = [
        o.id for i, o in enumerate(old) if i not in old_taken and o.id not in redirected_targets
    ]
    return result
