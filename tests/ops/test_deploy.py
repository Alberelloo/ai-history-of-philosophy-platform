"""Требования спецификации deployment.

Конфигурация публичного сервера проверяется так, как её видит Docker Compose (``docker
compose config``), обновление и откат — сценарием развёртывания с подменённым исполнителем
команд. Если задан ``PHILOGRAPH_DEPLOY_URL`` (стенд с Caddy), проверяется и живой HTTPS.
"""

from __future__ import annotations

import inspect
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from philograph.ops import migrate
from philograph.platform.health import Health
from philograph.platform.lifecycle import running
from philograph.platform.web import create_app

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import deploy

req = pytest.mark.req
DP = "deployment"
ROOT = Path(__file__).resolve().parents[2]
DOCKER_WINDOWS = Path("C:/Program Files/Docker/Docker/resources/bin/docker.exe")


@pytest.fixture(scope="module")
def prod_config(tmp_path_factory) -> dict:
    docker = shutil.which("docker") or (str(DOCKER_WINDOWS) if DOCKER_WINDOWS.exists() else None)
    if docker is None:
        pytest.skip("нет Docker: конфигурацию compose проверить нечем")
    where = tmp_path_factory.mktemp("compose")
    for name in ("compose.yaml", "compose.prod.yaml"):
        shutil.copy(ROOT / name, where / name)
    (where / ".env").write_text(
        "POSTGRES_PASSWORD=x\nPHILOGRAPH_VISITOR_SECRET=y\nPHILOGRAPH_DOMAIN=philograph.example.org\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            docker,
            "compose",
            "-f",
            "compose.yaml",
            "-f",
            "compose.prod.yaml",
            "config",
            "--format",
            "json",
        ],
        cwd=where,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        # Переменные окружения перекрыли бы .env: конфигурация — только из файлов.
        env={k: v for k, v in os.environ.items() if not k.startswith(("PHILOGRAPH_", "POSTGRES_"))},
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def published(config: dict) -> dict[str, list[int]]:
    return {
        name: sorted(int(p["published"]) for p in service.get("ports", []))
        for name, service in config["services"].items()
        if service.get("ports")
    }


@req(DP, "Публичный адрес по HTTPS")
def test_https_only_with_automatic_certificate(prod_config):
    caddy = prod_config["services"]["caddy"]
    assert caddy["environment"]["PHILOGRAPH_DOMAIN"] == "philograph.example.org"
    caddyfile = (ROOT / "deploy" / "Caddyfile").read_text(encoding="utf-8")
    # Сайт по имени домена: Caddy сам выпускает сертификат и перенаправляет HTTP на HTTPS.
    assert re.search(r"^\{\$PHILOGRAPH_DOMAIN\} \{", caddyfile, re.M)
    assert "reverse_proxy gateway:8080" in caddyfile and "auto_https off" not in caddyfile
    url = os.environ.get("PHILOGRAPH_DEPLOY_URL")  # например https://localhost
    if url:
        plain = httpx.get(url.replace("https://", "http://"), follow_redirects=False)
        assert plain.status_code in (301, 308) and plain.headers["location"].startswith("https://")
        page = httpx.get(url, verify=False)
        assert page.status_code == 200 and '<div id="root">' in page.text


@req(DP, "Внутренние части не видны снаружи")
def test_only_http_and_https_published(prod_config):
    assert published(prod_config) == {"caddy": [80, 443]}
    # Внутренние адреса и метрики не видны и через шлюз.
    client = TestClient(create_app("gateway", "1.0", Health("gateway", "1.0")))
    assert client.get("/internal/metrics").status_code == 404


def stack_compose() -> list[str] | None:
    """Команда compose работающего стенда (``PHILOGRAPH_DEPLOY_COMPOSE`` — его файлы)."""
    files = os.environ.get("PHILOGRAPH_DEPLOY_COMPOSE")
    docker = shutil.which("docker") or (str(DOCKER_WINDOWS) if DOCKER_WINDOWS.exists() else None)
    return [docker, "compose", *files.split()] if files and docker else None


