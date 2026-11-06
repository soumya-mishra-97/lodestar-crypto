"""Run any trader skill outside the app: no database, no worker, JSON on stdout.

    python -m lodestar.interfaces.skills <skill> [--coin ID] [options]

Used by the Claude skills in skills/<name>/SKILL.md. Every number in the output comes
from code over provider data (demo data when no CoinGecko key is configured).
Paper trading only: nothing here can place an order.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lodestar.application.pipeline.react import AnalystPolicy, ScriptedPolicy
from lodestar.application.ports import DataSources
from lodestar.application.trading.analysts import TRADE_ANALYSTS
from lodestar.application.trading.common import TradingPrefs, load_bars
from lodestar.application.trading.coordinator import build_trade_plan, collect, run_analyst
from lodestar.application.trading.engines import (
    AccountContext,
    backtester,
    risk_position_sizer,
    scenario_stats_engine,
    timing_agent,
)
from lodestar.config import get_settings
from lodestar.domain.evidence import Evidence, EvidenceBundle
from lodestar.domain.models import Asset
from lodestar.domain.trading.bars import Bars
from lodestar.domain.trading.plan import TRADE_DISCLAIMER, TradePlanDraft, verify_trade_plan
from lodestar.domain.trading.scanner import scan_metrics
from lodestar.infrastructure.container import build_sources
from lodestar.infrastructure.http import ResilientHttp
from lodestar.infrastructure.observability.logging import configure_logging

SKILLS = (
    "market-scanner",
    "news-event-scout",
    "sentiment-reader",
    "fundamentals-analyst",
    "technical-analyst",
    "liquidity-checker",
    "timing-agent",
    "scenario-stats-engine",
    "risk-position-sizer",
    "backtester-paper-trader",
    "report-verifier",
    "trade-plan",
)
ANALYST_BY_SKILL = {a.name.replace("_", "-"): a for a in TRADE_ANALYSTS}
PLANS = {a.name: a.scripted_plan() for a in TRADE_ANALYSTS}


class NullCache:
    async def get_json(self, key: str) -> Any | None:
        return None

    async def set_json(self, key: str, value: Any, ttl_seconds: int) -> None:
        return None

    async def delete(self, key: str) -> None:
        return None


class UtcClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


def scripted(name: str) -> AnalystPolicy:
    return ScriptedPolicy(PLANS[name])


def evidence_json(items: list[Evidence] | tuple[Evidence, ...]) -> list[dict[str, Any]]:
    return [e.to_dict() for e in items]


async def resolve(sources: DataSources, coin: str) -> Asset:
    profile = await sources.market.get_profile(coin)
    return Asset(
        uuid.uuid5(uuid.NAMESPACE_URL, f"lodestar:{profile.coingecko_id}"),
        profile.coingecko_id,
        profile.symbol,
        profile.name,
    )


async def run_skill(args: argparse.Namespace, sources: DataSources) -> dict[str, Any]:
    prefs = TradingPrefs(
        max_loss_pct=args.max_loss_pct,
        horizon_days=args.horizon,
        fee_bps=args.fee_bps,
        slippage_bps=args.slippage_bps,
        min_volume_usd=args.min_volume_usd,
    )
    now = UtcClock().now()
    skill = args.skill
    out: dict[str, Any] = {"skill": skill, "data_mode": sources.mode, "generated_at": now.isoformat()}

    if skill == "market-scanner":
        listings = await sources.market.top_markets(args.top_n)
        btc = (await sources.market.get_history("bitcoin", 120)).closes
        rows = []
        for m in listings:
            try:
                bars = Bars.from_history(await sources.market.get_history(m.coingecko_id, 120))
                metrics = scan_metrics(bars, btc, volume_24h_usd=m.volume_24h_usd, min_volume_usd=prefs.min_volume_usd)
                rows.append({"coingecko_id": m.coingecko_id, "symbol": m.symbol, **metrics.to_dict()})
            except Exception as exc:  # noqa: BLE001 - report per-coin failures, keep scanning
                rows.append({"coingecko_id": m.coingecko_id, "symbol": m.symbol, "error": str(exc)[:200]})
        rows.sort(key=lambda r: (r.get("score") is None, not r.get("passes_liquidity"), -(r.get("score") or 0)))
        return out | {"ranked": rows, "note": "A high score is a reason to look closer, not a signal on its own."}

    if skill == "report-verifier":
        doc = json.loads(await asyncio.to_thread(Path(args.file).read_text))
        draft = TradePlanDraft.from_dict(doc["draft"])
        result = verify_trade_plan(draft, EvidenceBundle.from_dicts(doc["evidence"]))
        return out | {"verification": result.to_dict(), "disclaimer_expected": TRADE_DISCLAIMER}

    asset = await resolve(sources, args.coin)
    out["asset"] = {"coingecko_id": asset.coingecko_id, "symbol": asset.symbol, "name": asset.name}
    account = AccountContext(args.account, {})

    if skill == "trade-plan":
        plan = await build_trade_plan(sources, asset, prefs, account, scripted, now)
        return out | {
            "card": plan.card(),
            "draft": plan.draft.to_dict(),
            "verification": plan.verification.to_dict(),
            "evidence": evidence_json(plan.evidence),
            "disclaimer": TRADE_DISCLAIMER,
        }

    data = await collect(sources, asset, prefs, now, polymarket=True, tolerance_pct=1.5)
    if skill in ANALYST_BY_SKILL:
        analysis = await run_analyst(ANALYST_BY_SKILL[skill], asset, data, scripted, max_steps=6, now=now)
        cited = {i for c in analysis.claims for i in c.evidence_ids}
        return out | {
            "claims": [c.to_dict() for c in analysis.claims],
            "signals": [s.to_dict() for s in analysis.signals],
            "evidence": evidence_json([*analysis.evidence, *(e for e in data.evidence if e.id in cited)]),
        }
    levels, timing = timing_agent(data.bars, now)
    if skill == "timing-agent":
        return out | {"timing": timing.result, "evidence": evidence_json(timing.evidence)}
    if skill == "scenario-stats-engine":
        scen = scenario_stats_engine(data.bars, levels.kind, prefs, now)
        return out | {"scenarios": scen.result, "evidence": evidence_json(scen.evidence)}
    if skill == "risk-position-sizer":
        sizing = risk_position_sizer(
            data.bars,
            levels,
            data.bundle,
            data.btc_closes,
            account,
            prefs,
            data.reconciliation.status == "mismatch",
            now,
            data.bundle.order_book,
        )
        return out | {
            "timing": timing.result,
            "sizing": sizing.result,
            "evidence": evidence_json([*timing.evidence, *sizing.evidence]),
        }
    if skill == "backtester-paper-trader":
        bars = await load_bars(sources, asset)
        _, bt = backtester(bars, levels.kind, prefs, now)
        return out | {
            "backtest": bt.result,
            "evidence": evidence_json(bt.evidence),
            "paper_trading": "Use the app's Paper screen; Lodestar never places real orders.",
        }
    raise SystemExit(f"unknown skill {skill}")


async def main_async(args: argparse.Namespace) -> dict[str, Any]:
    settings = get_settings()
    http = ResilientHttp()
    try:
        sources = build_sources(settings, http, NullCache(), UtcClock())
        result = await run_skill(args, sources)
        result.setdefault("disclaimer", TRADE_DISCLAIMER)
        return result
    finally:
        await http.aclose()


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="lodestar-skills", description="Run a Lodestar trader skill and print JSON.")
    p.add_argument("skill", choices=SKILLS)
    p.add_argument("--coin", default="polygon-ecosystem-token", help="CoinGecko id (default: polygon-ecosystem-token)")
    p.add_argument("--top-n", type=int, default=20)
    p.add_argument("--account", type=float, default=10_000.0, help="Paper account size in USD for sizing")
    p.add_argument("--max-loss-pct", type=float, default=1.0)
    p.add_argument("--horizon", type=int, default=14)
    p.add_argument("--fee-bps", type=float, default=10.0)
    p.add_argument("--slippage-bps", type=float, default=5.0)
    p.add_argument("--min-volume-usd", type=float, default=5_000_000.0)
    p.add_argument("--file", help="report-verifier: JSON with 'draft' and 'evidence' (e.g. trade-plan output)")
    return p


Runner = Callable[[argparse.Namespace], Coroutine[Any, Any, dict[str, Any]]]


def main(argv: list[str] | None = None, runner: Runner = main_async) -> int:
    args = parser().parse_args(argv)
    configure_logging("ERROR", json_logs=False)
    result = asyncio.run(runner(args))
    json.dump(result, sys.stdout, indent=1, default=str)
    sys.stdout.write("\n")
    verification = result.get("verification")
    return 1 if isinstance(verification, dict) and not verification.get("passed", True) else 0


if __name__ == "__main__":
    sys.exit(main())
