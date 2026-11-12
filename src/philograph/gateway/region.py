"""Регион читателя: страна из заголовка CDN (``regional-access``, ``design.md`` п. 1).

Шлюз — единственный сервис, видимый снаружи, и единственное место, где страна читателя
переводится в регион. Страна берётся из заголовка, который выставляет CDN (имя задаётся
настройкой), и только у запроса от доверенного прокси/CDN: если шлюз открыт напрямую, клиент
пришлёт заголовок сам. Всё остальное — значение не из двух латинских букв, служебные коды CDN
(``XX``, ``T1``), пустое имя заголовка — означает «регион неизвестен».

Регион живёт только до конца запроса: он передаётся сервисам в ``X-Philograph-Region``
и попадает в счётчик «известен / неизвестен», но не в журналы с привязкой к читателю
и не в хранилище. Запасной регион (``PHILOGRAPH_REGION_FALLBACK``) нужен стенду разработки
и сквозным тестам, которые ходят с локального адреса без CDN; в продакшене он не задаётся.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from starlette.datastructures import Headers

REGION_HEADER = "X-Philograph-Region"
"""Заголовок, в котором шлюз передаёт сервисам страну читателя."""

# Служебные значения заголовков CDN: страна не определена. ``T1`` — Tor, ``XX`` — «неизвестно».
SERVICE_CODES = frozenset({"XX", "T1"})

_CODE = re.compile(r"^[A-Z]{2}$")


def normalize_region(value: str | None) -> str | None:
    """Двухбуквенный код ISO 3166-1 в верхнем регистре; ``None`` — регион неизвестен."""
    if not value:
        return None
    code = value.strip().upper()
    if not _CODE.match(code) or code in SERVICE_CODES:
        return None
    return code


@dataclass(frozen=True)
class RegionSettings:
    header: str = ""  # имя заголовка страны от CDN; пусто — регион всегда неизвестен
    trusted_proxy: bool = False  # заголовку страны верим только от доверенного прокси/CDN
    fallback: str | None = None  # регион вместо неизвестного: только стенд и сквозные тесты

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> RegionSettings:
        """Настройки рядом с ``LimitSettings.from_env``; новых зависимостей нет."""
        return cls(
            header=(env.get("PHILOGRAPH_REGION_HEADER") or "").strip(),
            trusted_proxy=env.get("PHILOGRAPH_TRUSTED_PROXY") == "1",
            fallback=normalize_region(env.get("PHILOGRAPH_REGION_FALLBACK")),
        )


def _lookup(headers: Mapping[str, str], name: str) -> str | None:
    """Значение заголовка без учёта регистра имени (``Headers`` это умеет сам)."""
    if isinstance(headers, Headers):
        return headers.get(name)
    if name in headers:
        return headers[name]
    lowered = name.lower()
    for key, value in headers.items():
        if key.lower() == lowered:
            return value
    return None


def region_from_headers(settings: RegionSettings, headers: Mapping[str, str]) -> str | None:
    """Регион читателя: страна от доверенного CDN, иначе запасной регион стенда, иначе нет."""
    if settings.header and settings.trusted_proxy:
        region = normalize_region(_lookup(headers, settings.header))
        if region is not None:
            return region
    return settings.fallback


class RegionResolver:
    """Настройки региона для одного шлюза; страна нигде не запоминается."""

    def __init__(self, settings: RegionSettings) -> None:
        self.settings = settings

    def region(self, headers: Mapping[str, str]) -> str | None:
        return region_from_headers(self.settings, headers)

    def dropped_headers(self) -> set[str]:
        """Заголовки, которые шлюз не передаёт сервисам: клиентский регион и страна от CDN."""
        dropped = {REGION_HEADER.lower()}
        if self.settings.header:
            dropped.add(self.settings.header.lower())
        return dropped

    def vary(self) -> str | None:
        """По какому заголовку запроса различается ответ: имя заголовка страны, если задано."""
        return self.settings.header or None
