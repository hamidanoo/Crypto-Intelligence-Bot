"""Add trading competition intelligence tables.

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def _timestamps():
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "competitions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("announcement_id", sa.Integer(), nullable=False),
        sa.Column("competition_name", sa.String(512), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("competition_type", sa.String(64), nullable=False, server_default="GENERAL"),
        sa.Column("official_url", sa.String(1024), nullable=False),
        sa.Column("reward_pool", sa.Numeric(28, 8)),
        sa.Column("reward_currency", sa.String(32)),
        sa.Column("start_time", sa.DateTime(timezone=True)),
        sa.Column("end_time", sa.DateTime(timezone=True)),
        sa.Column("registration_start", sa.DateTime(timezone=True)),
        sa.Column("registration_end", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(32), nullable=False, server_default="UNKNOWN"),
        sa.Column("eligible_trading_pairs", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("eligible_assets", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("competition_rules", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("eligibility_requirements", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("multiplier_rules", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("source", sa.String(128), nullable=False, server_default="binance_website_cms"),
        sa.Column(
            "verification_status", sa.String(64), nullable=False, server_default="official_website"
        ),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["announcement_id"], ["announcements.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("announcement_id", name="uq_competitions_announcement_id"),
    )
    op.create_index("ix_competitions_announcement_id", "competitions", ["announcement_id"])
    op.create_index("ix_competitions_competition_name", "competitions", ["competition_name"])
    op.create_index("ix_competitions_competition_type", "competitions", ["competition_type"])
    op.create_index("ix_competitions_status", "competitions", ["status"])
    op.create_index("ix_competitions_start_time", "competitions", ["start_time"])
    op.create_index("ix_competitions_end_time", "competitions", ["end_time"])
    op.create_table(
        "competition_trading_pairs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("competition_id", sa.Integer(), nullable=False),
        sa.Column("pair", sa.String(64), nullable=False),
        sa.Column("base_asset", sa.String(64)),
        sa.Column("quote_asset", sa.String(64)),
        *_timestamps(),
        sa.ForeignKeyConstraint(["competition_id"], ["competitions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "competition_id", "pair", name="uq_competition_trading_pairs_competition_pair"
        ),
    )
    op.create_index(
        "ix_competition_trading_pairs_competition_id",
        "competition_trading_pairs",
        ["competition_id"],
    )
    op.create_index("ix_competition_trading_pairs_pair", "competition_trading_pairs", ["pair"])
    op.create_table(
        "competition_rewards",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("competition_id", sa.Integer(), nullable=False),
        sa.Column("rank_range", sa.String(128)),
        sa.Column("reward_amount", sa.Numeric(28, 8)),
        sa.Column("reward_currency", sa.String(32)),
        sa.Column("description", sa.Text()),
        *_timestamps(),
        sa.ForeignKeyConstraint(["competition_id"], ["competitions.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_competition_rewards_competition_id", "competition_rewards", ["competition_id"]
    )
    op.create_table(
        "competition_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("competition_id", sa.Integer(), nullable=False),
        sa.Column("rule_type", sa.String(64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("source_text", sa.Text()),
        *_timestamps(),
        sa.ForeignKeyConstraint(["competition_id"], ["competitions.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_competition_rules_competition_id", "competition_rules", ["competition_id"])
    op.create_index("ix_competition_rules_rule_type", "competition_rules", ["rule_type"])
    op.create_table(
        "competition_updates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("competition_id", sa.Integer(), nullable=False),
        sa.Column("update_type", sa.String(64), nullable=False),
        sa.Column("field_name", sa.String(128)),
        sa.Column("old_value", sa.JSON()),
        sa.Column("new_value", sa.JSON()),
        sa.Column("note", sa.Text()),
        *_timestamps(),
        sa.ForeignKeyConstraint(["competition_id"], ["competitions.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_competition_updates_competition_id", "competition_updates", ["competition_id"]
    )
    op.create_index("ix_competition_updates_update_type", "competition_updates", ["update_type"])
    op.create_table(
        "competition_collection_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.Integer()),
        sa.Column("started", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(32), nullable=False, server_default="running"),
        sa.Column("found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text()),
        sa.ForeignKeyConstraint(["source_id"], ["announcement_sources.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_competition_collection_runs_source_id", "competition_collection_runs", ["source_id"]
    )
    op.create_index(
        "ix_competition_collection_runs_started", "competition_collection_runs", ["started"]
    )
    op.create_index(
        "ix_competition_collection_runs_status", "competition_collection_runs", ["status"]
    )


def downgrade() -> None:
    op.drop_table("competition_collection_runs")
    op.drop_table("competition_updates")
    op.drop_table("competition_rules")
    op.drop_table("competition_rewards")
    op.drop_table("competition_trading_pairs")
    op.drop_table("competitions")
