"""The verifier: decides whether a report draft may be shown to a human.

It never edits the draft. It either passes it or returns findings that the
report writer must fix (at most two repair loops, then the run fails closed).

Claim rules
  C1  every cited id exists in the evidence bundle
  C2  every claim except an assumption cites at least one id
  C3  a fact cites an observation; a calculation cites a calculation
  C4  every number in the text matches a value of an evidence item the claim cites
  C5  no certainty, guarantee or promotional language
  C6  no price targets and no buy/sell/hold instructions
  C7  a scenario is phrased conditionally ("if", "could", ...)
  C8  a claim citing a stance or risk-level item uses that item's value
  C9  one sentence of reasonable length
Report rules
  R1  headline present; both horizons have claims
  R2  short-term and long-term assessments both exist, each with a risk level
  R3  the standard risk disclaimer is present, unchanged
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from lodestar.domain.claims import Claim, ClaimTag
from lodestar.domain.evidence import EvidenceBundle, EvidenceKind
from lodestar.domain.models import Horizon
from lodestar.domain.report import DISCLAIMER, ReportDraft
from lodestar.domain.scoring import HorizonAssessment

MAX_CLAIM_CHARS = 400
MAX_CLAIMS = 80
RELATIVE_TOLERANCE = 0.015

_EVIDENCE_ID = re.compile(r"\b[A-Z]{2,4}-\d{1,3}\b")
_NUMBER = re.compile(
    r"(?<![\w.])(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?:\s*(?P<suffix>trillion|billion|million|thousand|tn|bn|[kmbt])(?![a-z]))?"
    r"(?P<pct>\s*%)?",
    re.IGNORECASE,
)
_MULTIPLIER = {
    "k": 1e3,
    "thousand": 1e3,
    "m": 1e6,
    "million": 1e6,
    "b": 1e9,
    "bn": 1e9,
    "billion": 1e9,
    "t": 1e12,
    "tn": 1e12,
    "trillion": 1e12,
}
# Indicator parameters and horizons that legitimately appear as bare integers ("14-day RSI").
_PARAMETER_INTEGERS = {1, 2, 3, 4, 6, 7, 9, 12, 14, 20, 24, 26, 30, 50, 90, 100, 200, 365}
_CERTAINTY = re.compile(
    r"\b(guarantee[sd]?|guaranteeing|risk[- ]free|no risk|can(?:no|')t (?:lose|fail|go down)|sure thing|"
    r"will definitely|definitely will|certain(?:ly)? to|to the moon|100% (?:safe|sure|certain)|"
    r"easy money|can't miss|financial advice)\b",
    re.IGNORECASE,
)
_PRICE_TARGET = re.compile(
    r"\b(price target|target price|target of|targets? \$|will (?:reach|hit|rise to|fall to|drop to|climb to|trade at)|"
    r"(?:is|are) (?:going|set|expected|likely) to (?:reach|hit|rise to|fall to)|fair value of)\b",
    re.IGNORECASE,
)
_ADVICE = re.compile(
    r"\b((?:you|investors|readers) should (?:buy|sell|hold|short|accumulate|exit|take profit)|"
    r"(?:we )?recommend(?:s|ed)? (?:buying|selling|holding|shorting|accumulating)|"
    r"(?:strong )?(?:buy|sell) (?:signal|rating|recommendation)|buy now|sell now|time to (?:buy|sell))\b",
    re.IGNORECASE,
)
_CONDITIONAL = re.compile(r"\b(if|unless|should|could|would|may|might|in case|scenario|were)\b", re.IGNORECASE)
_LEVEL_KEYS = ("stance", "risk_level", "reliability", "setup_status")


@dataclass(frozen=True, slots=True)
class Finding:
    location: str
    rule: str
    message: str
    claim_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"location": self.location, "rule": self.rule, "message": self.message, "claim_text": self.claim_text}

    def as_feedback(self) -> str:
        quoted = f' "{self.claim_text[:160]}"' if self.claim_text else ""
        return f"{self.location}{quoted}: {self.message} [{self.rule}]"


@dataclass(slots=True)
class VerificationResult:
    findings: list[Finding] = field(default_factory=list)
    checked_claims: int = 0

    @property
    def passed(self) -> bool:
        return not self.findings

    def feedback(self) -> list[str]:
        return [f.as_feedback() for f in self.findings]

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "checked_claims": self.checked_claims,
            "findings": [f.to_dict() for f in self.findings],
        }


def extract_numbers(text: str) -> list[tuple[float, float]]:
    """(value, rounding tolerance) for every number in `text` that must be grounded.

    Evidence ids, indicator parameters ("14-day") and calendar years are skipped;
    anything with %, $ or a magnitude suffix is always checked.
    """
    text = _EVIDENCE_ID.sub(" ", text)
    out: list[tuple[float, float]] = []
    for m in _NUMBER.finditer(text):
        raw = m.group("num").replace(",", "")
        decimals = len(raw.split(".")[1]) if "." in raw else 0
        multiplier = _MULTIPLIER.get((m.group("suffix") or "").lower(), 1.0)
        value = float(raw) * multiplier
        dollar = m.start() > 0 and text[m.start() - 1] == "$"
        plain_int = not m.group("suffix") and not m.group("pct") and not dollar and decimals == 0
        if plain_int and (int(value) in _PARAMETER_INTEGERS or 1900 <= value <= 2100):
            continue
        out.append((value, 0.5 * 10 ** (-decimals) * multiplier))
    return out


def _matches(value: float, rounding_tol: float, target: float) -> bool:
    # Ratios may legitimately be written as percentages (0.42 -> "42%").
    for t in (abs(target), abs(target) * 100):
        if abs(abs(value) - t) <= max(RELATIVE_TOLERANCE * t, rounding_tol):
            return True
    return False


def _level_word(value: str) -> re.Pattern[str]:
    words = value.replace("_", " ")
    guard = r"(?<!very )" if words == "high" else ""
    return re.compile(rf"{guard}\b{re.escape(words)}\b", re.IGNORECASE)


def check_claim(claim: Claim, bundle: EvidenceBundle, location: str = "claim") -> list[Finding]:
    def finding(rule: str, message: str) -> Finding:
        return Finding(location, rule, message, claim.text)

    out: list[Finding] = []
    text = claim.text.strip()
    if not text:
        return [finding("C9", "claim text is empty")]
    if len(text) > MAX_CLAIM_CHARS:
        out.append(finding("C9", f"claim is longer than {MAX_CLAIM_CHARS} characters; split or shorten it"))

    cited = [bundle.get(i) for i in claim.evidence_ids]
    unknown = [i for i, item in zip(claim.evidence_ids, cited, strict=True) if item is None]
    if unknown:
        out.append(finding("C1", f"cites unknown evidence ids {unknown}"))
    items = [c for c in cited if c is not None]

    if claim.tag is not ClaimTag.ASSUMPTION and not claim.evidence_ids:
        out.append(finding("C2", f"a {claim.tag.value} must cite at least one evidence id"))
    if claim.tag is ClaimTag.FACT and not any(e.kind is EvidenceKind.OBSERVATION for e in items):
        out.append(finding("C3", "a fact must cite at least one provider observation; use 'calculation' otherwise"))
    if claim.tag is ClaimTag.CALCULATION and not any(e.kind is EvidenceKind.CALCULATION for e in items):
        out.append(finding("C3", "a calculation must cite at least one computed evidence item"))

    numeric = [float(e.value) for e in items if e.is_numeric]
    for value, tol in extract_numbers(text):
        if not any(_matches(value, tol, target) for target in numeric):
            out.append(finding("C4", f"the number {value:g} does not match any evidence this claim cites"))

    if _CERTAINTY.search(text):
        out.append(finding("C5", "uses certainty, guarantee or promotional language"))
    if _PRICE_TARGET.search(text):
        out.append(finding("C6", "states or implies a price target"))
    if _ADVICE.search(text):
        out.append(finding("C6", "gives a buy/sell/hold instruction; describe the evidence instead"))
    if claim.tag is ClaimTag.SCENARIO and not _CONDITIONAL.search(text):
        out.append(finding("C7", "a scenario must be conditional (use 'if', 'could', 'would' ...)"))

    for e in items:
        if isinstance(e.value, str) and e.key.endswith(_LEVEL_KEYS) and not _level_word(e.value).search(text):
            out.append(
                finding("C8", f"cites {e.id} ({e.label}) but does not state its value '{e.value.replace('_', ' ')}'")
            )
    return out


def verify_report(
    draft: ReportDraft,
    bundle: EvidenceBundle,
    assessments: Mapping[Horizon, HorizonAssessment | None],
) -> VerificationResult:
    result = VerificationResult()
    located = list(draft.located_claims())
    result.checked_claims = len(located)

    if not draft.headline.text.strip():
        result.findings.append(Finding("headline", "R1", "the report needs a one-sentence headline"))
    for horizon in Horizon:
        narrative = draft.short_term if horizon is Horizon.SHORT_TERM else draft.long_term
        if not narrative.all():
            result.findings.append(
                Finding(horizon.value, "R1", f"the {horizon.value.replace('_', '-')} section is empty")
            )
        a = assessments.get(horizon)
        if a is None or a.risk is None:
            result.findings.append(
                Finding(horizon.value, "R2", f"missing {horizon.value.replace('_', '-')} assessment or risk level")
            )
    if draft.disclaimer.strip() != DISCLAIMER:
        result.findings.append(Finding("disclaimer", "R3", "the standard risk disclaimer is missing or altered"))
    if len(located) > MAX_CLAIMS:
        result.findings.append(Finding("report", "C9", f"too many claims ({len(located)} > {MAX_CLAIMS}); be concise"))

    for location, claim in located:
        result.findings.extend(check_claim(claim, bundle, location))
    return result
