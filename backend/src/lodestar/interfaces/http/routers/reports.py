"""Reports: list, read, approve/reject (human-in-the-loop), export."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from lodestar.domain.models import ReportKind, ReportStatus
from lodestar.interfaces.http.deps import ContainerDep, OwnerDep, PrincipalDep, rate_limit
from lodestar.interfaces.http.schemas import DecisionRequest

router = APIRouter(tags=["reports"], dependencies=[Depends(rate_limit("api"))])


@router.get("/reports")
async def list_reports(
    _: PrincipalDep,
    c: ContainerDep,
    kind: ReportKind | None = None,
    status: ReportStatus | None = None,
    asset_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[dict[str, Any]]:
    return await c.reports.list_reports(kind=kind, status=status, asset_id=asset_id, limit=limit)


@router.get("/reports/{report_id}")
async def get_report(report_id: UUID, _: PrincipalDep, c: ContainerDep) -> dict[str, Any]:
    return await c.reports.get(report_id)


async def _decide(c: ContainerDep, report_id: UUID, user_id: UUID, approved: bool, note: str | None) -> dict[str, Any]:
    await c.pipeline.decide(report_id, approved=approved, note=note, user_id=user_id)
    return await c.reports.get(report_id)


@router.post("/reports/{report_id}/approve")
async def approve_report(
    report_id: UUID, body: DecisionRequest, principal: OwnerDep, c: ContainerDep
) -> dict[str, Any]:
    return await _decide(c, report_id, principal.user_id, True, body.note)


@router.post("/reports/{report_id}/reject")
async def reject_report(report_id: UUID, body: DecisionRequest, principal: OwnerDep, c: ContainerDep) -> dict[str, Any]:
    return await _decide(c, report_id, principal.user_id, False, body.note)


def _attachment(filename: str) -> dict[str, str]:
    return {"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"}


@router.get("/reports/{report_id}/export.md")
async def export_markdown(report_id: UUID, _: PrincipalDep, c: ContainerDep) -> Response:
    filename, text = await c.reports.markdown(report_id)
    return Response(text, media_type="text/markdown; charset=utf-8", headers=_attachment(filename))


@router.get("/reports/{report_id}/export.pdf")
async def export_pdf(report_id: UUID, _: PrincipalDep, c: ContainerDep) -> Response:
    filename, data = await c.reports.pdf(report_id)
    return Response(data, media_type="application/pdf", headers=_attachment(filename))
