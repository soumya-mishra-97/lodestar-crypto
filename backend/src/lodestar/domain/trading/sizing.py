"""Liquidity (order-book walk) and position sizing from the amount you are willing to lose.

Sizing order of operations, each step can only shrink the position:
  1. max loss:     units = max_loss / (entry - stop + round-trip costs per unit)
  2. concentration: notional <= max_position_pct x account equity
  3. liquidity:    expected slippage for the order <= max_slippage_pct (walking the real book)
  4. correlation:  halve the size if it is highly correlated with an open paper position
Paper trading only: the result is a hypothetical size, never an order.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from lodestar.domain.models import OrderBook

CORRELATION_LIMIT = 0.8


def walk_book_slippage_pct(book: OrderBook, notional_usd: float) -> float | None:
    """Average buy price vs mid for a market buy of `notional_usd`; None if the visible book is too thin."""
    mid = book.mid
    if not mid or notional_usd <= 0:
        return 0.0 if mid else None
    remaining, cost, qty = notional_usd, 0.0, 0.0
    for price, size in book.asks:
        level_usd = price * size
        take = min(remaining, level_usd)
        cost += take
        qty += take / price
        remaining -= take
        if remaining <= 1e-9:
            break
    if remaining > 1e-9:
        return None
    return (cost / qty / mid - 1) * 100


def slippage_curve(book: OrderBook, sizes_usd: Sequence[float]) -> list[dict[str, float | None]]:
    return [{"notional_usd": s, "slippage_pct": walk_book_slippage_pct(book, s)} for s in sizes_usd]


def max_size_within(book: OrderBook, max_slippage_pct: float, upper: float) -> float:
    """Largest notional (<= upper) whose book-walk slippage stays within the limit (bisection)."""
    lo, hi = 0.0, upper
    for _ in range(40):
        mid = (lo + hi) / 2
        s = walk_book_slippage_pct(book, mid)
        if s is not None and s <= max_slippage_pct:
            lo = mid
        else:
            hi = mid
    return lo


def correlation(a: Sequence[float], b: Sequence[float]) -> float | None:
    """Pearson correlation of daily returns over the overlapping tail of two close series."""
    n = min(len(a), len(b))
    if n < 20:
        return None
    ra = [y / x - 1 for x, y in zip(a[-n:], a[-n + 1 :], strict=False) if x > 0]
    rb = [y / x - 1 for x, y in zip(b[-n:], b[-n + 1 :], strict=False) if x > 0]
    m = min(len(ra), len(rb))
    if m < 20 or statistics.pstdev(ra[-m:]) == 0 or statistics.pstdev(rb[-m:]) == 0:
        return None
    return statistics.correlation(ra[-m:], rb[-m:])


@dataclass(frozen=True, slots=True)
class SizingInputs:
    entry: float
    stop: float
    equity_usd: float
    max_loss_pct: float
    max_position_pct: float
    max_slippage_pct: float
    fee_bps: float
    slippage_bps: float
    book: OrderBook | None = None
    max_correlation: float | None = None  # with open paper positions


@dataclass(frozen=True, slots=True)
class SizingResult:
    units: float
    notional_usd: float
    pct_of_equity: float
    max_loss_usd: float
    loss_at_stop_usd: float  # including round-trip costs
    stop_distance_pct: float
    expected_slippage_pct: float | None
    binding: str  # max_loss | concentration | liquidity | correlation | no_trade
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "units": self.units,
            "notional_usd": self.notional_usd,
            "pct_of_equity": self.pct_of_equity,
            "max_loss_usd": self.max_loss_usd,
            "loss_at_stop_usd": self.loss_at_stop_usd,
            "stop_distance_pct": self.stop_distance_pct,
            "expected_slippage_pct": self.expected_slippage_pct,
            "binding": self.binding,
            "warnings": list(self.warnings),
        }


def size_position(x: SizingInputs, slippage_of: Callable[[float], float | None] | None = None) -> SizingResult:
    max_loss = x.equity_usd * x.max_loss_pct / 100
    risk = x.entry - x.stop
    cost_per_unit = x.entry * 2 * (x.fee_bps + x.slippage_bps) / 10_000
    warnings: list[str] = []
    if risk <= 0 or x.entry <= 0 or max_loss <= 0:
        return SizingResult(
            0.0, 0.0, 0.0, max_loss, 0.0, 0.0, None, "no_trade", ("Invalid stop: it must sit below the entry.",)
        )

    units = max_loss / (risk + cost_per_unit)
    binding = "max_loss"
    cap = x.equity_usd * x.max_position_pct / 100
    if units * x.entry > cap:
        units, binding = cap / x.entry, "concentration"
    book = x.book
    walk = slippage_of or ((lambda n: walk_book_slippage_pct(book, n)) if book is not None else None)
    slippage = walk(units * x.entry) if walk else None
    if x.book is not None and (slippage is None or slippage > x.max_slippage_pct):
        allowed = max_size_within(x.book, x.max_slippage_pct, units * x.entry)
        units, binding = allowed / x.entry, "liquidity"
        slippage = walk(allowed) if walk else None
        warnings.append("Size reduced so expected slippage stays within your limit.")
    if x.book is None:
        warnings.append("No order book available: slippage was not checked against real depth.")
    if x.max_correlation is not None and x.max_correlation >= CORRELATION_LIMIT:
        units, binding = units / 2, "correlation"
        warnings.append("Highly correlated with an open paper position: size halved.")
    notional = units * x.entry
    return SizingResult(
        units=units,
        notional_usd=notional,
        pct_of_equity=notional / x.equity_usd * 100 if x.equity_usd else 0.0,
        max_loss_usd=max_loss,
        loss_at_stop_usd=units * (risk + cost_per_unit),
        stop_distance_pct=risk / x.entry * 100,
        expected_slippage_pct=slippage,
        binding=binding,
        warnings=tuple(warnings),
    )


def isfinite(v: float | None) -> bool:
    return v is not None and math.isfinite(v)
