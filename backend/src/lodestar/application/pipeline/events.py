"""Pipeline events: every step's status, inputs, outputs and evidence ids.

Each event is persisted (the audit trail behind the Pipeline screen) and then
published to the live event bus (SSE subscribers). Sequence numbers are
per-run and strictly increasing, so a reconnecting client resumes exactly
where it left off (``Last-Event-ID``).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from enum import StrEnum
from typing import Any
from uuid import UUID

import structlog

from lodestar.application.ports import Clock, EventRecord, RunEventBus, UnitOfWork
from lodestar.application.serialization import to_jsonable

log = structlog.get_logger(__name__)

MAX_STRING = 400
MAX_ITEMS = 40


class EventType(StrEnum):
    RUN = "run"  # run status changed
    STEP = "step"  # a pipeline step started / completed / failed / is waiting
    TOOL = "tool_call"  # one ReAct step inside an analyst
    NOTE = "note"  # informational (repair loop, dropped claims, data gaps)


class StepStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    WAITING = "waiting"


def compact(value: Any, depth: int = 0) -> Any:
    """Bound payload size: events are for humans, not a data dump."""
    value = to_jsonable(value)
    if isinstance(value, str):
        return value if len(value) <= MAX_STRING else value[: MAX_STRING - 1] + "…"
    if isinstance(value, list):
        items = [compact(v, depth + 1) for v in value[:MAX_ITEMS]]
        if len(value) > MAX_ITEMS:
            items.append(f"… {len(value) - MAX_ITEMS} more")
        return items
    if isinstance(value, dict):
        if depth > 4:
            return "{…}"
        return {str(k): compact(v, depth + 1) for k, v in value.items()}
    return value


def event_to_dict(e: EventRecord) -> dict[str, Any]:
    return {
        "run_id": str(e.run_id),
        "seq": e.seq,
        "ts": e.ts.isoformat(),
        "step": e.step,
        "type": e.type,
        "status": e.status,
        "payload": e.payload,
    }


class RunEventRecorder:
    """Persists then publishes events. Sequence numbers come from the database, so the API
    (queue, approve) and the worker (every step) can both write to the same run safely."""

    def __init__(self, uow: Callable[[], UnitOfWork], bus: RunEventBus, clock: Clock) -> None:
        self._uow, self._bus, self._clock = uow, bus, clock
        self._locks: dict[UUID, asyncio.Lock] = {}

    async def emit(
        self,
        run_id: UUID,
        *,
        step: str,
        type: EventType,
        status: str | None = None,
        **payload: Any,
    ) -> dict[str, Any]:
        lock = self._locks.setdefault(run_id, asyncio.Lock())
        # Parallel analysts in this process take turns; other processes retry inside the store.
        async with lock, self._uow() as uow:
            record = await uow.events.append(
                run_id,
                ts=self._clock.now(),
                step=step,
                type=type.value,
                status=status,
                payload=compact({k: v for k, v in payload.items() if v is not None}),
            )
            await uow.commit()
        event = event_to_dict(record)
        try:
            await self._bus.publish(run_id, event)
        except Exception as exc:  # noqa: BLE001 - live fan-out is best effort; the DB copy is authoritative
            log.warning("event_publish_failed", run_id=str(run_id), error=repr(exc))
        return event

    def forget(self, run_id: UUID) -> None:
        """Drop the per-run lock once a run reaches a resting state (bounded memory)."""
        self._locks.pop(run_id, None)
