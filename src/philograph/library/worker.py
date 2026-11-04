"""Задачи библиотеки в очереди: обработка источника, плановая проверка, передача событий."""

from __future__ import annotations

from philograph.library.processing import Pipeline
from philograph.platform.queue import Job, Queue

PROCESS = "library.process"
CHECK_UPDATES = "library.check_updates"


def register(queue: Queue, pipeline: Pipeline) -> None:
    @queue.handler(PROCESS)
    def process(job: Job) -> None:
        pipeline.start(
            job.payload.get("actor", "queue"),
            job.payload["source_id"],
            limit_usd=job.payload.get("limit_usd"),
        )
        pipeline.dispatch_outbox(queue)

    @queue.handler(CHECK_UPDATES)
    def check_updates(job: Job) -> None:
        pipeline.check_updates("scheduler")
        pipeline.dispatch_outbox(queue)
