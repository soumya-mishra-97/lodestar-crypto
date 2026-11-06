"""Deterministic signals, horizon assessments and per-horizon risk.

Scores, stances and risk levels are computed here, by code, from registered
evidence. The LLM never produces or alters them; it only explains them.
Weights are transparent heuristics, not predictions. Tune them in one place.

Every rule takes an evidence resolver (`ev(key) -> id`) so each signal and risk
factor carries the ids of the evidence it was derived from.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from lodestar.domain.indicators import IndicatorSet
from lodestar.domain.models import (
    Fundamentals,
    Horizon,
    LiquidityProfile,
    MarketSnapshot,
    RiskLevel,
    SentimentSnapshot,
    Stance,
    TvlSnapshot,
)

BASELINE = 50.0
FAVORABLE_AT = 60.0
UNFAVORABLE_AT = 40.0

EvidenceResolver = Callable[[str], str | None]

H_SHORT, H_LONG = Horizon.SHORT_TERM, Horizon.LONG_TERM


@dataclass(frozen=True, slots=True)
class Signal:
    name: str
    horizon: Horizon
    contribution: float  # points added to (or removed from) the 50 baseline
    detail: str
    evidence_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "horizon": self.horizon.value,
            "contribution": self.contribution,
            "detail": self.detail,
            "evidence_ids": list(self.evidence_ids),
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Signal:
        return cls(d["name"], Horizon(d["horizon"]), float(d["contribution"]), d["detail"], tuple(d["evidence_ids"]))


@dataclass(frozen=True, slots=True)
class RiskFactor:
    name: str
    points: float
    detail: str
    evidence_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "points": self.points,
            "detail": self.detail,
            "evidence_ids": list(self.evidence_ids),
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> RiskFactor:
        return cls(d["name"], float(d["points"]), d["detail"], tuple(d["evidence_ids"]))


@dataclass(frozen=True, slots=True)
class RiskAssessment:
    horizon: Horizon
    level: RiskLevel
    score: float  # 0 (lowest) .. 100 (highest)
    factors: tuple[RiskFactor, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "horizon": self.horizon.value,
            "level": self.level.value,
            "score": self.score,
            "factors": [f.to_dict() for f in self.factors],
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> RiskAssessment:
        return cls(
            Horizon(d["horizon"]),
            RiskLevel(d["level"]),
            float(d["score"]),
            tuple(RiskFactor.from_dict(f) for f in d["factors"]),
        )


@dataclass(frozen=True, slots=True)
class HorizonAssessment:
    horizon: Horizon
    score: float
    stance: Stance
    confidence: float  # 0..1, driven by data completeness, not by the model
    risk: RiskAssessment
    signals: tuple[Signal, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "horizon": self.horizon.value,
            "score": self.score,
            "stance": self.stance.value,
            "confidence": self.confidence,
            "risk": self.risk.to_dict(),
            "signals": [s.to_dict() for s in self.signals],
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> HorizonAssessment:
        return cls(
            Horizon(d["horizon"]),
            float(d["score"]),
            Stance(d["stance"]),
            float(d["confidence"]),
            RiskAssessment.from_dict(d["risk"]),
            tuple(Signal.from_dict(s) for s in d["signals"]),
        )


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def stance_for(score: float) -> Stance:
    if score >= FAVORABLE_AT:
        return Stance.FAVORABLE
    if score <= UNFAVORABLE_AT:
        return Stance.UNFAVORABLE
    return Stance.NEUTRAL


def risk_level_for(score: float) -> RiskLevel:
    if score < 30:
        return RiskLevel.LOW
    if score < 50:
        return RiskLevel.MODERATE
    if score < 70:
        return RiskLevel.HIGH
    return RiskLevel.VERY_HIGH


def _ids(ev: EvidenceResolver, *keys: str) -> tuple[str, ...]:
    return tuple(i for k in keys if (i := ev(k)))


# ---------------------------------------------------------------- technical analyst rules


def technical_signals(ind: IndicatorSet, snap: MarketSnapshot, ev: EvidenceResolver) -> list[Signal]:
    out: list[Signal] = []
    price = ind.last_close
    for label, key, ma in (("20-day", "sma_20", ind.sma_20), ("50-day", "sma_50", ind.sma_50)):
        if ma is not None:
            above = price > ma
            out.append(
                Signal(
                    f"trend_vs_{key}",
                    H_SHORT,
                    6.0 if above else -6.0,
                    f"Price is {'above' if above else 'below'} its {label} average",
                    _ids(ev, "last_close", key),
                )
            )
    if ind.macd is not None:
        up = ind.macd.histogram > 0
        out.append(
            Signal(
                "macd_momentum",
                H_SHORT,
                8.0 if up else -8.0,
                f"MACD histogram is {'positive' if up else 'negative'}",
                _ids(ev, "macd_histogram"),
            )
        )
    if ind.rsi_14 is not None:
        r, ids = ind.rsi_14, _ids(ev, "rsi_14")
        if r < 30:
            out.append(Signal("rsi", H_SHORT, 5.0, "RSI is oversold; a mean-reversion bounce is possible", ids))
        elif r > 70:
            out.append(Signal("rsi", H_SHORT, -7.0, "RSI is overbought; pullback risk is elevated", ids))
        elif 45 <= r <= 65:
            out.append(Signal("rsi", H_SHORT, 3.0, "RSI is in a healthy momentum range", ids))
    if ind.volume_ratio_7d_30d is not None and snap.change_7d_pct is not None:
        vr, ids = ind.volume_ratio_7d_30d, _ids(ev, "volume_ratio_7d_30d", "change_7d_pct")
        if vr > 1.25:
            rising = snap.change_7d_pct > 0
            detail = "Rising volume is " + ("confirming gains" if rising else "accompanying declines")
            out.append(Signal("volume_confirmation", H_SHORT, 6.0 if rising else -6.0, detail, ids))
        elif vr < 0.75:
            out.append(Signal("volume_confirmation", H_SHORT, -2.0, "Trading interest is fading", ids))
    if ind.bollinger is not None:
        ids = _ids(ev, "bollinger_pct_b")
        if ind.bollinger.percent_b > 1:
            out.append(Signal("bollinger", H_SHORT, -4.0, "Price is stretched above the upper Bollinger band", ids))
        elif ind.bollinger.percent_b < 0:
            out.append(Signal("bollinger", H_SHORT, 3.0, "Price is below the lower Bollinger band", ids))
    if ind.volatility_30d_pct is not None and ind.volatility_30d_pct > 120:
        out.append(
            Signal(
                "volatility",
                H_SHORT,
                -5.0,
                "Very high realised volatility widens the range of outcomes",
                _ids(ev, "volatility_30d_pct"),
            )
        )

    # Long-horizon trend evidence also comes from price history.
    if snap.change_1y_pct is not None:
        c = snap.change_1y_pct
        pts = 8.0 if c > 50 else 4.0 if c > 0 else -10.0 if c < -50 else -5.0
        out.append(
            Signal(
                "one_year_performance",
                H_LONG,
                pts,
                f"One-year return is {'positive' if c > 0 else 'negative'}",
                _ids(ev, "change_1y_pct"),
            )
        )
    if ind.sma_200 is not None:
        above = ind.last_close > ind.sma_200
        out.append(
            Signal(
                "trend_vs_sma_200",
                H_LONG,
                8.0 if above else -8.0,
                f"Price is {'above' if above else 'below'} its 200-day average",
                _ids(ev, "last_close", "sma_200"),
            )
        )
    if snap.ath_change_pct is not None:
        d, ids = snap.ath_change_pct, _ids(ev, "ath_change_pct")
        if d < -85:
            out.append(Signal("distance_from_ath", H_LONG, -8.0, "Trading far below its all-time high", ids))
        elif d < -50:
            out.append(Signal("distance_from_ath", H_LONG, -3.0, "Trading well below its all-time high", ids))
        elif d > -20:
            out.append(Signal("distance_from_ath", H_LONG, 3.0, "Trading near its all-time high", ids))
    return out


# ---------------------------------------------------------------- fundamental analyst rules


def fundamental_signals(
    snap: MarketSnapshot,
    fundamentals: Fundamentals | None,
    liquidity: LiquidityProfile | None,
    tvl: TvlSnapshot | None,
    ev: EvidenceResolver,
) -> list[Signal]:
    out: list[Signal] = []
    if snap.market_cap_rank is not None:
        rank, ids = snap.market_cap_rank, _ids(ev, "market_cap_rank")
        if rank <= 20:
            out.append(Signal("market_cap_rank", H_LONG, 8.0, "Top-20 asset by market capitalisation", ids))
        elif rank <= 100:
            out.append(Signal("market_cap_rank", H_LONG, 3.0, "Top-100 asset by market capitalisation", ids))
        elif rank > 300:
            out.append(Signal("market_cap_rank", H_LONG, -6.0, "Small-cap asset by market-cap rank", ids))
    if fundamentals is not None:
        f = fundamentals
        if f.circulating_supply and f.total_supply:
            ratio, ids = f.circulating_supply / f.total_supply, _ids(ev, "circulating_ratio_pct")
            if ratio < 0.5:
                out.append(
                    Signal(
                        "supply_dilution", H_LONG, -8.0, "Under half of total supply circulates; unlock overhang", ids
                    )
                )
            elif ratio < 0.8:
                out.append(
                    Signal("supply_dilution", H_LONG, -3.0, "A meaningful share of supply is not circulating", ids)
                )
            elif ratio >= 0.95:
                out.append(Signal("supply_dilution", H_LONG, 3.0, "Nearly all supply already circulates", ids))
        if f.max_supply is None:
            out.append(
                Signal("supply_cap", H_LONG, -2.0, "No hard supply cap (inflationary design)", _ids(ev, "max_supply"))
            )
    if liquidity is not None:
        if liquidity.depth_2pct_usd is not None:
            ids = _ids(ev, "depth_2pct_usd")
            if liquidity.depth_2pct_usd >= 1_000_000:
                out.append(Signal("liquidity_depth", H_LONG, 4.0, "Deep order books on major venues", ids))
            elif liquidity.depth_2pct_usd < 100_000:
                out.append(Signal("liquidity_depth", H_LONG, -6.0, "Thin order books; large orders move price", ids))
        if liquidity.median_spread_pct is not None and liquidity.median_spread_pct > 1.0:
            out.append(Signal("spread", H_LONG, -3.0, "Wide bid-ask spreads", _ids(ev, "median_spread_pct")))
    if snap.volume_24h_usd and snap.market_cap_usd and snap.volume_24h_usd / snap.market_cap_usd < 0.01:
        out.append(
            Signal("turnover", H_LONG, -3.0, "Low daily turnover relative to market cap", _ids(ev, "turnover_pct"))
        )
    if tvl is not None and tvl.change_30d_pct is not None:
        t, ids = tvl.change_30d_pct, _ids(ev, "tvl_change_30d_pct")
        if t > 10:
            out.append(Signal("ecosystem_tvl", H_LONG, 4.0, "Ecosystem TVL grew over 30 days", ids))
        elif t < -20:
            out.append(Signal("ecosystem_tvl", H_LONG, -4.0, "Ecosystem TVL contracted sharply over 30 days", ids))
    return out


# ---------------------------------------------------------------- sentiment analyst rules


def sentiment_signals(sentiment: SentimentSnapshot | None, ev: EvidenceResolver) -> list[Signal]:
    if sentiment is None:
        return []
    fg, ids = sentiment.fear_greed_value, _ids(ev, "fear_greed")
    if fg <= 25:
        return [Signal("market_sentiment", H_SHORT, 3.0, "Extreme fear market-wide (a contrarian signal)", ids)]
    if fg >= 75:
        return [Signal("market_sentiment", H_SHORT, -4.0, "Extreme greed market-wide", ids)]
    return []


# ---------------------------------------------------------------- risk analyst rules


@dataclass(frozen=True, slots=True)
class RiskInputs:
    volatility_30d_pct: float | None
    max_drawdown_1y_pct: float | None
    depth_2pct_usd: float | None
    market_cap_usd: float | None
    circulating_ratio: float | None
    fear_greed: int | None
    change_7d_pct: float | None
    price_sources_disagree: bool


def assess_risk(horizon: Horizon, r: RiskInputs, ev: EvidenceResolver) -> RiskAssessment:
    """Additive, explainable risk model. Each factor's points are visible in the UI."""
    factors: list[RiskFactor] = []
    short = horizon is Horizon.SHORT_TERM

    if r.volatility_30d_pct is not None:
        v = r.volatility_30d_pct
        pts = 30 if v > 150 else 22 if v > 100 else 14 if v > 60 else 6
        factors.append(
            RiskFactor(
                "volatility",
                pts if short else round(pts * 0.5),
                "30-day annualised volatility",
                _ids(ev, "volatility_30d_pct"),
            )
        )
    if r.depth_2pct_usd is None:
        factors.append(RiskFactor("liquidity", 12, "Order-book depth unavailable", ()))
    else:
        d = r.depth_2pct_usd
        factors.append(
            RiskFactor(
                "liquidity",
                20 if d < 100_000 else 10 if d < 1_000_000 else 3,
                "Order-book depth within 2%",
                _ids(ev, "depth_2pct_usd"),
            )
        )
    if r.price_sources_disagree:
        factors.append(
            RiskFactor(
                "data_disagreement", 8, "Price sources disagree beyond tolerance", _ids(ev, "price_reconciliation")
            )
        )

    if short:
        if r.fear_greed is not None and not 20 < r.fear_greed < 80:
            factors.append(
                RiskFactor("sentiment_extreme", 5, "Market-wide sentiment at an extreme", _ids(ev, "fear_greed"))
            )
        if r.change_7d_pct is not None and abs(r.change_7d_pct) > 25:
            factors.append(RiskFactor("recent_move", 8, "Large 7-day price move", _ids(ev, "change_7d_pct")))
    else:
        if r.max_drawdown_1y_pct is not None:
            dd = r.max_drawdown_1y_pct
            pts = 20 if dd < -70 else 14 if dd < -50 else 8 if dd < -30 else 3
            factors.append(
                RiskFactor("drawdown", pts, "Worst one-year peak-to-trough decline", _ids(ev, "max_drawdown_1y_pct"))
            )
        if r.market_cap_usd is not None:
            mc = r.market_cap_usd
            pts = 15 if mc < 1e8 else 10 if mc < 1e9 else 5 if mc < 1e10 else 2
            factors.append(RiskFactor("size", pts, "Market capitalisation", _ids(ev, "market_cap_usd")))
        if r.circulating_ratio is not None and r.circulating_ratio < 0.8:
            factors.append(
                RiskFactor(
                    "dilution",
                    10 if r.circulating_ratio < 0.5 else 5,
                    "Future supply unlocks",
                    _ids(ev, "circulating_ratio_pct"),
                )
            )

    score = round(_clamp(sum(f.points for f in factors)), 1)
    return RiskAssessment(horizon=horizon, level=risk_level_for(score), score=score, factors=tuple(factors))


# ---------------------------------------------------------------- synthesis (portfolio node)


def synthesize(
    horizon: Horizon,
    signals: Iterable[Signal],
    risk: RiskAssessment,
    *,
    history_days: int,
    optional_sources_present: int,
    optional_sources_total: int,
) -> HorizonAssessment:
    """Combine analyst signals for one horizon into a score, stance and confidence."""
    own = tuple(s for s in signals if s.horizon is horizon)
    total = _clamp(BASELINE + sum(s.contribution for s in own))
    min_history = 60 if horizon is Horizon.SHORT_TERM else 365
    history = min(1.0, history_days / min_history)
    completeness = optional_sources_present / optional_sources_total if optional_sources_total else 1.0
    return HorizonAssessment(
        horizon=horizon,
        score=round(total, 1),
        stance=stance_for(total),
        confidence=round(0.3 + 0.4 * history + 0.3 * completeness, 2),
        risk=risk,
        signals=own,
    )
