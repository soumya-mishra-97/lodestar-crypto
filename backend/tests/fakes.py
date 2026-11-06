"""In-memory adapters for every port. Fast, deterministic, no network, broker or database.

Market data comes from the demo providers (deterministic by design) under a fixed clock.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any, Self
from uuid import UUID, uuid4

from langgraph.checkpoint.memory import InMemorySaver

from lodestar.application.pipeline.nodes import ANALYSTS
from lodestar.application.pipeline.react import AnalystPolicy, ScriptedPolicy
from lodestar.application.pipeline.writer import ReportWriter, TemplateReportWriter, WriterInput
from lodestar.application.ports import (
    BacktestRecord,
    DataSources,
    EventRecord,
    PaperAccount,
    PaperPosition,
    ReportRecord,
    ReportSummary,
    RunRecord,
    ScanRecord,
    UserRecord,
)
from lodestar.application.trading.analysts import TRADE_ANALYSTS
from lodestar.config import Settings
from lodestar.domain.errors import LlmUnavailable
from lodestar.domain.models import (
    Asset,
    Holding,
    MarketHistory,
    PricePoint,
    ReportKind,
    ReportStatus,
    Role,
    RunStatus,
)
from lodestar.domain.report import ReportDraft
from lodestar.infrastructure.container import Container, assemble, attach_engine, scan_runner
from lodestar.infrastructure.events.bus import InMemoryRunEventBus
from lodestar.infrastructure.providers import demo
from lodestar.infrastructure.queue.celery_app import InlineJobQueue
from lodestar.infrastructure.security.tokens import JwtTokenService

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)


class FixedClock:
    def __init__(self, now: datetime = NOW) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def advance(self, **kwargs: float) -> None:
        self._now += timedelta(**kwargs)


def synthetic_history(coingecko_id: str, *, days: int = 365, start: float = 1.0, drift: float = 0.002) -> MarketHistory:
    points = []
    for i in range(days):
        price = start * math.exp(drift * i) * (1 + 0.03 * math.sin(i / 5))
        points.append(
            PricePoint(ts=NOW - timedelta(days=days - i), price=price, volume=1e7 * (1 + 0.2 * math.cos(i / 7)))
        )
    return MarketHistory(coingecko_id, tuple(points))


def demo_sources(clock: FixedClock) -> DataSources:
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


# ---------------------------------------------------------------- in-memory persistence


@dataclass
class InMemoryStore:
    users: dict[UUID, UserRecord] = field(default_factory=dict)
    assets: dict[UUID, Asset] = field(default_factory=dict)
    runs: dict[UUID, RunRecord] = field(default_factory=dict)
    events: list[EventRecord] = field(default_factory=list)
    reports: dict[UUID, ReportRecord] = field(default_factory=dict)
    watchlist: list[tuple[UUID, UUID]] = field(default_factory=list)
    holdings: dict[tuple[UUID, UUID, str], Holding] = field(default_factory=dict)
    settings: dict[UUID, dict[str, Any]] = field(default_factory=dict)
    scans: dict[UUID, ScanRecord] = field(default_factory=dict)
    backtests: dict[UUID, BacktestRecord] = field(default_factory=dict)
    paper_accounts: dict[UUID, PaperAccount] = field(default_factory=dict)
    paper_positions: dict[UUID, PaperPosition] = field(default_factory=dict)
    paper_equity: dict[tuple[UUID, date], tuple[float, float]] = field(default_factory=dict)


class _Users:
    def __init__(self, s: InMemoryStore) -> None:
        self.s = s

    async def count(self) -> int:
        return len(self.s.users)

    async def get(self, user_id: UUID) -> UserRecord | None:
        return self.s.users.get(user_id)

    async def get_by_email(self, email: str) -> UserRecord | None:
        return next((u for u in self.s.users.values() if u.email == email), None)

    async def add(self, email: str, password_hash: str, role: Role) -> UserRecord:
        u = UserRecord(uuid4(), email, password_hash, role, True)
        self.s.users[u.id] = u
        return u


class _Assets:
    def __init__(self, s: InMemoryStore) -> None:
        self.s = s

    async def get(self, asset_id: UUID) -> Asset | None:
        return self.s.assets.get(asset_id)

    async def get_by_coingecko_id(self, cg: str) -> Asset | None:
        return next((a for a in self.s.assets.values() if a.coingecko_id == cg), None)

    async def add(self, cg: str, symbol: str, name: str) -> Asset:
        if existing := await self.get_by_coingecko_id(cg):
            return existing
        a = Asset(uuid4(), cg, symbol, name)
        self.s.assets[a.id] = a
        return a

    async def list_all(self) -> list[Asset]:
        return sorted(self.s.assets.values(), key=lambda a: a.name)


class _Runs:
    def __init__(self, s: InMemoryStore, clock: FixedClock) -> None:
        self.s, self.clock = s, clock

    async def create(
        self, asset_id: UUID, requested_by: UUID | None, kind: ReportKind, *, data_mode: str, llm_mode: str
    ) -> RunRecord:
        self.clock.advance(seconds=1)  # stable ordering by created_at
        r = RunRecord(
            uuid4(),
            asset_id,
            requested_by,
            kind,
            RunStatus.QUEUED,
            None,
            0,
            None,
            data_mode,
            llm_mode,
            self.clock.now(),
            None,
            None,
        )
        self.s.runs[r.id] = r
        return r

    async def get(self, run_id: UUID) -> RunRecord | None:
        return self.s.runs.get(run_id)

    async def list(self, *, asset_id: UUID | None = None, limit: int = 50) -> list[RunRecord]:
        rows = [r for r in self.s.runs.values() if asset_id is None or r.asset_id == asset_id]
        return sorted(rows, key=lambda r: r.created_at, reverse=True)[:limit]

    async def active_for_asset(self, asset_id: UUID, kind: ReportKind | None = None) -> RunRecord | None:
        trade = ReportKind.TRADE_PLAN

        def same_graph(r: RunRecord) -> bool:
            return kind is None or ((r.kind is trade) == (kind is trade))

        active = [
            r
            for r in self.s.runs.values()
            if r.asset_id == asset_id and r.status in (RunStatus.QUEUED, RunStatus.RUNNING) and same_graph(r)
        ]
        return max(active, key=lambda r: r.created_at, default=None)

    async def update(
        self,
        run_id: UUID,
        *,
        status: RunStatus | None = None,
        current_step: str | None = None,
        repair_count: int | None = None,
        error: str | None = None,
    ) -> None:
        r = self.s.runs[run_id]
        changes: dict[str, Any] = {}
        if status is not None:
            changes["status"] = status
            if status is RunStatus.RUNNING and r.started_at is None:
                changes["started_at"] = self.clock.now()
            if status not in (RunStatus.QUEUED, RunStatus.RUNNING):
                changes["finished_at"] = r.finished_at or self.clock.now()
        if current_step is not None:
            changes["current_step"] = current_step
        if repair_count is not None:
            changes["repair_count"] = repair_count
        if error is not None:
            changes["error"] = error
        self.s.runs[run_id] = replace(r, **changes)


class _Events:
    def __init__(self, s: InMemoryStore) -> None:
        self.s = s

    async def append(
        self, run_id: UUID, *, ts: datetime, step: str, type: str, status: str | None, payload: dict[str, Any]
    ) -> EventRecord:
        record = EventRecord(run_id, await self.max_seq(run_id) + 1, ts, step, type, status, payload)
        self.s.events.append(record)
        return record

    async def list(self, run_id: UUID, *, after_seq: int = 0) -> list[EventRecord]:
        return sorted((e for e in self.s.events if e.run_id == run_id and e.seq > after_seq), key=lambda e: e.seq)

    async def max_seq(self, run_id: UUID) -> int:
        return max((e.seq for e in self.s.events if e.run_id == run_id), default=0)


class _Reports:
    def __init__(self, s: InMemoryStore, clock: FixedClock) -> None:
        self.s, self.clock = s, clock

    async def create(
        self, run_id: UUID, asset_id: UUID, kind: ReportKind, summary: ReportSummary, content: dict[str, Any]
    ) -> UUID:
        if existing := next((r for r in self.s.reports.values() if r.run_id == run_id), None):
            return existing.id
        r = ReportRecord(
            uuid4(),
            run_id,
            asset_id,
            kind,
            ReportStatus.PENDING_APPROVAL,
            summary,
            self.clock.now(),
            None,
            None,
            content,
        )
        self.s.reports[r.id] = r
        return r.id

    async def get(self, report_id: UUID) -> ReportRecord | None:
        return self.s.reports.get(report_id)

    async def get_by_run(self, run_id: UUID) -> ReportRecord | None:
        return next((r for r in self.s.reports.values() if r.run_id == run_id), None)

    async def list(
        self,
        *,
        kind: ReportKind | None = None,
        status: ReportStatus | None = None,
        asset_id: UUID | None = None,
        limit: int = 50,
    ) -> list[ReportRecord]:
        rows = [
            replace(r, content=None)
            for r in self.s.reports.values()
            if (kind is None or r.kind is kind)
            and (status is None or r.status is status)
            and (asset_id is None or r.asset_id == asset_id)
        ]
        return sorted(rows, key=lambda r: r.created_at, reverse=True)[:limit]

    async def latest_for_assets(self, asset_ids: Sequence[UUID]) -> dict[UUID, ReportRecord]:
        out: dict[UUID, ReportRecord] = {}
        for r in sorted(self.s.reports.values(), key=lambda r: r.created_at):
            analysis = r.kind is not ReportKind.TRADE_PLAN
            if r.asset_id in asset_ids and r.status is not ReportStatus.REJECTED and analysis:
                out[r.asset_id] = r
        return out

    async def decide(self, report_id: UUID, status: ReportStatus, *, user_id: UUID | None, note: str | None) -> None:
        self.s.reports[report_id] = replace(
            self.s.reports[report_id], status=status, decided_at=self.clock.now(), decision_note=note
        )


class _Watchlist:
    def __init__(self, s: InMemoryStore) -> None:
        self.s = s

    async def list_assets(self, user_id: UUID) -> list[Asset]:
        return [self.s.assets[a] for u, a in self.s.watchlist if u == user_id]

    async def add(self, user_id: UUID, asset_id: UUID) -> None:
        if (user_id, asset_id) not in self.s.watchlist:
            self.s.watchlist.append((user_id, asset_id))

    async def remove(self, user_id: UUID, asset_id: UUID) -> None:
        if (user_id, asset_id) in self.s.watchlist:
            self.s.watchlist.remove((user_id, asset_id))

    async def all_entries(self) -> list[tuple[UUID, UUID]]:
        return list(self.s.watchlist)


class _Portfolio:
    def __init__(self, s: InMemoryStore) -> None:
        self.s = s

    async def list_holdings(self, user_id: UUID) -> list[Holding]:
        return [h for (u, _, _), h in self.s.holdings.items() if u == user_id]

    async def upsert(
        self,
        user_id: UUID,
        asset_id: UUID,
        *,
        quantity: float,
        avg_cost_usd: float | None,
        notes: str | None,
        source: str,
    ) -> None:
        key = (user_id, asset_id, source)
        existing = self.s.holdings.get(key)
        self.s.holdings[key] = Holding(
            existing.id if existing else uuid4(), self.s.assets[asset_id], quantity, avg_cost_usd, source, notes
        )

    async def remove(self, user_id: UUID, holding_id: UUID) -> None:
        for key, h in list(self.s.holdings.items()):
            if key[0] == user_id and h.id == holding_id:
                del self.s.holdings[key]


class _Settings:
    def __init__(self, s: InMemoryStore) -> None:
        self.s = s

    async def get(self, user_id: UUID) -> dict[str, Any]:
        return dict(self.s.settings.get(user_id, {}))

    async def put(self, user_id: UUID, data: dict[str, Any]) -> None:
        self.s.settings[user_id] = dict(data)


class _Scans:
    def __init__(self, s: InMemoryStore, clock: FixedClock) -> None:
        self.s, self.clock = s, clock

    async def create(self, user_id: UUID | None, universe: str, top_n: int | None, data_mode: str) -> ScanRecord:
        self.clock.advance(seconds=1)
        r = ScanRecord(
            uuid4(), user_id, universe, top_n, "running", 0, 0, None, None, data_mode, self.clock.now(), None
        )
        self.s.scans[r.id] = r
        return r

    async def get(self, scan_id: UUID) -> ScanRecord | None:
        return self.s.scans.get(scan_id)

    async def list_recent(self, user_id: UUID | None, *, limit: int = 20) -> list[ScanRecord]:
        rows = [r for r in self.s.scans.values() if r.user_id == user_id]
        return sorted(rows, key=lambda r: r.created_at, reverse=True)[:limit]

    async def update(self, scan_id: UUID, **changes: Any) -> None:
        values = {k: v for k, v in changes.items() if v is not None}
        if values.get("status") in ("completed", "failed"):
            values["finished_at"] = self.clock.now()
        self.s.scans[scan_id] = replace(self.s.scans[scan_id], **values)


class _Backtests:
    def __init__(self, s: InMemoryStore, clock: FixedClock) -> None:
        self.s, self.clock = s, clock

    async def add(
        self,
        user_id: UUID | None,
        asset_id: UUID,
        run_id: UUID | None,
        kind: str,
        config: dict[str, Any],
        summary: dict[str, Any],
        result: dict[str, Any],
    ) -> UUID:
        r = BacktestRecord(uuid4(), user_id, asset_id, run_id, kind, config, summary, self.clock.now(), result)
        self.s.backtests[r.id] = r
        return r.id

    async def get(self, backtest_id: UUID) -> BacktestRecord | None:
        return self.s.backtests.get(backtest_id)

    async def list_recent(
        self, user_id: UUID | None, *, asset_id: UUID | None = None, limit: int = 50
    ) -> list[BacktestRecord]:
        rows = [
            replace(r, result=None)
            for r in self.s.backtests.values()
            if r.user_id == user_id and (asset_id is None or r.asset_id == asset_id)
        ]
        return sorted(rows, key=lambda r: r.created_at, reverse=True)[:limit]


class _Paper:
    def __init__(self, s: InMemoryStore) -> None:
        self.s = s

    async def get_account(self, user_id: UUID) -> PaperAccount | None:
        return self.s.paper_accounts.get(user_id)

    async def save_account(self, account: PaperAccount) -> None:
        self.s.paper_accounts[account.user_id] = account

    async def reset(self, user_id: UUID) -> None:
        self.s.paper_accounts.pop(user_id, None)
        for pid in [p.id for p in self.s.paper_positions.values() if p.user_id == user_id]:
            del self.s.paper_positions[pid]
        for key in [k for k in self.s.paper_equity if k[0] == user_id]:
            del self.s.paper_equity[key]

    async def add_position(self, position: PaperPosition) -> None:
        self.s.paper_positions[position.id] = position

    async def save_position(self, position: PaperPosition) -> None:
        self.s.paper_positions[position.id] = position

    async def get_position(self, user_id: UUID, position_id: UUID) -> PaperPosition | None:
        p = self.s.paper_positions.get(position_id)
        return p if p and p.user_id == user_id else None

    async def list_positions(self, user_id: UUID, *, statuses: Sequence[str] | None = None) -> list[PaperPosition]:
        rows = [
            p
            for p in self.s.paper_positions.values()
            if p.user_id == user_id and (not statuses or p.status in statuses)
        ]
        return sorted(rows, key=lambda p: (p.opened_on, p.created_at))

    async def save_equity(self, user_id: UUID, day: date, equity: float, cash: float) -> None:
        self.s.paper_equity[(user_id, day)] = (equity, cash)

    async def equity_series(self, user_id: UUID) -> list[tuple[date, float, float]]:
        return sorted((d, e, c) for (u, d), (e, c) in self.s.paper_equity.items() if u == user_id)

    async def all_user_ids(self) -> list[UUID]:
        return list(self.s.paper_accounts)


class InMemoryUnitOfWork:
    def __init__(self, store: InMemoryStore, clock: FixedClock) -> None:
        self.users = _Users(store)
        self.assets = _Assets(store)
        self.runs = _Runs(store, clock)
        self.events = _Events(store)
        self.reports = _Reports(store, clock)
        self.watchlist = _Watchlist(store)
        self.portfolio = _Portfolio(store)
        self.settings = _Settings(store)
        self.scans = _Scans(store, clock)
        self.backtests = _Backtests(store, clock)
        self.paper = _Paper(store)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


class FakeRedis:
    """Just enough of redis.asyncio.Redis for the token service and health check."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.data[key] = value

    async def getdel(self, key: str) -> str | None:
        return self.data.pop(key, None)

    async def delete(self, key: str) -> None:
        self.data.pop(key, None)

    async def ping(self) -> bool:
        return True


