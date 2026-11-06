"""Market scanner: trend, breakout, volume spike and strength against Bitcoin, ranked in code.

The score is a transparent sum of parts (0-100). Scanning many charts always finds
something that looks like an edge, so a high score is a reason to look closer,
not a signal on its own; the per-coin pipeline and its statistics decide the rest.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from lodestar.domain.trading.bars import Bars
from lodestar.domain.trading.setups import DEFAULT_PARAMS, SetupParams, choose_kind, compute

RS_WINDOW = 30


@dataclass(frozen=True, slots=True)
class ScanMetrics:
    close: float
    above_sma20: bool
    above_sma50: bool
    sma20_above_sma50: bool
    sma20_slope_pct: float  # 10-day change of the 20-day average
    trend_points: int  # 0..4
    breakout: bool  # close above the prior 20-day high
    breakout_distance_pct: float  # how far the close is from that high (negative = below)
    volume_ratio: float  # 7-day vs 30-day average volume
    return_30d_pct: float
    rs_vs_btc_pct: float  # 30-day return minus Bitcoin's
    volume_24h_usd: float | None
    passes_liquidity: bool
    setup_kind: str
    score: float

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


def _pct(a: float, b: float) -> float:
    return (a / b - 1) * 100 if b else 0.0


def scan_metrics(
    bars: Bars,
    btc_closes: Sequence[float] | None,
    *,
    volume_24h_usd: float | None,
    min_volume_usd: float,
    params: SetupParams = DEFAULT_PARAMS,
) -> ScanMetrics:
    if len(bars) < 60:
        raise ValueError("need at least 60 daily bars to scan")
    ind = compute(bars, params)
    i = len(bars) - 1
    c = bars.close[i]
    s20, s50 = ind.sma20[i] or c, ind.sma50[i] or c
    s20_prev = ind.sma20[i - 10] or s20
    slope = _pct(s20, s20_prev)
    trend = int(c > s20) + int(c > s50) + int(s20 > s50) + int(slope > 0)
    level = ind.prior_high[i] or c
    distance = _pct(c, level)
    vols = bars.volume
    v7, v30 = sum(vols[-7:]) / 7, sum(vols[-30:]) / 30
    ratio = v7 / v30 if v30 else 1.0
    ret = _pct(c, bars.close[i - RS_WINDOW])
    btc_ret = _pct(btc_closes[-1], btc_closes[-1 - RS_WINDOW]) if btc_closes and len(btc_closes) > RS_WINDOW else 0.0
    rs = ret - btc_ret

    breakout_pts = 20.0 if distance > 0 else 10.0 if distance > -2 else 0.0
    volume_pts = max(0.0, min(20.0, (ratio - 1) * 40))
    rs_pts = max(0.0, min(20.0, rs / 2 + 10))
    score = trend * 10 + breakout_pts + volume_pts + rs_pts
    return ScanMetrics(
        close=c,
        above_sma20=c > s20,
        above_sma50=c > s50,
        sma20_above_sma50=s20 > s50,
        sma20_slope_pct=slope,
        trend_points=trend,
        breakout=distance > 0,
        breakout_distance_pct=distance,
        volume_ratio=ratio,
        return_30d_pct=ret,
        rs_vs_btc_pct=rs,
        volume_24h_usd=volume_24h_usd,
        passes_liquidity=volume_24h_usd is not None and volume_24h_usd >= min_volume_usd,
        setup_kind=choose_kind(ind, bars, i).value,
        score=round(score, 1),
    )
