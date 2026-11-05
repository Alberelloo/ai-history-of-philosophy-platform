"""Весь продукт одной командой без Docker: ``python scripts/dev_stack.py``.

Каждый сервис — отдельный процесс, как в работе: сервис LLM, библиотека, поиск, ассистент,
исполнитель очереди и шлюз, который отдаёт клиент. База — файловая SQLite, Qdrant — внутри
процесса поиска, модели — демо (``config/llm.demo.yaml``). Журналы сервисов — строки JSON в
``<каталог>/logs/<сервис>.log``. Перед запуском соберите клиент: ``cd web && npm run build``.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
DEMO_OPERATOR_PASSWORD = "demo-operator"
DEMO_OPERATOR_HASH = (
    "pbkdf2_sha256$1000$64656d6f2d73616c74$"
    "907c04102bee49f460c2bee8e69686fd19c37d7fbc0fe866c4a0fb4a84fb029d"
)  # hash_password("demo-operator", salt=b"demo-salt", iterations=1000)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@dataclass
class Stack:
    url: str
    data: Path
    processes: dict[str, subprocess.Popen] = field(default_factory=dict)

    def logs(self, service: str) -> list[dict]:
        path = self.data / "logs" / f"{service}.log"
        events = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("{"):
                with contextlib.suppress(json.JSONDecodeError):
                    events.append(json.loads(line))
        return events

    def stop(self) -> None:
        for process in self.processes.values():
            process.terminate()
        for process in self.processes.values():
            try:
                process.wait(10)
            except subprocess.TimeoutExpired:
                process.kill()


def _wait(url: str, seconds: float = 60) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            if httpx.get(url, timeout=2).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.3)
    raise RuntimeError(f"не поднялся: {url}")


def start(data: Path, port: int | None = None) -> Stack:
    data.mkdir(parents=True, exist_ok=True)
    (data / "logs").mkdir(exist_ok=True)
    ports = {name: free_port() for name in ("llm", "library", "search", "assistant", "knowledge")}
    ports["gateway"] = port or free_port()
    db = f"sqlite:///{(data / 'stack.db').as_posix()}"
    env = {
        **os.environ,
        "PYTHONUTF8": "1",
        "PHILOGRAPH_DATABASE_URL": db,
        "PHILOGRAPH_FILES_ROOT": str(data / "files"),
        "PHILOGRAPH_LLM_CONFIG": str(ROOT / "config" / "llm.demo.yaml"),
        "PHILOGRAPH_LLM_URL": f"http://127.0.0.1:{ports['llm']}",
        "PHILOGRAPH_LIBRARY_URL": f"http://127.0.0.1:{ports['library']}",
        "PHILOGRAPH_SEARCH_URL": f"http://127.0.0.1:{ports['search']}",
        "PHILOGRAPH_ASSISTANT_URL": f"http://127.0.0.1:{ports['assistant']}",
        "PHILOGRAPH_QDRANT_PATH": str(data / "qdrant"),
        "PHILOGRAPH_EMBEDDING_MODEL": "demo-embeddings",
        "PHILOGRAPH_EMBEDDING_DIMENSION": "8",
        "PHILOGRAPH_WEB_ROOT": str(ROOT / "web" / "dist"),
        "PHILOGRAPH_VISITOR_SECRET": "dev-stack",
        "PHILOGRAPH_KNOWLEDGE_SERVICE": "1",
        "PHILOGRAPH_KNOWLEDGE_URL": f"http://127.0.0.1:{ports['knowledge']}",
        # Пароль оператора демо-стенда: demo-operator.
        "PHILOGRAPH_OPERATOR_PASSWORD_HASH": DEMO_OPERATOR_HASH,
    }
    apps = {
        "llm": "philograph.llm.main:app",
        "library": "philograph.library.main:app",
        "search": "philograph.search.main:app",
        "assistant": "philograph.assistant.main:app",
        "gateway": "philograph.gateway.app:app",
        "knowledge": "philograph.knowledge.main:app",
    }
    stack = Stack(f"http://127.0.0.1:{ports['gateway']}", data)

    def run(name: str, args: list[str]) -> None:
        # Файл журнала живёт столько же, сколько процесс сервиса.
        log = open(data / "logs" / f"{name}.log", "w", encoding="utf-8")  # noqa: SIM115
        stack.processes[name] = subprocess.Popen(
            args, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT
        )

    for name in ("llm", "library"):
        run(
            name,
            [
                sys.executable,
                "-m",
                "uvicorn",
                apps[name],
                "--port",
                str(ports[name]),
                "--log-level",
                "warning",
            ],
        )
    for name in ("llm", "library"):
        _wait(f"http://127.0.0.1:{ports[name]}/health/ready")
    with open(data / "logs" / "seed.log", "w", encoding="utf-8") as seed_log:
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "seed_demo.py")],
            cwd=ROOT,
            env=env,
            check=True,
            stdout=seed_log,
            stderr=subprocess.STDOUT,
        )
    for name in ("search", "assistant", "gateway", "knowledge"):
        run(
            name,
            [
                sys.executable,
                "-m",
                "uvicorn",
                apps[name],
                "--port",
                str(ports[name]),
                "--log-level",
                "warning",
            ],
        )
    run("worker", [sys.executable, "-m", "philograph.worker"])
    for name in ("search", "assistant", "gateway", "knowledge"):
        _wait(f"http://127.0.0.1:{ports[name]}/health/ready")
    # Индексацию делает сервис поиска из очереди: ждём, пока поиск начнёт находить.
    deadline = time.time() + 60
    while time.time() < deadline:
        found = httpx.post(
            f"http://127.0.0.1:{ports['search']}/v1/search", json={"query": "индукции"}, timeout=5
        ).json()
        if found["results"]:
            return stack
        time.sleep(0.5)
    stack.stop()
    raise RuntimeError("индексация не завершилась")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / ".stack")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    stack = start(args.data, args.port)
    print(f"PhiloGraph: {stack.url}  (журналы: {args.data / 'logs'}; остановка — Ctrl+C)")
    try:
        while all(p.poll() is None for p in stack.processes.values()):
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        stack.stop()


if __name__ == "__main__":
    main()
