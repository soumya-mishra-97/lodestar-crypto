"""Composition root: the only place that knows concrete classes.

Built once per process (API, worker, CLI) and torn down on shutdown. Everything
else receives its collaborators through constructors (Dependency Injection).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import interrupt
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from lodestar.application.auth import AuthService
from lodestar.application.pipeline.data_step import CollectionSettings
from lodestar.application.pipeline.events import RunEventRecorder
from lodestar.application.pipeline.nodes import ANALYSTS, PipelineConfig, PipelineDeps, PipelineNodes
from lodestar.application.pipeline.react import AnalystPolicy, PolicyFactory, ScriptedPolicy
from lodestar.application.pipeline.writer import ReportWriter, TemplateReportWriter
from lodestar.application.ports import Cache, Clock, DataSources, JobQueue, RunEventBus, UnitOfWork
from lodestar.application.services.assets import AssetService, CoinOnboarding, WatchlistService
from lodestar.application.services.overview import OverviewService
from lodestar.application.services.portfolio import PortfolioService
from lodestar.application.services.reports import ReportService
from lodestar.application.services.runs import PipelineService
from lodestar.application.services.settings import SettingsService
from lodestar.application.trading.analysts import TRADE_ANALYSTS
from lodestar.application.trading.common import TradingPrefs
from lodestar.application.trading.nodes import TRADE_STEPS, TradeDeps, TradeNodes
from lodestar.application.trading.services import BacktestService, PaperService, ScanService
from lodestar.config import Settings
from lodestar.infrastructure.cache.redis_cache import CachedExchangeProvider, CachedMarketDataProvider, RedisCache
from lodestar.infrastructure.db.repositories import SqlAlchemyUnitOfWork
from lodestar.infrastructure.events.bus import RedisRunEventBus
from lodestar.infrastructure.export.pdf import FpdfReportRenderer
from lodestar.infrastructure.http import ResilientHttp
from lodestar.infrastructure.llm.anthropic_agents import (
    ClaudeAnalystPolicy,
    ClaudeReportWriter,
    ClaudeSettings,
    FallbackWriter,
    make_client,
)
from lodestar.infrastructure.orchestration.langgraph_engine import (
    LangGraphEngine,
    build_graph,
    build_trade_graph,
    postgres_checkpointer,
)
from lodestar.infrastructure.providers import demo
from lodestar.infrastructure.providers.coingecko import CoinGeckoProvider
from lodestar.infrastructure.providers.defillama import DefiLlamaChainFees, DefiLlamaPriceProvider, DefiLlamaProvider
from lodestar.infrastructure.providers.kraken import KrakenFuturesFunding, KrakenProvider
from lodestar.infrastructure.providers.news import RssNewsProvider
from lodestar.infrastructure.providers.polymarket import PolymarketProvider
from lodestar.infrastructure.providers.sentiment import FearGreedProvider
from lodestar.infrastructure.providers.wallets import PublicChainBalances
from lodestar.infrastructure.queue.celery_app import CeleryJobQueue, InlineJobQueue, create_celery
from lodestar.infrastructure.security.crypto import FieldCipher
from lodestar.infrastructure.security.passwords import Argon2PasswordHasher
from lodestar.infrastructure.security.rate_limit import RedisRateLimiter
from lodestar.infrastructure.security.tokens import JwtTokenService

PIPELINE_STEPS = [
    "data",
    "technical",
    "fundamental",
    "sentiment",
    "risk",
    "portfolio",
    "report_writer",
    "verifier",
    "human_approval",
]


class UtcClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


def build_sources(settings: Settings, http: ResilientHttp, cache: Cache, clock: Clock) -> DataSources:
    if settings.effective_data_mode == "demo":
        market = demo.DemoMarketData(clock)
        return DataSources(
            mode="demo",
            market=market,
            exchange=demo.DemoExchange(market),
            reference=demo.DemoReferencePrice(market),
            sentiment=demo.DemoSentiment(clock),
            news=demo.DemoNews(clock),
            onchain=demo.DemoOnChain(clock),
            predictions=demo.DemoPredictions(),
            wallets=demo.DemoWallets(),
            derivatives=demo.DemoDerivatives(clock),
            fees=demo.DemoChainFees(clock),
        )
    cg_key = settings.coingecko_api_key.get_secret_value() if settings.coingecko_api_key else None
    tvl = DefiLlamaProvider(http)
    return DataSources(
        mode="live",
        market=CachedMarketDataProvider(
            CoinGeckoProvider(http, api_key=cg_key, plan=settings.coingecko_plan),
            cache,
            snapshot_ttl=settings.snapshot_cache_ttl_seconds,
            history_ttl=settings.history_cache_ttl_seconds,
            fundamentals_ttl=settings.fundamentals_cache_ttl_seconds,
        ),
        exchange=CachedExchangeProvider(
            KrakenProvider(http),
            cache,
            quote_ttl=settings.snapshot_cache_ttl_seconds,
            candles_ttl=settings.candles_cache_ttl_seconds,
        ),
        reference=DefiLlamaPriceProvider(http),
        sentiment=FearGreedProvider(http),
        news=RssNewsProvider(http, settings.news_feeds),
        onchain=tvl,
        predictions=PolymarketProvider(http),
        wallets=PublicChainBalances(http, settings.rpc_urls),
        derivatives=KrakenFuturesFunding(http),
        fees=DefiLlamaChainFees(http, tvl),
    )


def llm_mode(settings: Settings) -> str:
    return settings.llm_model if settings.llm_configured else "deterministic"


def build_agents(settings: Settings) -> tuple[PolicyFactory, ReportWriter]:
    template = TemplateReportWriter()
    plans = {a.name: a.scripted_plan() for a in (*ANALYSTS, *TRADE_ANALYSTS)}
    if not settings.llm_configured:

        def scripted(name: str) -> AnalystPolicy:
            return ScriptedPolicy(plans[name])

        return scripted, template
    cfg = ClaudeSettings(
        api_key=settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None,
        model=settings.llm_model,
        effort=settings.llm_effort,
        max_tokens=settings.llm_max_tokens,
        timeout_seconds=settings.llm_timeout_seconds,
        server_fallbacks=settings.llm_server_fallbacks,
    )
    client = make_client(cfg)

    def claude(name: str) -> AnalystPolicy:
        return ClaudeAnalystPolicy(client, cfg)

    return claude, FallbackWriter(ClaudeReportWriter(client, cfg), template)


def platform_view(settings: Settings) -> dict[str, Any]:
    demo_mode = settings.effective_data_mode == "demo"
    live = not demo_mode
    return {
        "data_mode": settings.effective_data_mode,
        "demo": demo_mode,
        "auth_mode": settings.auth_mode,
        "llm": {
            "mode": llm_mode(settings),
            "configured": settings.llm_configured,
            "model": settings.llm_model,
            "effort": settings.llm_effort,
        },
        "providers": [
            {
                "name": "CoinGecko",
                "role": "Prices, history, supply, liquidity",
                "active": live,
                "keyed": bool(settings.coingecko_api_key),
            },
            {"name": "Kraken", "role": "Daily candles and second price feed", "active": live, "keyed": False},
            {"name": "DefiLlama", "role": "Chain TVL and third price feed", "active": live, "keyed": False},
            {"name": "alternative.me", "role": "Fear & Greed index", "active": live, "keyed": False},
            {"name": "RSS news", "role": "Headlines (untrusted context)", "active": live, "keyed": False},
            {"name": "Polymarket", "role": "Prediction-market odds (optional)", "active": live, "keyed": False},
            {"name": "Public RPC / mempool.space", "role": "Read-only wallet balances", "active": live, "keyed": False},
            {"name": "Demo generator", "role": "Synthetic data for every source", "active": demo_mode, "keyed": False},
        ],
        "trading": {"steps": list(TRADE_STEPS), "paper_only": True, "order_placement": False},
        "pipeline": {
            "steps": PIPELINE_STEPS,
            "max_agent_steps": settings.max_agent_steps,
            "max_repairs": settings.max_repairs,
            "approval_required": True,
        },
        "schedule": {"daily_report_hour_utc": settings.daily_report_hour_utc},
    }


@dataclass
class Container:
    settings: Settings
    engine: AsyncEngine | None
    redis: Redis | None
    http: ResilientHttp | None
    tokens: JwtTokenService
    rate_limiter: Any
    auth: AuthService
    sources: DataSources
    bus: RunEventBus
    events: RunEventRecorder
    assets: AssetService
    watchlist: WatchlistService
    onboarding: CoinOnboarding
    pipeline: PipelineService
    portfolio: PortfolioService
    reports: ReportService
    overview: OverviewService
    preferences: SettingsService
    queue: JobQueue
    nodes: PipelineNodes
    uow: Any
    trade_nodes: TradeNodes | None = None
    scans: ScanService | None = None
    backtests: BacktestService | None = None
    paper: PaperService | None = None
    _stack: AsyncExitStack = field(default_factory=AsyncExitStack)
    local_owner_id: Any = None

    async def aclose(self) -> None:
        await self._stack.aclose()
        if self.http is not None:
            await self.http.aclose()
        if self.redis is not None:
            await self.redis.aclose()
        if self.engine is not None:
            await self.engine.dispose()


def assemble(
    settings: Settings,
    *,
    uow: Any,
    redis: Redis | Any,
    bus: RunEventBus,
    clock: Clock,
    sources: DataSources,
    queue: JobQueue,
    tokens: JwtTokenService,
    rate_limiter: Any,
    policies: PolicyFactory,
    writer: ReportWriter,
    engine: AsyncEngine | None = None,
    http: ResilientHttp | None = None,
    pace: bool = True,
) -> Container:
    """Wire services from already-built infrastructure. Shared by production and tests."""
    events = RunEventRecorder(uow, bus, clock)
    assets = AssetService(uow, sources)
    watchlist = WatchlistService(uow)
    portfolio = PortfolioService(uow, sources, assets)
    pipeline = PipelineService(uow, queue, events, data_mode=sources.mode, llm_mode=llm_mode(settings), clock=clock)
    preferences = SettingsService(uow, platform_view(settings))
    paper = PaperService(uow, sources, clock, preferences.preferences)
    backtests = BacktestService(uow, sources)
    deps = PipelineDeps(
        sources=sources,
        uow=uow,
        events=events,
        clock=clock,
        policies=policies,
        writer=writer,
        portfolio=portfolio.valuation,
        approval_gate=interrupt,
        config=PipelineConfig(
            max_agent_steps=settings.max_agent_steps,
            max_repairs=settings.max_repairs,
            mismatch_tolerance_pct=settings.mismatch_tolerance_pct,
            step_delay_seconds=settings.demo_step_delay_ms / 1000 if sources.mode == "demo" and pace else 0.0,
            collection=CollectionSettings(),
        ),
    )
    nodes = PipelineNodes(deps)
    trade_nodes = TradeNodes(deps, TradeDeps(paper=paper, backtests=backtests))
    return Container(
        settings=settings,
        engine=engine,
        redis=redis,
        http=http,
        tokens=tokens,
        rate_limiter=rate_limiter,
        auth=AuthService(uow, Argon2PasswordHasher(), tokens, allow_registration=settings.allow_registration),
        sources=sources,
        bus=bus,
        events=events,
        assets=assets,
        watchlist=watchlist,
        onboarding=CoinOnboarding(assets, watchlist, pipeline),
        pipeline=pipeline,
        portfolio=portfolio,
        reports=ReportService(uow, FpdfReportRenderer()),
        overview=OverviewService(uow, sources, portfolio),
        preferences=preferences,
        queue=queue,
        nodes=nodes,
        uow=uow,
        trade_nodes=trade_nodes,
        scans=ScanService(uow, sources, queue),
        backtests=backtests,
        paper=paper,
    )


def scan_runner(container: Container) -> Callable[[UUID], Awaitable[None]]:
    """Run a scan with the requesting user's trading preferences (worker task and inline queue)."""

    async def run(scan_id: UUID) -> None:
        assert container.scans is not None  # noqa: S101 - always wired by assemble()
        async with container.uow() as uow:
            scan = await uow.scans.get(scan_id)
        prefs = await container.preferences.preferences(scan.user_id) if scan and scan.user_id else {}
        await container.scans.execute(scan_id, TradingPrefs.from_prefs(prefs))

    return run


