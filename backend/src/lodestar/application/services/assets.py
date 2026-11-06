"""Assets, charts and the watchlist."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog

from lodestar.application.ports import DataSources, UnitOfWork
from lodestar.application.sanitize import is_valid_coingecko_id, is_valid_search_query
from lodestar.application.serialization import to_json_dict, to_jsonable
from lodestar.application.services.runs import PipelineService, run_json
from lodestar.domain import indicators as ta
from lodestar.domain.errors import LodestarError, NotFoundError, ValidationFailed
from lodestar.domain.models import Asset, AssetCandidate

log = structlog.get_logger(__name__)
UowFactory = Callable[[], UnitOfWork]
INDICATOR_WARMUP_DAYS = 200


def _day(ts: datetime) -> int:
    """Unix seconds at UTC midnight: one bar per calendar day, aligned across sources."""
    d = ts.astimezone(UTC).date()
    return int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp())


def _series(times: Sequence[int], values: Sequence[float | None], days: int) -> list[dict[str, float]]:
    return [{"t": t, "v": round(v, 10)} for t, v in list(zip(times, values, strict=True))[-days:] if v is not None]


class AssetService:
    def __init__(self, uow: UowFactory, sources: DataSources) -> None:
        self._uow, self._s = uow, sources

    async def search(self, query: str) -> list[AssetCandidate]:
        if not is_valid_search_query(query):
            raise ValidationFailed("Search query must be 1-64 letters, digits, spaces, dots or dashes")
        return (await self._s.market.search(query.strip()))[:20]

    async def track(self, coingecko_id: str) -> Asset:
        """Add any coin to the platform. Idempotent; verifies the id upstream first."""
        if not is_valid_coingecko_id(coingecko_id):
            raise ValidationFailed("Invalid CoinGecko id")
        async with self._uow() as uow:
            if existing := await uow.assets.get_by_coingecko_id(coingecko_id):
                return existing
        profile = await self._s.market.get_profile(coingecko_id)  # raises NotFoundError for unknown ids
        async with self._uow() as uow:
            asset = await uow.assets.add(profile.coingecko_id, profile.symbol, profile.name)
            await uow.commit()
        log.info("asset_tracked", coingecko_id=coingecko_id)
        return asset

    async def resolve_symbol(self, symbol: str) -> Asset | None:
        """Best match for a ticker: the highest-ranked search hit with exactly that symbol."""
        hits = [c for c in await self.search(symbol) if c.symbol.upper() == symbol.upper()]
        return await self.track(hits[0].coingecko_id) if hits else None

    async def list_all(self) -> list[Asset]:
        async with self._uow() as uow:
            return await uow.assets.list_all()

    async def get(self, asset_id: UUID) -> Asset:
        async with self._uow() as uow:
            if asset := await uow.assets.get(asset_id):
                return asset
        raise NotFoundError("Asset not found")

    async def chart(self, asset_id: UUID, days: int) -> dict[str, Any]:
        """Candles (exchange), close line (primary feed) and indicator series computed in code."""
        asset = await self.get(asset_id)
        history_days = min(365, days + INDICATOR_WARMUP_DAYS)
        snapshot, history, candles = await asyncio.gather(
            self._s.market.get_snapshot(asset.coingecko_id),
            self._s.market.get_history(asset.coingecko_id, history_days),
            self._safe_candles(asset.symbol, history_days),
        )
        if candles:
            times = [_day(c.ts) for c in candles]
            closes = [c.close for c in candles]
            source = self._s.exchange.venue
        else:
            times = [_day(p.ts) for p in history.points]
            closes = history.closes
            source = "coingecko" if self._s.mode == "live" else "demo"
        bands = ta.bollinger_series(closes)
        return {
            "asset": to_jsonable(asset),
            "snapshot": to_json_dict(snapshot),
            "candle_source": source if candles else None,
            "candles": [
                {"t": _day(c.ts), "o": c.open, "h": c.high, "l": c.low, "c": c.close, "v": c.volume} for c in candles
            ][-days:],
            "line": [{"t": _day(p.ts), "v": p.price, "volume": p.volume} for p in history.points][-days:],
            "indicators": {
                "source": source,
                "sma_20": _series(times, ta.sma_series(closes, 20), days),
                "sma_50": _series(times, ta.sma_series(closes, 50), days),
                "sma_200": _series(times, ta.sma_series(closes, 200), days),
                "bb_upper": _series(times, [b[2] if b else None for b in bands], days),
                "bb_lower": _series(times, [b[0] if b else None for b in bands], days),
                "rsi_14": _series(times, ta.rsi_series(closes, 14), days),
            },
        }

    async def _safe_candles(self, symbol: str, days: int) -> list[Any]:
        try:
            return await self._s.exchange.get_candles(symbol, days)
        except LodestarError as exc:
            log.warning("candles_unavailable", symbol=symbol, error=str(exc))
            return []


class WatchlistService:
    def __init__(self, uow: UowFactory) -> None:
        self._uow = uow

    async def list_assets(self, user_id: UUID) -> list[Asset]:
        async with self._uow() as uow:
            return await uow.watchlist.list_assets(user_id)

    async def add(self, user_id: UUID, asset_id: UUID) -> None:
        async with self._uow() as uow:
            if not await uow.assets.get(asset_id):
                raise NotFoundError("Asset not found")
            await uow.watchlist.add(user_id, asset_id)
            await uow.commit()

    async def remove(self, user_id: UUID, asset_id: UUID) -> None:
        async with self._uow() as uow:
            await uow.watchlist.remove(user_id, asset_id)
            await uow.commit()


class CoinOnboarding:
    """'Add a coin': track it, watch it, and start a visible pipeline run."""

    def __init__(self, assets: AssetService, watchlist: WatchlistService, pipeline: PipelineService) -> None:
        self._assets, self._watchlist, self._pipeline = assets, watchlist, pipeline

    async def add(
        self, coingecko_id: str, user_id: UUID, *, watch: bool = True, analyze: bool = True
    ) -> dict[str, Any]:
        asset = await self._assets.track(coingecko_id)
        if watch:
            await self._watchlist.add(user_id, asset.id)
        run = None
        if analyze:
            record, _ = await self._pipeline.request(asset.id, user_id)
            run = run_json(record, asset)
        return {"asset": to_jsonable(asset), "run": run}
