import logging
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.announcements.classifier import CATEGORIES
from app.announcements.client import AnnouncementAPIError, BinanceAnnouncementClient
from app.announcements.service import collect_from_source_async, ensure_default_source
from app.database import get_db
from app.models import Announcement, AnnouncementSource, CollectionRun
from app.rate_limit import check_rate_limit

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/announcements", tags=["announcements"])


class CollectRequest(BaseModel):
    source_id: int | None = None
    page_size: int | None = Field(default=None, ge=1, le=100)


class SourcePatchRequest(BaseModel):
    enabled: bool | None = None
    polling_interval_seconds: int | None = Field(default=None, ge=60, le=86400)
    configuration: dict | None = None


def _serialise_source(source: AnnouncementSource) -> dict:
    return {
        "id": source.id,
        "name": source.name,
        "source_type": source.source_type,
        "base_url": source.base_url,
        "enabled": source.enabled,
        "polling_interval_seconds": source.polling_interval_seconds,
        "configuration": source.configuration or {},
        "last_success_at": source.last_success_at.isoformat() if source.last_success_at else None,
        "last_error_at": source.last_error_at.isoformat() if source.last_error_at else None,
        "last_error_message": source.last_error_message,
        "created_at": source.created_at.isoformat() if source.created_at else None,
        "updated_at": source.updated_at.isoformat() if source.updated_at else None,
    }


def _serialise_announcement(announcement: Announcement) -> dict:
    return {
        "id": announcement.id,
        "source_id": announcement.source_id,
        "source_name": announcement.source_name,
        "external_id": announcement.external_id,
        "code": announcement.code,
        "title": announcement.title,
        "slug": announcement.slug,
        "canonical_url": announcement.canonical_url,
        "category": announcement.category,
        "category_confidence": announcement.category_confidence,
        "summary": announcement.summary,
        "published_at": (
            announcement.published_at.isoformat() if announcement.published_at else None
        ),
        "collected_at": (
            announcement.collected_at.isoformat() if announcement.collected_at else None
        ),
        "content_hash": announcement.content_hash,
        "verification_status": announcement.verification_status,
        "metadata": announcement.metadata_json or {},
        "notification_status": announcement.notification_status,
        "notified_at": announcement.notified_at.isoformat() if announcement.notified_at else None,
        "notification_attempts": announcement.notification_attempts,
    }


def _serialise_run(run: CollectionRun) -> dict:
    return {
        "id": run.id,
        "source_id": run.source_id,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "status": run.status,
        "announcements_found": run.announcements_found,
        "announcements_created": run.announcements_created,
        "duplicates_skipped": run.duplicates_skipped,
        "error_message": run.error_message,
    }


@router.get("")
async def list_announcements(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: str | None = None,
    source_id: int | None = None,
    search: str | None = None,
    published_from: datetime | None = None,
    published_to: datetime | None = None,
    sort: str = Query("published_at_desc"),
    db: Session = Depends(get_db),
):
    check_rate_limit(request)
    try:
        return _list_announcements_impl(
            db, page, page_size, category, source_id, search, published_from, published_to, sort
        )
    except SQLAlchemyError as exc:
        logger.warning("Announcement list database error: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Database unavailable") from exc


def _list_announcements_impl(
    db, page, page_size, category, source_id, search, published_from, published_to, sort
):
    query = db.query(Announcement)
    if category:
        if category.upper() not in CATEGORIES:
            raise HTTPException(status_code=400, detail=f"Unknown category: {category}")
        query = query.filter(Announcement.category == category.upper())
    if source_id is not None:
        query = query.filter(Announcement.source_id == source_id)
    if search:
        query = query.filter(Announcement.title.ilike(f"%{search}%"))
    if published_from is not None:
        query = query.filter(Announcement.published_at >= published_from)
    if published_to is not None:
        query = query.filter(Announcement.published_at <= published_to)
    if sort == "published_at_asc":
        query = query.order_by(Announcement.published_at.asc().nulls_last(), Announcement.id.asc())
    elif sort == "collected_at_desc":
        query = query.order_by(Announcement.collected_at.desc(), Announcement.id.desc())
    else:
        query = query.order_by(
            Announcement.published_at.desc().nulls_last(), Announcement.id.desc()
        )
    total = query.count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_serialise_announcement(item) for item in items],
    }


@router.get("/categories")
async def list_categories(request: Request, db: Session = Depends(get_db)):
    check_rate_limit(request)
    try:
        counts: dict[str, int] = {}
        for row in db.query(Announcement.category).all():
            counts[row[0]] = counts.get(row[0], 0) + 1
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {
        "categories": CATEGORIES,
        "counts": counts,
    }


@router.get("/sources")
async def list_sources(request: Request, db: Session = Depends(get_db)):
    check_rate_limit(request)
    try:
        sources = db.query(AnnouncementSource).order_by(AnnouncementSource.id.asc()).all()
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {"sources": [_serialise_source(source) for source in sources]}


