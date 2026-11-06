"""Celery configuration (Redis broker) and the JobQueue adapters.

The API only *sends* tasks by name, so it never imports worker code.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from celery import Celery
from celery.schedules import crontab

from lodestar.config import Settings

RUN_TASK = "lodestar.run_pipeline"
RESUME_TASK = "lodestar.resume_pipeline"
DAILY_TASK = "lodestar.daily_reports"
SCAN_TASK = "lodestar.run_scan"
PAPER_TASK = "lodestar.paper_tick"


def create_celery(settings: Settings) -> Celery:
    app = Celery("lodestar", broker=settings.celery_broker_url or settings.redis_url)
    app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        task_ignore_result=True,
        task_acks_late=True,  # a crashed worker's task is redelivered...
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,  # ...and long pipeline tasks are not hoarded
        task_time_limit=900,
        task_soft_time_limit=840,
        broker_connection_retry_on_startup=True,
        timezone="UTC",
        enable_utc=True,
        beat_schedule={
            "daily-reports": {
                "task": DAILY_TASK,
                "schedule": crontab(hour=settings.daily_report_hour_utc, minute=0),
            },
            # Paper positions advance on completed daily bars; hourly keeps the account current after midnight UTC.
            "paper-tick": {"task": PAPER_TASK, "schedule": crontab(minute=10)},
        },
    )
    return app


class CeleryJobQueue:
    def __init__(self, app: Celery) -> None:
        self._app = app

    async def enqueue_run(self, run_id: UUID) -> None:
        # task_id makes redelivery of the same run idempotent at the broker level.
        await asyncio.to_thread(self._app.send_task, RUN_TASK, args=[str(run_id)], task_id=f"run-{run_id}")

    async def enqueue_resume(self, run_id: UUID, decision: dict[str, Any]) -> None:
        await asyncio.to_thread(self._app.send_task, RESUME_TASK, args=[str(run_id), decision])

    async def enqueue_scan(self, scan_id: UUID) -> None:
        await asyncio.to_thread(self._app.send_task, SCAN_TASK, args=[str(scan_id)], task_id=f"scan-{scan_id}")


class InlineJobQueue:
    """Runs jobs in-process. Used by tests and the seed command (no broker needed)."""

    def __init__(self, *, background: bool = False) -> None:
        self._run: Callable[[UUID], Awaitable[None]] | None = None
        self._resume: Callable[[UUID, dict[str, Any]], Awaitable[None]] | None = None
        self._scan: Callable[[UUID], Awaitable[None]] | None = None
        self._background = background
        self._tasks: set[asyncio.Task[None]] = set()

    def bind(
        self,
        run: Callable[[UUID], Awaitable[None]],
        resume: Callable[[UUID, dict[str, Any]], Awaitable[None]],
        scan: Callable[[UUID], Awaitable[None]] | None = None,
    ) -> None:
        self._run, self._resume = run, resume
        if scan is not None:
            self._scan = scan

    async def _dispatch(self, aw: Awaitable[None]) -> None:
        if self._background:
            task = asyncio.ensure_future(aw)
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        else:
            await aw

    async def enqueue_run(self, run_id: UUID) -> None:
        if self._run is not None:
            await self._dispatch(self._run(run_id))

    async def enqueue_resume(self, run_id: UUID, decision: dict[str, Any]) -> None:
        if self._resume is not None:
            await self._dispatch(self._resume(run_id, decision))

    async def enqueue_scan(self, scan_id: UUID) -> None:
        if self._scan is not None:
            await self._dispatch(self._scan(scan_id))

    async def drain(self) -> None:
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)
