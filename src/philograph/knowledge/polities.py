"""Слой политических образований на год (geo-timeline, add-historical-polities).

Артефакт — SQLite, его пишет шаг сборки (``polities_build``): строки образований
Cliopatria с годами ``from_year``–``to_year`` (включительно), названием и упрощённой
геометрией (готовый JSON-текст). Модуль только читает артефакт: без модели, без сети и без
тяжёлых зависимостей (``shapely``/``ijson`` здесь не импортируются).

Правила (одно место на весь сервис; ``polities_build measure`` вызывает эти же функции):

- образование активно на T, если у него есть строка с ``from_year ≤ T ≤ to_year``;
- ``valid_from``–``valid_to`` — наибольший интервал вокруг T, на котором набор активных
  строк тот же: границы — ближайшие начала и концы строк (в пределах ±``YEAR_LIMIT``);
- несколько активных строк одного ``id`` — одно образование: многоугольники объединены,
  ``from`` = наибольший ``from_year``, ``to`` = наименьший ``to_year``, название и QID —
  строки с наибольшим ``from_year`` (при равенстве — с меньшим номером строки);
- порядок — по убыванию площади (сумма площадей строк), при равенстве — по ``id``.

Кэш — LRU по интервалу постоянного набора, с пределом по числу интервалов и по сумме
байт; ключ включает подпись файла артефакта (устройство, inode, размер, время), так что
атомарная замена артефакта сбрасывает кэш без перезапуска.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from philograph.platform import events

FORMAT_VERSION = 1
YEAR_LIMIT = 9999
DEFAULT_PATH = "data/cliopatria/polities.sqlite"
DEFAULT_CACHE = 64
DEFAULT_CACHE_BYTES = 64 * 1024 * 1024
YEAR = re.compile(r"^-?\d{1,4}$")

events.define(
    "knowledge.polities.served",
    "info",
    "Отдан слой политических образований на год",
    required=("year", "polities", "untranslated", "bytes", "valid_from", "valid_to", "cached"),
)
events.define(
    "knowledge.polities.unavailable",
    "warning",
    "Слой политических образований недоступен: нет артефакта или формат не тот",
    required=("reason",),
)
events.define(
    "knowledge.polities.rejected",
    "info",
    "Отказ: неверный год слоя образований или контрольная сумма датасета",
    required=("code",),
)

SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE polity_rows (
    row INTEGER PRIMARY KEY,
    id TEXT NOT NULL,
    from_year INTEGER NOT NULL,
    to_year INTEGER NOT NULL,
    name TEXT NOT NULL,
    name_status TEXT NOT NULL,
    name_source TEXT NOT NULL,
    original TEXT NOT NULL,
    wikidata TEXT,
    area REAL NOT NULL,
    geometry TEXT NOT NULL
);
CREATE INDEX polity_rows_from ON polity_rows (from_year, to_year);
CREATE INDEX polity_rows_to ON polity_rows (to_year);
"""


