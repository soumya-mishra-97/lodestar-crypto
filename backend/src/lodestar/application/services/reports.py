"""Reports: listing, reading and exporting (Markdown, PDF)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from lodestar.application.exports import export_filename, render_markdown
from lodestar.application.ports import PdfRenderer, ReportRecord, UnitOfWork
from lodestar.application.serialization import to_jsonable
from lodestar.domain.errors import NotFoundError
from lodestar.domain.models import Asset, ReportKind, ReportStatus

UowFactory = Callable[[], UnitOfWork]


def report_json(r: ReportRecord, asset: Asset | None, *, with_content: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": str(r.id),
        "run_id": str(r.run_id),
        "asset": to_jsonable(asset) if asset else None,
        "kind": r.kind.value,
        "status": r.status.value,
        **to_jsonable(r.summary),
        "created_at": r.created_at.isoformat(),
        "decided_at": r.decided_at.isoformat() if r.decided_at else None,
        "decision_note": r.decision_note,
    }
    if with_content:
        out["content"] = r.content
    return out


class ReportService:
    def __init__(self, uow: UowFactory, pdf: PdfRenderer) -> None:
        self._uow, self._pdf = uow, pdf

    async def list_reports(
        self,
        *,
        kind: ReportKind | None = None,
        status: ReportStatus | None = None,
        asset_id: UUID | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        async with self._uow() as uow:
            rows = await uow.reports.list(kind=kind, status=status, asset_id=asset_id, limit=limit)
            assets = {a.id: a for a in await uow.assets.list_all()}
        return [report_json(r, assets.get(r.asset_id)) for r in rows]

    async def get(self, report_id: UUID) -> dict[str, Any]:
        async with self._uow() as uow:
            r = await uow.reports.get(report_id)
            if r is None:
                raise NotFoundError("Report not found")
            asset = await uow.assets.get(r.asset_id)
        return report_json(r, asset, with_content=True)

    async def latest_for_asset(self, asset_id: UUID) -> dict[str, Any]:
        async with self._uow() as uow:
            found = (await uow.reports.latest_for_assets([asset_id])).get(asset_id)
            asset = await uow.assets.get(asset_id)
        if found is None:
            raise NotFoundError("No report for this asset yet")
        return report_json(found, asset, with_content=True)

    async def markdown(self, report_id: UUID) -> tuple[str, str]:
        report = await self.get(report_id)
        return export_filename(report, "md"), render_markdown(report)

    async def pdf(self, report_id: UUID) -> tuple[str, bytes]:
        report = await self.get(report_id)
        return export_filename(report, "pdf"), self._pdf.render(report)
