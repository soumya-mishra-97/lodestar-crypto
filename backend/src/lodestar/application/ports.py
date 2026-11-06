"""Ports: the interfaces the application layer depends on (Dependency Inversion).

Infrastructure provides adapters (CoinGecko, Kraken, Postgres, Redis, Celery,
LangGraph, Claude, ...). Tests provide in-memory fakes. Use cases never import
an adapter directly.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol, Self
from uuid import UUID

from lodestar.domain.addresses import Chain
from lodestar.domain.models import (
    Asset,
    AssetCandidate,
    Candle,
    ChainFees,
    ExchangeQuote,
    Fundamentals,
    FundingSnapshot,
    Holding,
    LiquidityProfile,
    MarketHistory,
    MarketListing,
    MarketSnapshot,
    NewsItem,
    OrderBook,
    PredictionMarket,
    PriceQuote,
    ReportKind,
    ReportStatus,
    Role,
    RunStatus,
    SentimentSnapshot,
    TvlSnapshot,
    WalletBalance,
)

# ---------------------------------------------------------------- data providers (all read-only)


class MarketDataProvider(Protocol):
    """Primary market data (CoinGecko or the demo generator)."""

    async def search(self, query: str) -> list[AssetCandidate]: ...
    async def get_profile(self, coingecko_id: str) -> AssetCandidate:
        """Canonical name/symbol for a coin id; raises NotFoundError if it doesn't exist."""
        ...

    async def top_markets(self, n: int) -> list[MarketListing]:
        """Top `n` coins by market cap (scanner universe)."""
        ...

    async def get_snapshot(self, coingecko_id: str) -> MarketSnapshot: ...
    async def get_history(self, coingecko_id: str, days: int) -> MarketHistory: ...
    async def get_fundamentals(self, coingecko_id: str) -> Fundamentals: ...
    async def get_liquidity(self, coingecko_id: str) -> LiquidityProfile: ...


class ExchangeProvider(Protocol):
    """One exchange's public market data. Returns None/[] when the pair is not listed."""

    venue: str

    async def get_quote(self, symbol: str) -> ExchangeQuote | None: ...
    async def get_candles(self, symbol: str, days: int) -> list[Candle]: ...
    async def get_order_book(self, symbol: str) -> OrderBook | None: ...


class ReferencePriceProvider(Protocol):
    """An independent price aggregator used to reconcile the primary feed."""

    async def get_price(self, coingecko_id: str) -> PriceQuote | None: ...


class SentimentProvider(Protocol):
    async def get_market_sentiment(self) -> SentimentSnapshot: ...


class NewsProvider(Protocol):
    async def latest(self, *, name: str, symbol: str, limit: int) -> list[NewsItem]: ...


class OnChainProvider(Protocol):
    async def get_chain_tvl(self, coingecko_id: str) -> TvlSnapshot | None: ...


class PredictionMarketProvider(Protocol):
    async def markets_for(self, *, name: str, symbol: str, limit: int) -> list[PredictionMarket]: ...


class DerivativesProvider(Protocol):
    async def get_funding(self, symbol: str) -> FundingSnapshot | None: ...


class ChainFeesProvider(Protocol):
    async def get_chain_fees(self, coingecko_id: str) -> ChainFees | None: ...


class WalletBalanceProvider(Protocol):
    async def balances(self, chain: Chain, address: str) -> list[WalletBalance]: ...


@dataclass(frozen=True, slots=True)
class DataSources:
    """Every provider the platform reads from, plus the mode they run in."""

    mode: str  # DataMode value
    market: MarketDataProvider
    exchange: ExchangeProvider
    reference: ReferencePriceProvider
    sentiment: SentimentProvider
    news: NewsProvider
    onchain: OnChainProvider
    predictions: PredictionMarketProvider
    wallets: WalletBalanceProvider
    derivatives: DerivativesProvider
    fees: ChainFeesProvider


# ---------------------------------------------------------------- infrastructure services


class Cache(Protocol):
    async def get_json(self, key: str) -> Any | None: ...
    async def set_json(self, key: str, value: Any, ttl_seconds: int) -> None: ...
    async def delete(self, key: str) -> None: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class JobQueue(Protocol):
    async def enqueue_run(self, run_id: UUID) -> None: ...
    async def enqueue_resume(self, run_id: UUID, decision: dict[str, Any]) -> None: ...
    async def enqueue_scan(self, scan_id: UUID) -> None: ...


class WorkflowEngine(Protocol):
    """Runs the agent graph (LangGraph) with durable checkpoints, one thread per run."""

    async def start(self, thread_id: str, state: dict[str, Any]) -> dict[str, Any]: ...
    async def resume(self, thread_id: str, value: dict[str, Any]) -> dict[str, Any]: ...


class RunEventBus(Protocol):
    """Live fan-out of pipeline events to SSE subscribers (Redis Streams in production)."""

    async def publish(self, run_id: UUID, event: dict[str, Any]) -> None: ...
    def tail(self, run_id: UUID, *, after_seq: int, idle_timeout: float) -> AsyncIterator[dict[str, Any] | None]:
        """Yield events with seq > after_seq; yield None as a heartbeat when idle."""
        ...


