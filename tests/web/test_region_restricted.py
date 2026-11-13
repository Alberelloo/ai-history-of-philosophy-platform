"""regional-access, «Библиотека закрывает текст ограниченных источников»: строка в списке.

Читатель без заголовка региона считается находящимся вне всех разрешённых регионов, поэтому
источник с регионами показа `[RU]` виден строкой «Доступен в РФ» и не открывается.
"""

from __future__ import annotations

import pytest

from philograph.library.registry import License

req = pytest.mark.req
RA = "regional-access"
RU_KIND = "public-domain-ru"


@pytest.fixture(scope="module")
def limited(site):
    site.registry.add_license_kind(
        RU_KIND,
        "Общественное достояние по праву РФ",
        None,
        {"display": True, "external_processing": True, "quoting": True},
        regions=["RU"],
    )
    source_id = site.registry.register(
        "operator",
        title="Русский учебник",
        authors=["П. Д. Юркевич"],
        year=1865,
        language="ru",
        kind="textbook",
        license=License(RU_KIND, "public_domain", author_death_years=[1900]),
        scope="public",
        files=[{"name": "r2", "path": "reference.txt"}],
    )
    version = site.pipeline.start("operator", source_id)
    site.registry.publish("operator", version)
    return site, source_id


@req(RA, "Библиотека закрывает текст ограниченных источников")
def test_restricted_source_row(page, limited):
    site, source_id = limited
    assert site.registry.regions(source_id) == frozenset({"RU"})
    page.goto(f"{site.url}/")
    # Список грузится запросом к библиотеке: ждём отрисовку строки, а не считаем сразу.
    page.wait_for_selector("li.source--restricted")

    row = page.locator("li.source--restricted", has_text="Русский учебник")
    assert row.count() == 1
    assert row.locator(".badge", has_text="Доступен в РФ").count() == 1
    assert row.locator("button", has_text="Читать").count() == 0
    assert row.locator("dt", has_text="Год").count() == 0
    assert row.locator("dt", has_text="Лицензия").count() == 0
    assert row.locator("dd", has_text="Юркевич").count() == 1

    # Открытые источники списка по-прежнему можно открыть: их ровно три.
    assert page.locator("li.source button", has_text="Читать").count() == 3
