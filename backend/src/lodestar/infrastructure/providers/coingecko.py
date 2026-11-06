"""CoinGecko adapter (Adapter pattern): maps the CoinGecko REST API onto MarketDataProvider."""

from __future__ import annotations

import asyncio
import statistics
import time
from datetime import UTC, datetime
from typing import Any

from lodestar.domain.errors import NotFoundError, ProviderUnavailable
from lodestar.domain.models import (
    AssetCandidate,
    Fundamentals,
    LiquidityProfile,
    MarketHistory,
    MarketListing,
    MarketSnapshot,
    PricePoint,
)
from lodestar.infrastructure.http import ResilientHttp

PUBLIC_URL = "https://api.coingecko.com/api/v3"
PRO_URL = "https://pro-api.coingecko.com/api/v3"
# CoinGecko search misses some rebrands (e.g. "polygon" no longer returns POL).
# Maps a user query to (alternate query, coin id to pull from its results).
SEARCH_ALIASES: dict[str, tuple[str, str]] = {
    "polygon": ("pol", "polygon-ecosystem-token"),
    "matic": ("pol", "polygon-ecosystem-token"),
}


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) else None


class CoinGeckoProvider:
    def __init__(self, http: ResilientHttp, *, api_key: str | None, plan: str) -> None:
        self._http = http
        self._base = PRO_URL if plan == "pro" else PUBLIC_URL
        self._headers: dict[str, str] = {}
        if api_key:
            self._headers["x-cg-pro-api-key" if plan == "pro" else "x-cg-demo-api-key"] = api_key
        # Snapshot and fundamentals share one /coins/{id} call: coalesce concurrent
        # requests and memoise briefly to protect the free-tier rate limit.
        self._coin_tasks: dict[str, tuple[float, asyncio.Task[dict[str, Any]]]] = {}
        self._coin_ttl = 20.0

    async def _get(self, path: str, **params: Any) -> Any:
        return await self._http.get_json(f"{self._base}{path}", params=params or None, headers=self._headers)

    async def search(self, query: str) -> list[AssetCandidate]:
        data = await self._get("/search", query=query)
        coins: list[dict[str, Any]] = data.get("coins", [])
        coins.sort(key=lambda c: (c.get("market_cap_rank") is None, c.get("market_cap_rank") or 0))
        if alias := SEARCH_ALIASES.get(query.lower()):
            alias_query, target_id = alias
            extra = await self._get("/search", query=alias_query)
            pinned = [c for c in extra.get("coins", []) if c["id"] == target_id]
            coins = pinned + [c for c in coins if c["id"] != target_id]
        return [
            AssetCandidate(
                coingecko_id=c["id"],
                symbol=str(c.get("symbol", "")).upper(),
                name=c.get("name", c["id"]),
                market_cap_rank=c.get("market_cap_rank"),
                thumb_url=c.get("thumb"),
            )
            for c in coins
        ]

    async def top_markets(self, n: int) -> list[MarketListing]:
        rows = await self._get(
            "/coins/markets", vs_currency="usd", order="market_cap_desc", per_page=min(n, 250), page=1
        )
        return [
            MarketListing(
                coingecko_id=r["id"],
                symbol=str(r.get("symbol", "")).upper(),
                name=str(r.get("name", r["id"])),
                market_cap_rank=r.get("market_cap_rank"),
                market_cap_usd=_num(r.get("market_cap")),
                volume_24h_usd=_num(r.get("total_volume")),
                price_usd=_num(r.get("current_price")),
            )
            for r in rows
            if isinstance(r, dict) and r.get("id")
        ]

    async def _coin(self, coingecko_id: str) -> dict[str, Any]:
        now = time.monotonic()
        cached = self._coin_tasks.get(coingecko_id)
        if cached is None or now - cached[0] > self._coin_ttl or (cached[1].done() and cached[1].exception()):
            if len(self._coin_tasks) > 256:
                self._coin_tasks.clear()  # bound memory
            cached = (now, asyncio.ensure_future(self._fetch_coin(coingecko_id)))
            self._coin_tasks[coingecko_id] = cached
        coin: dict[str, Any] = await asyncio.shield(cached[1])
        return coin

    async def _fetch_coin(self, coingecko_id: str) -> dict[str, Any]:
        try:
            coin: dict[str, Any] = await self._get(
                f"/coins/{coingecko_id}",
                localization="false",
                tickers="false",
                market_data="true",
                community_data="false",
                developer_data="false",
                sparkline="false",
            )
            return coin
        except ProviderUnavailable as exc:
            if "404" in str(exc):
                raise NotFoundError(f"Unknown coin '{coingecko_id}'") from exc
            raise

    async def get_profile(self, coingecko_id: str) -> AssetCandidate:
        coin = await self._coin(coingecko_id)
        return AssetCandidate(
            coingecko_id=coin.get("id", coingecko_id),
            symbol=str(coin.get("symbol", "")).upper()[:20],
            name=str(coin.get("name", coingecko_id))[:120],
            market_cap_rank=coin.get("market_cap_rank"),
            thumb_url=(coin.get("image") or {}).get("thumb"),
        )

    async def get_snapshot(self, coingecko_id: str) -> MarketSnapshot:
        coin = await self._coin(coingecko_id)
        md = coin.get("market_data") or {}

        def usd(field: str) -> float | None:
            return _num((md.get(field) or {}).get("usd"))

        price = usd("current_price")
        if price is None:
            raise ProviderUnavailable(f"No USD price for {coingecko_id}")
        updated = md.get("last_updated") or coin.get("last_updated")
        return MarketSnapshot(
            coingecko_id=coingecko_id,
            price_usd=price,
            market_cap_usd=usd("market_cap"),
            fdv_usd=usd("fully_diluted_valuation"),
            volume_24h_usd=usd("total_volume"),
            change_24h_pct=_num(md.get("price_change_percentage_24h")),
            change_7d_pct=_num(md.get("price_change_percentage_7d")),
            change_30d_pct=_num(md.get("price_change_percentage_30d")),
            change_1y_pct=_num(md.get("price_change_percentage_1y")),
            ath_usd=usd("ath"),
            ath_change_pct=_num((md.get("ath_change_percentage") or {}).get("usd")),
            market_cap_rank=coin.get("market_cap_rank"),
            as_of=datetime.fromisoformat(updated.replace("Z", "+00:00")) if updated else datetime.now(UTC),
        )

    async def get_history(self, coingecko_id: str, days: int) -> MarketHistory:
        data = await self._get(f"/coins/{coingecko_id}/market_chart", vs_currency="usd", days=days, interval="daily")
        prices, volumes, caps = data.get("prices", []), data.get("total_volumes", []), data.get("market_caps", [])
        vol_by_ts = {int(ts): v for ts, v in volumes}
        cap_by_ts = {int(ts): v for ts, v in caps}
        points: dict[str, PricePoint] = {}
        for ts, price in prices:
            if price is None:
                continue
            dt = datetime.fromtimestamp(ts / 1000, tz=UTC)
            # CoinGecko appends a live "now" point; keep one point per calendar day (the latest).
            points[dt.date().isoformat()] = PricePoint(
                ts=dt,
                price=float(price),
                volume=float(vol_by_ts.get(int(ts)) or 0.0),
                market_cap=cap_by_ts.get(int(ts)),
            )
        return MarketHistory(coingecko_id=coingecko_id, points=tuple(points.values()))

    async def get_fundamentals(self, coingecko_id: str) -> Fundamentals:
        coin = await self._coin(coingecko_id)
        md = coin.get("market_data") or {}
        return Fundamentals(
            circulating_supply=_num(md.get("circulating_supply")),
            total_supply=_num(md.get("total_supply")),
            max_supply=_num(md.get("max_supply")),
            categories=tuple(c for c in coin.get("categories") or [] if c)[:8],
            genesis_date=coin.get("genesis_date"),
        )

    async def get_liquidity(self, coingecko_id: str) -> LiquidityProfile:
        data = await self._get(f"/coins/{coingecko_id}/tickers", depth="true", order="volume_desc")
        tickers = [
            t
            for t in data.get("tickers", [])
            if not t.get("is_anomaly") and not t.get("is_stale") and t.get("trust_score") in ("green", "yellow")
        ][:15]
        if not tickers:
            return LiquidityProfile(None, None, None, 0)
        spreads = [s for t in tickers if (s := _num(t.get("bid_ask_spread_percentage"))) is not None]
        depth = sum(
            (_num(t.get("cost_to_move_up_usd")) or 0) + (_num(t.get("cost_to_move_down_usd")) or 0) for t in tickers
        )
        volumes = [(_num((t.get("converted_volume") or {}).get("usd")) or 0.0) for t in tickers]
        total = sum(volumes)
        return LiquidityProfile(
            median_spread_pct=statistics.median(spreads) if spreads else None,
            depth_2pct_usd=depth or None,
            top_venue_volume_share_pct=(max(volumes) / total * 100) if total else None,
            venue_count=len({(t.get("market") or {}).get("identifier") for t in tickers}),
        )
