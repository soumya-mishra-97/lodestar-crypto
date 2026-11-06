"""Fundamental analyst: size, supply dilution, liquidity structure and ecosystem TVL."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from lodestar.application.pipeline.analysts.base import Analyst, AnalystContext, result, spec
from lodestar.application.pipeline.formatting import fmt
from lodestar.application.pipeline.react import Tool, ToolResult
from lodestar.domain.claims import Claim, ClaimTag
from lodestar.domain.models import Horizon
from lodestar.domain.scoring import RiskAssessment, Signal, fundamental_signals


class FundamentalAnalyst(Analyst):
    name = "fundamental"
    namespace = "FUN"
    title = "Fundamental analyst"
    mandate = (
        "Assess the asset's long-term (six months or more) structure: market size and rank, supply "
        "dilution and cap, liquidity and turnover, and ecosystem total value locked where it applies."
    )

    def supply(self, ctx: AnalystContext) -> dict[str, Any]:
        f, s = ctx.bundle.fundamentals, ctx.bundle.snapshot
        reg = ctx.registry
        if f and f.circulating_supply and f.total_supply:
            reg.calculate(
                "circulating_ratio_pct",
                "Circulating / total supply (%)",
                f.circulating_supply / f.total_supply * 100,
                "pct",
                inputs=[ctx.ev("circulating_supply"), ctx.ev("total_supply")],
            )
        if s.fdv_usd and s.market_cap_usd:
            reg.calculate(
                "fdv_to_mcap",
                "Fully diluted valuation / market cap",
                s.fdv_usd / s.market_cap_usd,
                "ratio",
                inputs=[ctx.ev("fdv_usd"), ctx.ev("market_cap_usd")],
            )
        return ctx.describe("circulating_supply", "total_supply", "max_supply", "circulating_ratio_pct", "fdv_to_mcap")

    def structure(self, ctx: AnalystContext) -> dict[str, Any]:
        s = ctx.bundle.snapshot
        if s.volume_24h_usd and s.market_cap_usd:
            ctx.registry.calculate(
                "turnover_pct",
                "24h volume / market cap (%)",
                s.volume_24h_usd / s.market_cap_usd * 100,
                "pct",
                inputs=[ctx.ev("volume_24h_usd"), ctx.ev("market_cap_usd")],
            )
        return ctx.describe(
            "market_cap_usd", "market_cap_rank", "turnover_pct", "depth_2pct_usd", "median_spread_pct",
            "top_venue_share_pct", "venue_count",
        )  # fmt: skip

    def tools(self, ctx: AnalystContext) -> list[Tool]:
        def supply_profile(_: Mapping[str, Any]) -> ToolResult:
            return result(ctx, self.supply(ctx))

        def market_structure(_: Mapping[str, Any]) -> ToolResult:
            return result(ctx, self.structure(ctx))

        def ecosystem_tvl(_: Mapping[str, Any]) -> ToolResult:
            observed = ctx.describe("tvl_usd", "tvl_change_30d_pct")
            return result(ctx, observed or {"note": "Not the native token of a tracked chain; TVL does not apply."})

        return [
            Tool(
                spec("supply_profile", "Circulating, total and max supply; circulating ratio; FDV/market-cap ratio."),
                supply_profile,
            ),
            Tool(
                spec(
                    "market_structure",
                    "Market cap and rank, turnover, order-book depth, spreads and venue concentration.",
                ),
                market_structure,
            ),
            Tool(
                spec("ecosystem_tvl", "Total value locked on the chain this token secures, and its 30-day change."),
                ecosystem_tvl,
            ),
        ]

    def finalize(self, ctx: AnalystContext) -> tuple[list[Signal], list[RiskAssessment]]:
        self.supply(ctx)
        self.structure(ctx)
        b = ctx.bundle
        return fundamental_signals(b.snapshot, b.fundamentals, b.liquidity, b.tvl, ctx.ev), []

    def scripted_plan(self) -> list[tuple[str, dict[str, Any]]]:
        return [("supply_profile", {}), ("market_structure", {}), ("ecosystem_tvl", {})]

    def template_claims(
        self, ctx: AnalystContext, signals: Sequence[Signal], risks: Sequence[RiskAssessment]
    ) -> list[Claim]:
        view, out = ctx.view(), []

        def item(key: str) -> Any:
            eid = ctx.ev(key)
            return view.get(eid) if eid else None

        if (mc := item("market_cap_usd")) and (rank := item("market_cap_rank")):
            out.append(
                Claim(f"Market capitalisation is {fmt(mc)}, rank {fmt(rank)} by size.", ClaimTag.FACT, (mc.id, rank.id))
            )
        if ratio := item("circulating_ratio_pct"):
            out.append(Claim(f"{fmt(ratio)} of total supply is circulating.", ClaimTag.CALCULATION, (ratio.id,)))
        if turnover := item("turnover_pct"):
            out.append(
                Claim(
                    f"Daily volume equals {fmt(turnover)} of market capitalisation.",
                    ClaimTag.CALCULATION,
                    (turnover.id,),
                )
            )
        if tvl := item("tvl_usd"):
            out.append(Claim(f"Total value locked in the ecosystem is {fmt(tvl)}.", ClaimTag.FACT, (tvl.id,)))
        for s in sorted(signals, key=lambda s: -abs(s.contribution))[:3]:
            if s.horizon is Horizon.LONG_TERM and s.evidence_ids:
                out.append(Claim(f"{s.detail}.", ClaimTag.INTERPRETATION, s.evidence_ids))
        return out