class PdfRenderer(Protocol):
    def render(self, report: dict[str, Any]) -> bytes: ...


# ---------------------------------------------------------------- persistence records


@dataclass(frozen=True, slots=True)
class UserRecord:
    id: UUID
    email: str
    password_hash: str
    role: Role
    is_active: bool


@dataclass(frozen=True, slots=True)
class RunRecord:
    id: UUID
    asset_id: UUID
    requested_by: UUID | None
    kind: ReportKind
    status: RunStatus
    current_step: str | None
    repair_count: int
    error: str | None
    data_mode: str
    llm_mode: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


@dataclass(frozen=True, slots=True)
class EventRecord:
    run_id: UUID
    seq: int
    ts: datetime
    step: str
    type: str
    status: str | None
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ReportSummary:
    headline: str
    short_term_stance: str
    long_term_stance: str
    short_term_risk: str
    long_term_risk: str
    setup_kind: str | None = None  # trade plans only
    setup_status: str | None = None


@dataclass(frozen=True, slots=True)
class ScanRecord:
    id: UUID
    user_id: UUID | None
    universe: str  # watchlist | top
    top_n: int | None
    status: str  # running | completed | failed
    progress: int
    total: int
    results: list[dict[str, Any]] | None
    error: str | None
    data_mode: str
    created_at: datetime
    finished_at: datetime | None


@dataclass(frozen=True, slots=True)
class BacktestRecord:
    id: UUID
    user_id: UUID | None
    asset_id: UUID
    run_id: UUID | None
    kind: str
    config: dict[str, Any]
    summary: dict[str, Any]
    created_at: datetime
    result: dict[str, Any] | None = None  # loaded only on single reads


@dataclass(frozen=True, slots=True)
class PaperAccount:
    user_id: UUID
    starting_cash: float
    cash: float
    started_on: date
    last_processed: date | None


@dataclass(frozen=True, slots=True)
class PaperPosition:
    id: UUID
    user_id: UUID
    asset_id: UUID
    report_id: UUID | None
    origin: str  # plan | demo_replay
    status: str  # pending | triggered | open | closed | cancelled
    setup_kind: str
    trigger: float
    entry_low: float
    entry_high: float
    stop: float
    profit_level: float
    horizon: int
    expiry_bars: int
    units: float
    opened_on: date  # bars after this date are processed
    created_at: datetime
    bars_seen: int = 0
    bars_held: int = 0
    entry_price: float | None = None
    entry_at: datetime | None = None
    exit_price: float | None = None
    exit_at: datetime | None = None
    exit_reason: str | None = None
    fees_usd: float = 0.0
    pnl_usd: float | None = None


@dataclass(frozen=True, slots=True)
class ReportRecord:
    id: UUID
    run_id: UUID
    asset_id: UUID
    kind: ReportKind
    status: ReportStatus
    summary: ReportSummary
    created_at: datetime
    decided_at: datetime | None
    decision_note: str | None
    content: dict[str, Any] | None = None  # loaded only on single-report reads


class UserRepository(Protocol):
    async def count(self) -> int: ...
    async def get(self, user_id: UUID) -> UserRecord | None: ...
    async def get_by_email(self, email: str) -> UserRecord | None: ...
    async def add(self, email: str, password_hash: str, role: Role) -> UserRecord: ...


class AssetRepository(Protocol):
    async def get(self, asset_id: UUID) -> Asset | None: ...
    async def get_by_coingecko_id(self, coingecko_id: str) -> Asset | None: ...
    async def add(self, coingecko_id: str, symbol: str, name: str) -> Asset: ...
    async def list_all(self) -> list[Asset]: ...


class RunRepository(Protocol):
    async def create(
        self, asset_id: UUID, requested_by: UUID | None, kind: ReportKind, *, data_mode: str, llm_mode: str
    ) -> RunRecord: ...
    async def get(self, run_id: UUID) -> RunRecord | None: ...
    async def list(self, *, asset_id: UUID | None = None, limit: int = 50) -> list[RunRecord]: ...
    async def active_for_asset(self, asset_id: UUID, kind: ReportKind | None = None) -> RunRecord | None:
        """Latest queued/running run for the asset; with `kind`, only runs of that kind (analysis vs trade plan)."""
        ...

    async def update(
        self,
        run_id: UUID,
        *,
        status: RunStatus | None = None,
        current_step: str | None = None,
        repair_count: int | None = None,
        error: str | None = None,
    ) -> None: ...


class EventRepository(Protocol):
    async def append(
        self, run_id: UUID, *, ts: datetime, step: str, type: str, status: str | None, payload: dict[str, Any]
    ) -> EventRecord:
        """Persist an event with the next per-run sequence number, allocated atomically by the store."""
        ...

    async def list(self, run_id: UUID, *, after_seq: int = 0) -> list[EventRecord]: ...
    async def max_seq(self, run_id: UUID) -> int: ...


