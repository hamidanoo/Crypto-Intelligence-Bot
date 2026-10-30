"""Admin dashboard, user, role, audit, and settings endpoints.

Every endpoint is permission-gated at the API layer.
Dashboard statistics come from real database queries
with bounded counts; stale or unavailable services are
reported as such, never as healthy merely because a
configuration value exists.
"""

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.admin_common import audit, paginate, page_response, set_setting
from app.auth.dependencies import require_csrf, require_permission
from app.auth.passwords import hash_password
from app.auth.permissions import PERMISSIONS, user_permissions
from app.config import settings
from app.database import get_db
from app.models import (
    AdminPermission,
    AdminRole,
    AdminRolePermission,
    AdminUser,
    AdminUserRole,
    AirdropCampaign,
    AlphaToken,
    Announcement,
    AuditLog,
    Competition,
    CompetitionVolumeInterval,
    CryptoNews,
    MarketCollectionRun,
    MarketSnapshot,
    PrimeSale,
    SystemSetting,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])


def _aware(value):
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _iso(value):
    value = _aware(value)
    return value.isoformat() if value else None


# ---------------------------------------------------------------- dashboard


@router.get("/dashboard/overview")
async def dashboard_overview(
    user=Depends(require_permission("dashboard.view")), db: Session = Depends(get_db)
):
    try:
        now = datetime.now(timezone.utc)
        day_ago = now - timedelta(days=1)
        latest_volume = (
            db.query(CompetitionVolumeInterval)
            .order_by(CompetitionVolumeInterval.interval_start.desc())
            .first()
        )
        latest_snapshot = (
            db.query(MarketSnapshot).order_by(MarketSnapshot.collected_at.desc()).first()
        )
        latest_news = db.query(CryptoNews).order_by(CryptoNews.created_at.desc()).limit(5).all()
        latest_errors = (
            db.query(MarketCollectionRun)
            .filter(MarketCollectionRun.error_message.isnot(None))
            .order_by(MarketCollectionRun.id.desc())
            .limit(5)
            .all()
        )
        from app.scheduler import scheduler

        db_status = "healthy"
        try:
            db.execute(__import__("sqlalchemy").text("SELECT 1"))
        except Exception:
            db_status = "unavailable"
        redis_status = "unknown"
        try:
            import redis.asyncio as redis_lib

            client = redis_lib.Redis.from_url(settings.redis_url, socket_connect_timeout=1)
            await client.ping()
            await client.aclose()
            redis_status = "healthy"
        except Exception:
            redis_status = "unavailable"
        market_stale = True
        if latest_snapshot is not None and latest_snapshot.collected_at is not None:
            collected = _aware(latest_snapshot.collected_at)
            market_stale = now - collected > timedelta(minutes=settings.market_freshness_minutes)
        telegram_configured = bool(settings.telegram_bot_token) and bool(settings.telegram_group_id)
        return {
            "announcements_total": db.query(Announcement).count(),
            "announcements_new": db.query(Announcement)
            .filter(Announcement.collected_at >= day_ago)
            .count(),
            "active_alpha_tokens": db.query(AlphaToken).count(),
            "active_airdrops": db.query(AirdropCampaign)
            .filter(AirdropCampaign.status.in_(["ACTIVE", "UPCOMING", "CLAIMING"]))
            .count(),
            "upcoming_prime_sales": db.query(PrimeSale)
            .filter(PrimeSale.status.in_(["UPCOMING", "ACTIVE"]))
            .count(),
            "active_competitions": db.query(Competition)
            .filter(Competition.status.in_(["ACTIVE", "UPCOMING"]))
            .count(),
            "latest_competition_volume": (
                {
                    "competition_id": latest_volume.competition_id,
                    "trading_pair": latest_volume.trading_pair,
                    "public_base_volume": (
                        str(latest_volume.public_base_volume)
                        if latest_volume.public_base_volume is not None
                        else None
                    ),
                    "public_quote_volume": (
                        str(latest_volume.public_quote_volume)
                        if latest_volume.public_quote_volume is not None
                        else None
                    ),
                    "interval_start": _iso(latest_volume.interval_start),
                }
                if latest_volume
                else None
            ),
            "market_status": {
                "status": "stale" if market_stale else "healthy",
                "latest_snapshot_at": _iso(
                    latest_snapshot.collected_at if latest_snapshot else None
                ),
            },
            "futures_status": {
                "availability": "unavailable",
                "last_collection_status": (latest_errors[0].status if latest_errors else "unknown"),
            },
            "latest_news": [
                {
                    "id": item.id,
                    "headline": item.headline,
                    "category": item.category,
                    "published_at": _iso(item.published_at),
                    "original_url": item.original_url,
                }
                for item in latest_news
            ],
            "telegram_status": {
                "configured": telegram_configured,
                "group_configured": bool(settings.telegram_group_id),
            },
            "scheduler_status": {
                "running": bool(scheduler.running),
                "job_count": len(scheduler.get_jobs()),
            },
            "database_status": db_status,
            "redis_status": redis_status,
            "latest_collection_errors": [
                {
                    "module": run.job_name,
                    "error": run.error_message,
                    "at": _iso(run.completed_at),
                }
                for run in latest_errors
            ],
            "dashboard_refresh_interval_seconds": settings.dashboard_refresh_interval_seconds,
        }
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc


