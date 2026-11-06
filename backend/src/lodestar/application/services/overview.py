"""The Overview screen: portfolio value, risk, allocation, watchlist and the latest report."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any
from uuid import UUID

from lodestar.application.ports import DataSources, UnitOfWork
from lodestar.application.serialization import to_json_dict, to_jsonable
from lodestar.application.services.portfolio import PortfolioService
from lodestar.application.services.reports import report_json
from lodestar.application.services.runs import run_json
from lodestar.domain import indicators as ta
from lodestar.domain.errors import LodestarError
from lodestar.domain.models import Asset, Horizon, MarketHistory, MarketSnapshot
from lodestar.domain.portfolio import portfolio_risk, portfolio_volatility_pct, weights
from lodestar.domain.scoring import RiskInputs, assess_risk

UowFactory = Callable[[], UnitOfWork]
MAX_ALLOCATION_SLICES = 6


def _no_evidence(_: str) -> None:
    return None


class OverviewService:
    def __init__(self, uow: UowFactory, sources: DataSources, portfolio: PortfolioService) -> None:
        self._uow, self._s, self._portfolio = uow, sources, portfolio

    async def overview(self, user_id: UUID) -> dict[str, Any]:
        valuation_task = asyncio.create_task(self._portfolio.valuation(user_id))
        async with self._uow() as uow:
            watched = await uow.watchlist.list_assets(user_id)
            holdings = await uow.portfolio.list_holdings(user_id)
            held = {h.asset.id: h.asset for h in holdings}
            tracked = {a.id: a for a in watched} | held
            reports = await uow.reports.latest_for_assets(list(tracked))
            recent_runs = await uow.runs.list(limit=6)
            asset_names = {a.id: a for a in await uow.assets.list_all()}
        valuation = await valuation_task

        histories = dict(
            zip(
                tracked,
                await asyncio.gather(*(self._history(a) for a in tracked.values())),
                strict=True,
            )
        )
        snapshots = dict(
            zip(
                [a.id for a in watched],
                await asyncio.gather(*(self._snapshot(a) for a in watched)),
                strict=True,
            )
        )

        # Portfolio risk: value-weighted per-asset risk (latest report, else computed now) + concentration.
        values = {p["asset"]["id"]: p["value_usd"] or 0.0 for p in valuation["positions"]}
        ws = weights(values)
        risk_out: dict[str, Any] = {}
        for horizon in Horizon:
            scores: dict[str, float] = {}
            for p in valuation["positions"]:
                aid = UUID(p["asset"]["id"])
                report = reports.get(aid)
                if report and report.content:
                    scores[str(aid)] = float(report.content["assessments"][horizon.value]["risk"]["score"])
                elif (hist := histories.get(aid)) is not None:
                    scores[str(aid)] = self._live_risk(horizon, hist, p).score
            closes = {str(k): h.closes for k, h in histories.items() if h is not None}
            pr = portfolio_risk(ws, scores, volatility_30d_pct=portfolio_volatility_pct(ws, closes))
            risk_out[horizon.value] = pr.to_dict() if pr else None

        allocation = [
            {"asset": p["asset"], "value_usd": p["value_usd"], "weight_pct": p["weight_pct"]}
            for p in valuation["positions"]
            if p["value_usd"]
        ]
        if len(allocation) > MAX_ALLOCATION_SLICES:
            rest = allocation[MAX_ALLOCATION_SLICES - 1 :]
            allocation = [
                *allocation[: MAX_ALLOCATION_SLICES - 1],
                {
                    "asset": {"id": "other", "symbol": "Other", "name": f"{len(rest)} more"},
                    "value_usd": sum(a["value_usd"] for a in rest),
                    "weight_pct": sum(a["weight_pct"] or 0 for a in rest),
                },
            ]

        watch_rows = []
        for a in watched:
            report = reports.get(a.id)
            hist = histories.get(a.id)
            watch_rows.append(
                {
                    "asset": to_jsonable(a),
                    "snapshot": to_jsonable(snapshots.get(a.id)),
                    "sparkline": [round(v, 10) for v in hist.closes[-30:]] if hist else [],
                    "latest_report": report_json(report, a) if report else None,
                }
            )
        latest = max(reports.values(), key=lambda r: r.created_at, default=None)
        return {
            "data_mode": self._s.mode,
            "portfolio": {k: v for k, v in valuation.items() if k != "positions"}
            | {"positions": len(valuation["positions"])},
            "allocation": allocation,
            "risk": risk_out,
            "watchlist": watch_rows,
            "latest_report": report_json(latest, tracked.get(latest.asset_id)) if latest else None,
            "recent_runs": [run_json(r, asset_names.get(r.asset_id)) for r in recent_runs],
            "market_sentiment": await self._sentiment(),
        }

    def _live_risk(self, horizon: Horizon, hist: MarketHistory, position: dict[str, Any]) -> Any:
        closes = hist.closes
        return assess_risk(
            horizon,
            RiskInputs(
                volatility_30d_pct=ta.realized_volatility_pct(closes, 30),
                max_drawdown_1y_pct=ta.max_drawdown_pct(closes[-365:]),
                depth_2pct_usd=None,
                market_cap_usd=None,
                circulating_ratio=None,
                fear_greed=None,
                change_7d_pct=ta.pct_change(closes, 7),
                price_sources_disagree=False,
            ),
            _no_evidence,
        )

    async def _history(self, asset: Asset) -> MarketHistory | None:
        try:
            return await self._s.market.get_history(asset.coingecko_id, 365)
        except LodestarError:
            return None

    async def _snapshot(self, asset: Asset) -> MarketSnapshot | None:
        try:
            return await self._s.market.get_snapshot(asset.coingecko_id)
        except LodestarError:
            return None

    async def _sentiment(self) -> dict[str, Any] | None:
        try:
            return to_json_dict(await self._s.sentiment.get_market_sentiment())
        except LodestarError:
            return None
