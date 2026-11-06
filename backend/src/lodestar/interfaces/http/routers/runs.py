"""Pipeline runs: history, detail and the live Server-Sent Events stream."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import StreamingResponse

from lodestar.domain.models import RunStatus
from lodestar.interfaces.http.deps import ContainerDep, PrincipalDep, rate_limit

router = APIRouter(tags=["pipeline"])

# Statuses at which the live stream closes; the client reopens it after approving.
RESTING = {RunStatus.AWAITING_APPROVAL, RunStatus.APPROVED, RunStatus.REJECTED, RunStatus.FAILED}
HEARTBEAT_SECONDS = 15.0
MAX_STREAM_SECONDS = 15 * 60


def sse(event: dict[str, Any]) -> str:
    return f"id: {event['seq']}\nevent: {event['type']}\ndata: {json.dumps(event, separators=(',', ':'))}\n\n"


@router.get("/runs", dependencies=[Depends(rate_limit("api"))])
async def list_runs(
    _: PrincipalDep,
    c: ContainerDep,
    asset_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[dict[str, Any]]:
    return await c.pipeline.list_runs(asset_id=asset_id, limit=limit)


@router.get("/runs/{run_id}", dependencies=[Depends(rate_limit("api"))])
async def get_run(run_id: UUID, _: PrincipalDep, c: ContainerDep) -> dict[str, Any]:
    return await c.pipeline.get(run_id)


@router.get("/runs/{run_id}/events")
async def stream_events(
    run_id: UUID,
    request: Request,
    _: PrincipalDep,
    c: ContainerDep,
    after: Annotated[int, Query(ge=0)] = 0,
    last_event_id: Annotated[str | None, Header()] = None,
) -> StreamingResponse:
    """SSE: replay persisted events after `after` (or Last-Event-ID), then follow live until the run rests."""
    start_after = int(last_event_id) if last_event_id and last_event_id.isdigit() else after
    await c.pipeline.status(run_id)  # 404 before the stream starts

    async def stream() -> AsyncIterator[str]:
        last = start_after
        yield "retry: 3000\n\n"
        for past in await c.pipeline.events_after(run_id, last):
            yield sse(past)
            last = past["seq"]
        if await c.pipeline.status(run_id) in RESTING:
            yield "event: end\ndata: {}\n\n"
            return
        deadline = time.monotonic() + MAX_STREAM_SECONDS
        async for event in c.bus.tail(run_id, after_seq=last, idle_timeout=HEARTBEAT_SECONDS):
            if await request.is_disconnected() or time.monotonic() > deadline:
                return
            if event is None:
                # Heartbeat; also catch up from the database in case the live bus missed anything.
                for missed in await c.pipeline.events_after(run_id, last):
                    yield sse(missed)
                    last = missed["seq"]
                if await c.pipeline.status(run_id) in RESTING:
                    yield "event: end\ndata: {}\n\n"
                    return
                yield ": ping\n\n"
                continue
            if event["seq"] <= last:
                continue
            yield sse(event)
            last = event["seq"]
            if event["type"] == "run" and event.get("status") in {s.value for s in RESTING}:
                yield "event: end\ndata: {}\n\n"
                return

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
