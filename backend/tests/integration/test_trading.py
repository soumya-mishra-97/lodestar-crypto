"""Trader skills end to end over the API and in-memory adapters (demo data, fixed clock)."""

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from lodestar.application.trading.nodes import TRADE_STEPS
from lodestar.config import get_settings
from lodestar.interfaces import skills
from lodestar.interfaces.http.app import create_app
from tests.fakes import PipelineEnv, build_test_env

API = "/api/v1"


@pytest.fixture
async def env() -> PipelineEnv:
    return await build_test_env()


@pytest.fixture
async def client(env: PipelineEnv) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(env.container.settings, env.container)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def plan(client: httpx.AsyncClient, coin: str = "polygon-ecosystem-token") -> dict[str, Any]:
    r = await client.post(f"{API}/trade-plans", json={"coingecko_id": coin})
    assert r.status_code == 202, r.text
    run = (await client.get(f"{API}/runs/{r.json()['run']['id']}")).json()
    assert run["status"] == "awaiting_approval", run["error"]
    return run


async def test_scanner_produces_a_ranked_liquid_shortlist(client: httpx.AsyncClient) -> None:
    r = await client.post(f"{API}/scans", json={"universe": "top", "top_n": 14})
    assert r.status_code == 202
    scan = r.json()
    assert scan["status"] == "completed"
    rows = scan["results"]
    assert len(rows) == 14
    assert [row["rank"] for row in rows] == list(range(1, 15))
    scored = [row for row in rows if row["passes_liquidity"]]
    assert [row["score"] for row in scored] == sorted((row["score"] for row in scored), reverse=True)
    shortlist = [row for row in rows if row["shortlisted"]]
    assert 0 < len(shortlist) <= 5
    assert all(row["passes_liquidity"] for row in shortlist)
    assert {"trend_points", "breakout", "volume_ratio", "rs_vs_btc_pct", "setup_kind"} <= rows[0]["metrics"].keys()
    assert (await client.get(f"{API}/scans/latest")).json()["id"] == scan["id"]
    assert (await client.post(f"{API}/scans", json={"universe": "top", "top_n": 500})).status_code == 422


async def test_selecting_a_coin_runs_the_visible_pipeline_to_a_verified_card(client: httpx.AsyncClient) -> None:
    run = await plan(client)
    completed = {e["step"] for e in run["events"] if e["type"] == "step" and e["status"] == "completed"}
    assert set(TRADE_STEPS) - {"human_approval"} <= completed
    assert ("human_approval", "waiting") in {(e["step"], e["status"]) for e in run["events"]}
    assert any(e["type"] == "tool_call" and e["step"] == "liquidity_checker" for e in run["events"])

    report = (await client.get(f"{API}/reports/{run['report_id']}")).json()
    assert report["kind"] == "trade_plan"
    assert report["setup_kind"] in ("breakout", "pullback", "trend_reclaim")
    c = report["content"]
    card = c["card"]
    assert c["verification"]["passed"] is True
    assert card["timing"]["entry_zone"][0] < card["timing"]["entry_zone"][1]
    assert card["timing"]["invalidation"] < card["timing"]["entry_zone"][0]
    assert card["size"]["loss_at_stop_usd"] <= card["size"]["max_loss_usd"] + 1e-6
    assert [s["name"] for s in card["scenarios"]["scenarios"]] == ["bull", "base", "bear"]
    assert card["scenarios"]["overall"]["reliability"] in ("insufficient", "small", "adequate")
    assert card["risk"]["level"] in ("low", "moderate", "high", "very_high")
    assert "never places orders" in c["disclaimer"]
    ids = {e["id"] for e in c["evidence"]}
    claims = [
        c["draft"]["headline"],
        *(
            x
            for k in ("setup", "timing", "scenarios", "risk", "invalidation", "evidence", "assumptions")
            for x in c["draft"][k]
        ),
    ]
    assert all(set(cl["evidence_ids"]) <= ids for cl in claims)
    assert {"TIM", "SCE", "SIZ", "BKT", "SCN", "LIQ", "EVT"} <= {i.split("-")[0] for i in ids}

    md = await client.get(f"{API}/reports/{run['report_id']}/export.md")
    assert md.status_code == 200
    assert "Trade plan" in md.text
    assert "Entry zone" in md.text

    backtests = (await client.get(f"{API}/backtests")).json()
    assert len(backtests) == 1
    assert backtests[0]["run_id"] == run["id"]
    detail = (await client.get(f"{API}/backtests/{backtests[0]['id']}")).json()
    assert {"in_sample", "out_of_sample", "folds", "walk_forward", "warnings", "equity", "assumptions"} <= detail[
        "result"
    ].keys()


