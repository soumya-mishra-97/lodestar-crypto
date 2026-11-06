"""The trade-plan card and its verifier.

Card = setup, risk level, size from max loss, scenarios, what invalidates it,
evidence ids. Every sentence is a tagged claim checked by the same claim rules
as analysis reports (C1-C9), plus the trade-plan rules below. Fail closed.

  P1  timing cites the entry zone (low and high), the trigger and the invalidation level
  P2  no "best/perfect/right time" language: timing is conditions, never a moment
  P3  bull, base and bear scenarios are each cited; a small sample is stated out loud
  P4  the size cites units, notional and the max loss, and the loss at the stop is within it
  P5  the risk level is cited; P6 headline + invalidation present; P7 trading disclaimer unchanged
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from lodestar.domain.claims import Claim
from lodestar.domain.evidence import EvidenceBundle
from lodestar.domain.verification import Finding, VerificationResult, check_claim

TRADE_DISCLAIMER = (
    "Paper-trading research only, not financial advice. Lodestar never places orders and holds no exchange "
    "keys. Entry zones, triggers and invalidation levels are rule-based conditions computed from past and "
    "current data, not predictions, guarantees or price targets. Historical statistics and backtests describe "
    "the past, depend on sample size, can be overfitted, and can fail in new market conditions. Crypto assets "
    "are highly volatile and you can lose some or all of the money you invest."
)
SECTIONS = ("setup", "timing", "scenarios", "risk", "invalidation", "evidence", "assumptions")
_BEST_TIME = re.compile(
    r"\b((the )?(best|perfect|ideal|right|optimal) (time|moment|day|entry point)|now is the time|"
    r"don'?t miss|can'?t go wrong|sure entry)\b",
    re.IGNORECASE,
)
REQUIRED_TIMING_KEYS = ("entry_zone_low", "entry_zone_high", "trigger_level", "invalidation_level")
SIZING_KEYS = ("units", "notional_usd", "max_loss_usd")


@dataclass(frozen=True, slots=True)
class TradePlanDraft:
    headline: Claim
    setup: tuple[Claim, ...]
    timing: tuple[Claim, ...]
    scenarios: tuple[Claim, ...]
    risk: tuple[Claim, ...]
    invalidation: tuple[Claim, ...]
    evidence: tuple[Claim, ...]
    assumptions: tuple[Claim, ...]
    disclaimer: str = TRADE_DISCLAIMER
    writer: str = "deterministic"

    def located_claims(self) -> Iterator[tuple[str, Claim]]:
        yield "headline", self.headline
        for section in SECTIONS:
            for i, claim in enumerate(getattr(self, section)):
                yield f"{section}[{i}]", claim

    def all_claims(self) -> list[Claim]:
        return [c for _, c in self.located_claims()]

    def to_dict(self) -> dict[str, Any]:
        return {
            "headline": self.headline.to_dict(),
            **{s: [c.to_dict() for c in getattr(self, s)] for s in SECTIONS},
            "disclaimer": self.disclaimer,
            "writer": self.writer,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> TradePlanDraft:
        return cls(
            headline=Claim.from_dict(d["headline"]),
            **{s: tuple(Claim.from_dict(c) for c in d.get(s) or ()) for s in SECTIONS},
            disclaimer=d.get("disclaimer", ""),
            writer=d.get("writer", "deterministic"),
        )


def _cited_keys(claims: tuple[Claim, ...], bundle: EvidenceBundle) -> set[str]:
    return {e.key for c in claims for i in c.evidence_ids if (e := bundle.get(i)) is not None}


def verify_trade_plan(draft: TradePlanDraft, bundle: EvidenceBundle) -> VerificationResult:
    result = VerificationResult()
    located = list(draft.located_claims())
    result.checked_claims = len(located)

    def add(location: str, rule: str, message: str, text: str = "") -> None:
        result.findings.append(Finding(location, rule, message, text))

    if not draft.headline.text.strip():
        add("headline", "P6", "the card needs a one-sentence headline")
    if not draft.invalidation:
        add("invalidation", "P6", "state what invalidates the setup")
    if draft.disclaimer.strip() != TRADE_DISCLAIMER:
        add("disclaimer", "P7", "the standard trading disclaimer is missing or altered")

    timing_keys = _cited_keys(draft.timing + draft.invalidation, bundle)
    missing = [k for k in REQUIRED_TIMING_KEYS if k not in timing_keys]
    if missing:
        add("timing", "P1", f"timing must cite the computed {', '.join(missing)}")

    scenario_keys = _cited_keys(draft.scenarios, bundle)
    for name in ("bull", "base", "bear"):
        if f"scenario_{name}_pct" not in scenario_keys:
            add("scenarios", "P3", f"the {name} scenario is not cited")
    rel = bundle.by_key("sample_reliability")
    if rel is not None and rel.value in ("small", "insufficient") and "sample_reliability" not in scenario_keys:
        add("scenarios", "P3", f"the sample is {rel.value}; say so and cite {rel.id}")

    sizing_keys = _cited_keys(draft.risk, bundle)
    if not all(k in sizing_keys for k in SIZING_KEYS):
        add("risk", "P4", "the size must cite units, notional and the max loss it was derived from")
    loss, cap = bundle.by_key("loss_at_stop_usd"), bundle.by_key("max_loss_usd")
    if loss is not None and cap is not None and float(loss.value) > float(cap.value) * 1.001:
        add("risk", "P4", "the loss at the stop exceeds the max loss")
    if "risk_level" not in sizing_keys:
        add("risk", "P5", "cite the computed risk level")

    for location, claim in located:
        if _BEST_TIME.search(claim.text):
            add(location, "P2", "timing is a set of conditions, never a 'best time'", claim.text)
        result.findings.extend(check_claim(claim, bundle, location))
    return result