class ReportRepository(Protocol):
    async def create(
        self, run_id: UUID, asset_id: UUID, kind: ReportKind, summary: ReportSummary, content: dict[str, Any]
    ) -> UUID:
        """Idempotent per run: returns the existing report id if one was already saved."""
        ...

    async def get(self, report_id: UUID) -> ReportRecord | None: ...
    async def get_by_run(self, run_id: UUID) -> ReportRecord | None: ...
    async def list(
        self,
        *,
        kind: ReportKind | None = None,
        status: ReportStatus | None = None,
        asset_id: UUID | None = None,
        limit: int = 50,
    ) -> list[ReportRecord]: ...
    async def latest_for_assets(self, asset_ids: Sequence[UUID]) -> dict[UUID, ReportRecord]:
        """Latest non-rejected report per asset, with content."""
        ...

    async def decide(
        self, report_id: UUID, status: ReportStatus, *, user_id: UUID | None, note: str | None
    ) -> None: ...


class ScanRepository(Protocol):
    async def create(self, user_id: UUID | None, universe: str, top_n: int | None, data_mode: str) -> ScanRecord: ...
    async def get(self, scan_id: UUID) -> ScanRecord | None: ...
    async def list_recent(self, user_id: UUID | None, *, limit: int = 20) -> list[ScanRecord]: ...
    async def update(
        self,
        scan_id: UUID,
        *,
        status: str | None = None,
        progress: int | None = None,
        total: int | None = None,
        results: list[dict[str, Any]] | None = None,
        error: str | None = None,
    ) -> None: ...


class BacktestRepository(Protocol):
    async def add(
        self,
        user_id: UUID | None,
        asset_id: UUID,
        run_id: UUID | None,
        kind: str,
        config: dict[str, Any],
        summary: dict[str, Any],
        result: dict[str, Any],
    ) -> UUID: ...
    async def get(self, backtest_id: UUID) -> BacktestRecord | None: ...
    async def list_recent(
        self, user_id: UUID | None, *, asset_id: UUID | None = None, limit: int = 50
    ) -> list[BacktestRecord]: ...


class PaperRepository(Protocol):
    async def get_account(self, user_id: UUID) -> PaperAccount | None: ...
    async def save_account(self, account: PaperAccount) -> None: ...
    async def reset(self, user_id: UUID) -> None:
        """Delete the account, its positions and its equity history."""
        ...

    async def add_position(self, position: PaperPosition) -> None: ...
    async def save_position(self, position: PaperPosition) -> None: ...
    async def get_position(self, user_id: UUID, position_id: UUID) -> PaperPosition | None: ...
    async def list_positions(self, user_id: UUID, *, statuses: Sequence[str] | None = None) -> list[PaperPosition]: ...
    async def save_equity(self, user_id: UUID, day: date, equity: float, cash: float) -> None: ...
    async def equity_series(self, user_id: UUID) -> list[tuple[date, float, float]]: ...
    async def all_user_ids(self) -> list[UUID]: ...


class WatchlistRepository(Protocol):
    async def list_assets(self, user_id: UUID) -> list[Asset]: ...
    async def add(self, user_id: UUID, asset_id: UUID) -> None: ...
    async def remove(self, user_id: UUID, asset_id: UUID) -> None: ...
    async def all_entries(self) -> list[tuple[UUID, UUID]]:
        """(user_id, asset_id) for every watchlist entry."""
        ...


class PortfolioRepository(Protocol):
    async def list_holdings(self, user_id: UUID) -> list[Holding]: ...
    async def upsert(
        self,
        user_id: UUID,
        asset_id: UUID,
        *,
        quantity: float,
        avg_cost_usd: float | None,
        notes: str | None,
        source: str,
    ) -> None: ...
    async def remove(self, user_id: UUID, holding_id: UUID) -> None: ...


class SettingsRepository(Protocol):
    async def get(self, user_id: UUID) -> dict[str, Any]: ...
    async def put(self, user_id: UUID, data: dict[str, Any]) -> None: ...


class UnitOfWork(Protocol):
    """Groups repository work in one transaction (Unit of Work pattern)."""

    @property
    def users(self) -> UserRepository: ...
    @property
    def assets(self) -> AssetRepository: ...
    @property
    def runs(self) -> RunRepository: ...
    @property
    def events(self) -> EventRepository: ...
    @property
    def reports(self) -> ReportRepository: ...
    @property
    def watchlist(self) -> WatchlistRepository: ...
    @property
    def portfolio(self) -> PortfolioRepository: ...
    @property
    def settings(self) -> SettingsRepository: ...
    @property
    def scans(self) -> ScanRepository: ...
    @property
    def backtests(self) -> BacktestRepository: ...
    @property
    def paper(self) -> PaperRepository: ...

    async def __aenter__(self) -> Self: ...
    async def __aexit__(self, *exc: object) -> None: ...
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...
