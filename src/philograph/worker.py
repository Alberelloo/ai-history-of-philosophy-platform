"""Исполнитель очереди: ``python -m philograph.worker``.

Берёт задачи из очереди и выполняет их по одной; несколько исполнителей можно запустить
параллельно или вынести на отдельную машину — сервисы для читателей при этом не меняются.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from philograph import __version__
from philograph.library import schema as library_schema
from philograph.library import worker as library_worker
from philograph.library.catalog.fetcher import CatalogFetch, Fetcher
from philograph.library.processing import Pipeline, PipelineSettings
from philograph.library.registry import Registry
from philograph.operator.access import migrations as operator_migrations
from philograph.platform import events
from philograph.platform.db import make_engine
from philograph.platform.files import FileStore
from philograph.platform.lifecycle import running
from philograph.platform.queue import Queue
from philograph.platform.queue import migrations as queue_migrations


def main() -> None:
    events.configure(sinks=[events.json_sink()])
    sets = (library_schema.migrations, operator_migrations, queue_migrations)
    engine = make_engine(os.environ["PHILOGRAPH_DATABASE_URL"], [m.schema for m in sets])
    for m in sets:
        m.upgrade(engine)
    queue = Queue(engine)
    files = FileStore(Path(os.environ["PHILOGRAPH_FILES_ROOT"]))
    # Бережная загрузка: User-Agent проекта, robots.txt, условные запросы, учёт неудач.
    pipeline = Pipeline(
        Registry(engine),
        files,
        CatalogFetch(engine, Fetcher(), files),
        settings=PipelineSettings(fetch_retries=0),
    )
    library_worker.register(queue, pipeline)
    with running("worker", __version__):
        while True:
            if not queue.run_once():
                time.sleep(1.0)


if __name__ == "__main__":
    main()
