"""Deterministic engine skills: scanner, timing, scenarios, risk sizing, backtest.

Each takes bars and preferences, computes in code, and registers its results as
evidence in its own namespace so the writer can cite them and the verifier can
check every number.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from lodestar.application.trading.common import TradingPrefs
from lodestar.domain import indicators as ta
from lodestar.domain.evidence import Evidence, EvidenceRegistry
from lodestar.domain.models import Horizon, MarketDataBundle, OrderBook
from lodestar.domain.scoring import RiskInputs, assess_risk
from lodestar.domain.trading import backtest as bt
from lodestar.domain.trading import stats
from lodestar.domain.trading.bars import Bars
from lodestar.domain.trading.scanner import scan_metrics
from lodestar.domain.trading.setups import DEFAULT_PARAMS, PlanLevels, SetupKind, current_levels
from lodestar.domain.trading.sizing import SizingInputs, correlation, size_position


@dataclass(slots=True)
class EngineOutput:
    result: dict[str, Any]
    evidence: tuple[Evidence, ...]


def market_scanner(
    bars: Bars, btc_closes: Sequence[float] | None, volume_24h: float | None, prefs: TradingPrefs, now: datetime
) -> EngineOutput:
    m = scan_metrics(bars, btc_closes, volume_24h_usd=volume_24h, min_volume_usd=prefs.min_volume_usd)
    r = EvidenceRegistry("SCN", as_of=now)
    r.calculate("scan_score", "Scanner score (0-100)", m.score, "index")
    r.calculate("trend_points", "Trend checks passed (of 4)", float(m.trend_points), "count")
    r.calculate("breakout_distance_pct", "Close vs prior 20-day high (%)", m.breakout_distance_pct, "pct")
    r.calculate("volume_ratio", "7-day vs 30-day average volume", m.volume_ratio, "ratio")
    r.calculate("rs_vs_btc_pct", "30-day return minus Bitcoin's (%)", m.rs_vs_btc_pct, "pct")
    r.calculate("passes_liquidity", "Passes the liquidity filter", "yes" if m.passes_liquidity else "no", "text")
    return EngineOutput(m.to_dict(), r.items)


def timing_agent(bars: Bars, now: datetime) -> tuple[PlanLevels, EngineOutput]:
    """Conditions, never a moment: entry zone, trigger and invalidation from the setup rules."""
    lv = current_levels(bars, DEFAULT_PARAMS)
    r = EvidenceRegistry("TIM", as_of=now)
    r.calculate("setup_kind", "Setup being tracked", lv.kind.value.replace("_", " "), "text")
    r.calculate("setup_status", "Setup status", lv.status, "text")
    r.calculate(
        "trend_up", "Uptrend (close > 50-day avg and 20-day avg > 50-day avg)", "yes" if lv.trend_up else "no", "text"
    )
    r.calculate("close", "Latest daily close (USD)", lv.close, "usd")
    r.calculate("sma20", "20-day average (USD)", lv.sma20, "usd")
    r.calculate("sma50", "50-day average (USD)", lv.sma50, "usd")
    r.calculate("atr_14", "Average true range, 14 days (USD)", lv.atr, "usd")
    r.calculate("volume_mult", "Breakout volume confirmation (x 20-day average)", DEFAULT_PARAMS.volume_mult, "ratio")
    r.calculate("trigger_level", "Trigger level (USD)", lv.level, "usd")
    r.calculate("entry_zone_low", "Entry zone, low (USD)", lv.entry_low, "usd", inputs=[r.id_of("trigger_level")])
    r.calculate(
        "entry_zone_high",
        "Entry zone, high (USD)",
        lv.entry_high,
        "usd",
        inputs=[r.id_of("trigger_level"), r.id_of("atr_14")],
    )
    r.calculate(
        "invalidation_level",
        "Invalidation level (USD)",
        lv.invalidation,
        "usd",
        inputs=[r.id_of("trigger_level"), r.id_of("atr_14")],
    )
    r.calculate(
        "profit_level",
        "Profit-taking rule level, 2R (USD)",
        lv.profit_level,
        "usd",
        inputs=[r.id_of("entry_zone_low"), r.id_of("invalidation_level")],
    )
    return lv, EngineOutput(lv.to_dict(), r.items)


def scenario_stats_engine(bars: Bars, kind: SetupKind, prefs: TradingPrefs, now: datetime) -> EngineOutput:
    outcomes = stats.analog_outcomes(bars, kind, horizon=prefs.horizon_days, cost_pct=prefs.round_trip_cost_pct)
    summary = stats.summarize(outcomes)
    sigma = stats.horizon_sigma_pct(bars, prefs.horizon_days)
    scenarios = stats.scenarios(outcomes, sigma, prefs.horizon_days)
    r = EvidenceRegistry("SCE", as_of=now)
    r.calculate("horizon_days", "Holding horizon (days)", float(prefs.horizon_days), "days")
    r.calculate("confidence_level_pct", "Confidence level of intervals (%)", 95.0, "pct")
    r.calculate("sample_size", "Past signals of this setup (non-overlapping)", float(summary.n), "count")
    r.calculate("sample_reliability", "Sample reliability", summary.reliability, "text")
    r.calculate("scenario_band_pct", "Scenario band: half the typical move over the horizon (%)", 0.5 * sigma, "pct")
    r.calculate("round_trip_cost_pct", "Round-trip fees + slippage assumed (%)", prefs.round_trip_cost_pct, "pct")
    if summary.n:
        r.calculate("wins", "Past signals with a gain after costs", float(summary.wins), "count")
        r.calculate("win_rate_pct", "Win rate after costs (%)", summary.win_rate_pct, "pct")
        if summary.win_rate_ci:
            r.calculate("win_rate_ci_low_pct", "Win rate, interval low (%)", summary.win_rate_ci[0], "pct")
            r.calculate("win_rate_ci_high_pct", "Win rate, interval high (%)", summary.win_rate_ci[1], "pct")
        r.calculate("mean_return_pct", "Average return after costs (%)", summary.mean_pct, "pct")
        if summary.mean_ci:
            r.calculate("mean_ci_low_pct", "Average return, interval low (%)", summary.mean_ci[0], "pct")
            r.calculate("mean_ci_high_pct", "Average return, interval high (%)", summary.mean_ci[1], "pct")
        r.calculate("median_return_pct", "Median return after costs (%)", summary.median_pct, "pct")
        r.calculate("worst_drawdown_pct", "Worst drawdown during a hold (%)", summary.worst_drawdown_pct, "pct")
    for s in scenarios:
        n = s.name
        if s.total == 0:
            r.calculate(f"scenario_{n}_pct", f"{n.capitalize()} case frequency", "no data", "text")
            continue
        r.calculate(f"scenario_{n}_count", f"{n.capitalize()} case: past signals", float(s.count), "count")
        r.calculate(f"scenario_{n}_pct", f"{n.capitalize()} case frequency (%)", s.probability_pct, "pct")
        if s.probability_ci:
            r.calculate(
                f"scenario_{n}_ci_low_pct",
                f"{n.capitalize()} case frequency, interval low (%)",
                s.probability_ci[0],
                "pct",
            )
            r.calculate(
                f"scenario_{n}_ci_high_pct",
                f"{n.capitalize()} case frequency, interval high (%)",
                s.probability_ci[1],
                "pct",
            )
        r.calculate(f"scenario_{n}_mean_pct", f"{n.capitalize()} case average return (%)", s.mean_pct, "pct")
        r.calculate(f"scenario_{n}_median_pct", f"{n.capitalize()} case median return (%)", s.median_pct, "pct")
        r.calculate(
            f"scenario_{n}_worst_dd_pct", f"{n.capitalize()} case worst drawdown (%)", s.worst_drawdown_pct, "pct"
        )
    return EngineOutput(
        {
            "kind": kind.value,
            "horizon_days": prefs.horizon_days,
            "band_pct": 0.5 * sigma,
            "cost_pct": prefs.round_trip_cost_pct,
            "overall": summary.to_dict(),
            "scenarios": [s.to_dict() for s in scenarios],
            "outcomes": [
                {
                    "date": bars.ts[o.signal_index].date().isoformat(),
                    "return_pct": round(o.return_pct, 4),
                    "max_drawdown_pct": round(o.max_drawdown_pct, 4),
                }
                for o in outcomes
            ],
        },
        r.items,
    )


@dataclass(frozen=True, slots=True)
class AccountContext:
    equity_usd: float
    open_closes: dict[str, list[float]]  # symbol -> closes of assets with open paper positions


def risk_position_sizer(
    bars: Bars,
    levels: PlanLevels,
    bundle: MarketDataBundle,
    btc_closes: Sequence[float] | None,
    account: AccountContext,
    prefs: TradingPrefs,
    price_sources_disagree: bool,
    now: datetime,
    book: OrderBook | None,
) -> EngineOutput:
    closes = list(bars.close)
    corr_btc = correlation(closes[-91:], list(btc_closes or [])[-91:]) if btc_closes else None
    corrs = {
        sym: c
        for sym, other in account.open_closes.items()
        if (c := correlation(closes[-91:], other[-91:])) is not None
    }
    max_corr = max(corrs.values(), default=None)
    sizing = size_position(
        SizingInputs(
            entry=levels.entry_mid,
            stop=levels.invalidation,
            equity_usd=account.equity_usd,
            max_loss_pct=prefs.max_loss_pct,
            max_position_pct=prefs.max_position_pct,
            max_slippage_pct=prefs.max_slippage_pct,
            fee_bps=prefs.fee_bps,
            slippage_bps=prefs.slippage_bps,
            book=book,
            max_correlation=max_corr,
        )
    )
    risk = assess_risk(
        Horizon.SHORT_TERM,
        RiskInputs(
            volatility_30d_pct=ta.realized_volatility_pct(closes, 30),
            max_drawdown_1y_pct=ta.max_drawdown_pct(closes[-365:]),
            depth_2pct_usd=book.depth_usd(2.0)
            if book
            else (bundle.liquidity.depth_2pct_usd if bundle.liquidity else None),
            market_cap_usd=bundle.snapshot.market_cap_usd,
            circulating_ratio=None,
            fear_greed=bundle.sentiment.fear_greed_value if bundle.sentiment else None,
            change_7d_pct=bundle.snapshot.change_7d_pct,
            price_sources_disagree=price_sources_disagree,
        ),
        lambda _: None,
    )
    r = EvidenceRegistry("SIZ", as_of=now)
    r.calculate("equity_usd", "Paper account equity (USD)", account.equity_usd, "usd")
    r.calculate("max_loss_pct", "Max loss per trade (% of account)", prefs.max_loss_pct, "pct")
    r.calculate(
        "max_loss_usd",
        "Max loss per trade (USD)",
        sizing.max_loss_usd,
        "usd",
        inputs=[r.id_of("equity_usd"), r.id_of("max_loss_pct")],
    )
    r.calculate("stop_distance_pct", "Entry midpoint to invalidation (%)", sizing.stop_distance_pct, "pct")
    r.calculate(
        "units",
        "Paper position size (tokens)",
        sizing.units,
        "count",
        inputs=[r.id_of("max_loss_usd"), r.id_of("stop_distance_pct")],
    )
    r.calculate(
        "notional_usd",
        "Paper position value at the entry midpoint (USD)",
        sizing.notional_usd,
        "usd",
        inputs=[r.id_of("units")],
    )
    r.calculate(
        "pct_of_equity",
        "Position value as share of the account (%)",
        sizing.pct_of_equity,
        "pct",
        inputs=[r.id_of("notional_usd"), r.id_of("equity_usd")],
    )
    r.calculate(
        "loss_at_stop_usd",
        "Loss if stopped at invalidation, incl. costs (USD)",
        sizing.loss_at_stop_usd,
        "usd",
        inputs=[r.id_of("units")],
    )
    r.calculate("binding_limit", "Limit that set the size", sizing.binding.replace("_", " "), "text")
    r.calculate("max_position_pct", "Max position size (% of account)", prefs.max_position_pct, "pct")
    if sizing.expected_slippage_pct is not None:
        r.calculate("expected_slippage_pct", "Expected slippage for this size (%)", sizing.expected_slippage_pct, "pct")
    if corr_btc is not None:
        r.calculate("correlation_btc", "Correlation of daily returns with Bitcoin, 90 days", corr_btc, "ratio")
    if max_corr is not None:
        r.calculate(
            "max_correlation_open", "Highest correlation with an open paper position, 90 days", max_corr, "ratio"
        )
    r.calculate("risk_score", "Short-term risk score (0-100)", risk.score, "index")
    r.calculate("risk_level", "Short-term risk level", risk.level.value, "text", inputs=[r.id_of("risk_score")])
    return EngineOutput(
        {
            **sizing.to_dict(),
            "equity_usd": account.equity_usd,
            "entry_reference": levels.entry_mid,
            "stop": levels.invalidation,
            "correlation_btc": corr_btc,
            "correlations_open": corrs,
            "risk": risk.to_dict(),
        },
        r.items,
    )


def backtester(
    bars: Bars, kind: SetupKind, prefs: TradingPrefs, now: datetime
) -> tuple[bt.BacktestReport, EngineOutput]:
    cfg = bt.BacktestConfig(
        kind=kind, horizon=prefs.horizon_days, fee_bps=prefs.fee_bps, slippage_bps=prefs.slippage_bps
    )
    report = bt.run_backtest(bars, cfg)
    o, w = report.out_of_sample, report.walk_forward
    r = EvidenceRegistry("BKT", as_of=now)
    r.calculate("oos_days", "Out-of-sample period (days)", float(o.days), "days")
    r.calculate("oos_trades", "Out-of-sample trades", float(o.trades), "count")
    if o.win_rate_pct is not None:
        r.calculate("oos_win_rate_pct", "Out-of-sample win rate (%)", o.win_rate_pct, "pct")
    r.calculate("oos_total_return_pct", "Out-of-sample total return after costs (%)", o.total_return_pct, "pct")
    r.calculate("oos_buy_hold_pct", "Buy-and-hold return over the same period (%)", o.buy_hold_return_pct, "pct")
    r.calculate("oos_max_drawdown_pct", "Out-of-sample max drawdown (%)", o.max_drawdown_pct, "pct")
    r.calculate("oos_sharpe", "Out-of-sample Sharpe ratio", o.sharpe, "ratio")
    r.calculate("is_sharpe", "In-sample Sharpe ratio", report.in_sample.sharpe, "ratio")
    if w is not None:
        r.calculate("wf_folds", "Walk-forward windows", float(len(report.folds)), "count")
        r.calculate("wf_total_return_pct", "Walk-forward total return after costs (%)", w.total_return_pct, "pct")
        r.calculate("wf_trades", "Walk-forward trades", float(w.trades), "count")
    r.calculate("fee_bps", "Fee per side (bps)", prefs.fee_bps, "count")
    r.calculate("slippage_bps", "Slippage per side (bps)", prefs.slippage_bps, "count")
    r.calculate("warning_count", "Overfitting and reliability warnings", float(len(report.warnings)), "count")
    return report, EngineOutput(report.to_dict(), r.items)
