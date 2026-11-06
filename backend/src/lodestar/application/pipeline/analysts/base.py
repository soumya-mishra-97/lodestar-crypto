"""Analyst framework shared by the Technical, Fundamental, Sentiment and Risk agents.

An analyst run has three phases:
  1. ReAct loop: the policy (Claude or scripted) investigates with read-only tools.
     Tools compute values in code and register them as evidence.
  2. Finalize: code computes the analyst's required metrics and signals, whatever
     the policy chose to look at, so scores never depend on model behaviour.
  3. Claims: the policy's claims are pre-screened by the verifier rules; invalid
     ones are dropped. If none survive (or there is no LLM), template claims are used.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar

from lodestar.application.pipeline.react import (
    AgentBrief,
    AnalystPolicy,
    StepRecord,
    Tool,
    Toolkit,
    ToolResult,
    ToolSpec,
    run_react,
)
from lodestar.domain.claims import Claim
from lodestar.domain.evidence import Evidence, EvidenceBundle, EvidenceRegistry
from lodestar.domain.models import Asset, MarketDataBundle
from lodestar.domain.reconciliation import Reconciliation
from lodestar.domain.scoring import RiskAssessment, Signal
from lodestar.domain.verification import check_claim


@dataclass(slots=True)
class AnalystContext:
    asset: Asset
    bundle: MarketDataBundle
    data: EvidenceBundle  # evidence registered by the Data step
    registry: EvidenceRegistry  # this analyst's own namespace
    reconciliation: Reconciliation

    def ev(self, key: str) -> str | None:
        """Evidence id for a key: the analyst's own computation first, then collected data."""
        if own := self.registry.id_of(key):
            return own
        item = self.data.by_key(key)
        return item.id if item else None

    def view(self) -> EvidenceBundle:
        return EvidenceBundle(self.data.items + self.registry.items)

    def describe(self, *keys: str) -> dict[str, Any]:
        """Tool observation for evidence keys: {key: {id, value, label}} for those present."""
        out: dict[str, Any] = {}
        view = self.view()
        for key in keys:
            if (eid := self.ev(key)) and (item := view.get(eid)):
                out[key] = {"id": item.id, "value": item.value, "label": item.label}
        return out


@dataclass(frozen=True, slots=True)
class AnalystResult:
    name: str
    signals: tuple[Signal, ...]
    risks: tuple[RiskAssessment, ...]
    claims: tuple[Claim, ...]
    evidence: tuple[Evidence, ...]
    steps: int
    tool_calls: int
    stop_reason: str
    claims_source: str  # "llm" | "template"
    dropped_claims: int
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "signals": [s.to_dict() for s in self.signals],
            "risks": [r.to_dict() for r in self.risks],
            "claims": [c.to_dict() for c in self.claims],
            "evidence_ids": [e.id for e in self.evidence],
            "steps": self.steps,
            "tool_calls": self.tool_calls,
            "stop_reason": self.stop_reason,
            "claims_source": self.claims_source,
            "dropped_claims": self.dropped_claims,
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any], evidence: Sequence[Evidence] = ()) -> AnalystResult:
        return cls(
            name=d["name"],
            signals=tuple(Signal.from_dict(s) for s in d["signals"]),
            risks=tuple(RiskAssessment.from_dict(r) for r in d["risks"]),
            claims=tuple(Claim.from_dict(c) for c in d["claims"]),
            evidence=tuple(evidence),
            steps=d["steps"],
            tool_calls=d["tool_calls"],
            stop_reason=d["stop_reason"],
            claims_source=d["claims_source"],
            dropped_claims=d["dropped_claims"],
            summary=d["summary"],
        )


def spec(
    name: str, description: str, properties: dict[str, Any] | None = None, required: Sequence[str] = ()
) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=description,
        input_schema={
            "type": "object",
            "properties": properties or {},
            "required": list(required),
            "additionalProperties": False,
        },
    )


