"""Live pipeline event fan-out.

Redis Streams in production: every event is appended to `ls:run:<id>:events`
(capped, expiring), and SSE subscribers block on XREAD. A stream keeps its
history, so a subscriber that connects late, or reconnects, replays everything
it missed, filtered by sequence number. Postgres remains the durable record.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections import defaultdict
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from redis.asyncio import Redis


class RedisRunEventBus:
    def __init__(self, redis: Redis, *, ttl_seconds: int = 86_400, maxlen: int = 5_000) -> None:
        self._redis, self._ttl, self._maxlen = redis, ttl_seconds, maxlen

    @staticmethod
    def key(run_id: UUID) -> str:
        return f"ls:run:{run_id}:events"

    async def publish(self, run_id: UUID, event: dict[str, Any]) -> None:
        key = self.key(run_id)
        async with self._redis.pipeline(transaction=False) as pipe:
            pipe.xadd(key, {"e": json.dumps(event, separators=(",", ":"))}, maxlen=self._maxlen, approximate=True)
            pipe.expire(key, self._ttl)
            await pipe.execute()

    async def tail(self, run_id: UUID, *, after_seq: int, idle_timeout: float) -> AsyncIterator[dict[str, Any] | None]:
        key, last_id = self.key(run_id), "0-0"
        while True:
            response = await self._redis.xread({key: last_id}, block=int(idle_timeout * 1000), count=200)
            if not response:
                yield None  # heartbeat
                continue
            for _stream, entries in response:
                for entry_id, fields in entries:
                    last_id = entry_id.decode() if isinstance(entry_id, bytes) else entry_id
                    raw = fields.get(b"e") or fields.get("e")
                    event: dict[str, Any] = json.loads(raw)
                    if event["seq"] > after_seq:
                        yield event


class InMemoryRunEventBus:
    """Single-process bus for tests and inline mode."""

    def __init__(self) -> None:
        self._events: dict[UUID, list[dict[str, Any]]] = defaultdict(list)
        self._cond = asyncio.Condition()

    async def publish(self, run_id: UUID, event: dict[str, Any]) -> None:
        async with self._cond:
            self._events[run_id].append(event)
            self._cond.notify_all()

    async def tail(self, run_id: UUID, *, after_seq: int, idle_timeout: float) -> AsyncIterator[dict[str, Any] | None]:
        cursor = 0
        while True:
            async with self._cond:
                if cursor >= len(self._events[run_id]):
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(self._cond.wait(), timeout=idle_timeout)
                pending = self._events[run_id][cursor:]
                cursor += len(pending)
            if not pending:
                yield None
            for event in pending:
                if event["seq"] > after_seq:
                    yield event
