"""Требования спецификации service-runtime."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
import yaml
from fastapi import APIRouter
from fastapi.testclient import TestClient

from philograph.llm import store as llm_store
from philograph.llm.app import build_app
from philograph.llm.config import GatewayConfig
from philograph.llm.gateway import LLMGateway
from philograph.llm.main import create
from philograph.llm.providers import FakeProvider, TransientProviderError
from philograph.llm.templates import Template, TemplateRegistry
from philograph.operator.access import migrations as operator_migrations
from philograph.platform.client import ServiceClient, ServiceUnavailable
from philograph.platform.health import Health
from philograph.platform.queue import Queue
from philograph.platform.queue import migrations as queue_migrations
from philograph.platform.settings import ServiceSettings, SettingsError, load
from philograph.platform.web import create_app

from ..llm.conftest import CONFIG

ROOT = Path(__file__).resolve().parents[2]
req = pytest.mark.req


@req("service-runtime", "Запуск одной командой")
def test_compose_describes_whole_system():
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    services = compose["services"]
    assert {"postgres", "qdrant", "llm"} <= set(services)
    for name, service in services.items():
        if service.get("restart") == "no":
            continue  # разовая задача (миграции перед обновлением): не живёт, а завершается
        assert "healthcheck" in service, f"{name} без проверки готовности"
        assert service.get("restart") or "<<" in service
    # Сервисы приложения собираются из одного образа и ждут готовности базы.
    anchor = compose["x-service"]
    assert anchor["build"] == "." and anchor["depends_on"]["postgres"]["condition"] == (
        "service_healthy"
    )
    assert (ROOT / "Dockerfile").exists() and (ROOT / ".env.example").exists()


@req("service-runtime", "Настройки из окружения")
def test_settings_checked_at_startup(events, tmp_path):
    class LibrarySettings(ServiceSettings):
        database_url: str
        page_size: int = 20

    with pytest.raises(SettingsError) as info:
        load(LibrarySettings)
    assert "PHILOGRAPH_DATABASE_URL" in info.value.problems
    assert events.one("service.settings.invalid")["problems"] == ["PHILOGRAPH_DATABASE_URL"]

    # Сервис LLM не стартует без ключа провайдера настроенной роли.
    events.clear()
    with pytest.raises(SettingsError) as info:
        create({"PHILOGRAPH_LLM_CONFIG": str(ROOT / "config" / "llm.yaml")})
    assert "DEEPSEEK_API_KEY" in info.value.problems

    tracked = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=False
    ).stdout.split()
    assert ".env" not in tracked


@req("service-runtime", "Взаимодействие только через интерфейсы сервисов")
def test_service_boundaries_enforced_by_import_linter():
    linter = shutil.which("lint-imports") or str(Path(sys.executable).parent / "lint-imports")
    result = subprocess.run([linter], cwd=ROOT, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    # У каждого сервиса своя схема: таблицы одного сервиса не объявлены в другом.
    assert llm_store.SCHEMA != "operator"
    assert {t.schema for t in llm_store.metadata.tables.values()} == {"llm"}


@req("service-runtime", "Версионирование интерфейсов")
def test_old_interface_version_keeps_working():
    app = create_app("library", "0.2.0", Health("library", "0.2.0"))
    v1, v2 = APIRouter(prefix="/v1"), APIRouter(prefix="/v2")

    @v1.get("/chapters/{cid}")
    def chapter_v1(cid: str) -> dict:
        return {"text": "…"}

    @v2.get("/chapters/{cid}")
    def chapter_v2(cid: str) -> dict:
        return {"blocks": [{"kind": "paragraph", "text": "…"}]}

    app.include_router(v1)
    app.include_router(v2)
    from ..helpers import asgi_transport

    old = ServiceClient(
        "library", "http://library", api_version="v1", transport=asgi_transport(app)
    )
    new = ServiceClient(
        "library", "http://library", api_version="v2", transport=asgi_transport(app)
    )
    assert old.get("chapters/c1").json() == {"text": "…"}
    assert "blocks" in new.get("chapters/c1").json()


@req("service-runtime", "Таймауты между сервисами")
def test_timeouts_and_safe_retries(events):
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        raise httpx.ReadTimeout("медленно", request=request)

    client = ServiceClient(
        "search", "http://search", timeout=0.1, retries=1, transport=httpx.MockTransport(handler)
    )
    with pytest.raises(ServiceUnavailable) as info:
        client.get("search")
    assert info.value.reason == "таймаут" and calls == ["GET", "GET"]

    calls.clear()
    with pytest.raises(ServiceUnavailable):
        client.post("index")
    assert calls == ["POST"]  # операцию с побочным эффектом не повторяем
    assert [e["attempts"] for e in events.of("service.call.failed")] == [2, 1]


@req("service-runtime", "Деградация без LLM")
def test_llm_unavailable_gives_clear_message(engine_for, clock, events):
    provider = FakeProvider()
    provider.push(*[TransientProviderError("не отвечает")] * 5)
    templates = TemplateRegistry()
    templates.register(Template("answer", "Ответь.", ("question",)))
    gateway = LLMGateway(
        GatewayConfig.model_validate(CONFIG),
        {"fake": provider, "other": FakeProvider()},
        templates,
        llm_store.Store(engine_for(llm_store.migrations)),
        clock=clock,
        sleep=lambda _s: None,
    )
    client = TestClient(build_app(gateway))
    body = {
        "role": "main",
        "template": "answer",
        "caller": "assistant",
        "operation": "answer",
        "budget": "site",
        "data": {"question": "?"},
    }
    response = client.post("/v1/generate", json=body)
    assert response.status_code == 503
    assert response.json()["kind"] == "provider_unavailable"
    assert client.get("/health/live").status_code == 200
    assert events.of("llm.call.failed") and events.of("llm.call.retry")


@req("service-runtime", "Очередь задач")
def test_queue_retries_dedupes_and_keeps_failures(engine_for, clock, events):
    queue = Queue(engine_for(queue_migrations), clock, max_attempts=3, backoff_seconds=1)
    seen: list[int] = []

    @queue.handler("index")
    def index(job) -> None:
        seen.append(job.attempts)
        raise RuntimeError("индекс недоступен")

    assert queue.enqueue("index", {"source": "s1"}, key="index:s1:v2") is not None
    assert queue.enqueue("index", {"source": "s1"}, key="index:s1:v2") is None  # дубль
    for _ in range(3):
        queue.run_until_empty()
        clock.advance(seconds=10)
    assert seen == [1, 2, 3]
    failed = queue.failed()
    assert len(failed) == 1 and "индекс недоступен" in failed[0]["last_error"]
    events.assert_sequence("queue.job.retry", "queue.job.retry", "queue.job.failed")

    done: list[str] = []
    queue.handler("note")(lambda job: done.append(job.payload["v"]))
    queue.enqueue("note", {"v": "a"}, key="note:a")
    queue.run_until_empty()
    assert done == ["a"] and events.of("queue.job.done")


@req("service-runtime", "Отдельные схемы данных")
def test_migrations_apply_to_empty_database(engine_for, events):
    sets = (llm_store.migrations, operator_migrations, queue_migrations)
    engine = engine_for(*sets)
    for m in sets:
        assert m.current(engine) == m.latest()
        assert m.upgrade(engine) == []  # повторное применение ничего не делает
    applied = {(e["schema"], e["version"]) for e in events.of("db.migration.applied")}
    assert applied == {("llm", 1), ("operator", 1), ("queue", 1)}


@req("service-runtime", "Прослеживаемость требований тестами")
def test_traceability_check_detects_missing_test(tmp_path, monkeypatch, capsys):
    sys.path.insert(0, str(ROOT / "scripts"))
    import check_traceability as tr

    assert tr.main() == 0  # в репозитории у реализованных требований тесты есть
    capsys.readouterr()

    spec = tmp_path / "openspec" / "changes" / "c1" / "specs" / "demo" / "spec.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("### Requirement: Покрытое\n\n### Requirement: Забытое\n", encoding="utf-8")
    (tmp_path / "openspec" / "traceability.yaml").write_text("enforce: [demo]\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_demo.py").write_text(
        'import pytest\n\n@pytest.mark.req("demo", "Покрытое")\ndef test_x():\n    pass\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(tr, "ROOT", tmp_path)
    assert tr.main() == 1
    output = capsys.readouterr().out
    assert "Забытое" in output and "1 из 2" in output
