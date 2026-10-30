"""Add announcement sources, announcements, and collection runs.

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "announcement_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("source_type", sa.String(64), nullable=False),
        sa.Column("base_url", sa.String(512), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("polling_interval_seconds", sa.Integer(), nullable=False, server_default="300"),
        sa.Column("configuration", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_at", sa.DateTime(timezone=True)),
        sa.Column("last_error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_announcement_sources_name", "announcement_sources", ["name"], unique=True)
    op.create_table(
        "announcements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("source_name", sa.String(128), nullable=False),
        sa.Column("external_id", sa.String(128), nullable=False),
        sa.Column("code", sa.String(128)),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("slug", sa.String(512)),
        sa.Column("canonical_url", sa.String(1024), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("category_confidence", sa.String(16), nullable=False, server_default="low"),
        sa.Column("summary", sa.Text()),
        sa.Column("original_content", sa.Text()),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("verification_status", sa.String(64), nullable=False, server_default="official_website"),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("notification_status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("notified_at", sa.DateTime(timezone=True)),
        sa.Column("notification_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_notification_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["announcement_sources.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("source_id", "external_id", name="uq_announcements_source_external"),
        sa.UniqueConstraint("canonical_url", name="uq_announcements_canonical_url"),
    )
    op.create_index("ix_announcements_source_id", "announcements", ["source_id"])
    op.create_index("ix_announcements_external_id", "announcements", ["external_id"])
    op.create_index("ix_announcements_code", "announcements", ["code"])
    op.create_index("ix_announcements_category", "announcements", ["category"])
    op.create_index("ix_announcements_published_at", "announcements", ["published_at"])
    op.create_index("ix_announcements_collected_at", "announcements", ["collected_at"])
    op.create_index("ix_announcements_content_hash", "announcements", ["content_hash"])
    op.create_index("ix_announcements_notification_status", "announcements", ["notification_status"])
    op.create_table(
        "collection_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("announcements_found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("announcements_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duplicates_skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text()),
        sa.ForeignKeyConstraint(["source_id"], ["announcement_sources.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_collection_runs_source_id", "collection_runs", ["source_id"])
    op.create_index("ix_collection_runs_started_at", "collection_runs", ["started_at"])
    op.create_index("ix_collection_runs_status", "collection_runs", ["status"])


def downgrade() -> None:
    op.drop_table("collection_runs")
    op.drop_table("announcements")
    op.drop_table("announcement_sources")
