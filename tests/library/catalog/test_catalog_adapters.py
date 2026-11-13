"""Адаптеры каталога: год издания Gutenberg и авторы Wikisource без шапки.

Сеть не нужна: сайты подделаны через MockTransport фикстуры ``env``. Проверяется, что год
Gutenberg берётся из RDF, а если его нет — из Wikidata (P577, самый ранний), и что Wikisource
находит автора без шаблона «Отексте»/``header`` (ссылка на страницу автора или жирная подпись),
а при отсутствии автора — не падает и пишет предупреждение.
"""

from __future__ import annotations

import json
from urllib.parse import quote

import pytest

from philograph.library.catalog.adapters import Gutenberg, Wikisource

req = pytest.mark.req
SC = "source-catalog"

HOST = "ru.wikisource.org"
WIKIDATA_SEARCH = "https://www.wikidata.org/w/api.php?action=wbsearchentities&type=item&format=json"
WIKIDATA_ENTITY = "https://www.wikidata.org/wiki/Special:EntityData"


def pg_rdf(title: str, author: str, *, issued: str | None = None, book: int = 100) -> bytes:
    issued_xml = (
        f'<dcterms:issued rdf:datatype="http://www.w3.org/2001/XMLSchema#date">{issued}</dcterms:issued>\n'
        if issued
        else ""
    )
    return f"""<?xml version="1.0" encoding="utf-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
  xmlns:dcterms="http://purl.org/dc/terms/"
  xmlns:pgterms="http://www.gutenberg.org/2009/pgterms/"
  xmlns:marcrel="http://id.loc.gov/vocabulary/relators/">
  <pgterms:ebook rdf:about="ebooks/{book}">
    <dcterms:title>{title}</dcterms:title>
    {issued_xml}
    <dcterms:creator>
      <pgterms:agent><pgterms:name>{author}</pgterms:name></pgterms:agent>
    </dcterms:creator>
    <dcterms:language><rdf:Description><rdf:value>en</rdf:value></rdf:Description></dcterms:language>
    <dcterms:rights>Public domain in the USA.</dcterms:rights>
    <dcterms:hasFormat>
      <pgterms:file rdf:about="https://www.gutenberg.org/ebooks/{book}.epub3.images">
        <dcterms:format><rdf:Description><rdf:value>application/epub+zip</rdf:value></rdf:Description></dcterms:format>
      </pgterms:file>
    </dcterms:hasFormat>
  </pgterms:ebook>
</rdf:RDF>
""".encode()


def ws_pageprops(title: str) -> str:
    return (
        f"https://{HOST}/w/api.php?action=query&prop=pageprops&redirects=1"
        f"&format=json&formatversion=2&titles={quote(title)}"
    )


def ws_parse(page: str) -> str:
    return (
        f"https://{HOST}/w/api.php?action=parse&prop=wikitext&format=json"
        f"&formatversion=2&page={quote(page)}"
    )


def ws_rest(page: str) -> str:
    return Wikisource.rest_url(HOST, page)


def ws_site(env, wikitext: str, *, page: str, author_qid: dict[str, str] | None = None) -> None:
    """Поддельная страница Wikisource: шапка, вики-текст, страница автора (опционально) и HTML."""
    env.web.routes[ws_pageprops(page)] = (
        200,
        json.dumps({"query": {"pages": [{"title": page}]}}).encode(),
    )
    env.web.routes[ws_parse(page)] = (200, json.dumps({"parse": {"wikitext": wikitext}}).encode())
    for title, qid in (author_qid or {}).items():
        pageprops = {"pageprops": {"wikibase_item": qid}} if qid else {}
        env.web.routes[ws_pageprops(title)] = (
            200,
            json.dumps({"query": {"pages": [pageprops]}}).encode(),
        )
    html = (
        f'<html><head><meta charset="utf-8"/><title>{page}</title></head>'
        "<body><p>текст</p></body></html>"
    )
    env.web.routes[ws_rest(page)] = (200, html.encode())


def entity(qid: str, label: str, claims: dict[str, list]) -> bytes:
    body = {"entities": {qid: {"labels": {"ru": {"value": label}}, "claims": claims}}}
    return json.dumps(body).encode()


def time_claim(year: int) -> dict:
    return {"mainsnak": {"datavalue": {"value": {"time": f"+{year:04d}-00-00T00:00:00Z"}}}}


# --- Gutenberg: год издания ---------------------------------------------------------


