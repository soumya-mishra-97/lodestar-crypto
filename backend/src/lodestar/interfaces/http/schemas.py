"""HTTP request/response schemas (Pydantic). Validation happens here, at the edge."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints

from lodestar.domain.addresses import Chain

CoinGeckoId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9\-]{0,99}$")]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class RegisterRequest(StrictModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)


class LoginRequest(StrictModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - not a secret
    expires_in: int


class UserResponse(BaseModel):
    id: str
    email: str
    role: str


class AddAssetRequest(StrictModel):
    coingecko_id: CoinGeckoId
    watch: bool = True
    analyze: bool = True


class AssetCandidateResponse(BaseModel):
    coingecko_id: str
    symbol: str
    name: str
    market_cap_rank: int | None
    thumb_url: str | None


class HoldingUpsertRequest(StrictModel):
    asset_id: str = Field(pattern=r"^[0-9a-fA-F-]{36}$")
    quantity: float = Field(ge=0, le=1e15)
    avg_cost_usd: float | None = Field(default=None, ge=0, le=1e12)
    notes: str | None = Field(default=None, max_length=1000)


class CsvImportRequest(StrictModel):
    content: str = Field(min_length=1, max_length=200_000)


class AddressImportRequest(StrictModel):
    chain: Chain
    address: str = Field(min_length=20, max_length=300)


class DecisionRequest(StrictModel):
    note: str | None = Field(default=None, max_length=1000)


class PreferencesRequest(StrictModel):
    polymarket_enabled: bool | None = None
    mismatch_tolerance_pct: float | None = Field(default=None, ge=0.1, le=10)
    max_loss_pct: float | None = Field(default=None, ge=0.1, le=5)
    max_position_pct: float | None = Field(default=None, ge=1, le=100)
    max_slippage_pct: float | None = Field(default=None, ge=0.05, le=5)
    fee_bps: float | None = Field(default=None, ge=0, le=100)
    slippage_bps: float | None = Field(default=None, ge=0, le=100)
    horizon_days: int | None = Field(default=None, ge=3, le=60)
    min_volume_usd: float | None = Field(default=None, ge=0, le=1e11)
    paper_starting_cash: float | None = Field(default=None, ge=100, le=1e9)