def result(ctx: AnalystContext, observation: dict[str, Any]) -> ToolResult:
    """Wrap an observation and lift every evidence id it mentions into the result."""
    ids: list[str] = []

    def walk(v: Any) -> None:
        if isinstance(v, dict):
            if isinstance(v.get("id"), str):
                ids.append(v["id"])
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(observation)
    return ToolResult(observation, tuple(dict.fromkeys(ids)))


class Analyst(ABC):
    name: ClassVar[str]
    namespace: ClassVar[str]
    title: ClassVar[str]
    mandate: ClassVar[str]

    @abstractmethod
    def tools(self, ctx: AnalystContext) -> list[Tool]: ...

    @abstractmethod
    def finalize(self, ctx: AnalystContext) -> tuple[list[Signal], list[RiskAssessment]]:
        """Compute required metrics and signals in code (idempotent)."""

    @abstractmethod
    def scripted_plan(self) -> list[tuple[str, dict[str, Any]]]: ...

    @abstractmethod
    def template_claims(
        self, ctx: AnalystContext, signals: Sequence[Signal], risks: Sequence[RiskAssessment]
    ) -> list[Claim]: ...

    def common_tools(self, ctx: AnalystContext) -> list[Tool]:
        def list_evidence(args: Mapping[str, Any]) -> ToolResult:
            prefix = str(args.get("prefix", "")).upper()
            items = [e for e in ctx.view().items if e.id.startswith(prefix)]
            return result(
                ctx,
                {"items": [{"id": e.id, "label": e.label, "value": e.value, "unit": e.unit} for e in items[:60]]},
            )

        return [
            Tool(
                spec(
                    "list_evidence",
                    "List evidence already collected for this run (id, label, value, unit). "
                    "Optionally filter by id prefix, e.g. 'DAT' (market data), 'NWS' (headlines), "
                    "or your own namespace.",
                    {"prefix": {"type": "string", "description": "Id prefix filter"}},
                ),
                list_evidence,
            )
        ]

    async def run(
        self,
        ctx: AnalystContext,
        policy: AnalystPolicy,
        *,
        max_steps: int,
        on_step: Callable[[StepRecord], Awaitable[None]],
    ) -> AnalystResult:
        toolkit = Toolkit([*self.tools(ctx), *self.common_tools(ctx)])
        brief = AgentBrief(
            analyst=self.name,
            title=self.title,
            mandate=self.mandate,
            asset_name=ctx.asset.name,
            asset_symbol=ctx.asset.symbol,
            max_steps=max_steps,
            evidence_catalogue=tuple(
                {"id": e.id, "label": e.label, "value": e.value, "unit": e.unit, "kind": e.kind.value}
                for e in ctx.data.items
            ),
        )
        outcome = await run_react(policy, toolkit, brief, on_step=on_step)
        signals, risks = self.finalize(ctx)

        claims: list[Claim] = []
        dropped = 0
        source = "template"
        if outcome.final is not None and outcome.final.claims is not None:
            view = ctx.view()
            for claim in outcome.final.claims:
                if check_claim(claim, view):
                    dropped += 1
                else:
                    claims.append(claim)
            source = "llm" if claims else "template"
        if not claims:
            claims = self.template_claims(ctx, signals, risks)

        summary = outcome.final.summary if outcome.final else ""
        if outcome.stop_reason == "step_limit":
            summary = f"Stopped at the {max_steps}-step limit; signals were computed by code."
        elif outcome.stop_reason == "policy_error":
            summary = f"Model unavailable ({outcome.error}); used deterministic findings."
        return AnalystResult(
            name=self.name,
            signals=tuple(signals),
            risks=tuple(risks),
            claims=tuple(claims),
            evidence=ctx.registry.items,
            steps=len(outcome.steps),
            tool_calls=sum(len(s.calls) for s in outcome.steps),
            stop_reason=outcome.stop_reason,
            claims_source=source,
            dropped_claims=dropped,
            summary=summary,
        )
