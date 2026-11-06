"""A small, explicit ReAct loop: decide -> act (read-only tool) -> observe, with a hard step limit.

The loop is ours, not the model's: the policy only *chooses* the next action.
Tools are pure reads over data already collected for the run; they may register
computed evidence, but they cannot fetch new data, write to storage, or trade.

Two interchangeable policies drive it (Strategy pattern):
  ScriptedPolicy   deterministic plan, used without an LLM key and in tests
  ClaudePolicy     Claude tool use (infrastructure/llm), same tools, same limits
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from lodestar.domain.claims import Claim
from lodestar.domain.errors import LlmUnavailable

MAX_CALLS_PER_STEP = 4
StopReason = Literal["final", "step_limit", "policy_error"]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    args: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ToolResult:
    content: dict[str, Any]
    evidence_ids: tuple[str, ...] = ()
    is_error: bool = False


@dataclass(frozen=True, slots=True)
class FinalAnswer:
    """The agent's conclusion. `claims=None` asks for the analyst's deterministic template claims."""

    claims: tuple[Claim, ...] | None
    summary: str = ""


@dataclass(frozen=True, slots=True)
class StepRecord:
    index: int
    calls: tuple[tuple[ToolCall, ToolResult], ...]


@dataclass(frozen=True, slots=True)
class AgentBrief:
    analyst: str
    title: str
    mandate: str
    asset_name: str
    asset_symbol: str
    max_steps: int
    evidence_catalogue: tuple[dict[str, Any], ...] = ()  # data evidence the agent may cite


class AnalystPolicy(Protocol):
    async def decide(
        self, brief: AgentBrief, tools: Sequence[ToolSpec], history: Sequence[StepRecord]
    ) -> list[ToolCall] | FinalAnswer: ...


PolicyFactory = Callable[[str], AnalystPolicy]


@dataclass(frozen=True, slots=True)
class Tool:
    spec: ToolSpec
    handler: Callable[[Mapping[str, Any]], ToolResult]


class Toolkit:
    def __init__(self, tools: Sequence[Tool]) -> None:
        self._tools = {t.spec.name: t for t in tools}

    @property
    def specs(self) -> list[ToolSpec]:
        return [t.spec for t in self._tools.values()]

    def execute(self, call: ToolCall) -> ToolResult:
        tool = self._tools.get(call.name)
        if tool is None:
            return ToolResult({"error": f"unknown tool '{call.name}'", "available": sorted(self._tools)}, is_error=True)
        problem = _validate(call.args, tool.spec.input_schema)
        if problem:
            return ToolResult({"error": problem}, is_error=True)
        try:
            return tool.handler(call.args)
        except (ValueError, KeyError, TypeError) as exc:
            return ToolResult({"error": f"{type(exc).__name__}: {exc}"}, is_error=True)


def _validate(args: Mapping[str, Any], schema: Mapping[str, Any]) -> str | None:
    """Minimal JSON-schema check: required keys, no unknown keys, enums and integer bounds."""
    props: Mapping[str, Any] = schema.get("properties", {})
    missing = [k for k in schema.get("required", []) if k not in args]
    if missing:
        return f"missing required argument(s): {missing}"
    unknown = [k for k in args if k not in props]
    if unknown:
        return f"unknown argument(s): {unknown}"
    for key, value in args.items():
        spec = props[key]
        if "enum" in spec and value not in spec["enum"]:
            return f"{key} must be one of {spec['enum']}"
        if spec.get("type") == "integer":
            if not isinstance(value, int) or isinstance(value, bool):
                return f"{key} must be an integer"
            if not spec.get("minimum", value) <= value <= spec.get("maximum", value):
                return f"{key} must be between {spec.get('minimum')} and {spec.get('maximum')}"
        if spec.get("type") == "string" and not isinstance(value, str):
            return f"{key} must be a string"
    return None


@dataclass(slots=True)
class ReactOutcome:
    final: FinalAnswer | None
    steps: list[StepRecord] = field(default_factory=list)
    stop_reason: StopReason = "final"
    error: str | None = None


async def run_react(
    policy: AnalystPolicy,
    toolkit: Toolkit,
    brief: AgentBrief,
    *,
    on_step: Callable[[StepRecord], Awaitable[None]],
) -> ReactOutcome:
    history: list[StepRecord] = []
    for index in range(1, brief.max_steps + 1):
        try:
            action = await policy.decide(brief, toolkit.specs, history)
        except LlmUnavailable as exc:
            return ReactOutcome(None, history, "policy_error", str(exc))
        if isinstance(action, FinalAnswer):
            return ReactOutcome(action, history, "final")
        calls = action[:MAX_CALLS_PER_STEP]
        record = StepRecord(index, tuple((c, toolkit.execute(c)) for c in calls))
        history.append(record)
        await on_step(record)
    return ReactOutcome(None, history, "step_limit")


class ScriptedPolicy:
    """Deterministic policy: one planned tool call per step, then defer to template claims."""

    def __init__(self, plan: Sequence[tuple[str, Mapping[str, Any]]]) -> None:
        self._plan = list(plan)

    async def decide(
        self, brief: AgentBrief, tools: Sequence[ToolSpec], history: Sequence[StepRecord]
    ) -> list[ToolCall] | FinalAnswer:
        step = len(history)
        # Leave the last step for the final answer so a long plan never hits the limit.
        if step < len(self._plan) and step < brief.max_steps - 1:
            name, args = self._plan[step]
            return [ToolCall(id=f"{brief.analyst}-{step + 1}", name=name, args=dict(args))]
        return FinalAnswer(claims=None, summary="Scripted plan complete")
