"""Portfolio maths: allocation, concentration, blended risk and volatility. Pure functions."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Any

from lodestar.domain.indicators import DAYS_PER_YEAR
from lodestar.domain.models import RiskLevel
from lodestar.domain.scoring import risk_level_for


def weights(values: Mapping[str, float]) -> dict[str, float]:
    """Fractional weights (0..1) of each position by value. Non-positive values are ignored."""
    total = sum(v for v in values.values() if v > 0)
    return {k: v / total for k, v in values.items() if v > 0} if total else {}


def herfindahl(ws: Mapping[str, float]) -> float:
    """Herfindahl-Hirschman index of concentration: 1/n (diversified) .. 1 (single asset)."""
    return sum(w * w for w in ws.values())


def daily_returns(closes: Sequence[float]) -> list[float]:
    return [b / a - 1 for a, b in pairwise(closes) if a > 0]


def portfolio_volatility_pct(
    ws: Mapping[str, float], closes: Mapping[str, Sequence[float]], window: int = 30
) -> float | None:
    """Annualised volatility of the value-weighted portfolio over the last `window` days."""
    series = {k: daily_returns(list(closes[k])[-(window + 1) :]) for k in ws if k in closes}
    length = min((len(s) for s in series.values()), default=0)
    if length < 2:
        return None
    blended = [sum(ws[k] * series[k][-length:][i] for k in series) for i in range(length)]
    mean = sum(blended) / length
    var = sum((r - mean) ** 2 for r in blended) / (length - 1)
    return math.sqrt(var) * math.sqrt(DAYS_PER_YEAR) * 100


@dataclass(frozen=True, slots=True)
class PortfolioRisk:
    score: float  # 0..100
    level: RiskLevel
    weighted_asset_risk: float  # value-weighted average of per-asset risk scores
    concentration_hhi: float
    concentration_points: float
    largest_weight_pct: float
    volatility_30d_pct: float | None
    coverage_pct: float  # share of portfolio value with a risk score

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "level": self.level.value,
            "weighted_asset_risk": round(self.weighted_asset_risk, 2),
            "concentration_hhi": round(self.concentration_hhi, 4),
            "concentration_points": self.concentration_points,
            "largest_weight_pct": round(self.largest_weight_pct, 2),
            "volatility_30d_pct": None if self.volatility_30d_pct is None else round(self.volatility_30d_pct, 2),
            "coverage_pct": round(self.coverage_pct, 1),
        }


def concentration_points(hhi: float) -> float:
    """Extra risk for concentrated books. HHI 0.25 is four equal positions."""
    if hhi >= 0.6:
        return 15.0
    if hhi >= 0.4:
        return 10.0
    if hhi >= 0.25:
        return 5.0
    return 0.0


def portfolio_risk(
    ws: Mapping[str, float],
    asset_risk_scores: Mapping[str, float],
    *,
    volatility_30d_pct: float | None = None,
) -> PortfolioRisk | None:
    covered = {k: w for k, w in ws.items() if k in asset_risk_scores}
    coverage = sum(covered.values())
    if not covered or coverage <= 0:
        return None
    weighted = sum(w * asset_risk_scores[k] for k, w in covered.items()) / coverage
    hhi = herfindahl(ws)
    conc = concentration_points(hhi)
    score = round(min(100.0, weighted + conc), 1)
    return PortfolioRisk(
        score=score,
        level=risk_level_for(score),
        weighted_asset_risk=weighted,
        concentration_hhi=hhi,
        concentration_points=conc,
        largest_weight_pct=max(ws.values()) * 100,
        volatility_30d_pct=volatility_30d_pct,
        coverage_pct=coverage * 100,
    )