@req(DP, "Автоматический перезапуск")
def test_restart_policy_and_restart_event(prod_config, tmp_path, events):
    long_running = {
        n: s for n, s in prod_config["services"].items() if n not in ("migrate", "seed")
    }
    assert {s.get("restart") for s in long_running.values()} == {"unless-stopped"}
    with running("assistant", "1.4.0", tmp_path):
        pass  # штатная остановка убирает маркер
    assert not events.of("service.restarted")
    marker = tmp_path / "assistant.running"
    marker.write_text("1.4.0", encoding="utf-8")  # процесс упал, маркер остался
    with running("assistant", "1.4.0", tmp_path):
        assert marker.exists()
    restarted = events.one("service.restarted")
    assert restarted["previous_version"] == "1.4.0" and restarted["service"] == "assistant"
    assert [e["restarted"] for e in events.of("service.started")] == [False, True]
    compose = stack_compose()
    if compose:  # живой стенд: процесс ассистента падает, Docker поднимает его снова

        def restarts() -> int:
            logs = subprocess.run(
                [*compose, "logs", "--no-color", "assistant"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            ).stdout
            return logs.count('"service.restarted"')

        before = restarts()
        crashed = subprocess.run(
            [*compose, "exec", "-T", "assistant", "python", "scripts/crash_service.py"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        # Сессия exec закрывается вместе с упавшим процессом: код 137 ожидаем.
        assert "остановлен процесс" in crashed.stdout, crashed.stderr
        deadline = time.time() + 90
        while time.time() < deadline and restarts() == before:
            time.sleep(3)
        assert restarts() == before + 1


class Recorder:
    def __init__(self, fail_on: str | None = None) -> None:
        self.commands: list[tuple[list[str], dict[str, str]]] = []
        self.fail_on = fail_on

    def __call__(self, command: list[str], env: dict[str, str]) -> int:
        self.commands.append((command, env))
        return 1 if self.fail_on and self.fail_on in command else 0

    def steps(self) -> list[str]:
        return [next(a for a in ("build", "run", "up") if a in c) for c, _ in self.commands]


@req(DP, "Обновление с миграциями")
def test_update_applies_migrations_first(tmp_path, database_url, events):
    state = tmp_path / "state.json"
    deploy.write_state({"current": "1.4.0", "previous": "1.3.0"}, state)
    failing = Recorder(fail_on="migrate")
    assert deploy.update("1.5.0", failing, state) == 1
    assert failing.steps() == ["build", "run"]  # сервисы не перезапускались
    assert deploy.read_state(state)["current"] == "1.4.0"  # работает прежняя версия
    ok = Recorder()
    assert deploy.update("1.5.0", ok, state) == 0
    assert ok.steps() == ["build", "run", "up"]
    assert all(env["PHILOGRAPH_VERSION"] == "1.5.0" for _, env in ok.commands)
    assert "--wait" in ok.commands[-1][0]
    assert deploy.read_state(state) == {"current": "1.5.0", "previous": "1.4.0"}
    # Команда миграций применяет схемы всех сервисов и пишет итог в журнал.
    applied = migrate.upgrade_all(database_url)
    assert set(applied) == {m.schema for m in migrate.all_migrations()}
    assert events.of("ops.migrations.applied")


@req(DP, "Откат обновления")
def test_rollback_one_command_and_additive_migrations(tmp_path):
    state = tmp_path / "state.json"
    deploy.write_state({"current": "1.5.0", "previous": "1.4.0"}, state)
    runner = Recorder()
    assert deploy.rollback(runner, state) == 0
    assert runner.commands[0][1] == {"PHILOGRAPH_VERSION": "1.4.0"}
    assert deploy.read_state(state) == {"current": "1.4.0", "previous": "1.5.0"}
    deploy.write_state({"current": "1.4.0", "previous": None}, state)
    assert deploy.rollback(Recorder(), state) == 1  # откатываться некуда
    # Прежний код работает с новой схемой: миграции только добавляют.
    forbidden = re.compile(r"\b(DROP|RENAME|drop_column|alter_column|drop_table)\b", re.I)
    for m in migrate.all_migrations():
        for item in m._items:
            source = inspect.getsource(item.apply) if item.apply.__name__ != "apply" else ""
            assert not forbidden.search(source), (
                f"{m.schema}:{item.version} удаляет или переименовывает"
            )


@req(DP, "Версия в журнале")
def test_version_at_start_and_in_health(events):
    app = create_app("search", "1.5.0", Health("search", "1.5.0"))
    with TestClient(app) as client:
        started = events.one("service.started")
        assert started["version"] == "1.5.0" and started["service"] == "search"
        assert client.get("/health/live").json()["version"] == "1.5.0"
        assert client.get("/health/ready").json()["version"] == "1.5.0"
    assert events.one("service.stopped")["version"] == "1.5.0"
