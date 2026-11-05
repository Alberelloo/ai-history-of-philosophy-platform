"""Сквозные тесты: живой продукт из отдельных процессов и настоящий браузер.

Стенд: если задан ``PHILOGRAPH_E2E_URL`` — уже поднятый (в CI это ``docker compose`` с
``compose.e2e.yaml``), журналы читаются через ``docker compose logs``. Иначе тест сам поднимает
``scripts/dev_stack.py`` во временном каталоге. Тест проходит по сайту как человек: кликает,
выделяет, ждёт ответа — и проверяет журналы сервисов, через которые прошёл запрос.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))


class ComposeStack:
    def __init__(self, url: str) -> None:
        self.url = url

    def logs(self, service: str) -> list[dict]:
        out = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                "compose.yaml",
                "-f",
                "compose.e2e.yaml",
                "logs",
                "--no-color",
                "--no-log-prefix",
                service,
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        ).stdout
        events = []
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("{"):
                with contextlib.suppress(json.JSONDecodeError):
                    events.append(json.loads(line))
        return events


@pytest.fixture(scope="session")
def stack(tmp_path_factory):
    if os.environ.get("PHILOGRAPH_E2E_URL"):
        compose = ComposeStack(os.environ["PHILOGRAPH_E2E_URL"])
        # Поиск индексирует демо-источники из очереди: ждём оба события публикации.
        wait_logs(compose, "search", lambda e: e["event"] == "search.index.event", 120)

        def indexed():
            return len([e for e in compose.logs("search") if e["event"] == "search.index.event"])

        import time

        deadline = time.time() + 120
        while indexed() < 2 and time.time() < deadline:
            time.sleep(1)
        yield compose
        return
    if not (ROOT / "web" / "dist" / "index.html").exists():
        pytest.skip("клиент не собран: npm run build в web/")
    import dev_stack

    running = dev_stack.start(tmp_path_factory.mktemp("stack"))
    yield running
    running.stop()


@pytest.fixture
def page(browser, stack):
    context = browser.new_context(
        permissions=["clipboard-read", "clipboard-write"], viewport={"width": 1400, "height": 900}
    )
    page = context.new_page()
    page.set_default_timeout(15000)
    yield page
    context.close()


def wait_logs(stack, service: str, predicate, seconds: float = 10.0) -> list[dict]:
    """Журнал пишется асинхронно: ждём нужное событие, а не читаем один раз."""
    import time

    deadline = time.time() + seconds
    while True:
        found = [e for e in stack.logs(service) if predicate(e)]
        if found or time.time() > deadline:
            return found
        time.sleep(0.3)
