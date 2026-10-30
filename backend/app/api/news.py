"""Phase 7 API: crypto news, listings, delistings, sources.

News rows are built from Phase 3 announcements
plus any deliberately enabled RSS sources; no
announcement is duplicated. Summaries are null
when article bodies are unavailable, serialised
here as "Summary unavailable" — never invented.
Routes are /news (no /api/v1 prefix), matching
existing routers.
"""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.api.admin_common import audit as _audit_collection
from app.auth.dependencies import require_csrf, require_permission
from app.marketintel.classification import NEWS_CATEGORIES
from app.marketintel.service import process_news
from app.models import CryptoNews, NewsCollectionRun, NewsSource
from app.rate_limit import check_rate_limit

logger = logging.getLogger(__name__)
router = APIRouter(tags=["news"])


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def _serialise(row: CryptoNews) -> dict:
    return {
        "id": row.id,
        "headline": row.headline,
        "summary": row.summary if row.summary is not None else "Summary unavailable",
        "summary_available": row.summary is not None,
        "original_url": row.original_url,
        "publisher": row.publisher,
        "category": row.category,
        "related_symbols": row.related_symbols or [],
        "published_at": _iso(row.published_at),
        "collected_at": _iso(row.created_at),
        "source_id": row.source_id,
        "announcement_id": row.announcement_id,
        "processing_status": row.processing_status,
    }


def _list(request: Request, db: Session, query, page: int, page_size: int):
    check_rate_limit(request)
    try:
        total = query.count()
        rows = (
            query.order_by(CryptoNews.published_at.desc().nullslast(), CryptoNews.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {
        "items": [_serialise(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def _apply_filters(query, category, publisher, search, published_from, published_to):
    if category:
        query = query.filter(CryptoNews.category == category.upper())
    if publisher:
        query = query.filter(CryptoNews.publisher.ilike(f"%{publisher}%"))
    if search:
        query = query.filter(CryptoNews.headline.ilike(f"%{search}%"))
    if published_from:
        query = query.filter(CryptoNews.published_at >= published_from)
    if published_to:
        query = query.filter(CryptoNews.published_at <= published_to)
    return query


@router.get("/news")
async def list_news(
    request: Request,
    category: str | None = None,
    publisher: str | None = None,
    search: str | None = None,
    published_from: datetime | None = None,
    published_to: datetime | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    if category and category.upper() not in NEWS_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"Invalid category: {category}")
    query = _apply_filters(
        db.query(CryptoNews), category, publisher, search, published_from, published_to
    )
    return _list(request, db, query, page, page_size)


@router.get("/news/categories")
async def news_categories(request: Request, db: Session = Depends(get_db)):
    check_rate_limit(request)
    try:
        rows = db.query(CryptoNews).all()
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.category] = counts.get(row.category, 0) + 1
    return {"categories": NEWS_CATEGORIES, "counts": counts}


@router.get("/news/sources")
async def news_sources(request: Request, db: Session = Depends(get_db)):
    check_rate_limit(request)
    try:
        rows = db.query(NewsSource).order_by(NewsSource.name.asc()).all()
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {
        "items": [
            {
                "id": row.id,
                "name": row.name,
                "source_type": row.source_type,
                "feed_url": row.feed_url,
                "enabled": row.enabled,
                "reliability_note": row.reliability_note,
            }
            for row in rows
        ],
        "total": len(rows),
    }


@router.get("/news/collection-runs")
async def news_collection_runs(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    check_rate_limit(request)
    try:
        query = db.query(NewsCollectionRun)
        total = query.count()
        rows = (
            query.order_by(NewsCollectionRun.started_at.desc(), NewsCollectionRun.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {
        "items": [
            {
                "id": row.id,
                "source_id": row.source_id,
                "started_at": _iso(row.started_at),
                "completed_at": _iso(row.completed_at),
                "status": row.status,
                "found": row.found,
                "created": row.created,
                "skipped": row.skipped,
                "error_message": row.error_message,
            }
            for row in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/news/listings")
async def news_listings(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    return _list(
        request, db, db.query(CryptoNews).filter(CryptoNews.category == "LISTINGS"), page, page_size
    )


@router.get("/news/delistings")
async def news_delistings(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    return _list(
        request,
        db,
        db.query(CryptoNews).filter(CryptoNews.category == "DELISTINGS"),
        page,
        page_size,
    )


@router.get("/news/{news_id}")
async def get_news(request: Request, news_id: int, db: Session = Depends(get_db)):
    check_rate_limit(request)
    try:
        row = db.query(CryptoNews).filter(CryptoNews.id == news_id).first()
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    if row is None:
        raise HTTPException(status_code=404, detail="News item not found")
    return _serialise(row)


@router.post("/news/collect")
async def collect_news(
    request: Request,
    db: Session = Depends(get_db),
    _admin=Depends(require_permission("collections.run")),
    _csrf=Depends(require_csrf),
):
    _audit_collection(
        db, _admin, "collection.requested", entity="collection", details={"path": request.url.path}
    )
    check_rate_limit(request)
    try:
        result = process_news(db)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable for collection") from exc
    return result
