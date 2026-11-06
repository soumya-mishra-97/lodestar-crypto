"""Field-level encryption for sensitive columns (portfolio notes, future exchange keys).

MultiFernet (AES-128-CBC + HMAC-SHA256): the first key encrypts, every key decrypts,
so keys rotate without downtime. Generate a key with:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from lodestar.domain.errors import LodestarError


class FieldCipher:
    def __init__(self, keys_csv: str) -> None:
        keys = [k.strip() for k in keys_csv.split(",") if k.strip()]
        self._fernet = MultiFernet([Fernet(k) for k in keys]) if keys else None

    @property
    def enabled(self) -> bool:
        return self._fernet is not None

    def encrypt(self, plaintext: str) -> str:
        if self._fernet is None:
            raise LodestarError("Field encryption key not configured")
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, token: str) -> str:
        if self._fernet is None:
            raise LodestarError("Field encryption key not configured")
        try:
            return self._fernet.decrypt(token.encode()).decode()
        except InvalidToken as exc:
            raise LodestarError("Unable to decrypt field (wrong or rotated-out key)") from exc

    def rotate(self, token: str) -> str:
        """Re-encrypt under the primary key (run after adding a new key)."""
        if self._fernet is None:
            raise LodestarError("Field encryption key not configured")
        return self._fernet.rotate(token.encode()).decode()
