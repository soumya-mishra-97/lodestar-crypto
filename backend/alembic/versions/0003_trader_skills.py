"""Trader skills: scans, backtests, paper trading; trade-plan fields on reports.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)
PRICE = sa.Numeric(38, 12)
MONEY = sa.Numeric(38, 8)


def upgrade() -> None:
    op.add_column("reports", sa.Column("setup_kind", sa.String(16)))
    op.add_column("reports", sa.Column("setup_status", sa.String(16)))

    op.create_table(
        "scans",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("universe", sa.String(16), nullable=False),
        sa.Column("top_n", sa.Integer),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("progress", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total", sa.Integer, nullable=False, server_default="0"),
        sa.Column("results", postgresql.JSONB),
        sa.Column("error", sa.Text),
        sa.Column("data_mode", sa.String(8), nullable=False),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", TS),
    )
    op.create_index("ix_scans_user_created", "scans", ["user_id", sa.text("created_at DESC")])

    op.create_table(
        "backtests",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("asset_id", UUID, sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_id", UUID, sa.ForeignKey("pipeline_runs.id", ondelete="SET NULL")),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("config", postgresql.JSONB, nullable=False),
        sa.Column("summary", postgresql.JSONB, nullable=False),
        sa.Column("result", postgresql.JSONB, nullable=False),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_backtests_user_created", "backtests", ["user_id", sa.text("created_at DESC")])

    op.create_table(
        "paper_accounts",
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("starting_cash", MONEY, nullable=False),
        sa.Column("cash", MONEY, nullable=False),
        sa.Column("started_on", sa.Date, nullable=False),
        sa.Column("last_processed", sa.Date),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "paper_positions",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("asset_id", UUID, sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("report_id", UUID, sa.ForeignKey("reports.id", ondelete="SET NULL")),
        sa.Column("origin", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("setup_kind", sa.String(16), nullable=False),
        sa.Column("trigger", PRICE, nullable=False),
        sa.Column("entry_low", PRICE, nullable=False),
        sa.Column("entry_high", PRICE, nullable=False),
        sa.Column("stop", PRICE, nullable=False),
        sa.Column("profit_level", PRICE, nullable=False),
        sa.Column("horizon", sa.Integer, nullable=False),
        sa.Column("expiry_bars", sa.Integer, nullable=False),
        sa.Column("units", PRICE, nullable=False),
        sa.Column("opened_on", sa.Date, nullable=False),
        sa.Column("bars_seen", sa.Integer, nullable=False, server_default="0"),
        sa.Column("bars_held", sa.Integer, nullable=False, server_default="0"),
        sa.Column("entry_price", PRICE),
        sa.Column("entry_at", TS),
        sa.Column("exit_price", PRICE),
        sa.Column("exit_at", TS),
        sa.Column("exit_reason", sa.Text),
        sa.Column("fees_usd", MONEY, nullable=False, server_default="0"),
        sa.Column("pnl_usd", MONEY),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_paper_positions_user_status", "paper_positions", ["user_id", "status"])
    op.create_table(
        "paper_equity",
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("day", sa.Date, primary_key=True),
        sa.Column("equity", MONEY, nullable=False),
        sa.Column("cash", MONEY, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("paper_equity")
    op.drop_table("paper_positions")
    op.drop_table("paper_accounts")
    op.drop_table("backtests")
    op.drop_table("scans")
    op.drop_column("reports", "setup_status")
    op.drop_column("reports", "setup_kind")
