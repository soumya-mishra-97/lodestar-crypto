"""Daily OHLCV bars and the rolling indicators the setup rules need."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

from lodestar.domain.models import Candle, MarketHistory


@dataclass(frozen=True, slots=True)
class Bars:
    """Parallel arrays, oldest first. `approximate` = built from closes only (no real OHLC)."""

    ts: tuple[datetime, ...]
    open: tuple[float, ...]
    high: tuple[float, ...]
    low: tuple[float, ...]
    close: tuple[float, ...]
    volume: tuple[float, ...]
    approximate: bool = False

    def __len__(self) -> int:
        return len(self.close)

    @property
    def dates(self) -> list[date]:
        return [t.date() for t in self.ts]

    @classmethod
    def from_candles(cls, candles: Sequence[Candle]) -> Bars:
        return cls(
            tuple(c.ts for c in candles),
            tuple(c.open for c in candles),
            tuple(c.high for c in candles),
            tuple(c.low for c in candles),
            tuple(c.close for c in candles),
            tuple(c.volume for c in candles),
        )

    @classmethod
    def from_history(cls, history: MarketHistory) -> Bars:
        """Closes only: open = previous close, high/low = max/min(open, close)."""
        closes = history.closes
        opens = [closes[0], *closes[:-1]]
        return cls(
            tuple(p.ts for p in history.points),
            tuple(opens),
            tuple(max(o, c) for o, c in zip(opens, closes, strict=True)),
            tuple(min(o, c) for o, c in zip(opens, closes, strict=True)),
            tuple(closes),
            tuple(history.volumes),
            approximate=True,
        )

    def upto(self, end: int) -> Bars:
        """Bars 0..end inclusive."""
        s = slice(0, end + 1)
        return Bars(
            self.ts[s], self.open[s], self.high[s], self.low[s], self.close[s], self.volume[s], self.approximate
        )

    def to_dicts(self) -> list[dict[str, float | str]]:
        return [
            {"ts": t.isoformat(), "o": o, "h": h, "l": lo, "c": c, "v": v}
            for t, o, h, lo, c, v in zip(self.ts, self.open, self.high, self.low, self.close, self.volume, strict=True)
        ]

    @classmethod
    def from_dicts(cls, rows: Sequence[dict[str, float | str]], *, approximate: bool = False) -> Bars:
        return cls(
            tuple(datetime.fromisoformat(str(r["ts"])) for r in rows),
            tuple(float(r["o"]) for r in rows),
            tuple(float(r["h"]) for r in rows),
            tuple(float(r["l"]) for r in rows),
            tuple(float(r["c"]) for r in rows),
            tuple(float(r["v"]) for r in rows),
            approximate,
        )


def rolling_mean(values: Sequence[float], n: int) -> list[float | None]:
    out: list[float | None] = []
    total = 0.0
    for i, v in enumerate(values):
        total += v
        if i >= n:
            total -= values[i - n]
        out.append(total / n if i >= n - 1 else None)
    return out


def atr_series(bars: Bars, n: int = 14) -> list[float | None]:
    """Wilder's average true range."""
    out: list[float | None] = [None] * len(bars)
    if len(bars) <= n:
        return out
    tr = [bars.high[0] - bars.low[0]]
    for i in range(1, len(bars)):
        prev = bars.close[i - 1]
        tr.append(max(bars.high[i] - bars.low[i], abs(bars.high[i] - prev), abs(bars.low[i] - prev)))
    value = sum(tr[1 : n + 1]) / n
    out[n] = value
    for i in range(n + 1, len(bars)):
        value = (value * (n - 1) + tr[i]) / n
        out[i] = value
    return out


def prior_highest(values: Sequence[float], n: int) -> list[float | None]:
    """Highest of the `n` values *before* each index (excludes the current bar)."""
    out: list[float | None] = [None] * len(values)
    for i in range(n, len(values)):
        out[i] = max(values[i - n : i])
    return out
