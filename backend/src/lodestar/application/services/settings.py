"""User preferences that shape pipeline runs, plus a read-only view of the platform setup."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any
from uuid import UUID

from lodestar.application.ports import UnitOfWork
from lodestar.domain.errors import ValidationFailed

UowFactory = Callable[[], UnitOfWork]

DEFAULT_PREFERENCES: dict[str, Any] = {
    "polymarket_enabled": True,
    "mismatch_tolerance_pct": 1.5,
    # trader skills (paper trading only)
    "max_loss_pct": 1.0,
    "max_position_pct": 25.0,
    "max_slippage_pct": 0.5,
    "fee_bps": 10.0,
    "slippage_bps": 5.0,
    "horizon_days": 14,
    "min_volume_usd": 5_000_000.0,
    "paper_starting_cash": 10_000.0,
}
# Inclusive (low, high) bounds for numeric preferences.
RANGES: dict[str, tuple[float, float]] = {
    "mismatch_tolerance_pct": (0.1, 10.0),
    "max_loss_pct": (0.1, 5.0),
    "max_position_pct": (1.0, 100.0),
    "max_slippage_pct": (0.05, 5.0),
    "fee_bps": (0.0, 100.0),
    "slippage_bps": (0.0, 100.0),
    "horizon_days": (3, 60),
    "min_volume_usd": (0.0, 1e11),
    "paper_starting_cash": (100.0, 1e9),
}


class SettingsService:
    def __init__(self, uow: UowFactory, platform: Mapping[str, Any]) -> None:
        self._uow, self._platform = uow, dict(platform)

    async def preferences(self, user_id: UUID) -> dict[str, Any]:
        async with self._uow() as uow:
            stored = await uow.settings.get(user_id)
        return {**DEFAULT_PREFERENCES, **{k: v for k, v in stored.items() if k in DEFAULT_PREFERENCES}}

    async def update(self, user_id: UUID, patch: Mapping[str, Any]) -> dict[str, Any]:
        current = await self.preferences(user_id)
        for key, value in patch.items():
            if key not in DEFAULT_PREFERENCES or value is None:
                continue
            if key in RANGES:
                lo, hi = RANGES[key]
                if not lo <= float(value) <= hi:
                    raise ValidationFailed(f"{key.replace('_', ' ')} must be between {lo:g} and {hi:g}")
                current[key] = int(value) if key == "horizon_days" else float(value)
            else:
                current[key] = bool(value)
        async with self._uow() as uow:
            await uow.settings.put(user_id, current)
            await uow.commit()
        return current

    async def view(self, user_id: UUID) -> dict[str, Any]:
        return {**self._platform, "preferences": await self.preferences(user_id)}
