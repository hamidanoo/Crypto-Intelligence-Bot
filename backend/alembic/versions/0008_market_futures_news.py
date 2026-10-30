"""Add market, futures, and news intelligence tables.

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def _timestamps():
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "market_watchlists",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("note", sa.Text()),
        *_timestamps(),
    )
    op.create_index("ix_market_watchlists_symbol", "market_watchlists", ["symbol"], unique=True)
    op.create_table(
        "market_alerts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("alert_type", sa.String(64), nullable=False),
        sa.Column("threshold_percent", sa.Numeric(20, 8)),
        sa.Column("baseline_price", sa.Numeric(28, 8)),
        sa.Column("current_price", sa.Numeric(28, 8)),
        sa.Column("change_percent", sa.Numeric(20, 8)),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cooldown_until", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(32), nullable=False, server_default="triggered"),
        sa.Column("source", sa.String(64), nullable=False, server_default="binance_spot"),
        *_timestamps(),
    )
    op.create_index("ix_market_alerts_symbol", "market_alerts", ["symbol"])
    op.create_index("ix_market_alerts_alert_type", "market_alerts", ["alert_type"])
    op.create_index("ix_market_alerts_triggered_at", "market_alerts", ["triggered_at"])
    op.create_table(
        "news_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("source_type", sa.String(64), nullable=False),
        sa.Column("feed_url", sa.String(1024)),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("reliability_note", sa.Text()),
        *_timestamps(),
    )
    op.create_index("ix_news_sources_name", "news_sources", ["name"], unique=True)
    op.create_table(
        "crypto_news",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.Integer()),
        sa.Column("announcement_id", sa.Integer()),
        sa.Column("headline", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text()),
        sa.Column("original_url", sa.String(1024), nullable=False),
        sa.Column("publisher", sa.String(128), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("related_symbols", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("processing_status", sa.String(32), nullable=False, server_default="processed"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["source_id"], ["news_sources.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["announcement_id"], ["announcements.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("announcement_id", name="uq_crypto_news_announcement"),
        sa.UniqueConstraint("original_url", name="uq_crypto_news_url"),
        sa.UniqueConstraint("fingerprint", name="uq_crypto_news_fingerprint"),
    )
    op.create_index("ix_crypto_news_category", "crypto_news", ["category"])
    op.create_index("ix_crypto_news_published_at", "crypto_news", ["published_at"])
    op.create_table(
        "news_collection_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.Integer()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(32), nullable=False, server_default="running"),
        sa.Column("found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text()),
        sa.ForeignKeyConstraint(["source_id"], ["news_sources.id"], ondelete="SET NULL"),
    )
    op.create_table(
        "market_collection_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_name", sa.String(64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(32), nullable=False, server_default="running"),
        sa.Column("symbols_requested", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("symbols_collected", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text()),
    )
    op.create_index("ix_market_collection_runs_job_name", "market_collection_runs", ["job_name"])
    op.create_table(
        "futures_market_ratios",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("ratio_type", sa.String(64), nullable=False),
        sa.Column("long_ratio", sa.Numeric(20, 8)),
        sa.Column("short_ratio", sa.Numeric(20, 8)),
        sa.Column("long_short_ratio", sa.Numeric(20, 8)),
        sa.Column("period", sa.String(32)),
        sa.Column("source", sa.String(64), nullable=False, server_default="binance_futures"),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_futures_market_ratios_symbol", "futures_market_ratios", ["symbol"])
    op.create_index("ix_futures_market_ratios_ratio_type", "futures_market_ratios", ["ratio_type"])
    op.create_index(
        "ix_futures_market_ratios_collected_at", "futures_market_ratios", ["collected_at"]
    )


def downgrade() -> None:
    op.drop_table("futures_market_ratios")
    op.drop_table("market_collection_runs")
    op.drop_table("news_collection_runs")
    op.drop_table("crypto_news")
    op.drop_table("news_sources")
    op.drop_table("market_alerts")
    op.drop_table("market_watchlists")
