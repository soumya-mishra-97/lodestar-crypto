"""Pure-ASGI middleware (cheaper than BaseHTTPMiddleware: no per-request task or body buffering)."""

from __future__ import annotations

import re
import time
import uuid

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

log = structlog.get_logger("lodestar.access")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9\-]{8,64}$")

SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
    (b"cross-origin-opener-policy", b"same-origin"),
    (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'"),
    (b"cache-control", b"no-store"),
]


class RequestContextMiddleware:
    """Assigns/propagates X-Request-ID, adds security headers, logs one access line."""

    def __init__(self, app: ASGIApp, *, hsts: bool) -> None:
        self.app, self.hsts = app, hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = dict(scope["headers"]).get(b"x-request-id", b"").decode("latin-1")
        request_id = incoming if _REQUEST_ID.fullmatch(incoming) else uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        structlog.contextvars.bind_contextvars(request_id=request_id)
        start, status = time.perf_counter(), 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode()))
                # Swagger UI loads assets from a CDN; the strict API CSP would break it.
                is_docs = scope["path"].startswith("/docs")
                headers.extend(h for h in SECURITY_HEADERS if not (is_docs and h[0] == b"content-security-policy"))
                if self.hsts:
                    headers.append((b"strict-transport-security", b"max-age=63072000; includeSubDomains"))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            log.info(
                "request",
                method=scope["method"],
                path=scope["path"],
                status=status,
                duration_ms=round((time.perf_counter() - start) * 1000, 1),
            )
            structlog.contextvars.unbind_contextvars("request_id")


class BodySizeLimitMiddleware:
    """Rejects request bodies above `max_bytes` before they are read into memory."""

    def __init__(self, app: ASGIApp, *, max_bytes: int = 64 * 1024) -> None:
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        length = dict(scope["headers"]).get(b"content-length")
        if length is not None and length.isdigit() and int(length) > self.max_bytes:
            await send({"type": "http.response.start", "status": 413, "headers": [(b"content-type", b"text/plain")]})
            await send({"type": "http.response.body", "body": b"Request body too large"})
            return
        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise ValueError("Request body too large")
            return message

        await self.app(scope, limited_receive, send)
