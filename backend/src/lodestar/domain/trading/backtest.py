"""Backtester: the setup rules traded on history with costs, out-of-sample and walk-forward.

Execution model (long only, one position at a time, no leverage):
  signal on the close of bar i  ->  buy on the open of bar i+1 (+slippage, +fee)
  stop  = entry - atr_mult x ATR(i)          (if a bar touches both, the stop is assumed first)
  exit  = stop, the profit-taking rule (entry + reward_r x risk), or the close after `horizon` bars
Costs are charged on both sides. Parameters are chosen on in-sample data only and then
judged on data they never saw; walk-forward repeats that across rolling windows.
Results describe the past and are reported with explicit overfitting warnings.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field
from itertools import pairwise, product
from typing import Any

from lodestar.domain.trading.bars import Bars
from lodestar.domain.trading.setups import WARMUP, SetupKind, SetupParams, compute, signal_at

DAYS_PER_YEAR = 365


@dataclass(frozen=True, slots=True)
class BacktestConfig:
    kind: SetupKind
    horizon: int = 14
    fee_bps: float = 10.0  # per side
    slippage_bps: float = 5.0  # per side
    reward_r: float = 2.0
    lookbacks: tuple[int, ...] = (20, 30, 55)
    atr_mults: tuple[float, ...] = (1.5, 2.0, 3.0)
    in_sample_fraction: float = 0.7
    wf_train: int = 240
    wf_test: int = 60
    min_trades_to_rank: int = 3

    def grid(self) -> list[SetupParams]:
        return [
            SetupParams(lookback=lb, atr_mult=am, reward_r=self.reward_r)
            for lb, am in product(self.lookbacks, self.atr_mults)
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "horizon": self.horizon,
            "fee_bps": self.fee_bps,
            "slippage_bps": self.slippage_bps,
            "reward_r": self.reward_r,
            "lookbacks": list(self.lookbacks),
            "atr_mults": list(self.atr_mults),
            "in_sample_fraction": self.in_sample_fraction,
            "wf_train": self.wf_train,
            "wf_test": self.wf_test,
        }


@dataclass(frozen=True, slots=True)
class Trade:
    signal_index: int
    entry_index: int
    exit_index: int
    entry: float
    exit: float
    return_pct: float  # net of fees and slippage
    reason: str  # stop | profit_rule | time

    def to_dict(self, bars: Bars) -> dict[str, Any]:
        return {
            "entry_date": bars.ts[self.entry_index].date().isoformat(),
            "exit_date": bars.ts[self.exit_index].date().isoformat(),
            "entry": self.entry,
            "exit": self.exit,
            "return_pct": round(self.return_pct, 4),
            "reason": self.reason,
            "bars_held": self.exit_index - self.entry_index + 1,
        }


@dataclass(frozen=True, slots=True)
class Metrics:
    trades: int
    win_rate_pct: float | None
    avg_return_pct: float | None
    median_return_pct: float | None
    total_return_pct: float
    max_drawdown_pct: float
    sharpe: float
    profit_factor: float | None
    exposure_pct: float
    buy_hold_return_pct: float
    days: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "trades": self.trades,
            "win_rate_pct": self.win_rate_pct,
            "avg_return_pct": self.avg_return_pct,
            "median_return_pct": self.median_return_pct,
            "total_return_pct": self.total_return_pct,
            "max_drawdown_pct": self.max_drawdown_pct,
            "sharpe": self.sharpe,
            "profit_factor": self.profit_factor,
            "exposure_pct": self.exposure_pct,
            "buy_hold_return_pct": self.buy_hold_return_pct,
            "days": self.days,
        }


@dataclass(slots=True)
class SimResult:
    trades: list[Trade]
    equity: list[float]  # one value per bar in [start, end], starting at 1.0
    start: int
    end: int


def simulate(bars: Bars, kind: SetupKind, params: SetupParams, cfg: BacktestConfig, start: int, end: int) -> SimResult:
    """Trade signals in bars[start..end]. Signals may use earlier bars (indicators); fills never use later ones."""
    ind = compute(bars, params)
    fee, slip = cfg.fee_bps / 10_000, cfg.slippage_bps / 10_000
    equity: list[float] = []
    trades: list[Trade] = []
    cash = 1.0
    pos: dict[str, Any] | None = None
    i = max(start, WARMUP)
    equity.extend([1.0] * (i - start))
    while i <= end:
        if pos is None:
            equity.append(cash)
            if i < end and signal_at(kind, ind, bars, i, params) and ind.atr[i] is not None:
                entry = bars.open[i + 1] * (1 + slip)
                stop = entry - params.atr_mult * (ind.atr[i] or 0.0)
                if stop > 0:
                    pos = {
                        "signal": i,
                        "entry_i": i + 1,
                        "entry": entry,
                        "stop": stop,
                        "tp": entry + params.reward_r * (entry - stop),
                        "cash": cash,
                    }
            i += 1
            continue
        # In position on bar i (entry bar included: we bought at its open).
        exit_price, reason = None, ""
        o, h, lo, c = bars.open[i], bars.high[i], bars.low[i], bars.close[i]
        if lo <= pos["stop"]:
            exit_price, reason = min(o, pos["stop"]) if i > pos["entry_i"] else pos["stop"], "stop"
        elif h >= pos["tp"]:
            exit_price, reason = max(o, pos["tp"]) if i > pos["entry_i"] else pos["tp"], "profit_rule"
        elif i - pos["entry_i"] + 1 >= cfg.horizon or i == end:
            exit_price, reason = c, "time"
        if exit_price is None:
            equity.append(pos["cash"] * (c / pos["entry"]) * (1 - fee))
            i += 1
            continue
        exit_net = exit_price * (1 - slip)
        ret = (exit_net / pos["entry"]) * (1 - fee) * (1 - fee) - 1
        cash = pos["cash"] * (1 + ret)
        equity.append(cash)
        trades.append(Trade(pos["signal"], pos["entry_i"], i, pos["entry"], exit_net, ret * 100, reason))
        pos = None
        i += 1
    return SimResult(trades, equity, start, end)


def metrics(bars: Bars, sim: SimResult) -> Metrics:
    eq = sim.equity
    rets = [t.return_pct for t in sim.trades]
    daily = [b / a - 1 for a, b in pairwise(eq) if a > 0]
    sd = statistics.pstdev(daily) if len(daily) > 1 else 0.0
    sharpe = (statistics.fmean(daily) / sd * math.sqrt(DAYS_PER_YEAR)) if sd > 0 else 0.0
    peak, worst = 1.0, 0.0
    for v in eq:
        peak = max(peak, v)
        worst = min(worst, v / peak - 1)
    gains = sum(r for r in rets if r > 0)
    losses = -sum(r for r in rets if r < 0)
    held = sum(t.exit_index - t.entry_index + 1 for t in sim.trades)
    days = sim.end - sim.start + 1
    first, last = bars.close[sim.start], bars.close[sim.end]
    return Metrics(
        trades=len(rets),
        win_rate_pct=(sum(r > 0 for r in rets) / len(rets) * 100) if rets else None,
        avg_return_pct=statistics.fmean(rets) if rets else None,
        median_return_pct=statistics.median(rets) if rets else None,
        total_return_pct=(eq[-1] - 1) * 100 if eq else 0.0,
        max_drawdown_pct=worst * 100,
        sharpe=sharpe,
        profit_factor=(gains / losses) if losses > 0 else None,
        exposure_pct=held / days * 100 if days else 0.0,
        buy_hold_return_pct=(last / first - 1) * 100,
        days=days,
    )


@dataclass(frozen=True, slots=True)
class GridRow:
    params: SetupParams
    metrics: Metrics


def optimise(bars: Bars, cfg: BacktestConfig, start: int, end: int) -> tuple[SetupParams, list[GridRow]]:
    """Best parameters by Sharpe on [start, end] (only rows with enough trades are eligible)."""
    rows = [GridRow(p, metrics(bars, simulate(bars, cfg.kind, p, cfg, start, end))) for p in cfg.grid()]
    eligible = [r for r in rows if r.metrics.trades >= cfg.min_trades_to_rank] or rows
    best = max(eligible, key=lambda r: (r.metrics.sharpe, r.metrics.total_return_pct))
    return best.params, rows


@dataclass(frozen=True, slots=True)
class Fold:
    train: tuple[int, int]
    test: tuple[int, int]
    params: SetupParams
    train_metrics: Metrics
    test_metrics: Metrics


@dataclass(slots=True)
class BacktestReport:
    config: BacktestConfig
    bars: int
    first_date: str
    last_date: str
    approximate_bars: bool
    chosen: SetupParams
    in_sample: Metrics
    out_of_sample: Metrics
    oos_range: tuple[int, int]
    grid_median_sharpe: float
    folds: list[Fold]
    walk_forward: Metrics | None
    oos_trades: list[dict[str, Any]]
    equity: list[dict[str, Any]]  # OOS equity vs buy & hold, both indexed to 100
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "config": self.config.to_dict(),
            "bars": self.bars,
            "first_date": self.first_date,
            "last_date": self.last_date,
            "approximate_bars": self.approximate_bars,
            "chosen_params": self.chosen.to_dict(),
            "in_sample": self.in_sample.to_dict(),
            "out_of_sample": self.out_of_sample.to_dict(),
            "oos_range": list(self.oos_range),
            "grid_median_sharpe": self.grid_median_sharpe,
            "folds": [
                {
                    "train": list(f.train),
                    "test": list(f.test),
                    "params": f.params.to_dict(),
                    "train_metrics": f.train_metrics.to_dict(),
                    "test_metrics": f.test_metrics.to_dict(),
                }
                for f in self.folds
            ],
            "walk_forward": self.walk_forward.to_dict() if self.walk_forward else None,
            "oos_trades": self.oos_trades,
            "equity": self.equity,
            "warnings": self.warnings,
            "assumptions": [
                "Signals use the close of day i; entries fill at the next day's open (no look-ahead).",
                f"Costs: {self.config.fee_bps:g} bps fee and {self.config.slippage_bps:g} bps slippage on each side.",
                "Long only, one position at a time, no leverage; if a bar touches both the stop and the profit rule, "
                "the stop is assumed first.",
                *(
                    [
                        "Bars were built from daily closes (no exchange OHLC), so intraday highs and lows are "
                        "approximated."
                    ]
                    if self.approximate_bars
                    else []
                ),
            ],
        }


def walk_forward(bars: Bars, cfg: BacktestConfig) -> tuple[list[Fold], Metrics | None, SimResult | None]:
    folds: list[Fold] = []
    trades: list[Trade] = []
    equity: list[float] = []
    start = WARMUP
    while start + cfg.wf_train + cfg.wf_test <= len(bars):
        tr = (start, start + cfg.wf_train - 1)
        te = (tr[1] + 1, tr[1] + cfg.wf_test)
        params, _ = optimise(bars, cfg, *tr)
        train_m = metrics(bars, simulate(bars, cfg.kind, params, cfg, *tr))
        sim = simulate(bars, cfg.kind, params, cfg, *te)
        folds.append(Fold(tr, te, params, train_m, metrics(bars, sim)))
        base = equity[-1] if equity else 1.0
        equity.extend(base * v for v in sim.equity)
        trades.extend(sim.trades)
        start += cfg.wf_test
    if not folds:
        return [], None, None
    stitched = SimResult(trades, equity, folds[0].test[0], folds[-1].test[1])
    return folds, metrics(bars, stitched), stitched


def overfitting_warnings(report: BacktestReport) -> list[str]:
    w: list[str] = []
    ins, oos = report.in_sample, report.out_of_sample
    if oos.trades < 10:
        w.append(f"Only {oos.trades} out-of-sample trades: far too few to tell skill from luck.")
    if ins.sharpe > 0 and oos.sharpe < 0.5 * ins.sharpe:
        w.append("Out-of-sample Sharpe is less than half of in-sample: the chosen parameters look overfitted.")
    if ins.total_return_pct > 0 and oos.total_return_pct < 0:
        w.append("Profitable in-sample but losing out-of-sample.")
    if report.grid_median_sharpe < 0.5 * ins.sharpe and ins.sharpe > 0:
        w.append(
            "The chosen parameters beat the median parameter set by a wide margin: results are sensitive to tuning."
        )
    if len({(f.params.lookback, f.params.atr_mult) for f in report.folds}) > max(1, len(report.folds) // 2):
        w.append("Walk-forward picked different parameters in most windows: the edge is unstable.")
    if (
        report.walk_forward is not None
        and report.walk_forward.total_return_pct < report.walk_forward.buy_hold_return_pct
    ):
        w.append("Walk-forward results trail simply holding the coin over the same windows.")
    gains = sorted((t["return_pct"] for t in report.oos_trades if t["return_pct"] > 0), reverse=True)
    if gains and len(gains) >= 3 and sum(gains[:2]) > 0.6 * sum(gains):
        w.append("Most out-of-sample profit came from two trades: results depend on a few outliers.")
    if report.bars < 2 * DAYS_PER_YEAR:
        w.append(f"Only {report.bars} days of history: fewer than two years of market regimes are covered.")
    if report.approximate_bars:
        w.append("Bars were approximated from daily closes, which understates intraday stops.")
    return w


def run_backtest(bars: Bars, cfg: BacktestConfig) -> BacktestReport:
    if len(bars) < WARMUP + 60:
        raise ValueError(f"need at least {WARMUP + 60} daily bars to backtest, got {len(bars)}")
    split = WARMUP + int((len(bars) - WARMUP) * cfg.in_sample_fraction)
    chosen, grid = optimise(bars, cfg, WARMUP, split - 1)
    ins = metrics(bars, simulate(bars, cfg.kind, chosen, cfg, WARMUP, split - 1))
    oos_sim = simulate(bars, cfg.kind, chosen, cfg, split, len(bars) - 1)
    oos = metrics(bars, oos_sim)
    folds, wf, _ = walk_forward(bars, cfg)
    base = bars.close[split]
    equity = [
        {
            "date": bars.ts[split + k].date().isoformat(),
            "strategy": round(v * 100, 4),
            "buy_hold": round(bars.close[split + k] / base * 100, 4),
        }
        for k, v in enumerate(oos_sim.equity)
    ]
    report = BacktestReport(
        config=cfg,
        bars=len(bars),
        first_date=bars.ts[0].date().isoformat(),
        last_date=bars.ts[-1].date().isoformat(),
        approximate_bars=bars.approximate,
        chosen=chosen,
        in_sample=ins,
        out_of_sample=oos,
        oos_range=(split, len(bars) - 1),
        grid_median_sharpe=statistics.median(r.metrics.sharpe for r in grid),
        folds=folds,
        walk_forward=wf,
        oos_trades=[t.to_dict(bars) for t in oos_sim.trades],
        equity=equity,
    )
    report.warnings = overfitting_warnings(report)
    return report


def summary_line(m: Metrics) -> dict[str, Any]:
    return {
        "trades": m.trades,
        "win_rate_pct": m.win_rate_pct,
        "total_return_pct": m.total_return_pct,
        "sharpe": m.sharpe,
    }


def fmt_range(bars: Bars, r: Sequence[int]) -> str:
    return f"{bars.ts[r[0]].date().isoformat()} to {bars.ts[r[1]].date().isoformat()}"
