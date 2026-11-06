"""Claude adapters: the ReAct analyst policy and the report writer.

- The analyst policy only chooses actions; the loop, the step limit and every tool
  live in application code. Tools are read-only and compute in code.
- The writer returns schema-constrained output; the verifier decides what ships.
- Static, cache-controlled system prompts; server-side refusal fallbacks (configurable).
- Every API failure becomes LlmUnavailable, which the pipeline handles explicitly.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import replace
from typing import Any, Literal

import anthropic
import structlog
from pydantic import BaseModel, Field

from lodestar.application.pipeline.react import AgentBrief, FinalAnswer, StepRecord, ToolCall, ToolSpec
from lodestar.application.pipeline.writer import ReportWriter, WriterInput
from lodestar.domain.claims import Claim, ClaimTag
from lodestar.domain.errors import LlmUnavailable
from lodestar.domain.report import DISCLAIMER, HorizonNarrative, ReportDraft
from lodestar.infrastructure.llm.prompts import (
    ANALYST_SYSTEM_PROMPT,
    PROMPT_VERSION,
    WRITER_SYSTEM_PROMPT,
    analyst_user_message,
    writer_user_message,
)

log = structlog.get_logger(__name__)

TAGS = [t.value for t in ClaimTag]
SUBMIT = "submit_findings"
CLAIM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "tag": {"type": "string", "enum": TAGS},
        "evidence_ids": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["text", "tag", "evidence_ids"],
    "additionalProperties": False,
}
SUBMIT_TOOL: dict[str, Any] = {
    "name": SUBMIT,
    "description": "Submit your final findings (three to six claims). Call exactly once, as your last action.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "One sentence: what you investigated"},
            "claims": {"type": "array", "items": CLAIM_SCHEMA},
        },
        "required": ["summary", "claims"],
        "additionalProperties": False,
    },
}


class ClaudeSettings(BaseModel):
    api_key: str | None
    model: str
    effort: str
    max_tokens: int
    timeout_seconds: float
    server_fallbacks: bool


def make_client(cfg: ClaudeSettings) -> anthropic.AsyncAnthropic:
    return anthropic.AsyncAnthropic(api_key=cfg.api_key, timeout=cfg.timeout_seconds, max_retries=2)


def _extras(cfg: ClaudeSettings) -> dict[str, Any]:
    if not cfg.server_fallbacks:
        return {}
    # On a policy refusal the API re-runs the request on a fallback model within the same call.
    return {
        "extra_headers": {"anthropic-beta": "server-side-fallback-2026-07-01"},
        "extra_body": {"fallbacks": "default"},
    }


def _translate(exc: anthropic.APIError) -> LlmUnavailable:
    if isinstance(exc, anthropic.RateLimitError):
        return LlmUnavailable("LLM rate limited")
    if isinstance(exc, anthropic.BadRequestError):
        log.error("llm_bad_request", error=exc.message)
        return LlmUnavailable("LLM rejected the request")
    if isinstance(exc, anthropic.APIStatusError):
        return LlmUnavailable(f"LLM API error {exc.status_code}")
    return LlmUnavailable("LLM unreachable")


def _claims(raw: Sequence[Any]) -> tuple[Claim, ...]:
    out = []
    for c in raw:
        try:
            out.append(Claim.from_dict(c if isinstance(c, dict) else c.model_dump()))
        except (KeyError, ValueError, TypeError):
            continue
    return tuple(out)


class ClaudeAnalystPolicy:
    """Stateful for one analyst run: holds the conversation, appends tool results each step."""

    def __init__(self, client: anthropic.AsyncAnthropic, cfg: ClaudeSettings) -> None:
        self._client, self._cfg = client, cfg
        self._messages: list[dict[str, Any]] = []
        self._pending: list[str] = []  # tool_use ids from the last assistant turn

    async def decide(
        self, brief: AgentBrief, tools: Sequence[ToolSpec], history: Sequence[StepRecord]
    ) -> list[ToolCall] | FinalAnswer:
        if not self._messages:
            self._messages.append({"role": "user", "content": analyst_user_message(brief)})
        elif self._pending:
            results = {call.id: res for call, res in history[-1].calls} if history else {}
            blocks = []
            for tool_use_id in self._pending:
                res = results.get(tool_use_id)
                content = res.content if res else {"error": "not executed: too many calls in one step"}
                blocks.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": _json(content),
                        "is_error": bool(res.is_error) if res else True,
                    }
                )
            remaining = brief.max_steps - len(history)
            if remaining <= 1:
                blocks.append({"type": "text", "text": f"Step limit reached: call {SUBMIT} now."})
            self._messages.append({"role": "user", "content": blocks})
            self._pending = []

        tool_defs = [{"name": t.name, "description": t.description, "input_schema": t.input_schema} for t in tools]
        try:
            request: dict[str, Any] = {
                "model": self._cfg.model,
                "max_tokens": self._cfg.max_tokens,
                "system": [{"type": "text", "text": ANALYST_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
                "tools": [*tool_defs, SUBMIT_TOOL],
                "messages": self._messages,
                "output_config": {"effort": self._cfg.effort},
                **_extras(self._cfg),
            }
            response = await self._client.messages.create(**request)
        except anthropic.APIError as exc:
            raise _translate(exc) from exc

        log.info(
            "llm_call",
            role=f"analyst:{brief.analyst}",
            request_id=response._request_id,
            stop_reason=response.stop_reason,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cache_read_tokens=response.usage.cache_read_input_tokens,
        )
        if response.stop_reason == "refusal":
            raise LlmUnavailable("LLM declined the request")
        if response.stop_reason == "max_tokens":
            raise LlmUnavailable("LLM output truncated")
        self._messages.append({"role": "assistant", "content": response.content})

        uses = [b for b in response.content if b.type == "tool_use"]
        submit = next((b for b in uses if b.name == SUBMIT), None)
        if submit is not None:
            data = submit.input if isinstance(submit.input, dict) else {}
            return FinalAnswer(claims=_claims(data.get("claims") or []), summary=str(data.get("summary", ""))[:300])
        if not uses:
            return FinalAnswer(claims=None, summary="The model ended without submitting findings")
        self._pending = [b.id for b in uses]
        return [ToolCall(id=b.id, name=b.name, args=b.input if isinstance(b.input, dict) else {}) for b in uses]


def _json(value: Any) -> str:
    return json.dumps(value, default=str, ensure_ascii=True)


# ---------------------------------------------------------------- writer


class ClaimOut(BaseModel):
    text: str = Field(description="One plain-English sentence, at most 35 words")
    tag: Literal["fact", "calculation", "interpretation", "scenario", "assumption"]
    evidence_ids: list[str]


class HorizonOut(BaseModel):
    thesis: list[ClaimOut]
    opportunities: list[ClaimOut]
    risks: list[ClaimOut]
    watch: list[ClaimOut]


class DraftOut(BaseModel):
    headline: ClaimOut
    short_term: HorizonOut
    long_term: HorizonOut
    portfolio: list[ClaimOut]
    data_quality: list[ClaimOut]
    uncertainties: list[ClaimOut]


def _c(c: ClaimOut) -> Claim:
    return Claim(c.text.strip(), ClaimTag(c.tag), tuple(dict.fromkeys(c.evidence_ids)))


def _h(h: HorizonOut) -> HorizonNarrative:
    return HorizonNarrative(
        thesis=tuple(map(_c, h.thesis)),
        opportunities=tuple(map(_c, h.opportunities)),
        risks=tuple(map(_c, h.risks)),
        watch=tuple(map(_c, h.watch)),
    )


class ClaudeReportWriter:
    def __init__(self, client: anthropic.AsyncAnthropic, cfg: ClaudeSettings) -> None:
        self._client, self._cfg = client, cfg

    @property
    def name(self) -> str:
        return f"{self._cfg.model} ({PROMPT_VERSION})"

    async def write(self, inp: WriterInput, feedback: Sequence[str] = ()) -> ReportDraft:
        try:
            request: dict[str, Any] = {
                "model": self._cfg.model,
                "max_tokens": self._cfg.max_tokens,
                "system": [{"type": "text", "text": WRITER_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
                "messages": [{"role": "user", "content": writer_user_message(inp, feedback)}],
                "output_config": {"effort": self._cfg.effort},
                **_extras(self._cfg),
            }
            response = await self._client.messages.parse(output_format=DraftOut, **request)
        except anthropic.APIError as exc:
            raise _translate(exc) from exc
        log.info(
            "llm_call",
            role="writer",
            request_id=response._request_id,
            stop_reason=response.stop_reason,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cache_read_tokens=response.usage.cache_read_input_tokens,
        )
        if response.stop_reason in ("refusal", "max_tokens") or response.parsed_output is None:
            raise LlmUnavailable(f"LLM writer produced no usable output ({response.stop_reason})")
        d = response.parsed_output
        return ReportDraft(
            headline=_c(d.headline),
            short_term=_h(d.short_term),
            long_term=_h(d.long_term),
            portfolio=tuple(map(_c, d.portfolio)),
            data_quality=tuple(map(_c, d.data_quality)),
            uncertainties=tuple(map(_c, d.uncertainties)),
            disclaimer=DISCLAIMER,  # attached by code, checked by the verifier
            writer=self.name,
        )


class FallbackWriter:
    """Use the primary (LLM) writer; if the model is unavailable, the deterministic writer.

    The verifier checks either draft the same way, so a fallback never weakens verification.
    """

    def __init__(self, primary: ReportWriter, fallback: ReportWriter) -> None:
        self._primary, self._fallback = primary, fallback

    @property
    def name(self) -> str:
        return self._primary.name

    async def write(self, inp: WriterInput, feedback: Sequence[str] = ()) -> ReportDraft:
        try:
            return await self._primary.write(inp, feedback)
        except LlmUnavailable as exc:
            log.warning("writer_fallback", error=str(exc))
            draft = await self._fallback.write(inp, feedback)
            return replace(draft, writer=f"{self._fallback.name} (LLM unavailable)")
