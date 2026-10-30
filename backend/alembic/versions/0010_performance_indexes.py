"""Add composite indexes for Phase 9 audit hot queries.

Revision ID: 0010
Revises: 0009

Indexes only — no columns, tables, or data change, and no
historical migration is touched. These cover the filters
the Phase 9 audit found running without a composite
index: market-alert cooldown lookups (symbol, type,
triggered_at), latest-snapshot lookups (symbol,
collected_at), and audit-log date-range filters
(created_at). The downgrade drops exactly these indexes.
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_market_alerts_symbol_type_triggered",
        "market_alerts",
        ["symbol", "alert_type", "triggered_at"],
    )
    op.create_index(
        "ix_market_snapshots_symbol_collected",
        "market_snapshots",
        ["symbol", "collected_at"],
    )
    op.create_index(
        "ix_futures_snapshots_symbol_collected",
        "futures_snapshots",
        ["symbol", "collected_at"],
    )
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_logs_created_at", table_name="audit_logs")
    op.drop_index("ix_futures_snapshots_symbol_collected", table_name="futures_snapshots")
    op.drop_index("ix_market_snapshots_symbol_collected", table_name="market_snapshots")
    op.drop_index("ix_market_alerts_symbol_type_triggered", table_name="market_alerts")
