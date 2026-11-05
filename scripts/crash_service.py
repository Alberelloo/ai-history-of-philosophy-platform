"""Проверка автоматического перезапуска: роняет процесс сервиса внутри контейнера.

``docker compose exec <сервис> python scripts/crash_service.py`` — процесс uvicorn или
исполнителя получает SIGKILL и не успевает остановиться штатно, как при нехватке памяти.
"""

from __future__ import annotations

import os
import signal
from pathlib import Path


def main() -> None:
    me = os.getpid()
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit() or int(proc.name) in (1, me):
            continue
        cmdline = (proc / "cmdline").read_bytes().replace(b"\0", b" ")
        if b"uvicorn" in cmdline or b"philograph." in cmdline:
            os.kill(int(proc.name), signal.SIGKILL)
            print(f"остановлен процесс {proc.name}")
            return
    raise SystemExit("процесс сервиса не найден")


if __name__ == "__main__":
    main()
