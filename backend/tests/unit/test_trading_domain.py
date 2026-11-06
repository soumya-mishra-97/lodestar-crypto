"""Trading maths: no look-ahead, honest statistics, costs, sizing limits, the paper engine, plan verification."""

import itertools
import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from lodestar.domain.claims import Claim, ClaimTag
from lodestar.domain.evidence import EvidenceBundle, EvidenceRegistry
from lodestar.domain.models import OrderBook
from lodestar.domain.trading import backtest as bt
from lodestar.domain.trading import stats
from lodestar.domain.trading.bars import Bars
from lodestar.domain.trading.paper import DailyBar, PaperState, advance
from lodestar.domain.trading.plan import TRADE_DISCLAIMER, TradePlanDraft, verify_trade_plan
from lodestar.domain.trading.scanner import scan_metrics
from lodestar.domain.trading.setups import SetupKind, compute, current_levels, signal_at
from lodestar.domain.trading.sizing import SizingInputs, size_position, walk_book_slippage_pct

T0 = datetime(2024, 1, 1, tzinfo=UTC)


def make_bars(closes: list[float], *, volume_spikes: set[int] | None = None) -> Bars:
    spikes = volume_spikes or set()
    opens = [closes[0], *closes[:-1]]
    return Bars(
        tuple(T0 + timedelta(days=i) for i in range(len(closes))),
        tuple(opens),
        tuple(max(o, c) * 1.01 for o, c in zip(opens, closes, strict=True)),
        tuple(min(o, c) * 0.99 for o, c in zip(opens, closes, strict=True)),
        tuple(closes),
        tuple(3e6 if i in spikes else 1e6 for i in range(len(closes))),
    )


def wave(n: int = 400, drift: float = 0.002) -> Bars:
    closes = [100 * math.exp(drift * i) * (1 + 0.06 * math.sin(i / 7)) for i in range(n)]
    return make_bars(closes, volume_spikes=set(range(0, n, 9)))


# ---------------------------------------------------------------- setups


@pytest.mark.parametrize("kind", list(SetupKind))
def test_signals_never_look_ahead(kind: SetupKind) -> None:
    bars = wave()
    full = compute(bars)
    for end in (120, 200, 333):
        truncated = bars.upto(end)
        part = compute(truncated)
        for i in range(end + 1):
            assert signal_at(kind, full, bars, i) == signal_at(kind, part, truncated, i)


def test_levels_are_conditions_with_invalidation_below_the_zone() -> None:
    lv = current_levels(wave())
    assert lv.entry_low == lv.level < lv.entry_high
    assert lv.invalidation < lv.entry_low < lv.profit_level
    assert lv.profit_level == pytest.approx(lv.entry_mid + 2 * (lv.entry_mid - lv.invalidation))
    assert lv.status in ("active", "extended", "waiting")
    downtrend = current_levels(make_bars([200 - i * 0.3 for i in range(300)]))
    assert downtrend.kind is SetupKind.TREND_RECLAIM
    assert downtrend.trend_up is False


# ---------------------------------------------------------------- statistics


def test_wilson_and_t_intervals() -> None:
    lo, hi = stats.wilson(5, 10) or (0, 0)
    assert (round(lo, 3), round(hi, 3)) == (0.237, 0.763)
    assert stats.wilson(0, 0) is None
    ci = stats.mean_ci([1.0, 2.0, 3.0, 4.0])
    assert ci is not None
    assert ci[0] < 2.5 < ci[1]
    assert [stats.reliability(n) for n in (3, 12, 40)] == ["insufficient", "small", "adequate"]


def test_analog_outcomes_do_not_overlap_and_scenarios_partition_the_sample() -> None:
    bars = wave(600)
    outcomes = stats.analog_outcomes(bars, SetupKind.PULLBACK, horizon=14, cost_pct=0.3)
    assert outcomes
    gaps = [b.signal_index - a.signal_index for a, b in itertools.pairwise(outcomes)]
    assert all(g >= 14 for g in gaps)
    for o in outcomes:
        assert o.entry == bars.open[o.signal_index + 1]  # filled the bar after the signal
        assert o.max_drawdown_pct <= 0
    scen = stats.scenarios(outcomes, stats.horizon_sigma_pct(bars, 14), 14)
    assert [s.name for s in scen] == ["bull", "base", "bear"]
    assert sum(s.count for s in scen) == len(outcomes)
    free = stats.analog_outcomes(bars, SetupKind.PULLBACK, horizon=14, cost_pct=0.0)
    assert [round(a.return_pct - b.return_pct, 6) for a, b in zip(free, outcomes, strict=True)] == [0.3] * len(outcomes)


# ---------------------------------------------------------------- backtest


