"""LangGraph wiring for the agent pipeline (adapter for the WorkflowEngine port).

The graph is checkpointed after every step (Postgres in production), keyed by
run id. That is what lets the human-approval step pause indefinitely in one
worker process and resume later in another.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from lodestar.application.pipeline.nodes import ANALYST_NAMES, ANALYSTS, PipelineNodes, route_after_verification
from lodestar.application.pipeline.state import PipelineState
from lodestar.application.trading.analysts import TRADE_ANALYSTS
from lodestar.application.trading.nodes import TradeNodes


def build_graph(nodes: PipelineNodes, *, max_repairs: int) -> Any:
    g: Any = StateGraph(PipelineState)
    g.add_node("data", nodes.data)
    for analyst in ANALYSTS:
        g.add_node(analyst.name, nodes.analyst_node(analyst))
    g.add_node("portfolio", nodes.portfolio)
    g.add_node("report_writer", nodes.report_writer)
    g.add_node("verifier", nodes.verifier)
    g.add_node("human_approval", nodes.human_approval)
    g.add_node("fail_closed", nodes.fail_closed)

    g.add_edge(START, "data")
    for name in ANALYST_NAMES:  # fan out: the four analysts run in parallel
        g.add_edge("data", name)
    g.add_edge(list(ANALYST_NAMES), "portfolio")  # fan in: wait for all four
    g.add_edge("portfolio", "report_writer")
    g.add_edge("report_writer", "verifier")
    g.add_conditional_edges(
        "verifier",
        lambda state: route_after_verification(state, max_repairs=max_repairs),
        {"human_approval": "human_approval", "report_writer": "report_writer", "fail_closed": "fail_closed"},
    )
    g.add_edge("human_approval", END)
    g.add_edge("fail_closed", END)
    return g


def build_trade_graph(nodes: TradeNodes, *, max_repairs: int) -> Any:
    """The trader-skills coordinator: five skills in parallel, then the engine skills in sequence."""
    g: Any = StateGraph(PipelineState)
    g.add_node("data", nodes.data)
    for analyst in TRADE_ANALYSTS:
        g.add_node(analyst.name, nodes.analyst_node(analyst))
    for name in (
        "timing_agent",
        "scenario_stats_engine",
        "risk_position_sizer",
        "backtester",
        "report_writer",
        "verifier",
        "human_approval",
        "fail_closed",
    ):
        g.add_node(name, getattr(nodes, name))
    g.add_edge(START, "data")
    names = [a.name for a in TRADE_ANALYSTS]
    for name in names:
        g.add_edge("data", name)
    g.add_edge(names, "timing_agent")
    g.add_edge("timing_agent", "scenario_stats_engine")
    g.add_edge("scenario_stats_engine", "risk_position_sizer")
    g.add_edge("risk_position_sizer", "backtester")
    g.add_edge("backtester", "report_writer")
    g.add_edge("report_writer", "verifier")
    g.add_conditional_edges(
        "verifier",
        lambda state: route_after_verification(state, max_repairs=max_repairs),
        {"human_approval": "human_approval", "report_writer": "report_writer", "fail_closed": "fail_closed"},
    )
    g.add_edge("human_approval", END)
    g.add_edge("fail_closed", END)
    return g


class LangGraphEngine:
    def __init__(self, graph: Any, checkpointer: BaseCheckpointSaver[Any]) -> None:
        # Untyped handle: LangGraph's overloads are stricter than our JSON state contract needs.
        self._app: Any = graph.compile(checkpointer=checkpointer)

    @staticmethod
    def _config(thread_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": thread_id}, "recursion_limit": 40}

    async def start(self, thread_id: str, state: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = await self._app.ainvoke(state, self._config(thread_id))
        return result

    async def resume(self, thread_id: str, value: dict[str, Any]) -> dict[str, Any]:
        snapshot = await self._app.aget_state(self._config(thread_id))
        if not snapshot.next:
            return dict(snapshot.values)  # nothing waiting (already resumed or never paused)
        result: dict[str, Any] = await self._app.ainvoke(Command(resume=value), self._config(thread_id))
        return result


def psycopg_url(database_url: str) -> str:
    """SQLAlchemy's asyncpg URL -> a libpq URL psycopg understands."""
    return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


@asynccontextmanager
async def postgres_checkpointer(database_url: str) -> AsyncIterator[AsyncPostgresSaver]:
    pool = AsyncConnectionPool(
        psycopg_url(database_url),
        max_size=5,
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
    await pool.open()
    try:
        saver = AsyncPostgresSaver(pool)  # type: ignore[arg-type]  # dict_row is set via kwargs
        await saver.setup()  # idempotent: creates/migrates its own checkpoint tables
        yield saver
    finally:
        await pool.close()
