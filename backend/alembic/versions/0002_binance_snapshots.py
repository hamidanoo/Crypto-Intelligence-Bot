"""Binance market and futures snapshots.

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "market_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("price_change_24h", sa.Float(), nullable=True),
        sa.Column("price_change_percent_24h", sa.Float(), nullable=True),
        sa.Column("high_24h", sa.Float(), nullable=True),
        sa.Column("low_24h", sa.Float(), nullable=True),
        sa.Column("volume_24h", sa.Float(), nullable=True),
        sa.Column("quote_volume_24h", sa.Float(), nullable=True),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_market_snapshots_symbol", "market_snapshots", ["symbol"], unique=False)
    op.create_index("ix_market_snapshots_collected_at", "market_snapshots", ["collected_at"], unique=False)

    op.create_table(
        "futures_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("funding_rate", sa.Float(), nullable=True),
        sa.Column("next_funding_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("mark_price", sa.Float(), nullable=True),
        sa.Column("open_interest", sa.Float(), nullable=True),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_futures_snapshots_symbol", "futures_snapshots", ["symbol"], unique=False)
    op.create_index("ix_futures_snapshots_collected_at", "futures_snapshots", ["collected_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_futures_snapshots_collected_at", table_name="futures_snapshots")
    op.drop_index("ix_futures_snapshots_symbol", table_name="futures_snapshots")
    op.drop_table("futures_snapshots")
    op.drop_index("ix_market_snapshots_collected_at", table_name="market_snapshots")
    op.drop_index("ix_market_snapshots_symbol", table_name="market_snapshots")
    op.drop_table("market_snapshots")
