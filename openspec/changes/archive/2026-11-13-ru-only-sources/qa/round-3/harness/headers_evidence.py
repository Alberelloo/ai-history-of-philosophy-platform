"""Точное доказательство F-4: сколько заголовков Cache-Control уходит клиенту.

Поднимает те же поддельные сервисы и один шлюз, что и ``live_checks.py``, и печатает
сырые заголовки ответа (Playwright ``headers_array`` — с повторами).
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[6]
QA = Path(__file__).resolve().parents[1]
HARNESS = Path(__file__).resolve().parent
LOGS = HARNESS / "logs"

sys.path.insert(0, str(ROOT / "src"))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start(module: str, port: int, env: dict[str, str], name: str) -> subprocess.Popen:
    log = open(LOGS / f"{name}-headers.log", "w", encoding="utf-8")  # noqa: SIM115
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", module, "--port", str(port), "--log-level", "warning"],
        cwd=ROOT,
        env={
            **os.environ,
            **env,
            "PYTHONUTF8": "1",
            "PYTHONPATH": os.pathsep.join([str(ROOT / "src"), str(HARNESS)]),
        },
        stdout=log,
        stderr=subprocess.STDOUT,
    )


def wait(url: str) -> None:
    for _ in range(300):
        try:
            httpx.get(f"{url}/health/live", timeout=1)
            return
        except httpx.HTTPError:
            time.sleep(0.2)
    raise RuntimeError(url)


def main() -> None:
    fake_port, gateway_port = free_port(), free_port()
    processes = [
        start("fake_services:app", fake_port, {}, "fake"),
        start(
            "philograph.gateway.app:app",
            gateway_port,
            {
                "PHILOGRAPH_LIBRARY_URL": f"http://127.0.0.1:{fake_port}/library",
                "PHILOGRAPH_ASSISTANT_URL": f"http://127.0.0.1:{fake_port}/assistant",
                "PHILOGRAPH_REGION_HEADER": "CF-IPCountry",
                "PHILOGRAPH_TRUSTED_PROXY": "1",
                "PHILOGRAPH_VISITOR_SECRET": "round-3",
                "PHILOGRAPH_WEB_ROOT": str(ROOT / "web" / "dist"),
            },
            "gateway",
        ),
    ]
    gateway = f"http://127.0.0.1:{gateway_port}"
    try:
        wait(gateway)
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            context = browser.new_context(extra_http_headers={"CF-IPCountry": "RU"})
            page = context.new_page()
            response = page.goto(f"{gateway}/api/v1/sources", wait_until="load")
            raw = [
                [item["name"], item["value"]] for item in response.headers_array()
                if item["name"].lower() in {"cache-control", "vary", "content-type"}
            ]
            print(json.dumps(raw, ensure_ascii=False, indent=1))
            duplicates = [k for k, _ in raw if k.lower() == "cache-control"]
            print(f"заголовков Cache-Control в ответе: {len(duplicates)}")
            browser.close()
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                process.wait(10)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    main()
