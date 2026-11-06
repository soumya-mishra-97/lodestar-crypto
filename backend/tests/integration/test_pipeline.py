"""The LangGraph pipeline end to end over demo data: every acceptance-critical path."""

from dataclasses import replace
from typing import Any
from uuid import UUID

from lodestar.domain.claims import Claim, ClaimTag
from lodestar.domain.evidence import EvidenceBundle
from lodestar.domain.models import ReportStatus, RunStatus
from lodestar.domain.report import DISCLAIMER, HorizonNarrative, ReportDraft
from tests.fakes import BrokenPolicy, PipelineEnv, ScriptedWriter, build_test_env

POL = "polygon-ecosystem-token"
ANALYSTS = ("technical", "fundamental", "sentiment", "risk")


async def start(env: PipelineEnv, coin: str = POL) -> dict[str, Any]:
    owner = (await env.container.auth.ensure_local_owner()).id
    out = await env.container.onboarding.add(coin, owner)
    return await env.container.pipeline.get(UUID(out["run"]["id"]))


def steps(run: dict[str, Any], kind: str = "step") -> list[tuple[str, str]]:
    return [(e["step"], e["status"]) for e in run["events"] if e["type"] == kind]


async def test_adding_pol_runs_the_full_pipeline_to_a_verified_report() -> None:
    env = await build_test_env()
    run = await start(env)

    assert run["status"] == RunStatus.AWAITING_APPROVAL
    seqs = [e["seq"] for e in run["events"]]
    assert seqs == list(range(1, len(seqs) + 1))  # gap-free, strictly increasing
    completed = [s for s, status in steps(run) if status == "completed"]
    assert completed[0] == "data"
    assert set(completed[1:5]) == set(ANALYSTS)  # the parallel fan-out
    assert completed[5:] == ["portfolio", "report_writer", "verifier"]
    assert ("human_approval", "waiting") in steps(run)

    tool_calls = [e for e in run["events"] if e["type"] == "tool_call"]
    assert {e["step"] for e in tool_calls} == set(ANALYSTS)
    assert all(e["payload"]["react_step"] <= e["payload"]["max_steps"] for e in tool_calls)
    for e in run["events"]:
        if e["type"] == "step" and e["status"] == "completed" and e["step"] in ("data", *ANALYSTS):
            assert e["payload"]["evidence_ids"], e["step"]  # every producing step reports its evidence ids

    report = await env.container.reports.get(UUID(run["report_id"]))
    c = report["content"]
    assert report["status"] == ReportStatus.PENDING_APPROVAL
    assert c["verification"]["passed"]
    assert c["verification"]["repairs"] == 0
    assert c["disclaimer"] == DISCLAIMER
    for horizon in ("short_term", "long_term"):
        assessment = c["assessments"][horizon]
        assert assessment["risk"]["level"] in ("low", "moderate", "high", "very_high")
        assert any(c["draft"][horizon].values())

    # Every claim is tagged and every cited id resolves to registered evidence.
    bundle = EvidenceBundle.from_dicts(c["evidence"])
    draft = ReportDraft.from_dict(c["draft"])
    for claim in draft.all_claims():
        assert claim.tag in ClaimTag
        assert set(claim.evidence_ids) <= bundle.ids()
    assert {e.id.split("-")[0] for e in bundle.items} >= {"DAT", "TEC", "FUN", "SEN", "RSK", "ASM", "PF", "NWS"}


async def test_approval_resumes_the_graph_and_publishes() -> None:
    env = await build_test_env()
    run = await start(env)
    owner = (await env.container.auth.ensure_local_owner()).id
    report = await env.container.pipeline.decide(
        UUID(run["report_id"]), approved=True, note="looks right", user_id=owner
    )
    assert report.status is ReportStatus.APPROVED
    after = await env.container.pipeline.get(UUID(run["id"]))
    assert after["status"] == RunStatus.APPROVED
    assert ("human_approval", "completed") in steps(after)
    # The resumed graph re-applies the decision idempotently: exactly one terminal run event.
    assert [s for s, status in steps(after, "run") if status == "approved"] == ["run"]


async def test_rejection_keeps_the_report_out_of_the_overview() -> None:
    env = await build_test_env()
    run = await start(env)
    owner = (await env.container.auth.ensure_local_owner()).id
    await env.container.pipeline.decide(UUID(run["report_id"]), approved=False, note=None, user_id=owner)
    overview = await env.container.overview.overview(owner)
    assert overview["latest_report"] is None
    assert (await env.container.pipeline.get(UUID(run["id"])))["status"] == RunStatus.REJECTED


def _break(draft: ReportDraft) -> ReportDraft:
    bad = Claim("Price will reach $5 soon, guaranteed.", ClaimTag.SCENARIO, ("DAT-01",))
    return replace(draft, short_term=replace(draft.short_term, watch=(bad, *draft.short_term.watch)))


