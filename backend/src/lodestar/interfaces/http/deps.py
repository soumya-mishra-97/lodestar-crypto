"""FastAPI dependencies: container access, authentication, authorization, rate limits.

Two auth modes:
  local     single-user, no login; every request acts as the implicit owner. Only for a
            stack bound to localhost (docker-compose binds 127.0.0.1). Refused in production.
  password  owner account, short-lived JWT access tokens and rotating refresh cookies.
"""

from __future__ import annotations

import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from lodestar.domain.errors import AuthenticationError, AuthorizationError
from lodestar.domain.models import Role
from lodestar.infrastructure.container import Container

_bearer = HTTPBearer(auto_error=False)


def get_container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


ContainerDep = Annotated[Container, Depends(get_container)]


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: UUID
    role: Role


async def local_owner(container: Container) -> Principal:
    if container.local_owner_id is None:
        container.local_owner_id = (await container.auth.ensure_local_owner()).id
    return Principal(user_id=container.local_owner_id, role=Role.OWNER)


async def current_principal(
    container: ContainerDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Principal:
    if container.settings.auth_mode == "local":
        return await local_owner(container)
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthenticationError("Missing bearer token")
    claims = container.tokens.verify_access(credentials.credentials)
    return Principal(user_id=UUID(claims["sub"]), role=Role(claims["role"]))


PrincipalDep = Annotated[Principal, Depends(current_principal)]


def require_role(*roles: Role) -> Callable[[Principal], Awaitable[Principal]]:
    async def check(principal: PrincipalDep) -> Principal:
        if principal.role not in roles:
            raise AuthorizationError("Insufficient permissions")
        return principal

    return check


OwnerDep = Annotated[Principal, Depends(require_role(Role.OWNER))]


def client_ip(request: Request) -> str:
    # Behind a trusted proxy, configure uvicorn --proxy-headers / --forwarded-allow-ips instead of
    # reading X-Forwarded-For here (it is client-controlled).
    return request.client.host if request.client else "unknown"


def rate_limit(scope: str, *, per: str = "user") -> Callable[..., Awaitable[None]]:
    """Per-user (authenticated) or per-IP rate limit. Limits come from settings."""

    async def dependency(request: Request, container: ContainerDep) -> None:
        s = container.settings
        limits = {
            "api": (s.rate_limit_per_minute, 60),
            "login": (s.login_attempts_per_minute, 60),
            "analysis": (s.analyses_per_hour, 3600),
        }
        limit, window = limits[scope]
        identity = client_ip(request)
        if per == "user" and (auth := request.headers.get("authorization", "")).lower().startswith("bearer "):
            with contextlib.suppress(AuthenticationError):  # invalid token: fall back to IP
                identity = container.tokens.verify_access(auth[7:])["sub"]
        await container.rate_limiter.hit(
            f"{scope}:{identity}", limit=limit, window_seconds=window, fail_open=scope != "login"
        )

    return dependency
