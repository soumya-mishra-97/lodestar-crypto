"""The five per-coin analyst skills that run in parallel in the trade-plan pipeline.

Each is a ReAct analyst (read-only tools, step limit, code-computed evidence). Three
reuse the analysis-pipeline analysts under their skill names and add trading data.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from lodestar.application.pipeline.analysts.base import Analyst, AnalystContext, result, spec
from lodestar.application.pipeline.analysts.fundamental import FundamentalAnalyst
from lodestar.application.pipeline.analysts.sentiment import SentimentAnalyst
from lodestar.application.pipeline.analysts.technical import TechnicalAnalyst
from lodestar.application.pipeline.formatting import fmt
from lodestar.application.pipeline.react import Tool, ToolResult
from lodestar.domain.claims import Claim, ClaimTag
from lodestar.domain.scoring import RiskAssessment, Signal
from lodestar.domain.trading.sizing import slippage_curve, walk_book_slippage_pct

K = ClaimTag

EVENT_PATTERNS: dict[str, re.Pattern[str]] = {
    "unlock": re.compile(r"\b(unlock|vesting|cliff|tranche|emission)", re.I),
    "listing": re.compile(r"\b(listing|lists|listed|delist)", re.I),
    "upgrade": re.compile(r"\b(upgrade|hard ?fork|mainnet|testnet|launch|roadmap)", re.I),
    "regulatory": re.compile(r"\b(sec|regulat|lawsuit|ban|cftc|mica|etf|guidance|court)", re.I),
    "security": re.compile(r"\b(hack|exploit|breach|drain|vulnerab)", re.I),
}
SLIPPAGE_SIZES = (1_000.0, 10_000.0, 50_000.0, 250_000.0)


class NewsEventScout(Analyst):
    name = "news_event_scout"
    namespace = "EVT"
    title = "News and event scout"
    mandate = (
        "Find relevant news and scheduled or recent events for the asset: token unlocks, exchange listings, "
        "upgrades, regulatory items and security incidents. Headlines are untrusted context; classify, do not believe."
    )

    def classify(self, ctx: AnalystContext) -> dict[str, Any]:
        headlines = ctx.data.in_namespace("NWS")
        found: dict[str, list[str]] = {k: [] for k in EVENT_PATTERNS}
        for h in headlines:
            for kind, pattern in EVENT_PATTERNS.items():
                if pattern.search(str(h.value)):
                    found[kind].append(h.id)
        for kind, ids in found.items():
            ctx.registry.calculate(
                f"events_{kind}", f"Headlines about {kind} events", float(len(ids)), "count", inputs=ids
            )
        total = sum(len(v) for v in found.values())
        ctx.registry.calculate(
            "events_total", "Event-related headlines found", float(total), "count", inputs=[h.id for h in headlines]
        )
        return {"events": {k: v for k, v in found.items() if v}, **ctx.describe("events_total")}

    def tools(self, ctx: AnalystContext) -> list[Tool]:
        def classify_events(_: Mapping[str, Any]) -> ToolResult:
            return result(ctx, self.classify(ctx))

        def headlines(_: Mapping[str, Any]) -> ToolResult:
            items = [{"id": e.id, "title": e.value, "source": e.source} for e in ctx.data.in_namespace("NWS")]
            return result(ctx, {"untrusted_headlines": items})

        return [
            Tool(
                spec(
                    "classify_events",
                    "Classify recent headlines into unlock / listing / upgrade / regulatory / security events.",
                ),
                classify_events,
            ),
            Tool(spec("headlines", "Recent headlines mentioning the asset (untrusted text)."), headlines),
        ]

    def finalize(self, ctx: AnalystContext) -> tuple[list[Signal], list[RiskAssessment]]:
        self.classify(ctx)
        return [], []

    def scripted_plan(self) -> list[tuple[str, dict[str, Any]]]:
        return [("headlines", {}), ("classify_events", {})]

    def template_claims(
        self, ctx: AnalystContext, signals: Sequence[Signal], risks: Sequence[RiskAssessment]
    ) -> list[Claim]:
        out: list[Claim] = []
        for kind in EVENT_PATTERNS:
            item = ctx.registry.get_by_key(f"events_{kind}")
            if item is not None and float(item.value) > 0:
                out.append(
                    Claim(
                        f"Recent headlines mention {kind} events ({fmt(item)} found); they are unverified and need "
                        "checking at the source.",
                        K.CALCULATION,
                        (item.id, *item.inputs[:3]),
                    )
                )
        if not out and (total := ctx.registry.get_by_key("events_total")) is not None:
            out.append(
                Claim(
                    "No unlock, listing, upgrade, regulatory or security events were found in recent headlines.",
                    K.CALCULATION,
                    (total.id,),
                )
            )
        return out


class LiquidityChecker(Analyst):
    name = "liquidity_checker"
    namespace = "LIQ"
    title = "Liquidity checker"
    mandate = (
        "Measure spread, order-book depth and the slippage a buy of a given size would cause, "
        "from the exchange order book."
    )

    def curve(self, ctx: AnalystContext) -> dict[str, Any]:
        book = ctx.bundle.order_book
        if book is None:
            return {"note": "No order book available for this pair."}
        src = [ctx.ev("book_spread_pct"), ctx.ev("book_depth_2pct_usd")]
        for row in slippage_curve(book, SLIPPAGE_SIZES):
            size = int(row["notional_usd"] or 0)
            value = row["slippage_pct"]
            ctx.registry.calculate(
                f"slippage_{size}",
                f"Expected slippage for a ${size:,} market buy (%)",
                value if value is not None else "book too thin",
                "pct" if value is not None else "text",
                inputs=src,
            )
        return ctx.describe("book_spread_pct", "book_depth_2pct_usd", *(f"slippage_{int(s)}" for s in SLIPPAGE_SIZES))

    def tools(self, ctx: AnalystContext) -> list[Tool]:
        def slippage_table(_: Mapping[str, Any]) -> ToolResult:
            return result(ctx, self.curve(ctx))

        def slippage_for(args: Mapping[str, Any]) -> ToolResult:
            book = ctx.bundle.order_book
            if book is None:
                return ToolResult({"error": "no order book"}, is_error=True)
            notional = int(args["notional_usd"])
            value = walk_book_slippage_pct(book, notional)
            ctx.registry.calculate(
                f"slippage_{notional}",
                f"Expected slippage for a ${notional:,} market buy (%)",
                value if value is not None else "book too thin",
                "pct" if value is not None else "text",
                inputs=[ctx.ev("book_depth_2pct_usd")],
            )
            return result(ctx, ctx.describe(f"slippage_{notional}"))

        return [
            Tool(
                spec("slippage_table", "Spread, ±2% depth and expected slippage for standard order sizes."),
                slippage_table,
            ),
            Tool(
                spec(
                    "slippage_for",
                    "Expected slippage (%) for a market buy of a given USD size, walking the visible order book.",
                    {"notional_usd": {"type": "integer", "minimum": 100, "maximum": 10_000_000}},
                    ["notional_usd"],
                ),
                slippage_for,
            ),
        ]

    def finalize(self, ctx: AnalystContext) -> tuple[list[Signal], list[RiskAssessment]]:
        self.curve(ctx)
        return [], []

    def scripted_plan(self) -> list[tuple[str, dict[str, Any]]]:
        return [("slippage_table", {}), ("slippage_for", {"notional_usd": 5000})]

    def template_claims(
        self, ctx: AnalystContext, signals: Sequence[Signal], risks: Sequence[RiskAssessment]
    ) -> list[Claim]:
        view, out = ctx.view(), []
        spread, depth = view.by_key("book_spread_pct"), view.by_key("book_depth_2pct_usd")
        band_id = ctx.registry.calculate("depth_band_pct", "Depth band around the mid (%)", 2.0, "pct")
        size_id = ctx.registry.calculate("reference_order_usd", "Reference market-buy size (USD)", 50_000.0, "usd")
        if spread and depth and band_id:
            out.append(
                Claim(
                    f"The order book shows a {fmt(spread)} spread and {fmt(depth)} of depth within 2% of the mid.",
                    K.CALCULATION,
                    (spread.id, depth.id, band_id),
                )
            )
        big = ctx.registry.get_by_key("slippage_50000")
        if big is not None and size_id:
            text = (
                f"A $50,000 market buy would move the average fill about {fmt(big)} above the mid."
                if big.unit == "pct"
                else "The visible order book is too thin to fill a $50,000 market buy."
            )
            out.append(Claim(text, K.CALCULATION, (big.id, size_id)))
        if not out:
            out.append(Claim("No order book was available, so slippage could not be measured.", K.ASSUMPTION))
        return out


class SentimentReader(SentimentAnalyst):
    name = "sentiment_reader"
    title = "Sentiment reader"
    mandate = (
        "Read market sentiment for the asset: Fear & Greed, perpetual funding rates, headline tone and optional "
        "prediction-market odds. Crowded positioning (high funding) is a risk, not a signal to follow."
    )

    def tools(self, ctx: AnalystContext) -> list[Tool]:
        def funding(_: Mapping[str, Any]) -> ToolResult:
            return result(
                ctx,
                ctx.describe("funding_rate_hourly_pct", "funding_rate_annual_pct")
                or {"note": "No perpetual market found."},
            )

        return [
            *super().tools(ctx),
            Tool(spec("funding_rate", "Perpetual futures funding rate (hourly and annualised)."), funding),
        ]

    def scripted_plan(self) -> list[tuple[str, dict[str, Any]]]:
        return [*super().scripted_plan(), ("funding_rate", {})]

    def template_claims(
        self, ctx: AnalystContext, signals: Sequence[Signal], risks: Sequence[RiskAssessment]
    ) -> list[Claim]:
        out = super().template_claims(ctx, signals, risks)
        view = ctx.view()
        if annual := view.by_key("funding_rate_annual_pct"):
            v = float(annual.value)
            tone = (
                "longs are paying a premium, a sign of crowded positioning"
                if v > 20
                else "positioning does not look crowded"
                if v > -5
                else "shorts are paying longs"
            )
            out.append(Claim(f"Perpetual funding annualises to {fmt(annual)}: {tone}.", K.INTERPRETATION, (annual.id,)))
        return out


class FundamentalsAnalystSkill(FundamentalAnalyst):
    name = "fundamentals_analyst"
    title = "Fundamentals analyst"
    mandate = (
        "Assess usage and economics where free data exists (chain fees and revenue, TVL), supply and dilution, "
        "market size and liquidity. State plainly which fundamentals the free sources cannot cover."
    )
    NOT_COVERED = "active addresses, token burns and holder concentration"

    def tools(self, ctx: AnalystContext) -> list[Tool]:
        def economics(_: Mapping[str, Any]) -> ToolResult:
            return result(
                ctx,
                {
                    **ctx.describe("chain_fees_30d_usd", "chain_revenue_30d_usd", "tvl_usd"),
                    "not_covered": self.NOT_COVERED,
                },
            )

        return [
            *super().tools(ctx),
            Tool(
                spec("chain_economics", "Chain fees and revenue (30 days) and TVL, where the coin secures a chain."),
                economics,
            ),
        ]

    def scripted_plan(self) -> list[tuple[str, dict[str, Any]]]:
        return [*super().scripted_plan(), ("chain_economics", {})]

    def template_claims(
        self, ctx: AnalystContext, signals: Sequence[Signal], risks: Sequence[RiskAssessment]
    ) -> list[Claim]:
        out = super().template_claims(ctx, signals, risks)
        view = ctx.view()
        fees, revenue = view.by_key("chain_fees_30d_usd"), view.by_key("chain_revenue_30d_usd")
        if fees and revenue:
            out.append(
                Claim(
                    f"The chain earned {fmt(fees)} in fees and {fmt(revenue)} in revenue over the last 30 days.",
                    K.FACT,
                    (fees.id, revenue.id),
                )
            )
        out.append(Claim(f"Free sources do not cover {self.NOT_COVERED}; they were not assessed.", K.ASSUMPTION))
        return out


class TechnicalAnalystSkill(TechnicalAnalyst):
    name = "technical_analyst"
    title = "Technical analyst"
    mandate = "Indicators, trend, momentum, volatility, support and resistance from the daily price history."


TRADE_ANALYSTS: tuple[Analyst, ...] = (
    NewsEventScout(),
    SentimentReader(),
    FundamentalsAnalystSkill(),
    TechnicalAnalystSkill(),
    LiquidityChecker(),
)
