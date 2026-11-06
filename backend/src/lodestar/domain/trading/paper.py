"""Paper-trading engine: the same execution rules as the backtester, applied to new daily bars.

Fake money only. There is no order placement anywhere in Lodestar.

  pending   -> a completed daily close above the trigger level            -> triggered
  triggered -> fill at the next bar's open (+slippage, +fee); cancel if it gaps
               more than 2% above the entry zone                            -> open
  open      -> stop / profit-taking rule / time exit (stop assumed first)  -> closed
  pending   -> expires after `expiry_bars` bars without a trigger            -> cancelled
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Literal

PositionStatus = Literal["pending", "triggered", "open", "closed", "cancelled"]
GAP_TOLERANCE = 1.02


@dataclass(frozen=True, slots=True)
class DailyBar:
    ts: datetime
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True, slots=True)
class PaperState:
    status: PositionStatus
    trigger: float
    entry_high: float
    stop: float
    profit_level: float
    horizon: int
    expiry_bars: int
    bars_seen: int = 0
    bars_held: int = 0
    entry_price: float | None = None
    entry_at: datetime | None = None
    exit_price: float | None = None
    exit_at: datetime | None = None
    exit_reason: str | None = None


@dataclass(frozen=True, slots=True)
class Fill:
    side: Literal["buy", "sell"]
    price: float
    at: datetime
    reason: str


def advance(state: PaperState, bar: DailyBar, *, slippage_bps: float) -> tuple[PaperState, Fill | None]:
    """Apply one completed daily bar. Pure: returns the new state and any simulated fill."""
    slip = slippage_bps / 10_000
    s = replace(state, bars_seen=state.bars_seen + 1)
    if s.status == "pending":
        if bar.close > s.trigger:
            return replace(s, status="triggered"), None
        if s.bars_seen >= s.expiry_bars:
            return replace(s, status="cancelled", exit_reason="expired without a trigger", exit_at=bar.ts), None
        return s, None
    if s.status == "triggered":
        price = bar.open * (1 + slip)
        if price > s.entry_high * GAP_TOLERANCE:
            return replace(s, status="cancelled", exit_reason="gapped above the entry zone", exit_at=bar.ts), None
        s = replace(s, status="open", entry_price=price, entry_at=bar.ts, bars_held=0)
        fill: Fill | None = Fill("buy", price, bar.ts, "trigger")
        # The entry bar can also hit the stop or the profit rule after the open.
        s2, exit_fill = _check_exit(s, bar, slip, entry_bar=True)
        return s2, exit_fill or fill
    if s.status == "open":
        return _check_exit(s, bar, slip, entry_bar=False)
    return s, None


def _check_exit(s: PaperState, bar: DailyBar, slip: float, *, entry_bar: bool) -> tuple[PaperState, Fill | None]:
    held = s.bars_held + 1
    price: float | None = None
    reason = ""
    if bar.low <= s.stop:
        price, reason = (s.stop if entry_bar else min(bar.open, s.stop)), "stop"
    elif bar.high >= s.profit_level:
        price, reason = (s.profit_level if entry_bar else max(bar.open, s.profit_level)), "profit_rule"
    elif held >= s.horizon:
        price, reason = bar.close, "time"
    if price is None:
        return replace(s, bars_held=held), None
    exit_price = price * (1 - slip)
    closed = replace(s, status="closed", bars_held=held, exit_price=exit_price, exit_at=bar.ts, exit_reason=reason)
    return closed, Fill("sell", exit_price, bar.ts, reason)
