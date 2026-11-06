"""HTTP API over in-memory adapters: the user journeys behind each screen."""

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from lodestar.interfaces.http.app import create_app
from tests.fakes import PipelineEnv, build_test_env

API = "/api/v1"
PASSWORD = "correct-horse-battery-staple"
POL = "polygon-ecosystem-token"


async def _client(env: PipelineEnv) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(env.container.settings, env.container)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
async def env() -> PipelineEnv:
    return await build_test_env()


@pytest.fixture
async def client(env: PipelineEnv) -> AsyncIterator[httpx.AsyncClient]:
    async for c in _client(env):
        yield c


async def add_pol(client: httpx.AsyncClient) -> dict[str, Any]:
    r = await client.post(f"{API}/assets", json={"coingecko_id": POL})
    assert r.status_code == 201, r.text
    return r.json()


def parse_sse(text: str) -> list[dict[str, Any]]:
    events = []
    for block in text.split("\n\n"):
        data = [line[6:] for line in block.splitlines() if line.startswith("data: ")]
        if data and data[0] != "{}":
            events.append(json.loads(data[0]))
    return events


async def test_health_session_and_security_headers(client: httpx.AsyncClient) -> None:
    r = await client.get("/health/live")
    assert r.status_code == 200
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    s = (await client.get(f"{API}/session")).json()
    assert s == {
        "auth_mode": "local",
        "authenticated": True,
        "data_mode": "demo",
        "demo": True,
        "llm_mode": "deterministic",
    }


async def test_add_coin_starts_a_visible_run_ending_in_a_verified_report(client: httpx.AsyncClient) -> None:
    body = await add_pol(client)
    assert (body["asset"]["symbol"], body["asset"]["name"]) == ("POL", "POL (ex-MATIC)")
    run_id = body["run"]["id"]

    # Live stream (here: replay, the inline queue already finished the run) carries every step.
    r = await client.get(f"{API}/runs/{run_id}/events")
    assert r.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(r.text)
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    assert events[-1]["type"] == "run"
    assert events[-1]["status"] == "awaiting_approval"
    assert "event: end" in r.text

    # Resuming from Last-Event-ID only sends what was missed.
    r = await client.get(f"{API}/runs/{run_id}/events", headers={"Last-Event-ID": str(len(events) - 2)})
    assert [e["seq"] for e in parse_sse(r.text)] == [len(events) - 1, len(events)]

    run = (await client.get(f"{API}/runs/{run_id}")).json()
    assert run["status"] == "awaiting_approval"
    assert run["report_id"]
    assert run["asset"]["symbol"] == "POL"

    report = (await client.get(f"{API}/reports/{run['report_id']}")).json()
    assert report["status"] == "pending_approval"
    assert report["content"]["verification"]["passed"] is True

    r = await client.post(f"{API}/reports/{run['report_id']}/approve", json={"note": "checked"})
    assert r.status_code == 200
    assert r.json()["status"] == "approved"
    assert (await client.post(f"{API}/reports/{run['report_id']}/reject", json={})).status_code == 409
    assert (await client.get(f"{API}/runs/{run_id}")).json()["status"] == "approved"


async def test_overview_is_populated(client: httpx.AsyncClient) -> None:
    asset = (await add_pol(client))["asset"]
    r = await client.put(
        f"{API}/portfolio/holdings", json={"asset_id": asset["id"], "quantity": 20000, "avg_cost_usd": 0.25}
    )
    assert r.status_code == 204
    o = (await client.get(f"{API}/overview")).json()
    assert o["data_mode"] == "demo"
    assert o["portfolio"]["total_value_usd"] > 0
    assert o["allocation"][0]["asset"]["symbol"] == "POL"
    assert o["risk"]["long_term"]["level"] in ("low", "moderate", "high", "very_high")
    assert o["watchlist"][0]["latest_report"]["status"] == "pending_approval"
    assert len(o["watchlist"][0]["sparkline"]) == 30
    assert o["latest_report"]["asset"]["symbol"] == "POL"
    assert o["recent_runs"][0]["status"] == "awaiting_approval"


async def test_coin_detail_chart_has_candles_and_indicators(client: httpx.AsyncClient) -> None:
    asset = (await add_pol(client))["asset"]
    chart = (await client.get(f"{API}/assets/{asset['id']}/chart", params={"days": 90})).json()
    assert len(chart["candles"]) == 90
    assert chart["candle_source"] == "demo-exchange"
    candle = chart["candles"][-1]
    assert candle["l"] <= min(candle["o"], candle["c"]) <= max(candle["o"], candle["c"]) <= candle["h"]
    ind = chart["indicators"]
    assert len(ind["sma_200"]) == 90
    assert len(ind["rsi_14"]) == 90
    assert all(0 <= p["v"] <= 100 for p in ind["rsi_14"])
    report = (await client.get(f"{API}/assets/{asset['id']}/report")).json()
    assert set(report["content"]["assessments"]) == {"short_term", "long_term"}


