"""SQLAlchemy 2.0 ORM models. Persistence detail only: never exposed past repositories."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class UserRow(TimestampMixin, Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class AssetRow(TimestampMixin, Base):
    __tablename__ = "assets"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    coingecko_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)


class WatchlistItemRow(TimestampMixin, Base):
    __tablename__ = "watchlist_items"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True)
    asset: Mapped[AssetRow] = relationship(lazy="joined")


class HoldingRow(TimestampMixin, Base):
    __tablename__ = "holdings"
    __table_args__ = (UniqueConstraint("user_id", "asset_id", "source", name="uq_holdings_user_asset_source"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id", ondelete="RESTRICT"))
    source: Mapped[str] = mapped_column(String(128), nullable=False, server_default="manual")
    quantity: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    avg_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(38, 18))
    notes_encrypted: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    asset: Mapped[AssetRow] = relationship(lazy="joined")


class PipelineRunRow(TimestampMixin, Base):
    __tablename__ = "pipeline_runs"
    __table_args__ = (
        Index("ix_pipeline_runs_asset_created", "asset_id", text("created_at DESC")),
        Index("ix_pipeline_runs_created", text("created_at DESC")),
        Index("ix_pipeline_runs_active", "asset_id", postgresql_where=text("status IN ('queued', 'running')")),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), nullable=False)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    current_step: Mapped[str | None] = mapped_column(String(32))
    repair_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    error: Mapped[str | None] = mapped_column(Text)
    data_mode: Mapped[str] = mapped_column(String(8), nullable=False)
    llm_mode: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PipelineEventRow(Base):
    __tablename__ = "pipeline_events"
    __table_args__ = (UniqueConstraint("run_id", "seq", name="uq_pipeline_events_run_seq"),)
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pipeline_runs.id", ondelete="CASCADE"), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    step: Mapped[str] = mapped_column(String(32), nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str | None] = mapped_column(String(24))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class ReportRow(TimestampMixin, Base):
    __tablename__ = "reports"
    __table_args__ = (
        Index("ix_reports_asset_created", "asset_id", text("created_at DESC")),
        Index("ix_reports_created", text("created_at DESC")),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pipeline_runs.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    # Denormalised summary: cheap list/overview queries without reading the JSON document.
    headline: Mapped[str] = mapped_column(Text, nullable=False)
    short_term_stance: Mapped[str] = mapped_column(String(16), nullable=False)
    long_term_stance: Mapped[str] = mapped_column(String(16), nullable=False)
    short_term_risk: Mapped[str] = mapped_column(String(16), nullable=False)
    long_term_risk: Mapped[str] = mapped_column(String(16), nullable=False)
    setup_kind: Mapped[str | None] = mapped_column(String(16))  # trade plans only
    setup_status: Mapped[str | None] = mapped_column(String(16))
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decision_note: Mapped[str | None] = mapped_column(Text)


class UserSettingsRow(Base):
    __tablename__ = "user_settings"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ScanRow(TimestampMixin, Base):
    __tablename__ = "scans"
    __table_args__ = (Index("ix_scans_user_created", "user_id", text("created_at DESC")),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    universe: Mapped[str] = mapped_column(String(16), nullable=False)
    top_n: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    total: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    results: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    data_mode: Mapped[str] = mapped_column(String(8), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BacktestRow(TimestampMixin, Base):
    __tablename__ = "backtests"
    __table_args__ = (Index("ix_backtests_user_created", "user_id", text("created_at DESC")),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), nullable=False)
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("pipeline_runs.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class PaperAccountRow(TimestampMixin, Base):
    __tablename__ = "paper_accounts"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    starting_cash: Mapped[Decimal] = mapped_column(Numeric(38, 8), nullable=False)
    cash: Mapped[Decimal] = mapped_column(Numeric(38, 8), nullable=False)
    started_on: Mapped[date] = mapped_column(Date, nullable=False)
    last_processed: Mapped[date | None] = mapped_column(Date)


class PaperPositionRow(TimestampMixin, Base):
    __tablename__ = "paper_positions"
    __table_args__ = (Index("ix_paper_positions_user_status", "user_id", "status"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), nullable=False)
    report_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("reports.id", ondelete="SET NULL"))
    origin: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    setup_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    trigger: Mapped[Decimal] = mapped_column(Numeric(38, 12), nullable=False)
    entry_low: Mapped[Decimal] = mapped_column(Numeric(38, 12), nullable=False)
    entry_high: Mapped[Decimal] = mapped_column(Numeric(38, 12), nullable=False)
    stop: Mapped[Decimal] = mapped_column(Numeric(38, 12), nullable=False)
    profit_level: Mapped[Decimal] = mapped_column(Numeric(38, 12), nullable=False)
    horizon: Mapped[int] = mapped_column(Integer, nullable=False)
    expiry_bars: Mapped[int] = mapped_column(Integer, nullable=False)
    units: Mapped[Decimal] = mapped_column(Numeric(38, 12), nullable=False)
    opened_on: Mapped[date] = mapped_column(Date, nullable=False)
    bars_seen: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    bars_held: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    entry_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    entry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exit_price: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    exit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exit_reason: Mapped[str | None] = mapped_column(Text)
    fees_usd: Mapped[Decimal] = mapped_column(Numeric(38, 8), nullable=False, server_default="0")
    pnl_usd: Mapped[Decimal | None] = mapped_column(Numeric(38, 8))


class PaperEquityRow(Base):
    __tablename__ = "paper_equity"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    equity: Mapped[Decimal] = mapped_column(Numeric(38, 8), nullable=False)
    cash: Mapped[Decimal] = mapped_column(Numeric(38, 8), nullable=False)