async def test_repair_loop_feeds_findings_back_and_recovers() -> None:
    writer = ScriptedWriter(_break, _break)  # fails twice, the third attempt (2nd repair) is clean
    env = await build_test_env(writer=writer)
    run = await start(env)
    assert run["status"] == RunStatus.AWAITING_APPROVAL
    assert writer.feedback_seen[0] == []
    assert any("price target" in f for f in writer.feedback_seen[1])
    verifier = [e for e in run["events"] if e["step"] == "verifier" and e["status"] == "completed"]
    assert [e["payload"]["outputs"]["passed"] for e in verifier] == [False, False, True]
    report = await env.container.reports.get(UUID(run["report_id"]))
    assert report["content"]["verification"]["repairs"] == 2


async def test_fails_closed_after_two_repairs() -> None:
    env = await build_test_env(writer=ScriptedWriter(_break, _break, _break))
    run = await start(env)
    assert run["status"] == RunStatus.FAILED
    assert "fail closed" in run["error"]
    assert run["report_id"] is None  # nothing reaches a human
    assert ("fail_closed", "failed") in steps(run)
    assert not env.store.reports


async def test_missing_disclaimer_is_caught() -> None:
    env = await build_test_env(writer=ScriptedWriter(*[lambda d: replace(d, disclaimer="")] * 3))
    run = await start(env)
    assert run["status"] == RunStatus.FAILED


async def test_model_outage_degrades_to_deterministic_findings() -> None:
    env = await build_test_env(policies=lambda name: BrokenPolicy())
    run = await start(env)
    assert run["status"] == RunStatus.AWAITING_APPROVAL
    report = await env.container.reports.get(UUID(run["report_id"]))
    for name in ANALYSTS:
        a = report["content"]["analysts"][name]
        assert (a["stop_reason"], a["claims_source"]) == ("policy_error", "template")


async def test_price_mismatch_is_flagged_as_evidence_and_risk() -> None:
    env = await build_test_env()
    run = await start(env, "chainlink")  # demo data carries a deliberate cross-source gap
    notes = [e["payload"]["message"] for e in run["events"] if e["type"] == "note"]
    assert any("Price mismatch" in n for n in notes)
    report = await env.container.reports.get(UUID(run["report_id"]))
    c = report["content"]
    assert c["reconciliation"]["status"] == "mismatch"
    factors = {f["name"] for f in c["assessments"]["short_term"]["risk"]["factors"]}
    assert "data_disagreement" in factors


async def test_portfolio_context_and_unknown_coin() -> None:
    env = await build_test_env()
    owner = (await env.container.auth.ensure_local_owner()).id
    asset = await env.container.assets.track(POL)
    await env.container.portfolio.upsert(owner, asset.id, quantity=10_000, avg_cost_usd=0.2, notes=None)
    run = await start(env)
    report = await env.container.reports.get(UUID(run["report_id"]))
    assert report["content"]["portfolio"]["held"] is True
    texts = [c["text"] for c in report["content"]["draft"]["portfolio"]]
    assert any(t.startswith("You hold 10,000 POL") for t in texts)


async def test_in_flight_runs_are_deduplicated_and_daily_queues_watchlist() -> None:
    env = await build_test_env()
    owner = (await env.container.auth.ensure_local_owner()).id
    asset = await env.container.assets.track(POL)
    await env.container.watchlist.add(owner, asset.id)
    env.queue.bind(lambda run_id: _noop(), env.container.pipeline.resume)  # leave runs queued
    first, created = await env.container.pipeline.request(asset.id, owner)
    again, created_again = await env.container.pipeline.request(asset.id, owner)
    assert created
    assert not created_again
    assert first.id == again.id
    assert await env.container.pipeline.queue_daily() == 0  # already in flight


async def _noop() -> None:
    return None


async def test_template_writer_output_is_always_verifiable_for_every_demo_coin() -> None:
    env = await build_test_env()
    for coin in ("bitcoin", "ethereum", "solana", "dogecoin", "arbitrum", "near"):
        run = await start(env, coin)
        assert run["status"] == RunStatus.AWAITING_APPROVAL, (coin, run["error"])


def test_narrative_sections_round_trip() -> None:
    n = HorizonNarrative(thesis=(Claim("a", ClaimTag.ASSUMPTION),))
    assert HorizonNarrative.from_dict(n.to_dict()) == n


async def test_a_lost_task_does_not_block_the_asset_forever() -> None:
    env = await build_test_env()
    owner = (await env.container.auth.ensure_local_owner()).id
    asset = await env.container.assets.track(POL)
    env.queue.bind(lambda run_id: _noop(), env.container.pipeline.resume)  # the task is "lost"
    lost, _ = await env.container.pipeline.request(asset.id, owner)
    env.clock.advance(minutes=16)
    env.queue.bind(env.container.pipeline.execute, env.container.pipeline.resume)
    fresh, created = await env.container.pipeline.request(asset.id, owner)
    assert created
    assert fresh.id != lost.id
    assert (await env.container.pipeline.get(lost.id))["status"] == RunStatus.FAILED
    assert (await env.container.pipeline.get(fresh.id))["status"] == RunStatus.AWAITING_APPROVAL
