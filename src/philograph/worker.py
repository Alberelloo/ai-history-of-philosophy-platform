"""Исполнитель очереди: ``python -m philograph.worker``.

Берёт задачи из очереди и выполняет их по одной; несколько исполнителей можно запустить
параллельно или вынести на отдельную машину — сервисы для читателей при этом не меняются.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from philograph.library import schema as library_schema
from philograph.library import worker as library_worker
from philograph.library.processing import Pipeline
from philograph.library.registry import Registry
from philograph.operator.access import migrations as operator_migrations
from philograph.platform import events
from philograph.platform.db import make_engine
from philograph.platform.files import FileStore
from philograph.platform.queue import Queue
from philograph.platform.queue import migrations as queue_migrations


def _fetch(spec: dict) -> bytes:
    if "path" in spec:
        return Path(spec["path"]).read_bytes()
    import httpx

    response = httpx.get(spec["url"], timeout=60, follow_redirects=True)
    if response.status_code != 200:
        raise OSError(f"ответ {response.status_code}")
    return response.content


def main() -> None:
    events.configure(sinks=[events.json_sink()])
    sets = (library_schema.migrations, operator_migrations, queue_migrations)
    engine = make_engine(os.environ["PHILOGRAPH_DATABASE_URL"], [m.schema for m in sets])
    for m in sets:
        m.upgrade(engine)
    queue = Queue(engine)
    pipeline = Pipeline(
        Registry(engine), FileStore(Path(os.environ["PHILOGRAPH_FILES_ROOT"])), _fetch
    )
    library_worker.register(queue, pipeline)
    if os.environ.get("PHILOGRAPH_QDRANT_URL"):
        from philograph.search.app import subscribe
        from philograph.search.main import components

        subscribe(queue, components(dict(os.environ))[0])
    while True:
        if not queue.run_once():
            time.sleep(1.0)


if __name__ == "__main__":
    main()
