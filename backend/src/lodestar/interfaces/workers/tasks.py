"""Celery worker tasks: pipeline runs, approval resumes and the daily schedule.

    celery -A lodestar.interfaces.workers.tasks worker --concurrency=2
    celery -A lodestar.interfaces.workers.tasks beat

The pipeline is async; each worker process owns one long-lived event loop and
one container (DB pool, Redis, HTTP client, LangGraph checkpointer), created
lazily on its first task and reused for every task after that.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar
from uuid import UUID

import structlog

from lodestar.config import get_settings
from lodestar.infrastructure.container import Container, build_container, scan_runner
from lodestar.infrastructure.observability.logging import configure_logging
from lodestar.infrastructure.queue.celery_app import (
    DAILY_TASK,
    PAPER_TASK,
    RESUME_TASK,
    RUN_TASK,
    SCAN_TASK,
    create_celery,
)

log = structlog.get_logger(__name__)
settings = get_settings()
app = create_celery(settings)
T = TypeVar("T")


class _Runtime:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._container: Container | None = None
        self._lock = threading.Lock()

    def run(self, work: Callable[[Container], Awaitable[T]]) -> T:
        with self._lock:
            if self._loop is None:
                configure_logging(settings.log_level, json_logs=settings.is_production)
                self._loop = asyncio.new_event_loop()
            if self._container is None:
                self._container = self._loop.run_until_complete(build_container(settings, with_workflow=True))
            return self._loop.run_until_complete(work(self._container))


runtime = _Runtime()


@app.task(name=RUN_TASK, acks_late=True)
def run_pipeline(run_id: str) -> None:
    structlog.contextvars.bind_contextvars(run_id=run_id)
    log.info("pipeline_task_started")
    runtime.run(lambda c: c.pipeline.execute(UUID(run_id)))
    log.info("pipeline_task_finished")


@app.task(name=RESUME_TASK, acks_late=True)
def resume_pipeline(run_id: str, decision: dict[str, Any]) -> None:
    structlog.contextvars.bind_contextvars(run_id=run_id)
    runtime.run(lambda c: c.pipeline.resume(UUID(run_id), decision))


@app.task(name=DAILY_TASK)
def daily_reports() -> int:
    queued = runtime.run(lambda c: c.pipeline.queue_daily())
    log.info("daily_reports_queued", count=queued)
    return queued


@app.task(name=SCAN_TASK, acks_late=True)
def run_scan(scan_id: str) -> None:
    structlog.contextvars.bind_contextvars(scan_id=scan_id)
    runtime.run(lambda c: scan_runner(c)(UUID(scan_id)))


async def _paper_tick(c: Container) -> int:
    assert c.paper is not None  # noqa: S101 - wired by the container
    return await c.paper.tick_all()


@app.task(name=PAPER_TASK)
def paper_tick() -> int:
    """Advance every paper account on newly completed daily bars (fake money only)."""
    accounts = runtime.run(_paper_tick)
    log.info("paper_tick", accounts=accounts)
    return accounts
