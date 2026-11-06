from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from lodestar.interfaces.http.deps import ContainerDep

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
async def live() -> dict[str, str]:
    """Process is up. Used by the orchestrator's liveness probe."""
    return {"status": "ok"}


@router.get("/ready")
async def ready(c: ContainerDep) -> JSONResponse:
    """Dependencies reachable. Used by the readiness probe / load balancer."""
    checks: dict[str, Any] = {}
    try:
        if c.engine is None or c.redis is None:
            raise RuntimeError("datastores not configured")
        async with c.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:  # noqa: BLE001 - report, don't raise
        checks["database"] = "unavailable"
    try:
        if c.redis is None:
            raise RuntimeError("redis not configured")
        await c.redis.ping()
        checks["redis"] = "ok"
    except Exception:  # noqa: BLE001
        checks["redis"] = "unavailable"
    healthy = all(v == "ok" for v in checks.values())
    return JSONResponse(
        {"status": "ok" if healthy else "degraded", "checks": checks}, status_code=200 if healthy else 503
    )
