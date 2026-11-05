"""Требования спецификации source-catalog. Сеть не нужна: сайты подделаны через MockTransport."""

from __future__ import annotations

import pytest

from philograph.library.catalog import model
from philograph.library.catalog.__main__ import main as cli

from .conftest import FIXTURES, PARAGRAPHS, book

req = pytest.mark.req
SC = "source-catalog"
URL = "https://books.example/b.txt"


def problems(env, level="error"):
    return [str(p) for p in model.validate(env.catalog, year=2026) if p.level == level]


# --- Каталог источников в репозитории ----------------------------------------------


@req(SC, "Каталог источников в репозитории")
def test_valid_catalog_passes(env, capsys):
    env.entry()
    env.entry("second-book", landing_url="https://books.example/other", review={"status": "draft"})
    assert problems(env) == []
    env.catalog.save()
    assert cli(["--catalog", str(env.catalog.path), "validate"]) == 0
    out = capsys.readouterr().out
    assert "записей: 2" in out and '"approved": 1' in out and '"draft": 1' in out


@req(SC, "Каталог источников в репозитории")
def test_duplicate_id_fails(env):
    env.entry("same-id")
    env.entry("same-id", landing_url="https://books.example/x")
    assert any("same-id" in p and "повторяется" in p for p in problems(env))


@req(SC, "Каталог источников в репозитории")
def test_approved_without_license_basis_fails(env):
    entry = env.entry()
    del entry["license"]["basis"]
    found = problems(env)
    assert any("[test-book]" in p and "basis" in p for p in found), found
    entry["license"] = None
    assert any("[test-book]" in p and "нет лицензии" in p for p in problems(env))


@req(SC, "Каталог источников в репозитории")
def test_catalog_has_no_texts():
    from .conftest import REPO_SOURCES

    for path in REPO_SOURCES.rglob("*"):
        assert path.suffix in {".yaml", ".json", ".md", ""}, (
            f"в каталоге не должно быть текстов: {path}"
        )


# --- Добавление источника по ссылке ------------------------------------------------


@req(SC, "Добавление источника по ссылке")
def test_add_gutenberg_book(env):
    env.web.routes["https://www.gutenberg.org/ebooks/10615.rdf"] = (
        200,
        (FIXTURES / "pg10615.rdf").read_bytes(),
    )
    entry, new = env.service.add("https://www.gutenberg.org/ebooks/10615", kind="primary")
    assert new and entry["review"]["status"] == "draft"
    meta = model.metadata(entry)
    assert meta["title"].startswith("An Essay Concerning Humane Understanding, Volume 1 MDCXC")
    assert meta["authors"] == [{"name": "John Locke", "death_year": 1704, "wikidata": None}]
    assert meta["language"] == "en"
    assert model.files(entry) == [
        {
            "name": "pg10615.epub",
            "url": "https://www.gutenberg.org/ebooks/10615.epub3.images",
            "clean": "gutenberg",
        }
    ]
    assert entry["license"]["basis"] == "public_domain"
    assert entry["id"] == "locke-essay-concerning-humane-understanding-volume"


@req(SC, "Добавление источника по ссылке")
def test_add_same_url_twice(env):
    first = env.entry()
    entry, new = env.service.add(first["landing_url"] + "/", kind="primary")
    assert not new and entry["id"] == "test-book"
    assert len(env.catalog.entries) == 1


@req(SC, "Добавление источника по ссылке")
def test_unknown_site_becomes_direct(env):
    entry, new = env.service.add("https://unknown.example/files/hume.pdf", kind="primary")
    assert new and entry["adapter"] == "direct"
    assert model.files(entry) == [
        {"name": "hume.pdf", "url": "https://unknown.example/files/hume.pdf"}
    ]
    assert model.metadata(entry) == {} and entry["publish"] == "manual"


# --- Метаданные с сайта и правки человека ------------------------------------------


@req(SC, "Метаданные с сайта и правки человека")
def test_override_wins(env):
    env.web.routes[URL] = (200, book(*PARAGRAPHS))
    env.entry(override={"metadata": {"title": "Опыт о человеческом разумении"}})
    outcome = env.sync()["test-book"]
    assert outcome.outcome == "published", outcome
    assert env.registry.get(outcome.source_id).title == "Опыт о человеческом разумении"


@req(SC, "Метаданные с сайта и правки человека")
def test_site_metadata_change_updates_without_version(env, events):
    env.web.routes[URL] = (200, book(*PARAGRAPHS))
    entry = env.entry()
    source_id = env.sync()["test-book"].source_id
    versions = len(env.registry.versions(source_id))
    entry["harvested"]["metadata"]["year"] = 1700
    outcome = env.sync()["test-book"]
    assert outcome.outcome == "unchanged"
    assert env.registry.get(source_id).year == 1700
    assert len(env.registry.versions(source_id)) == versions
    assert events.where("library.metadata.updated", source_id=source_id, fields=["year"])


