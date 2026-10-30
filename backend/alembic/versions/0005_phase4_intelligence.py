"""Add Alpha, airdrop, and Prime Sale intelligence tables.

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def _timestamps():
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "alpha_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("announcement_id", sa.Integer(), nullable=False),
        sa.Column("token_name", sa.String(255), nullable=False),
        sa.Column("token_symbol", sa.String(64)),
        sa.Column("contract_address", sa.String(128)),
        sa.Column("blockchain_network", sa.String(64)),
        sa.Column("trading_status", sa.String(64), nullable=False, server_default="announced"),
        sa.Column("trading_pairs", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("announcement_url", sa.String(1024), nullable=False),
        sa.Column("announcement_timestamp", sa.DateTime(timezone=True)),
        sa.Column("token_metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("data_source", sa.String(128), nullable=False, server_default="binance_website_cms"),
        sa.Column("verification_status", sa.String(64), nullable=False, server_default="official_website"),
        sa.Column("current_price", sa.Numeric(28, 8)),
        sa.Column("price_change_24h", sa.Numeric(28, 8)),
        sa.Column("volume_24h", sa.Numeric(28, 8)),
        sa.Column("market_data_source", sa.String(128)),
        sa.Column("market_data_updated_at", sa.DateTime(timezone=True)),
        sa.Column("market_data_status", sa.String(32), nullable=False, server_default="unavailable"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["announcement_id"], ["announcements.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("announcement_id", name="uq_alpha_tokens_announcement_id"),
    )
    op.create_index("ix_alpha_tokens_announcement_id", "alpha_tokens", ["announcement_id"])
    op.create_index("ix_alpha_tokens_token_symbol", "alpha_tokens", ["token_symbol"])
    op.create_index("ix_alpha_tokens_contract_address", "alpha_tokens", ["contract_address"])
    op.create_index("ix_alpha_tokens_blockchain_network", "alpha_tokens", ["blockchain_network"])
    op.create_table(
        "alpha_token_updates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token_id", sa.Integer(), nullable=False),
        sa.Column("update_type", sa.String(64), nullable=False),
        sa.Column("changes", sa.JSON(), nullable=False, server_default="{}"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["token_id"], ["alpha_tokens.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_alpha_token_updates_token_id", "alpha_token_updates", ["token_id"])
    op.create_index("ix_alpha_token_updates_update_type", "alpha_token_updates", ["update_type"])
    op.create_table(
        "airdrop_campaigns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("announcement_id", sa.Integer(), nullable=False),
        sa.Column("campaign_name", sa.String(512), nullable=False),
        sa.Column("token_name", sa.String(255)),
        sa.Column("token_symbol", sa.String(64)),
        sa.Column("description", sa.Text()),
        sa.Column("eligibility_summary", sa.Text()),
        sa.Column("start_date", sa.DateTime(timezone=True)),
        sa.Column("end_date", sa.DateTime(timezone=True)),
        sa.Column("claim_period_start", sa.DateTime(timezone=True)),
        sa.Column("claim_period_end", sa.DateTime(timezone=True)),
        sa.Column("distribution_schedule", sa.Text()),
        sa.Column("reward_info", sa.Text()),
        sa.Column("supported_networks", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("official_url", sa.String(1024), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="UNKNOWN"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["announcement_id"], ["announcements.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("announcement_id", name="uq_airdrop_campaigns_announcement_id"),
    )
    op.create_index("ix_airdrop_campaigns_announcement_id", "airdrop_campaigns", ["announcement_id"])
    op.create_index("ix_airdrop_campaigns_token_symbol", "airdrop_campaigns", ["token_symbol"])
    op.create_index("ix_airdrop_campaigns_status", "airdrop_campaigns", ["status"])
    op.create_table(
        "airdrop_eligibility",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("campaign_id", sa.Integer(), nullable=False),
        sa.Column("requirement_type", sa.String(64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("source_text", sa.Text()),
        sa.Column("is_confirmed_details", sa.Boolean(), nullable=False, server_default=sa.false()),
        *_timestamps(),
        sa.ForeignKeyConstraint(["campaign_id"], ["airdrop_campaigns.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_airdrop_eligibility_campaign_id", "airdrop_eligibility", ["campaign_id"])
    op.create_index("ix_airdrop_eligibility_requirement_type", "airdrop_eligibility", ["requirement_type"])
    op.create_table(
        "prime_sales",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("announcement_id", sa.Integer(), nullable=False),
        sa.Column("token_name", sa.String(255), nullable=False),
        sa.Column("token_symbol", sa.String(64)),
        sa.Column("sale_description", sa.Text()),
        sa.Column("subscription_start", sa.DateTime(timezone=True)),
        sa.Column("subscription_end", sa.DateTime(timezone=True)),
        sa.Column("distribution_time", sa.DateTime(timezone=True)),
        sa.Column("trading_availability", sa.Text()),
        sa.Column("subscription_price", sa.Numeric(28, 8)),
        sa.Column("min_commitment", sa.Numeric(28, 8)),
        sa.Column("max_commitment", sa.Numeric(28, 8)),
        sa.Column("eligible_assets", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("allocation_methodology", sa.Text()),
        sa.Column("reward_info", sa.Text()),
        sa.Column("official_url", sa.String(1024), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="UNKNOWN"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["announcement_id"], ["announcements.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("announcement_id", name="uq_prime_sales_announcement_id"),
    )
    op.create_index("ix_prime_sales_announcement_id", "prime_sales", ["announcement_id"])
    op.create_index("ix_prime_sales_token_symbol", "prime_sales", ["token_symbol"])
    op.create_index("ix_prime_sales_status", "prime_sales", ["status"])
    op.create_table(
        "prime_sale_allocation_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sale_id", sa.Integer(), nullable=False),
        sa.Column("formula_type", sa.String(64), nullable=False, server_default="unknown"),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("total_token_allocation", sa.Numeric(28, 8)),
        sa.Column("sale_price", sa.Numeric(28, 8)),
        *_timestamps(),
        sa.ForeignKeyConstraint(["sale_id"], ["prime_sales.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("sale_id", name="uq_prime_sale_allocation_rules_sale_id"),
    )
    op.create_index("ix_prime_sale_allocation_rules_sale_id", "prime_sale_allocation_rules", ["sale_id"])
    op.create_table(
        "campaign_notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("notification_type", sa.String(64), nullable=False),
        sa.Column("announcement_id", sa.Integer()),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("error_message", sa.Text()),
        *_timestamps(),
        sa.ForeignKeyConstraint(["announcement_id"], ["announcements.id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "entity_type", "entity_id", "notification_type",
            name="uq_campaign_notifications_entity_type",
        ),
    )
    op.create_index("ix_campaign_notifications_entity_type", "campaign_notifications", ["entity_type"])
    op.create_index("ix_campaign_notifications_entity_id", "campaign_notifications", ["entity_id"])
    op.create_index("ix_campaign_notifications_notification_type", "campaign_notifications", ["notification_type"])


def downgrade() -> None:
    op.drop_table("campaign_notifications")
    op.drop_table("prime_sale_allocation_rules")
    op.drop_table("prime_sales")
    op.drop_table("airdrop_eligibility")
    op.drop_table("airdrop_campaigns")
    op.drop_table("alpha_token_updates")
    op.drop_table("alpha_tokens")
