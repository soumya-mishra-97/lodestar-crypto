"""Agentic pipeline: runs, events, reports with approval, multi-source holdings, user settings.

Replaces the single-shot analysis_reports table.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.drop_table("analysis_reports")

    op.add_column("holdings", sa.Column("source", sa.String(128), nullable=False, server_default="manual"))
    op.drop_constraint("uq_holdings_user_asset", "holdings", type_="unique")
    op.create_unique_constraint("uq_holdings_user_asset_source", "holdings", ["user_id", "asset_id", "source"])

    op.create_table(
        "pipeline_runs",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("asset_id", UUID, sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("requested_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("current_step", sa.String(32)),
        sa.Column("repair_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error", sa.Text),
        sa.Column("data_mode", sa.String(8), nullable=False),
        sa.Column("llm_mode", sa.String(64), nullable=False),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", TS),
        sa.Column("finished_at", TS),
    )
    op.create_index("ix_pipeline_runs_asset_created", "pipeline_runs", ["asset_id", sa.text("created_at DESC")])
    op.create_index("ix_pipeline_runs_created", "pipeline_runs", [sa.text("created_at DESC")])
    op.create_index(
        "ix_pipeline_runs_active",
        "pipeline_runs",
        ["asset_id"],
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )

    op.create_table(
        "pipeline_events",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("run_id", UUID, sa.ForeignKey("pipeline_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("ts", TS, nullable=False),
        sa.Column("step", sa.String(32), nullable=False),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column("status", sa.String(24)),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.UniqueConstraint("run_id", "seq", name="uq_pipeline_events_run_seq"),
    )

    op.create_table(
        "reports",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("run_id", UUID, sa.ForeignKey("pipeline_runs.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("asset_id", UUID, sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("headline", sa.Text, nullable=False),
        sa.Column("short_term_stance", sa.String(16), nullable=False),
        sa.Column("long_term_stance", sa.String(16), nullable=False),
        sa.Column("short_term_risk", sa.String(16), nullable=False),
        sa.Column("long_term_risk", sa.String(16), nullable=False),
        sa.Column("content", postgresql.JSONB, nullable=False),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("decided_at", TS),
        sa.Column("decided_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("decision_note", sa.Text),
    )
    op.create_index("ix_reports_asset_created", "reports", ["asset_id", sa.text("created_at DESC")])
    op.create_index("ix_reports_created", "reports", [sa.text("created_at DESC")])

    op.create_table(
        "user_settings",
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("data", postgresql.JSONB, nullable=False),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("user_settings")
    op.drop_table("reports")
    op.drop_table("pipeline_events")
    op.drop_table("pipeline_runs")
    op.drop_constraint("uq_holdings_user_asset_source", "holdings", type_="unique")
    op.execute("DELETE FROM holdings WHERE source <> 'manual'")
    op.create_unique_constraint("uq_holdings_user_asset", "holdings", ["user_id", "asset_id"])
    op.drop_column("holdings", "source")
    op.create_table(
        "analysis_reports",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("asset_id", UUID, sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("requested_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error", sa.Text),
        sa.Column("short_term_stance", sa.String(16)),
        sa.Column("long_term_stance", sa.String(16)),
        sa.Column("risk_level", sa.String(16)),
        sa.Column("grounding_score", sa.Numeric(4, 3)),
        sa.Column("result", postgresql.JSONB),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", TS),
    )