@router.get("/dashboard/activity")
async def dashboard_activity(
    user=Depends(require_permission("dashboard.view")), db: Session = Depends(get_db)
):
    def _by_day(model, column):
        start = datetime.now(timezone.utc) - timedelta(days=14)
        rows = (
            db.query(func.date(column), func.count())
            .filter(column >= start)
            .group_by(func.date(column))
            .order_by(func.date(column))
            .all()
        )
        return [{"date": str(day), "count": int(count)} for day, count in rows]

    try:
        return {
            "announcements_by_day": _by_day(Announcement, Announcement.collected_at),
            "news_by_day": _by_day(CryptoNews, CryptoNews.created_at),
            "volume_by_day": _by_day(
                CompetitionVolumeInterval, CompetitionVolumeInterval.collected_at
            ),
            "notifications_by_day": [],
        }
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc


@router.get("/dashboard/health")
async def dashboard_health(
    user=Depends(require_permission("dashboard.view")), db: Session = Depends(get_db)
):
    services = []
    try:
        db.execute(__import__("sqlalchemy").text("SELECT 1"))
        services.append(
            {
                "name": "database",
                "status": "healthy",
                "detail": "Connection check succeeded",
                "last_success_at": None,
            }
        )
    except Exception:
        services.append(
            {
                "name": "database",
                "status": "unavailable",
                "detail": "Connection check failed",
                "last_success_at": None,
            }
        )
    try:
        import redis.asyncio as redis_lib

        client = redis_lib.Redis.from_url(settings.redis_url, socket_connect_timeout=1)
        await client.ping()
        await client.aclose()
        services.append(
            {
                "name": "redis",
                "status": "healthy",
                "detail": "Ping succeeded",
                "last_success_at": None,
            }
        )
    except Exception:
        services.append(
            {
                "name": "redis",
                "status": "unavailable",
                "detail": "Ping failed or Redis not reachable",
                "last_success_at": None,
            }
        )
    from app.scheduler import scheduler

    services.append(
        {
            "name": "scheduler",
            "status": "healthy" if scheduler.running else "degraded",
            "detail": f"{len(scheduler.get_jobs())} jobs registered",
            "last_success_at": None,
        }
    )
    services.append(
        {
            "name": "telegram",
            "status": (
                "healthy"
                if settings.telegram_bot_token and settings.telegram_group_id
                else "degraded"
            ),
            "detail": (
                "Bot token and group configured"
                if settings.telegram_bot_token and settings.telegram_group_id
                else "Bot token or group not configured"
            ),
            "last_success_at": None,
        }
    )
    services.append(
        {
            "name": "binance_spot",
            "status": "unknown",
            "detail": "Status comes from the last market collection run; check the market page",
            "last_success_at": None,
        }
    )
    services.append(
        {
            "name": "binance_futures",
            "status": "unavailable",
            "detail": "Futures endpoints return HTTP 451 here (restricted location)",
            "last_success_at": None,
        }
    )
    latest_announcement = db.query(Announcement).order_by(Announcement.collected_at.desc()).first()
    services.append(
        {
            "name": "announcement_collection",
            "status": "healthy" if latest_announcement else "unknown",
            "detail": (
                "Last announcement collected"
                if latest_announcement
                else "No announcements collected yet"
            ),
            "last_success_at": _iso(
                latest_announcement.collected_at if latest_announcement else None
            ),
        }
    )
    return {"services": services}