@req(SC, "Метаданные с сайта и правки человека")
def test_gutenberg_year_from_rdf_when_wikidata_has_nothing(env):
    """``dcterms:issued`` Gutenberg — дата выкладки на сайт, поэтому она последний вариант.

    Иначе карточка «Критики чистого разума» получала бы 2003 вместо 1781.
    """
    env.web.routes["https://www.gutenberg.org/ebooks/100.rdf"] = (
        200,
        pg_rdf("Some Book", "Author, Test", issued="1790-01-01"),
    )
    harvest = Gutenberg().harvest("https://www.gutenberg.org/ebooks/100", env.service.fetcher)
    assert harvest.metadata["year"] == 1790  # Wikidata ничего не знает — берём RDF
    assert any("wikidata.org" in r for r in env.service.fetcher.requests)


@req(SC, "Метаданные с сайта и правки человека")
def test_gutenberg_year_prefers_first_publication_over_site_date(env):
    """Первая публикация с Wikidata приоритетнее даты выкладки на сайт."""
    env.web.routes["https://www.gutenberg.org/ebooks/102.rdf"] = (
        200,
        pg_rdf("A Treatise", "Hume, David", issued="2004-05-01", book=102),
    )
    assert _harvest_with_wikidata(env, "A Treatise", 1739, book=102) == 1739


def _harvest_with_wikidata(env, title: str, year: int, *, book: int) -> int | None:
    """Харвест книги, у которой Wikidata знает год первой публикации."""
    env.web.routes[f"{WIKIDATA_SEARCH}&limit=10&language=en&search={quote(title)}"] = (
        200,
        json.dumps({"search": [{"id": "Q777"}]}).encode(),
    )
    env.web.routes[f"{WIKIDATA_ENTITY}/Q777.json"] = (
        200,
        entity("Q777", title, {"P577": [time_claim(year)]}),
    )
    return (
        Gutenberg()
        .harvest(f"https://www.gutenberg.org/ebooks/{book}", env.service.fetcher)
        .metadata["year"]
    )


@req(SC, "Метаданные с сайта и правки человека")
def test_gutenberg_year_from_wikidata(env):
    title = "Critique of Pure Reason"
    env.web.routes["https://www.gutenberg.org/ebooks/101.rdf"] = (
        200,
        pg_rdf(title, "Kant, Immanuel", book=101),
    )
    env.web.routes[f"{WIKIDATA_SEARCH}&limit=10&language=en&search={quote(title)}"] = (
        200,
        json.dumps({"search": [{"id": "Q220002"}]}).encode(),
    )
    env.web.routes[f"{WIKIDATA_ENTITY}/Q220002.json"] = (
        200,
        entity("Q220002", title, {"P577": [time_claim(1781), time_claim(1787)]}),
    )
    harvest = Gutenberg().harvest("https://www.gutenberg.org/ebooks/101", env.service.fetcher)
    # P577 два значения — берётся самый ранний.
    assert harvest.metadata["year"] == 1781


@req(SC, "Метаданные с сайта и правки человека")
def test_gutenberg_year_from_author_works_fallback(env):
    title = "Some Book"
    author = "Test Author"
    env.web.routes["https://www.gutenberg.org/ebooks/102.rdf"] = (
        200,
        pg_rdf(title, author, book=102),
    )
    env.web.routes[f"{WIKIDATA_SEARCH}&limit=10&language=en&search={quote(title)}"] = (
        200,
        json.dumps({"search": []}).encode(),
    )
    env.web.routes[f"{WIKIDATA_SEARCH}&limit=5&language=en&search={quote(author)}"] = (
        200,
        json.dumps({"search": [{"id": "Q9"}]}).encode(),
    )
    env.web.routes[f"{WIKIDATA_ENTITY}/Q9.json"] = (
        200,
        entity(
            "Q9",
            author,
            {
                "P31": [{"mainsnak": {"datavalue": {"value": {"id": "Q5"}}}}],
                "P570": [time_claim(1900)],
                "P800": [{"mainsnak": {"datavalue": {"value": {"id": "Q8"}}}}],
            },
        ),
    )
    env.web.routes[f"{WIKIDATA_ENTITY}/Q8.json"] = (
        200,
        entity("Q8", title, {"P577": [time_claim(1888)]}),
    )
    harvest = Gutenberg().harvest("https://www.gutenberg.org/ebooks/102", env.service.fetcher)
    assert harvest.metadata["year"] == 1888