async def test_reports_list_and_export(client: httpx.AsyncClient) -> None:
    run = (await add_pol(client))["run"]
    report_id = (await client.get(f"{API}/runs/{run['id']}")).json()["report_id"]
    listed = (await client.get(f"{API}/reports", params={"kind": "on_demand"})).json()
    assert [r["id"] for r in listed] == [report_id]
    assert (await client.get(f"{API}/reports", params={"kind": "daily"})).json() == []

    md = await client.get(f"{API}/reports/{report_id}/export.md")
    assert md.status_code == 200
    assert "attachment" in md.headers["content-disposition"]
    assert "DEMO DATA" in md.text
    assert "## Short term" in md.text
    assert "[CALC]" in md.text
    assert "not financial advice" in md.text

    pdf = await client.get(f"{API}/reports/{report_id}/export.pdf")
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")


async def test_portfolio_manual_csv_and_address_import(client: httpx.AsyncClient) -> None:
    csv = "symbol,quantity,avg_cost\nBTC,0.5,60000\nETH,2,\nNOPE,1,1\n"
    r = (await client.post(f"{API}/portfolio/import/csv", json={"content": csv})).json()
    assert [row["asset"]["symbol"] for row in r["imported"]] == ["BTC", "ETH"]
    assert r["errors"][0]["line"] == 4

    address = "0x" + "12" * 20
    r = await client.post(f"{API}/portfolio/import/address", json={"chain": "polygon", "address": address})
    assert r.status_code == 200
    assert r.json()["imported"][0]["asset"]["symbol"] == "POL"

    seed = "abandon " * 11 + "about"
    r = await client.post(f"{API}/portfolio/import/address", json={"chain": "ethereum", "address": seed})
    assert r.status_code == 422
    assert "seed phrase" in r.json()["detail"]

    p = (await client.get(f"{API}/portfolio")).json()
    assert {pos["asset"]["symbol"] for pos in p["positions"]} == {"BTC", "ETH", "POL"}
    pol = next(pos for pos in p["positions"] if pos["asset"]["symbol"] == "POL")
    assert pol["holdings"][0]["source_label"].startswith("Polygon wallet 0x1212")
    assert sum(pos["weight_pct"] for pos in p["positions"]) == pytest.approx(100)

    holding_id = pol["holdings"][0]["id"]
    assert (await client.delete(f"{API}/portfolio/holdings/{holding_id}")).status_code == 204
    assert len((await client.get(f"{API}/portfolio")).json()["positions"]) == 2


async def test_settings_view_and_update(client: httpx.AsyncClient) -> None:
    s = (await client.get(f"{API}/settings")).json()
    assert s["demo"] is True
    assert s["pipeline"]["max_repairs"] == 2
    assert s["pipeline"]["approval_required"]
    assert s["preferences"]["polymarket_enabled"] is True
    assert s["preferences"]["mismatch_tolerance_pct"] == 1.5
    assert s["preferences"]["max_loss_pct"] == 1.0
    r = await client.put(
        f"{API}/settings", json={"mismatch_tolerance_pct": 4, "polymarket_enabled": False, "max_loss_pct": 2}
    )
    prefs = r.json()["preferences"]
    assert (prefs["polymarket_enabled"], prefs["mismatch_tolerance_pct"], prefs["max_loss_pct"]) == (False, 4.0, 2.0)
    assert (await client.put(f"{API}/settings", json={"mismatch_tolerance_pct": 50})).status_code == 422


async def test_input_validation(client: httpx.AsyncClient) -> None:
    assert (await client.post(f"{API}/assets", json={"coingecko_id": "../../etc"})).status_code == 422
    assert (await client.post(f"{API}/assets", json={"coingecko_id": "bitcoin", "extra": 1})).status_code == 422
    r = await client.post(f"{API}/assets", json={"coingecko_id": "not-a-real-coin"})
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/problem+json")
    assert (await client.get(f"{API}/assets/search", params={"q": "<script>"})).status_code == 422


async def test_password_mode_requires_login() -> None:
    env = await build_test_env(auth_mode="password", allow_registration=False)
    async for client in _client(env):
        assert (await client.get(f"{API}/session")).json()["authenticated"] is False
        r = await client.get(f"{API}/overview")
        assert r.status_code == 401
        assert r.headers["content-type"].startswith("application/problem+json")

        r = await client.post(f"{API}/auth/register", json={"email": "me@example.com", "password": PASSWORD})
        assert r.status_code == 201
        assert r.json()["role"] == "owner"
        r = await client.post(f"{API}/auth/register", json={"email": "x@example.com", "password": PASSWORD})
        assert r.status_code == 403  # registration closes after the owner

        r = await client.post(f"{API}/auth/login", json={"email": "me@example.com", "password": "nope"})
        assert r.status_code == 401
        assert r.json()["detail"] == "Invalid credentials"
        r = await client.post(f"{API}/auth/login", json={"email": "me@example.com", "password": PASSWORD})
        assert "httponly" in r.headers["set-cookie"].lower()
        headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
        assert (await client.get(f"{API}/session", headers=headers)).json()["authenticated"] is True
        assert (await client.get(f"{API}/overview", headers=headers)).status_code == 200
