"""Бережная загрузка с чужих сайтов и состояние загрузки по ссылке.

``Fetcher`` — HTTP: User-Agent проекта, не чаще запроса в секунду на сайт, robots.txt,
повторы временных ошибок с растущей паузой, предел размера. ``CatalogFetch`` — функция
получения файла для конвейера: условный запрос по ETag и Last-Modified прошлого ответа,
очистка служебных частей сайта, учёт неудач подряд и постоянных перенаправлений.
"""

from __future__ import annotations

import html
import time
import urllib.robotparser
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from sqlalchemy import Engine, select

from philograph import __version__
from philograph.library import schema as t
from philograph.platform import events
from philograph.platform.clock import Clock, SystemClock
from philograph.platform.files import FileStore, fingerprint

USER_AGENT = (
    f"PhiloGraph/{__version__} (+https://github.com/Alberelloo/ai-history-of-philosophy-platform)"
)
TEMPORARY = {429, 500, 502, 503, 504}
PERMANENT_REDIRECTS = {301, 308}
FAILURES_WARNING = 3

events.define(
    "library.catalog.fetch_failed",
    "warning",
    "Файл источника не загружается несколько раз подряд",
    required=("url", "failures", "reason"),
)
events.define(
    "library.catalog.moved",
    "warning",
    "Ссылка источника переехала: обновите её в каталоге",
    required=("url", "final_url"),
)
events.define(
    "library.catalog.not_modified",
    "info",
    "Сайт ответил, что файл не изменился",
    required=("url",),
)


class FetchError(OSError):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class FetchSettings:
    user_agent: str = USER_AGENT
    min_interval: float = 1.0  # секунд между запросами к одному сайту
    retries: int = 3
    backoff: float = 2.0  # пауза перед первым повтором, дальше вдвое больше
    timeout: float = 120.0
    max_bytes: int = 200 * 1024 * 1024
    respect_robots: bool = True


@dataclass
class Response:
    url: str
    status: int
    data: bytes
    final_url: str
    headers: dict[str, str] = field(default_factory=dict)
    permanent_redirect: bool = False

    @property
    def not_modified(self) -> bool:
        return self.status == 304

    def text(self) -> str:
        return self.data.decode("utf-8", errors="replace")

    def json(self) -> Any:
        import json

        return json.loads(self.data)


