"""Pipeline runs: request, execute (worker), human decision, resume (worker), history."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any
from uuid import UUID

import structlog

from lodestar.application.pipeline.approval import apply_decision
from lodestar.application.pipeline.events import EventType, RunEventRecorder, event_to_dict
from lodestar.application.ports import Clock, JobQueue, ReportRecord, RunRecord, UnitOfWork, WorkflowEngine
from lodestar.application.serialization import to_jsonable
from lodestar.domain.errors import ConflictError, LodestarError, NotFoundError
from lodestar.domain.models import Asset, ReportKind, ReportStatus, RunStatus

log = structlog.get_logger(__name__)
STALE_MESSAGE = "Expired: no worker finished this run in time; a new run was started"
UowFactory = Callable[[], UnitOfWork]


def run_json(run: RunRecord, asset: Asset | None = None, report_id: UUID | None = None) -> dict[str, Any]:
    out: dict[str, Any] = to_jsonable(run)
    out["is_terminal"] = run.status.is_terminal
    if asset is not None:
        out["asset"] = to_jsonable(asset)
    out["report_id"] = str(report_id) if report_id else None
    return out


class PipelineService:
    def __init__(
        self,
        uow: UowFactory,
        queue: JobQueue,
        events: RunEventRecorder,
        *,
        data_mode: str,
        llm_mode: str,
        clock: Clock,
        stale_after: timedelta = timedelta(minutes=15),
    ) -> None:
        self._uow, self._queue, self._events = uow, queue, events
        self._data_mode, self._llm_mode = data_mode, llm_mode
        self._engines: dict[str, WorkflowEngine] = {}
        self._clock, self._stale_after = clock, stale_after

    def attach_engine(self, engine: WorkflowEngine, *, graph: str = "analysis") -> None:
        """Worker/CLI processes run the graphs; the API process only queues and decides.

        `graph` is "analysis" (on-demand/daily reports) or "trade" (trade plans)."""
        self._engines[graph] = engine

    # ------------------------------------------------------------------ API side

    async def request(
        self, asset_id: UUID, user_id: UUID | None, *, kind: ReportKind = ReportKind.ON_DEMAND, force: bool = False
    ) -> tuple[RunRecord, bool]:
        """Queue a run. Returns (run, created). An in-flight run for the asset is reused unless forced."""
        async with self._uow() as uow:
            if not await uow.assets.get(asset_id):
                raise NotFoundError("Asset not found")
            active = await uow.runs.active_for_asset(asset_id, kind)
            stale = active is not None and self._clock.now() - active.created_at > self._stale_after
            if active and not force and not stale:
                return active, False
            if active and stale:
                # A lost task (worker crash, broker flush) must not block the asset forever.
                await uow.runs.update(active.id, status=RunStatus.FAILED, error=STALE_MESSAGE)
            run = await uow.runs.create(asset_id, user_id, kind, data_mode=self._data_mode, llm_mode=self._llm_mode)
            await uow.commit()
        if active and stale:
            await self._events.emit(
                active.id, step="run", type=EventType.RUN, status=RunStatus.FAILED.value, message=STALE_MESSAGE
            )
        await self._events.emit(run.id, step="run", type=EventType.RUN, status=RunStatus.QUEUED.value, kind=kind.value)
        await self._queue.enqueue_run(run.id)
        log.info("run_queued", run_id=str(run.id), asset_id=str(asset_id), kind=kind.value)
        return run, True

    async def decide(self, report_id: UUID, *, approved: bool, note: str | None, user_id: UUID | None) -> ReportRecord:
        async with self._uow() as uow:
            report = await uow.reports.get(report_id)
        if report is None:
            raise NotFoundError("Report not found")
        if report.status is not ReportStatus.PENDING_APPROVAL:
            raise ConflictError(f"Report is already {report.status.value.replace('_', ' ')}")
        decision = {"approved": approved, "note": note, "user_id": str(user_id) if user_id else None}
        await apply_decision(self._uow, self._events, report.run_id, report.id, decision)
        await self._queue.enqueue_resume(report.run_id, decision)  # lets the graph thread finish formally
        async with self._uow() as uow:
            updated = await uow.reports.get(report_id)
        assert updated is not None  # noqa: S101 - just written
        return updated

    async def list_runs(self, *, asset_id: UUID | None = None, limit: int = 50) -> list[dict[str, Any]]:
        async with self._uow() as uow:
            runs = await uow.runs.list(asset_id=asset_id, limit=limit)
            assets = {a.id: a for a in await uow.assets.list_all()}
            out = []
            for r in runs:
                report = await uow.reports.get_by_run(r.id)
                out.append(run_json(r, assets.get(r.asset_id), report.id if report else None))
        return out

    async def get(self, run_id: UUID) -> dict[str, Any]:
        async with self._uow() as uow:
            run = await uow.runs.get(run_id)
            if run is None:
                raise NotFoundError("Run not found")
            asset = await uow.assets.get(run.asset_id)
            report = await uow.reports.get_by_run(run_id)
            events = await uow.events.list(run_id)
        out = run_json(run, asset, report.id if report else None)
        out["events"] = [event_to_dict(e) for e in events]
        return out

    async def status(self, run_id: UUID) -> RunStatus:
        async with self._uow() as uow:
            run = await uow.runs.get(run_id)
        if run is None:
            raise NotFoundError("Run not found")
        return run.status

    async def events_after(self, run_id: UUID, after_seq: int) -> list[dict[str, Any]]:
        async with self._uow() as uow:
            return [event_to_dict(e) for e in await uow.events.list(run_id, after_seq=after_seq)]

    # ------------------------------------------------------------------ worker side

    def _require_engine(self, kind: ReportKind) -> WorkflowEngine:
        graph = "trade" if kind is ReportKind.TRADE_PLAN else "analysis"
        engine = self._engines.get(graph)
        if engine is None:
            raise RuntimeError(f"This process has no {graph} workflow engine (run pipelines in the worker)")
        return engine

    async def execute(self, run_id: UUID) -> None:
        async with self._uow() as uow:
            run = await uow.runs.get(run_id)
            if run is None:
                raise NotFoundError("Run not found")
            if run.status is not RunStatus.QUEUED:
                log.info("run_skipped", run_id=str(run_id), status=run.status.value)  # duplicate delivery
                return
            asset = await uow.assets.get(run.asset_id)
            if asset is None:
                raise NotFoundError("Asset not found")
            prefs = await uow.settings.get(run.requested_by) if run.requested_by else {}
        engine = self._require_engine(run.kind)
        state = {
            "run_id": str(run_id),
            "user_id": str(run.requested_by) if run.requested_by else None,
            "kind": run.kind.value,
            "asset": to_jsonable(asset),
            "preferences": prefs,
            "evidence": [],
            "analysts": {},
        }
        try:
            await engine.start(str(run_id), state)
        except LodestarError as exc:
            await self._fail(run_id, str(exc))
        except Exception:
            log.exception("run_crashed", run_id=str(run_id))
            await self._fail(run_id, "Internal error while running the pipeline")
            raise

    async def resume(self, run_id: UUID, decision: dict[str, Any]) -> None:
        async with self._uow() as uow:
            run = await uow.runs.get(run_id)
        if run is None:
            return
        try:
            await self._require_engine(run.kind).resume(str(run_id), decision)
        except Exception:
            # The decision is already recorded (apply_decision); a failed resume only leaves the graph thread open.
            log.exception("run_resume_failed", run_id=str(run_id))

    async def _fail(self, run_id: UUID, message: str) -> None:
        async with self._uow() as uow:
            await uow.runs.update(run_id, status=RunStatus.FAILED, error=message)
            await uow.commit()
        await self._events.emit(run_id, step="run", type=EventType.RUN, status=RunStatus.FAILED.value, message=message)
        self._events.forget(run_id)

    async def queue_daily(self) -> int:
        """Scheduled daily: one run per watchlisted asset per user (deduplicated per asset)."""
        async with self._uow() as uow:
            entries = await uow.watchlist.all_entries()
        queued = 0
        for user_id, asset_id in entries:
            _, created = await self.request(asset_id, user_id, kind=ReportKind.DAILY)
            queued += created
        return queued
