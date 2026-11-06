"""User-scoped screens: session info, overview, portfolio, settings.

Every query is filtered by the authenticated principal's id, so one user can
never read or modify another user's data (object-level authorization).
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, status

from lodestar.domain.errors import AuthenticationError
from lodestar.interfaces.http.deps import ContainerDep, OwnerDep, PrincipalDep, local_owner, rate_limit
from lodestar.interfaces.http.schemas import (
    AddressImportRequest,
    CsvImportRequest,
    HoldingUpsertRequest,
    PreferencesRequest,
)

router = APIRouter(tags=["me"], dependencies=[Depends(rate_limit("api"))])


@router.get("/session")
async def session(c: ContainerDep, authorization: Annotated[str | None, Header()] = None) -> dict[str, Any]:
    """Public: what the UI needs before login (auth mode, demo mode)."""
    s = c.settings
    authenticated = s.auth_mode == "local"
    if s.auth_mode == "local":
        await local_owner(c)
    elif authorization and authorization.lower().startswith("bearer "):
        try:
            c.tokens.verify_access(authorization[7:])
            authenticated = True
        except AuthenticationError:
            authenticated = False
    return {
        "auth_mode": s.auth_mode,
        "authenticated": authenticated,
        "data_mode": c.sources.mode,
        "demo": c.sources.mode == "demo",
        "llm_mode": "deterministic" if not s.llm_configured else s.llm_model,
    }


@router.get("/overview")
async def overview(principal: PrincipalDep, c: ContainerDep) -> dict[str, Any]:
    return await c.overview.overview(principal.user_id)


@router.get("/portfolio")
async def get_portfolio(principal: PrincipalDep, c: ContainerDep) -> dict[str, Any]:
    return await c.portfolio.valuation(principal.user_id)


@router.put("/portfolio/holdings", status_code=status.HTTP_204_NO_CONTENT)
async def upsert_holding(body: HoldingUpsertRequest, principal: OwnerDep, c: ContainerDep) -> None:
    await c.portfolio.upsert(
        principal.user_id, UUID(body.asset_id), quantity=body.quantity, avg_cost_usd=body.avg_cost_usd, notes=body.notes
    )


@router.delete("/portfolio/holdings/{holding_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_holding(holding_id: UUID, principal: OwnerDep, c: ContainerDep) -> None:
    await c.portfolio.remove(principal.user_id, holding_id)


@router.post("/portfolio/import/csv")
async def import_csv(body: CsvImportRequest, principal: OwnerDep, c: ContainerDep) -> dict[str, Any]:
    return await c.portfolio.import_csv(principal.user_id, body.content)


@router.post("/portfolio/import/address")
async def import_address(body: AddressImportRequest, principal: OwnerDep, c: ContainerDep) -> dict[str, Any]:
    return await c.portfolio.import_address(principal.user_id, body.chain, body.address)


@router.get("/settings")
async def get_settings(principal: PrincipalDep, c: ContainerDep) -> dict[str, Any]:
    return await c.preferences.view(principal.user_id)


@router.put("/settings")
async def update_settings(body: PreferencesRequest, principal: OwnerDep, c: ContainerDep) -> dict[str, Any]:
    await c.preferences.update(principal.user_id, body.model_dump(exclude_none=True))
    return await c.preferences.view(principal.user_id)
