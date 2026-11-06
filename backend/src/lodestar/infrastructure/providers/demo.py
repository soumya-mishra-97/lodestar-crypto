"""Demo mode: deterministic synthetic data for every provider port. No network, no keys.

Each coin's price path is a seeded random walk anchored to a fixed "current"
price, so numbers are stable across processes and restarts but move with the
calendar. Every source is named `demo*` so evidence can never be mistaken for
real market data, and the UI shows a "demo data" banner whenever this mode is on.
One coin (Chainlink) carries a deliberate cross-source price gap so the
reconciliation warning can be seen end to end.
"""

from __future__ import annotations

import math
import random
import zlib
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from typing import ClassVar

from lodestar.application.ports import Clock
from lodestar.domain.addresses import Chain
from lodestar.domain.errors import NotFoundError
from lodestar.domain.models import (
    AssetCandidate,
    Candle,
    ChainFees,
    ExchangeQuote,
    Fundamentals,
    FundingSnapshot,
    LiquidityProfile,
    MarketHistory,
    MarketListing,
    MarketSnapshot,
    NewsItem,
    OrderBook,
    PredictionMarket,
    PricePoint,
    PriceQuote,
    SentimentSnapshot,
    TvlSnapshot,
    WalletBalance,
)

HISTORY_DAYS = 730
DEMO_SOURCE = "demo"


@dataclass(frozen=True, slots=True)
class DemoCoin:
    id: str
    symbol: str
    name: str
    price: float
    rank: int
    circulating: float
    total: float | None
    max_supply: float | None
    annual_vol: float  # annualised volatility of daily log returns
    drift: float  # annual drift of the synthetic path (shapes the trend, not the end price)
    ath_multiple: float  # all-time high as a multiple of the current price
    chain: str | None = None  # DefiLlama chain name when the coin is a chain's native token
    tvl: float | None = None
    exchange_skew_pct: float = 0.12  # demo exchange price offset vs the primary feed
    reference_skew_pct: float = -0.08


CATALOG: tuple[DemoCoin, ...] = (
    DemoCoin("bitcoin", "BTC", "Bitcoin", 71250.0, 1, 19.8e6, 19.8e6, 21e6, 0.48, 0.35, 1.04),
    DemoCoin("ethereum", "ETH", "Ethereum", 3380.0, 2, 120.4e6, 120.4e6, None, 0.62, 0.20, 1.45, "Ethereum", 62.5e9),
    DemoCoin("solana", "SOL", "Solana", 164.2, 5, 470e6, 590e6, None, 0.78, 0.45, 1.58, "Solana", 9.1e9),
    DemoCoin("ripple", "XRP", "XRP", 0.552, 7, 56e9, 99.99e9, 100e9, 0.66, 0.05, 6.9),
    DemoCoin("cardano", "ADA", "Cardano", 0.447, 10, 35.6e9, 45e9, 45e9, 0.72, -0.10, 6.9),
    DemoCoin("dogecoin", "DOGE", "Dogecoin", 0.161, 9, 146e9, 146e9, None, 0.92, 0.10, 4.6),
    DemoCoin("avalanche-2", "AVAX", "Avalanche", 27.9, 14, 407e6, 449e6, 720e6, 0.84, -0.15, 5.2, "Avalanche", 1.1e9),
    DemoCoin("chainlink", "LINK", "Chainlink", 14.62, 16, 608e6, 1e9, 1e9, 0.80, 0.15, 3.6, None, None, 3.4, 0.1),
    DemoCoin("polkadot", "DOT", "Polkadot", 4.51, 22, 1.5e9, 1.55e9, None, 0.75, -0.30, 12.0),
    DemoCoin(
        "polygon-ecosystem-token",
        "POL",
        "POL (ex-MATIC)",
        0.0912,
        48,
        10.4e9,
        10.47e9,
        None,
        0.86,
        -0.35,
        14.0,
        "Polygon",
        1.05e9,
    ),
    DemoCoin("arbitrum", "ARB", "Arbitrum", 0.452, 45, 4.1e9, 10e9, 10e9, 0.88, -0.25, 5.2, "Arbitrum", 2.6e9),
    DemoCoin("uniswap", "UNI", "Uniswap", 7.48, 24, 600e6, 1e9, 1e9, 0.82, 0.05, 6.0),
    DemoCoin("near", "NEAR", "NEAR Protocol", 3.52, 26, 1.2e9, 1.23e9, None, 0.85, -0.05, 5.8, "Near", 1.6e8),
    DemoCoin("litecoin", "LTC", "Litecoin", 74.6, 20, 75e6, 84e6, 84e6, 0.62, -0.05, 5.5),
)
BY_ID = {c.id: c for c in CATALOG}
BY_SYMBOL = {c.symbol: c for c in CATALOG}


