"""Trader skills: scanner, trade plans, backtests and paper trading. Paper only: nothing here places orders."""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import Field

from lodestar.application.serialization import to_jsonable
from lodestar.application.services.runs import run_json
from lodestar.application.trading.common import TradingPrefs, load_bars
from lodestar.application.trading.services import BacktestService, PaperService, ScanService
from lodestar.domain.models import ReportKind
from lodestar.domain.trading.setups import SetupKind, current_levels
from lodestar.infrastructure.container import Container
from lodestar.interfaces.http.deps import ContainerDep, OwnerDep, PrincipalDep, rate_limit
from lodestar.interfaces.http.schemas import CoinGeckoId, StrictModel

router = APIRouter(tags=["trading"], dependencies=[Depends(rate_limit("api"))])


class ScanRequest(StrictModel):
    universe: Literal["watchlist", "top"] = "top"
    top_n: int | None = Field(default=20, ge=5, le=100)


class TradePlanRequest(StrictModel):
    coingecko_id: CoinGeckoId
    force: bool = False


class BacktestRequest(StrictModel):
    coingecko_id: CoinGeckoId
    setup: SetupKind | None = None  # default: the setup the timing agent would track today


class PaperOpenRequest(StrictModel):
    report_id: UUID


def _scans(c: Container) -> ScanService:
    assert c.scans is not None  # noqa: S101 - wired by the container
    return c.scans


def _backtests(c: Container) -> BacktestService:
    assert c.backtests is not None  # noqa: S101
    return c.backtests


def _paper(c: Container) -> PaperService:
    assert c.paper is not None  # noqa: S101
    return c.paper


async def _prefs(c: Container, user_id: UUID) -> TradingPrefs:
    return TradingPrefs.from_prefs(await c.preferences.preferences(user_id))


# ---------------------------------------------------------------- scanner


@router.post("/scans", status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(rate_limit("analysis"))])
async def start_scan(body: ScanRequest, principal: OwnerDep, c: ContainerDep) -> dict[str, Any]:
    return await _scans(c).request(principal.user_id, body.universe, body.top_n)


@router.get("/scans")
async def list_scans(principal: PrincipalDep, c: ContainerDep) -> list[dict[str, Any]]:
    return await _scans(c).list(principal.user_id)


@router.get("/scans/latest")
async def latest_scan(principal: PrincipalDep, c: ContainerDep) -> dict[str, Any] | None:
    return await _scans(c).latest(principal.user_id)


@router.get("/scans/{scan_id}")
async def get_scan(scan_id: UUID, _: PrincipalDep, c: ContainerDep) -> dict[str, Any]:
    return await _scans(c).get(scan_id)


# ---------------------------------------------------------------- trade plans


@router.post("/trade-plans", status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(rate_limit("analysis"))])
async def start_trade_plan(body: TradePlanRequest, principal: OwnerDep, c: ContainerDep) -> dict[str, Any]:
    """Track the coin (if needed) and start the per-coin trader-skills pipeline."""
    asset = await c.assets.track(body.coingecko_id)
    run, created = await c.pipeline.request(asset.id, principal.user_id, kind=ReportKind.TRADE_PLAN, force=body.force)
    return {"asset": to_jsonable(asset), "run": run_json(run, asset), "created": created}


# ---------------------------------------------------------------- backtests


@router.post("/backtests", dependencies=[Depends(rate_limit("analysis"))])
async def run_backtest(body: BacktestRequest, principal: OwnerDep, c: ContainerDep) -> dict[str, Any]:
    asset = await c.assets.track(body.coingecko_id)
    kind = body.setup or current_levels(await load_bars(c.sources, asset)).kind
    return await _backtests(c).run(principal.user_id, asset, kind, await _prefs(c, principal.user_id))


@router.get("/backtests")
async def list_backtests(
    principal: PrincipalDep, c: ContainerDep, asset_id: UUID | None = None
) -> list[dict[str, Any]]:
    return await _backtests(c).list(principal.user_id, asset_id)


@router.get("/backtests/{backtest_id}")
async def get_backtest(backtest_id: UUID, _: PrincipalDep, c: ContainerDep) -> dict[str, Any]:
    return await _backtests(c).get(backtest_id)


# ---------------------------------------------------------------- paper trading


@router.get("/paper")
async def paper_account(principal: PrincipalDep, c: ContainerDep) -> dict[str, Any]:
    return await _paper(c).performance(principal.user_id)


@router.post("/paper/positions", status_code=status.HTTP_201_CREATED)
async def paper_open(body: PaperOpenRequest, principal: OwnerDep, c: ContainerDep) -> dict[str, Any]:
    """Paper-trade an approved plan: a simulated position that waits for its trigger. No order is placed."""
    return await _paper(c).open_from_plan(principal.user_id, body.report_id)


@router.post("/paper/positions/{position_id}/cancel", status_code=status.HTTP_204_NO_CONTENT)
async def paper_cancel(position_id: UUID, principal: OwnerDep, c: ContainerDep) -> None:
    await _paper(c).cancel(principal.user_id, position_id)


@router.post("/paper/tick")
async def paper_tick(principal: OwnerDep, c: ContainerDep) -> dict[str, Any]:
    await _paper(c).tick(principal.user_id)
    return await _paper(c).performance(principal.user_id)


@router.post("/paper/reset")
async def paper_reset(principal: OwnerDep, c: ContainerDep) -> dict[str, Any]:
    await _paper(c).reset(principal.user_id)
    return await _paper(c).performance(principal.user_id)


@router.post("/paper/demo-replay")
async def paper_demo_replay(
    principal: OwnerDep, c: ContainerDep, days: Annotated[int, Query(ge=30, le=300)] = 75
) -> dict[str, Any]:
    """Demo mode only: restart the paper account in the past on synthetic data (positions labelled demo_replay)."""
    async with c.uow() as uow:
        watched = await uow.watchlist.list_assets(principal.user_id)
    await _paper(c).seed_demo_replay(principal.user_id, watched[:3], days_back=days)
    return await _paper(c).performance(principal.user_id)
