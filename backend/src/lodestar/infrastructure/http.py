"""Shared async HTTP client with retries, backoff and a per-host circuit breaker.

One pooled httpx.AsyncClient per process (connection reuse, bounded memory).
Upstream failures surface as ProviderUnavailable, never as raw httpx errors.
"""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
import structlog

from lodestar.domain.errors import ProviderUnavailable

log = structlog.get_logger(__name__)
RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


@dataclass(slots=True)
class CircuitBreaker:
    """Opens after `threshold` consecutive failures; half-opens after `reset_after` seconds."""

    threshold: int = 5
    reset_after: float = 60.0
    failures: int = 0
    opened_at: float | None = field(default=None)

    def allow(self) -> bool:
        if self.opened_at is None:
            return True
        return time.monotonic() - self.opened_at >= self.reset_after  # half-open: allow a probe

    def success(self) -> None:
        self.failures, self.opened_at = 0, None

    def failure(self) -> None:
        self.failures += 1
        if self.failures >= self.threshold:
            self.opened_at = time.monotonic()


class ResilientHttp:
    def __init__(
        self,
        *,
        timeout: float = 15.0,
        max_retries: int = 3,
        user_agent: str = "lodestar/0.2 (+personal read-only research)",
        transport: httpx.AsyncBaseTransport | None = None,  # tests inject httpx.MockTransport
        backoff_seconds: float = 0.5,
    ) -> None:
        self._backoff = backoff_seconds
        self._client = httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(timeout, connect=5.0),
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
            headers={"User-Agent": user_agent, "Accept": "application/json"},
            follow_redirects=True,
        )
        self._max_retries = max_retries
        self._breakers: dict[str, CircuitBreaker] = {}

    async def get_json(
        self, url: str, *, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None
    ) -> Any:
        response = await self._get(url, params=params, headers=headers)
        try:
            return response.json()
        except ValueError as exc:
            raise ProviderUnavailable(f"Invalid JSON from {response.url.host}") from exc

    async def post_json(self, url: str, payload: Any, *, headers: dict[str, str] | None = None) -> Any:
        """POST JSON (used for read-only JSON-RPC calls such as eth_getBalance)."""
        response = await self._send("POST", url, json=payload, headers=headers)
        try:
            return response.json()
        except ValueError as exc:
            raise ProviderUnavailable(f"Invalid JSON from {response.url.host}") from exc

    async def get_bytes(self, url: str, *, max_bytes: int = 2_000_000) -> bytes:
        response = await self._get(url, headers={"Accept": "application/rss+xml, application/xml, text/xml"})
        if len(response.content) > max_bytes:
            raise ProviderUnavailable("Upstream response too large")
        return response.content

    async def _get(
        self, url: str, *, params: dict[str, Any] | None = None, headers: dict[str, str] | None = None
    ) -> httpx.Response:
        return await self._send("GET", url, params=params, headers=headers)

    async def _send(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        json: Any = None,
    ) -> httpx.Response:
        host = httpx.URL(url).host
        breaker = self._breakers.setdefault(host, CircuitBreaker())
        if not breaker.allow():
            raise ProviderUnavailable(f"Circuit open for {host}")

        last_error: str = "unknown error"
        for attempt in range(self._max_retries + 1):
            try:
                response = await self._client.request(method, url, params=params, headers=headers, json=json)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = type(exc).__name__
            else:
                if response.status_code < 400:
                    breaker.success()
                    return response
                last_error = f"HTTP {response.status_code}"
                if response.status_code not in RETRYABLE_STATUS:
                    breaker.success()  # the host is healthy; the request was bad
                    raise ProviderUnavailable(f"{host} returned {response.status_code}")
                if retry_after := response.headers.get("retry-after"):
                    delay = min(float(retry_after), 30.0) if retry_after.isdigit() else 2.0
                    await asyncio.sleep(delay)
                    continue
            if attempt < self._max_retries:
                await asyncio.sleep(min(self._backoff * 2**attempt, 8.0) + random.uniform(0, self._backoff / 2))  # noqa: S311

        breaker.failure()
        log.warning("upstream_failed", host=host, error=last_error)
        raise ProviderUnavailable(f"{host} unavailable ({last_error})")

    async def aclose(self) -> None:
        await self._client.aclose()