def _seed(*parts: str) -> int:
    return zlib.crc32("|".join(parts).encode())


def _today(clock: Clock) -> datetime:
    now = clock.now().astimezone(UTC)
    return datetime(now.year, now.month, now.day, tzinfo=UTC)


ANCHOR = date(2026, 11, 1)  # each coin's configured price holds on this date


def _day_return(coin: DemoCoin, day: date) -> float:
    """Daily log return, seeded by (coin, date) so any given day's price never changes."""
    rng = random.Random(_seed("ret", coin.id, day.isoformat()))  # noqa: S311 - synthetic data, not security
    regime = 1.6 if (day.toordinal() // 90) % 3 == 1 else 1.0  # occasional high-volatility regimes
    return coin.drift / 365 + rng.gauss(0, coin.annual_vol / math.sqrt(365) * regime)


@lru_cache(maxsize=512)
def _path(coin: DemoCoin, end: date) -> tuple[tuple[datetime, float, float], ...]:
    """(day, close, usd_volume) for HISTORY_DAYS days ending at `end`.

    A random walk anchored at ANCHOR (where close == coin.price), extended forward
    and backward one seeded day at a time: stable across days, restarts and processes,
    which is what paper trading needs.
    """
    start = end - timedelta(days=HISTORY_DAYS - 1)
    logp = {ANCHOR: math.log(coin.price)}
    day = ANCHOR
    while day < end:
        nxt = day + timedelta(days=1)
        logp[nxt] = logp[day] + _day_return(coin, nxt)
        day = nxt
    day = ANCHOR
    while day > start:
        logp[day - timedelta(days=1)] = logp[day] - _day_return(coin, day)
        day -= timedelta(days=1)
    base_volume = coin.price * coin.circulating * 0.035
    out = []
    for k in range(HISTORY_DAYS):
        d = start + timedelta(days=k)
        noise = random.Random(_seed("vol", coin.id, d.isoformat())).gauss(0, 0.35)  # noqa: S311
        out.append((datetime(d.year, d.month, d.day, tzinfo=UTC), math.exp(logp[d]), base_volume * math.exp(noise)))
    return tuple(out)


class DemoMarketData:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock

    def _coin(self, coingecko_id: str) -> DemoCoin:
        coin = BY_ID.get(coingecko_id)
        if coin is None:
            raise NotFoundError(f"Unknown coin '{coingecko_id}' (demo mode includes {len(CATALOG)} coins)")
        return coin

    def path(self, coingecko_id: str) -> list[tuple[datetime, float, float]]:
        return list(_path(self._coin(coingecko_id), _today(self._clock).date()))

    async def search(self, query: str) -> list[AssetCandidate]:
        q = query.strip().lower()
        hits = [
            c
            for c in CATALOG
            if q in c.id
            or q in c.name.lower()
            or q == c.symbol.lower()
            or (q in ("matic", "polygon") and c.symbol == "POL")
        ]
        return [AssetCandidate(c.id, c.symbol, c.name, c.rank, None) for c in sorted(hits, key=lambda c: c.rank)]

    async def top_markets(self, n: int) -> list[MarketListing]:
        rows = []
        for c in sorted(CATALOG, key=lambda c: c.rank)[:n]:
            _ts, price, volume = self.path(c.id)[-1]
            rows.append(MarketListing(c.id, c.symbol, c.name, c.rank, price * c.circulating, volume, price))
        return rows

    async def get_profile(self, coingecko_id: str) -> AssetCandidate:
        c = self._coin(coingecko_id)
        return AssetCandidate(c.id, c.symbol, c.name, c.rank, None)

    async def get_snapshot(self, coingecko_id: str) -> MarketSnapshot:
        c, path = self._coin(coingecko_id), self.path(coingecko_id)
        closes = [p for _, p, _ in path]
        price = closes[-1]

        def change(days: int) -> float:
            return (price / closes[-1 - days] - 1) * 100

        ath = max(*closes, c.price * c.ath_multiple)
        return MarketSnapshot(
            coingecko_id=c.id,
            price_usd=price,
            market_cap_usd=price * c.circulating,
            fdv_usd=price * (c.max_supply or c.total or c.circulating),
            volume_24h_usd=path[-1][2],
            change_24h_pct=change(1),
            change_7d_pct=change(7),
            change_30d_pct=change(30),
            change_1y_pct=change(365),
            ath_usd=ath,
            ath_change_pct=(price / ath - 1) * 100,
            market_cap_rank=c.rank,
            as_of=self._clock.now(),
        )

    async def get_history(self, coingecko_id: str, days: int) -> MarketHistory:
        path = self.path(coingecko_id)[-days:]
        return MarketHistory(coingecko_id, tuple(PricePoint(ts, p, v) for ts, p, v in path))

    async def get_fundamentals(self, coingecko_id: str) -> Fundamentals:
        c = self._coin(coingecko_id)
        return Fundamentals(c.circulating, c.total, c.max_supply, ("Demo",), None)

    async def get_liquidity(self, coingecko_id: str) -> LiquidityProfile:
        c = self._coin(coingecko_id)
        mcap = c.price * c.circulating
        return LiquidityProfile(
            median_spread_pct=0.02 if c.rank <= 20 else 0.08,
            depth_2pct_usd=mcap * 0.0004,
            top_venue_volume_share_pct=24.0 + c.rank % 17,
            venue_count=12 if c.rank <= 20 else 8,
        )


class DemoExchange:
    venue = "demo-exchange"

    def __init__(self, market: DemoMarketData) -> None:
        self._market = market

    async def get_quote(self, symbol: str) -> ExchangeQuote | None:
        coin = BY_SYMBOL.get(symbol.upper())
        if coin is None:
            return None
        path = self._market.path(coin.id)
        price = path[-1][1] * (1 + coin.exchange_skew_pct / 100)
        return ExchangeQuote(
            venue=self.venue,
            pair=f"{coin.symbol}USD",
            price_usd=price,
            bid=price * 0.9998,
            ask=price * 1.0002,
            volume_24h_base=path[-1][2] / price * 0.18,
            as_of=path[-1][0] + timedelta(hours=12),
        )

    async def get_candles(self, symbol: str, days: int) -> list[Candle]:
        coin = BY_SYMBOL.get(symbol.upper())
        if coin is None:
            return []
        path = self._market.path(coin.id)
        candles, prev = [], path[0][1]
        for ts, close, usd_volume in path:
            rng = random.Random(_seed("wick", coin.id, ts.date().isoformat()))  # noqa: S311
            wick = abs(rng.gauss(0, coin.annual_vol / math.sqrt(365) * 0.6))
            high = max(prev, close) * (1 + wick)
            low = min(prev, close) * (1 - wick * 0.9)
            candles.append(Candle(ts, prev, high, low, close, usd_volume / close * 0.18))
            prev = close
        return candles[-days:]

    async def get_order_book(self, symbol: str) -> OrderBook | None:
        """Synthetic book whose +/-2% depth matches the demo liquidity profile."""
        quote = await self.get_quote(symbol)
        coin = BY_SYMBOL.get(symbol.upper())
        if quote is None or coin is None:
            return None
        mid = quote.price_usd
        depth_2pct = mid * coin.circulating * 0.0004  # USD, both sides (matches DemoMarketData.get_liquidity)
        levels = 40
        per_level_usd = depth_2pct / 2 / levels * 1.15  # a little extra so the 2% band holds the full depth
        rng = random.Random(_seed("book", coin.id, quote.as_of.date().isoformat()))  # noqa: S311
        bids, asks = [], []
        for k in range(1, levels + 1):
            step = 0.0005 * k  # 0.05% apart -> 40 levels span 2%
            size = per_level_usd * (0.6 + 0.8 * rng.random())
            asks.append((mid * (1 + step), size / (mid * (1 + step))))
            bids.append((mid * (1 - step), size / (mid * (1 - step))))
        return OrderBook(self.venue, f"{coin.symbol}USD", tuple(bids), tuple(asks), quote.as_of)


class DemoReferencePrice:
    def __init__(self, market: DemoMarketData) -> None:
        self._market = market

    async def get_price(self, coingecko_id: str) -> PriceQuote | None:
        coin = BY_ID.get(coingecko_id)
        if coin is None:
            return None
        ts, price, _ = self._market.path(coingecko_id)[-1]
        return PriceQuote("demo-aggregator", price * (1 + coin.reference_skew_pct / 100), ts + timedelta(hours=12))


def _classify(value: int) -> str:
    if value < 25:
        return "Extreme Fear"
    if value < 45:
        return "Fear"
    if value <= 55:
        return "Neutral"
    if value <= 75:
        return "Greed"
    return "Extreme Greed"


class DemoSentiment:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock

    async def get_market_sentiment(self) -> SentimentSnapshot:
        today = _today(self._clock)
        value = 28 + _seed("fng", today.date().isoformat()) % 45
        return SentimentSnapshot(value, _classify(value), today)


class DemoNews:
    TEMPLATES = (
        "{name} core developers publish a quarterly roadmap update",
        "Exchange flows for {symbol} shift as traders rotate across large caps",
        "Analysts debate {name} network activity after recent volatility",
        "{name} mainnet upgrade scheduled after governance vote",
        "Major exchange announces listing of new {symbol} trading pairs",
        "Token unlock calendar: {symbol} vesting tranche due next month",
        "Regulators publish draft guidance that could affect {name} staking",
    )

    def __init__(self, clock: Clock) -> None:
        self._clock = clock

    async def latest(self, *, name: str, symbol: str, limit: int) -> list[NewsItem]:
        today = _today(self._clock)
        # Three general headlines plus two event headlines that rotate per coin.
        first_event = 3 + _seed("news", symbol) % 4
        picks = [*self.TEMPLATES[:3], self.TEMPLATES[first_event], self.TEMPLATES[3 + (first_event - 2) % 4]]
        return [
            NewsItem(
                f"[Demo] {t.format(name=name.split(' (', maxsplit=1)[0], symbol=symbol)}",
                "demo.news",
                f"https://example.com/demo/{symbol.lower()}/{i}",
                today - timedelta(days=i * 2, hours=3),
            )
            for i, t in enumerate(picks[:limit])
        ]


class DemoOnChain:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock

    async def get_chain_tvl(self, coingecko_id: str) -> TvlSnapshot | None:
        coin = BY_ID.get(coingecko_id)
        if coin is None or coin.chain is None or coin.tvl is None:
            return None
        change = ((_seed("tvl", coin.id) % 400) - 150) / 10  # -15% .. +25%
        return TvlSnapshot(coin.chain, coin.tvl, change, _today(self._clock))


class DemoDerivatives:
    """Synthetic perpetual funding: small, coin- and day-seeded, occasionally crowded."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock

    async def get_funding(self, symbol: str) -> FundingSnapshot | None:
        coin = BY_SYMBOL.get(symbol.upper())
        if coin is None or coin.rank > 30:
            return None  # small caps often have no perpetual market
        today = _today(self._clock)
        rng = random.Random(_seed("funding", coin.id, today.date().isoformat()))  # noqa: S311
        return FundingSnapshot("demo-futures", f"PF_{coin.symbol}USD", rng.gauss(0.0012, 0.0015), today)


class DemoChainFees:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock

    async def get_chain_fees(self, coingecko_id: str) -> ChainFees | None:
        coin = BY_ID.get(coingecko_id)
        if coin is None or coin.chain is None or coin.tvl is None:
            return None
        fees_30d = coin.tvl * 0.035
        return ChainFees(coin.chain, fees_30d / 30, fees_30d, fees_30d * 0.48, _today(self._clock))


class DemoPredictions:
    MARKETS: ClassVar[dict[str, tuple[str, float]]] = {
        "BTC": ("Will Bitcoin close the year above its January open? (demo)", 61.0),
        "ETH": ("Will an Ethereum ETF see net inflows this month? (demo)", 54.0),
        "SOL": ("Will Solana flip BNB by market cap this quarter? (demo)", 23.0),
    }

    async def markets_for(self, *, name: str, symbol: str, limit: int) -> list[PredictionMarket]:
        found = self.MARKETS.get(symbol.upper())
        if not found or limit <= 0:
            return []
        question, yes = found
        return [
            PredictionMarket(f"demo-{symbol.lower()}", question, yes, 1.2e6, None, "https://example.com/demo/markets")
        ]


class DemoWallets:
    """Deterministic balances derived from the address, so imports are repeatable."""

    HOLDINGS: ClassVar[dict[Chain, tuple[tuple[str, str, str, float], ...]]] = {
        Chain.ETHEREUM: (("ethereum", "ETH", "Ethereum", 4.0), ("chainlink", "LINK", "Chainlink", 400.0)),
        Chain.POLYGON: (("polygon-ecosystem-token", "POL", "POL (ex-MATIC)", 25_000.0),),
        Chain.BITCOIN: (("bitcoin", "BTC", "Bitcoin", 0.5),),
    }

    async def balances(self, chain: Chain, address: str) -> list[WalletBalance]:
        factor = 0.25 + (_seed("wallet", chain.value, address) % 100) / 100
        return [WalletBalance(cg, sym, name, round(qty * factor, 6)) for cg, sym, name, qty in self.HOLDINGS[chain]]
