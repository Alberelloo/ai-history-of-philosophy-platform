"""Группа 7 «Внешняя обработка» сервиса знаний: разбор неоднозначных упоминаний моделью
пропускает источники без разрешения внешней обработки. Требование ``regional-access``
«Внешняя обработка закрытых источников».
"""

from __future__ import annotations

import httpx
import pytest

from philograph.knowledge.mentions import Mentions
from philograph.platform.client import ServiceClient

req = pytest.mark.req
RA = "regional-access"
REQ = "Внешняя обработка закрытых источников"


def version_library(external: bool) -> ServiceClient:
    """Фиктивная библиотека: ``internal/versions/{id}/paragraphs`` с заданным признаком."""
    payload = {
        "source_id": "s_no_external",
        "source_title": "Без внешней обработки",
        "version_id": "v1",
        "scope": "public",
        "permissions": {"display": True, "external_processing": external, "quoting": True},
        "external_processing": external,
        "regions": None,
        "chapters": {"c1": "Глава"},
        "paragraphs": [
            {
                "id": "p1",
                "text": "Бэкон писал об оптике.",
                "lang": "ru",
                "ord": 1,
                "section_id": "s1",
                "section_title": "Глава",
                "chapter_id": "c1",
                "searchable": True,
            }
        ],
        "headings": [],
        "footnotes": [],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert "/internal/versions/" in request.url.path
        return httpx.Response(200, json=payload)

    return ServiceClient(
        "library", "http://library/api", transport=httpx.MockTransport(handler), retries=0
    )


def two_bacons(onto) -> None:
    """Два однофамильца «Бэкон»: имя неоднозначно без контекста главы."""
    onto.person("Бэкон", "1561", "1626")
    onto.person("Бэкон", "1214", "1292")


@req(RA, REQ)
def test_ambiguous_mention_skips_resolver_without_external(onto, events):
    """7.3: без ``external_processing`` модель-разрешитель не вызывается, упоминание остаётся
    неоднозначным и не записывается."""
    two_bacons(onto)
    calls: list[tuple[str, list[str], str]] = []

    def resolver(surface, candidates, text):
        calls.append((surface, list(candidates), text))
        return candidates[0]

    mentions = Mentions(onto.statements, version_library(False), resolver=resolver)
    assert mentions.index_version("v1") == 0  # упоминание не поставлено
    assert calls == []  # текст не ушёл модели
    events.one("knowledge.mentions.unresolved")


@req(RA, REQ)
def test_ambiguous_mention_uses_resolver_with_external(onto):
    """Обратная совместимость: с ``external_processing`` разрешитель вызывается, как раньше."""
    two_bacons(onto)
    calls: list[tuple[str, list[str], str]] = []

    def resolver(surface, candidates, text):
        calls.append((surface, list(candidates), text))
        return candidates[0]

    mentions = Mentions(onto.statements, version_library(True), resolver=resolver)
    assert mentions.index_version("v1") == 1
    assert calls  # внешняя обработка разрешена — модель вызывается
