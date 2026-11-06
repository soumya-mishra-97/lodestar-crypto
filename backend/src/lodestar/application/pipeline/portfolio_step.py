"""The Portfolio step: synthesise analyst signals into horizon assessments, add position context.

Both happen in code. No position sizing, no trade instructions: Lodestar describes
what you hold and how concentrated it is, nothing more.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from lodestar.application.pipeline.analysts.base import AnalystResult
from lodestar.domain.evidence import EvidenceBundle, EvidenceRegistry
from lodestar.domain.models import Asset, Horizon, MarketDataBundle
from lodestar.domain.scoring import HorizonAssessment, synthesize

CONCENTRATION_WARNING_PCT = 40.0


def synthesize_assessments(
    analysts: Mapping[str, AnalystResult],
    bundle: MarketDataBundle,
    registry: EvidenceRegistry,
) -> dict[Horizon, HorizonAssessment]:
    signals = [s for a in analysts.values() for s in a.signals]
    risks = {r.horizon: r for a in analysts.values() for r in a.risks}
    optional = [bundle.fundamentals, bundle.liquidity, bundle.sentiment, bundle.exchange]
    out: dict[Horizon, HorizonAssessment] = {}
    for horizon in Horizon:
        a = synthesize(
            horizon,
            signals,
            risks[horizon],
            history_days=len(bundle.history.points),
            optional_sources_present=sum(x is not None for x in optional),
            optional_sources_total=len(optional),
        )
        h, nice = horizon.value, horizon.value.replace("_", "-").capitalize()
        inputs = [i for s in a.signals for i in s.evidence_ids]
        registry.calculate(f"{h}_score", f"{nice} signal score (0-100)", a.score, "index", inputs=inputs)
        registry.calculate(f"{h}_stance", f"{nice} stance", a.stance.value, "text", inputs=inputs)
        registry.calculate(
            f"{h}_confidence_pct", f"{nice} data confidence (%)", a.confidence * 100, "pct", inputs=inputs
        )
        out[horizon] = a
    return out


def position_context(
    asset: Asset,
    valuation: Mapping[str, Any] | None,
    registry: EvidenceRegistry,
) -> dict[str, Any]:
    """Register what the user holds of this asset and how it sits in the tracked portfolio."""
    if valuation is None:
        registry.observe("holds_asset", "Asset held in your tracked portfolio", "unknown", "text", source="portfolio")
        return {"held": False, "available": False}
    positions = valuation.get("positions") or []
    total = float(valuation.get("total_value_usd") or 0.0)
    position = next((p for p in positions if str(p["asset"]["id"]) == str(asset.id)), None)
    registry.calculate("portfolio_value_usd", "Tracked portfolio value (USD)", total, "usd")
    registry.calculate("portfolio_positions", "Assets in your tracked portfolio", float(len(positions)), "count")
    if position is None or not position.get("quantity"):
        registry.observe("holds_asset", "Asset held in your tracked portfolio", "no", "text", source="portfolio")
        return {"held": False, "available": True, "total_value_usd": total, "positions": len(positions)}

    registry.observe("holds_asset", "Asset held in your tracked portfolio", "yes", "text", source="portfolio")
    qty_id = registry.observe(
        "position_quantity", f"{asset.symbol} held (tokens)", float(position["quantity"]), "count", source="portfolio"
    )
    value_id = registry.calculate(
        "position_value_usd", f"Value of your {asset.symbol} (USD)", position.get("value_usd"), "usd", inputs=[qty_id]
    )
    weight_id = registry.calculate(
        "position_weight_pct", f"{asset.symbol} share of tracked portfolio (%)", position.get("weight_pct"), "pct",
        inputs=[value_id, registry.id_of("portfolio_value_usd")],
    )  # fmt: skip
    registry.calculate(
        "position_pnl_pct", f"Unrealised P&L on {asset.symbol} vs cost basis (%)", position.get("pnl_pct"), "pct",
        inputs=[value_id],
    )  # fmt: skip
    weight = position.get("weight_pct") or 0.0
    return {
        "held": True,
        "available": True,
        "quantity": position["quantity"],
        "value_usd": position.get("value_usd"),
        "weight_pct": weight,
        "pnl_pct": position.get("pnl_pct"),
        "total_value_usd": total,
        "positions": len(positions),
        "concentrated": weight >= CONCENTRATION_WARNING_PCT,
        "evidence_ids": [i for i in (qty_id, value_id, weight_id) if i],
    }


def evidence_view(rows: list[dict[str, Any]]) -> EvidenceBundle:
    return EvidenceBundle.from_dicts(rows)
