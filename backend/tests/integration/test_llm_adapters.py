"""The Claude adapters against a fake Messages API: protocol handling, pre-screening, fallback."""

import json
import re
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import anthropic
import httpx

from lodestar.application.pipeline.writer import TemplateReportWriter
from lodestar.domain.models import RunStatus
from lodestar.infrastructure.llm.anthropic_agents import (
    ClaudeAnalystPolicy,
    ClaudeReportWriter,
    ClaudeSettings,
    FallbackWriter,
)
from tests.fakes import build_test_env

CFG = ClaudeSettings(
    api_key="test", model="claude-opus-5-5", effort="medium", max_tokens=4000, timeout_seconds=5, server_fallbacks=True
)


def usage() -> SimpleNamespace:
    return SimpleNamespace(input_tokens=10, output_tokens=5, cache_read_input_tokens=0)


def tool_use(id_: str, name: str, payload: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=id_, name=name, input=payload)


class FakeMessages:
    """Turn 1: look at evidence. Turn 2: submit one valid and one invalid claim."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    async def create(self, **request: Any) -> SimpleNamespace:
        self.requests.append(request)
        messages = request["messages"]
        if len(messages) == 1:
            content = [tool_use("t1", "list_evidence", {"prefix": "DAT"})]
            return SimpleNamespace(content=content, stop_reason="tool_use", usage=usage(), _request_id="r1")
        first = messages[0]["content"]
        catalogue = json.loads(re.search(r"<collected_evidence>\n(.*)\n</collected_evidence>", first, re.S).group(1))
        price = next(e for e in catalogue if e["label"] == "Current price (USD)")
        claims = [
            {"text": f"Price is ${price['value']:.4g}.", "tag": "fact", "evidence_ids": [price["id"]]},
            {"text": "Price will reach $10 next month.", "tag": "scenario", "evidence_ids": [price["id"]]},
        ]
        content = [tool_use("t2", "submit_findings", {"summary": "Looked at price.", "claims": claims})]
        return SimpleNamespace(content=content, stop_reason="tool_use", usage=usage(), _request_id="r2")


async def test_claude_policy_drives_the_react_loop_and_bad_claims_are_dropped() -> None:
    fake = FakeMessages()
    client = SimpleNamespace(messages=fake)
    env = await build_test_env(policies=lambda name: ClaudeAnalystPolicy(client, CFG))  # type: ignore[arg-type]
    owner = (await env.container.auth.ensure_local_owner()).id
    out = await env.container.onboarding.add("polygon-ecosystem-token", owner)
    run = await env.container.pipeline.get(UUID(out["run"]["id"]))
    assert run["status"] == RunStatus.AWAITING_APPROVAL

    report = await env.container.reports.get(UUID(run["report_id"]))
    for name in ("technical", "fundamental", "sentiment", "risk"):
        a = report["content"]["analysts"][name]
        assert (a["claims_source"], a["dropped_claims"], a["tool_calls"]) == ("llm", 1, 1)

    second = fake.requests[1]
    tool_result = second["messages"][2]["content"][0]
    assert tool_result["type"] == "tool_result"
    assert tool_result["tool_use_id"] == "t1"
    assert second["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert second["extra_body"] == {"fallbacks": "default"}
    assert {t["name"] for t in second["tools"]} >= {"list_evidence", "submit_findings"}
    notes = [e["payload"]["message"] for e in run["events"] if e["type"] == "note"]
    assert any("failed pre-verification" in n for n in notes)


class RateLimited:
    async def parse(self, **_: Any) -> Any:
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        raise anthropic.RateLimitError("slow down", response=httpx.Response(429, request=request), body=None)


async def test_writer_outage_falls_back_to_the_deterministic_writer() -> None:
    writer = FallbackWriter(ClaudeReportWriter(SimpleNamespace(messages=RateLimited()), CFG), TemplateReportWriter())  # type: ignore[arg-type]
    env = await build_test_env(writer=writer)
    owner = (await env.container.auth.ensure_local_owner()).id
    out = await env.container.onboarding.add("bitcoin", owner)
    run = await env.container.pipeline.get(UUID(out["run"]["id"]))
    report = await env.container.reports.get(UUID(run["report_id"]))
    assert report["content"]["draft"]["writer"] == "deterministic (LLM unavailable)"
    assert report["content"]["verification"]["passed"]
