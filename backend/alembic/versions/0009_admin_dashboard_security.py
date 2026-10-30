"""Add administrator authentication, RBAC, sessions, and credential encryption.

Revision ID: 0009
Revises: 0008

Roles and permissions are seeded idempotently with
INSERT ... SELECT ... WHERE NOT EXISTS, which works on
both SQLite and PostgreSQL. The downgrade drops the new
tables and columns in reverse order; seeded role and
permission rows are removed with the tables themselves.
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

PERMISSIONS = [
    "dashboard.view",
    "users.view",
    "users.manage",
    "roles.view",
    "roles.manage",
    "audit.view",
    "integrations.view",
    "integrations.manage",
    "telegram.view",
    "telegram.manage",
    "notifications.view",
    "notifications.manage",
    "settings.view",
    "settings.manage",
    "scheduler.view",
    "scheduler.manage",
    "scheduler.trigger",
    "collections.run",
    "announcements.view",
    "announcements.manage",
    "intelligence.view",
    "intelligence.manage",
    "competitions.view",
    "competitions.manage",
    "volume.view",
    "volume.manage",
    "market.view",
    "market.manage",
    "news.view",
    "news.manage",
    "news_sources.view",
    "news_sources.manage",
]

ROLE_PERMISSIONS = {
    "super_admin": PERMISSIONS,
    "admin": [
        "dashboard.view",
        "users.view",
        "roles.view",
        "audit.view",
        "integrations.view",
        "telegram.view",
        "telegram.manage",
        "notifications.view",
        "notifications.manage",
        "settings.view",
        "scheduler.view",
        "scheduler.manage",
        "scheduler.trigger",
        "collections.run",
        "announcements.view",
        "announcements.manage",
        "intelligence.view",
        "intelligence.manage",
        "competitions.view",
        "competitions.manage",
        "volume.view",
        "volume.manage",
        "market.view",
        "market.manage",
        "news.view",
        "news.manage",
        "news_sources.view",
        "news_sources.manage",
    ],
    "operator": [
        "dashboard.view",
        "telegram.view",
        "notifications.view",
        "notifications.manage",
        "scheduler.view",
        "collections.run",
        "announcements.view",
        "intelligence.view",
        "competitions.view",
        "volume.view",
        "market.view",
        "news.view",
    ],
    "viewer": [
        "dashboard.view",
        "telegram.view",
        "notifications.view",
        "scheduler.view",
        "announcements.view",
        "intelligence.view",
        "competitions.view",
        "volume.view",
        "market.view",
        "news.view",
        "integrations.view",
    ],
}


def _timestamps():
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def _seed_roles_permissions() -> None:
    bind = op.get_bind()
    for role in ROLE_PERMISSIONS:
        bind.execute(
            sa.text(
                "INSERT INTO admin_roles (name, created_at, updated_at) "
                "SELECT :name, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP "
                "WHERE NOT EXISTS (SELECT 1 FROM admin_roles WHERE name = :name)"
            ),
            {"name": role},
        )
    for permission in PERMISSIONS:
        bind.execute(
            sa.text(
                "INSERT INTO admin_permissions (key, created_at, updated_at) "
                "SELECT :key, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP "
                "WHERE NOT EXISTS (SELECT 1 FROM admin_permissions WHERE key = :key)"
            ),
            {"key": permission},
        )
    for role, permissions in ROLE_PERMISSIONS.items():
        for permission in permissions:
            bind.execute(
                sa.text(
                    "INSERT INTO admin_role_permissions (role_id, permission_id) "
                    "SELECT r.id, p.id FROM admin_roles r, admin_permissions p "
                    "WHERE r.name = :role AND p.key = :permission "
                    "AND NOT EXISTS (SELECT 1 FROM admin_role_permissions arp "
                    "WHERE arp.role_id = r.id AND arp.permission_id = p.id)"
                ),
                {"role": role, "permission": permission},
            )


def upgrade() -> None:
    op.create_table(
        "admin_roles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("description", sa.String(255)),
        *_timestamps(),
    )
    op.create_index("ix_admin_roles_name", "admin_roles", ["name"], unique=True)
    op.create_table(
        "admin_permissions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("description", sa.String(255)),
        *_timestamps(),
    )
    op.create_index("ix_admin_permissions_key", "admin_permissions", ["key"], unique=True)
    op.create_table(
        "admin_role_permissions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "role_id",
            sa.Integer(),
            sa.ForeignKey("admin_roles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "permission_id",
            sa.Integer(),
            sa.ForeignKey("admin_permissions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Inline constraint: SQLite cannot add a unique
        # constraint with ALTER TABLE after creation.
        sa.UniqueConstraint(
            "role_id", "permission_id", name="uq_admin_role_permissions_role_permission"
        ),
    )
    op.create_index("ix_admin_role_permissions_role_id", "admin_role_permissions", ["role_id"])
    op.create_index(
        "ix_admin_role_permissions_permission_id", "admin_role_permissions", ["permission_id"]
    )
    op.create_table(
        "admin_user_roles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "admin_user_id",
            sa.Integer(),
            sa.ForeignKey("admin_users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "role_id",
            sa.Integer(),
            sa.ForeignKey("admin_roles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "admin_user_id", "role_id", name="uq_admin_user_roles_user_role"
        ),
    )
    op.create_index("ix_admin_user_roles_admin_user_id", "admin_user_roles", ["admin_user_id"])
    op.create_index("ix_admin_user_roles_role_id", "admin_user_roles", ["role_id"])
    op.create_table(
        "admin_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "admin_user_id",
            sa.Integer(),
            sa.ForeignKey("admin_users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("session_token_hash", sa.String(128), nullable=False),
        sa.Column("csrf_token", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("ip_address", sa.String(64)),
        sa.Column("user_agent", sa.String(255)),
    )
    op.create_index("ix_admin_sessions_admin_user_id", "admin_sessions", ["admin_user_id"])
    op.create_index(
        "ix_admin_sessions_session_token_hash",
        "admin_sessions",
        ["session_token_hash"],
        unique=True,
    )
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "admin_user_id",
            sa.Integer(),
            sa.ForeignKey("admin_users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_password_reset_tokens_admin_user_id", "password_reset_tokens", ["admin_user_id"]
    )
    op.create_index(
        "ix_password_reset_tokens_token_hash",
        "password_reset_tokens",
        ["token_hash"],
        unique=True,
    )
    with op.batch_alter_table("admin_users") as batch:
        batch.add_column(
            sa.Column("failed_login_attempts", sa.Integer(), nullable=False, server_default="0")
        )
        batch.add_column(sa.Column("locked_until", sa.DateTime(timezone=True)))
    with op.batch_alter_table("api_integrations") as batch:
        batch.add_column(sa.Column("encrypted_secret", sa.Text()))
        batch.add_column(sa.Column("encrypted_nonce", sa.String(128)))
        batch.add_column(sa.Column("encryption_key_id", sa.String(64)))
    with op.batch_alter_table("audit_logs") as batch:
        batch.add_column(sa.Column("correlation_id", sa.String(64)))
        batch.add_column(sa.Column("ip_address", sa.String(64)))
        batch.add_column(
            sa.Column("outcome", sa.String(32), nullable=False, server_default="success")
        )
    op.create_index("ix_audit_logs_correlation_id", "audit_logs", ["correlation_id"])
    _seed_roles_permissions()


def downgrade() -> None:
    op.drop_index("ix_audit_logs_correlation_id", table_name="audit_logs")
    with op.batch_alter_table("audit_logs") as batch:
        batch.drop_column("outcome")
        batch.drop_column("ip_address")
        batch.drop_column("correlation_id")
    with op.batch_alter_table("api_integrations") as batch:
        batch.drop_column("encryption_key_id")
        batch.drop_column("encrypted_nonce")
        batch.drop_column("encrypted_secret")
    with op.batch_alter_table("admin_users") as batch:
        batch.drop_column("locked_until")
        batch.drop_column("failed_login_attempts")
    op.drop_index("ix_password_reset_tokens_token_hash", table_name="password_reset_tokens")
    op.drop_index("ix_password_reset_tokens_admin_user_id", table_name="password_reset_tokens")
    op.drop_table("password_reset_tokens")
    op.drop_index("ix_admin_sessions_session_token_hash", table_name="admin_sessions")
    op.drop_index("ix_admin_sessions_admin_user_id", table_name="admin_sessions")
    op.drop_table("admin_sessions")
    op.drop_index("ix_admin_user_roles_role_id", table_name="admin_user_roles")
    op.drop_index("ix_admin_user_roles_admin_user_id", table_name="admin_user_roles")
    op.drop_table("admin_user_roles")
    op.drop_index("ix_admin_role_permissions_permission_id", table_name="admin_role_permissions")
    op.drop_index("ix_admin_role_permissions_role_id", table_name="admin_role_permissions")
    op.drop_table("admin_role_permissions")
    op.drop_index("ix_admin_permissions_key", table_name="admin_permissions")
    op.drop_table("admin_permissions")
    op.drop_index("ix_admin_roles_name", table_name="admin_roles")
    op.drop_table("admin_roles")
