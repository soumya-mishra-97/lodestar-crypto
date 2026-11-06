"""Scenario statistics from historical analogs: what happened after past signals of the same setup.

- Entry on the open of the bar after the signal (no look-ahead), exit at the close
  `horizon` bars later, net of round-trip costs.
- Samples never overlap: after a signal, the next one is counted only once the
  previous holding window has ended, so one move is not counted many times.
- Bull / base / bear split outcomes by +/- half of the coin's typical move over the
  horizon (its daily volatility scaled to the horizon).
- Confidence intervals: Wilson for proportions, Student t for means.
These describe the past. Small samples are flagged and must be said out loud.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from lodestar.domain.trading.bars import Bars
from lodestar.domain.trading.setups import DEFAULT_PARAMS, SetupKind, SetupParams, compute, signal_at

Reliability = Literal["insufficient", "small", "adequate"]
MIN_ADEQUATE = 30
MIN_USABLE = 10
_T95 = {
    1: 12.71,
    2: 4.30,
    3: 3.18,
    4: 2.78,
    5: 2.57,
    6: 2.45,
    7: 2.36,
    8: 2.31,
    9: 2.26,
    10: 2.23,
    12: 2.18,
    15: 2.13,
    20: 2.09,
    25: 2.06,
    30: 2.04,
}


def reliability(n: int) -> Reliability:
    if n < MIN_USABLE:
        return "insufficient"
    if n < MIN_ADEQUATE:
        return "small"
    return "adequate"


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n == 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def t_value(df: int) -> float:
    if df <= 0:
        return float("nan")
    for k in sorted(_T95):
        if df <= k:
            return _T95[k]
    return 1.96


def mean_ci(values: Sequence[float]) -> tuple[float, float] | None:
    if len(values) < 2:
        return None
    m = statistics.fmean(values)
    half = t_value(len(values) - 1) * statistics.stdev(values) / math.sqrt(len(values))
    return m - half, m + half


@dataclass(frozen=True, slots=True)
class Outcome:
    signal_index: int
    entry: float
    exit: float
    return_pct: float  # net of costs
    max_drawdown_pct: float  # worst low during the hold vs entry (<= 0)


def analog_outcomes(
    bars: Bars,
    kind: SetupKind,
    *,
    horizon: int,
    cost_pct: float,
    params: SetupParams = DEFAULT_PARAMS,
) -> list[Outcome]:
    """Non-overlapping outcomes of every past signal. `cost_pct` = round-trip fees + slippage."""
    ind = compute(bars, params)
    out: list[Outcome] = []
    i = 0
    last = len(bars) - 1 - horizon
    while i < last:
        if signal_at(kind, ind, bars, i, params):
            entry = bars.open[i + 1]
            exit_ = bars.close[i + horizon]
            low = min(bars.low[i + 1 : i + horizon + 1])
            out.append(
                Outcome(i, entry, exit_, (exit_ / entry - 1) * 100 - cost_pct, min(0.0, (low / entry - 1) * 100))
            )
            i += horizon
        else:
            i += 1
    return out


def horizon_sigma_pct(bars: Bars, horizon: int) -> float:
    rets = [math.log(b / a) for a, b in zip(bars.close, bars.close[1:], strict=False) if a > 0 and b > 0]
    if len(rets) < 2:
        return 0.0
    return statistics.stdev(rets) * math.sqrt(horizon) * 100


@dataclass(frozen=True, slots=True)
class OutcomeStats:
    n: int
    wins: int
    win_rate_pct: float | None
    win_rate_ci: tuple[float, float] | None  # percent
    mean_pct: float | None
    mean_ci: tuple[float, float] | None
    median_pct: float | None
    worst_drawdown_pct: float | None
    reliability: Reliability

    def to_dict(self) -> dict[str, Any]:
        return {
            "n": self.n,
            "wins": self.wins,
            "win_rate_pct": self.win_rate_pct,
            "win_rate_ci": list(self.win_rate_ci) if self.win_rate_ci else None,
            "mean_pct": self.mean_pct,
            "mean_ci": list(self.mean_ci) if self.mean_ci else None,
            "median_pct": self.median_pct,
            "worst_drawdown_pct": self.worst_drawdown_pct,
            "reliability": self.reliability,
        }


def summarize(outcomes: Sequence[Outcome]) -> OutcomeStats:
    n = len(outcomes)
    rets = [o.return_pct for o in outcomes]
    wins = sum(r > 0 for r in rets)
    ci = wilson(wins, n)
    return OutcomeStats(
        n=n,
        wins=wins,
        win_rate_pct=wins / n * 100 if n else None,
        win_rate_ci=(ci[0] * 100, ci[1] * 100) if ci else None,
        mean_pct=statistics.fmean(rets) if rets else None,
        mean_ci=mean_ci(rets),
        median_pct=statistics.median(rets) if rets else None,
        worst_drawdown_pct=min(o.max_drawdown_pct for o in outcomes) if outcomes else None,
        reliability=reliability(n),
    )


@dataclass(frozen=True, slots=True)
class Scenario:
    name: Literal["bull", "base", "bear"]
    definition: str
    count: int
    total: int
    probability_pct: float | None
    probability_ci: tuple[float, float] | None
    mean_pct: float | None
    median_pct: float | None
    worst_drawdown_pct: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "definition": self.definition,
            "count": self.count,
            "total": self.total,
            "probability_pct": self.probability_pct,
            "probability_ci": list(self.probability_ci) if self.probability_ci else None,
            "mean_pct": self.mean_pct,
            "median_pct": self.median_pct,
            "worst_drawdown_pct": self.worst_drawdown_pct,
        }


def scenarios(outcomes: Sequence[Outcome], sigma_pct: float, horizon: int) -> list[Scenario]:
    band = 0.5 * sigma_pct
    groups: dict[str, list[Outcome]] = {"bull": [], "base": [], "bear": []}
    for o in outcomes:
        key = "bull" if o.return_pct > band else "bear" if o.return_pct < -band else "base"
        groups[key].append(o)
    defs = {
        "bull": f"return above +{band:.1f}% after {horizon} days",
        "base": f"return between -{band:.1f}% and +{band:.1f}% after {horizon} days",
        "bear": f"return below -{band:.1f}% after {horizon} days",
    }
    total = len(outcomes)
    out = []
    for name in ("bull", "base", "bear"):
        g = groups[name]
        rets = [o.return_pct for o in g]
        ci = wilson(len(g), total)
        out.append(
            Scenario(
                name=name,
                definition=defs[name],
                count=len(g),
                total=total,
                probability_pct=len(g) / total * 100 if total else None,
                probability_ci=(ci[0] * 100, ci[1] * 100) if ci else None,
                mean_pct=statistics.fmean(rets) if rets else None,
                median_pct=statistics.median(rets) if rets else None,
                worst_drawdown_pct=min(o.max_drawdown_pct for o in g) if g else None,
            )
        )
    return out
