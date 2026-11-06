"""Risk analyst: per-horizon, itemised risk from volatility, drawdown, liquidity, size, dilution and data quality."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from lodestar.application.pipeline.analysts.base import Analyst, AnalystContext, result, spec
from lodestar.application.pipeline.formatting import fmt
from lodestar.application.pipeline.react import Tool, ToolResult
from lodestar.domain import indicators as ta
from lodestar.domain.claims import Claim, ClaimTag
from lodestar.domain.models import Horizon
from lodestar.domain.scoring import RiskAssessment, RiskInputs, Signal, assess_risk


class RiskAnalyst(Analyst):
    name = "risk"
    namespace = "RSK"
    title = "Risk analyst"
    mandate = (
        "Assess downside risk separately for the short term (days to four weeks) and the long term "
        "(six months or more): volatility, drawdown, liquidity, size, supply dilution, sentiment extremes "
        "and whether independent price sources agree."
    )

    def inputs(self, ctx: AnalystContext) -> RiskInputs:
        closes, b = ctx.bundle.history.closes, ctx.bundle
        src = [ctx.ev("history_days")]
        reg = ctx.registry
        vol = ta.realized_volatility_pct(closes, 30)
        dd = ta.max_drawdown_pct(closes[-365:])
        reg.calculate("volatility_30d_pct", "30-day annualised volatility (%)", vol, "pct", inputs=src)
        reg.calculate("max_drawdown_1y_pct", "Max drawdown over 1 year (%)", dd, "pct", inputs=src)
        ratio = None
        if (f := b.fundamentals) and f.circulating_supply and f.total_supply:
            ratio = f.circulating_supply / f.total_supply
            reg.calculate(
                "circulating_ratio_pct", "Circulating / total supply (%)", ratio * 100, "pct",
                inputs=[ctx.ev("circulating_supply"), ctx.ev("total_supply")],
            )  # fmt: skip
        return RiskInputs(
            volatility_30d_pct=vol,
            max_drawdown_1y_pct=dd,
            depth_2pct_usd=b.liquidity.depth_2pct_usd if b.liquidity else None,
            market_cap_usd=b.snapshot.market_cap_usd,
            circulating_ratio=ratio,
            fear_greed=b.sentiment.fear_greed_value if b.sentiment else None,
            change_7d_pct=b.snapshot.change_7d_pct,
            price_sources_disagree=ctx.reconciliation.status == "mismatch",
        )

    def assess(self, ctx: AnalystContext, horizon: Horizon) -> RiskAssessment:
        risk = assess_risk(horizon, self.inputs(ctx), ctx.ev)
        h = horizon.value
        factor_ids = [i for f in risk.factors for i in f.evidence_ids]
        ctx.registry.calculate(
            f"{h}_risk_score",
            f"{h.replace('_', '-').capitalize()} risk score (0-100)",
            risk.score,
            "index",
            inputs=factor_ids,
        )
        ctx.registry.calculate(
            f"{h}_risk_level",
            f"{h.replace('_', '-').capitalize()} risk level",
            risk.level.value,
            "text",
            inputs=factor_ids,
        )
        return risk

    def tools(self, ctx: AnalystContext) -> list[Tool]:
        def assess_horizon(args: Mapping[str, Any]) -> ToolResult:
            risk = self.assess(ctx, Horizon(args["horizon"]))
            h = risk.horizon.value
            observed = ctx.describe(f"{h}_risk_score", f"{h}_risk_level")
            observed["factors"] = [
                {"name": f.name, "points": f.points, "detail": f.detail, "evidence_ids": list(f.evidence_ids)}
                for f in risk.factors
            ]
            return result(ctx, observed)

        def reconciliation_status(_: Mapping[str, Any]) -> ToolResult:
            return result(
                ctx,
                {
                    **ctx.describe("price_reconciliation", "price_max_deviation_pct", "price_source_count"),
                    "comparisons": ctx.reconciliation.to_dict()["comparisons"],
                },
            )

        def drawdown_and_volatility(_: Mapping[str, Any]) -> ToolResult:
            self.inputs(ctx)
            return result(ctx, ctx.describe("volatility_30d_pct", "max_drawdown_1y_pct", "depth_2pct_usd"))

        return [
            Tool(
                spec(
                    "assess_horizon_risk",
                    "Compute the itemised risk score and level for one horizon.",
                    {"horizon": {"type": "string", "enum": [h.value for h in Horizon]}},
                    ["horizon"],
                ),
                assess_horizon,
            ),
            Tool(
                spec("reconciliation_status", "Whether independent price sources agree, with per-source deviations."),
                reconciliation_status,
            ),
            Tool(
                spec("drawdown_and_volatility", "30-day volatility, one-year max drawdown and order-book depth."),
                drawdown_and_volatility,
            ),
        ]

    def finalize(self, ctx: AnalystContext) -> tuple[list[Signal], list[RiskAssessment]]:
        return [], [self.assess(ctx, h) for h in Horizon]

    def scripted_plan(self) -> list[tuple[str, dict[str, Any]]]:
        return [
            ("reconciliation_status", {}),
            ("assess_horizon_risk", {"horizon": "short_term"}),
            ("assess_horizon_risk", {"horizon": "long_term"}),
        ]

    def template_claims(
        self, ctx: AnalystContext, signals: Sequence[Signal], risks: Sequence[RiskAssessment]
    ) -> list[Claim]:
        view, out = ctx.view(), []
        for risk in risks:
            h = risk.horizon.value
            score_id, level_id = ctx.ev(f"{h}_risk_score"), ctx.ev(f"{h}_risk_level")
            score = view.get(score_id) if score_id else None
            if score is None or level_id is None:
                continue
            drivers = [f.name.replace("_", " ") for f in sorted(risk.factors, key=lambda f: -f.points)[:2]]
            out.append(
                Claim(
                    f"{h.replace('_', '-').capitalize()} risk is {risk.level.value.replace('_', ' ')} "
                    f"(score {fmt(score)} of 100), driven mainly by {' and '.join(drivers)}.",
                    ClaimTag.CALCULATION,
                    (score.id, level_id),
                )
            )
        status, deviation = ctx.ev("price_reconciliation"), ctx.ev("price_max_deviation_pct")
        dev = view.get(deviation) if deviation else None
        rec = ctx.reconciliation
        if status and dev:
            if rec.status == "mismatch":
                text = (
                    f"Price sources disagree: the largest deviation from the cross-source median is {fmt(dev)}, "
                    f"beyond the tolerance; treat price-based figures with caution."
                )
            elif rec.status == "consistent":
                text = f"Independent price sources agree; the largest deviation from their median is {fmt(dev)}."
            else:
                text = "Only one price source was available, so the price could not be cross-checked."
            out.append(Claim(text, ClaimTag.CALCULATION, (status, dev.id)))
        return out
