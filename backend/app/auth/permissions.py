"""Granular permissions and the role matrix.

Permissions are enforced at the API layer through the
require_permission dependency. Frontend navigation may
hide items the user lacks, but that is presentation only
and is never treated as enforcement. The matrix below is
the single source of truth and is mirrored in migration
0009's seed data and in docs/RBAC.md.
"""

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
    "super_admin": set(PERMISSIONS),
    "admin": {
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
    },
    "operator": {
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
    },
    "viewer": {
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
    },
}


def user_permissions(db, user) -> set[str]:
    """Effective permissions for a user.

    The AdminUserRole join table is authoritative when it
    has rows; otherwise the legacy AdminUser.role string
    is used as a fallback, so users created before the
    join rows were assigned still resolve correctly.
    Superusers always hold every permission.
    """
    from app.models import (
        AdminPermission,
        AdminRole,
        AdminRolePermission,
        AdminUserRole,
    )

    if getattr(user, "is_superuser", False):
        return set(PERMISSIONS)
    rows = (
        db.query(AdminPermission.key)
        .join(AdminRolePermission, AdminRolePermission.permission_id == AdminPermission.id)
        .join(AdminRole, AdminRole.id == AdminRolePermission.role_id)
        .join(AdminUserRole, AdminUserRole.role_id == AdminRole.id)
        .filter(AdminUserRole.admin_user_id == user.id)
        .all()
    )
    if rows:
        return {row[0] for row in rows}
    return set(ROLE_PERMISSIONS.get(user.role, set()))
