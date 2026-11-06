"""Trade-plan writer: composes the card's claims from registered evidence only."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from lodestar.application.pipeline.analysts.base import AnalystResult
from lodestar.application.pipeline.formatting import fmt
from lodestar.domain.claims import Claim, ClaimTag
from lodestar.domain.evidence import Evidence, EvidenceBundle
from lodestar.domain.models import Asset
from lodestar.domain.trading.plan import TRADE_DISCLAIMER, TradePlanDraft

K = ClaimTag
KIND_LABEL = {"breakout": "Breakout", "pullback": "Pullback", "trend reclaim": "Trend-reclaim"}


@dataclass(frozen=True, slots=True)
class TradeWriterInput:
    asset: Asset
    evidence: EvidenceBundle
    analysts: Mapping[str, AnalystResult]
    sizing: Mapping[str, Any]
    data_gaps: tuple[str, ...] = field(default_factory=tuple)


class TradePlanWriterPort(Protocol):
    @property
    def name(self) -> str: ...

    async def write(self, inp: TradeWriterInput, feedback: Sequence[str] = ()) -> TradePlanDraft: ...


class TradePlanWriter:
    name = "deterministic"

    async def write(self, inp: TradeWriterInput, feedback: Sequence[str] = ()) -> TradePlanDraft:
        ev, sym = inp.evidence, inp.asset.symbol

        def e(key: str, ns: str) -> Evidence | None:
            return ev.by_key(key, namespace=ns)

        def ids(*items: Evidence | None) -> tuple[str, ...]:
            return tuple(i.id for i in items if i is not None)

        kind, status, trend = e("setup_kind", "TIM"), e("setup_status", "TIM"), e("trend_up", "TIM")
        level, lo, hi = e("trigger_level", "TIM"), e("entry_zone_low", "TIM"), e("entry_zone_high", "TIM")
        inv, atr, profit, vmult = (
            e("invalidation_level", "TIM"),
            e("atr_14", "TIM"),
            e("profit_level", "TIM"),
            e("volume_mult", "TIM"),
        )
        risk_level, risk_score = e("risk_level", "SIZ"), e("risk_score", "SIZ")
        units, notional, pct_eq = e("units", "SIZ"), e("notional_usd", "SIZ"), e("pct_of_equity", "SIZ")
        max_loss, max_loss_pct, loss_stop = (
            e("max_loss_usd", "SIZ"),
            e("max_loss_pct", "SIZ"),
            e("loss_at_stop_usd", "SIZ"),
        )
        kind_text = str(kind.value) if kind else "setup"
        status_text = str(status.value) if status else "waiting"

        headline = Claim(
            f"{inp.asset.name}: {kind_text} setup is {status_text}, short-term risk is "
            f"{str(risk_level.value).replace('_', ' ') if risk_level else 'unknown'}; the paper plan is sized to lose "
            "at most "
            f"{fmt(max_loss) if max_loss else 'a fixed amount'} if invalidated.",
            K.INTERPRETATION,
            ids(kind, status, risk_level, max_loss),
        )

        setup: list[Claim] = []
        if kind and trend:
            trend_words = "price is in an uptrend" if trend.value == "yes" else "price is not in an uptrend yet"
            setup.append(
                Claim(
                    f"{KIND_LABEL.get(kind_text, kind_text.capitalize())} setup: {trend_words} by the 20- and 50-day "
                    "average rule.",
                    K.INTERPRETATION,
                    ids(kind, trend),
                )
            )
        if (score := e("scan_score", "SCN")) and (rs := e("rs_vs_btc_pct", "SCN")):
            setup.append(
                Claim(
                    f"Scanner score is {fmt(score)} of 100; the 30-day return relative to Bitcoin is {fmt(rs)}.",
                    K.CALCULATION,
                    ids(score, rs),
                )
            )
        if (vr := e("volume_ratio", "SCN")) is not None:
            setup.append(Claim(f"Recent volume runs at {fmt(vr)} times its 30-day average.", K.CALCULATION, ids(vr)))

        timing: list[Claim] = []
        if level and kind:
            trigger_words = {
                "breakout": f"a daily close above the prior 20-day high of {fmt(level)} with volume at least "
                f"{fmt(vmult) if vmult else ''} times its 20-day average",
                "pullback": f"a daily close back above the 20-day average, now {fmt(level)}",
                "trend reclaim": f"a daily close back above the 50-day average, now {fmt(level)}",
            }[kind_text]
            timing.append(
                Claim(
                    f"Trigger: {trigger_words}.", K.CALCULATION, ids(level, vmult if kind_text == "breakout" else None)
                )
            )
        if lo and hi:
            timing.append(
                Claim(
                    f"Entry zone: {fmt(lo)} to {fmt(hi)}, the trigger level plus half an average true range.",
                    K.CALCULATION,
                    ids(lo, hi),
                )
            )
        if status:
            status_words = {
                "waiting": "waiting: the trigger has not fired in the last 3 days, so there is no entry yet",
                "active": "active: the trigger fired recently and price is inside the entry zone",
                "extended": "extended: the trigger fired but price is above the entry zone; chasing it raises the "
                "risk per unit",
            }[status_text]
            timing.append(Claim(f"Status is {status_words}.", K.CALCULATION, ids(status)))
        if profit:
            timing.append(
                Claim(
                    f"Profit-taking rule: {fmt(profit)}, two times the initial risk above the entry midpoint.",
                    K.CALCULATION,
                    ids(profit),
                )
            )

        invalidation: list[Claim] = []
        if inv and atr:
            invalidation.append(
                Claim(
                    f"The setup is invalidated by a daily close below {fmt(inv)}: the trigger level minus 2 average "
                    f"true ranges ({fmt(atr)} each).",
                    K.CALCULATION,
                    ids(inv, atr),
                )
            )
            invalidation.append(
                Claim(
                    f"If price closes below {fmt(inv)}, the plan is void and a paper position would exit at the stop.",
                    K.SCENARIO,
                    ids(inv),
                )
            )

        scenarios = self._scenarios(inp)

        risk: list[Claim] = []
        if risk_level and risk_score:
            risk.append(
                Claim(
                    f"Short-term risk is {str(risk_level.value).replace('_', ' ')} (score {fmt(risk_score)} of 100).",
                    K.CALCULATION,
                    ids(risk_level, risk_score),
                )
            )
        if units and notional and pct_eq and loss_stop and max_loss and max_loss_pct:
            risk.append(
                Claim(
                    f"Paper size: {fmt(units)} {sym}, about {fmt(notional)} or {fmt(pct_eq)} of the paper account; a "
                    "stop at the "
                    f"invalidation level would lose {fmt(loss_stop)} including costs, within the {fmt(max_loss_pct)} "
                    f"limit of {fmt(max_loss)}.",
                    K.CALCULATION,
                    ids(units, notional, pct_eq, loss_stop, max_loss, max_loss_pct),
                )
            )
        if (binding := e("binding_limit", "SIZ")) is not None:
            risk.append(Claim(f"The limit that set the size was: {binding.value}.", K.CALCULATION, ids(binding)))
        if (slip := e("expected_slippage_pct", "SIZ")) is not None:
            risk.append(
                Claim(
                    f"Expected slippage for this size is {fmt(slip)} on the visible order book.",
                    K.CALCULATION,
                    ids(slip),
                )
            )
        if (corr := e("correlation_btc", "SIZ")) is not None:
            risk.append(
                Claim(
                    f"The correlation of daily returns with Bitcoin over 90 days is {fmt(corr)}, so this position "
                    "adds market exposure rather than diversifying it."
                    if float(corr.value) > 0.6
                    else f"The correlation of daily returns with Bitcoin over 90 days is {fmt(corr)}.",
                    K.CALCULATION,
                    ids(corr),
                )
            )
        if (mc := e("max_correlation_open", "SIZ")) is not None:
            risk.append(
                Claim(f"The highest correlation with an open paper position is {fmt(mc)}.", K.CALCULATION, ids(mc))
            )

        evidence_claims: list[Claim] = []
        for name in (
            "news_event_scout",
            "sentiment_reader",
            "fundamentals_analyst",
            "technical_analyst",
            "liquidity_checker",
        ):
            a = inp.analysts.get(name)
            if a:
                evidence_claims.extend([c for c in a.claims if c.tag is not K.ASSUMPTION][:2])
        evidence_claims.extend(self._backtest(inp))

        assumptions = [
            Claim("Paper trading only: Lodestar places no orders and holds no exchange keys.", K.ASSUMPTION),
            Claim(
                "Entry, trigger and invalidation are rule-based conditions; they say where a setup starts and stops, "
                "not where price will go.",
                K.ASSUMPTION,
            ),
            Claim(
                "Historical statistics describe past signals of the same rule and can fail in new market conditions.",
                K.ASSUMPTION,
            ),
        ]
        if (cl := e("confidence_level_pct", "SCE")) is not None:
            assumptions.append(Claim(f"Intervals shown are {fmt(cl)} confidence intervals.", K.CALCULATION, ids(cl)))
        for name in ("fundamentals_analyst",):
            a = inp.analysts.get(name)
            if a:
                assumptions.extend([c for c in a.claims if c.tag is K.ASSUMPTION][:1])
        if inp.data_gaps:
            assumptions.append(
                Claim("Some optional sources were unavailable; the data gaps are listed with the card.", K.ASSUMPTION)
            )

        seen: set[str] = set()

        def unique(items: list[Claim]) -> tuple[Claim, ...]:
            out = []
            for c in items:
                if c.text not in seen:
                    seen.add(c.text)
                    out.append(c)
            return tuple(out)

        return TradePlanDraft(
            headline=headline,
            setup=unique(setup),
            timing=unique(timing),
            scenarios=unique(scenarios),
            risk=unique(risk),
            invalidation=unique(invalidation),
            evidence=unique(evidence_claims),
            assumptions=unique(assumptions),
            disclaimer=TRADE_DISCLAIMER,
            writer=self.name,
        )

    @staticmethod
    def _scenarios(inp: TradeWriterInput) -> list[Claim]:
        ev = inp.evidence

        def e(key: str) -> Evidence | None:
            return ev.by_key(key, namespace="SCE")

        horizon, n, rel, band = e("horizon_days"), e("sample_size"), e("sample_reliability"), e("scenario_band_pct")
        out: list[Claim] = []
        if n is None or horizon is None or rel is None:
            return out
        if float(n.value) == 0:
            cited = tuple(
                x.id for x in (e("scenario_bull_pct"), e("scenario_base_pct"), e("scenario_bear_pct"), rel, n) if x
            )
            out.append(
                Claim(
                    "No past signals of this rule exist in the available history, so the sample is insufficient and "
                    "no scenario can be estimated.",
                    K.ASSUMPTION,
                    cited,
                )
            )
            return out
        wins, wr, lo, hi = e("wins"), e("win_rate_pct"), e("win_rate_ci_low_pct"), e("win_rate_ci_high_pct")
        mean, median, dd = e("mean_return_pct"), e("median_return_pct"), e("worst_drawdown_pct")
        if wins and wr and mean and median and dd:
            ci = f" (interval {fmt(lo)} to {fmt(hi)})" if lo and hi else ""
            out.append(
                Claim(
                    f"Across {fmt(n)} past signals held {fmt(horizon)} days, {fmt(wins)} gained after costs: win rate "
                    f"{fmt(wr)}{ci}, "
                    f"average {fmt(mean)}, median {fmt(median)}, worst drawdown during a hold {fmt(dd)}.",
                    K.CALCULATION,
                    tuple(x.id for x in (n, horizon, wins, wr, lo, hi, mean, median, dd) if x),
                )
            )
        for name, words in (("bull", "Bull case"), ("base", "Base case"), ("bear", "Bear case")):
            pct, count = e(f"scenario_{name}_pct"), e(f"scenario_{name}_count")
            if pct is None or count is None or band is None:
                continue
            slo, shi = e(f"scenario_{name}_ci_low_pct"), e(f"scenario_{name}_ci_high_pct")
            smean, smed, sdd = (
                e(f"scenario_{name}_mean_pct"),
                e(f"scenario_{name}_median_pct"),
                e(f"scenario_{name}_worst_dd_pct"),
            )
            band_words = {"bull": f"above +{fmt(band)}", "base": f"within ±{fmt(band)}", "bear": f"below -{fmt(band)}"}[
                name
            ]
            if float(count.value) == 0:
                out.append(
                    Claim(
                        f"{words} ({band_words} after {fmt(horizon)} days): none of the {fmt(n)} past signals.",
                        K.CALCULATION,
                        tuple(x.id for x in (pct, count, band, horizon, n) if x),
                    )
                )
                continue
            ci = f", interval {fmt(slo)} to {fmt(shi)}" if slo and shi else ""
            out.append(
                Claim(
                    f"{words} ({band_words} after {fmt(horizon)} days): {fmt(count)} of {fmt(n)} past signals "
                    f"({fmt(pct)}{ci}); "
                    f"average {fmt(smean) if smean else 'n/a'}, median {fmt(smed) if smed else 'n/a'}, worst drawdown "
                    f"{fmt(sdd) if sdd else 'n/a'}.",
                    K.CALCULATION,
                    tuple(x.id for x in (pct, count, band, horizon, n, slo, shi, smean, smed, sdd) if x),
                )
            )
        if rel.value == "insufficient":
            out.append(
                Claim(
                    f"The sample is insufficient (fewer than ten signals, here {fmt(n)}): do not rely on these "
                    "statistics.",
                    K.ASSUMPTION,
                    (rel.id, n.id),
                )
            )
        elif rel.value == "small":
            out.append(
                Claim(
                    f"The sample is small (fewer than thirty signals, here {fmt(n)}): these statistics are too small "
                    "to trust on their own.",
                    K.ASSUMPTION,
                    (rel.id, n.id),
                )
            )
        else:
            out.append(
                Claim(
                    f"The sample is adequate ({fmt(n)} signals), but past frequencies are still not probabilities of "
                    "the future.",
                    K.ASSUMPTION,
                    (rel.id, n.id),
                )
            )
        return out

    @staticmethod
    def _backtest(inp: TradeWriterInput) -> list[Claim]:
        ev = inp.evidence

        def e(key: str) -> Evidence | None:
            return ev.by_key(key, namespace="BKT")

        days, trades, ret, bh, sharpe = (
            e("oos_days"),
            e("oos_trades"),
            e("oos_total_return_pct"),
            e("oos_buy_hold_pct"),
            e("oos_sharpe"),
        )
        fee, slip, warn = e("fee_bps"), e("slippage_bps"), e("warning_count")
        out: list[Claim] = []
        if days and trades and ret and bh and sharpe and fee and slip:
            out.append(
                Claim(
                    f"Out-of-sample backtest over the last {fmt(days)} days: {fmt(trades)} trades, total return "
                    f"{fmt(ret)} versus {fmt(bh)} for holding, "
                    f"Sharpe {fmt(sharpe)}, after {fmt(fee)} bps fees and {fmt(slip)} bps slippage per side.",
                    K.CALCULATION,
                    tuple(x.id for x in (days, trades, ret, bh, sharpe, fee, slip)),
                )
            )
        if (wf := e("wf_total_return_pct")) and (folds := e("wf_folds")):
            out.append(
                Claim(
                    f"Walk-forward testing across {fmt(folds)} windows returned {fmt(wf)} after costs.",
                    K.CALCULATION,
                    (folds.id, wf.id),
                )
            )
        if warn is not None and float(warn.value) > 0:
            out.append(
                Claim(
                    f"The backtest raised {fmt(warn)} overfitting or reliability warnings, so treat it as weak "
                    "evidence.",
                    K.INTERPRETATION,
                    (warn.id,),
                )
            )
        return out