class NoopRateLimiter:
    async def hit(self, key: str, *, limit: int, window_seconds: int, fail_open: bool = True) -> None:
        return None


# ---------------------------------------------------------------- agents


class ScriptedWriter:
    """Returns drafts / raises in order, falling back to the template writer; records feedback seen."""

    name = "scripted"

    def __init__(self, *steps: Any) -> None:
        self.steps = list(steps)
        self.feedback_seen: list[list[str]] = []
        self._template = TemplateReportWriter()

    async def write(self, inp: WriterInput, feedback: Sequence[str] = ()) -> ReportDraft:
        self.feedback_seen.append(list(feedback))
        draft = await self._template.write(inp, feedback)
        step = self.steps.pop(0) if self.steps else None
        if isinstance(step, Exception):
            raise step
        if callable(step):
            return step(draft)  # type: ignore[no-any-return]
        return draft


ANALYST_PLANS = {a.name: a.scripted_plan() for a in (*ANALYSTS, *TRADE_ANALYSTS)}


def scripted_policies(name: str) -> AnalystPolicy:
    return ScriptedPolicy(ANALYST_PLANS[name])


class BrokenPolicy:
    async def decide(self, *args: Any) -> Any:
        raise LlmUnavailable("model offline")


@dataclass
class PipelineEnv:
    container: Container
    store: InMemoryStore
    clock: FixedClock
    queue: InlineJobQueue
    bus: InMemoryRunEventBus


