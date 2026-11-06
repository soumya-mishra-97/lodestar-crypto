"""The verifier decides what a human may see: every rule gets a positive and a negative case."""

from datetime import UTC, datetime

import pytest

from lodestar.domain.claims import Claim, ClaimTag
from lodestar.domain.evidence import EvidenceBundle, EvidenceRegistry
from lodestar.domain.models import Horizon, RiskLevel, Stance
from lodestar.domain.report import DISCLAIMER, HorizonNarrative, ReportDraft
from lodestar.domain.scoring import HorizonAssessment, RiskAssessment
from lodestar.domain.verification import check_claim, extract_numbers, verify_report

T = ClaimTag
NOW = datetime(2026, 11, 3, tzinfo=UTC)


@pytest.fixture
def bundle() -> EvidenceBundle:
    dat = EvidenceRegistry("DAT", as_of=NOW)
    dat.observe("price_usd", "Price", 0.08781234, "usd", source="coingecko")
    dat.observe("market_cap_usd", "Market cap", 1_234_000_000.0, "usd", source="coingecko")
    dat.observe("change_7d_pct", "7d change", -4.2, "pct", source="coingecko")
    tec = EvidenceRegistry("TEC", as_of=NOW)
    tec.calculate("rsi_14", "RSI", 55.1234, "index")
    tec.calculate("bollinger_pct_b", "%B", 0.42, "ratio")
    asm = EvidenceRegistry("ASM", as_of=NOW)
    asm.calculate("short_term_stance", "Short-term stance", "favorable", "text")
    rsk = EvidenceRegistry("RSK", as_of=NOW)
    rsk.calculate("long_term_risk_level", "Long-term risk level", "high", "text")
    rsk.calculate("short_term_risk_level", "Short-term risk level", "very_high", "text")
    return EvidenceBundle(dat.items + tec.items + asm.items + rsk.items)


def rules(claim: Claim, bundle: EvidenceBundle) -> list[str]:
    return [f.rule for f in check_claim(claim, bundle)]


def test_grounded_claims_pass(bundle: EvidenceBundle) -> None:
    ok = [
        Claim("Price is $0.0878.", T.FACT, ("DAT-01",)),
        Claim("Market cap is $1.23B.", T.FACT, ("DAT-02",)),
        Claim("Price fell 4.2% over seven days.", T.FACT, ("DAT-03",)),
        Claim("The 14-day RSI is 55.1.", T.CALCULATION, ("TEC-01",)),
        Claim("Price sits at 42% of its Bollinger range.", T.CALCULATION, ("TEC-02",)),  # ratio as percent
        Claim("If momentum fades, price could retest recent lows.", T.SCENARIO, ("TEC-01",)),
        Claim("Scores summarise past data and do not predict prices.", T.ASSUMPTION),
        Claim("Short-term signals are favorable.", T.INTERPRETATION, ("ASM-01",)),
        Claim("Long-term risk is high.", T.INTERPRETATION, ("RSK-01",)),
        Claim("Short-term risk is very high.", T.INTERPRETATION, ("RSK-02",)),
    ]
    for claim in ok:
        assert rules(claim, bundle) == [], claim.text


@pytest.mark.parametrize(
    ("claim", "rule"),
    [
        (Claim("Price is $0.0878.", T.FACT, ("DAT-99",)), "C1"),
        (Claim("Momentum is improving.", T.INTERPRETATION), "C2"),
        (Claim("The RSI is 55.1.", T.FACT, ("TEC-01",)), "C3"),  # a calculation tagged as fact
        (Claim("Price is $0.0878.", T.CALCULATION, ("DAT-01",)), "C3"),  # an observation tagged as calculation
        (Claim("Price is $0.12.", T.FACT, ("DAT-01",)), "C4"),  # number does not match
        (Claim("Market cap is $1.23B and RSI is 55.", T.FACT, ("DAT-02",)), "C4"),  # 55 not cited
        (Claim("This is a guaranteed winner.", T.INTERPRETATION, ("TEC-01",)), "C5"),
        (Claim("It is risk-free at these levels.", T.INTERPRETATION, ("TEC-01",)), "C5"),
        (Claim("Our price target is higher.", T.INTERPRETATION, ("TEC-01",)), "C6"),
        (Claim("Price will reach new highs.", T.INTERPRETATION, ("TEC-01",)), "C6"),
        (Claim("You should buy the dip.", T.INTERPRETATION, ("TEC-01",)), "C6"),
        (Claim("Price rallies to the upper band.", T.SCENARIO, ("TEC-02",)), "C7"),
        (Claim("Short-term signals are unfavorable.", T.INTERPRETATION, ("ASM-01",)), "C8"),
        (Claim("Long-term risk is very high.", T.INTERPRETATION, ("RSK-01",)), "C8"),  # cites "high"
        (Claim("x" * 401, T.ASSUMPTION), "C9"),
    ],
)
def test_each_rule_rejects(claim: Claim, rule: str, bundle: EvidenceBundle) -> None:
    assert rule in rules(claim, bundle)


def test_number_extraction_skips_parameters_years_and_ids() -> None:
    assert extract_numbers("The 14-day RSI and 200-day average in 2026 (TEC-04)") == []
    values = [v for v, _ in extract_numbers("$1.23B, 4.2%, 1,234 tokens and 3k")]
    assert values == pytest.approx([1.23e9, 4.2, 1234, 3000])


def _assessment(h: Horizon) -> HorizonAssessment:
    return HorizonAssessment(h, 55.0, Stance.NEUTRAL, 0.9, RiskAssessment(h, RiskLevel.HIGH, 55.0, ()), ())


def _draft(**overrides: object) -> ReportDraft:
    base = {
        "headline": Claim("Short-term signals are favorable.", T.INTERPRETATION, ("ASM-01",)),
        "short_term": HorizonNarrative(thesis=(Claim("The 14-day RSI is 55.1.", T.CALCULATION, ("TEC-01",)),)),
        "long_term": HorizonNarrative(risks=(Claim("Long-term risk is high.", T.CALCULATION, ("RSK-01",)),)),
        "disclaimer": DISCLAIMER,
    }
    return ReportDraft(**{**base, **overrides})  # type: ignore[arg-type]


def test_report_level_rules(bundle: EvidenceBundle) -> None:
    both = {h: _assessment(h) for h in Horizon}
    assert verify_report(_draft(), bundle, both).passed

    missing_long = verify_report(_draft(long_term=HorizonNarrative()), bundle, both)
    assert [f.rule for f in missing_long.findings] == ["R1"]

    no_assessment = verify_report(_draft(), bundle, {Horizon.SHORT_TERM: both[Horizon.SHORT_TERM]})
    assert [f.rule for f in no_assessment.findings] == ["R2"]

    altered = verify_report(_draft(disclaimer="Not advice."), bundle, both)
    assert [f.rule for f in altered.findings] == ["R3"]


def test_findings_locate_claims_for_repair(bundle: EvidenceBundle) -> None:
    bad = HorizonNarrative(watch=(Claim("Price will reach $1.", T.SCENARIO, ("DAT-01",)),))
    result = verify_report(_draft(short_term=bad), bundle, {h: _assessment(h) for h in Horizon})
    assert not result.passed
    assert all(f.location == "short_term.watch[0]" for f in result.findings)
    assert any("price target" in fb for fb in result.feedback())
