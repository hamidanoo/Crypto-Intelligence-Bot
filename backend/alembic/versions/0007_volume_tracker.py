"""Add competition volume tracker tables.

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def _timestamps():
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "competition_volume_intervals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("competition_id", sa.Integer(), nullable=False),
        sa.Column("trading_pair", sa.String(64), nullable=False),
        sa.Column("base_asset", sa.String(64)),
        sa.Column("quote_asset", sa.String(64)),
        sa.Column("interval_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("interval_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("public_base_volume", sa.Numeric(28, 8)),
        sa.Column("public_quote_volume", sa.Numeric(28, 8)),
        sa.Column("estimated_eligible_volume", sa.Numeric(28, 8)),
        sa.Column("official_eligible_volume", sa.Numeric(28, 8)),
        sa.Column("calculation_method", sa.String(128)),
        sa.Column("data_status", sa.String(32), nullable=False, server_default="incomplete"),
        sa.Column("recalculated", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["competition_id"], ["competitions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "competition_id",
            "trading_pair",
            "interval_start",
            name="uq_volume_intervals_competition_pair_start",
        ),
    )
    op.create_index(
        "ix_competition_volume_intervals_competition_id",
        "competition_volume_intervals",
        ["competition_id"],
    )
    op.create_index(
        "ix_competition_volume_intervals_trading_pair",
        "competition_volume_intervals",
        ["trading_pair"],
    )
    op.create_index(
        "ix_competition_volume_intervals_interval_start",
        "competition_volume_intervals",
        ["interval_start"],
    )
    op.create_index(
        "ix_competition_volume_intervals_data_status",
        "competition_volume_intervals",
        ["data_status"],
    )
    op.create_table(
        "competition_volume_checkpoints",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("competition_id", sa.Integer(), nullable=False),
        sa.Column("trading_pair", sa.String(64), nullable=False),
        sa.Column("last_interval_end", sa.DateTime(timezone=True)),
        sa.Column("last_trade_id", sa.Integer()),
        *_timestamps(),
        sa.ForeignKeyConstraint(["competition_id"], ["competitions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "competition_id",
            "trading_pair",
            name="uq_volume_checkpoints_competition_pair",
        ),
    )
    op.create_index(
        "ix_competition_volume_checkpoints_competition_id",
        "competition_volume_checkpoints",
        ["competition_id"],
    )
    op.create_index(
        "ix_competition_volume_checkpoints_trading_pair",
        "competition_volume_checkpoints",
        ["trading_pair"],
    )
    op.create_table(
        "competition_volume_collection_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("competition_id", sa.Integer()),
        sa.Column("started", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(32), nullable=False, server_default="running"),
        sa.Column("intervals_found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("intervals_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("intervals_updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("intervals_skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text()),
        sa.ForeignKeyConstraint(["competition_id"], ["competitions.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_competition_volume_collection_runs_competition_id",
        "competition_volume_collection_runs",
        ["competition_id"],
    )
    op.create_index(
        "ix_competition_volume_collection_runs_started",
        "competition_volume_collection_runs",
        ["started"],
    )
    op.create_index(
        "ix_competition_volume_collection_runs_status",
        "competition_volume_collection_runs",
        ["status"],
    )
    op.create_table(
        "competition_volume_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("competition_id", sa.Integer(), nullable=False),
        sa.Column("trading_pair", sa.String(64), nullable=False),
        sa.Column("interval_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("interval_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("message_text", sa.Text()),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("error_message", sa.Text()),
        sa.ForeignKeyConstraint(["competition_id"], ["competitions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "competition_id",
            "trading_pair",
            "interval_start",
            name="uq_volume_reports_competition_pair_start",
        ),
    )
    op.create_index(
        "ix_competition_volume_reports_competition_id",
        "competition_volume_reports",
        ["competition_id"],
    )
    op.create_index(
        "ix_competition_volume_reports_trading_pair",
        "competition_volume_reports",
        ["trading_pair"],
    )
    op.create_index(
        "ix_competition_volume_reports_interval_start",
        "competition_volume_reports",
        ["interval_start"],
    )
    op.create_index(
        "ix_competition_volume_reports_status", "competition_volume_reports", ["status"]
    )
    op.create_table(
        "competition_pair_configurations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("competition_id", sa.Integer(), nullable=False),
        sa.Column("trading_pair", sa.String(64), nullable=False),
        sa.Column("multiplier", sa.Numeric(28, 8)),
        sa.Column("multiplier_verified", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("tracking_enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("calculation_method", sa.String(128)),
        sa.Column("note", sa.Text()),
        *_timestamps(),
        sa.ForeignKeyConstraint(["competition_id"], ["competitions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "competition_id",
            "trading_pair",
            name="uq_pair_configurations_competition_pair",
        ),
    )
    op.create_index(
        "ix_competition_pair_configurations_competition_id",
        "competition_pair_configurations",
        ["competition_id"],
    )
    op.create_index(
        "ix_competition_pair_configurations_trading_pair",
        "competition_pair_configurations",
        ["trading_pair"],
    )


def downgrade() -> None:
    op.drop_table("competition_pair_configurations")
    op.drop_table("competition_volume_reports")
    op.drop_table("competition_volume_collection_runs")
    op.drop_table("competition_volume_checkpoints")
    op.drop_table("competition_volume_intervals")
