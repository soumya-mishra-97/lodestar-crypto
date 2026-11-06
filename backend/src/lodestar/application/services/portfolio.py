"""Portfolio: manual entry, CSV import, read-only public-address import, valuation."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Callable
from typing import Any
from uuid import UUID

import structlog

from lodestar.application.importers import parse_holdings_csv
from lodestar.application.ports import DataSources, UnitOfWork
from lodestar.application.serialization import to_jsonable
from lodestar.application.services.assets import AssetService
from lodestar.domain.addresses import Chain, normalize_address, short_address
from lodestar.domain.errors import LodestarError, NotFoundError, ValidationFailed
from lodestar.domain.models import Asset, Holding, MarketSnapshot

log = structlog.get_logger(__name__)
UowFactory = Callable[[], UnitOfWork]


def source_label(source: str) -> str:
    if source.startswith("wallet:"):
        _, chain, address = source.split(":", 2)
        return f"{chain.capitalize()} wallet {short_address(address)}"
    return {"manual": "Manual", "csv": "CSV import"}.get(source, source)


class PortfolioService:
    def __init__(self, uow: UowFactory, sources: DataSources, assets: AssetService, *, concurrency: int = 5) -> None:
        self._uow, self._s, self._assets = uow, sources, assets
        self._sem = asyncio.Semaphore(concurrency)

    # ------------------------------------------------------------------ writes

    async def upsert(
        self,
        user_id: UUID,
        asset_id: UUID,
        *,
        quantity: float,
        avg_cost_usd: float | None,
        notes: str | None,
        source: str = "manual",
    ) -> None:
        if quantity < 0 or (avg_cost_usd is not None and avg_cost_usd < 0):
            raise ValidationFailed("Quantity and cost must be non-negative")
        async with self._uow() as uow:
            if not await uow.assets.get(asset_id):
                raise NotFoundError("Asset not found")
            await uow.portfolio.upsert(
                user_id, asset_id, quantity=quantity, avg_cost_usd=avg_cost_usd, notes=notes, source=source
            )
            await uow.commit()

    async def remove(self, user_id: UUID, holding_id: UUID) -> None:
        async with self._uow() as uow:
            await uow.portfolio.remove(user_id, holding_id)
            await uow.commit()

    async def import_csv(self, user_id: UUID, text: str) -> dict[str, Any]:
        parsed = parse_holdings_csv(text)
        errors = [{"line": line, "message": msg} for line, msg in parsed.errors]
        imported: list[dict[str, Any]] = []
        resolved: dict[str, Asset | None] = {}
        for row in parsed.rows:
            key = row.coingecko_id or f"sym:{row.symbol}"
            try:
                if key not in resolved:
                    resolved[key] = (
                        await self._assets.track(row.coingecko_id)
                        if row.coingecko_id
                        else await self._assets.resolve_symbol(row.symbol or "")
                    )
            except LodestarError as exc:
                errors.append({"line": row.line, "message": str(exc)})
                continue
            asset = resolved[key]
            if asset is None:
                errors.append({"line": row.line, "message": f"no coin found for symbol '{row.symbol}'"})
                continue
            await self.upsert(
                user_id, asset.id, quantity=row.quantity, avg_cost_usd=row.avg_cost_usd, notes=row.notes, source="csv"
            )
            imported.append({"line": row.line, "asset": to_jsonable(asset), "quantity": row.quantity})
        log.info("csv_imported", rows=len(imported), errors=len(errors))
        return {"imported": imported, "errors": errors}

    async def import_address(self, user_id: UUID, chain: Chain, address: str) -> dict[str, Any]:
        """Read balances of a *public* address and record them as holdings. Never asks for keys."""
        normalized = normalize_address(chain, address)
        balances = await self._s.wallets.balances(chain, normalized)
        source = f"wallet:{chain.value}:{normalized}"
        imported = []
        for b in balances:
            if b.quantity <= 0:
                continue
            asset = await self._assets.track(b.coingecko_id)
            await self.upsert(user_id, asset.id, quantity=b.quantity, avg_cost_usd=None, notes=None, source=source)
            imported.append({"asset": to_jsonable(asset), "quantity": b.quantity})
        return {
            "chain": chain.value,
            "address": normalized,
            "source": source,
            "source_label": source_label(source),
            "imported": imported,
            "demo": self._s.mode == "demo",
        }

    # ------------------------------------------------------------------ valuation

    async def holdings(self, user_id: UUID) -> list[Holding]:
        async with self._uow() as uow:
            return await uow.portfolio.list_holdings(user_id)

    async def valuation(self, user_id: UUID) -> dict[str, Any]:
        holdings = await self.holdings(user_id)
        by_asset: dict[UUID, list[Holding]] = defaultdict(list)
        for h in holdings:
            by_asset[h.asset.id].append(h)
        assets = {h.asset.id: h.asset for h in holdings}
        snaps = await asyncio.gather(
            *(self._snapshot(assets[a].coingecko_id) for a in by_asset), return_exceptions=True
        )

        positions: list[dict[str, Any]] = []
        for (asset_id, rows), snap in zip(by_asset.items(), snaps, strict=True):
            s = snap if isinstance(snap, MarketSnapshot) else None
            qty = sum(h.quantity for h in rows)
            costed = [h for h in rows if h.avg_cost_usd is not None]
            cost = sum(h.quantity * (h.avg_cost_usd or 0.0) for h in costed) if costed else None
            costed_qty = sum(h.quantity for h in costed)
            price = s.price_usd if s else None
            value = price * qty if price is not None else None
            pnl = (price * costed_qty - cost) if price is not None and cost is not None else None
            positions.append(
                {
                    "asset": to_jsonable(assets[asset_id]),
                    "quantity": qty,
                    "avg_cost_usd": (cost / costed_qty) if cost is not None and costed_qty else None,
                    "cost_usd": cost,
                    "price_usd": price,
                    "change_24h_pct": s.change_24h_pct if s else None,
                    "value_usd": value,
                    "pnl_usd": pnl,
                    "pnl_pct": (pnl / cost * 100) if pnl is not None and cost else None,
                    "price_stale": s is None,
                    "holdings": [
                        {
                            "id": str(h.id),
                            "source": h.source,
                            "source_label": source_label(h.source),
                            "quantity": h.quantity,
                            "avg_cost_usd": h.avg_cost_usd,
                            "notes": h.notes,
                        }
                        for h in rows
                    ],
                }
            )
        total = sum(p["value_usd"] or 0.0 for p in positions)
        for p in positions:
            p["weight_pct"] = (p["value_usd"] / total * 100) if p["value_usd"] and total else None
        positions.sort(key=lambda p: -(p["value_usd"] or 0.0))
        total_cost = sum(p["cost_usd"] or 0.0 for p in positions)
        total_pnl = (
            sum(p["pnl_usd"] or 0.0 for p in positions) if any(p["pnl_usd"] is not None for p in positions) else None
        )
        weighted_change = [
            (p["weight_pct"], p["change_24h_pct"])
            for p in positions
            if p["weight_pct"] and p["change_24h_pct"] is not None
        ]
        return {
            "positions": positions,
            "total_value_usd": total,
            "total_cost_usd": total_cost,
            "total_pnl_usd": total_pnl,
            "total_pnl_pct": (total_pnl / total_cost * 100) if total_pnl is not None and total_cost else None,
            "change_24h_pct": sum(w * c for w, c in weighted_change) / 100 if weighted_change else None,
            "stale_prices": sum(p["price_stale"] for p in positions),
        }

    async def _snapshot(self, coingecko_id: str) -> MarketSnapshot:
        async with self._sem:
            return await self._s.market.get_snapshot(coingecko_id)
