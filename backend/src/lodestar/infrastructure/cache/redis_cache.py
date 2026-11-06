"""Redis-backed JSON cache, plus caching Decorators for the market data and exchange providers.

JSON only, never pickle: a poisoned cache entry must not be able to execute code.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError

from lodestar.application import codec
from lodestar.application.ports import Cache, ExchangeProvider, MarketDataProvider
from lodestar.application.serialization import to_jsonable
from lodestar.domain.models import (
    AssetCandidate,
    Candle,
    ExchangeQuote,
    Fundamentals,
    LiquidityProfile,
    MarketHistory,
    MarketListing,
    MarketSnapshot,
    OrderBook,
)

log = structlog.get_logger(__name__)
T = TypeVar("T")


class RedisCache:
    def __init__(self, redis: Redis, *, namespace: str = "ls") -> None:
        self._redis, self._ns = redis, namespace

    def _key(self, key: str) -> str:
        return f"{self._ns}:{key}"

    async def get_json(self, key: str) -> Any | None:
        try:
            raw = await self._redis.get(self._key(key))
        except RedisError as exc:  # cache is an optimisation: degrade, don't fail
            log.warning("cache_get_failed", key=key, error=str(exc))
            return None
        return json.loads(raw) if raw else None

    async def set_json(self, key: str, value: Any, ttl_seconds: int) -> None:
        try:
            await self._redis.set(self._key(key), json.dumps(value, separators=(",", ":")), ex=ttl_seconds)
        except RedisError as exc:
            log.warning("cache_set_failed", key=key, error=str(exc))

    async def delete(self, key: str) -> None:
        try:
            await self._redis.delete(self._key(key))
        except RedisError as exc:
            log.warning("cache_delete_failed", key=key, error=str(exc))


class CachedMarketDataProvider:
    """Decorator: same interface as MarketDataProvider, with per-method TTLs."""

    def __init__(
        self,
        inner: MarketDataProvider,
        cache: Cache,
        *,
        snapshot_ttl: int,
        history_ttl: int,
        fundamentals_ttl: int,
    ) -> None:
        self._inner, self._cache = inner, cache
        self._snapshot_ttl, self._history_ttl, self._fundamentals_ttl = snapshot_ttl, history_ttl, fundamentals_ttl

    async def _cached(self, key: str, ttl: int, load: Callable[[], Awaitable[T]], decode: Callable[[Any], T]) -> T:
        return await cached(self._cache, key, ttl, load, decode)

    async def search(self, query: str) -> list[AssetCandidate]:
        return await self._cached(
            f"search:{query.lower()}",
            600,
            lambda: self._inner.search(query),
            lambda rows: [codec.candidate(r) for r in rows],
        )

    async def top_markets(self, n: int) -> list[MarketListing]:
        return await self._cached(
            f"top:{n}", 600, lambda: self._inner.top_markets(n), lambda rows: [MarketListing(**r) for r in rows]
        )

    async def get_profile(self, coingecko_id: str) -> AssetCandidate:
        return await self._cached(
            f"profile:{coingecko_id}",
            self._fundamentals_ttl,
            lambda: self._inner.get_profile(coingecko_id),
            codec.candidate,
        )

    async def get_snapshot(self, coingecko_id: str) -> MarketSnapshot:
        return await self._cached(
            f"snapshot:{coingecko_id}",
            self._snapshot_ttl,
            lambda: self._inner.get_snapshot(coingecko_id),
            codec.snapshot,
        )

    async def get_history(self, coingecko_id: str, days: int) -> MarketHistory:
        return await self._cached(
            f"history:{coingecko_id}:{days}",
            self._history_ttl,
            lambda: self._inner.get_history(coingecko_id, days),
            codec.history,
        )

    async def get_fundamentals(self, coingecko_id: str) -> Fundamentals:
        return await self._cached(
            f"fundamentals:{coingecko_id}",
            self._fundamentals_ttl,
            lambda: self._inner.get_fundamentals(coingecko_id),
            codec.fundamentals,
        )

    async def get_liquidity(self, coingecko_id: str) -> LiquidityProfile:
        return await self._cached(
            f"liquidity:{coingecko_id}",
            self._fundamentals_ttl // 6,
            lambda: self._inner.get_liquidity(coingecko_id),
            codec.liquidity,
        )


class CachedExchangeProvider:
    """Decorator for an exchange: candles change once a day, quotes every minute."""

    def __init__(self, inner: ExchangeProvider, cache: Cache, *, quote_ttl: int, candles_ttl: int) -> None:
        self._inner, self._cache = inner, cache
        self._quote_ttl, self._candles_ttl = quote_ttl, candles_ttl
        self.venue = inner.venue

    async def get_quote(self, symbol: str) -> ExchangeQuote | None:
        return await cached(
            self._cache,
            f"xq:{self.venue}:{symbol}",
            self._quote_ttl,
            lambda: self._inner.get_quote(symbol),
            lambda d: codec.exchange_quote(d) if d else None,
            cache_none=True,
        )

    async def get_order_book(self, symbol: str) -> OrderBook | None:
        return await self._inner.get_order_book(symbol)  # books change by the second: never cached

    async def get_candles(self, symbol: str, days: int) -> list[Candle]:
        return await cached(
            self._cache,
            f"xc:{self.venue}:{symbol}:{days}",
            self._candles_ttl,
            lambda: self._inner.get_candles(symbol, days),
            lambda rows: [codec.candle(r) for r in rows],
        )


_NONE = {"__none__": True}


async def cached[T](
    cache: Cache,
    key: str,
    ttl: int,
    load: Callable[[], Awaitable[T]],
    decode: Callable[[Any], T],
    *,
    cache_none: bool = False,
) -> T:
    hit = await cache.get_json(key)
    if hit == _NONE:
        return decode(None)
    if hit is not None:
        return decode(hit)
    value = await load()
    if value is not None:
        await cache.set_json(key, to_jsonable(value), ttl)
    elif cache_none:
        await cache.set_json(key, _NONE, ttl)
    return value
