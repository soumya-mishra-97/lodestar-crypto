"""Scanner, backtest and paper-trading use cases."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import structlog

from lodestar.application.ports import Clock, DataSources, JobQueue, PaperAccount, PaperPosition, UnitOfWork
from lodestar.application.serialization import to_jsonable
from lodestar.application.trading.common import TradingPrefs, load_bars
from lodestar.application.trading.engines import AccountContext
from lodestar.domain.errors import ConflictError, LodestarError, NotFoundError, ValidationFailed
from lodestar.domain.models import Asset, ReportKind, ReportStatus
from lodestar.domain.trading.backtest import BacktestConfig, run_backtest
from lodestar.domain.trading.bars import Bars
from lodestar.domain.trading.paper import DailyBar, PaperState, advance
from lodestar.domain.trading.scanner import scan_metrics
from lodestar.domain.trading.setups import SetupKind, current_levels
from lodestar.domain.trading.sizing import SizingInputs, size_position

log = structlog.get_logger(__name__)
UowFactory = Callable[[], UnitOfWork]
PrefsReader = Callable[[UUID], Awaitable[dict[str, Any]]]
SHORTLIST_SIZE = 5
SCAN_DAYS = 120
EXPIRY_BARS = 10
OPEN_STATUSES = ("pending", "triggered", "open")


def scan_json(s: Any) -> dict[str, Any]:
    return to_jsonable(s)  # type: ignore[no-any-return]


class ScanService:
    def __init__(self, uow: UowFactory, sources: DataSources, queue: JobQueue, *, concurrency: int = 3) -> None:
        self._uow, self._s, self._queue = uow, sources, queue
        self._sem = asyncio.Semaphore(concurrency)

    async def request(self, user_id: UUID, universe: str, top_n: int | None) -> dict[str, Any]:
        if universe not in ("watchlist", "top"):
            raise ValidationFailed("universe must be 'watchlist' or 'top'")
        if universe == "top" and not (top_n and 5 <= top_n <= 100):
            raise ValidationFailed("top_n must be between 5 and 100")
        async with self._uow() as uow:
            scan = await uow.scans.create(user_id, universe, top_n if universe == "top" else None, self._s.mode)
            await uow.commit()
        await self._queue.enqueue_scan(scan.id)
        return await self.get(scan.id)

    async def get(self, scan_id: UUID) -> dict[str, Any]:
        async with self._uow() as uow:
            scan = await uow.scans.get(scan_id)
        if scan is None:
            raise NotFoundError("Scan not found")
        return scan_json(scan)

    async def list(self, user_id: UUID, limit: int = 20) -> list[dict[str, Any]]:
        async with self._uow() as uow:
            scans = await uow.scans.list_recent(user_id, limit=limit)
        return [{**scan_json(s), "results": None} for s in scans]

    async def latest(self, user_id: UUID) -> dict[str, Any] | None:
        async with self._uow() as uow:
            scans = await uow.scans.list_recent(user_id, limit=1)
        return scan_json(scans[0]) if scans else None

    async def execute(self, scan_id: UUID, prefs: TradingPrefs) -> None:
        """Worker: score every coin in the universe, rank, mark the liquid shortlist."""
        async with self._uow() as uow:
            scan = await uow.scans.get(scan_id)
            if scan is None or scan.status != "running":
                return
            watch = (
                await uow.watchlist.list_assets(scan.user_id) if scan.universe == "watchlist" and scan.user_id else []
            )
            tracked = {a.coingecko_id: a for a in await uow.assets.list_all()}
        try:
            if scan.universe == "top":
                listings = await self._s.market.top_markets(scan.top_n or 20)
                universe = [(m.coingecko_id, m.symbol, m.name, m.volume_24h_usd, m.market_cap_rank) for m in listings]
            else:
                universe = [(a.coingecko_id, a.symbol, a.name, None, None) for a in watch]
            btc = (await self._s.market.get_history("bitcoin", SCAN_DAYS)).closes
        except LodestarError as exc:
            async with self._uow() as uow:
                await uow.scans.update(scan_id, status="failed", error=str(exc))
                await uow.commit()
            return
        async with self._uow() as uow:
            await uow.scans.update(scan_id, total=len(universe))
            await uow.commit()

        done = 0
        lock = asyncio.Lock()

        async def one(cg: str, sym: str, name: str, volume: float | None, rank: int | None) -> dict[str, Any]:
            nonlocal done
            async with self._sem:
                row: dict[str, Any] = {"coingecko_id": cg, "symbol": sym, "name": name, "market_cap_rank": rank}
                try:
                    history = await self._s.market.get_history(cg, SCAN_DAYS)
                    if volume is None:
                        volume = (await self._s.market.get_snapshot(cg)).volume_24h_usd
                    m = scan_metrics(
                        Bars.from_history(history), btc, volume_24h_usd=volume, min_volume_usd=prefs.min_volume_usd
                    )
                    row |= {
                        "metrics": m.to_dict(),
                        "score": m.score,
                        "passes_liquidity": m.passes_liquidity,
                        "error": None,
                    }
                except (LodestarError, ValueError) as exc:
                    row |= {"metrics": None, "score": None, "passes_liquidity": False, "error": str(exc)[:200]}
                row["asset_id"] = str(tracked[cg].id) if cg in tracked else None
            async with lock:
                done += 1
                async with self._uow() as uow:
                    await uow.scans.update(scan_id, progress=done)
                    await uow.commit()
            return row

        rows = await asyncio.gather(*(one(*u) for u in universe))
        ranked = sorted(rows, key=lambda r: (r["score"] is None, not r["passes_liquidity"], -(r["score"] or 0)))
        shortlist = 0
        for i, r in enumerate(ranked, start=1):
            r["rank"] = i
            r["shortlisted"] = bool(r["passes_liquidity"] and r["score"] is not None and shortlist < SHORTLIST_SIZE)
            shortlist += r["shortlisted"]
        async with self._uow() as uow:
            await uow.scans.update(scan_id, status="completed", results=ranked, progress=len(ranked))
            await uow.commit()
        log.info("scan_completed", scan_id=str(scan_id), coins=len(ranked), shortlist=shortlist)


class BacktestService:
    def __init__(self, uow: UowFactory, sources: DataSources) -> None:
        self._uow, self._s = uow, sources

    async def run(
        self, user_id: UUID | None, asset: Asset, kind: SetupKind, prefs: TradingPrefs, *, run_id: UUID | None = None
    ) -> dict[str, Any]:
        bars = await load_bars(self._s, asset)
        report = await asyncio.to_thread(
            run_backtest,
            bars,
            BacktestConfig(
                kind=kind, horizon=prefs.horizon_days, fee_bps=prefs.fee_bps, slippage_bps=prefs.slippage_bps
            ),
        )
        return await self.save(user_id, asset, kind, report.to_dict(), run_id=run_id)

    async def save(
        self, user_id: UUID | None, asset: Asset, kind: SetupKind, result: dict[str, Any], *, run_id: UUID | None
    ) -> dict[str, Any]:
        o = result["out_of_sample"]
        summary = {
            "symbol": asset.symbol,
            "kind": kind.value,
            "oos_trades": o["trades"],
            "oos_total_return_pct": o["total_return_pct"],
            "oos_buy_hold_pct": o["buy_hold_return_pct"],
            "oos_sharpe": o["sharpe"],
            "warnings": len(result["warnings"]),
            "data_mode": self._s.mode,
        }
        async with self._uow() as uow:
            backtest_id = await uow.backtests.add(
                user_id, asset.id, run_id, kind.value, result["config"], summary, result
            )
            await uow.commit()
        return {"id": str(backtest_id), "summary": summary, "result": result}

    async def list(self, user_id: UUID, asset_id: UUID | None = None) -> list[dict[str, Any]]:
        async with self._uow() as uow:
            rows = await uow.backtests.list_recent(user_id, asset_id=asset_id)
            assets = {a.id: a for a in await uow.assets.list_all()}
        return [{**to_jsonable(r), "asset": to_jsonable(assets.get(r.asset_id))} for r in rows]

    async def get(self, backtest_id: UUID) -> dict[str, Any]:
        async with self._uow() as uow:
            row = await uow.backtests.get(backtest_id)
            asset = await uow.assets.get(row.asset_id) if row else None
        if row is None:
            raise NotFoundError("Backtest not found")
        return {**to_jsonable(row), "asset": to_jsonable(asset)}


def _bar_map(bars: Bars) -> dict[date, DailyBar]:
    return {
        t.date(): DailyBar(t, o, h, lo, c)
        for t, o, h, lo, c in zip(bars.ts, bars.open, bars.high, bars.low, bars.close, strict=True)
    }


def _state(p: PaperPosition) -> PaperState:
    return PaperState(
        status=p.status,  # type: ignore[arg-type]
        trigger=p.trigger,
        entry_high=p.entry_high,
        stop=p.stop,
        profit_level=p.profit_level,
        horizon=p.horizon,
        expiry_bars=p.expiry_bars,
        bars_seen=p.bars_seen,
        bars_held=p.bars_held,
        entry_price=p.entry_price,
        entry_at=p.entry_at,
        exit_price=p.exit_price,
        exit_at=p.exit_at,
        exit_reason=p.exit_reason,
    )


class PaperService:
    """Paper trading with fake money on the same rules as the backtester. Never places orders."""

    def __init__(self, uow: UowFactory, sources: DataSources, clock: Clock, prefs: PrefsReader) -> None:
        self._uow, self._s, self._clock, self._prefs = uow, sources, clock, prefs

    async def _trading_prefs(self, user_id: UUID) -> TradingPrefs:
        return TradingPrefs.from_prefs(await self._prefs(user_id))

    def _today(self) -> date:
        return self._clock.now().date()

    async def account(self, user_id: UUID, *, started_on: date | None = None) -> PaperAccount:
        async with self._uow() as uow:
            acct = await uow.paper.get_account(user_id)
            if acct is None:
                cash = (await self._trading_prefs(user_id)).paper_starting_cash
                acct = PaperAccount(user_id, cash, cash, started_on or self._today(), None)
                await uow.paper.save_account(acct)
                await uow.commit()
        return acct

    async def sizing_context(self, user_id: UUID | None) -> AccountContext:
        if user_id is None:
            return AccountContext(TradingPrefs().paper_starting_cash, {})
        acct = await self.account(user_id)
        async with self._uow() as uow:
            positions = await uow.paper.list_positions(user_id, statuses=["open"])
            assets = {a.id: a for a in await uow.assets.list_all()}
        equity = acct.cash + sum(p.units * (p.entry_price or 0) for p in positions)
        closes: dict[str, list[float]] = {}
        for p in positions:
            a = assets.get(p.asset_id)
            if a and a.symbol not in closes:
                try:
                    closes[a.symbol] = (await self._s.market.get_history(a.coingecko_id, 120)).closes
                except LodestarError:
                    continue
        return AccountContext(equity, closes)

    async def open_from_plan(self, user_id: UUID, report_id: UUID) -> dict[str, Any]:
        """Queue a paper position from an approved trade plan. Paper only: no exchange is contacted."""
        async with self._uow() as uow:
            report = await uow.reports.get(report_id)
        if report is None or report.kind is not ReportKind.TRADE_PLAN or report.content is None:
            raise NotFoundError("Trade plan not found")
        if report.status is not ReportStatus.APPROVED:
            raise ConflictError("Approve the trade plan before paper trading it")
        card = report.content["card"]
        units = float(card["size"]["units"])
        if units <= 0:
            raise ConflictError("This plan has no position size")
        await self.account(user_id)
        async with self._uow() as uow:
            existing = [
                p
                for p in await uow.paper.list_positions(user_id, statuses=list(OPEN_STATUSES))
                if p.report_id == report_id
            ]
            if existing:
                raise ConflictError("This plan is already being paper traded")
            prefs = await self._trading_prefs(user_id)
            position = PaperPosition(
                id=uuid4(),
                user_id=user_id,
                asset_id=report.asset_id,
                report_id=report_id,
                origin="plan",
                status="pending",
                setup_kind=card["setup"]["kind"],
                trigger=float(card["timing"]["trigger_level"]),
                entry_low=float(card["timing"]["entry_zone"][0]),
                entry_high=float(card["timing"]["entry_zone"][1]),
                stop=float(card["timing"]["invalidation"]),
                profit_level=float(card["timing"]["profit_level"]),
                horizon=prefs.horizon_days,
                expiry_bars=EXPIRY_BARS,
                units=units,
                opened_on=self._today(),
                created_at=self._clock.now(),
            )
            await uow.paper.add_position(position)
            await uow.commit()
        return to_jsonable(position)  # type: ignore[no-any-return]

    async def cancel(self, user_id: UUID, position_id: UUID) -> None:
        async with self._uow() as uow:
            p = await uow.paper.get_position(user_id, position_id)
            if p is None:
                raise NotFoundError("Position not found")
            if p.status not in ("pending", "triggered"):
                raise ConflictError(
                    "Only positions waiting for their trigger can be cancelled; open ones exit by their rules"
                )
            await uow.paper.save_position(
                replace(p, status="cancelled", exit_reason="cancelled by you", exit_at=self._clock.now())
            )
            await uow.commit()

    async def reset(self, user_id: UUID, *, started_on: date | None = None) -> PaperAccount:
        async with self._uow() as uow:
            await uow.paper.reset(user_id)
            await uow.commit()
        return await self.account(user_id, started_on=started_on)

    async def tick_all(self) -> int:
        async with self._uow() as uow:
            users = await uow.paper.all_user_ids()
        for user_id in users:
            await self.tick(user_id)
        return len(users)

    async def tick(self, user_id: UUID) -> dict[str, Any]:
        """Process every completed daily bar since the last run (yesterday is the latest complete bar)."""
        acct = await self.account(user_id)
        prefs = await self._trading_prefs(user_id)
        last_complete = self._today() - timedelta(days=1)
        start = (acct.last_processed or acct.started_on - timedelta(days=1)) + timedelta(days=1)
        if start > last_complete:
            return {"processed_days": 0}
        async with self._uow() as uow:
            positions = await uow.paper.list_positions(user_id)
            assets = {a.id: a for a in await uow.assets.list_all()}
        bars_by_asset: dict[UUID, dict[date, DailyBar]] = {}
        for asset_id in {p.asset_id for p in positions}:
            try:
                bars_by_asset[asset_id] = _bar_map(await load_bars(self._s, assets[asset_id]))
            except LodestarError as exc:
                log.warning("paper_bars_unavailable", asset=str(asset_id), error=str(exc))
                bars_by_asset[asset_id] = {}

        cash = acct.cash
        fee = prefs.fee_bps / 10_000
        live = {p.id: p for p in positions}
        equity_points: list[tuple[date, float, float]] = []
        day = start
        while day <= last_complete:
            for pid in list(live):
                p = live[pid]
                if p.status not in OPEN_STATUSES or day <= p.opened_on:
                    continue
                bar = bars_by_asset.get(p.asset_id, {}).get(day)
                if bar is None:
                    continue
                state, fill = advance(_state(p), bar, slippage_bps=prefs.slippage_bps)
                p = replace(
                    p,
                    status=state.status,
                    bars_seen=state.bars_seen,
                    bars_held=state.bars_held,
                    entry_price=state.entry_price,
                    entry_at=state.entry_at,
                    exit_price=state.exit_price,
                    exit_at=state.exit_at,
                    exit_reason=state.exit_reason,
                )
                if state.status == "open" and p.entry_price is not None and fill is not None and fill.side == "buy":
                    cost = p.units * p.entry_price
                    if cost * (1 + fee) > cash:
                        p = replace(
                            p,
                            status="cancelled",
                            exit_reason="insufficient paper cash",
                            entry_price=None,
                            entry_at=None,
                        )
                    else:
                        cash -= cost * (1 + fee)
                        p = replace(p, fees_usd=cost * fee)
                entry_px, exit_px = p.entry_price, p.exit_price
                if state.status == "closed" and entry_px is not None and exit_px is not None:
                    if fill is not None and fill.side == "sell" and state.entry_at == bar.ts:
                        # Entered and exited on the same bar: book the entry cost first.
                        cost = p.units * entry_px
                        cash -= cost * (1 + fee)
                        p = replace(p, fees_usd=cost * fee)
                    proceeds = p.units * exit_px
                    exit_fee = proceeds * fee
                    cash += proceeds - exit_fee
                    p = replace(
                        p,
                        fees_usd=p.fees_usd + exit_fee,
                        pnl_usd=proceeds - exit_fee - p.units * entry_px - p.fees_usd,
                    )
                live[pid] = p
            marked = sum(
                p.units * bars_by_asset[p.asset_id][day].close
                for p in live.values()
                if p.status == "open" and day in bars_by_asset.get(p.asset_id, {})
            )
            equity_points.append((day, cash + marked, cash))
            day += timedelta(days=1)

        async with self._uow() as uow:
            for p in live.values():
                await uow.paper.save_position(p)
            for d, eq, c in equity_points:
                await uow.paper.save_equity(user_id, d, eq, c)
            await uow.paper.save_account(replace(acct, cash=cash, last_processed=last_complete))
            await uow.commit()
        return {"processed_days": len(equity_points)}

    async def performance(self, user_id: UUID) -> dict[str, Any]:
        acct = await self.account(user_id)
        async with self._uow() as uow:
            positions = await uow.paper.list_positions(user_id)
            series = await uow.paper.equity_series(user_id)
            assets = {a.id: a for a in await uow.assets.list_all()}
        marks: dict[UUID, float] = {}
        for p in positions:
            if p.status == "open" and p.asset_id not in marks:
                try:
                    marks[p.asset_id] = (await self._s.market.get_snapshot(assets[p.asset_id].coingecko_id)).price_usd
                except LodestarError:
                    marks[p.asset_id] = p.entry_price or 0.0
        open_value = sum(p.units * marks.get(p.asset_id, 0.0) for p in positions if p.status == "open")
        equity = acct.cash + open_value
        closed = [p for p in positions if p.status == "closed" and p.pnl_usd is not None]
        wins = [p for p in closed if (p.pnl_usd or 0) > 0]
        peak, max_dd = acct.starting_cash, 0.0
        for _, e, _c in series:
            peak = max(peak, e)
            max_dd = min(max_dd, (e / peak - 1) * 100)
        benchmark = await self._btc_benchmark(acct, [d for d, _, _ in series])

        def row(p: PaperPosition) -> dict[str, Any]:
            a = assets.get(p.asset_id)
            mark = marks.get(p.asset_id)
            unrealised = (p.units * (mark - p.entry_price)) if p.status == "open" and mark and p.entry_price else None
            return {**to_jsonable(p), "asset": to_jsonable(a), "mark_price": mark, "unrealised_usd": unrealised}

        return {
            "account": to_jsonable(acct),
            "equity_usd": equity,
            "open_value_usd": open_value,
            "return_pct": (equity / acct.starting_cash - 1) * 100 if acct.starting_cash else 0.0,
            "realised_pnl_usd": sum(p.pnl_usd or 0 for p in closed),
            "closed_trades": len(closed),
            "win_rate_pct": len(wins) / len(closed) * 100 if closed else None,
            "max_drawdown_pct": max_dd,
            "equity": [{"date": d.isoformat(), "equity": e, "cash": c} for d, e, c in series],
            "benchmark": benchmark,
            "positions": [row(p) for p in sorted(positions, key=lambda p: p.created_at, reverse=True)],
            "data_mode": self._s.mode,
        }

    async def _btc_benchmark(self, acct: PaperAccount, days: list[date]) -> dict[str, Any] | None:
        if not days:
            return None
        try:
            history = await self._s.market.get_history("bitcoin", 365)
        except LodestarError:
            return None
        closes = {p.ts.date(): p.price for p in history.points}
        base_day = next((d for d in sorted(closes) if d >= days[0] - timedelta(days=1)), None)
        if base_day is None:
            return None
        base = closes[base_day]
        points: list[dict[str, Any]] = [
            {"date": d.isoformat(), "value": acct.starting_cash * closes[d] / base} for d in days if d in closes
        ]
        return {
            "label": "Bitcoin buy-and-hold",
            "points": points,
            "return_pct": (points[-1]["value"] / acct.starting_cash - 1) * 100 if points else None,
        }

    async def seed_demo_replay(self, user_id: UUID, assets: list[Asset], *, days_back: int = 75) -> int:
        """Demo mode only: start the paper account in the past and queue plans as they would have been
        computed then, so the engine has synthetic history to process. Clearly labelled 'demo_replay'."""
        if self._s.mode != "demo":
            raise ValidationFailed("Demo replay is only available in demo mode")
        prefs = await self._trading_prefs(user_id)
        start = self._today() - timedelta(days=days_back)
        await self.reset(user_id, started_on=start)
        created = 0
        for k, asset in enumerate(assets):
            bars = await load_bars(self._s, asset)
            for offset in (days_back - 5 - 3 * k, days_back // 2 - 3 * k):
                day = self._today() - timedelta(days=offset)
                idx = max(i for i, t in enumerate(bars.ts) if t.date() <= day)
                lv = current_levels(bars.upto(idx))
                sizing = size_position(
                    SizingInputs(
                        lv.entry_mid,
                        lv.invalidation,
                        prefs.paper_starting_cash,
                        prefs.max_loss_pct,
                        prefs.max_position_pct,
                        prefs.max_slippage_pct,
                        prefs.fee_bps,
                        prefs.slippage_bps,
                    )
                )
                if sizing.units <= 0:
                    continue
                position = PaperPosition(
                    id=uuid4(),
                    user_id=user_id,
                    asset_id=asset.id,
                    report_id=None,
                    origin="demo_replay",
                    status="pending",
                    setup_kind=lv.kind.value,
                    trigger=lv.level,
                    entry_low=lv.entry_low,
                    entry_high=lv.entry_high,
                    stop=lv.invalidation,
                    profit_level=lv.profit_level,
                    horizon=prefs.horizon_days,
                    expiry_bars=EXPIRY_BARS,
                    units=sizing.units,
                    opened_on=day,
                    created_at=datetime.combine(day, datetime.min.time(), tzinfo=self._clock.now().tzinfo),
                )
                async with self._uow() as uow:
                    await uow.paper.add_position(position)
                    await uow.commit()
                created += 1
        await self.tick(user_id)
        return created
