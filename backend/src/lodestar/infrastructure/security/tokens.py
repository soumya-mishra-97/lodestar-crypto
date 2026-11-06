"""JWT access tokens + opaque, single-use refresh tokens stored in Redis.

- Access token: short-lived (15 min) HS256 JWT, held in memory by the SPA.
- Refresh token: random 256-bit value in an HttpOnly, Secure, SameSite=Strict cookie.
  Only its SHA-256 hash is stored server-side. Each use deletes it (rotation), so a
  stolen token works at most once and logout revokes it immediately.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import jwt
from redis.asyncio import Redis

from lodestar.application.auth import TokenPair
from lodestar.domain.errors import AuthenticationError
from lodestar.domain.models import Role

ALGORITHM = "HS256"


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class JwtTokenService:
    def __init__(self, redis: Redis, *, secret: str, issuer: str, access_ttl: int, refresh_ttl: int) -> None:
        self._redis, self._secret, self._issuer = redis, secret, issuer
        self._access_ttl, self._refresh_ttl = access_ttl, refresh_ttl

    async def issue(self, user_id: UUID, role: Role) -> TokenPair:
        now = datetime.now(UTC)
        access = jwt.encode(
            {
                "sub": str(user_id),
                "role": role.value,
                "iss": self._issuer,
                "iat": now,
                "nbf": now,
                "exp": now + timedelta(seconds=self._access_ttl),
                "jti": secrets.token_hex(8),
            },
            self._secret,
            algorithm=ALGORITHM,
        )
        refresh = secrets.token_urlsafe(32)
        await self._redis.set(f"ls:rt:{_digest(refresh)}", str(user_id), ex=self._refresh_ttl)
        return TokenPair(access_token=access, refresh_token=refresh, expires_in=self._access_ttl)

    def verify_access(self, token: str) -> dict[str, Any]:
        try:
            return jwt.decode(
                token,
                self._secret,
                algorithms=[ALGORITHM],  # pinned: blocks alg=none / algorithm confusion
                issuer=self._issuer,
                options={"require": ["exp", "iat", "sub", "iss"]},
            )
        except jwt.PyJWTError as exc:
            raise AuthenticationError("Invalid or expired token") from exc

    async def consume(self, refresh_token: str) -> UUID:
        user_id = await self._redis.getdel(f"ls:rt:{_digest(refresh_token)}")
        if not user_id:
            raise AuthenticationError("Refresh token invalid, expired or already used")
        return UUID(user_id.decode() if isinstance(user_id, bytes) else user_id)

    async def revoke(self, refresh_token: str) -> None:
        await self._redis.delete(f"ls:rt:{_digest(refresh_token)}")
