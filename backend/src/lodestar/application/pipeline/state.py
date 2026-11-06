"""Graph state shared by every pipeline step.

Only JSON values live here: LangGraph checkpoints the state after every step,
and checkpoints must be safe to store and reload in another process.
Parallel analysts write to `evidence` and `analysts` concurrently, so both use
merge reducers instead of last-writer-wins.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


def merge_dicts(left: dict[str, Any] | None, right: dict[str, Any] | None) -> dict[str, Any]:
    return {**(left or {}), **(right or {})}


class PipelineState(TypedDict, total=False):
    run_id: str
    user_id: str | None
    kind: str
    asset: dict[str, Any]
    preferences: dict[str, Any]

    bundle: dict[str, Any]  # MarketDataBundle (codec.encode_bundle)
    reconciliation: dict[str, Any] | None
    evidence: Annotated[list[dict[str, Any]], operator.add]
    analysts: Annotated[dict[str, dict[str, Any]], merge_dicts]

    assessments: dict[str, dict[str, Any]]  # horizon -> HorizonAssessment
    portfolio: dict[str, Any]

    draft: dict[str, Any] | None
    verification: dict[str, Any] | None
    attempt: int  # writer attempts so far
    repair_count: int
    feedback: list[str]

    report_id: str | None
    decision: dict[str, Any] | None

    # trade-plan pipeline only
    bars: list[dict[str, Any]]
    bars_approximate: bool
    btc_closes: list[float] | None
    scan: dict[str, Any]
    timing: dict[str, Any]
    scenarios: dict[str, Any]
    sizing: dict[str, Any]
    backtest: dict[str, Any]
    backtest_id: str | None
