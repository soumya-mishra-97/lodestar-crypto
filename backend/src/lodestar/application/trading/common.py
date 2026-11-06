"""Shared helpers for the trader suite: bar loading and trading preferences."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from lodestar.application.ports import DataSources
from lodestar.domain.errors import InsufficientData, LodestarError
from lodestar.domain.models import Asset
from lodestar.domain.trading.bars import Bars

BAR_DAYS = 720  # Kraken serves up to 720 daily candles; the demo exchange serves 730
MIN_BARS = 120


@dataclass(frozen=True, slots=True)
class TradingPrefs:
    max_loss_pct: float = 1.0  # of the paper account, per trade
    max_position_pct: float = 25.0
    max_slippage_pct: float = 0.5
    fee_bps: float = 10.0
    slippage_bps: float = 5.0
    horizon_days: int = 14
    min_volume_usd: float = 5_000_000.0
    paper_starting_cash: float = 10_000.0

    @property
    def round_trip_cost_pct(self) -> float:
        return 2 * (self.fee_bps + self.slippage_bps) / 100

    @classmethod
    def from_prefs(cls, prefs: Mapping[str, Any] | None) -> TradingPrefs:
        p = prefs or {}
        d = cls()
        return cls(
            max_loss_pct=float(p.get("max_loss_pct", d.max_loss_pct)),
            max_position_pct=float(p.get("max_position_pct", d.max_position_pct)),
            max_slippage_pct=float(p.get("max_slippage_pct", d.max_slippage_pct)),
            fee_bps=float(p.get("fee_bps", d.fee_bps)),
            slippage_bps=float(p.get("slippage_bps", d.slippage_bps)),
            horizon_days=int(p.get("horizon_days", d.horizon_days)),
            min_volume_usd=float(p.get("min_volume_usd", d.min_volume_usd)),
            paper_starting_cash=float(p.get("paper_starting_cash", d.paper_starting_cash)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


async def load_bars(sources: DataSources, asset: Asset, days: int = BAR_DAYS) -> Bars:
    """Exchange OHLC when the venue lists the pair, otherwise daily closes from the primary feed."""
    try:
        candles = await sources.exchange.get_candles(asset.symbol, days)
    except LodestarError:
        candles = []
    if len(candles) >= MIN_BARS:
        return Bars.from_candles(candles)
    history = await sources.market.get_history(asset.coingecko_id, min(days, 365))
    if len(history.points) < MIN_BARS:
        raise InsufficientData(f"Only {len(history.points)} days of history for {asset.symbol}")
    return Bars.from_history(history)