@router.get("/collection-runs")
async def list_collection_runs(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    source_id: int | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
):
    check_rate_limit(request)
    try:
        query = db.query(CollectionRun)
        if source_id is not None:
            query = query.filter(CollectionRun.source_id == source_id)
        if status:
            query = query.filter(CollectionRun.status == status)
        query = query.order_by(CollectionRun.started_at.desc(), CollectionRun.id.desc())
        total = query.count()
        items = query.offset((page - 1) * page_size).limit(page_size).all()
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_serialise_run(item) for item in items],
    }


@router.get("/{announcement_id}")
async def get_announcement(announcement_id: int, request: Request, db: Session = Depends(get_db)):
    check_rate_limit(request)
    try:
        announcement = db.query(Announcement).filter_by(id=announcement_id).first()
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    if announcement is None:
        raise HTTPException(status_code=404, detail="Announcement not found")
    return _serialise_announcement(announcement)


async def _collect_sources(
    db: Session, sources: list[AnnouncementSource]
) -> tuple[list[dict], int, int]:
    runs: list[dict] = []
    created_total = 0
    skipped_total = 0
    for source in sources:
        client = BinanceAnnouncementClient(base_url=source.base_url)
        try:
            run, _created = await collect_from_source_async(db, source, client)
            runs.append(_serialise_run(run))
            created_total += run.announcements_created
            skipped_total += run.duplicates_skipped
        except AnnouncementAPIError as exc:
            # The run was already recorded as failed by the service.
            latest = (
                db.query(CollectionRun)
                .filter_by(source_id=source.id)
                .order_by(CollectionRun.id.desc())
                .first()
            )
            runs.append(
                _serialise_run(latest)
                if latest
                else {"source_id": source.id, "status": "failed", "error_message": str(exc)}
            )
    return runs, created_total, skipped_total


@router.post("/collect")
async def collect_announcements(
    request: Request,
    payload: CollectRequest | None = Body(default=None),
    db: Session = Depends(get_db),
):
    """Manual collection. Authentication for admin operations
    is a Phase 8 feature; in Phase 3 this endpoint is not
    admin-gated, so it must only be exposed behind the
    deployment's own access controls. See
    docs/ANNOUNCEMENT_MONITOR.md."""
    check_rate_limit(request)
    try:
        if payload and payload.source_id is not None:
            source = db.query(AnnouncementSource).filter_by(id=payload.source_id).first()
            if source is None:
                raise HTTPException(status_code=404, detail="Announcement source not found")
            if not source.enabled:
                raise HTTPException(status_code=400, detail="Announcement source is disabled")
            sources = [source]
        else:
            sources = db.query(AnnouncementSource).filter_by(enabled=True).all()
            if not sources:
                sources = [ensure_default_source(db)]
        if payload and payload.page_size is not None:
            for source in sources:
                config = dict(source.configuration or {})
                config["page_size"] = payload.page_size
                source.configuration = config
        runs, created, skipped = await _collect_sources(db, sources)
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        logger.warning("Announcement collection database error: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Database unavailable for collection") from exc
    body = {"runs": runs, "announcements_created": created, "duplicates_skipped": skipped}
    if runs and all(run.get("status") == "failed" for run in runs):
        return JSONResponse(status_code=502, content=body)
    return body


@router.post("/sources/{source_id}/collect")
async def collect_source(source_id: int, request: Request, db: Session = Depends(get_db)):
    check_rate_limit(request)
    source = db.query(AnnouncementSource).filter_by(id=source_id).first()
    if source is None:
        raise HTTPException(status_code=404, detail="Announcement source not found")
    if not source.enabled:
        raise HTTPException(status_code=400, detail="Announcement source is disabled")
    try:
        runs, created, skipped = await _collect_sources(db, [source])
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable for collection") from exc
    body = {"runs": runs, "announcements_created": created, "duplicates_skipped": skipped}
    if runs and all(run.get("status") == "failed" for run in runs):
        return JSONResponse(status_code=502, content=body)
    return body


@router.patch("/sources/{source_id}")
async def patch_source(
    source_id: int,
    request: Request,
    payload: SourcePatchRequest = Body(...),
    db: Session = Depends(get_db),
):
    check_rate_limit(request)
    source = db.query(AnnouncementSource).filter_by(id=source_id).first()
    if source is None:
        raise HTTPException(status_code=404, detail="Announcement source not found")
    if payload.enabled is not None:
        source.enabled = payload.enabled
    if payload.polling_interval_seconds is not None:
        source.polling_interval_seconds = payload.polling_interval_seconds
    if payload.configuration is not None:
        source.configuration = payload.configuration
    try:
        db.commit()
        db.refresh(source)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return _serialise_source(source)
