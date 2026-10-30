"""Store snapshot financial values as Numeric instead of Float.

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("market_snapshots") as batch:
        batch.alter_column("price", type_=sa.Numeric(28, 8), existing_type=sa.Float())
        batch.alter_column("price_change_24h", type_=sa.Numeric(28, 8), existing_type=sa.Float())
        batch.alter_column("price_change_percent_24h", type_=sa.Numeric(20, 8), existing_type=sa.Float())
        batch.alter_column("high_24h", type_=sa.Numeric(28, 8), existing_type=sa.Float())
        batch.alter_column("low_24h", type_=sa.Numeric(28, 8), existing_type=sa.Float())
        batch.alter_column("volume_24h", type_=sa.Numeric(28, 8), existing_type=sa.Float())
        batch.alter_column("quote_volume_24h", type_=sa.Numeric(28, 8), existing_type=sa.Float())
    with op.batch_alter_table("futures_snapshots") as batch:
        batch.alter_column("funding_rate", type_=sa.Numeric(20, 10), existing_type=sa.Float())
        batch.alter_column("mark_price", type_=sa.Numeric(28, 8), existing_type=sa.Float())
        batch.alter_column("open_interest", type_=sa.Numeric(28, 8), existing_type=sa.Float())


def downgrade() -> None:
    with op.batch_alter_table("futures_snapshots") as batch:
        batch.alter_column("funding_rate", type_=sa.Float(), existing_type=sa.Numeric(20, 10))
        batch.alter_column("mark_price", type_=sa.Float(), existing_type=sa.Numeric(28, 8))
        batch.alter_column("open_interest", type_=sa.Float(), existing_type=sa.Numeric(28, 8))
    with op.batch_alter_table("market_snapshots") as batch:
        batch.alter_column("price", type_=sa.Float(), existing_type=sa.Numeric(28, 8))
        batch.alter_column("price_change_24h", type_=sa.Float(), existing_type=sa.Numeric(28, 8))
        batch.alter_column("price_change_percent_24h", type_=sa.Float(), existing_type=sa.Numeric(20, 8))
        batch.alter_column("high_24h", type_=sa.Float(), existing_type=sa.Numeric(28, 8))
        batch.alter_column("low_24h", type_=sa.Float(), existing_type=sa.Numeric(28, 8))
        batch.alter_column("volume_24h", type_=sa.Float(), existing_type=sa.Numeric(28, 8))
        batch.alter_column("quote_volume_24h", type_=sa.Float(), existing_type=sa.Numeric(28, 8))
