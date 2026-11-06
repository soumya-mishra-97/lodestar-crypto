"""Recording a human approval decision (shared by the API and the graph's approval step)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from lodestar.application.pipeline.events import EventType, RunEventRecorder, StepStatus
from lodestar.application.ports import UnitOfWork
from lodestar.domain.errors import NotFoundError
from lodestar.domain.models import ReportStatus, RunStatus

UowFactory = Callable[[], UnitOfWork]


async def apply_decision(
    uow_factory: UowFactory,
    events: RunEventRecorder,
    run_id: UUID,
    report_id: UUID,
    decision: dict[str, Any],
) -> None:
    """Record a human decision on a report. Idempotent: safe from the API and from the graph resume."""
    approved = bool(decision.get("approved"))
    status = RunStatus.APPROVED if approved else RunStatus.REJECTED
    async with uow_factory() as uow:
        report = await uow.reports.get(report_id)
        run = await uow.runs.get(run_id)
        if report is None or run is None:
            raise NotFoundError("Report not found")
        if run.status is status:
            return  # already applied
        if report.status is ReportStatus.PENDING_APPROVAL:
            user = decision.get("user_id")
            await uow.reports.decide(
                report_id,
                ReportStatus.APPROVED if approved else ReportStatus.REJECTED,
                user_id=UUID(str(user)) if user else None,
                note=decision.get("note"),
            )
        await uow.runs.update(run_id, status=status, current_step="done")
        await uow.commit()
    await events.emit(
        run_id,
        step="human_approval",
        type=EventType.STEP,
        status=StepStatus.COMPLETED,
        outputs={"decision": status.value, "note": decision.get("note")},
    )
    await events.emit(run_id, step="run", type=EventType.RUN, status=status.value, report_id=str(report_id))
    events.forget(run_id)
