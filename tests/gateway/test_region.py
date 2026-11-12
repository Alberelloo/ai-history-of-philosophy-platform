"""Регион читателя: настройки и разбор заголовка страны (``regional-access``)."""

from __future__ import annotations

import pytest

from philograph.gateway.region import (
    REGION_HEADER,
    RegionResolver,
    RegionSettings,
    normalize_region,
    region_from_headers,
)

req = pytest.mark.req
RA = "regional-access"


def test_settings_from_env():
    """Настройки читаются из окружения рядом с LimitSettings.from_env."""
    settings = RegionSettings.from_env(
        {
            "PHILOGRAPH_REGION_HEADER": " CF-IPCountry ",
            "PHILOGRAPH_TRUSTED_PROXY": "1",
            "PHILOGRAPH_REGION_FALLBACK": "ru",
        }
    )
    assert settings.header == "CF-IPCountry"
    assert settings.trusted_proxy is True
    assert settings.fallback == "RU"
    empty = RegionSettings.from_env({})
    assert empty.header == "" and empty.trusted_proxy is False and empty.fallback is None


@req(RA, "Регион читателя определяет шлюз")
def test_region_from_trusted_proxy():
    """Читатель из РФ: страна пришла от доверенного CDN — регион RU."""
    settings = RegionSettings(header="CF-IPCountry", trusted_proxy=True)
    assert region_from_headers(settings, {"cf-ipcountry": "RU"}) == "RU"
    # Имя заголовка сравнивается без учёта регистра, значение — тоже.
    assert region_from_headers(settings, {"Cf-Ipcountry": "ru"}) == "RU"


@req(RA, "Регион читателя определяет шлюз")
def test_untrusted_proxy_ignores_country():
    """Запрос не от доверенного прокси: заголовку страны не верим, регион неизвестен."""
    settings = RegionSettings(header="CF-IPCountry", trusted_proxy=False)
    assert region_from_headers(settings, {"CF-IPCountry": "RU"}) is None


@req(RA, "Неизвестный регион закрывает ограниченные источники")
def test_service_codes_are_unknown():
    """Служебные коды CDN и всё, что не двухбуквенный код, — неизвестный регион."""
    for value in ("XX", "T1", "RUS", "РФ", "", "  ", "RU1", "1R"):
        assert normalize_region(value) is None, value
    assert normalize_region(None) is None


@req(RA, "Регион читателя определяет шлюз")
def test_lowercase_region_normalized():
    """Код приводится к верхнему регистру, пробелы по краям не мешают."""
    assert normalize_region("ru") == "RU"
    assert normalize_region(" ru ") == "RU"
    assert normalize_region("De") == "DE"


@req(RA, "Неизвестный регион закрывает ограниченные источники")
def test_fallback_region_for_local_stand():
    """Запасной регион подставляет стенд разработки, когда страны нет."""
    settings = RegionSettings(header="CF-IPCountry", trusted_proxy=True, fallback="RU")
    assert region_from_headers(settings, {}) == "RU"
    # Страна от CDN важнее запасного региона.
    assert region_from_headers(settings, {"CF-IPCountry": "DE"}) == "DE"


@req(RA, "Неизвестный регион закрывает ограниченные источники")
def test_empty_header_setting_means_unknown():
    """Имя заголовка не задано — регион всегда неизвестен, даже если клиент что-то прислал."""
    settings = RegionSettings(header="", trusted_proxy=True)
    assert region_from_headers(settings, {"CF-IPCountry": "RU"}) is None
    assert region_from_headers(settings, {REGION_HEADER: "RU"}) is None


@req(RA, "Неизвестный регион закрывает ограниченные источники")
def test_invalid_fallback_ignored():
    """Неверный запасной регион считается пустым: подставлять нечего."""
    settings = RegionSettings.from_env({"PHILOGRAPH_REGION_FALLBACK": "XX"})
    assert settings.fallback is None
    assert RegionResolver(settings).region({}) is None


@req(RA, "Регион читателя определяет шлюз")
def test_dropped_headers_and_vary():
    """Шлюз выбрасывает клиентский регион и заголовок страны; Vary — по заголовку страны."""
    resolver = RegionResolver(RegionSettings(header="CF-IPCountry", trusted_proxy=True))
    assert resolver.dropped_headers() == {REGION_HEADER.lower(), "cf-ipcountry"}
    assert resolver.vary() == "CF-IPCountry"
    bare = RegionResolver(RegionSettings())
    assert bare.dropped_headers() == {REGION_HEADER.lower()}
    assert bare.vary() is None