class PolitiesUnavailable(Exception):
    """Артефакта нет (``missing``) или его формат не поддерживается (``format``)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class BadYear(ValueError):
    """Год не целое число в пределах ±``YEAR_LIMIT``."""


def parse_year(raw: str | None) -> int:
    if raw is None or not YEAR.fullmatch(raw.strip()):
        raise BadYear(raw)
    year = int(raw.strip())
    if abs(year) > YEAR_LIMIT:
        raise BadYear(raw)
    return year


def reject_year() -> None:
    events.emit("knowledge.polities.rejected", code="bad_year")


@dataclass(frozen=True)
class Slice:
    """Набор образований интервала: готовое тело массива ``polities`` и счётчики."""

    valid_from: int
    valid_to: int
    body: bytes
    polities: int
    untranslated: int
    ru: int


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _merge(geometries: list[str]) -> str:
    if len(geometries) == 1:
        return geometries[0]
    polygons: list[Any] = []
    for text in geometries:
        g = json.loads(text)
        polygons.extend([g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"])
    return _dumps({"type": "MultiPolygon", "coordinates": polygons})


def open_artifact(path: Path) -> sqlite3.Connection:
    """Соединение только для чтения; проверка версии формата."""
    if not path.is_file():
        raise PolitiesUnavailable("missing")
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
        row = conn.execute("SELECT value FROM meta WHERE key = 'format_version'").fetchone()
    except sqlite3.DatabaseError as exc:
        raise PolitiesUnavailable("format") from exc
    if row is None or row[0] != str(FORMAT_VERSION):
        conn.close()
        raise PolitiesUnavailable("format")
    return conn


def read_meta(conn: sqlite3.Connection) -> dict[str, str]:
    return dict(conn.execute("SELECT key, value FROM meta").fetchall())


def interval(conn: sqlite3.Connection, year: int) -> tuple[int, int]:
    """Наибольший интервал вокруг ``year`` с тем же набором активных строк."""
    q = conn.execute
    active_from, active_to = q(
        "SELECT MAX(from_year), MIN(to_year) FROM polity_rows"
        " WHERE from_year <= ? AND to_year >= ?",
        (year, year),
    ).fetchone()
    (ended,) = q("SELECT MAX(to_year) FROM polity_rows WHERE to_year < ?", (year,)).fetchone()
    (starts,) = q("SELECT MIN(from_year) FROM polity_rows WHERE from_year > ?", (year,)).fetchone()
    lo = [-YEAR_LIMIT] + [
        v for v in (active_from, None if ended is None else ended + 1) if v is not None
    ]
    hi = [YEAR_LIMIT] + [
        v for v in (active_to, None if starts is None else starts - 1) if v is not None
    ]
    return max(lo), min(hi)


def build_slice(conn: sqlite3.Connection, year: int) -> Slice:
    """Образования, активные на ``year``, и интервал постоянного набора."""
    valid_from, valid_to = interval(conn, year)
    rows = conn.execute(
        "SELECT row, id, from_year, to_year, name, name_status, name_source, original, wikidata,"
        " area, geometry FROM polity_rows WHERE from_year <= ? AND to_year >= ? ORDER BY row",
        (year, year),
    ).fetchall()
    groups: dict[str, list[tuple]] = {}
    for r in rows:
        groups.setdefault(r[1], []).append(r)
    items = []
    for pid, group in groups.items():
        lead = max(group, key=lambda r: (r[2], -r[0]))  # наибольший from_year, меньшая строка
        items.append(
            (
                -sum(r[9] for r in group),
                pid,
                {
                    "id": pid,
                    "name": lead[4],
                    "name_status": lead[5],
                    "name_source": lead[6],
                    "original": lead[7],
                    "wikidata": lead[8],
                    "from": max(r[2] for r in group),
                    "to": min(r[3] for r in group),
                },
                _merge([r[10] for r in group]),
            )
        )
    items.sort(key=lambda x: (x[0], x[1]))
    parts = [_dumps(meta)[:-1] + ',"geometry":' + geom + "}" for _, _, meta, geom in items]
    untranslated = sum(1 for _, _, meta, _ in items if meta["name_status"] == "original")
    return Slice(
        valid_from,
        valid_to,
        ("[" + ",".join(parts) + "]").encode(),
        len(items),
        untranslated,
        len(items) - untranslated,
    )


def response_body(year: int, part: Slice, source: str, cached: bool) -> bytes:
    """Тело ответа ``/map/polities``: поля года вокруг готового массива образований."""
    head = (
        f'{{"year":{year},"valid_from":{part.valid_from},"valid_to":{part.valid_to},'
        f'"cached":{"true" if cached else "false"},"polities":'
    ).encode()
    return head + part.body + b',"source":' + source.encode() + b"}"


class PolityLayer:
    def __init__(
        self,
        path: Path | str | None,
        *,
        cache_size: int = DEFAULT_CACHE,
        cache_bytes: int = DEFAULT_CACHE_BYTES,
    ) -> None:
        self.path = Path(path) if path is not None else None
        self.cache_size = cache_size
        self.cache_bytes = cache_bytes
        self._cache: OrderedDict[tuple, Slice] = OrderedDict()
        self._source: tuple[tuple, str] | None = None
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls, env: dict[str, str]) -> PolityLayer:
        return cls(
            env.get("PHILOGRAPH_POLITIES_DB", DEFAULT_PATH),
            cache_size=int(env.get("PHILOGRAPH_POLITIES_CACHE", str(DEFAULT_CACHE))),
            cache_bytes=int(env.get("PHILOGRAPH_POLITIES_CACHE_BYTES", str(DEFAULT_CACHE_BYTES))),
        )

    def cached_intervals(self) -> int:
        with self._lock:
            return len(self._cache)

    def cached_bytes(self) -> int:
        with self._lock:
            return sum(len(s.body) for s in self._cache.values())

    def _signature(self) -> tuple:
        if self.path is None:
            raise PolitiesUnavailable("missing")
        try:
            st = os.stat(self.path)
        except OSError as exc:
            raise PolitiesUnavailable("missing") from exc
        return (str(self.path), st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)

    def _lookup(self, sig: tuple, year: int) -> tuple[Slice, str] | None:
        with self._lock:
            if self._source is None or self._source[0] != sig:
                return None
            for key, part in self._cache.items():
                if key[0] == sig and part.valid_from <= year <= part.valid_to:
                    self._cache.move_to_end(key)
                    return part, self._source[1]
        return None

    def _store(self, sig: tuple, part: Slice, source: str) -> None:
        with self._lock:
            if self._source is None or self._source[0] != sig:
                self._cache.clear()
                self._source = (sig, source)
            if len(part.body) > self.cache_bytes:
                return  # слой больше предела — не кэшируется
            self._cache[(sig, part.valid_from, part.valid_to)] = part
            total = sum(len(s.body) for s in self._cache.values())
            while len(self._cache) > self.cache_size or total > self.cache_bytes:
                _, old = self._cache.popitem(last=False)
                total -= len(old.body)

    def compute(self, year: int) -> tuple[Slice, str]:
        """Набор на год прямо из артефакта, без кэша (замер ``measure`` и промах кэша)."""
        conn = open_artifact(self.path) if self.path is not None else None
        if conn is None:
            raise PolitiesUnavailable("missing")
        try:
            source = read_meta(conn).get("source", "{}")
            return build_slice(conn, year), source
        finally:
            conn.close()

    def serve(self, year: int) -> bytes:
        """Тело ответа на год; события ``served`` или ``unavailable``."""
        try:
            sig = self._signature()
            hit = self._lookup(sig, year)
            if hit is None:
                part, source = self.compute(year)
                self._store(sig, part, source)
            else:
                part, source = hit
        except PolitiesUnavailable as exc:
            events.emit("knowledge.polities.unavailable", reason=exc.reason)
            raise
        body = response_body(year, part, source, cached=hit is not None)
        events.emit(
            "knowledge.polities.served",
            year=year,
            polities=part.polities,
            untranslated=part.untranslated,
            bytes=len(body),
            valid_from=part.valid_from,
            valid_to=part.valid_to,
            cached=hit is not None,
        )
        return body
