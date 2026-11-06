"""Deterministic technical indicators over daily closes.

Pure functions, no dependencies: easy to test, safe to run anywhere, and the
single source of truth for every number the LLM is later allowed to mention.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

from lodestar.domain.models import MarketHistory

DAYS_PER_YEAR = 365  # crypto trades every day


def sma(values: Sequence[float], period: int) -> float | None:
    if period <= 0 or len(values) < period:
        return None
    return sum(values[-period:]) / period


def ema_series(values: Sequence[float], period: int) -> list[float]:
    """EMA seeded with the SMA of the first `period` values."""
    if period <= 0 or len(values) < period:
        return []
    k = 2 / (period + 1)
    seed = sum(values[:period]) / period
    out = [seed]
    for v in values[period:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def rsi(values: Sequence[float], period: int = 14) -> float | None:
    """Wilder's RSI."""
    if len(values) <= period:
        return None
    gains = losses = 0.0
    for i in range(1, period + 1):
        delta = values[i] - values[i - 1]
        gains += max(delta, 0.0)
        losses += max(-delta, 0.0)
    avg_gain, avg_loss = gains / period, losses / period
    for i in range(period + 1, len(values)):
        delta = values[i] - values[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(delta, 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-delta, 0.0)) / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


@dataclass(frozen=True, slots=True)
class Macd:
    macd: float
    signal: float
    histogram: float


def macd(values: Sequence[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Macd | None:
    fast_e, slow_e = ema_series(values, fast), ema_series(values, slow)
    if not slow_e:
        return None
    offset = slow - fast
    line = [f - s for f, s in zip(fast_e[offset:], slow_e, strict=False)]
    sig = ema_series(line, signal)
    if not sig:
        return None
    return Macd(macd=line[-1], signal=sig[-1], histogram=line[-1] - sig[-1])


@dataclass(frozen=True, slots=True)
class Bollinger:
    lower: float
    middle: float
    upper: float
    percent_b: float  # 0 = lower band, 1 = upper band


def bollinger(values: Sequence[float], period: int = 20, k: float = 2.0) -> Bollinger | None:
    mid = sma(values, period)
    if mid is None:
        return None
    window = values[-period:]
    sd = math.sqrt(sum((v - mid) ** 2 for v in window) / period)
    lower, upper = mid - k * sd, mid + k * sd
    pct_b = (values[-1] - lower) / (upper - lower) if upper != lower else 0.5
    return Bollinger(lower=lower, middle=mid, upper=upper, percent_b=pct_b)


def log_returns(values: Sequence[float]) -> list[float]:
    return [math.log(b / a) for a, b in pairwise(values) if a > 0 and b > 0]


def realized_volatility_pct(values: Sequence[float], window: int = 30) -> float | None:
    """Annualised standard deviation of daily log returns, in percent."""
    rets = log_returns(values[-(window + 1) :])
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(DAYS_PER_YEAR) * 100


def max_drawdown_pct(values: Sequence[float]) -> float | None:
    """Largest peak-to-trough decline, as a negative percentage."""
    if len(values) < 2:
        return None
    peak, worst = values[0], 0.0
    for v in values:
        peak = max(peak, v)
        if peak > 0:
            worst = min(worst, (v - peak) / peak)
    return worst * 100


def pct_change(values: Sequence[float], lookback: int) -> float | None:
    if len(values) <= lookback or values[-1 - lookback] == 0:
        return None
    return (values[-1] / values[-1 - lookback] - 1) * 100


@dataclass(frozen=True, slots=True)
class IndicatorSet:
    last_close: float
    history_days: int
    sma_20: float | None
    sma_50: float | None
    sma_200: float | None
    rsi_14: float | None
    macd: Macd | None
    bollinger: Bollinger | None
    volatility_30d_pct: float | None
    max_drawdown_1y_pct: float | None
    return_90d_pct: float | None
    volume_ratio_7d_30d: float | None  # >1 means recent volume above monthly average
    support_30d: float | None
    resistance_30d: float | None


def compute_indicators(history: MarketHistory) -> IndicatorSet:
    closes, volumes = history.closes, history.volumes
    vol_7, vol_30 = sma(volumes, 7), sma(volumes, 30)
    last_30 = closes[-30:]
    return IndicatorSet(
        last_close=closes[-1],
        history_days=len(closes),
        sma_20=sma(closes, 20),
        sma_50=sma(closes, 50),
        sma_200=sma(closes, 200),
        rsi_14=rsi(closes, 14),
        macd=macd(closes),
        bollinger=bollinger(closes),
        volatility_30d_pct=realized_volatility_pct(closes, 30),
        max_drawdown_1y_pct=max_drawdown_pct(closes[-DAYS_PER_YEAR:]),
        return_90d_pct=pct_change(closes, 90),
        volume_ratio_7d_30d=(vol_7 / vol_30) if vol_7 is not None and vol_30 else None,
        support_30d=min(last_30) if len(last_30) >= 30 else None,
        resistance_30d=max(last_30) if len(last_30) >= 30 else None,
    )


# ---------------------------------------------------------------- series (for charts)


def sma_series(values: Sequence[float], period: int) -> list[float | None]:
    """Rolling simple moving average, aligned with `values` (None until the window fills)."""
    out: list[float | None] = []
    window_sum = 0.0
    for i, v in enumerate(values):
        window_sum += v
        if i >= period:
            window_sum -= values[i - period]
        out.append(window_sum / period if i >= period - 1 else None)
    return out


def rsi_series(values: Sequence[float], period: int = 14) -> list[float | None]:
    """Wilder's RSI for every point, aligned with `values`."""
    out: list[float | None] = [None] * len(values)
    if len(values) <= period:
        return out
    gains = losses = 0.0
    for i in range(1, period + 1):
        delta = values[i] - values[i - 1]
        gains += max(delta, 0.0)
        losses += max(-delta, 0.0)
    avg_gain, avg_loss = gains / period, losses / period

    def value() -> float:
        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0
        return 100 - 100 / (1 + avg_gain / avg_loss)

    out[period] = value()
    for i in range(period + 1, len(values)):
        delta = values[i] - values[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(delta, 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-delta, 0.0)) / period
        out[i] = value()
    return out


def bollinger_series(
    values: Sequence[float], period: int = 20, k: float = 2.0
) -> list[tuple[float, float, float] | None]:
    """(lower, middle, upper) for every point, aligned with `values`."""
    out: list[tuple[float, float, float] | None] = []
    for i in range(len(values)):
        if i < period - 1:
            out.append(None)
            continue
        window = values[i - period + 1 : i + 1]
        mid = sum(window) / period
        sd = math.sqrt(sum((v - mid) ** 2 for v in window) / period)
        out.append((mid - k * sd, mid, mid + k * sd))
    return out
