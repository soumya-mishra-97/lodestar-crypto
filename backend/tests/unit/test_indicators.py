import math

import pytest

from lodestar.domain.indicators import (
    bollinger,
    compute_indicators,
    ema_series,
    macd,
    max_drawdown_pct,
    pct_change,
    realized_volatility_pct,
    rsi,
    sma,
)
from tests.fakes import synthetic_history


def test_sma_uses_last_n_values() -> None:
    assert sma([1, 2, 3, 4, 5], 3) == pytest.approx(4.0)
    assert sma([1, 2], 3) is None


def test_ema_seeds_with_sma_and_tracks_constant_series() -> None:
    assert ema_series([5.0] * 30, 10)[-1] == pytest.approx(5.0)
    assert ema_series([1.0, 2.0], 5) == []


def test_rsi_extremes() -> None:
    assert rsi([float(i) for i in range(1, 40)]) == pytest.approx(100.0)
    assert rsi([float(i) for i in range(40, 1, -1)]) == pytest.approx(0.0)
    assert rsi([10.0] * 30) == pytest.approx(50.0)
    assert rsi([1.0] * 5) is None


def test_macd_is_positive_in_an_accelerating_uptrend() -> None:
    closes = [math.exp(0.01 * i) for i in range(120)]
    result = macd(closes)
    assert result is not None
    assert result.macd > 0


def test_bollinger_percent_b_is_mid_for_flat_series() -> None:
    band = bollinger([3.0] * 25)
    assert band is not None
    assert band.percent_b == pytest.approx(0.5)


def test_max_drawdown_and_pct_change() -> None:
    assert max_drawdown_pct([100, 50, 75, 120]) == pytest.approx(-50.0)
    assert pct_change([100, 110, 121], 2) == pytest.approx(21.0)
    assert pct_change([100], 5) is None


def test_volatility_is_zero_for_constant_growth() -> None:
    closes = [100 * 1.01**i for i in range(40)]
    assert realized_volatility_pct(closes) == pytest.approx(0.0, abs=1e-9)


def test_compute_indicators_on_a_year_of_data() -> None:
    ind = compute_indicators(synthetic_history("x", days=365))
    assert ind.history_days == 365
    assert ind.sma_200 is not None
    assert ind.rsi_14 is not None
    assert ind.support_30d is not None
    assert ind.resistance_30d is not None
    assert ind.support_30d <= ind.last_close <= ind.resistance_30d
