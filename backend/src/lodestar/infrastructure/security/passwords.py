"""Argon2id password hashing (OWASP-recommended)."""

from __future__ import annotations

from argon2 import PasswordHasher as _Argon2
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError


class Argon2PasswordHasher:
    def __init__(self) -> None:
        self._ph = _Argon2()  # argon2id, library defaults track OWASP guidance
        self._dummy = self._ph.hash("timing-equaliser-not-a-real-password")

    def hash(self, password: str) -> str:
        return self._ph.hash(password)

    def verify(self, password_hash: str, password: str) -> bool:
        try:
            return self._ph.verify(password_hash, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

    def dummy_verify(self) -> None:
        self.verify(self._dummy, "wrong-password")
