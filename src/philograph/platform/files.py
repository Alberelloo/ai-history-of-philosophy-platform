"""Файловое хранилище с адресацией по отпечатку содержимого.

Одинаковый файл хранится один раз. Интерфейс простой, чтобы позже заменить локальный диск
S3-совместимым хранилищем без изменений в сервисах.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


def fingerprint(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class FileStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, digest: str) -> Path:
        return self.root / digest[:2] / digest

    def put(self, data: bytes) -> str:
        digest = fingerprint(data)
        path = self._path(digest)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.replace(path)
        return digest

    def get(self, digest: str) -> bytes:
        return self._path(digest).read_bytes()

    def exists(self, digest: str) -> bool:
        return self._path(digest).exists()

    def delete(self, digest: str) -> None:
        self._path(digest).unlink(missing_ok=True)