@req(SC, "Метаданные с сайта и правки человека")
def test_harvest_shows_changes_and_keeps_override(env):
    env.web.routes["https://www.gutenberg.org/ebooks/10615.rdf"] = (
        200,
        (FIXTURES / "pg10615.rdf").read_bytes(),
    )
    entry, _ = env.service.add("https://www.gutenberg.org/ebooks/10615", kind="primary")
    entry["override"] = {"metadata": {"title": "Опыт"}}
    entry["harvested"]["metadata"]["language"] = "de"
    changes = env.service.harvest(entry)
    assert [(c.field, c.old, c.new) for c in changes] == [("language", "de", "en")]
    assert model.metadata(entry)["title"] == "Опыт"


# --- Синхронизация каталога с библиотекой ------------------------------------------


@req(SC, "Синхронизация каталога с библиотекой")
def test_first_sync_registers_and_links(env):
    env.web.routes[URL] = (200, book(*PARAGRAPHS))
    env.entry()
    outcome = env.sync()["test-book"]
    assert outcome.outcome == "published"
    assert env.service.linked("test-book") == outcome.source_id
    source = env.registry.get(outcome.source_id)
    assert source.published_version == outcome.version_id
    assert source.original_url == "https://books.example/test-book"


@req(SC, "Синхронизация каталога с библиотекой")
def test_second_sync_changes_nothing(env):
    env.web.routes[URL] = (200, book(*PARAGRAPHS))
    env.entry(publish="manual")
    first = env.sync()["test-book"]
    assert first.outcome == "waiting_operator"
    sources = len(env.registry.overview())
    again = env.sync()["test-book"]
    assert again.outcome == "unchanged"
    assert len(env.registry.overview()) == sources
    assert len(env.registry.versions(first.source_id)) == 1


@req(SC, "Синхронизация каталога с библиотекой")
def test_draft_is_skipped(env):
    env.entry(review={"status": "draft"})
    outcome = env.sync()["test-book"]
    assert outcome.outcome == "draft" and outcome.source_id is None
    assert env.web.hits(URL) == 0


# --- Правило публикации обновлений -------------------------------------------------


@req(SC, "Правило публикации обновлений")
def test_small_fix_is_published_and_links_work(env):
    env.web.routes[URL] = (200, book(*PARAGRAPHS))
    env.entry()
    first = env.sync()["test-book"]
    fixed = list(PARAGRAPHS)
    fixed[3] = fixed[3].replace("knowledge", "knowlege").replace("knowlege", "knowledge!")
    env.web.routes[URL] = (200, book(*fixed))
    outcome = env.service.check_updates()[0]
    assert outcome.outcome == "published", outcome
    assert outcome.version_id != first.version_id
    doc = env.registry.load_document(outcome.version_id)
    old_ids = {b.id for _, b in env.registry.load_document(first.version_id).blocks()}
    for pid in old_ids:
        assert env.registry.resolve_paragraph(pid)["source_id"] == first.source_id
    assert any("knowledge!" in b.text for _, b in doc.blocks())


@req(SC, "Правило публикации обновлений")
def test_large_change_waits_with_warning(env, events):
    env.web.routes[URL] = (200, book(*PARAGRAPHS))
    env.entry()
    first = env.sync()["test-book"]
    env.web.routes[URL] = (200, book(*PARAGRAPHS[:40]))
    outcome = env.service.check_updates()[0]
    assert outcome.outcome == "waiting_operator" and "удалено 20 из" in outcome.detail
    assert env.registry.get(first.source_id).published_version == first.version_id
    assert events.where("library.catalog.needs_decision", version_id=outcome.version_id)


@req(SC, "Правило публикации обновлений")
def test_same_text_is_published_without_operator(env):
    env.web.routes[URL] = (200, b"Chapter I\n\n" + "\n\n".join(PARAGRAPHS).encode())
    env.entry(publish="manual")
    entry = env.catalog.find("test-book")
    entry["harvested"]["files"][0].pop("clean")
    first = env.sync()["test-book"]
    env.registry.publish("operator", first.version_id)
    # файл другой (лишние пустые строки), текст абзацев тот же
    env.web.routes[URL] = (200, b"Chapter I\n\n\n\n" + "\n\n\n".join(PARAGRAPHS).encode())
    outcome = env.service.check_updates()[0]
    assert outcome.outcome == "published_same_text", outcome


# --- Снятие источника через каталог ------------------------------------------------


@req(SC, "Снятие источника через каталог")
def test_withdrawn_entry_is_unpublished(env):
    env.web.routes[URL] = (200, book(*PARAGRAPHS))
    entry = env.entry()
    first = env.sync()["test-book"]
    pid = next(b.id for _, b in env.registry.load_document(first.version_id).blocks())
    entry["review"] = {"status": "withdrawn", "note": "проверка"}
    assert env.sync()["test-book"].outcome == "withdrawn"
    assert env.registry.get(first.source_id).status == "unpublished"
    assert env.registry.resolve_paragraph(pid)["status"] == "source_unavailable"
    assert env.sync()["test-book"].outcome == "withdrawn_already"
    entry["review"] = {"status": "approved"}
    assert env.sync()["test-book"].outcome == "unchanged"
    assert env.registry.resolve_paragraph(pid)["status"] == "found"