async def attach_engine(container: Container, checkpointer: BaseCheckpointSaver[Any] | None = None) -> None:
    """Give this process a workflow engine (worker, CLI, tests). Postgres checkpoints unless one is passed."""
    if checkpointer is None:
        if container.settings.env == "test":
            checkpointer = InMemorySaver()
        else:
            checkpointer = await container._stack.enter_async_context(
                postgres_checkpointer(container.settings.database_url)
            )
    assert checkpointer is not None  # noqa: S101 - narrowed above
    repairs = container.settings.max_repairs
    container.pipeline.attach_engine(LangGraphEngine(build_graph(container.nodes, max_repairs=repairs), checkpointer))
    if container.trade_nodes is not None:
        container.pipeline.attach_engine(
            LangGraphEngine(build_trade_graph(container.trade_nodes, max_repairs=repairs), checkpointer), graph="trade"
        )


async def build_container(
    settings: Settings,
    *,
    queue: Literal["celery", "inline"] = "celery",
    with_workflow: bool = False,
    pace: bool = True,
) -> Container:
    db = create_async_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,
        pool_recycle=1800,
    )
    session_factory = async_sessionmaker(db, expire_on_commit=False, class_=AsyncSession)
    cipher = FieldCipher(settings.field_encryption_keys.get_secret_value())

    def uow() -> UnitOfWork:
        return SqlAlchemyUnitOfWork(session_factory, cipher)

    redis = Redis.from_url(settings.redis_url, health_check_interval=30, socket_timeout=30)
    http, clock = ResilientHttp(), UtcClock()
    policies, writer = build_agents(settings)
    job_queue: JobQueue = InlineJobQueue() if queue == "inline" else CeleryJobQueue(create_celery(settings))
    container = assemble(
        settings,
        uow=uow,
        redis=redis,
        bus=RedisRunEventBus(redis),
        clock=clock,
        sources=build_sources(settings, http, RedisCache(redis), clock),
        queue=job_queue,
        tokens=JwtTokenService(
            redis,
            secret=settings.jwt_secret.get_secret_value(),
            issuer=settings.jwt_issuer,
            access_ttl=settings.access_token_ttl_seconds,
            refresh_ttl=settings.refresh_token_ttl_seconds,
        ),
        rate_limiter=RedisRateLimiter(redis),
        policies=policies,
        writer=writer,
        engine=db,
        http=http,
        pace=pace,
    )
    if isinstance(job_queue, InlineJobQueue):
        job_queue.bind(container.pipeline.execute, container.pipeline.resume, scan_runner(container))
    if with_workflow:
        await attach_engine(container)
    return container