async def build_test_env(
    *,
    auth_mode: str = "local",
    writer: ReportWriter | None = None,
    policies: Any = scripted_policies,
    **settings_overrides: Any,
) -> PipelineEnv:
    settings = Settings(
        env="test",
        auth_mode=auth_mode,  # type: ignore[arg-type]
        jwt_secret="test-secret-" + "x" * 32,  # type: ignore[arg-type]
        data_mode="demo",
        **settings_overrides,
    )
    store, clock = InMemoryStore(), FixedClock()
    queue, bus = InlineJobQueue(), InMemoryRunEventBus()

    def uow() -> InMemoryUnitOfWork:
        return InMemoryUnitOfWork(store, clock)

    redis = FakeRedis()
    tokens = JwtTokenService(
        redis,  # type: ignore[arg-type]
        secret=settings.jwt_secret.get_secret_value(),
        issuer="lodestar",
        access_ttl=900,
        refresh_ttl=3600,
    )
    container = assemble(
        settings,
        uow=uow,
        redis=redis,
        bus=bus,
        clock=clock,
        sources=demo_sources(clock),
        queue=queue,
        tokens=tokens,
        rate_limiter=NoopRateLimiter(),
        policies=policies,
        writer=writer or TemplateReportWriter(),
        pace=False,
    )
    await attach_engine(container, InMemorySaver())
    queue.bind(container.pipeline.execute, container.pipeline.resume, scan_runner(container))
    return PipelineEnv(container, store, clock, queue, bus)
