"""FastAPI application factory.

Run with:  uvicorn lodestar.interfaces.http.app:app
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

from lodestar.config import Settings, get_settings
from lodestar.infrastructure.container import Container, build_container
from lodestar.infrastructure.observability.logging import configure_logging
from lodestar.interfaces.http.errors import register_error_handlers
from lodestar.interfaces.http.middleware import BodySizeLimitMiddleware, RequestContextMiddleware
from lodestar.interfaces.http.routers import assets, auth, health, me, reports, runs, trading

MAX_BODY_BYTES = 256 * 1024  # CSV imports are capped at 200 KB of text


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json_logs=settings.is_production)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        owned = container is None
        app.state.container = container or await build_container(settings)
        try:
            yield
        finally:
            if owned:
                await app.state.container.aclose()

    app = FastAPI(
        title="Lodestar API",
        version="0.2.0",
        description="Personal, read-only crypto portfolio analysis with an evidence-grounded agent pipeline.",
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )
    if container is not None:
        app.state.container = container

    # Middleware order: last added runs first.
    app.add_middleware(GZipMiddleware, minimum_size=1024)  # skips text/event-stream
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID", "Last-Event-ID"],
        expose_headers=["X-Request-ID", "Retry-After", "Content-Disposition"],
        max_age=600,
    )
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=MAX_BODY_BYTES)
    app.add_middleware(RequestContextMiddleware, hsts=settings.is_production)

    register_error_handlers(app)
    app.include_router(health.router)
    for router in (auth.router, me.router, assets.router, runs.router, reports.router, trading.router):
        app.include_router(router, prefix=settings.api_prefix)

    # /metrics should be reachable only from the internal network (blocked at the proxy).
    Instrumentator(excluded_handlers=["/health/.*", "/metrics"]).instrument(app).expose(app, include_in_schema=False)
    return app


app = create_app()