class Fetcher:
    def __init__(
        self,
        settings: FetchSettings | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings or FetchSettings()
        self.client = httpx.Client(
            transport=transport,
            headers={"User-Agent": self.settings.user_agent},
            timeout=self.settings.timeout,
            follow_redirects=True,
        )
        self.sleep = sleep
        self.monotonic = monotonic
        self._last: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self.requests: list[str] = []  # для тестов и итогов

    def _wait_turn(self, host: str) -> None:
        last = self._last.get(host)
        if last is not None:
            delay = self.settings.min_interval - (self.monotonic() - last)
            if delay > 0:
                self.sleep(delay)
        self._last[host] = self.monotonic()

    def _allowed(self, url: str) -> bool:
        if not self.settings.respect_robots:
            return True
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            parser: urllib.robotparser.RobotFileParser | None = None
            try:
                response = self._send(f"{origin}/robots.txt", {})
                if response.status_code == 200:
                    parser = urllib.robotparser.RobotFileParser()
                    parser.parse(response.text.splitlines())
            except httpx.HTTPError:
                parser = None  # robots.txt недоступен — ограничений нет
            self._robots[origin] = parser
        parser = self._robots[origin]
        return parser is None or parser.can_fetch(self.settings.user_agent, url)

    def _send(self, url: str, headers: dict[str, str]) -> httpx.Response:
        self._wait_turn(urlsplit(url).netloc)
        self.requests.append(url)
        with self.client.stream("GET", url, headers=headers) as response:
            chunks, size = [], 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > self.settings.max_bytes:
                    raise FetchError(f"файл больше {self.settings.max_bytes} байт: {url}")
                chunks.append(chunk)
            response._content = b"".join(chunks)
            return response

    def get(
        self, url: str, headers: dict[str, str] | None = None, *, api: bool = False
    ) -> Response:
        """``api=True`` — документированный API сайта: действуют его правила, а не robots.txt."""
        if not api and not self._allowed(url):
            raise FetchError(f"robots.txt сайта запрещает загрузку: {url}")
        pause = self.settings.backoff
        reason = ""
        status: int | None = None
        for attempt in range(1 + self.settings.retries):
            if attempt:
                self.sleep(pause)
                pause *= 2
            try:
                response = self._send(url, dict(headers or {}))
            except FetchError:
                raise
            except httpx.HTTPError as exc:
                reason = str(exc) or type(exc).__name__
                status = None
                continue
            status = response.status_code
            if status in TEMPORARY:
                reason = f"ответ {status}"
                continue
            if status not in (200, 304):
                raise FetchError(f"ответ {status}: {url}", status)
            return Response(
                url=url,
                status=status,
                data=response.content if status == 200 else b"",
                final_url=str(response.url),
                headers={k.lower(): v for k, v in response.headers.items()},
                permanent_redirect=any(
                    r.status_code in PERMANENT_REDIRECTS for r in response.history
                ),
            )
        raise FetchError(f"не загрузилось после повторов ({reason}): {url}", status)


# --- получение файлов для конвейера ---------------------------------------------------


Cleaner = Callable[[bytes], bytes]


def missing_page(name: str) -> bytes:
    """Страница-заглушка вместо подстраницы, которой нет на сайте: название и отметка."""
    title = html.escape(name)
    return (
        f'<html><head><meta charset="utf-8"/><title>{title}</title></head>'
        f'<body><div data-philograph="missing"></div></body></html>'
    ).encode()


class CatalogFetch:
    """Функция получения файла для ``Pipeline``: ``fetch(spec) -> bytes``."""

    def __init__(
        self,
        engine: Engine,
        fetcher: Fetcher,
        files: FileStore,
        *,
        cleaners: dict[str, Cleaner] | None = None,
        clock: Clock | None = None,
    ) -> None:
        self.engine = engine
        self.fetcher = fetcher
        self.files = files
        self.clock = clock or SystemClock()
        if cleaners is None:
            from philograph.library.catalog.clean import CLEANERS

            cleaners = CLEANERS
        self.cleaners = cleaners

    def state(self, url: str) -> dict[str, Any] | None:
        with self.engine.begin() as conn:
            row = (
                conn.execute(select(t.fetch_state).where(t.fetch_state.c.url == url))
                .mappings()
                .first()
            )
        return dict(row) if row else None

    def _save(self, url: str, **values: Any) -> None:
        values["checked_at"] = self.clock.now()
        with self.engine.begin() as conn:
            exists = conn.execute(
                select(t.fetch_state.c.url).where(t.fetch_state.c.url == url)
            ).first()
            if exists:
                conn.execute(
                    t.fetch_state.update().where(t.fetch_state.c.url == url).values(**values)
                )
            else:
                conn.execute(t.fetch_state.insert().values(**{"url": url, "failures": 0, **values}))

    def __call__(self, spec: dict[str, Any]) -> bytes:
        if "path" in spec:
            return Path(spec["path"]).read_bytes()
        if spec.get("missing"):
            # Подстраницы нет на сайте: заглушка проходит ту же очистку, что и страницы сайта
            # (у Wikisource очистка ставит заголовок главы по названию подстраницы).
            stub = missing_page(spec["name"])
            cleaner = self.cleaners.get(spec.get("clean") or "")
            return cleaner(stub) if cleaner else stub
        url = spec["url"]
        state = self.state(url) or {}
        headers: dict[str, str] = {}
        cached = state.get("sha256")
        if cached and self.files.exists(cached):
            if state.get("etag"):
                headers["If-None-Match"] = state["etag"]
            if state.get("last_modified"):
                headers["If-Modified-Since"] = state["last_modified"]
        try:
            response = self.fetcher.get(url, headers, api=bool(spec.get("api")))
        except FetchError as exc:
            failures = int(state.get("failures") or 0) + 1
            self._save(url, failures=failures, last_error=str(exc), last_status=exc.status)
            if failures >= FAILURES_WARNING:
                events.emit(
                    "library.catalog.fetch_failed", url=url, failures=failures, reason=str(exc)
                )
            raise
        if response.not_modified:
            self._save(url, failures=0, last_error=None, last_status=304)
            events.emit("library.catalog.not_modified", url=url)
            return self.files.get(cached)
        data = response.data
        cleaner = self.cleaners.get(spec.get("clean") or "")
        if cleaner:
            data = cleaner(data)
        self._save(
            url,
            etag=response.headers.get("etag"),
            last_modified=response.headers.get("last-modified"),
            sha256=fingerprint(data),
            final_url=response.final_url,
            failures=0,
            last_error=None,
            last_status=response.status,
        )
        if response.permanent_redirect:
            events.emit("library.catalog.moved", url=url, final_url=response.final_url)
        # Снимок нужен для ответа 304 при следующей проверке.
        self.files.put(data)
        return data


def now_iso(clock: Clock) -> str:
    value: datetime = clock.now()
    return value.replace(microsecond=0).isoformat()
