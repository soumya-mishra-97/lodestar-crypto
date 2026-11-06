"""Redis fixed-window rate limiter (atomic INCR + EXPIRE in one round trip)."""

from __future__ import annotations

import time

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError

from lodestar.domain.errors import RateLimitedError

log = structlog.get_logger(__name__)


class RedisRateLimiter:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def hit(self, key: str, *, limit: int, window_seconds: int, fail_open: bool = True) -> None:
        window = int(time.time() // window_seconds)
        redis_key = f"ls:rl:{key}:{window}"
        try:
            async with self._redis.pipeline(transaction=True) as pipe:
                pipe.incr(redis_key)
                pipe.expire(redis_key, window_seconds + 1)
                count, _ = await pipe.execute()
        except RedisError as exc:
            log.warning("rate_limiter_unavailable", error=str(exc), fail_open=fail_open)
            if fail_open:
                return
            raise RateLimitedError(retry_after_seconds=window_seconds) from exc
        if int(count) > limit:
            retry_after = window_seconds - int(time.time()) % window_seconds
            raise RateLimitedError(retry_after_seconds=max(retry_after, 1))
