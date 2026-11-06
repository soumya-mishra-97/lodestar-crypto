"""Pipeline steps as graph nodes.

    data ─┬─ technical ──┐
          ├─ fundamental ┤
          ├─ sentiment ──┼─ portfolio ─ report_writer ─ verifier ─┬─ human_approval
          └─ risk ───────┘                    ▲                   ├─ (repair) ─┘ max 2
                                              └───────────────────┴─ fail_closed

Every node is instrumented: it emits `running` and then `completed` (or
`failed`) events with its inputs, outputs and the evidence ids it produced.
Nodes depend only on ports; the LangGraph wiring lives in infrastructure.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import structlog

from lodestar.application import codec
from lodestar.application.pipeline.analysts.base import Analyst, AnalystContext, AnalystResult
from lodestar.application.pipeline.analysts.fundamental import FundamentalAnalyst
from lodestar.application.pipeline.analysts.risk import RiskAnalyst
from lodestar.application.pipeline.analysts.sentiment import SentimentAnalyst
from lodestar.application.pipeline.analysts.technical import TechnicalAnalyst
from lodestar.application.pipeline.approval import apply_decision
from lodestar.application.pipeline.data_step import (
    CollectionSettings,
    DataCollector,
    collection_summary,
    reconcile,
    register_data_evidence,
)
from lodestar.application.pipeline.events import EventType, RunEventRecorder, StepStatus
from lodestar.application.pipeline.portfolio_step import position_context, synthesize_assessments
from lodestar.application.pipeline.react import PolicyFactory, StepRecord
from lodestar.application.pipeline.state import PipelineState
from lodestar.application.pipeline.writer import ReportWriter, WriterInput
from lodestar.application.ports import Clock, DataSources, ReportSummary, UnitOfWork
from lodestar.domain.evidence import EvidenceBundle, EvidenceRegistry
from lodestar.domain.models import Horizon, ReportKind, RunStatus
from lodestar.domain.reconciliation import Reconciliation
from lodestar.domain.report import ReportDraft
from lodestar.domain.scoring import HorizonAssessment
from lodestar.domain.verification import verify_report

log = structlog.get_logger(__name__)

PIPELINE_VERSION = "2026.11.2"
ANALYSTS: tuple[Analyst, ...] = (TechnicalAnalyst(), FundamentalAnalyst(), SentimentAnalyst(), RiskAnalyst())
PortfolioReader = Callable[[UUID], Awaitable[dict[str, Any] | None]]
ApprovalGate = Callable[[dict[str, Any]], Any]  # pauses the graph; returns the human decision on resume


@dataclass(frozen=True, slots=True)
class PipelineConfig:
    max_agent_steps: int = 6
    max_repairs: int = 2
    mismatch_tolerance_pct: float = 1.5
    step_delay_seconds: float = 0.0  # demo mode: pace steps so the live timeline is watchable
    collection: CollectionSettings = field(default_factory=CollectionSettings)


@dataclass(frozen=True, slots=True)
class PipelineDeps:
    sources: DataSources
    uow: Callable[[], UnitOfWork]
    events: RunEventRecorder
    clock: Clock
    policies: PolicyFactory
    writer: ReportWriter
    portfolio: PortfolioReader
    approval_gate: ApprovalGate
    config: PipelineConfig


def route_after_verification(state: Mapping[str, Any], *, max_repairs: int) -> str:
    """Pass -> human approval. Fail -> repair (at most `max_repairs` times) -> otherwise fail closed."""
    verification = state.get("verification") or {}
    if verification.get("passed"):
        return "human_approval"
    if state.get("repair_count", 0) < max_repairs:
        return "report_writer"
    return "fail_closed"


class PipelineNodes:
    def __init__(self, deps: PipelineDeps) -> None:
        self._d = deps
        self._collector = DataCollector(deps.sources, deps.config.collection)

    # ------------------------------------------------------------------ instrumentation

    async def _step(
        self,
        state: PipelineState,
        step: str,
        work: Callable[[], Awaitable[tuple[dict[str, Any], dict[str, Any], list[str]]]],
        *,
        inputs: dict[str, Any] | None = None,
        attempt: int | None = None,
    ) -> dict[str, Any]:
        run_id = UUID(state["run_id"])
        async with self._d.uow() as uow:
            await uow.runs.update(run_id, current_step=step)
            await uow.commit()
        await self._d.events.emit(
            run_id, step=step, type=EventType.STEP, status=StepStatus.RUNNING, inputs=inputs, attempt=attempt
        )
        if self._d.config.step_delay_seconds:
            await asyncio.sleep(self._d.config.step_delay_seconds)
        started = time.perf_counter()
        try:
            update, outputs, evidence_ids = await work()
        except Exception as exc:
            await self._d.events.emit(
                run_id,
                step=step,
                type=EventType.STEP,
                status=StepStatus.FAILED,
                attempt=attempt,
                message=f"{type(exc).__name__}: {exc}"[:300],
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
            )
            raise
        await self._d.events.emit(
            run_id,
            step=step,
            type=EventType.STEP,
            status=StepStatus.COMPLETED,
            attempt=attempt,
            outputs=outputs,
            evidence_ids=evidence_ids,
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
        )
        return update

    # ------------------------------------------------------------------ data

    async def data(self, state: PipelineState) -> dict[str, Any]:
        run_id = UUID(state["run_id"])
        asset = codec.asset(state["asset"])
        prefs = state.get("preferences") or {}
        async with self._d.uow() as uow:
            await uow.runs.update(run_id, status=RunStatus.RUNNING)
            await uow.commit()
        await self._d.events.emit(run_id, step="run", type=EventType.RUN, status=RunStatus.RUNNING.value)

        async def work() -> tuple[dict[str, Any], dict[str, Any], list[str]]:
            bundle = await self._collector.collect(
                asset, polymarket_enabled=bool(prefs.get("polymarket_enabled", True))
            )
            tolerance = float(prefs.get("mismatch_tolerance_pct", self._d.config.mismatch_tolerance_pct))
            primary = "coingecko" if self._d.sources.mode == "live" else "demo"
            rec = reconcile(bundle, tolerance_pct=tolerance, primary_source=primary)
            evidence = register_data_evidence(bundle, rec, primary_source=primary, now=self._d.clock.now())
            if rec.status == "mismatch":
                await self._d.events.emit(
                    run_id,
                    step="data",
                    type=EventType.NOTE,
                    message=f"Price mismatch: {', '.join(rec.mismatched_sources)} deviate beyond {tolerance:g}%",
                    level="warning",
                )
            update = {
                "bundle": codec.encode_bundle(bundle),
                "reconciliation": rec.to_dict(),
                "evidence": [e.to_dict() for e in evidence],
            }
            return update, collection_summary(bundle, rec), [e.id for e in evidence]

        return await self._step(
            state,
            "data",
            work,
            inputs={"asset": asset.symbol, "coingecko_id": asset.coingecko_id, "mode": self._d.sources.mode},
        )

    # ------------------------------------------------------------------ analysts (parallel)

    def analyst_node(self, analyst: Analyst) -> Callable[[PipelineState], Awaitable[dict[str, Any]]]:
        async def node(state: PipelineState) -> dict[str, Any]:
            return await self._run_analyst(analyst, state)

        node.__name__ = analyst.name
        return node

    async def _run_analyst(self, analyst: Analyst, state: PipelineState) -> dict[str, Any]:
        run_id = UUID(state["run_id"])
        data = EvidenceBundle.from_dicts(state["evidence"])
        ctx = AnalystContext(
            asset=codec.asset(state["asset"]),
            bundle=codec.decode_bundle(state["bundle"]),
            data=data,
            registry=EvidenceRegistry(analyst.namespace, as_of=self._d.clock.now()),
            reconciliation=Reconciliation.from_dict(state["reconciliation"] or {}),
        )

        async def on_step(record: StepRecord) -> None:
            for call, res in record.calls:
                await self._d.events.emit(
                    run_id,
                    step=analyst.name,
                    type=EventType.TOOL,
                    status="error" if res.is_error else "ok",
                    react_step=record.index,
                    max_steps=self._d.config.max_agent_steps,
                    tool=call.name,
                    args=dict(call.args),
                    observation=res.content,
                    evidence_ids=list(res.evidence_ids),
                )

        async def work() -> tuple[dict[str, Any], dict[str, Any], list[str]]:
            result = await analyst.run(
                ctx, self._d.policies(analyst.name), max_steps=self._d.config.max_agent_steps, on_step=on_step
            )
            if result.dropped_claims:
                await self._d.events.emit(
                    run_id,
                    step=analyst.name,
                    type=EventType.NOTE,
                    message=f"{result.dropped_claims} model claim(s) failed pre-verification and were dropped",
                    level="warning",
                )
            outputs = {
                "signals": [
                    {"name": s.name, "horizon": s.horizon.value, "contribution": s.contribution} for s in result.signals
                ],
                "risks": [{"horizon": r.horizon.value, "level": r.level.value, "score": r.score} for r in result.risks],
                "claims": len(result.claims),
                "claims_source": result.claims_source,
                "react_steps": result.steps,
                "stop_reason": result.stop_reason,
                "summary": result.summary,
            }
            update = {
                "analysts": {analyst.name: result.to_dict()},
                "evidence": [e.to_dict() for e in result.evidence],
            }
            return update, outputs, [e.id for e in result.evidence]

        return await self._step(
            state,
            analyst.name,
            work,
            inputs={
                "mandate": analyst.mandate,
                "data_evidence": len(data.items),
                "max_steps": self._d.config.max_agent_steps,
            },
        )

    # ------------------------------------------------------------------ portfolio

    async def portfolio(self, state: PipelineState) -> dict[str, Any]:
        asset = codec.asset(state["asset"])

        async def work() -> tuple[dict[str, Any], dict[str, Any], list[str]]:
            evidence = EvidenceBundle.from_dicts(state["evidence"])
            analysts = self._analysts(state, evidence)
            asm = EvidenceRegistry("ASM", as_of=self._d.clock.now())
            assessments = synthesize_assessments(analysts, codec.decode_bundle(state["bundle"]), asm)
            pf = EvidenceRegistry("PF", as_of=self._d.clock.now())
            valuation = None
            if user_id := state.get("user_id"):
                try:
                    valuation = await self._d.portfolio(UUID(user_id))
                except Exception as exc:  # noqa: BLE001 - portfolio context is optional
                    log.warning("portfolio_context_unavailable", error=repr(exc))
            context = position_context(asset, valuation, pf)
            items = [*asm.items, *pf.items]
            outputs = {
                h.value: {
                    "score": a.score,
                    "stance": a.stance.value,
                    "risk_level": a.risk.level.value,
                    "confidence": a.confidence,
                }
                for h, a in assessments.items()
            } | {"position": context}
            update = {
                "assessments": {h.value: a.to_dict() for h, a in assessments.items()},
                "portfolio": context,
                "evidence": [e.to_dict() for e in items],
                "attempt": 0,
                "repair_count": 0,
                "feedback": [],
            }
            return update, outputs, [e.id for e in items]

        return await self._step(
            state, "portfolio", work, inputs={"analysts": sorted((state.get("analysts") or {}).keys())}
        )

    # ------------------------------------------------------------------ writer / verifier

    async def report_writer(self, state: PipelineState) -> dict[str, Any]:
        attempt = state.get("attempt", 0) + 1
        feedback = state.get("feedback") or []

        async def work() -> tuple[dict[str, Any], dict[str, Any], list[str]]:
            inp = self._writer_input(state)
            draft = await self._d.writer.write(inp, feedback)
            cited = sorted({i for c in draft.all_claims() for i in c.evidence_ids})
            outputs = {"writer": draft.writer, "claims": len(draft.all_claims()), "headline": draft.headline.text}
            update: dict[str, Any] = {"draft": draft.to_dict(), "attempt": attempt}
            if attempt > 1:  # this attempt is a repair; the router counts repairs actually run
                update["repair_count"] = state.get("repair_count", 0) + 1
            return update, outputs, cited

        return await self._step(
            state,
            "report_writer",
            work,
            attempt=attempt,
            inputs={
                "evidence_items": len(state["evidence"]),
                "repair_feedback": feedback or None,
                "writer": self._d.writer.name,
            },
        )

    async def verifier(self, state: PipelineState) -> dict[str, Any]:
        run_id = UUID(state["run_id"])
        attempt = state.get("attempt", 1)

        async def work() -> tuple[dict[str, Any], dict[str, Any], list[str]]:
            draft = ReportDraft.from_dict(state["draft"] or {})
            evidence = EvidenceBundle.from_dicts(state["evidence"])
            assessments = self._assessments(state)
            result = verify_report(draft, evidence, assessments)
            update: dict[str, Any] = {"verification": result.to_dict()}
            outputs: dict[str, Any] = {
                "passed": result.passed,
                "checked_claims": result.checked_claims,
                "findings": result.feedback(),
            }
            if result.passed:
                report_id = await self._publish_for_approval(state, draft, result.to_dict())
                update["report_id"] = str(report_id)
                outputs["report_id"] = str(report_id)
            else:
                repairs = state.get("repair_count", 0)
                update["feedback"] = result.feedback()
                if repairs < self._d.config.max_repairs:
                    await self._d.events.emit(
                        run_id,
                        step="verifier",
                        type=EventType.NOTE,
                        message=(
                            f"Verification failed with {len(result.findings)} finding(s); "
                            f"repair loop {repairs + 1} of {self._d.config.max_repairs}"
                        ),
                        level="warning",
                    )
            return update, outputs, []

        update = await self._step(state, "verifier", work, attempt=attempt, inputs={"attempt": attempt})
        if update.get("report_id"):
            await self._d.events.emit(
                run_id,
                step="human_approval",
                type=EventType.STEP,
                status=StepStatus.WAITING,
                inputs={"report_id": update["report_id"]},
                message="Verified report is waiting for your approval",
            )
            await self._d.events.emit(
                run_id,
                step="run",
                type=EventType.RUN,
                status=RunStatus.AWAITING_APPROVAL.value,
                report_id=update["report_id"],
            )
            self._d.events.forget(run_id)
        return update

    async def _publish_for_approval(
        self, state: PipelineState, draft: ReportDraft, verification: dict[str, Any]
    ) -> UUID:
        run_id = UUID(state["run_id"])
        asset = codec.asset(state["asset"])
        assessments = self._assessments(state)
        st, lt = assessments[Horizon.SHORT_TERM], assessments[Horizon.LONG_TERM]
        bundle = codec.decode_bundle(state["bundle"])
        content = {
            "pipeline_version": PIPELINE_VERSION,
            "generated_at": self._d.clock.now().isoformat(),
            "data_mode": self._d.sources.mode,
            "asset": state["asset"],
            "snapshot": state["bundle"]["snapshot"],
            "assessments": state["assessments"],
            "draft": draft.to_dict(),
            "portfolio": state.get("portfolio"),
            "reconciliation": state.get("reconciliation"),
            "analysts": {
                k: {
                    kk: v[kk]
                    for kk in ("claims_source", "steps", "tool_calls", "stop_reason", "summary", "dropped_claims")
                }
                for k, v in (state.get("analysts") or {}).items()
            },
            "evidence": state["evidence"],
            "data_gaps": bundle.data_gaps,
            "verification": {
                **verification,
                "attempts": state.get("attempt", 1),
                "repairs": state.get("repair_count", 0),
            },
            "disclaimer": draft.disclaimer,
        }
        summary = ReportSummary(
            headline=draft.headline.text,
            short_term_stance=st.stance.value,
            long_term_stance=lt.stance.value,
            short_term_risk=st.risk.level.value,
            long_term_risk=lt.risk.level.value,
        )
        async with self._d.uow() as uow:
            report_id = await uow.reports.create(
                run_id, asset.id, ReportKind(state.get("kind", "on_demand")), summary, content
            )
            await uow.runs.update(run_id, status=RunStatus.AWAITING_APPROVAL, current_step="human_approval")
            await uow.commit()
        return report_id

    # ------------------------------------------------------------------ terminal steps

    async def human_approval(self, state: PipelineState) -> dict[str, Any]:
        """Pause for a human decision. Must stay idempotent: the engine re-runs this node on resume."""
        decision: dict[str, Any] = self._d.approval_gate(
            {"report_id": state.get("report_id"), "question": "Approve this report?"}
        )
        await apply_decision(
            self._d.uow, self._d.events, UUID(state["run_id"]), UUID(str(state["report_id"])), decision
        )
        return {"decision": decision}

    async def fail_closed(self, state: PipelineState) -> dict[str, Any]:
        run_id = UUID(state["run_id"])
        findings = (state.get("verification") or {}).get("findings", [])
        message = (
            f"Report failed verification after {state.get('repair_count', 0)} repair attempt(s); "
            "nothing was published (fail closed)."
        )
        async with self._d.uow() as uow:
            await uow.runs.update(run_id, status=RunStatus.FAILED, error=message, current_step="fail_closed")
            await uow.commit()
        await self._d.events.emit(
            run_id,
            step="fail_closed",
            type=EventType.STEP,
            status=StepStatus.FAILED,
            message=message,
            outputs={"findings": findings[:20]},
        )
        await self._d.events.emit(
            run_id, step="run", type=EventType.RUN, status=RunStatus.FAILED.value, message=message
        )
        self._d.events.forget(run_id)
        return {}

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _analysts(state: PipelineState, evidence: EvidenceBundle) -> dict[str, AnalystResult]:
        out = {}
        for name, d in (state.get("analysts") or {}).items():
            own = [e for i in d["evidence_ids"] if (e := evidence.get(i)) is not None]
            out[name] = AnalystResult.from_dict(d, own)
        return out

    @staticmethod
    def _assessments(state: PipelineState) -> dict[Horizon, HorizonAssessment]:
        return {Horizon(h): HorizonAssessment.from_dict(a) for h, a in (state.get("assessments") or {}).items()}

    def _writer_input(self, state: PipelineState) -> WriterInput:
        evidence = EvidenceBundle.from_dicts(state["evidence"])
        bundle = codec.decode_bundle(state["bundle"])
        return WriterInput(
            asset=codec.asset(state["asset"]),
            evidence=evidence,
            assessments=self._assessments(state),
            analysts=self._analysts(state, evidence),
            portfolio=state.get("portfolio") or {},
            reconciliation=Reconciliation.from_dict(state["reconciliation"] or {}),
            data_gaps=tuple(bundle.data_gaps),
        )


ANALYST_NAMES = tuple(a.name for a in ANALYSTS)
