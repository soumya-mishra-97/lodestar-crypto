"""Long-only setup rules shared by the timing agent, scenario stats and the backtester.

One definition of a "signal" everywhere: what the timing agent describes today is
exactly what the stats engine counted in the past and what the backtester traded.
A signal on bar `i` uses bars `0..i` only; any fill happens on bar `i+1` or later.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any, Literal

from lodestar.domain.trading.bars import Bars, atr_series, prior_highest, rolling_mean

WARMUP = 55  # bars needed before the 50-day average and ATR are defined
RECENT_SIGNAL_BARS = 3


class SetupKind(StrEnum):
    BREAKOUT = "breakout"  # uptrend + first close above the prior N-day high on rising volume
    PULLBACK = "pullback"  # uptrend + close back above the 20-day average after dipping below it
    TREND_RECLAIM = "trend_reclaim"  # close back above the 50-day average after being below it


@dataclass(frozen=True, slots=True)
class SetupParams:
    lookback: int = 20  # breakout window (days)
    atr_mult: float = 2.0  # invalidation distance below the trigger level, in ATRs
    volume_mult: float = 1.2  # breakout volume confirmation vs the 20-day average
    reward_r: float = 2.0  # profit-taking rule, in multiples of the initial risk
    zone_atr: float = 0.5  # entry-zone width above the trigger level, in ATRs

    def to_dict(self) -> dict[str, Any]:
        return {
            "lookback": self.lookback,
            "atr_mult": self.atr_mult,
            "volume_mult": self.volume_mult,
            "reward_r": self.reward_r,
            "zone_atr": self.zone_atr,
        }


DEFAULT_PARAMS = SetupParams()


@dataclass(frozen=True, slots=True)
class Indicators:
    sma20: list[float | None]
    sma50: list[float | None]
    atr: list[float | None]
    vol20: list[float | None]
    prior_high: list[float | None]


def compute(bars: Bars, params: SetupParams = DEFAULT_PARAMS) -> Indicators:
    return Indicators(
        sma20=rolling_mean(bars.close, 20),
        sma50=rolling_mean(bars.close, 50),
        atr=atr_series(bars, 14),
        vol20=rolling_mean(bars.volume, 20),
        prior_high=prior_highest(bars.high, params.lookback),
    )


def _f(v: float | None) -> float:
    return v if v is not None else float("nan")


def trend_up(ind: Indicators, bars: Bars, i: int) -> bool:
    s20, s50 = ind.sma20[i], ind.sma50[i]
    return s20 is not None and s50 is not None and bars.close[i] > s50 and s20 > s50


def signal_at(kind: SetupKind, ind: Indicators, bars: Bars, i: int, params: SetupParams = DEFAULT_PARAMS) -> bool:
    """True when the setup fires on the close of bar `i` (uses bars 0..i only)."""
    if i < WARMUP or i >= len(bars):
        return False
    c, prev = bars.close[i], bars.close[i - 1]
    if kind is SetupKind.BREAKOUT:
        level, prev_level, avg_vol = ind.prior_high[i], ind.prior_high[i - 1], ind.vol20[i - 1]
        if level is None or prev_level is None or not avg_vol:
            return False
        return (
            trend_up(ind, bars, i)
            and c > level
            and prev <= prev_level
            and bars.volume[i] >= params.volume_mult * avg_vol
        )
    if kind is SetupKind.PULLBACK:
        s20, p20 = ind.sma20[i], ind.sma20[i - 1]
        return s20 is not None and p20 is not None and trend_up(ind, bars, i) and prev < p20 and c > s20
    s50, p50 = ind.sma50[i], ind.sma50[i - 1]
    return s50 is not None and p50 is not None and prev <= p50 and c > s50


def signals(
    bars: Bars, kind: SetupKind, params: SetupParams = DEFAULT_PARAMS, ind: Indicators | None = None
) -> list[int]:
    ind = ind or compute(bars, params)
    return [i for i in range(len(bars)) if signal_at(kind, ind, bars, i, params)]


def trigger_level(kind: SetupKind, ind: Indicators, i: int) -> float | None:
    if kind is SetupKind.BREAKOUT:
        return ind.prior_high[i]
    if kind is SetupKind.PULLBACK:
        return ind.sma20[i]
    return ind.sma50[i]


TRIGGER_TEXT = {
    SetupKind.BREAKOUT: "a daily close above the prior {lookback}-day high with volume at least {volume_mult:g}x its "
    "20-day average",
    SetupKind.PULLBACK: "a daily close back above the 20-day average while the trend is up",
    SetupKind.TREND_RECLAIM: "a daily close back above the 50-day average",
}

Status = Literal["active", "extended", "waiting"]


@dataclass(frozen=True, slots=True)
class PlanLevels:
    """Conditions, not predictions: where a long setup would start and what would invalidate it."""

    kind: SetupKind
    status: Status
    trend_up: bool
    level: float  # trigger level
    entry_low: float
    entry_high: float
    invalidation: float
    profit_level: float  # rule: entry midpoint + reward_r x initial risk
    atr: float
    close: float
    sma20: float
    sma50: float
    last_signal_bars_ago: int | None
    trigger_text: str
    params: SetupParams

    @property
    def entry_mid(self) -> float:
        return (self.entry_low + self.entry_high) / 2

    @property
    def risk_per_unit(self) -> float:
        return self.entry_mid - self.invalidation

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "status": self.status,
            "trend_up": self.trend_up,
            "level": self.level,
            "entry_low": self.entry_low,
            "entry_high": self.entry_high,
            "invalidation": self.invalidation,
            "profit_level": self.profit_level,
            "atr": self.atr,
            "close": self.close,
            "sma20": self.sma20,
            "sma50": self.sma50,
            "last_signal_bars_ago": self.last_signal_bars_ago,
            "trigger_text": self.trigger_text,
            "params": self.params.to_dict(),
        }


def choose_kind(ind: Indicators, bars: Bars, i: int) -> SetupKind:
    """Which setup to watch now.

    Breakout when price is extended above the 20-day average, otherwise pullback; trend reclaim in downtrends.
    """
    if not trend_up(ind, bars, i):
        return SetupKind.TREND_RECLAIM
    atr, s20 = ind.atr[i], ind.sma20[i]
    if atr is not None and s20 is not None and bars.close[i] > s20 + 0.5 * atr:
        return SetupKind.BREAKOUT
    return SetupKind.PULLBACK


def current_levels(bars: Bars, params: SetupParams = DEFAULT_PARAMS, kind: SetupKind | None = None) -> PlanLevels:
    if len(bars) <= WARMUP + 1:
        raise ValueError(f"need more than {WARMUP + 1} daily bars, got {len(bars)}")
    ind = compute(bars, params)
    i = len(bars) - 1
    kind = kind or choose_kind(ind, bars, i)
    atr = _f(ind.atr[i])
    recent = [i - j for j in range(RECENT_SIGNAL_BARS + 1) if signal_at(kind, ind, bars, i - j, params)]
    signal_i = recent[0] if recent else None
    # When the setup fired recently, anchor the levels to the signal bar so they don't drift with price.
    anchor = signal_i if signal_i is not None else i
    level = trigger_level(kind, ind, anchor) or bars.close[i]
    entry_low, entry_high = level, level + params.zone_atr * atr
    invalidation = level - params.atr_mult * atr
    mid = (entry_low + entry_high) / 2
    if signal_i is None:
        status: Status = "waiting"
    elif bars.close[i] > entry_high:
        status = "extended"
    else:
        status = "active"
    return PlanLevels(
        kind=kind,
        status=status,
        trend_up=trend_up(ind, bars, i),
        level=level,
        entry_low=entry_low,
        entry_high=entry_high,
        invalidation=invalidation,
        profit_level=mid + params.reward_r * (mid - invalidation),
        atr=atr,
        close=bars.close[i],
        sma20=_f(ind.sma20[i]),
        sma50=_f(ind.sma50[i]),
        last_signal_bars_ago=(i - signal_i) if signal_i is not None else None,
        trigger_text=TRIGGER_TEXT[kind].format(lookback=params.lookback, volume_mult=params.volume_mult),
        params=params,
    )


def with_params(params: SetupParams, **changes: Any) -> SetupParams:
    return replace(params, **changes)
