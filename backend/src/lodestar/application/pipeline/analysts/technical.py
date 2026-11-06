"""Technical analyst: trend, momentum, volatility and volume from daily price history."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from lodestar.application.pipeline.analysts.base import Analyst, AnalystContext, result, spec
from lodestar.application.pipeline.formatting import fmt
from lodestar.application.pipeline.react import Tool, ToolResult
from lodestar.domain import indicators as ta
from lodestar.domain.claims import Claim, ClaimTag
from lodestar.domain.models import Horizon
from lodestar.domain.scoring import RiskAssessment, Signal, technical_signals

INDICATORS = (
    "sma",
    "ema",
    "rsi",
    "macd",
    "bollinger",
    "realized_volatility",
    "max_drawdown",
    "pct_change",
    "support_resistance",
    "volume_ratio",
)
DEFAULT_WINDOW = {
    "sma": 50,
    "ema": 20,
    "rsi": 14,
    "realized_volatility": 30,
    "max_drawdown": 365,
    "pct_change": 90,
    "support_resistance": 30,
}


class TechnicalAnalyst(Analyst):
    name = "technical"
    namespace = "TEC"
    title = "Technical analyst"
    mandate = (
        "Assess price trend, momentum, volatility and volume from the daily price history. "
        "Focus on the short term (days to four weeks) and note the long-term trend (200-day average)."
    )

    # ------------------------------------------------------------ computations (register evidence)

    def compute(self, ctx: AnalystContext, name: str, window: int | None = None) -> dict[str, Any]:
        closes, volumes = ctx.bundle.history.closes, ctx.bundle.history.volumes
        w = window or DEFAULT_WINDOW.get(name, 0)
        src = [ctx.ev("history_days"), ctx.ev("last_close")]
        reg = ctx.registry

        def calc(key: str, label: str, value: float | None, unit: str = "usd") -> None:
            reg.calculate(key, label, value, unit, inputs=src)  # type: ignore[arg-type]

        match name:
            case "sma":
                calc(f"sma_{w}", f"{w}-day simple moving average (USD)", ta.sma(closes, w))
                keys = [f"sma_{w}"]
            case "ema":
                series = ta.ema_series(closes, w)
                calc(f"ema_{w}", f"{w}-day exponential moving average (USD)", series[-1] if series else None)
                keys = [f"ema_{w}"]
            case "rsi":
                calc(f"rsi_{w}", f"RSI ({w}-day)", ta.rsi(closes, w), "index")
                keys = [f"rsi_{w}"]
            case "macd":
                m = ta.macd(closes)
                calc("macd_histogram", "MACD histogram (12/26/9)", m.histogram if m else None)
                calc("macd_line", "MACD line (12/26)", m.macd if m else None)
                keys = ["macd_histogram", "macd_line"]
            case "bollinger":
                b = ta.bollinger(closes)
                calc("bollinger_pct_b", "Bollinger %B (20, 2)", b.percent_b if b else None, "ratio")
                calc("bollinger_upper", "Upper Bollinger band (USD)", b.upper if b else None)
                calc("bollinger_lower", "Lower Bollinger band (USD)", b.lower if b else None)
                keys = ["bollinger_pct_b", "bollinger_upper", "bollinger_lower"]
            case "realized_volatility":
                calc(
                    f"volatility_{w}d_pct",
                    f"{w}-day annualised volatility (%)",
                    ta.realized_volatility_pct(closes, w),
                    "pct",
                )
                keys = [f"volatility_{w}d_pct"]
            case "max_drawdown":
                key = "max_drawdown_1y_pct" if w == 365 else f"max_drawdown_{w}d_pct"
                calc(key, f"Max drawdown over {w} days (%)", ta.max_drawdown_pct(closes[-w:]), "pct")
                keys = [key]
            case "pct_change":
                calc(f"return_{w}d_pct", f"{w}-day return (%)", ta.pct_change(closes, w), "pct")
                keys = [f"return_{w}d_pct"]
            case "support_resistance":
                last = closes[-w:]
                ok = len(last) >= w
                calc(f"support_{w}d", f"{w}-day low (USD)", min(last) if ok else None)
                calc(f"resistance_{w}d", f"{w}-day high (USD)", max(last) if ok else None)
                keys = [f"support_{w}d", f"resistance_{w}d"]
            case "volume_ratio":
                v7, v30 = ta.sma(volumes, 7), ta.sma(volumes, 30)
                ratio = v7 / v30 if v7 is not None and v30 else None
                calc("volume_ratio_7d_30d", "7-day vs 30-day average volume ratio", ratio, "ratio")
                keys = ["volume_ratio_7d_30d"]
            case _:
                raise ValueError(f"unknown indicator '{name}'")
        return ctx.describe(*keys)

    # ------------------------------------------------------------ analyst interface

    def tools(self, ctx: AnalystContext) -> list[Tool]:
        def compute_indicator(args: Mapping[str, Any]) -> ToolResult:
            observed = self.compute(ctx, str(args["name"]), args.get("window"))
            if not observed:
                return ToolResult({"error": "not enough history for this indicator"}, is_error=True)
            return result(ctx, observed)

        def price_summary(args: Mapping[str, Any]) -> ToolResult:
            days = int(args["days"])
            closes = ctx.bundle.history.closes[-(days + 1) :]
            src = [ctx.ev("history_days")]
            ctx.registry.calculate(
                f"return_{days}d_pct",
                f"{days}-day return (%)",
                ta.pct_change(ctx.bundle.history.closes, days),
                "pct",
                inputs=src,
            )
            ctx.registry.calculate(f"high_{days}d", f"{days}-day high close (USD)", max(closes), "usd", inputs=src)
            ctx.registry.calculate(f"low_{days}d", f"{days}-day low close (USD)", min(closes), "usd", inputs=src)
            return result(ctx, ctx.describe(f"return_{days}d_pct", f"high_{days}d", f"low_{days}d", "last_close"))

        return [
            Tool(
                spec(
                    "compute_indicator",
                    "Compute a technical indicator over the daily closes (computed by code and registered as "
                    "citable evidence). Windows are in days.",
                    {
                        "name": {"type": "string", "enum": list(INDICATORS)},
                        "window": {"type": "integer", "minimum": 5, "maximum": 365},
                    },
                    ["name"],
                ),
                compute_indicator,
            ),
            Tool(
                spec(
                    "price_summary",
                    "Return, high and low close over the last N days.",
                    {"days": {"type": "integer", "minimum": 7, "maximum": 365}},
                    ["days"],
                ),
                price_summary,
            ),
        ]

    def finalize(self, ctx: AnalystContext) -> tuple[list[Signal], list[RiskAssessment]]:
        for name, window in (
            ("sma", 20), ("sma", 50), ("sma", 200), ("rsi", 14), ("macd", None), ("bollinger", None),
            ("realized_volatility", 30), ("volume_ratio", None), ("support_resistance", 30),
            ("pct_change", 90), ("max_drawdown", 365),
        ):  # fmt: skip
            self.compute(ctx, name, window)
        ind = ta.compute_indicators(ctx.bundle.history)
        return technical_signals(ind, ctx.bundle.snapshot, ctx.ev), []

    def scripted_plan(self) -> list[tuple[str, dict[str, Any]]]:
        return [
            ("compute_indicator", {"name": "sma", "window": 50}),
            ("compute_indicator", {"name": "rsi", "window": 14}),
            ("compute_indicator", {"name": "macd"}),
            ("price_summary", {"days": 30}),
        ]

    def template_claims(
        self, ctx: AnalystContext, signals: Sequence[Signal], risks: Sequence[RiskAssessment]
    ) -> list[Claim]:
        view, out = ctx.view(), []

        def item(key: str) -> Any:
            eid = ctx.ev(key)
            return view.get(eid) if eid else None

        last, sma50, sma200, rsi, vol = (
            item(k) for k in ("last_close", "sma_50", "sma_200", "rsi_14", "volatility_30d_pct")
        )
        if last and sma50:
            side = "above" if float(last.value) > float(sma50.value) else "below"
            out.append(
                Claim(
                    f"The latest close of {fmt(last)} is {side} the 50-day average of {fmt(sma50)}.",
                    ClaimTag.CALCULATION,
                    (last.id, sma50.id),
                )
            )
        if rsi:
            out.append(Claim(f"The 14-day RSI is {fmt(rsi)}.", ClaimTag.CALCULATION, (rsi.id,)))
        if vol:
            out.append(Claim(f"Realised 30-day volatility is {fmt(vol)} annualised.", ClaimTag.CALCULATION, (vol.id,)))
        if last and sma200:
            side = "above" if float(last.value) > float(sma200.value) else "below"
            out.append(
                Claim(
                    f"Price is {side} its 200-day average of {fmt(sma200)}, the long-term trend line.",
                    ClaimTag.CALCULATION,
                    (last.id, sma200.id),
                )
            )
        for s in sorted(signals, key=lambda s: -abs(s.contribution))[:3]:
            if s.horizon is Horizon.SHORT_TERM and s.evidence_ids:
                out.append(Claim(f"{s.detail}.", ClaimTag.INTERPRETATION, s.evidence_ids))
        return out
