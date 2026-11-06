"""Trade-plan pipeline steps (the coordinator as graph nodes).

    data -+- news_event_scout ----+
          +- sentiment_reader ----+
          +- fundamentals_analyst +- timing_agent - scenario_stats_engine - risk_position_sizer
          +- technical_analyst ---+     - backtester - report_writer - verifier -+- human_approval
          +- liquidity_checker ---+                        ^ (repair, max 2) ---+- fail_closed

Instrumentation, streaming, the approval gate and fail-closed behaviour are inherited
from the analysis pipeline; only the steps differ.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from lodestar.application import codec
from lodestar.application.pipeline.events import EventType, StepStatus
from lodestar.application.pipeline.nodes import PIPELINE_VERSION, PipelineDeps, PipelineNodes
from lodestar.application.pipeline.state import PipelineState
from lodestar.application.ports import ReportSummary
from lodestar.application.trading.analysts import TRADE_ANALYSTS
from lodestar.application.trading.common import TradingPrefs
from lodestar.application.trading.coordinator import build_card, collect
from lodestar.application.trading.engines import backtester, risk_position_sizer, scenario_stats_engine, timing_agent
from lodestar.application.trading.services import BacktestService, PaperService
from lodestar.application.trading.writer import TradePlanWriter, TradePlanWriterPort, TradeWriterInput
from lodestar.domain.evidence import EvidenceBundle
from lodestar.domain.models import ReportKind, RunStatus
from lodestar.domain.trading.bars import Bars
from lodestar.domain.trading.plan import TradePlanDraft, verify_trade_plan
from lodestar.domain.trading.setups import SetupKind, current_levels

TRADE_STEPS = (
    "data",
    *(a.name for a in TRADE_ANALYSTS),
    "timing_agent",
    "scenario_stats_engine",
    "risk_position_sizer",
    "backtester",
    "report_writer",
    "verifier",
    "human_approval",
)


@dataclass(frozen=True, slots=True)
class TradeDeps:
    paper: PaperService
    backtests: BacktestService
    writer: TradePlanWriterPort = field(default_factory=TradePlanWriter)


class TradeNodes(PipelineNodes):
    def __init__(self, deps: PipelineDeps, trade: TradeDeps) -> None:
        super().__init__(deps)
        self._t = trade

    def _prefs(self, state: PipelineState) -> TradingPrefs:
        return TradingPrefs.from_prefs(state.get("preferences"))

    @staticmethod
    def _bars(state: PipelineState) -> Bars:
        return Bars.from_dicts(state["bars"], approximate=bool(state.get("bars_approximate")))

    # ------------------------------------------------------------------ data (+ market scanner for this coin)

    async def data(self, state: PipelineState) -> dict[str, Any]:
        run_id = UUID(state["run_id"])
        asset = codec.asset(state["asset"])
        prefs_raw = state.get("preferences") or {}
        async with self._d.uow() as uow:
            await uow.runs.update(run_id, status=RunStatus.RUNNING)
            await uow.commit()
        await self._d.events.emit(run_id, step="run", type=EventType.RUN, status=RunStatus.RUNNING.value)

        async def work() -> tuple[dict[str, Any], dict[str, Any], list[str]]:
            data = await collect(
                self._d.sources,
                asset,
                self._prefs(state),
                self._d.clock.now(),
                polymarket=bool(prefs_raw.get("polymarket_enabled", True)),
                tolerance_pct=float(prefs_raw.get("mismatch_tolerance_pct", self._d.config.mismatch_tolerance_pct)),
            )
            if data.reconciliation.status == "mismatch":
                await self._d.events.emit(
                    run_id,
                    step="data",
                    type=EventType.NOTE,
                    level="warning",
                    message=f"Price mismatch: {', '.join(data.reconciliation.mismatched_sources)} deviate beyond "
                    "tolerance",
                )
            update = {
                "bundle": codec.encode_bundle(data.bundle),
                "reconciliation": data.reconciliation.to_dict(),
                "evidence": [e.to_dict() for e in data.evidence],
                "bars": data.bars.to_dicts(),
                "bars_approximate": data.bars.approximate,
                "btc_closes": data.btc_closes,
                "scan": data.scan.result,
            }
            outputs = {
                "bars": len(data.bars),
                "ohlc_source": "approximated from closes" if data.bars.approximate else self._d.sources.exchange.venue,
                "order_book": data.bundle.order_book is not None,
                "funding": data.bundle.funding is not None,
                "scanner": {
                    k: data.scan.result[k]
                    for k in ("score", "trend_points", "breakout", "volume_ratio", "rs_vs_btc_pct", "passes_liquidity")
                },
                "reconciliation": data.reconciliation.status,
                "data_gaps": data.bundle.data_gaps,
            }
            return update, outputs, [e.id for e in data.evidence]

        return await self._step(
            state, "data", work, inputs={"asset": asset.symbol, "mode": self._d.sources.mode, "skill": "market-scanner"}
        )

    # ------------------------------------------------------------------ engines

    async def timing_agent(self, state: PipelineState) -> dict[str, Any]:
        async def work() -> tuple[dict[str, Any], dict[str, Any], list[str]]:
            _, out = timing_agent(self._bars(state), self._d.clock.now())
            keep = ("kind", "status", "level", "entry_low", "entry_high", "invalidation", "profit_level", "atr")
            return (
                {"timing": out.result, "evidence": [e.to_dict() for e in out.evidence]},
                {k: out.result[k] for k in keep},
                [e.id for e in out.evidence],
            )

        return await self._step(
            state, "timing_agent", work, inputs={"rule": "conditions only: entry zone, trigger, invalidation"}
        )

    async def scenario_stats_engine(self, state: PipelineState) -> dict[str, Any]:
        prefs = self._prefs(state)
        kind = SetupKind(state["timing"]["kind"])

        async def work() -> tuple[dict[str, Any], dict[str, Any], list[str]]:
            out = scenario_stats_engine(self._bars(state), kind, prefs, self._d.clock.now())
            result = out.result
            outputs = {
                "overall": result["overall"],
                "scenarios": [{k: s[k] for k in ("name", "count", "probability_pct")} for s in result["scenarios"]],
            }
            if result["overall"]["reliability"] != "adequate":
                await self._d.events.emit(
                    UUID(state["run_id"]),
                    step="scenario_stats_engine",
                    type=EventType.NOTE,
                    level="warning",
                    message=f"Sample is {result['overall']['reliability']} ({result['overall']['n']} past signals): "
                    "statistics are not reliable on their own",
                )
            return (
                {"scenarios": result, "evidence": [e.to_dict() for e in out.evidence]},
                outputs,
                [e.id for e in out.evidence],
            )

        return await self._step(
            state,
            "scenario_stats_engine",
            work,
            inputs={"setup": kind.value, "horizon_days": prefs.horizon_days, "cost_pct": prefs.round_trip_cost_pct},
        )

    async def risk_position_sizer(self, state: PipelineState) -> dict[str, Any]:
        prefs = self._prefs(state)
        user_id = UUID(state["user_id"]) if state.get("user_id") else None

        async def work() -> tuple[dict[str, Any], dict[str, Any], list[str]]:
            bars = self._bars(state)
            bundle = codec.decode_bundle(state["bundle"])
            levels = current_levels(bars, kind=SetupKind(state["timing"]["kind"]))
            account = await self._t.paper.sizing_context(user_id)
            out = risk_position_sizer(
                bars,
                levels,
                bundle,
                state.get("btc_closes"),
                account,
                prefs,
                (state.get("reconciliation") or {}).get("status") == "mismatch",
                self._d.clock.now(),
                bundle.order_book,
            )
            keep = (
                "units",
                "notional_usd",
                "pct_of_equity",
                "max_loss_usd",
                "loss_at_stop_usd",
                "binding",
                "expected_slippage_pct",
                "warnings",
            )
            outputs = {**{k: out.result[k] for k in keep}, "risk_level": out.result["risk"]["level"]}
            return (
                {"sizing": out.result, "evidence": [e.to_dict() for e in out.evidence]},
                outputs,
                [e.id for e in out.evidence],
            )

        return await self._step(
            state,
            "risk_position_sizer",
            work,
            inputs={k: getattr(prefs, k) for k in ("max_loss_pct", "max_position_pct", "max_slippage_pct")},
        )

    async def backtester(self, state: PipelineState) -> dict[str, Any]:
        prefs = self._prefs(state)
        kind = SetupKind(state["timing"]["kind"])
        asset = codec.asset(state["asset"])

        async def work() -> tuple[dict[str, Any], dict[str, Any], list[str]]:
            report, out = backtester(self._bars(state), kind, prefs, self._d.clock.now())
            saved = await self._t.backtests.save(
                UUID(state["user_id"]) if state.get("user_id") else None,
                asset,
                kind,
                out.result,
                run_id=UUID(state["run_id"]),
            )
            outputs = {
                "backtest_id": saved["id"],
                "in_sample": report.in_sample.to_dict(),
                "out_of_sample": report.out_of_sample.to_dict(),
                "walk_forward_folds": len(report.folds),
                "warnings": report.warnings,
            }
            return (
                {"backtest": out.result, "backtest_id": saved["id"], "evidence": [e.to_dict() for e in out.evidence]},
                outputs,
                [e.id for e in out.evidence],
            )

        return await self._step(
            state,
            "backtester",
            work,
            inputs={
                "setup": kind.value,
                "fee_bps": prefs.fee_bps,
                "slippage_bps": prefs.slippage_bps,
                "tests": "in-sample, out-of-sample, walk-forward",
            },
        )

    # ------------------------------------------------------------------ writer / verifier

    async def report_writer(self, state: PipelineState) -> dict[str, Any]:
        attempt = state.get("attempt", 0) + 1
        feedback = state.get("feedback") or []

        async def work() -> tuple[dict[str, Any], dict[str, Any], list[str]]:
            evidence = EvidenceBundle.from_dicts(state["evidence"])
            bundle = codec.decode_bundle(state["bundle"])
            draft = await self._t.writer.write(
                TradeWriterInput(
                    codec.asset(state["asset"]),
                    evidence,
                    self._analysts(state, evidence),
                    state["sizing"],
                    tuple(bundle.data_gaps),
                ),
                feedback,
            )
            update: dict[str, Any] = {"draft": draft.to_dict(), "attempt": attempt}
            if attempt > 1:
                update["repair_count"] = state.get("repair_count", 0) + 1
            cited = sorted({i for c in draft.all_claims() for i in c.evidence_ids})
            return (
                update,
                {"writer": draft.writer, "claims": len(draft.all_claims()), "headline": draft.headline.text},
                cited,
            )

        return await self._step(
            state,
            "report_writer",
            work,
            attempt=attempt,
            inputs={"card": "trade plan", "repair_feedback": feedback or None},
        )

    async def verifier(self, state: PipelineState) -> dict[str, Any]:
        run_id = UUID(state["run_id"])
        attempt = state.get("attempt", 1)

        async def work() -> tuple[dict[str, Any], dict[str, Any], list[str]]:
            draft = TradePlanDraft.from_dict(state["draft"] or {})
            result = verify_trade_plan(draft, EvidenceBundle.from_dicts(state["evidence"]))
            update: dict[str, Any] = {"verification": result.to_dict()}
            outputs: dict[str, Any] = {
                "passed": result.passed,
                "checked_claims": result.checked_claims,
                "findings": result.feedback(),
            }
            if result.passed:
                report_id = await self._publish_plan(state, draft, result.to_dict())
                update["report_id"] = outputs["report_id"] = str(report_id)
            else:
                repairs = state.get("repair_count", 0)
                update["feedback"] = result.feedback()
                if repairs < self._d.config.max_repairs:
                    await self._d.events.emit(
                        run_id,
                        step="verifier",
                        type=EventType.NOTE,
                        level="warning",
                        message=f"Verification failed with {len(result.findings)} finding(s); repair loop "
                        f"{repairs + 1} of {self._d.config.max_repairs}",
                    )
            return update, outputs, []

        update = await self._step(
            state,
            "verifier",
            work,
            attempt=attempt,
            inputs={"attempt": attempt, "rules": "claims C1-C9, trade plan P1-P7"},
        )
        if update.get("report_id"):
            await self._d.events.emit(
                run_id,
                step="human_approval",
                type=EventType.STEP,
                status=StepStatus.WAITING,
                inputs={"report_id": update["report_id"]},
                message="Verified trade plan is waiting for your review",
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

    async def _publish_plan(self, state: PipelineState, draft: TradePlanDraft, verification: dict[str, Any]) -> UUID:
        run_id = UUID(state["run_id"])
        asset = codec.asset(state["asset"])
        bundle = codec.decode_bundle(state["bundle"])
        card = build_card(asset, state["timing"], state["scenarios"], state["sizing"], state["backtest"], state["scan"])
        content = {
            "kind": "trade_plan",
            "pipeline_version": PIPELINE_VERSION,
            "generated_at": self._d.clock.now().isoformat(),
            "data_mode": self._d.sources.mode,
            "asset": state["asset"],
            "snapshot": state["bundle"]["snapshot"],
            "card": card,
            "outcomes": state["scenarios"].get("outcomes", []),
            "backtest_id": state.get("backtest_id"),
            "draft": draft.to_dict(),
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
        risk_level = card["risk"]["level"]
        summary = ReportSummary(
            headline=draft.headline.text,
            short_term_stance="neutral",
            long_term_stance="neutral",
            short_term_risk=risk_level,
            long_term_risk=risk_level,
            setup_kind=card["setup"]["kind"],
            setup_status=card["setup"]["status"],
        )
        async with self._d.uow() as uow:
            report_id = await uow.reports.create(run_id, asset.id, ReportKind.TRADE_PLAN, summary, content)
            await uow.runs.update(run_id, status=RunStatus.AWAITING_APPROVAL, current_step="human_approval")
            await uow.commit()
        return report_id