@req(SC, "Снятие источника через каталог")
def test_deleted_entry_fails_validation(env):
    env.entry()
    env.catalog.save()
    env.catalog.entries.clear()
    found = problems(env)
    assert any("[test-book]" in p and "withdrawn" in p for p in found), found


# --- Бережная загрузка с сайтов ----------------------------------------------------


@req(SC, "Бережная загрузка с сайтов")
def test_robots_disallow(env):
    env.web.routes["https://books.example/robots.txt"] = (200, b"User-agent: *\nDisallow: /\n")
    env.web.routes[URL] = (200, book(*PARAGRAPHS))
    env.entry()
    outcome = env.sync()["test-book"]
    assert outcome.outcome == "failed" and "robots.txt" in outcome.detail
    assert env.web.hits(URL) == 0


@req(SC, "Бережная загрузка с сайтов")
def test_temporary_error_is_retried(env):
    env.web.routes[URL] = [(503, b""), (200, book(*PARAGRAPHS))]
    env.entry()
    assert env.sync()["test-book"].outcome == "published"
    assert env.web.hits(URL) == 2 and 0.5 in env.sleeps


@req(SC, "Бережная загрузка с сайтов")
def test_user_agent_and_rate_limit(env):
    env.web.routes[URL] = (200, book(*PARAGRAPHS))
    env.entry()
    env.sync()
    agents = {r.headers["user-agent"] for r in env.web.seen}
    assert len(agents) == 1
    agent = agents.pop()
    assert "PhiloGraph" in agent and "github.com/Alberelloo" in agent and "@" not in agent
    # два запроса к одному сайту (robots.txt и файл) — между ними пауза в секунду
    assert 1.0 in env.sleeps


@req(SC, "Бережная загрузка с сайтов")
def test_size_limit(env):
    env.service.fetcher.settings.max_bytes = 100
    env.web.routes[URL] = (200, book(*PARAGRAPHS))
    env.entry()
    outcome = env.sync()["test-book"]
    assert outcome.outcome == "failed" and "больше 100 байт" in outcome.detail


# --- Проверка обновлений без лишней загрузки ---------------------------------------


@req(SC, "Проверка обновлений без лишней загрузки")
def test_not_modified_creates_no_version(env, events):
    calls = []

    def respond(request):
        import httpx

        calls.append(dict(request.headers))
        if request.headers.get("if-none-match") == '"v1"':
            return httpx.Response(304, request=request)
        return httpx.Response(200, content=book(*PARAGRAPHS), headers={"ETag": '"v1"'})

    env.web.routes[URL] = respond
    env.entry()
    first = env.sync()["test-book"]
    assert env.service.check_updates()[0].outcome == "unchanged"
    assert calls[-1]["if-none-match"] == '"v1"'
    assert len(env.registry.versions(first.source_id)) == 1
    assert events.of("library.catalog.not_modified")


@req(SC, "Проверка обновлений без лишней загрузки")
def test_gutenberg_header_change_is_ignored(env):
    env.web.routes[URL] = (200, book(*PARAGRAPHS, header="Release date: 2001"))
    env.entry()
    first = env.sync()["test-book"]
    env.web.routes[URL] = (200, book(*PARAGRAPHS, header="Most recently updated: 2026"))
    assert env.service.check_updates()[0].outcome == "unchanged"
    assert len(env.registry.versions(first.source_id)) == 1


# --- Недоступный или переехавший источник ------------------------------------------


@req(SC, "Недоступный или переехавший источник")
def test_missing_site_keeps_publication(env, events):
    env.web.routes[URL] = (200, book(*PARAGRAPHS))
    env.entry()
    first = env.sync()["test-book"]
    env.web.routes[URL] = (404, b"")
    for _ in range(3):
        assert env.service.check_updates()[0].outcome == "failed"
    assert env.registry.get(first.source_id).published_version == first.version_id
    warning = events.one("library.catalog.fetch_failed")
    assert warning.get("failures") == 3
    assert env.service.status()[0]["fetch_failures"] == 3


@req(SC, "Недоступный или переехавший источник")
def test_moved_site_is_followed_and_reported(env, events):
    import httpx

    new = "https://new.example/b.txt"
    env.web.routes[URL] = lambda r: httpx.Response(301, headers={"Location": new}, request=r)
    env.web.routes[new] = (200, book(*PARAGRAPHS))
    env.entry()
    assert env.sync()["test-book"].outcome == "published"
    assert env.service.pipeline.fetch.state(URL)["final_url"] == new
    assert events.one("library.catalog.moved").get("final_url") == new
