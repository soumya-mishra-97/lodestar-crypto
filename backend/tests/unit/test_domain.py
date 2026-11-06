"""Evidence registry, scoring, reconciliation, portfolio maths and address safety."""

from datetime import UTC, datetime

import pytest

from lodestar.domain.addresses import Chain, looks_like_secret, normalize_address
from lodestar.domain.errors import ValidationFailed
from lodestar.domain.evidence import EvidenceKind, EvidenceRegistry
from lodestar.domain.models import Horizon, RiskLevel, Stance
from lodestar.domain.portfolio import herfindahl, portfolio_risk, portfolio_volatility_pct, weights
from lodestar.domain.reconciliation import SourcePrice, reconcile_prices
from lodestar.domain.scoring import RiskInputs, Signal, assess_risk, synthesize

NOW = datetime(2026, 11, 3, tzinfo=UTC)


def test_registry_ids_are_namespaced_idempotent_and_skip_missing() -> None:
    reg = EvidenceRegistry("TEC", as_of=NOW)
    a = reg.calculate("rsi_14", "RSI", 55.123456789, "index", inputs=["DAT-01", None])
    assert a == "TEC-01"
    assert reg.calculate("rsi_14", "RSI", 55.123456789, "index") == "TEC-01"  # same value: same id
    assert reg.calculate("sma_20", "SMA", None, "usd") is None  # never invent a value
    item = reg.items[0]
    assert item.kind is EvidenceKind.CALCULATION
    assert item.inputs == ("DAT-01",)
    assert item.value == 55.1235  # rounded once, at registration


def _inputs(**over: object) -> RiskInputs:
    base = {
        "volatility_30d_pct": 70.0,
        "max_drawdown_1y_pct": -40.0,
        "depth_2pct_usd": 2e6,
        "market_cap_usd": 5e9,
        "circulating_ratio": 0.9,
        "fear_greed": 50,
        "change_7d_pct": 3.0,
        "price_sources_disagree": False,
    }
    return RiskInputs(**{**base, **over})  # type: ignore[arg-type]


def test_risk_is_assessed_separately_per_horizon() -> None:
    def ev(_: str) -> None:
        return None

    short = assess_risk(Horizon.SHORT_TERM, _inputs(), ev)
    long = assess_risk(Horizon.LONG_TERM, _inputs(), ev)
    assert {f.name for f in short.factors} == {"volatility", "liquidity"}
    assert {"drawdown", "size", "volatility", "liquidity"} <= {f.name for f in long.factors}
    assert short.horizon is Horizon.SHORT_TERM
    assert long.horizon is Horizon.LONG_TERM

    stressed = assess_risk(
        Horizon.SHORT_TERM, _inputs(volatility_30d_pct=180, depth_2pct_usd=5e4, fear_greed=90, change_7d_pct=-30,
                                    price_sources_disagree=True), ev,
    )  # fmt: skip
    assert stressed.level is RiskLevel.VERY_HIGH
    assert "data_disagreement" in {f.name for f in stressed.factors}


def test_synthesis_uses_only_its_horizon_and_reports_confidence() -> None:
    risk = assess_risk(Horizon.LONG_TERM, _inputs(), lambda _: None)
    signals = [
        Signal("a", Horizon.LONG_TERM, 8.0, "x"),
        Signal("b", Horizon.LONG_TERM, 4.0, "y"),
        Signal("c", Horizon.SHORT_TERM, -30.0, "z"),
    ]
    a = synthesize(
        Horizon.LONG_TERM, signals, risk, history_days=365, optional_sources_present=4, optional_sources_total=4
    )
    assert (a.score, a.stance, a.confidence) == (62.0, Stance.FAVORABLE, 1.0)
    assert [s.name for s in a.signals] == ["a", "b"]


def test_reconciliation_flags_outliers_against_the_median() -> None:
    quotes = [SourcePrice("coingecko", 100.0, NOW), SourcePrice("kraken", 100.4, NOW), SourcePrice("llama", 103.0, NOW)]
    rec = reconcile_prices(quotes, tolerance_pct=1.5)
    assert rec.status == "mismatch"
    assert rec.mismatched_sources == ["llama"]
    assert rec.max_deviation_pct == pytest.approx(2.589, abs=1e-3)
    assert reconcile_prices(quotes[:2], tolerance_pct=1.5).status == "consistent"
    assert reconcile_prices(quotes[:1], tolerance_pct=1.5).status == "single_source"


def test_portfolio_risk_blends_assets_and_penalises_concentration() -> None:
    ws = weights({"btc": 750.0, "pol": 250.0, "dust": 0.0})
    assert ws == {"btc": 0.75, "pol": 0.25}
    assert herfindahl(ws) == pytest.approx(0.625)
    pr = portfolio_risk(ws, {"btc": 30.0, "pol": 60.0})
    assert pr is not None
    assert pr.weighted_asset_risk == pytest.approx(37.5)
    assert pr.concentration_points == 15.0  # HHI >= 0.6
    assert pr.score == 52.5
    assert pr.level is RiskLevel.HIGH
    flat = {"btc": [100.0] * 40, "pol": [1.0] * 40}
    assert portfolio_volatility_pct(ws, flat) == 0.0


def test_address_validation_and_secret_rejection() -> None:
    evm = "0x" + "aB" * 20
    assert normalize_address(Chain.POLYGON, evm) == evm.lower()
    assert normalize_address(Chain.BITCOIN, "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq").startswith("bc1q")
    with pytest.raises(ValidationFailed):
        normalize_address(Chain.ETHEREUM, "0x1234")
    seed = "abandon " * 11 + "about"
    private_key = "0x" + "1f" * 32
    for secret in (seed, private_key, "5HueCGU8rMjxEXxiPuD5BDku4MkFqeZyd4dZ1jvhTVqvbTLvyTJ"):
        assert looks_like_secret(secret)
        with pytest.raises(ValidationFailed, match="private key or seed phrase"):
            normalize_address(Chain.ETHEREUM, secret)
    assert not looks_like_secret(evm)
