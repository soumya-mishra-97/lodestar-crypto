"""Assets: search, add (track + watch + start a run), detail chart, watchlist."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from lodestar.application.serialization import to_jsonable
from lodestar.interfaces.http.deps import ContainerDep, OwnerDep, PrincipalDep, rate_limit
from lodestar.interfaces.http.schemas import AddAssetRequest, AssetCandidateResponse

router = APIRouter(tags=["assets"], dependencies=[Depends(rate_limit("api"))])


@router.get("/assets/search", response_model=list[AssetCandidateResponse])
async def search_assets(
    _: PrincipalDep, c: ContainerDep, q: Annotated[str, Query(min_length=1, max_length=64)]
) -> list[AssetCandidateResponse]:
    return [AssetCandidateResponse(**asdict(x)) for x in await c.assets.search(q)]


@router.post(
    "/assets",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("analysis"))],
)
async def add_asset(body: AddAssetRequest, principal: OwnerDep, c: ContainerDep) -> dict[str, Any]:
    """Track a coin, add it to the watchlist and start a visible pipeline run."""
    return await c.onboarding.add(body.coingecko_id, principal.user_id, watch=body.watch, analyze=body.analyze)


@router.get("/assets")
async def list_assets(_: PrincipalDep, c: ContainerDep) -> list[dict[str, Any]]:
    return [to_jsonable(a) for a in await c.assets.list_all()]


@router.get("/assets/{asset_id}")
async def get_asset(asset_id: UUID, _: PrincipalDep, c: ContainerDep) -> dict[str, Any]:
    out: dict[str, Any] = to_jsonable(await c.assets.get(asset_id))
    return out


@router.get("/assets/{asset_id}/chart")
async def asset_chart(
    asset_id: UUID, _: PrincipalDep, c: ContainerDep, days: Annotated[int, Query(ge=14, le=365)] = 120
) -> dict[str, Any]:
    return await c.assets.chart(asset_id, days)


@router.get("/assets/{asset_id}/report")
async def latest_asset_report(asset_id: UUID, _: PrincipalDep, c: ContainerDep) -> dict[str, Any]:
    return await c.reports.latest_for_asset(asset_id)


@router.post(
    "/assets/{asset_id}/runs",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(rate_limit("analysis"))],
)
async def start_run(asset_id: UUID, principal: OwnerDep, c: ContainerDep, force: bool = False) -> dict[str, Any]:
    run, created = await c.pipeline.request(asset_id, principal.user_id, force=force)
    return {"run": to_jsonable(run), "created": created}


@router.get("/watchlist")
async def get_watchlist(principal: PrincipalDep, c: ContainerDep) -> list[dict[str, Any]]:
    return [to_jsonable(a) for a in await c.watchlist.list_assets(principal.user_id)]


@router.put("/watchlist/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def watch(asset_id: UUID, principal: PrincipalDep, c: ContainerDep) -> None:
    await c.watchlist.add(principal.user_id, asset_id)


@router.delete("/watchlist/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unwatch(asset_id: UUID, principal: PrincipalDep, c: ContainerDep) -> None:
    await c.watchlist.remove(principal.user_id, asset_id)
