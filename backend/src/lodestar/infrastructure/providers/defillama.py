"""DefiLlama adapter: ecosystem TVL for assets that are the native token of a chain."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

from lodestar.domain.models import ChainFees, PriceQuote, TvlSnapshot
from lodestar.infrastructure.http import ResilientHttp

BASE = "https://api.llama.fi"
# Rebranded tokens whose CoinGecko id differs from the id DefiLlama links to the chain.
CHAIN_ALIASES = {"polygon-ecosystem-token": "Polygon"}


class DefiLlamaProvider:
    def __init__(self, http: ResilientHttp) -> None:
        self._http = http
        self._chains: dict[str, str] | None = None
        self._chains_loaded_at: datetime | None = None

    async def chain_for(self, coingecko_id: str) -> str | None:
        if alias := CHAIN_ALIASES.get(coingecko_id):
            return alias
        now = datetime.now(UTC)
        if self._chains is None or self._chains_loaded_at is None or now - self._chains_loaded_at > timedelta(hours=12):
            chains: list[dict[str, Any]] = await self._http.get_json(f"{BASE}/v2/chains")
            self._chains = {c["gecko_id"]: c["name"] for c in chains if c.get("gecko_id") and c.get("name")}
            self._chains_loaded_at = now
        return self._chains.get(coingecko_id)

    async def get_chain_tvl(self, coingecko_id: str) -> TvlSnapshot | None:
        chain = await self.chain_for(coingecko_id)
        if chain is None:
            return None  # not a chain token: TVL does not apply, which is not a data gap
        series: list[dict[str, Any]] = await self._http.get_json(f"{BASE}/v2/historicalChainTvl/{quote(chain)}")
        if not series:
            return None
        latest = series[-1]
        month_ago = series[-31] if len(series) > 31 else None
        change = None
        if month_ago and month_ago.get("tvl"):
            change = (latest["tvl"] / month_ago["tvl"] - 1) * 100
        return TvlSnapshot(
            chain=chain,
            tvl_usd=float(latest["tvl"]),
            change_30d_pct=change,
            as_of=datetime.fromtimestamp(int(latest["date"]), tz=UTC),
        )


PRICES = "https://coins.llama.fi/prices/current"


class DefiLlamaPriceProvider:
    """Independent aggregated price (DefiLlama coins API), used to reconcile the primary feed."""

    source = "defillama"

    def __init__(self, http: ResilientHttp) -> None:
        self._http = http

    async def get_price(self, coingecko_id: str) -> PriceQuote | None:
        key = f"coingecko:{coingecko_id}"
        data: dict[str, Any] = await self._http.get_json(f"{PRICES}/{quote(key)}")
        row = (data.get("coins") or {}).get(key)
        if not row or not isinstance(row.get("price"), int | float):
            return None
        return PriceQuote(
            source=self.source,
            price_usd=float(row["price"]),
            as_of=datetime.fromtimestamp(int(row.get("timestamp") or 0), tz=UTC),
        )


FEES = "https://api.llama.fi/overview/fees"


class DefiLlamaChainFees:
    """Chain-level fees and revenue (DefiLlama) for coins that are a chain's native token."""

    def __init__(self, http: ResilientHttp, tvl: DefiLlamaProvider) -> None:
        self._http, self._tvl = http, tvl

    async def _overview(self, chain: str, data_type: str) -> dict[str, Any]:
        data: dict[str, Any] = await self._http.get_json(
            f"{FEES}/{quote(chain.lower())}",
            params={"excludeTotalDataChart": "true", "excludeTotalDataChartBreakdown": "true", "dataType": data_type},
        )
        return data

    async def get_chain_fees(self, coingecko_id: str) -> ChainFees | None:
        chain = await self._tvl.chain_for(coingecko_id)
        if chain is None:
            return None
        fees = await self._overview(chain, "dailyFees")
        revenue = await self._overview(chain, "dailyRevenue")

        def num(d: dict[str, Any], key: str) -> float | None:
            v = d.get(key)
            return float(v) if isinstance(v, int | float) else None

        return ChainFees(
            chain, num(fees, "total24h"), num(fees, "total30d"), num(revenue, "total30d"), datetime.now(UTC)
        )
