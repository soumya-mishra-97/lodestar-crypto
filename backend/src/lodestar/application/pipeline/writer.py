"""Report writer port and the deterministic writer.

The writer explains an evidence bundle; it never computes. The deterministic
writer composes claims from registered evidence only, so it is the baseline
the LLM writer must beat and the writer used when no LLM is configured.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from lodestar.application.pipeline.analysts.base import AnalystResult
from lodestar.application.pipeline.formatting import fmt
from lodestar.domain.claims import Claim, ClaimTag
from lodestar.domain.evidence import Evidence, EvidenceBundle
from lodestar.domain.models import Asset, Horizon
from lodestar.domain.reconciliation import Reconciliation
from lodestar.domain.report import DISCLAIMER, HorizonNarrative, ReportDraft
from lodestar.domain.scoring import HorizonAssessment, Signal

K = ClaimTag


@dataclass(frozen=True, slots=True)
class WriterInput:
    asset: Asset
    evidence: EvidenceBundle
    assessments: Mapping[Horizon, HorizonAssessment]
    analysts: Mapping[str, AnalystResult]
    portfolio: Mapping[str, Any]
    reconciliation: Reconciliation
    data_gaps: tuple[str, ...] = field(default_factory=tuple)


class ReportWriter(Protocol):
    @property
    def name(self) -> str: ...

    async def write(self, inp: WriterInput, feedback: Sequence[str] = ()) -> ReportDraft: ...


def _nice(h: Horizon) -> str:
    return h.value.replace("_", "-")


class TemplateReportWriter:
    name = "deterministic"

    async def write(self, inp: WriterInput, feedback: Sequence[str] = ()) -> ReportDraft:
        ev = inp.evidence

        def e(key: str, ns: str | None = None) -> Evidence | None:
            return ev.by_key(key, namespace=ns)

        def ids(*items: Evidence | None) -> tuple[str, ...]:
            return tuple(i.id for i in items if i is not None)

        st, lt = inp.assessments[Horizon.SHORT_TERM], inp.assessments[Horizon.LONG_TERM]
        refs = {
            h: (
                e(f"{h.value}_stance", "ASM"),
                e(f"{h.value}_risk_level", "RSK"),
                e(f"{h.value}_score", "ASM"),
                e(f"{h.value}_risk_score", "RSK"),
            )
            for h in Horizon
        }
        headline = Claim(
            f"{inp.asset.name}: short-term signals are {st.stance.value} "
            f"with {st.risk.level.value.replace('_', ' ')} risk; "
            f"long-term signals are {lt.stance.value} with {lt.risk.level.value.replace('_', ' ')} risk.",
            K.INTERPRETATION,
            ids(
                refs[Horizon.SHORT_TERM][0],
                refs[Horizon.SHORT_TERM][1],
                refs[Horizon.LONG_TERM][0],
                refs[Horizon.LONG_TERM][1],
            ),
        )

        def score_claim(h: Horizon, a: HorizonAssessment) -> list[Claim]:
            stance, _, score, _ = refs[h]
            if not (stance and score):
                return []
            return [
                Claim(
                    f"The {_nice(h)} signal score is {fmt(score)} of 100 ({a.stance.value}).",
                    K.CALCULATION,
                    ids(score, stance),
                )
            ]

        def signal_claims(a: HorizonAssessment, positive: bool) -> list[Claim]:
            picked: list[Signal] = sorted(
                (s for s in a.signals if (s.contribution > 0) == positive and s.evidence_ids),
                key=lambda s: -abs(s.contribution),
            )[:3]
            return [Claim(f"{s.detail}.", K.INTERPRETATION, s.evidence_ids) for s in picked]

        def analyst_claims(name: str) -> list[Claim]:
            a = inp.analysts.get(name)
            return list(a.claims) if a else []

        def cites(claim: Claim, *keys: str) -> bool:
            return any((x := ev.get(i)) is not None and x.key in keys for i in claim.evidence_ids)

        technical = analyst_claims("technical")
        long_keys = ("sma_200", "change_1y_pct", "ath_change_pct", "max_drawdown_1y_pct")
        tech_short = [c for c in technical if not cites(c, *long_keys)]
        tech_long = [c for c in technical if cites(c, *long_keys)]
        risk_claims = analyst_claims("risk")
        risk_for = {
            Horizon.SHORT_TERM: [c for c in risk_claims if c.text.lower().startswith("short")],
            Horizon.LONG_TERM: [c for c in risk_claims if c.text.lower().startswith("long")],
        }
        risk_other = [c for c in risk_claims if c not in risk_for[Horizon.SHORT_TERM] + risk_for[Horizon.LONG_TERM]]

        short_watch: list[Claim] = []
        if sup := e("support_30d"):
            short_watch.append(
                Claim(
                    f"If price closes below the 30-day low of {fmt(sup)}, the short-term picture would weaken.",
                    K.SCENARIO,
                    ids(sup),
                )
            )
        if res := e("resistance_30d"):
            short_watch.append(
                Claim(
                    f"If price holds above the 30-day high of {fmt(res)}, short-term momentum would strengthen.",
                    K.SCENARIO,
                    ids(res),
                )
            )
        short_watch += analyst_claims("sentiment")

        long_watch: list[Claim] = []
        if sma200 := e("sma_200"):
            long_watch.append(
                Claim(
                    f"If price sustains a move across the 200-day average of {fmt(sma200)}, "
                    "the long-term trend signal would change direction.",
                    K.SCENARIO,
                    ids(sma200),
                )
            )
        if (ratio := e("circulating_ratio_pct", "FUN")) and float(ratio.value) < 95:
            long_watch.append(
                Claim(
                    f"With {fmt(ratio)} of supply circulating, future unlocks could add selling pressure.",
                    K.SCENARIO,
                    ids(ratio),
                )
            )

        short = HorizonNarrative(
            thesis=tuple(score_claim(Horizon.SHORT_TERM, st) + tech_short),
            opportunities=tuple(signal_claims(st, positive=True)),
            risks=tuple(risk_for[Horizon.SHORT_TERM] + signal_claims(st, positive=False)),
            watch=tuple(short_watch),
        )
        long = HorizonNarrative(
            thesis=tuple(score_claim(Horizon.LONG_TERM, lt) + tech_long + analyst_claims("fundamental")),
            opportunities=tuple(signal_claims(lt, positive=True)),
            risks=tuple(risk_for[Horizon.LONG_TERM] + signal_claims(lt, positive=False)),
            watch=tuple(long_watch),
        )
        seen: set[str] = {headline.text}
        short, long = _dedupe(short, seen), _dedupe(long, seen)
        return ReportDraft(
            headline=headline,
            short_term=short,
            long_term=long,
            portfolio=tuple(self._portfolio(inp)),
            data_quality=tuple(risk_other + self._data_quality(inp)),
            uncertainties=tuple(self._uncertainties(inp)),
            disclaimer=DISCLAIMER,
            writer=self.name,
        )

    def _portfolio(self, inp: WriterInput) -> list[Claim]:
        ev, sym = inp.evidence, inp.asset.symbol
        held = ev.by_key("holds_asset", namespace="PF")
        if held is None:
            return []
        if held.value == "unknown":
            return [Claim("Portfolio context was unavailable for this run.", K.ASSUMPTION, (held.id,))]
        if held.value == "no":
            return [Claim(f"You do not hold {sym} in your tracked portfolio.", K.FACT, (held.id,))]
        qty, value, weight = (
            ev.by_key(k, namespace="PF") for k in ("position_quantity", "position_value_usd", "position_weight_pct")
        )
        out: list[Claim] = []
        if qty and value and weight:
            out.append(
                Claim(
                    f"You hold {fmt(qty)} {sym} worth {fmt(value)}, {fmt(weight)} of your tracked portfolio.",
                    K.CALCULATION,
                    (qty.id, value.id, weight.id),
                )
            )
            if inp.portfolio.get("concentrated"):
                out.append(
                    Claim(
                        f"At {fmt(weight)} of your portfolio, a large {sym} price move "
                        "would move your total value materially.",
                        K.INTERPRETATION,
                        (weight.id,),
                    )
                )
        if pnl := ev.by_key("position_pnl_pct", namespace="PF"):
            out.append(
                Claim(
                    f"Unrealised P&L on this position is {fmt(pnl)} against your recorded cost basis.",
                    K.CALCULATION,
                    (pnl.id,),
                )
            )
        return out

    def _data_quality(self, inp: WriterInput) -> list[Claim]:
        ev, out = inp.evidence, []
        if ex := ev.by_key("exchange_price_usd"):
            out.append(Claim(f"{ex.source.capitalize()} last traded at {fmt(ex)}.", K.FACT, (ex.id,)))
        if rp := ev.by_key("reference_price_usd"):
            out.append(Claim(f"The {rp.source} aggregated price is {fmt(rp)}.", K.FACT, (rp.id,)))
        if inp.data_gaps:
            out.append(
                Claim(
                    "Some optional sources were unavailable for this run; the data gaps are listed with the report.",
                    K.ASSUMPTION,
                )
            )
        return out

    def _uncertainties(self, inp: WriterInput) -> list[Claim]:
        out = [
            Claim(
                "Scores are rule-based summaries of past and current data; they do not predict future prices.",
                K.ASSUMPTION,
            ),
            Claim(
                "Headlines and prediction-market questions are unverified third-party text, used as context only.",
                K.ASSUMPTION,
            ),
        ]
        if (conf := inp.evidence.by_key("long_term_confidence_pct", namespace="ASM")) and float(conf.value) < 70:
            out.append(
                Claim(
                    f"Long-term data confidence is {fmt(conf)}, so the long-term view rests on incomplete data.",
                    K.CALCULATION,
                    (conf.id,),
                )
            )
        return out


def _dedupe(narrative: HorizonNarrative, seen: set[str]) -> HorizonNarrative:
    """Analyst findings and signal explanations can say the same thing; keep the first occurrence."""
    sections: dict[str, tuple[Claim, ...]] = {}
    for name, claims in narrative.sections():
        kept = []
        for claim in claims:
            if claim.text not in seen:
                seen.add(claim.text)
                kept.append(claim)
        sections[name] = tuple(kept)
    return HorizonNarrative(**sections)
