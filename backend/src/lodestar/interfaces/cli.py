"""Operational commands.

python -m lodestar.interfaces.cli seed       # first-run data: owner, watchlist, holdings, POL report
python -m lodestar.interfaces.cli run <coingecko-id>   # run the pipeline inline and print the outcome
python -m lodestar.interfaces.cli daily      # queue today's watchlist reports now
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from uuid import UUID

from lodestar.config import Settings, get_settings
from lodestar.domain.models import ReportKind
from lodestar.infrastructure.container import Container, build_container
from lodestar.infrastructure.observability.logging import configure_logging

SAMPLE_COIN = "polygon-ecosystem-token"
DEMO_WATCHLIST = ("polygon-ecosystem-token", "bitcoin", "ethereum", "solana", "chainlink")
LIVE_WATCHLIST = ("polygon-ecosystem-token", "bitcoin", "ethereum")
DEMO_HOLDINGS = {  # coingecko id -> (quantity, average cost in USD)
    "bitcoin": (0.42, 58_200.0),
    "ethereum": (5.5, 2_950.0),
    "polygon-ecosystem-token": (42_000.0, 0.31),
    "solana": (60.0, 142.0),
    "chainlink": (310.0, 16.4),
}


async def _owner_id(c: Container) -> UUID | None:
    """The account to seed for: the implicit owner in local mode (password mode: set up via the UI)."""
    if c.settings.auth_mode == "local":
        return (await c.auth.ensure_local_owner()).id
    return None


async def seed(settings: Settings) -> None:
    """Idempotent: seeds the watchlist/analysis data and the trader-skills data independently."""
    # Seed runs inline and unpaced: demo pacing only matters for someone watching live.
    c = await build_container(settings, queue="inline", with_workflow=True, pace=False)
    try:
        owner = await _owner_id(c)
        if owner is None:
            print("seed: skipped (password mode: create the owner account in the UI, then add coins)")
            return
        await _seed_analysis(c, owner)
        await _seed_trading(c, owner)
    finally:
        await c.aclose()


async def _seed_analysis(c: Container, owner: UUID) -> None:
    if await c.watchlist.list_assets(owner):
        print("seed: watchlist already seeded")
        return
    demo = c.sources.mode == "demo"
    coins = DEMO_WATCHLIST if demo else LIVE_WATCHLIST
    for coin in coins:
        asset = await c.assets.track(coin)
        await c.watchlist.add(owner, asset.id)
        if demo and coin in DEMO_HOLDINGS:
            qty, cost = DEMO_HOLDINGS[coin]
            await c.portfolio.upsert(owner, asset.id, quantity=qty, avg_cost_usd=cost, notes=None)
    print(f"seed: tracking {len(coins)} coins ({c.sources.mode} data)")
    for coin in coins if demo else (SAMPLE_COIN,):
        asset = await c.assets.track(coin)
        run, _ = await c.pipeline.request(asset.id, owner)
        status = await c.pipeline.status(run.id)
        print(f"seed: {asset.symbol} pipeline run {run.id} -> {status.value}")


async def _seed_trading(c: Container, owner: UUID) -> None:
    """Scanner run, trade plans for POL and the top of the shortlist, a backtest each, and (demo) a paper replay."""
    assert c.scans is not None  # noqa: S101 - wired by the container
    assert c.paper is not None  # noqa: S101
    if await c.scans.list(owner, limit=1):
        print("seed: trading already seeded")
        return
    demo = c.sources.mode == "demo"
    scan = await c.scans.request(owner, "top", 14 if demo else 20)
    shortlist = [r["coingecko_id"] for r in scan.get("results") or [] if r.get("shortlisted")]
    print(f"seed: scanner ranked {len(scan.get('results') or [])} coins, shortlist {len(shortlist)}")
    coins = list(dict.fromkeys([SAMPLE_COIN, *shortlist[: 2 if demo else 0]]))
    for coin in coins:
        asset = await c.assets.track(coin)
        run, _ = await c.pipeline.request(asset.id, owner, kind=ReportKind.TRADE_PLAN)
        print(f"seed: {asset.symbol} trade plan run {run.id} -> {(await c.pipeline.status(run.id)).value}")
    if demo:
        watched = await c.watchlist.list_assets(owner)
        created = await c.paper.seed_demo_replay(owner, watched[:3])
        print(f"seed: paper account replayed {created} demo plan(s) over synthetic history")
    else:
        await c.paper.account(owner)


async def run_one(settings: Settings, coingecko_id: str) -> int:
    c = await build_container(settings, queue="inline", with_workflow=True, pace=False)
    try:
        owner = await _owner_id(c)
        asset = await c.assets.track(coingecko_id)
        run, _ = await c.pipeline.request(asset.id, owner, force=True)
        detail = await c.pipeline.get(run.id)
        for e in detail["events"]:
            if e["type"] in ("step", "run"):
                print(f"{e['seq']:>3} {e['step']:<15} {e['status']}")
        print(f"run {run.id}: {detail['status']} (report {detail['report_id']})")
        return 0 if detail["status"] in ("awaiting_approval", "approved") else 1
    finally:
        await c.aclose()


async def daily(settings: Settings) -> None:
    c = await build_container(settings)
    try:
        print(f"queued {await c.pipeline.queue_daily()} run(s)")
    finally:
        await c.aclose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lodestar")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed")
    run = sub.add_parser("run")
    run.add_argument("coingecko_id", nargs="?", default=SAMPLE_COIN)
    sub.add_parser("daily")
    args = parser.parse_args(argv)
    settings = get_settings()
    configure_logging("WARNING", json_logs=settings.is_production)
    if args.command == "seed":
        asyncio.run(seed(settings))
        return 0
    if args.command == "run":
        return asyncio.run(run_one(settings, args.coingecko_id))
    asyncio.run(daily(settings))
    return 0


if __name__ == "__main__":
    sys.exit(main())
