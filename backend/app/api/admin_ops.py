"""Admin operations: Telegram, integrations, notifications, scheduler, news sources.

Secrets are never returned: integration reads return a
masked suffix only, Telegram reads return configuration
flags only, and credential writes are AES-GCM encrypted
at rest. Scheduler controls accept only job ids from a
server-side allowlist and never execute arbitrary code.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.admin_common import audit, get_setting, paginate, page_response, set_setting
from app.auth.dependencies import require_csrf, require_permission
from app.auth.encryption import (
    CredentialEncryptionError,
    decrypt_secret,
    encrypt_secret,
    mask_secret,
    require_encryption_key,
)
from app.auth.ssrf import SSRFBlockedError, fetch_feed
from app.config import settings
from app.database import get_db
from app.models import (
    ApiIntegration,
    CampaignNotification,
    CollectionRun,
    CompetitionCollectionRun,
    CompetitionVolumeCollectionRun,
    MarketCollectionRun,
    NewsSource,
    TelegramGroup,
)
from app.scheduler import register_jobs, scheduler

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin-operations"])

# Job ids that the scheduler admin page may control. Any
# other job id is rejected, so no arbitrary function can
# be triggered through this endpoint.
ALLOWED_SCHEDULER_JOBS = {
    "announcement_collection",
    "alpha_processing",
    "airdrop_processing",
    "prime_sale_processing",
    "competition_processing",
    "competition_volume_tracking",
    "market_snapshot",
    "funding_collection",
    "open_interest_collection",
    "news_collection",
    "listing_processing",
    "market_movement_detection",
}

_JOB_RUN_MODELS = {
    # Phase 9 audit: announcement and volume jobs
    # previously showed last_run "unknown" even though
    # their run rows exist.
    "announcement_collection": CollectionRun,
    "competition_volume_tracking": CompetitionVolumeCollectionRun,
    "competition_processing": CompetitionCollectionRun,
    "market_snapshot": MarketCollectionRun,
    "funding_collection": MarketCollectionRun,
    "open_interest_collection": MarketCollectionRun,
    "news_collection": MarketCollectionRun,
    "listing_processing": MarketCollectionRun,
    "market_movement_detection": MarketCollectionRun,
}


def _iso(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


# ---------------------------------------------------------------- telegram


class TelegramPatchRequest(BaseModel):
    group_chat_id: str | None = None
    group_title: str | None = None
    notifications_enabled: bool | None = None
    categories: dict | None = None


class TelegramTestRequest(BaseModel):
    message: str = "Crypto Intelligence test message"


def _telegram_config(db: Session) -> dict:
    group = db.query(TelegramGroup).order_by(TelegramGroup.id).first()
    stored = get_setting(db, "telegram_notifications", {})
    return {
        "bot_configured": bool(settings.telegram_bot_token),
        "bot_username": None,
        "group_chat_id": group.chat_id if group else settings.telegram_group_id,
        "group_title": group.title if group else None,
        "notifications_enabled": bool(stored.get("enabled", True)),
        "categories": stored.get("categories", {}),
    }


@router.get("/telegram")
async def get_telegram(
    user=Depends(require_permission("telegram.view")), db: Session = Depends(get_db)
):
    return _telegram_config(db)


@router.patch("/telegram")
async def patch_telegram(
    body: TelegramPatchRequest,
    user=Depends(require_permission("telegram.manage")),
    _csrf=Depends(require_csrf),
    db: Session = Depends(get_db),
):
    group = db.query(TelegramGroup).order_by(TelegramGroup.id).first()
    if body.group_chat_id is not None:
        if group is None:
            group = TelegramGroup(chat_id=body.group_chat_id, title=body.group_title)
            db.add(group)
        else:
            group.chat_id = body.group_chat_id
            if body.group_title is not None:
                group.title = body.group_title
        db.commit()
    stored = get_setting(db, "telegram_notifications", {})
    if body.notifications_enabled is not None:
        stored["enabled"] = body.notifications_enabled
    if body.categories is not None:
        stored["categories"] = body.categories
    set_setting(db, "telegram_notifications", stored, "Telegram notification settings")
    audit(db, user, "telegram.updated", entity="telegram_group")
    return _telegram_config(db)


@router.post("/telegram/test-message")
async def telegram_test_message(
    body: TelegramTestRequest,
    user=Depends(require_permission("telegram.manage")),
    _csrf=Depends(require_csrf),
    db: Session = Depends(get_db),
):
    # Explicit user action only: this endpoint is never
    # called on page load, and it never sends without a
    # configured token and group.
    config = _telegram_config(db)
    if not settings.telegram_bot_token or not config["group_chat_id"]:
        audit(
            db,
            user,
            "telegram.test.failed",
            outcome="failure",
            details={"reason": "not_configured"},
        )
        raise HTTPException(status_code=503, detail="Telegram bot token or group is not configured")
    try:
        from aiogram import Bot

        bot = Bot(token=settings.telegram_bot_token)
        try:
            await bot.send_message(config["group_chat_id"], body.message)
        finally:
            await bot.session.close()
    except Exception as exc:
        audit(
            db,
            user,
            "telegram.test.failed",
            outcome="failure",
            details={"reason": type(exc).__name__},
        )
        raise HTTPException(status_code=502, detail="Telegram test message failed") from exc
    audit(db, user, "telegram.test.sent")
    return {"sent": True}


# ---------------------------------------------------------------- integrations


class IntegrationCreateRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=128)
    base_url: str | None = None
    api_key: str | None = None
    api_secret: str | None = None
    enabled: bool = False


class IntegrationPatchRequest(BaseModel):
    base_url: str | None = None
    api_key: str | None = None
    api_secret: str | None = None
    enabled: bool | None = None


def _serialise_integration(row: ApiIntegration) -> dict:
    return {
        "id": row.id,
        "provider": row.provider,
        "base_url": row.base_url,
        "enabled": bool(row.enabled),
        "api_key_masked": row.api_key_masked,
        "last_success_at": _iso(row.last_success_at),
        "last_error": row.last_error,
        "last_checked_at": _iso(row.updated_at),
    }


def _apply_secret(row: ApiIntegration, api_key: str | None, api_secret: str | None) -> None:
    if api_key is not None:
        row.api_key_masked = mask_secret(api_key)
    if api_secret is not None:
        require_encryption_key()
        encrypted = encrypt_secret(api_secret)
        row.encrypted_secret = encrypted["ciphertext_b64"]
        row.encrypted_nonce = encrypted["nonce_b64"]
        row.encryption_key_id = encrypted["key_id"]


@router.get("/integrations")
async def list_integrations(
    user=Depends(require_permission("integrations.view")), db: Session = Depends(get_db)
):
    rows = db.query(ApiIntegration).order_by(ApiIntegration.id).all()
    return {"items": [_serialise_integration(r) for r in rows]}


@router.post("/integrations")
async def create_integration(
    body: IntegrationCreateRequest,
    user=Depends(require_permission("integrations.manage")),
    _csrf=Depends(require_csrf),
    db: Session = Depends(get_db),
):
    if db.query(ApiIntegration).filter(ApiIntegration.provider == body.provider).first():
        raise HTTPException(status_code=400, detail="Integration already exists")
    row = ApiIntegration(provider=body.provider, base_url=body.base_url, enabled=body.enabled)
    try:
        _apply_secret(row, body.api_key, body.api_secret)
    except CredentialEncryptionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    db.add(row)
    db.commit()
    db.refresh(row)
    audit(db, user, "integration.created", entity="api_integration", entity_id=row.id)
    return _serialise_integration(row)


@router.patch("/integrations/{integration_id}")
async def patch_integration(
    integration_id: int,
    body: IntegrationPatchRequest,
    user=Depends(require_permission("integrations.manage")),
    _csrf=Depends(require_csrf),
    db: Session = Depends(get_db),
):
    row = db.query(ApiIntegration).filter(ApiIntegration.id == integration_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Integration not found")
    if body.base_url is not None:
        row.base_url = body.base_url
    if body.enabled is not None:
        row.enabled = body.enabled
    try:
        _apply_secret(row, body.api_key, body.api_secret)
    except CredentialEncryptionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    db.commit()
    audit(db, user, "integration.updated", entity="api_integration", entity_id=row.id)
    return _serialise_integration(row)


@router.post("/integrations/{integration_id}/test-connection")
async def test_integration(
    integration_id: int,
    user=Depends(require_permission("integrations.manage")),
    _csrf=Depends(require_csrf),
    db: Session = Depends(get_db),
):
    row = db.query(ApiIntegration).filter(ApiIntegration.id == integration_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Integration not found")
    # Decryption happens only in this authorised internal
    # path, and the plaintext is never returned or logged.
    if row.encrypted_secret and row.encrypted_nonce:
        try:
            decrypt_secret(
                row.encrypted_secret, row.encrypted_nonce, row.encryption_key_id or "current"
            )
        except CredentialEncryptionError as exc:
            row.last_error = "Decryption failed"
            db.commit()
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    if "binance" in row.provider.lower():
        try:
            from app.binance.client import BinanceClient

            client = BinanceClient(
                spot_base_url=row.base_url or settings.binance_spot_base_url,
                futures_base_url=settings.binance_futures_base_url,
            )
            await client.spot_ping()
            row.last_success_at = datetime.now(timezone.utc)
            row.last_error = None
            db.commit()
            audit(db, user, "integration.tested", entity="api_integration", entity_id=row.id)
            return {"status": "healthy", "detail": "Spot ping succeeded"}
        except Exception as exc:
            row.last_error = type(exc).__name__
            db.commit()
            return {"status": "degraded", "detail": f"Spot ping failed: {type(exc).__name__}"}
    row.last_success_at = datetime.now(timezone.utc)
    row.last_error = None
    db.commit()
    audit(db, user, "integration.tested", entity="api_integration", entity_id=row.id)
    return {"status": "healthy", "detail": "Stored credential decrypts successfully"}


# ---------------------------------------------------------------- notifications


class NotificationsPatchRequest(BaseModel):
    global_enabled: bool | None = None
    categories: dict | None = None
    thresholds: dict | None = None
    cooldown_minutes: int | None = Field(default=None, ge=0, le=1440)


@router.get("/notifications")
async def get_notifications(
    user=Depends(require_permission("notifications.view")), db: Session = Depends(get_db)
):
    stored = get_setting(db, "notification_settings", {})
    return {
        "global_enabled": bool(stored.get("global_enabled", True)),
        "categories": stored.get("categories", {}),
        "thresholds": stored.get("thresholds", {}),
        "cooldown_minutes": stored.get("cooldown_minutes", 60),
    }


@router.patch("/notifications")
async def patch_notifications(
    body: NotificationsPatchRequest,
    user=Depends(require_permission("notifications.manage")),
    _csrf=Depends(require_csrf),
    db: Session = Depends(get_db),
):
    stored = get_setting(db, "notification_settings", {})
    if body.global_enabled is not None:
        stored["global_enabled"] = body.global_enabled
    if body.categories is not None:
        stored["categories"] = body.categories
    if body.thresholds is not None:
        stored["thresholds"] = body.thresholds
    if body.cooldown_minutes is not None:
        stored["cooldown_minutes"] = body.cooldown_minutes
    set_setting(db, "notification_settings", stored, "Central notification settings")
    audit(db, user, "notifications.updated")
    return {
        "global_enabled": bool(stored.get("global_enabled", True)),
        "categories": stored.get("categories", {}),
        "thresholds": stored.get("thresholds", {}),
        "cooldown_minutes": stored.get("cooldown_minutes", 60),
    }


@router.get("/notifications/history")
async def notifications_history(
    user=Depends(require_permission("notifications.view")),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    total, items = paginate(
        db.query(CampaignNotification).order_by(CampaignNotification.id.desc()),
        page,
        page_size,
    )
    return page_response(
        total,
        page,
        page_size,
        [
            {
                "id": row.id,
                "entity_type": row.entity_type,
                "entity_id": row.entity_id,
                "notification_type": row.notification_type,
                "status": row.status,
                "sent_at": _iso(row.sent_at),
            }
            for row in items
        ],
    )


# ---------------------------------------------------------------- scheduler


@router.get("/scheduler")
async def list_scheduler_jobs(
    user=Depends(require_permission("scheduler.view")), db: Session = Depends(get_db)
):
    register_jobs()
    flags = get_setting(db, "scheduler_jobs", {})
    items = []
    for job in scheduler.get_jobs():
        model = _JOB_RUN_MODELS.get(job.id)
        last_run = None
        last_status = "unknown"
        if model is not None:
            run = db.query(model).order_by(model.id.desc()).first()
            if run is not None:
                last_run = _iso(
                    getattr(run, "completed_at", None)
                    or getattr(run, "completed", None)
                    or getattr(run, "started", None)
                )
                last_status = getattr(run, "status", "unknown")
        interval_minutes = None
        try:
            interval = job.trigger.interval
            interval_minutes = int(interval.total_seconds() // 60)
        except Exception:
            interval_minutes = None
        # APScheduler jobs added before the scheduler starts
        # do not expose next_run_time yet; treat that as
        # unknown rather than failing the whole page.
        try:
            next_run_time = job.next_run_time
        except Exception:
            next_run_time = None
        items.append(
            {
                "id": job.id,
                "name": job.id,
                "interval_minutes": interval_minutes,
                "next_run_time": _iso(next_run_time),
                "last_run_at": last_run,
                "last_status": last_status,
                "enabled": bool(flags.get(job.id, {}).get("enabled", next_run_time is not None)),
            }
        )
    return {"items": items}


def _scheduler_job_or_404(job_id: str):
    register_jobs()
    if job_id not in ALLOWED_SCHEDULER_JOBS:
        raise HTTPException(status_code=400, detail="Unknown scheduler job")
    job = scheduler.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Scheduler job not found")
    return job


@router.post("/scheduler/{job_id}/pause")
async def pause_job(
    job_id: str,
    user=Depends(require_permission("scheduler.manage")),
    _csrf=Depends(require_csrf),
    db: Session = Depends(get_db),
):
    _scheduler_job_or_404(job_id)
    scheduler.pause_job(job_id)
    flags = get_setting(db, "scheduler_jobs", {})
    flags[job_id] = {"enabled": False}
    set_setting(db, "scheduler_jobs", flags, "Scheduler job enabled flags")
    audit(db, user, "scheduler.paused", entity="scheduler_job", entity_id=job_id)
    return {"job_id": job_id, "status": "paused"}


@router.post("/scheduler/{job_id}/resume")
async def resume_job(
    job_id: str,
    user=Depends(require_permission("scheduler.manage")),
    _csrf=Depends(require_csrf),
    db: Session = Depends(get_db),
):
    _scheduler_job_or_404(job_id)
    scheduler.resume_job(job_id)
    flags = get_setting(db, "scheduler_jobs", {})
    flags[job_id] = {"enabled": True}
    set_setting(db, "scheduler_jobs", flags, "Scheduler job enabled flags")
    audit(db, user, "scheduler.resumed", entity="scheduler_job", entity_id=job_id)
    return {"job_id": job_id, "status": "resumed"}


@router.post("/scheduler/{job_id}/trigger")
async def trigger_job(
    job_id: str,
    user=Depends(require_permission("scheduler.trigger")),
    _csrf=Depends(require_csrf),
    db: Session = Depends(get_db),
):
    job = _scheduler_job_or_404(job_id)
    # A paused job must not be triggered into running
    # (Phase 9 audit): previously trigger reported
    # success while a paused job silently did nothing
    # (or fired despite the pause, depending on the
    # scheduler backend). Resume first, then trigger.
    flags = get_setting(db, "scheduler_jobs", {}) or {}
    if flags.get(job_id, {}).get("enabled") is False:
        raise HTTPException(
            status_code=400, detail="Scheduler job is paused; resume it before triggering"
        )
    # No "scheduler not running" refusal here: modifying
    # next_run_time is valid on a stopped scheduler and
    # the run fires as soon as it starts again. Refusing
    # would break trigger-while-stopped, which the
    # scheduler controls test covers. The paused-job
    # refusal above is the real guard: a paused job
    # must never be triggered into running.
    # Schedule an immediate run through the existing
    # scheduler; the job function itself is never
    # invoked with caller-supplied arguments.
    job.modify(next_run_time=datetime.now(timezone.utc))
    audit(db, user, "scheduler.triggered", entity="scheduler_job", entity_id=job_id)
    return {"job_id": job_id, "status": "triggered"}


# ---------------------------------------------------------------- news sources


class NewsSourceCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    source_type: str = "rss"
    feed_url: str | None = None
    enabled: bool = False


class NewsSourcePatchRequest(BaseModel):
    name: str | None = None
    feed_url: str | None = None
    enabled: bool | None = None
    reliability_note: str | None = None


def _serialise_news_source(row: NewsSource) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "source_type": row.source_type,
        "feed_url": row.feed_url,
        "enabled": bool(row.enabled),
        "reliability_note": row.reliability_note,
        "last_success_at": None,
        "last_error": None,
    }


@router.get("/news-sources")
async def list_news_sources(
    user=Depends(require_permission("news_sources.view")), db: Session = Depends(get_db)
):
    rows = db.query(NewsSource).order_by(NewsSource.id).all()
    return {"items": [_serialise_news_source(r) for r in rows]}


@router.post("/news-sources")
async def create_news_source(
    body: NewsSourceCreateRequest,
    user=Depends(require_permission("news_sources.manage")),
    _csrf=Depends(require_csrf),
    db: Session = Depends(get_db),
):
    # A source is never enabled merely because it was
    # added: enabling is a separate explicit action, and
    # the caller may still pass enabled=False only.
    if body.enabled:
        raise HTTPException(
            status_code=400,
            detail="Enable a source explicitly after adding it, not at creation",
        )
    row = NewsSource(
        name=body.name, source_type=body.source_type, feed_url=body.feed_url, enabled=False
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    audit(db, user, "news_source.created", entity="news_source", entity_id=row.id)
    return _serialise_news_source(row)


@router.patch("/news-sources/{source_id}")
async def patch_news_source(
    source_id: int,
    body: NewsSourcePatchRequest,
    user=Depends(require_permission("news_sources.manage")),
    _csrf=Depends(require_csrf),
    db: Session = Depends(get_db),
):
    row = db.query(NewsSource).filter(NewsSource.id == source_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="News source not found")
    if body.name is not None:
        row.name = body.name
    if body.feed_url is not None:
        row.feed_url = body.feed_url
    if body.enabled is not None:
        row.enabled = body.enabled
    if body.reliability_note is not None:
        row.reliability_note = body.reliability_note
    db.commit()
    audit(db, user, "news_source.updated", entity="news_source", entity_id=row.id)
    return _serialise_news_source(row)


@router.post("/news-sources/{source_id}/test")
async def test_news_source(
    source_id: int,
    user=Depends(require_permission("news_sources.manage")),
    _csrf=Depends(require_csrf),
    db: Session = Depends(get_db),
):
    row = db.query(NewsSource).filter(NewsSource.id == source_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="News source not found")
    if not row.feed_url:
        raise HTTPException(status_code=400, detail="News source has no feed URL")
    try:
        result = fetch_feed(row.feed_url)
    except SSRFBlockedError as exc:
        audit(
            db,
            user,
            "news_source.test.failed",
            entity="news_source",
            entity_id=row.id,
            outcome="failure",
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Feed fetch failed") from exc
    audit(db, user, "news_source.tested", entity="news_source", entity_id=row.id)
    return {"ok": True, "status": result["status"], "detail": "Feed fetched successfully"}
