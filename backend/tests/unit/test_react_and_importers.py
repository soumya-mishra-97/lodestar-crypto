"""The ReAct loop's limits and tool hygiene, CSV import parsing and report export."""

from collections.abc import Mapping, Sequence
from typing import Any

from lodestar.application.importers import parse_holdings_csv
from lodestar.application.pipeline.react import (
    AgentBrief,
    FinalAnswer,
    ScriptedPolicy,
    StepRecord,
    Tool,
    ToolCall,
    Toolkit,
    ToolResult,
    ToolSpec,
    run_react,
)
from lodestar.domain.errors import LlmUnavailable

BRIEF = AgentBrief("technical", "Technical analyst", "test", "Polygon", "POL", max_steps=3)


def echo_tool() -> Tool:
    def handler(args: Mapping[str, Any]) -> ToolResult:
        if args["n"] == 13:
            raise ValueError("unlucky")
        return ToolResult({"n": args["n"]}, ("TEC-01",))

    spec = ToolSpec(
        "echo",
        "echo",
        {
            "type": "object",
            "properties": {
                "n": {"type": "integer", "minimum": 0, "maximum": 100},
                "mode": {"type": "string", "enum": ["a"]},
            },
            "required": ["n"],
        },
    )
    return Tool(spec, handler)


class LoopingPolicy:
    """Never finishes: the loop must stop it."""

    async def decide(self, brief: AgentBrief, tools: Sequence[ToolSpec], history: Sequence[StepRecord]) -> Any:
        return [ToolCall(f"c{len(history)}", "echo", {"n": len(history)})]


async def noop(_: StepRecord) -> None:
    return None


async def test_step_limit_stops_a_runaway_policy() -> None:
    seen: list[StepRecord] = []

    async def record(step: StepRecord) -> None:
        seen.append(step)

    outcome = await run_react(LoopingPolicy(), Toolkit([echo_tool()]), BRIEF, on_step=record)
    assert outcome.stop_reason == "step_limit"
    assert outcome.final is None
    assert [s.index for s in seen] == [1, 2, 3]


async def test_tool_errors_become_observations_not_crashes() -> None:
    kit = Toolkit([echo_tool()])
    assert kit.execute(ToolCall("1", "nope", {})).is_error
    assert "missing required" in kit.execute(ToolCall("2", "echo", {})).content["error"]
    assert "unknown argument" in kit.execute(ToolCall("3", "echo", {"n": 1, "x": 2})).content["error"]
    assert "between" in kit.execute(ToolCall("4", "echo", {"n": 500})).content["error"]
    assert "must be one of" in kit.execute(ToolCall("5", "echo", {"n": 1, "mode": "b"})).content["error"]
    assert kit.execute(ToolCall("6", "echo", {"n": 13})).content == {"error": "ValueError: unlucky"}
    ok = kit.execute(ToolCall("7", "echo", {"n": 2}))
    assert (ok.is_error, ok.evidence_ids) == (False, ("TEC-01",))


async def test_scripted_policy_leaves_room_for_the_final_answer() -> None:
    plan = [("echo", {"n": i}) for i in range(10)]
    outcome = await run_react(ScriptedPolicy(plan), Toolkit([echo_tool()]), BRIEF, on_step=noop)
    assert outcome.stop_reason == "final"
    assert len(outcome.steps) == BRIEF.max_steps - 1
    assert isinstance(outcome.final, FinalAnswer)
    assert outcome.final.claims is None


async def test_policy_outage_is_reported_not_raised() -> None:
    class Down:
        async def decide(self, *_: Any) -> Any:
            raise LlmUnavailable("rate limited")

    outcome = await run_react(Down(), Toolkit([echo_tool()]), BRIEF, on_step=noop)
    assert (outcome.stop_reason, outcome.error) == ("policy_error", "rate limited")


def test_csv_parsing_is_tolerant_of_headers_and_strict_on_values() -> None:
    text = '﻿Symbol,Qty,Avg Cost,Notes\nPOL,"12,000",$0.31,cold wallet\nbtc,0.5,,\n,1,1,\nETH,-2,100,\nSOL,abc,1,\n\n'
    out = parse_holdings_csv(text.replace("Avg Cost", "avg_cost"))
    assert [(r.symbol, r.quantity, r.avg_cost_usd) for r in out.rows] == [("POL", 12000.0, 0.31), ("BTC", 0.5, None)]
    assert [line for line, _ in out.errors] == [4, 5, 6]

    by_id = parse_holdings_csv("coingecko_id,quantity\npolygon-ecosystem-token,5\n../etc,1\n")
    assert by_id.rows[0].coingecko_id == "polygon-ecosystem-token"
    assert by_id.errors[0][0] == 3

    assert parse_holdings_csv("name,amount\nx,1\n").errors  # no coin/symbol column
    leaked = parse_holdings_csv("symbol,quantity,notes\nPOL,1," + "0x" + "ab" * 32 + "\n")
    assert not leaked.rows
    assert "private key" in leaked.errors[0][1]
