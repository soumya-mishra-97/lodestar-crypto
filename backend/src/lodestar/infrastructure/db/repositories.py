"""SQLAlchemy implementations of the repository ports, plus the Unit of Work."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Self
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import distinct_on, insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lodestar.application.ports import (
    BacktestRecord,
    EventRecord,
    PaperAccount,
    PaperPosition,
    ReportRecord,
    ReportSummary,
    RunRecord,
    ScanRecord,
    UserRecord,
)
from lodestar.domain.models import Asset, Holding, ReportKind, ReportStatus, Role, RunStatus
from lodestar.infrastructure.db.models import (
    AssetRow,
    BacktestRow,
    HoldingRow,
    PaperAccountRow,
    PaperEquityRow,
    PaperPositionRow,
    PipelineEventRow,
    PipelineRunRow,
    ReportRow,
    ScanRow,
    UserRow,
    UserSettingsRow,
    WatchlistItemRow,
)
from lodestar.infrastructure.security.crypto import FieldCipher

ACTIVE_RUN = (RunStatus.QUEUED.value, RunStatus.RUNNING.value)
MAX_SEQ_RETRIES = 5


def _now() -> datetime:
    return datetime.now(UTC)


def _user(row: UserRow) -> UserRecord:
    return UserRecord(row.id, row.email, row.password_hash, Role(row.role), row.is_active)


def _asset(row: AssetRow) -> Asset:
    return Asset(id=row.id, coingecko_id=row.coingecko_id, symbol=row.symbol, name=row.name)


def _run(row: PipelineRunRow) -> RunRecord:
    return RunRecord(
        id=row.id,
        asset_id=row.asset_id,
        requested_by=row.requested_by,
        kind=ReportKind(row.kind),
        status=RunStatus(row.status),
        current_step=row.current_step,
        repair_count=row.repair_count,
        error=row.error,
        data_mode=row.data_mode,
        llm_mode=row.llm_mode,
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
    )


def _report(row: ReportRow, *, with_content: bool) -> ReportRecord:
    return ReportRecord(
        id=row.id,
        run_id=row.run_id,
        asset_id=row.asset_id,
        kind=ReportKind(row.kind),
        status=ReportStatus(row.status),
        summary=ReportSummary(
            headline=row.headline,
            short_term_stance=row.short_term_stance,
            long_term_stance=row.long_term_stance,
            short_term_risk=row.short_term_risk,
            long_term_risk=row.long_term_risk,
            setup_kind=row.setup_kind,
            setup_status=row.setup_status,
        ),
        created_at=row.created_at,
        decided_at=row.decided_at,
        decision_note=row.decision_note,
        content=row.content if with_content else None,
    )


class SqlUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def count(self) -> int:
        return int(await self._s.scalar(select(func.count()).select_from(UserRow)) or 0)

    async def get(self, user_id: UUID) -> UserRecord | None:
        row = await self._s.get(UserRow, user_id)
        return _user(row) if row else None

    async def get_by_email(self, email: str) -> UserRecord | None:
        row = await self._s.scalar(select(UserRow).where(UserRow.email == email))
        return _user(row) if row else None

    async def add(self, email: str, password_hash: str, role: Role) -> UserRecord:
        row = UserRow(email=email, password_hash=password_hash, role=role.value)
        self._s.add(row)
        await self._s.flush()
        return _user(row)


class SqlAssetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get(self, asset_id: UUID) -> Asset | None:
        row = await self._s.get(AssetRow, asset_id)
        return _asset(row) if row else None

    async def get_by_coingecko_id(self, coingecko_id: str) -> Asset | None:
        row = await self._s.scalar(select(AssetRow).where(AssetRow.coingecko_id == coingecko_id))
        return _asset(row) if row else None

    async def add(self, coingecko_id: str, symbol: str, name: str) -> Asset:
        stmt = (
            insert(AssetRow)
            .values(coingecko_id=coingecko_id, symbol=symbol[:20], name=name[:120])
            .on_conflict_do_nothing(index_elements=["coingecko_id"])
        )
        await self._s.execute(stmt)
        asset = await self.get_by_coingecko_id(coingecko_id)
        if asset is None:  # pragma: no cover - insert-or-select cannot miss
            raise RuntimeError("asset upsert failed")
        return asset

    async def list_all(self) -> list[Asset]:
        rows = await self._s.scalars(select(AssetRow).order_by(AssetRow.name))
        return [_asset(r) for r in rows]


class SqlRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def create(
        self, asset_id: UUID, requested_by: UUID | None, kind: ReportKind, *, data_mode: str, llm_mode: str
    ) -> RunRecord:
        row = PipelineRunRow(
            asset_id=asset_id,
            requested_by=requested_by,
            kind=kind.value,
            status=RunStatus.QUEUED.value,
            repair_count=0,
            data_mode=data_mode,
            llm_mode=llm_mode[:64],
            created_at=_now(),
        )
        self._s.add(row)
        await self._s.flush()
        return _run(row)

    async def get(self, run_id: UUID) -> RunRecord | None:
        row = await self._s.get(PipelineRunRow, run_id)
        return _run(row) if row else None

    async def list(self, *, asset_id: UUID | None = None, limit: int = 50) -> list[RunRecord]:
        q = select(PipelineRunRow)
        if asset_id is not None:
            q = q.where(PipelineRunRow.asset_id == asset_id)
        rows = await self._s.scalars(q.order_by(PipelineRunRow.created_at.desc()).limit(limit))
        return [_run(r) for r in rows]

    async def active_for_asset(self, asset_id: UUID, kind: ReportKind | None = None) -> RunRecord | None:
        q = select(PipelineRunRow).where(PipelineRunRow.asset_id == asset_id, PipelineRunRow.status.in_(ACTIVE_RUN))
        if kind is not None:
            trade = ReportKind.TRADE_PLAN.value
            q = (
                q.where(PipelineRunRow.kind == trade)
                if kind is ReportKind.TRADE_PLAN
                else q.where(PipelineRunRow.kind != trade)
            )
        row = await self._s.scalar(q.order_by(PipelineRunRow.created_at.desc()).limit(1))
        return _run(row) if row else None

    async def update(
        self,
        run_id: UUID,
        *,
        status: RunStatus | None = None,
        current_step: str | None = None,
        repair_count: int | None = None,
        error: str | None = None,
    ) -> None:
        row = await self._s.get(PipelineRunRow, run_id)
        if row is None:
            return
        if status is not None:
            row.status = status.value
            if status is RunStatus.RUNNING and row.started_at is None:
                row.started_at = _now()
            if status in (RunStatus.AWAITING_APPROVAL, RunStatus.APPROVED, RunStatus.REJECTED, RunStatus.FAILED):
                row.finished_at = row.finished_at or _now()
        if current_step is not None:
            row.current_step = current_step
        if repair_count is not None:
            row.repair_count = repair_count
        if error is not None:
            row.error = error[:2000]


class SqlEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def append(
        self, run_id: UUID, *, ts: datetime, step: str, type: str, status: str | None, payload: dict[str, Any]
    ) -> EventRecord:
        for _ in range(MAX_SEQ_RETRIES):
            try:
                async with self._s.begin_nested():  # savepoint: a lost race rolls back only this insert
                    seq = int(await self.max_seq(run_id)) + 1
                    self._s.add(
                        PipelineEventRow(
                            run_id=run_id, seq=seq, ts=ts, step=step, type=type, status=status, payload=payload
                        )
                    )
                    await self._s.flush()
                return EventRecord(run_id, seq, ts, step, type, status, payload)
            except IntegrityError:
                continue  # another process took this seq; read the new max and retry
        raise RuntimeError("could not allocate an event sequence number")

    async def list(self, run_id: UUID, *, after_seq: int = 0) -> list[EventRecord]:
        rows = await self._s.scalars(
            select(PipelineEventRow)
            .where(PipelineEventRow.run_id == run_id, PipelineEventRow.seq > after_seq)
            .order_by(PipelineEventRow.seq)
        )
        return [EventRecord(r.run_id, r.seq, r.ts, r.step, r.type, r.status, r.payload) for r in rows]

    async def max_seq(self, run_id: UUID) -> int:
        value = await self._s.scalar(select(func.max(PipelineEventRow.seq)).where(PipelineEventRow.run_id == run_id))
        return int(value or 0)


class SqlReportRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def create(
        self, run_id: UUID, asset_id: UUID, kind: ReportKind, summary: ReportSummary, content: dict[str, Any]
    ) -> UUID:
        existing = await self._s.scalar(select(ReportRow.id).where(ReportRow.run_id == run_id))
        if existing is not None:
            return existing
        row = ReportRow(
            run_id=run_id,
            asset_id=asset_id,
            kind=kind.value,
            status=ReportStatus.PENDING_APPROVAL.value,
            headline=summary.headline,
            short_term_stance=summary.short_term_stance,
            long_term_stance=summary.long_term_stance,
            short_term_risk=summary.short_term_risk,
            long_term_risk=summary.long_term_risk,
            setup_kind=summary.setup_kind,
            setup_status=summary.setup_status,
            content=content,
            created_at=_now(),
        )
        self._s.add(row)
        await self._s.flush()
        return row.id

    async def get(self, report_id: UUID) -> ReportRecord | None:
        row = await self._s.get(ReportRow, report_id)
        return _report(row, with_content=True) if row else None

    async def get_by_run(self, run_id: UUID) -> ReportRecord | None:
        row = await self._s.scalar(select(ReportRow).where(ReportRow.run_id == run_id))
        return _report(row, with_content=False) if row else None

    async def list(
        self,
        *,
        kind: ReportKind | None = None,
        status: ReportStatus | None = None,
        asset_id: UUID | None = None,
        limit: int = 50,
    ) -> list[ReportRecord]:
        q = select(ReportRow)
        if kind is not None:
            q = q.where(ReportRow.kind == kind.value)
        if status is not None:
            q = q.where(ReportRow.status == status.value)
        if asset_id is not None:
            q = q.where(ReportRow.asset_id == asset_id)
        rows = await self._s.scalars(q.order_by(ReportRow.created_at.desc()).limit(limit))
        return [_report(r, with_content=False) for r in rows]

    async def latest_for_assets(self, asset_ids: Sequence[UUID]) -> dict[UUID, ReportRecord]:
        if not asset_ids:
            return {}
        q = (
            select(ReportRow)
            .where(
                ReportRow.asset_id.in_(asset_ids),
                ReportRow.status != ReportStatus.REJECTED.value,
                ReportRow.kind != ReportKind.TRADE_PLAN.value,
            )
            .ext(distinct_on(ReportRow.asset_id))  # latest analysis report per asset
            .order_by(ReportRow.asset_id, ReportRow.created_at.desc())
        )
        return {r.asset_id: _report(r, with_content=True) for r in await self._s.scalars(q)}

    async def decide(self, report_id: UUID, status: ReportStatus, *, user_id: UUID | None, note: str | None) -> None:
        row = await self._s.get(ReportRow, report_id)
        if row is None:
            return
        row.status, row.decided_at, row.decided_by = status.value, _now(), user_id
        row.decision_note = note[:1000] if note else None


class SqlWatchlistRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def list_assets(self, user_id: UUID) -> list[Asset]:
        rows = await self._s.scalars(
            select(WatchlistItemRow).where(WatchlistItemRow.user_id == user_id).order_by(WatchlistItemRow.created_at)
        )
        return [_asset(r.asset) for r in rows]

    async def add(self, user_id: UUID, asset_id: UUID) -> None:
        await self._s.execute(
            insert(WatchlistItemRow).values(user_id=user_id, asset_id=asset_id).on_conflict_do_nothing()
        )

    async def remove(self, user_id: UUID, asset_id: UUID) -> None:
        await self._s.execute(
            delete(WatchlistItemRow).where(WatchlistItemRow.user_id == user_id, WatchlistItemRow.asset_id == asset_id)
        )

    async def all_entries(self) -> list[tuple[UUID, UUID]]:
        rows = await self._s.execute(select(WatchlistItemRow.user_id, WatchlistItemRow.asset_id))
        return [(u, a) for u, a in rows.all()]


class SqlPortfolioRepository:
    def __init__(self, session: AsyncSession, cipher: FieldCipher) -> None:
        self._s, self._cipher = session, cipher

    async def list_holdings(self, user_id: UUID) -> list[Holding]:
        rows = await self._s.scalars(
            select(HoldingRow).where(HoldingRow.user_id == user_id).order_by(HoldingRow.created_at)
        )
        return [
            Holding(
                id=r.id,
                asset=_asset(r.asset),
                quantity=float(r.quantity),
                avg_cost_usd=float(r.avg_cost_usd) if r.avg_cost_usd is not None else None,
                source=r.source,
                notes=self._cipher.decrypt(r.notes_encrypted) if r.notes_encrypted else None,
            )
            for r in rows
        ]

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
        values = {
            "user_id": user_id,
            "asset_id": asset_id,
            "source": source[:128],
            "quantity": Decimal(str(quantity)),
            "avg_cost_usd": Decimal(str(avg_cost_usd)) if avg_cost_usd is not None else None,
            "notes_encrypted": self._cipher.encrypt(notes) if notes else None,  # requires a key
        }
        stmt = insert(HoldingRow).values(**values)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_holdings_user_asset_source",
            set_={k: stmt.excluded[k] for k in ("quantity", "avg_cost_usd", "notes_encrypted")}
            | {"updated_at": func.now()},
        )
        await self._s.execute(stmt)

    async def remove(self, user_id: UUID, holding_id: UUID) -> None:
        await self._s.execute(delete(HoldingRow).where(HoldingRow.user_id == user_id, HoldingRow.id == holding_id))


class SqlSettingsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get(self, user_id: UUID) -> dict[str, Any]:
        row = await self._s.get(UserSettingsRow, user_id)
        return dict(row.data) if row else {}

    async def put(self, user_id: UUID, data: dict[str, Any]) -> None:
        stmt = insert(UserSettingsRow).values(user_id=user_id, data=data)
        stmt = stmt.on_conflict_do_update(
            index_elements=["user_id"], set_={"data": stmt.excluded.data, "updated_at": func.now()}
        )
        await self._s.execute(stmt)


def _scan(r: ScanRow) -> ScanRecord:
    return ScanRecord(
        r.id,
        r.user_id,
        r.universe,
        r.top_n,
        r.status,
        r.progress,
        r.total,
        r.results,
        r.error,
        r.data_mode,
        r.created_at,
        r.finished_at,
    )


class SqlScanRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def create(self, user_id: UUID | None, universe: str, top_n: int | None, data_mode: str) -> ScanRecord:
        row = ScanRow(
            user_id=user_id,
            universe=universe,
            top_n=top_n,
            status="running",
            progress=0,
            total=0,
            data_mode=data_mode,
            created_at=_now(),
        )
        self._s.add(row)
        await self._s.flush()
        return _scan(row)

    async def get(self, scan_id: UUID) -> ScanRecord | None:
        row = await self._s.get(ScanRow, scan_id)
        return _scan(row) if row else None

    async def list_recent(self, user_id: UUID | None, *, limit: int = 20) -> list[ScanRecord]:
        rows = await self._s.scalars(
            select(ScanRow).where(ScanRow.user_id == user_id).order_by(ScanRow.created_at.desc()).limit(limit)
        )
        return [_scan(r) for r in rows]

    async def update(
        self,
        scan_id: UUID,
        *,
        status: str | None = None,
        progress: int | None = None,
        total: int | None = None,
        results: list[dict[str, Any]] | None = None,
        error: str | None = None,
    ) -> None:
        row = await self._s.get(ScanRow, scan_id)
        if row is None:
            return
        if status is not None:
            row.status = status
            if status in ("completed", "failed"):
                row.finished_at = _now()
        if progress is not None:
            row.progress = progress
        if total is not None:
            row.total = total
        if results is not None:
            row.results = results
        if error is not None:
            row.error = error[:2000]


def _backtest(r: BacktestRow, *, with_result: bool) -> BacktestRecord:
    return BacktestRecord(
        r.id,
        r.user_id,
        r.asset_id,
        r.run_id,
        r.kind,
        r.config,
        r.summary,
        r.created_at,
        r.result if with_result else None,
    )


class SqlBacktestRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

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
        row = BacktestRow(
            user_id=user_id,
            asset_id=asset_id,
            run_id=run_id,
            kind=kind,
            config=config,
            summary=summary,
            result=result,
            created_at=_now(),
        )
        self._s.add(row)
        await self._s.flush()
        return row.id

    async def get(self, backtest_id: UUID) -> BacktestRecord | None:
        row = await self._s.get(BacktestRow, backtest_id)
        return _backtest(row, with_result=True) if row else None

    async def list_recent(
        self, user_id: UUID | None, *, asset_id: UUID | None = None, limit: int = 50
    ) -> list[BacktestRecord]:
        q = select(BacktestRow).where(BacktestRow.user_id == user_id)
        if asset_id is not None:
            q = q.where(BacktestRow.asset_id == asset_id)
        rows = await self._s.scalars(q.order_by(BacktestRow.created_at.desc()).limit(limit))
        return [_backtest(r, with_result=False) for r in rows]


def _f(v: Decimal | None) -> float | None:
    return float(v) if v is not None else None


def _position(r: PaperPositionRow) -> PaperPosition:
    return PaperPosition(
        id=r.id,
        user_id=r.user_id,
        asset_id=r.asset_id,
        report_id=r.report_id,
        origin=r.origin,
        status=r.status,
        setup_kind=r.setup_kind,
        trigger=float(r.trigger),
        entry_low=float(r.entry_low),
        entry_high=float(r.entry_high),
        stop=float(r.stop),
        profit_level=float(r.profit_level),
        horizon=r.horizon,
        expiry_bars=r.expiry_bars,
        units=float(r.units),
        opened_on=r.opened_on,
        created_at=r.created_at,
        bars_seen=r.bars_seen,
        bars_held=r.bars_held,
        entry_price=_f(r.entry_price),
        entry_at=r.entry_at,
        exit_price=_f(r.exit_price),
        exit_at=r.exit_at,
        exit_reason=r.exit_reason,
        fees_usd=float(r.fees_usd),
        pnl_usd=_f(r.pnl_usd),
    )


def _dec(v: float | None) -> Decimal | None:
    return Decimal(str(v)) if v is not None else None


class SqlPaperRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get_account(self, user_id: UUID) -> PaperAccount | None:
        r = await self._s.get(PaperAccountRow, user_id)
        return (
            PaperAccount(r.user_id, float(r.starting_cash), float(r.cash), r.started_on, r.last_processed)
            if r
            else None
        )

    async def save_account(self, account: PaperAccount) -> None:
        values = {
            "user_id": account.user_id,
            "starting_cash": Decimal(str(account.starting_cash)),
            "cash": Decimal(str(account.cash)),
            "started_on": account.started_on,
            "last_processed": account.last_processed,
        }
        stmt = insert(PaperAccountRow).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["user_id"],
            set_={k: stmt.excluded[k] for k in ("starting_cash", "cash", "started_on", "last_processed")},
        )
        await self._s.execute(stmt)

    async def reset(self, user_id: UUID) -> None:
        for model in (PaperEquityRow, PaperPositionRow, PaperAccountRow):
            await self._s.execute(delete(model).where(model.user_id == user_id))

    def _values(self, p: PaperPosition) -> dict[str, Any]:
        return {
            "user_id": p.user_id,
            "asset_id": p.asset_id,
            "report_id": p.report_id,
            "origin": p.origin,
            "status": p.status,
            "setup_kind": p.setup_kind,
            "trigger": _dec(p.trigger),
            "entry_low": _dec(p.entry_low),
            "entry_high": _dec(p.entry_high),
            "stop": _dec(p.stop),
            "profit_level": _dec(p.profit_level),
            "horizon": p.horizon,
            "expiry_bars": p.expiry_bars,
            "units": _dec(p.units),
            "opened_on": p.opened_on,
            "bars_seen": p.bars_seen,
            "bars_held": p.bars_held,
            "entry_price": _dec(p.entry_price),
            "entry_at": p.entry_at,
            "exit_price": _dec(p.exit_price),
            "exit_at": p.exit_at,
            "exit_reason": p.exit_reason,
            "fees_usd": _dec(p.fees_usd),
            "pnl_usd": _dec(p.pnl_usd),
        }

    async def add_position(self, position: PaperPosition) -> None:
        self._s.add(PaperPositionRow(id=position.id, created_at=position.created_at, **self._values(position)))
        await self._s.flush()

    async def save_position(self, position: PaperPosition) -> None:
        row = await self._s.get(PaperPositionRow, position.id)
        if row is None:
            return
        for key, value in self._values(position).items():
            setattr(row, key, value)

    async def get_position(self, user_id: UUID, position_id: UUID) -> PaperPosition | None:
        row = await self._s.get(PaperPositionRow, position_id)
        return _position(row) if row and row.user_id == user_id else None

    async def list_positions(self, user_id: UUID, *, statuses: Sequence[str] | None = None) -> list[PaperPosition]:
        q = select(PaperPositionRow).where(PaperPositionRow.user_id == user_id)
        if statuses:
            q = q.where(PaperPositionRow.status.in_(list(statuses)))
        rows = await self._s.scalars(q.order_by(PaperPositionRow.opened_on, PaperPositionRow.created_at))
        return [_position(r) for r in rows]

    async def save_equity(self, user_id: UUID, day: date, equity: float, cash: float) -> None:
        stmt = insert(PaperEquityRow).values(
            user_id=user_id, day=day, equity=Decimal(str(equity)), cash=Decimal(str(cash))
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["user_id", "day"], set_={"equity": stmt.excluded.equity, "cash": stmt.excluded.cash}
        )
        await self._s.execute(stmt)

    async def equity_series(self, user_id: UUID) -> list[tuple[date, float, float]]:
        rows = await self._s.execute(
            select(PaperEquityRow.day, PaperEquityRow.equity, PaperEquityRow.cash)
            .where(PaperEquityRow.user_id == user_id)
            .order_by(PaperEquityRow.day)
        )
        return [(d, float(e), float(c)) for d, e, c in rows.all()]

    async def all_user_ids(self) -> list[UUID]:
        return list(await self._s.scalars(select(PaperAccountRow.user_id)))


class SqlAlchemyUnitOfWork:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], cipher: FieldCipher) -> None:
        self._factory, self._cipher = session_factory, cipher

    async def __aenter__(self) -> Self:
        self._session = self._factory()
        self.users = SqlUserRepository(self._session)
        self.assets = SqlAssetRepository(self._session)
        self.runs = SqlRunRepository(self._session)
        self.events = SqlEventRepository(self._session)
        self.reports = SqlReportRepository(self._session)
        self.watchlist = SqlWatchlistRepository(self._session)
        self.portfolio = SqlPortfolioRepository(self._session, self._cipher)
        self.settings = SqlSettingsRepository(self._session)
        self.scans = SqlScanRepository(self._session)
        self.backtests = SqlBacktestRepository(self._session)
        self.paper = SqlPaperRepository(self._session)
        return self

    async def __aexit__(self, *exc: object) -> None:
        if exc[0] is not None:
            await self._session.rollback()
        await self._session.close()  # uncommitted work is discarded

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()
