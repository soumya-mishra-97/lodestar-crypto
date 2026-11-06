"""Public-address validation and secret detection for read-only wallet import.

Lodestar only ever needs a *public* address. Anything that looks like a private
key, extended private key or seed phrase is rejected before it is stored,
logged or sent anywhere.
"""

from __future__ import annotations

import re
from enum import StrEnum

from lodestar.domain.errors import ValidationFailed


class Chain(StrEnum):
    ETHEREUM = "ethereum"
    POLYGON = "polygon"
    BITCOIN = "bitcoin"


_EVM = re.compile(r"^0x[0-9a-fA-F]{40}$")
_BTC_BECH32 = re.compile(r"^(bc1)[02-9ac-hj-np-z]{11,87}$")
_BTC_BASE58 = re.compile(r"^[13][1-9A-HJ-NP-Za-km-z]{25,34}$")

_HEX_KEY = re.compile(r"^(0x)?[0-9a-fA-F]{64}$")
_WIF = re.compile(r"^[5KL][1-9A-HJ-NP-Za-km-z]{50,51}$")
_EXTENDED_PRIVATE = re.compile(r"^[xyzt]prv[1-9A-HJ-NP-Za-km-z]{100,}$")
_SEED_WORD = re.compile(r"^[a-z]{3,8}$")
SEED_LENGTHS = {12, 15, 18, 21, 24}


def looks_like_secret(text: str) -> bool:
    """True for private keys (hex/WIF), extended private keys and BIP-39-shaped seed phrases."""
    value = text.strip()
    if _HEX_KEY.fullmatch(value) or _WIF.fullmatch(value) or _EXTENDED_PRIVATE.fullmatch(value):
        return True
    words = value.lower().split()
    return len(words) in SEED_LENGTHS and all(_SEED_WORD.fullmatch(w) for w in words)


def normalize_address(chain: Chain, address: str) -> str:
    value = address.strip()
    if looks_like_secret(value):
        raise ValidationFailed(
            "That looks like a private key or seed phrase. Lodestar never needs it: paste a public address "
            "instead, and consider that secret compromised if you shared it anywhere."
        )
    if chain in (Chain.ETHEREUM, Chain.POLYGON):
        if not _EVM.fullmatch(value):
            raise ValidationFailed("Expected a 0x-prefixed, 40-hex-character EVM address")
        return value.lower()
    if _BTC_BECH32.fullmatch(value.lower()):
        return value.lower()
    if _BTC_BASE58.fullmatch(value):
        return value
    raise ValidationFailed("Expected a Bitcoin address (bc1..., 1... or 3...)")


def short_address(address: str) -> str:
    return f"{address[:6]}…{address[-4:]}" if len(address) > 12 else address