# ---------------------------------------------------------------- users


class UserCreateRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    email: str = Field(max_length=255)
    password: str = Field(min_length=8, max_length=256)
    role: str = Field(default="viewer", max_length=64)
    is_active: bool = True


class UserPatchRequest(BaseModel):
    email: str | None = None
    role: str | None = None
    is_active: bool | None = None


def _serialise_user(user: AdminUser, db: Session) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "is_superuser": bool(user.is_superuser),
        "is_active": bool(user.is_active),
        "created_at": _iso(user.created_at),
        "permissions": sorted(user_permissions(db, user)),
    }


def _assign_role(db: Session, user: AdminUser, role_name: str) -> None:
    role = db.query(AdminRole).filter(AdminRole.name == role_name).first()
    if role is None:
        raise HTTPException(status_code=400, detail=f"Unknown role: {role_name}")
    db.query(AdminUserRole).filter(AdminUserRole.admin_user_id == user.id).delete()
    db.add(AdminUserRole(admin_user_id=user.id, role_id=role.id))
    user.role = role_name
    user.is_superuser = role_name == "super_admin"


def _count_active_super_admins(db: Session) -> int:
    return (
        db.query(AdminUser)
        .filter(AdminUser.is_superuser.is_(True), AdminUser.is_active.is_(True))
        .count()
    )


def _get_user_or_404(db: Session, user_id: int) -> AdminUser:
    user = db.query(AdminUser).filter(AdminUser.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="Administrator not found")
    return user