@req(SC, "Метаданные с сайта и правки человека")
def test_gutenberg_year_none_when_wikidata_unreachable(env):
    env.web.routes["https://www.gutenberg.org/ebooks/103.rdf"] = (
        200,
        pg_rdf("Some Book", "Author, Test", book=103),
    )
    # Wikidata не отвечает (маршрут не задан → 404): год None, без падения.
    harvest = Gutenberg().harvest("https://www.gutenberg.org/ebooks/103", env.service.fetcher)
    assert harvest.metadata["year"] is None


# --- Wikisource: авторы без шапки «Отексте» ------------------------------------------


@req(SC, "Добавление источника по ссылке")
def test_wikisource_author_from_link(env):
    page = "Статья"
    wikitext = "[[Автор:Иванов, Иван]]\nТекст статьи."
    ws_site(env, wikitext, page=page, author_qid={"Автор:Иванов, Иван": "Q123"})
    env.web.routes[f"{WIKIDATA_ENTITY}/Q123.json"] = (
        200,
        entity("Q123", "Иван Иванов", {"P570": [time_claim(1855)]}),
    )
    harvest = Wikisource().harvest(f"https://{HOST}/wiki/{quote(page)}", env.service.fetcher)
    assert harvest.metadata["authors"] == [
        {"name": "Иван Иванов", "death_year": 1855, "wikidata": "Q123"}
    ]


@req(SC, "Добавление источника по ссылке")
def test_wikisource_author_from_signed_template(env):
    """ЭСБЕ подписывает статью подшаблоном: «{{ЭСБЕ/Автор|Н. Г. Дебольский}}» в конце."""
    page = "ЭСБЕ/Теория познания"
    wikitext = (
        "{{ЭСБЕ\n|КАЧЕСТВО=2\n}}\n"
        "'''Теория познания.''' — текст статьи одной строкой.\n"
        "{{ЭСБЕ/Автор|Н. Г. Дебольский}}.\n"
        "[[Категория:ЭСБЕ:Философия]]"
    )
    ws_site(env, wikitext, page=page, author_qid={"Автор:Н. Г. Дебольский": None})
    harvest = Wikisource().harvest(f"https://{HOST}/wiki/{quote(page)}", env.service.fetcher)
    assert harvest.metadata["authors"] == [
        {"name": "Н. Г. Дебольский", "death_year": None, "wikidata": None}
    ]


@req(SC, "Добавление источника по ссылке")
def test_wikisource_author_from_bold_name(env):
    page = "Статья"
    ws_site(
        env, "'''Иван Иванов'''\nТекст статьи.", page=page, author_qid={"Автор:Иван Иванов": None}
    )
    harvest = Wikisource().harvest(f"https://{HOST}/wiki/{quote(page)}", env.service.fetcher)
    assert harvest.metadata["authors"] == [
        {"name": "Иван Иванов", "death_year": None, "wikidata": None}
    ]


@req(SC, "Добавление источника по ссылке")
def test_wikisource_bold_title_is_not_author(env):
    page = "Теория познания"
    # Жирная строка совпадает с названием страницы — это не подпись автора.
    ws_site(env, "'''Теория познания.''' — текст статьи.", page=page)
    harvest = Wikisource().harvest(f"https://{HOST}/wiki/{quote(page)}", env.service.fetcher)
    assert harvest.metadata["authors"] == []


@req(SC, "Добавление источника по ссылке")
def test_wikisource_no_author_warns_without_failing(env, events):
    page = "Теория познания"
    ws_site(env, "'''Теория познания.''' — текст статьи.", page=page)
    harvest = Wikisource().harvest(f"https://{HOST}/wiki/{quote(page)}", env.service.fetcher)
    assert harvest.metadata["authors"] == []
    assert events.of("library.catalog.author_not_found")


@req(SC, "Добавление источника по ссылке")
def test_wikisource_header_author_unchanged(env):
    page = "Государство"
    wikitext = "{{Отексте\n|АВТОР=[[Платон]]\n|НАЗВАНИЕ=Государство\n}}\n\nТекст."
    ws_site(env, wikitext, page=page, author_qid={"Автор:Платон": None})
    harvest = Wikisource().harvest(f"https://{HOST}/wiki/{quote(page)}", env.service.fetcher)
    assert harvest.metadata["authors"] == [{"name": "Платон", "death_year": None, "wikidata": None}]