def test_backtest_charges_costs_and_fills_after_the_signal() -> None:
    bars = wave(700)
    cfg = bt.BacktestConfig(kind=SetupKind.PULLBACK, fee_bps=0, slippage_bps=0)
    costly = replace(cfg, fee_bps=50, slippage_bps=50)
    params = cfg.grid()[0]
    free = bt.simulate(bars, cfg.kind, params, cfg, 60, 699)
    paid = bt.simulate(bars, costly.kind, params, costly, 60, 699)
    assert free.trades
    assert [t.entry_index for t in free.trades] == [t.signal_index + 1 for t in free.trades]
    assert all(t.entry == bars.open[t.entry_index] for t in free.trades)
    assert all(a.exit_index < b.signal_index + 1 for a, b in zip(free.trades, free.trades[1:], strict=False))
    assert sum(t.return_pct for t in paid.trades) < sum(t.return_pct for t in free.trades)

    report = bt.run_backtest(bars, cfg)
    assert report.oos_range[0] > 55
    assert report.folds
    assert all(f.test[0] > f.train[1] for f in report.folds)  # walk-forward tests only on unseen windows
    assert any("history" in w or "trades" in w for w in report.warnings)


# ---------------------------------------------------------------- sizing and liquidity


def book(levels: int = 20, qty: float = 10.0) -> OrderBook:
    return OrderBook(
        "x",
        "XUSD",
        tuple((100 - 0.1 * k, qty) for k in range(1, levels + 1)),
        tuple((100 + 0.1 * k, qty) for k in range(1, levels + 1)),
        T0,
    )


def test_book_walk_and_sizing_limits() -> None:
    b = book()
    assert walk_book_slippage_pct(b, 1001) == pytest.approx(0.1, abs=1e-3)  # first ask level only
    assert walk_book_slippage_pct(b, 1e9) is None  # book exhausted

    base = SizingInputs(entry=100, stop=90, equity_usd=10_000, max_loss_pct=1, max_position_pct=50, max_slippage_pct=5,
                        fee_bps=10, slippage_bps=5)  # fmt: skip
    s = size_position(base)
    assert s.binding == "max_loss"
    assert s.loss_at_stop_usd == pytest.approx(100)
    assert s.loss_at_stop_usd <= s.max_loss_usd + 1e-9

    tight = size_position(replace(base, stop=99.9))
    assert tight.binding == "concentration"
    assert tight.notional_usd == pytest.approx(5_000)

    # A $1M account risking 1% wants ~$97k of a book holding ~$20k per side: liquidity binds.
    thin = size_position(replace(base, equity_usd=1_000_000, book=b, max_slippage_pct=0.2))
    assert thin.binding == "liquidity"
    assert 0 < thin.notional_usd < 20_000
    assert (thin.expected_slippage_pct or 0) <= 0.2 + 1e-9

    correlated = size_position(replace(base, max_correlation=0.9))
    assert correlated.binding == "correlation"
    assert correlated.units == pytest.approx(s.units / 2)

    assert size_position(replace(base, stop=101)).binding == "no_trade"


# ---------------------------------------------------------------- paper engine


def bar(day: int, o: float, h: float, lo: float, c: float) -> DailyBar:
    return DailyBar(T0 + timedelta(days=day), o, h, lo, c)


def test_paper_engine_trigger_fill_and_exits() -> None:
    s = PaperState("pending", trigger=100, entry_high=102, stop=95, profit_level=110, horizon=5, expiry_bars=3)
    s, fill = advance(s, bar(1, 98, 99.5, 97, 99), slippage_bps=0)
    assert (s.status, fill) == ("pending", None)
    s, _ = advance(s, bar(2, 99, 101, 98, 100.5), slippage_bps=0)  # close above trigger
    assert s.status == "triggered"
    s, fill = advance(s, bar(3, 101, 103, 100.5, 102), slippage_bps=10)
    assert s.status == "open"
    assert fill is not None
    assert fill.price == pytest.approx(101 * 1.001)  # next open + slippage
    s, fill = advance(s, bar(4, 105, 111, 104, 109), slippage_bps=0)
    assert (s.status, s.exit_reason, s.exit_price) == ("closed", "profit_rule", 110)

    stop = replace(s, status="open", bars_held=1, exit_price=None, exit_reason=None)
    closed, _ = advance(stop, bar(5, 94, 96, 90, 92), slippage_bps=0)  # gaps below the stop: fills at the open
    assert (closed.exit_reason, closed.exit_price) == ("stop", 94)

    timed = replace(stop, bars_held=4)
    closed, _ = advance(timed, bar(6, 100, 101, 99, 100), slippage_bps=0)
    assert (closed.exit_reason, closed.exit_price) == ("time", 100)

    gap = PaperState("triggered", trigger=100, entry_high=102, stop=95, profit_level=110, horizon=5, expiry_bars=3)
    cancelled, _ = advance(gap, bar(7, 110, 112, 108, 111), slippage_bps=0)
    assert (cancelled.status, cancelled.exit_reason) == ("cancelled", "gapped above the entry zone")

    stale = PaperState("pending", trigger=100, entry_high=102, stop=95, profit_level=110, horizon=5, expiry_bars=2)
    for d in (8, 9):
        stale, _ = advance(stale, bar(d, 90, 91, 89, 90), slippage_bps=0)
    assert (stale.status, stale.exit_reason) == ("cancelled", "expired without a trigger")


# ---------------------------------------------------------------- scanner


