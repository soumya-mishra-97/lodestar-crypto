"""Authentication use cases: owner bootstrap, login, refresh rotation, logout."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from lodestar.application.ports import UnitOfWork, UserRecord
from lodestar.domain.errors import (
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    NotFoundError,
    ValidationFailed,
)
from lodestar.domain.models import Role

MIN_PASSWORD_LENGTH = 12
LOCAL_OWNER_EMAIL = "owner@lodestar.local"


class PasswordHasher(Protocol):
    def hash(self, password: str) -> str: ...
    def verify(self, password_hash: str, password: str) -> bool: ...
    def dummy_verify(self) -> None: ...


@dataclass(frozen=True, slots=True)
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int


class TokenService(Protocol):
    async def issue(self, user_id: UUID, role: Role) -> TokenPair: ...
    async def consume(self, refresh_token: str) -> UUID:
        """Validate and invalidate a refresh token (single use), returning its user id."""
        ...

    async def revoke(self, refresh_token: str) -> None: ...


class AuthService:
    def __init__(
        self,
        uow: Callable[[], UnitOfWork],
        hasher: PasswordHasher,
        tokens: TokenService,
        *,
        allow_registration: bool,
    ) -> None:
        self._uow, self._hasher, self._tokens = uow, hasher, tokens
        self._allow_registration = allow_registration

    async def register(self, email: str, password: str) -> UserRecord:
        """The first account becomes the owner. Later sign-ups need explicit opt-in."""
        if len(password) < MIN_PASSWORD_LENGTH:
            raise ValidationFailed(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
        email = email.strip().lower()
        async with self._uow() as uow:
            existing_users = await uow.users.count()
            if existing_users and not self._allow_registration:
                raise AuthorizationError("Registration is closed")
            if await uow.users.get_by_email(email):
                raise ConflictError("Account already exists")
            role = Role.OWNER if existing_users == 0 else Role.VIEWER
            user = await uow.users.add(email, self._hasher.hash(password), role)
            await uow.commit()
            return user

    async def login(self, email: str, password: str) -> TokenPair:
        async with self._uow() as uow:
            user = await uow.users.get_by_email(email.strip().lower())
        if user is None:
            self._hasher.dummy_verify()  # equalise timing to prevent account enumeration
            raise AuthenticationError("Invalid credentials")
        if not user.is_active or not self._hasher.verify(user.password_hash, password):
            raise AuthenticationError("Invalid credentials")
        return await self._tokens.issue(user.id, user.role)

    async def refresh(self, refresh_token: str) -> TokenPair:
        user_id = await self._tokens.consume(refresh_token)  # rotation: old token dies here
        async with self._uow() as uow:
            user = await uow.users.get(user_id)
        if user is None or not user.is_active:
            raise AuthenticationError("Account disabled")
        return await self._tokens.issue(user.id, user.role)

    async def get_user(self, user_id: UUID) -> UserRecord:
        async with self._uow() as uow:
            if user := await uow.users.get(user_id):
                return user
        raise NotFoundError("User not found")

    async def ensure_local_owner(self) -> UserRecord:
        """Single-user local mode: the implicit owner account (no usable password)."""
        async with self._uow() as uow:
            if user := await uow.users.get_by_email(LOCAL_OWNER_EMAIL):
                return user
            user = await uow.users.add(LOCAL_OWNER_EMAIL, self._hasher.hash(secrets.token_urlsafe(32)), Role.OWNER)
            await uow.commit()
            return user

    async def logout(self, refresh_token: str) -> None:
        await self._tokens.revoke(refresh_token)
