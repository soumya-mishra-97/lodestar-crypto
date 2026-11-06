"""Coordinator steps for one coin, shared by the LangGraph trade pipeline and the skills CLI.

    collect -> [news, sentiment, fundamentals, technical, liquidity] -> timing -> scenarios
            -> risk sizing -> backtest -> writer -> verifier (-> human review in the app)

The graph wraps each step in instrumentation, checkpoints and streaming; the CLI calls
them in sequence without a database. Same functions, same numbers.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from lodestar.application.pipeline.analysts.base import Analyst, AnalystContext, AnalystResult
from lodestar.application.pipeline.data_step import CollectionSettings, DataCollector, reconcile, register_data_evidence
from lodestar.application.pipeline.react import PolicyFactory, StepRecord
from lodestar.application.ports import DataSources
from lodestar.application.trading.analysts import TRADE_ANALYSTS
from lodestar.application.trading.common import BAR_DAYS, MIN_BARS, TradingPrefs
from lodestar.application.trading.engines import (
    AccountContext,
    EngineOutput,
    backtester,
    market_scanner,
    risk_position_sizer,
    scenario_stats_engine,
    timing_agent,
)
from lodestar.application.trading.writer import TradePlanWriter, TradeWriterInput
from lodestar.domain.errors import LodestarError
from lodestar.domain.evidence import Evidence, EvidenceBundle, EvidenceRegistry
from lodestar.domain.models import Asset, MarketDataBundle
from lodestar.domain.reconciliation import Reconciliation
from lodestar.domain.trading.bars import Bars
from lodestar.domain.trading.plan import TradePlanDraft, verify_trade_plan
from lodestar.domain.trading.setups import SetupKind, current_levels
from lodestar.domain.verification import VerificationResult

TRADE_COLLECTION = CollectionSettings(history_days=365, candle_days=BAR_DAYS)


@dataclass(slots=True)
class TradeData:
    bundle: MarketDataBundle
    reconciliation: Reconciliation
    bars: Bars
    btc_closes: list[float] | None
    evidence: list[Evidence]
    scan: EngineOutput


async def collect(
    sources: DataSources, asset: Asset, prefs: TradingPrefs, now: datetime, *, polymarket: bool, tolerance_pct: float
) -> TradeData:
    bundle = await DataCollector(sources, TRADE_COLLECTION).collect(asset, polymarket_enabled=polymarket)
    primary = "coingecko" if sources.mode == "live" else "demo"
    rec = reconcile(bundle, tolerance_pct=tolerance_pct, primary_source=primary)
    evidence = register_data_evidence(bundle, rec, primary_source=primary, now=now)
    bars = Bars.from_candles(bundle.candles) if len(bundle.candles) >= MIN_BARS else Bars.from_history(bundle.history)
    btc: list[float] | None
    if asset.coingecko_id == "bitcoin":
        btc = list(bars.close)
    else:
        try:
            btc = (await sources.market.get_history("bitcoin", 365)).closes
        except LodestarError:
            btc = None
    scan = market_scanner(bars, btc, bundle.snapshot.volume_24h_usd, prefs, now)
    return TradeData(bundle, rec, bars, btc, [*evidence, *scan.evidence], scan)


async def run_analyst(
    analyst: Analyst,
    asset: Asset,
    data: TradeData,
    policies: PolicyFactory,
    *,
    max_steps: int,
    now: datetime,
    on_step: Callable[[StepRecord], Awaitable[None]] | None = None,
) -> AnalystResult:
    ctx = AnalystContext(
        asset=asset,
        bundle=data.bundle,
        data=EvidenceBundle(tuple(data.evidence)),
        registry=EvidenceRegistry(analyst.namespace, as_of=now),
        reconciliation=data.reconciliation,
    )

    async def noop(_: StepRecord) -> None:
        return None

    return await analyst.run(ctx, policies(analyst.name), max_steps=max_steps, on_step=on_step or noop)


@dataclass(slots=True)
class TradePlanResult:
    asset: Asset
    data: TradeData
    analysts: dict[str, AnalystResult]
    timing: EngineOutput
    scenarios: EngineOutput
    sizing: EngineOutput
    backtest: EngineOutput
    draft: TradePlanDraft
    verification: VerificationResult
    evidence: list[Evidence] = field(default_factory=list)

    def card(self) -> dict[str, Any]:
        return build_card(
            self.asset,
            self.timing.result,
            self.scenarios.result,
            self.sizing.result,
            self.backtest.result,
            self.data.scan.result,
        )


def build_card(
    asset: Asset,
    timing: dict[str, Any],
    scenarios: dict[str, Any],
    sizing: dict[str, Any],
    backtest: dict[str, Any],
    scan: dict[str, Any],
) -> dict[str, Any]:
    """The structured trade-plan card (the prose lives in the verified draft)."""
    return {
        "asset": {"symbol": asset.symbol, "name": asset.name, "coingecko_id": asset.coingecko_id},
        "setup": {
            k: timing[k] for k in ("kind", "status", "trend_up", "trigger_text", "close", "sma20", "sma50", "atr")
        },
        "timing": {
            "trigger_level": timing["level"],
            "entry_zone": [timing["entry_low"], timing["entry_high"]],
            "invalidation": timing["invalidation"],
            "profit_level": timing["profit_level"],
        },
        "risk": sizing["risk"],
        "size": {k: v for k, v in sizing.items() if k != "risk"},
        "scenarios": {
            k: scenarios[k] for k in ("kind", "horizon_days", "band_pct", "cost_pct", "overall", "scenarios")
        },
        "backtest": {
            "out_of_sample": backtest["out_of_sample"],
            "walk_forward": backtest["walk_forward"],
            "in_sample": backtest["in_sample"],
            "warnings": backtest["warnings"],
            "chosen_params": backtest["chosen_params"],
        },
        "scanner": scan,
    }


async def build_trade_plan(
    sources: DataSources,
    asset: Asset,
    prefs: TradingPrefs,
    account: AccountContext,
    policies: PolicyFactory,
    now: datetime,
    *,
    max_steps: int = 6,
    polymarket: bool = True,
    tolerance_pct: float = 1.5,
) -> TradePlanResult:
    """The whole coordinator flow in-process (used by the skills CLI and tests)."""
    data = await collect(sources, asset, prefs, now, polymarket=polymarket, tolerance_pct=tolerance_pct)
    results = await asyncio.gather(
        *(run_analyst(a, asset, data, policies, max_steps=max_steps, now=now) for a in TRADE_ANALYSTS)
    )
    analysts = {r.name: r for r in results}
    evidence = [*data.evidence, *(e for r in results for e in r.evidence)]
    levels, timing = timing_agent(data.bars, now)
    scen = scenario_stats_engine(data.bars, levels.kind, prefs, now)
    sizing = risk_position_sizer(
        data.bars,
        levels,
        data.bundle,
        data.btc_closes,
        account,
        prefs,
        data.reconciliation.status == "mismatch",
        now,
        data.bundle.order_book,
    )
    _, bt = backtester(data.bars, levels.kind, prefs, now)
    evidence += [*timing.evidence, *scen.evidence, *sizing.evidence, *bt.evidence]
    bundle = EvidenceBundle(tuple(evidence))
    draft = await TradePlanWriter().write(
        TradeWriterInput(asset, bundle, analysts, sizing.result, tuple(data.bundle.data_gaps))
    )
    return TradePlanResult(
        asset, data, analysts, timing, scen, sizing, bt, draft, verify_trade_plan(draft, bundle), evidence
    )


def levels_at(bars: Bars, end: int, kind: SetupKind | None = None) -> Any:
    """Plan levels as they would have been computed on bar `end` (used by the paper replay)."""
    return current_levels(bars.upto(end), kind=kind)
