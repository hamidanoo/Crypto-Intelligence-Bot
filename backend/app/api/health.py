import logging
from datetime import datetime, timezone

from fastapi import APIRouter
from sqlalchemy import text

from app.config import settings
from app.database import SessionLocal

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.get("/health")
def health():
    """Liveness endpoint. It does not depend on the database or Redis,
    so it stays available while a dependency is being recovered."""
    return {
        "status": "ok",
        "service": settings.app_name,
        "environment": settings.environment,
        "timestamp": _utc_now_iso(),
    }


@router.get("/health/ready")
def readiness():
    """Readiness endpoint reporting each dependency honestly.

    A dependency that cannot be reached is reported as unavailable
    rather than hidden, and the overall status reflects that.
    """
    components: dict[str, str] = {}

    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        components["database"] = "ok"
    except Exception as exc:  # noqa: BLE001 - readiness must report, not raise
        logger.warning("Database readiness check failed: %s", type(exc).__name__)
        components["database"] = "unavailable"

    try:
        import redis

        client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=2)
        client.ping()
        components["redis"] = "ok"
    except Exception as exc:  # noqa: BLE001 - readiness must report, not raise
        logger.warning("Redis readiness check failed: %s", type(exc).__name__)
        components["redis"] = "unavailable"

    overall = "ready" if all(value == "ok" for value in components.values()) else "degraded"
    return {
        "status": overall,
        "service": settings.app_name,
        "environment": settings.environment,
        "timestamp": _utc_now_iso(),
        "components": components,
    }