def test_scanner_prefers_strength_and_filters_liquidity() -> None:
    up = make_bars([100 * 1.004**i for i in range(150)], volume_spikes=set(range(140, 150)))
    down = make_bars([100 * 0.996**i for i in range(150)])
    btc = [100.0] * 150
    a = scan_metrics(up, btc, volume_24h_usd=5e7, min_volume_usd=1e7)
    b = scan_metrics(down, btc, volume_24h_usd=5e6, min_volume_usd=1e7)
    assert a.score > b.score
    assert a.trend_points == 4
    assert b.trend_points == 0
    assert (a.passes_liquidity, b.passes_liquidity) == (True, False)
    assert a.rs_vs_btc_pct > 0 > b.rs_vs_btc_pct


# ---------------------------------------------------------------- trade-plan verifier


def plan_fixture() -> tuple[TradePlanDraft, EvidenceBundle]:
    now = T0
    tim, sce, siz = (EvidenceRegistry(ns, as_of=now) for ns in ("TIM", "SCE", "SIZ"))
    t = {
        k: tim.calculate(k, k, v, "usd")
        for k, v in (
            ("trigger_level", 100.0),
            ("entry_zone_low", 100.0),
            ("entry_zone_high", 102.0),
            ("invalidation_level", 95.0),
        )
    }
    status = tim.calculate("setup_status", "status", "waiting", "text")
    s = {
        k: sce.calculate(k, k, v, "pct")
        for k, v in (("scenario_bull_pct", 40.0), ("scenario_base_pct", 35.0), ("scenario_bear_pct", 25.0))
    }
    rel = sce.calculate("sample_reliability", "reliability", "small", "text")
    n = sce.calculate("sample_size", "n", 20.0, "count")
    z = {
        k: siz.calculate(k, k, v, "usd")
        for k, v in (("units", 10.0), ("notional_usd", 1010.0), ("max_loss_usd", 100.0), ("loss_at_stop_usd", 72.0))
    }
    risk = siz.calculate("risk_level", "risk", "high", "text")
    c = ClaimTag.CALCULATION
    draft = TradePlanDraft(
        headline=Claim("The setup is waiting.", ClaimTag.INTERPRETATION, (status or "",)),
        setup=(),
        timing=(
            Claim(
                "Entry zone: $100.00 to $102.00 after a daily close above $100.00.",
                c,
                (t["entry_zone_low"] or "", t["entry_zone_high"] or "", t["trigger_level"] or ""),
            ),
        ),
        scenarios=(
            Claim("Bull case: 40.0% of past signals.", c, (s["scenario_bull_pct"] or "",)),
            Claim("Base case: 35.0% of past signals.", c, (s["scenario_base_pct"] or "",)),
            Claim("Bear case: 25.0% of past signals.", c, (s["scenario_bear_pct"] or "",)),
            Claim("The sample is small (20 signals).", ClaimTag.ASSUMPTION, (rel or "", n or "")),
        ),
        risk=(
            Claim(
                "Risk is high; size 10 units, $1,010.00, losing $100.00 at most.",
                c,
                (risk or "", z["units"] or "", z["notional_usd"] or "", z["max_loss_usd"] or ""),
            ),
        ),
        invalidation=(Claim("A daily close below $95.00 invalidates the setup.", c, (t["invalidation_level"] or "",)),),
        evidence=(),
        assumptions=(),
        disclaimer=TRADE_DISCLAIMER,
    )
    return draft, EvidenceBundle(tim.items + sce.items + siz.items)


def rules(draft: TradePlanDraft, bundle: EvidenceBundle) -> set[str]:
    return {f.rule for f in verify_trade_plan(draft, bundle).findings}


def test_trade_plan_verifier_rules() -> None:
    draft, bundle = plan_fixture()
    assert rules(draft, bundle) == set()
    assert "P1" in rules(replace(draft, invalidation=()), bundle) | rules(replace(draft, timing=()), bundle)
    assert "P2" in rules(
        replace(
            draft,
            timing=(
                *draft.timing,
                Claim("Now is the best time to enter.", ClaimTag.INTERPRETATION, draft.timing[0].evidence_ids),
            ),
        ),
        bundle,
    )
    assert "P3" in rules(replace(draft, scenarios=draft.scenarios[:2] + draft.scenarios[3:]), bundle)
    assert "P3" in rules(replace(draft, scenarios=draft.scenarios[:3]), bundle)  # small sample not stated
    assert "P4" in rules(
        replace(draft, risk=(Claim("Risk is high.", ClaimTag.CALCULATION, draft.risk[0].evidence_ids[:1]),)), bundle
    )
    over = EvidenceBundle(tuple(replace(e, value=150.0) if e.key == "loss_at_stop_usd" else e for e in bundle.items))
    assert "P4" in rules(draft, over)
    assert "P7" in rules(replace(draft, disclaimer="Trade at your own risk."), bundle)
    assert "C6" in rules(
        replace(
            draft,
            timing=(*draft.timing, Claim("Price will reach $102.00.", ClaimTag.SCENARIO, draft.timing[0].evidence_ids)),
        ),
        bundle,
    )