@router.get("/users")
async def list_users(
    user=Depends(require_permission("users.view")),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    total, items = paginate(db.query(AdminUser).order_by(AdminUser.id), page, page_size)
    return page_response(total, page, page_size, [_serialise_user(u, db) for u in items])


@router.post("/users")
async def create_user(
    body: UserCreateRequest,
    user=Depends(require_permission("users.manage")),
    _csrf=Depends(require_csrf),
    db: Session = Depends(get_db),
):
    if body.role not in ("super_admin", "admin", "operator", "viewer"):
        raise HTTPException(status_code=400, detail="Unknown role")
    # A caller cannot grant a role whose permissions they
    # do not themselves hold (privilege-escalation guard).
    caller_permissions = user_permissions(db, user)
    from app.auth.permissions import ROLE_PERMISSIONS

    missing = ROLE_PERMISSIONS[body.role] - caller_permissions
    if missing:
        raise HTTPException(status_code=403, detail="Cannot grant permissions you do not possess")
    if db.query(AdminUser).filter(AdminUser.username == body.username).first():
        raise HTTPException(status_code=400, detail="Username already exists")
    if db.query(AdminUser).filter(AdminUser.email == body.email).first():
        raise HTTPException(status_code=400, detail="Email already exists")
    new_user = AdminUser(
        username=body.username,
        email=body.email,
        password_hash=hash_password(body.password),
        role=body.role,
        is_active=body.is_active,
        is_superuser=body.role == "super_admin",
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    _assign_role(db, new_user, body.role)
    db.commit()
    audit(db, user, "admin.created", entity="admin_user", entity_id=new_user.id)
    return _serialise_user(new_user, db)


@router.get("/users/{user_id}")
async def get_user(
    user_id: int,
    user=Depends(require_permission("users.view")),
    db: Session = Depends(get_db),
):
    return _serialise_user(_get_user_or_404(db, user_id), db)


@router.patch("/users/{user_id}")
async def patch_user(
    user_id: int,
    body: UserPatchRequest,
    user=Depends(require_permission("users.manage")),
    _csrf=Depends(require_csrf),
    db: Session = Depends(get_db),
):
    target = _get_user_or_404(db, user_id)
    if body.role is not None:
        if body.role not in ("super_admin", "admin", "operator", "viewer"):
            raise HTTPException(status_code=400, detail="Unknown role")
        # The last-active-Super-Admin guard runs before the
        # self-role-change guard, so demoting the final
        # Super Admin is reported as that specific error
        # even when the caller is that administrator.
        if (
            target.is_superuser
            and body.role != "super_admin"
            and _count_active_super_admins(db) <= 1
        ):
            raise HTTPException(status_code=400, detail="Cannot demote the last active Super Admin")
        if target.id == user.id and body.role != target.role:
            raise HTTPException(status_code=403, detail="Cannot change your own role")
        from app.auth.permissions import ROLE_PERMISSIONS

        missing = ROLE_PERMISSIONS[body.role] - user_permissions(db, user)
        if missing:
            raise HTTPException(
                status_code=403, detail="Cannot grant permissions you do not possess"
            )
        _assign_role(db, target, body.role)
    if body.email is not None:
        target.email = body.email
    if body.is_active is not None:
        if (
            target.id != user.id
            and target.is_superuser
            and body.is_active is False
            and _count_active_super_admins(db) <= 1
        ):
            raise HTTPException(
                status_code=400, detail="Cannot deactivate the last active Super Admin"
            )
        if target.id == user.id and body.is_active is False:
            raise HTTPException(status_code=403, detail="Cannot deactivate yourself")
        target.is_active = body.is_active
    db.commit()
    audit(db, user, "admin.updated", entity="admin_user", entity_id=target.id)
    return _serialise_user(target, db)


@router.post("/users/{user_id}/deactivate")
async def deactivate_user(
    user_id: int,
    user=Depends(require_permission("users.manage")),
    _csrf=Depends(require_csrf),
    db: Session = Depends(get_db),
):
    target = _get_user_or_404(db, user_id)
    if target.id == user.id:
        raise HTTPException(status_code=403, detail="Cannot deactivate yourself")
    if target.is_superuser and _count_active_super_admins(db) <= 1:
        raise HTTPException(status_code=400, detail="Cannot deactivate the last active Super Admin")
    target.is_active = False
    db.commit()
    audit(db, user, "admin.deactivated", entity="admin_user", entity_id=target.id)
    return _serialise_user(target, db)


# ---------------------------------------------------------------- roles


class RoleCreateRequest(BaseModel):
    name: str = Field(min_length=3, max_length=64)
    permissions: list[str] = Field(default_factory=list)


class RolePatchRequest(BaseModel):
    name: str | None = None
    permissions: list[str] | None = None


def _serialise_role(role: AdminRole, db: Session) -> dict:
    keys = (
        db.query(AdminPermission.key)
        .join(AdminRolePermission, AdminRolePermission.permission_id == AdminPermission.id)
        .filter(AdminRolePermission.role_id == role.id)
        .all()
    )
    return {"id": role.id, "name": role.name, "permissions": sorted(k[0] for k in keys)}


@router.get("/roles")
async def list_roles(user=Depends(require_permission("roles.view")), db: Session = Depends(get_db)):
    roles = db.query(AdminRole).order_by(AdminRole.id).all()
    return {"items": [_serialise_role(r, db) for r in roles]}


@router.post("/roles")
async def create_role(
    body: RoleCreateRequest,
    user=Depends(require_permission("roles.manage")),
    _csrf=Depends(require_csrf),
    db: Session = Depends(get_db),
):
    unknown = [p for p in body.permissions if p not in PERMISSIONS]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown permissions: {unknown}")
    missing = set(body.permissions) - user_permissions(db, user)
    if missing:
        raise HTTPException(status_code=403, detail="Cannot grant permissions you do not possess")
    if db.query(AdminRole).filter(AdminRole.name == body.name).first():
        raise HTTPException(status_code=400, detail="Role already exists")
    role = AdminRole(name=body.name)
    db.add(role)
    db.commit()
    db.refresh(role)
    for key in body.permissions:
        perm = db.query(AdminPermission).filter(AdminPermission.key == key).first()
        db.add(AdminRolePermission(role_id=role.id, permission_id=perm.id))
    db.commit()
    audit(db, user, "role.created", entity="admin_role", entity_id=role.id)
    return _serialise_role(role, db)


@router.patch("/roles/{role_id}")
async def patch_role(
    role_id: int,
    body: RolePatchRequest,
    user=Depends(require_permission("roles.manage")),
    _csrf=Depends(require_csrf),
    db: Session = Depends(get_db),
):
    role = db.query(AdminRole).filter(AdminRole.id == role_id).first()
    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")
    if body.permissions is not None:
        unknown = [p for p in body.permissions if p not in PERMISSIONS]
        if unknown:
            raise HTTPException(status_code=400, detail=f"Unknown permissions: {unknown}")
        missing = set(body.permissions) - user_permissions(db, user)
        if missing:
            raise HTTPException(
                status_code=403, detail="Cannot grant permissions you do not possess"
            )
        db.query(AdminRolePermission).filter(AdminRolePermission.role_id == role.id).delete()
        for key in body.permissions:
            perm = db.query(AdminPermission).filter(AdminPermission.key == key).first()
            db.add(AdminRolePermission(role_id=role.id, permission_id=perm.id))
    if body.name is not None:
        role.name = body.name
    db.commit()
    audit(db, user, "role.updated", entity="admin_role", entity_id=role.id)
    return _serialise_role(role, db)


@router.get("/permissions")
async def list_permissions(user=Depends(require_permission("users.view"))):
    return {"permissions": list(PERMISSIONS)}


# ---------------------------------------------------------------- audit logs


@router.get("/audit-logs")
async def list_audit_logs(
    user=Depends(require_permission("audit.view")),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    action: str | None = None,
    actor: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
):
    query = db.query(AuditLog).order_by(AuditLog.id.desc())
    if action:
        query = query.filter(AuditLog.action == action)
    if actor:
        query = query.filter(AuditLog.actor.ilike(f"%{actor}%"))
    if date_from:
        try:
            query = query.filter(AuditLog.created_at >= datetime.fromisoformat(date_from))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_from")
    if date_to:
        try:
            query = query.filter(AuditLog.created_at <= datetime.fromisoformat(date_to))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_to")
    total, items = paginate(query, page, page_size)
    return page_response(
        total,
        page,
        page_size,
        [
            {
                "id": row.id,
                "admin_user_id": row.admin_user_id,
                "actor": row.actor,
                "action": row.action,
                "entity": row.entity,
                "entity_id": row.entity_id,
                "outcome": row.outcome,
                "correlation_id": row.correlation_id,
                "ip_address": row.ip_address,
                "created_at": _iso(row.created_at),
                "details": row.details or {},
            }
            for row in items
        ],
    )


# ---------------------------------------------------------------- system settings


class SystemSettingPatchRequest(BaseModel):
    key: str = Field(min_length=1, max_length=128)
    value: dict = Field(default_factory=dict)


@router.get("/system-settings")
async def list_system_settings(
    user=Depends(require_permission("settings.view")), db: Session = Depends(get_db)
):
    rows = db.query(SystemSetting).order_by(SystemSetting.key).all()
    return {
        "items": [
            {"key": row.key, "value": row.value or {}, "description": row.description}
            for row in rows
        ]
    }


@router.patch("/system-settings")
async def patch_system_settings(
    body: SystemSettingPatchRequest,
    user=Depends(require_permission("settings.manage")),
    _csrf=Depends(require_csrf),
    db: Session = Depends(get_db),
):
    set_setting(db, body.key, body.value)
    audit(db, user, "settings.updated", entity="system_setting", entity_id=body.key)
    return {"key": body.key, "value": body.value}