async def test_paper_trading_needs_an_approved_plan_and_advances_on_new_bars(
    client: httpx.AsyncClient, env: PipelineEnv
) -> None:
    run = await plan(client, "solana")
    rid = run["report_id"]
    r = await client.post(f"{API}/paper/positions", json={"report_id": rid})
    assert r.status_code == 409  # not approved yet
    assert (await client.post(f"{API}/reports/{rid}/approve", json={})).status_code == 200
    r = await client.post(f"{API}/paper/positions", json={"report_id": rid})
    assert r.status_code == 201
    position = r.json()
    assert (position["status"], position["origin"]) == ("pending", "plan")
    assert (await client.post(f"{API}/paper/positions", json={"report_id": rid})).status_code == 409  # once per plan

    env.clock.advance(days=20)
    perf = (await client.post(f"{API}/paper/tick")).json()
    assert len(perf["equity"]) == 20
    p = next(x for x in perf["positions"] if x["id"] == position["id"])
    assert p["bars_seen"] > 0
    assert p["status"] in ("pending", "triggered", "open", "closed", "cancelled")
    if p["status"] == "closed":
        assert p["pnl_usd"] is not None
        assert p["fees_usd"] > 0
    assert perf["benchmark"]["label"] == "Bitcoin buy-and-hold"

    reset = (await client.post(f"{API}/paper/reset")).json()
    assert reset["positions"] == []
    assert reset["equity_usd"] == reset["account"]["starting_cash"]


async def test_demo_replay_populates_the_paper_portfolio(client: httpx.AsyncClient) -> None:
    for coin in ("bitcoin", "ethereum", "solana"):
        await client.post(f"{API}/assets", json={"coingecko_id": coin, "analyze": False})
    perf = (await client.post(f"{API}/paper/demo-replay")).json()
    assert len(perf["equity"]) >= 70
    assert perf["positions"]
    assert all(p["origin"] == "demo_replay" for p in perf["positions"])
    statuses = {p["status"] for p in perf["positions"]}
    assert statuses & {"open", "closed", "cancelled"}
    assert perf["data_mode"] == "demo"


async def test_manual_backtest_and_settings(client: httpx.AsyncClient) -> None:
    r = await client.post(f"{API}/backtests", json={"coingecko_id": "bitcoin", "setup": "breakout"})
    assert r.status_code == 200
    body = r.json()
    assert body["summary"]["kind"] == "breakout"
    assert body["result"]["config"]["fee_bps"] == 10.0
    r = await client.put(f"{API}/settings", json={"fee_bps": 25, "horizon_days": 21})
    assert r.json()["preferences"]["horizon_days"] == 21
    body = (await client.post(f"{API}/backtests", json={"coingecko_id": "bitcoin"})).json()
    assert (body["result"]["config"]["fee_bps"], body["result"]["config"]["horizon"]) == (25.0, 21)
    assert (await client.put(f"{API}/settings", json={"max_loss_pct": 50})).status_code == 422


@pytest.mark.parametrize("skill", ["timing-agent", "risk-position-sizer", "liquidity-checker", "trade-plan"])
def test_skills_cli_runs_without_a_database(
    skill: str, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LS_DATA_MODE", "demo")
    get_settings.cache_clear()
    try:
        code = skills.main([skill, "--coin", "solana"])
    finally:
        get_settings.cache_clear()
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert (out["skill"], out["data_mode"]) == (skill, "demo")
    assert "never places orders" in out["disclaimer"]
    if skill == "trade-plan":
        assert out["verification"]["passed"] is True


def test_every_skill_is_packaged_as_a_claude_skill() -> None:
    root = Path(__file__).resolve().parents[3] / "skills"
    for name in skills.SKILLS:
        text = (root / name / "SKILL.md").read_text()
        assert text.startswith(f"---\nname: {name}\ndescription: ")
        assert f"lodestar.interfaces.skills {name}" in text
        assert "Paper trading only" in text
