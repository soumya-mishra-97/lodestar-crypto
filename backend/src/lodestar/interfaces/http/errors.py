"""Map application errors to RFC 9457 problem+json responses. Never leak internals."""

from __future__ import annotations

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from lodestar.domain.errors import (
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    InsufficientData,
    LlmUnavailable,
    LodestarError,
    NotFoundError,
    ProviderUnavailable,
    RateLimitedError,
    ValidationFailed,
)

log = structlog.get_logger(__name__)

STATUS = {
    NotFoundError: 404,
    ConflictError: 409,
    ValidationFailed: 422,
    AuthenticationError: 401,
    AuthorizationError: 403,
    RateLimitedError: 429,
    ProviderUnavailable: 503,
    InsufficientData: 422,
    LlmUnavailable: 503,
}


def _problem(status: int, code: str, detail: str, request: Request) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        media_type="application/problem+json",
        content={
            "type": f"https://lodestar.local/problems/{code}",
            "title": code.replace("_", " ").capitalize(),
            "status": status,
            "detail": detail,
            "instance": request.url.path,
            "request_id": getattr(request.state, "request_id", None),
        },
    )


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(LodestarError)
    async def _domain(request: Request, exc: LodestarError) -> JSONResponse:
        status = next((s for t, s in STATUS.items() if isinstance(exc, t)), 500)
        response = _problem(status, exc.code, str(exc) if status < 500 else "Internal error", request)
        if isinstance(exc, RateLimitedError):
            response.headers["Retry-After"] = str(exc.retry_after_seconds)
        if isinstance(exc, AuthenticationError):
            response.headers["WWW-Authenticate"] = "Bearer"
        if status >= 500:
            log.error("unhandled_domain_error", error=str(exc), code=exc.code)
        return response

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [".".join(str(p) for p in e["loc"][1:]) or "body" for e in exc.errors()]
        return _problem(422, "validation_failed", f"Invalid input: {', '.join(fields)}", request)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled_error", path=request.url.path)
        return _problem(500, "internal_error", "Internal error", request)
