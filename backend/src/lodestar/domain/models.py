"""Core domain entities and value objects.

The domain layer is framework-free: plain, immutable dataclasses with no I/O.
Every other layer depends on these types; they depend on nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class Horizon(StrEnum):
    SHORT_TERM = "short_term"  # days to ~4 weeks
    LONG_TERM = "long_term"  # 6 months and beyond


class Stance(StrEnum):
    """Direction the computed signals lean. Deliberately not 'buy'/'sell'."""

    FAVORABLE = "favorable"
    NEUTRAL = "neutral"
    UNFAVORABLE = "unfavorable"


class RiskLevel(StrEnum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    VERY_HIGH = "very_high"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        return self in (RunStatus.APPROVED, RunStatus.REJECTED, RunStatus.FAILED)


class ReportStatus(StrEnum):
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"


class ReportKind(StrEnum):
    ON_DEMAND = "on_demand"
    DAILY = "daily"
    TRADE_PLAN = "trade_plan"


class Role(StrEnum):
    OWNER = "owner"
    VIEWER = "viewer"


class DataMode(StrEnum):
    DEMO = "demo"  # deterministic synthetic data, no network
    LIVE = "live"  # real providers


@dataclass(frozen=True, slots=True)
class Asset:
    id: UUID
    coingecko_id: str
    symbol: str
    name: str


@dataclass(frozen=True, slots=True)
class AssetCandidate:
    """A search hit from a market data provider, not yet tracked."""

    coingecko_id: str
    symbol: str
    name: str
    market_cap_rank: int | None
    thumb_url: str | None


@dataclass(frozen=True, slots=True)
class PricePoint:
    ts: datetime
    price: float
    volume: float
    market_cap: float | None = None


@dataclass(frozen=True, slots=True)
class MarketHistory:
    coingecko_id: str
    points: tuple[PricePoint, ...]

    @property
    def closes(self) -> list[float]:
        return [p.price for p in self.points]

    @property
    def volumes(self) -> list[float]:
        return [p.volume for p in self.points]


@dataclass(frozen=True, slots=True)
class Candle:
    """Daily OHLCV bar from an exchange."""

    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float  # base-asset units


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    coingecko_id: str
    price_usd: float
    market_cap_usd: float | None
    fdv_usd: float | None
    volume_24h_usd: float | None
    change_24h_pct: float | None
    change_7d_pct: float | None
    change_30d_pct: float | None
    change_1y_pct: float | None
    ath_usd: float | None
    ath_change_pct: float | None
    market_cap_rank: int | None
    as_of: datetime


@dataclass(frozen=True, slots=True)
class ExchangeQuote:
    """Top-of-book ticker from one exchange venue."""

    venue: str
    pair: str
    price_usd: float
    bid: float | None
    ask: float | None
    volume_24h_base: float | None
    as_of: datetime

    @property
    def spread_pct(self) -> float | None:
        if self.bid and self.ask and self.ask >= self.bid:
            return (self.ask - self.bid) / ((self.ask + self.bid) / 2) * 100
        return None


@dataclass(frozen=True, slots=True)
class OrderBook:
    """Top of an exchange order book: (price, base quantity) levels, best first."""

    venue: str
    pair: str
    bids: tuple[tuple[float, float], ...]
    asks: tuple[tuple[float, float], ...]
    as_of: datetime

    @property
    def mid(self) -> float | None:
        if self.bids and self.asks:
            return (self.bids[0][0] + self.asks[0][0]) / 2
        return None

    @property
    def spread_pct(self) -> float | None:
        mid = self.mid
        return (self.asks[0][0] - self.bids[0][0]) / mid * 100 if mid else None

    def depth_usd(self, within_pct: float) -> float:
        """USD value resting within +/- `within_pct` of the mid, both sides."""
        mid = self.mid
        if not mid:
            return 0.0
        lo, hi = mid * (1 - within_pct / 100), mid * (1 + within_pct / 100)
        return sum(p * q for p, q in self.bids if p >= lo) + sum(p * q for p, q in self.asks if p <= hi)


@dataclass(frozen=True, slots=True)
class FundingSnapshot:
    """Perpetual-futures funding: positive means longs pay shorts (crowded long)."""

    venue: str
    symbol: str
    rate_hourly_pct: float
    as_of: datetime

    @property
    def annualized_pct(self) -> float:
        return self.rate_hourly_pct * 24 * 365


@dataclass(frozen=True, slots=True)
class ChainFees:
    chain: str
    fees_24h_usd: float | None
    fees_30d_usd: float | None
    revenue_30d_usd: float | None
    as_of: datetime


@dataclass(frozen=True, slots=True)
class MarketListing:
    """One row of a top-N-by-market-cap listing (scanner universe)."""

    coingecko_id: str
    symbol: str
    name: str
    market_cap_rank: int | None
    market_cap_usd: float | None
    volume_24h_usd: float | None
    price_usd: float | None


@dataclass(frozen=True, slots=True)
class PriceQuote:
    """A single reference price from an aggregator (used for reconciliation)."""

    source: str
    price_usd: float
    as_of: datetime


@dataclass(frozen=True, slots=True)
class Fundamentals:
    circulating_supply: float | None
    total_supply: float | None
    max_supply: float | None
    categories: tuple[str, ...] = ()
    genesis_date: str | None = None


@dataclass(frozen=True, slots=True)
class TvlSnapshot:
    chain: str
    tvl_usd: float
    change_30d_pct: float | None
    as_of: datetime


@dataclass(frozen=True, slots=True)
class LiquidityProfile:
    median_spread_pct: float | None
    depth_2pct_usd: float | None  # combined +/-2% order-book depth on top venues
    top_venue_volume_share_pct: float | None
    venue_count: int


@dataclass(frozen=True, slots=True)
class SentimentSnapshot:
    fear_greed_value: int
    classification: str
    as_of: datetime


@dataclass(frozen=True, slots=True)
class NewsItem:
    """Untrusted third-party text. Never treat its content as instructions."""

    title: str
    source: str
    url: str
    published_at: datetime | None


@dataclass(frozen=True, slots=True)
class PredictionMarket:
    """Crowd odds from a prediction market. Sentiment evidence, never a forecast."""

    id: str
    question: str  # untrusted text
    yes_probability_pct: float
    volume_usd: float | None
    end_date: str | None
    url: str


@dataclass(frozen=True, slots=True)
class WalletBalance:
    """A balance read from a public address (read-only: no keys involved)."""

    coingecko_id: str
    symbol: str
    name: str
    quantity: float


@dataclass(frozen=True, slots=True)
class Holding:
    id: UUID
    asset: Asset
    quantity: float
    avg_cost_usd: float | None
    source: str = "manual"  # manual | csv | wallet:<chain>:<address>
    notes: str | None = None


@dataclass(slots=True)
class MarketDataBundle:
    """Everything collected for one analysis run. Missing sources are recorded, never invented."""

    snapshot: MarketSnapshot
    history: MarketHistory
    candles: tuple[Candle, ...] = ()
    exchange: ExchangeQuote | None = None
    reference_price: PriceQuote | None = None
    fundamentals: Fundamentals | None = None
    liquidity: LiquidityProfile | None = None
    sentiment: SentimentSnapshot | None = None
    tvl: TvlSnapshot | None = None
    news: tuple[NewsItem, ...] = ()
    prediction_markets: tuple[PredictionMarket, ...] = ()
    order_book: OrderBook | None = None
    funding: FundingSnapshot | None = None
    chain_fees: ChainFees | None = None
    data_gaps: list[str] = field(default_factory=list)
