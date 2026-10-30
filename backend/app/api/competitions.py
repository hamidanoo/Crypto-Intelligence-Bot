"""Phase 5 API: Binance trading competitions.

Follows the Phase 3/4 API conventions: pagination with
page/page_size, filters, sorting, 404 for missing
records, 400 for invalid input, 502 when the upstream
announcement collection fails, and 503 on database
errors. Financial values are serialised as strings, so
Decimal precision survives JSON encoding.

This is the analytics foundation only: responses
include duration, reward pool, eligible pairs, status,
and the update timeline. There is no volume
aggregation endpoint here — that is Phase 6 work.

Manual collection is gated in Phase 8 by the
collections.run permission and CSRF protection.
"""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.announcements.client import AnnouncementAPIError, BinanceAnnouncementClient
from app.announcements.service import collect_from_source_async, ensure_default_source
from app.competitions.processing import competition_pairs, process_competitions
from app.database import get_db
from app.api.admin_common import audit as _audit_collection
from app.auth.dependencies import require_csrf, require_permission
from app.models import (
    Competition,
    CompetitionReward,
    CompetitionRule,
    CompetitionTradingPair,
    CompetitionUpdate,
)
from app.rate_limit import check_rate_limit

logger = logging.getLogger(__name__)
router = APIRouter(tags=["competitions"])

_SORTS = {
    "start_time_asc": (Competition.start_time.asc(), Competition.id.asc()),
    "start_time_desc": (Competition.start_time.desc(), Competition.id.desc()),
    "created_at_desc": (Competition.created_at.desc(), Competition.id.desc()),
    "created_at_asc": (Competition.created_at.asc(), Competition.id.asc()),
    "reward_pool_desc": (Competition.reward_pool.desc(), Competition.id.desc()),
}


def _dec(value) -> str | None:
    return str(value) if value is not None else None


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def _duration(competition: Competition) -> int | None:
    if competition.start_time is None or competition.end_time is None:
        return None
    return int((competition.end_time - competition.start_time).total_seconds())


def _serialise(competition: Competition, db: Session | None = None) -> dict:
    pairs = competition.eligible_trading_pairs or []
    if db is not None:
        pairs = [row.pair for row in competition_pairs(db, competition.id)] or pairs
    return {
        "id": competition.id,
        "announcement_id": competition.announcement_id,
        "competition_name": competition.competition_name,
        "description": competition.description,
        "competition_type": competition.competition_type,
        "official_url": competition.official_url,
        "reward_pool": _dec(competition.reward_pool),
        "reward_currency": competition.reward_currency,
        "start_time": _iso(competition.start_time),
        "end_time": _iso(competition.end_time),
        "registration_start": _iso(competition.registration_start),
        "registration_end": _iso(competition.registration_end),
        "status": competition.status,
        "duration_seconds": _duration(competition),
        "eligible_trading_pairs": pairs,
        "eligible_assets": competition.eligible_assets or [],
        "competition_rules": competition.competition_rules or [],
        "eligibility_requirements": competition.eligibility_requirements or [],
        "multiplier_rules": competition.multiplier_rules or [],
        "source": competition.source,
        "verification_status": competition.verification_status,
        "created_at": _iso(competition.created_at),
        "updated_at": _iso(competition.updated_at),
    }


def _apply_filters(
    query, competition_type, status, pair, start_from, start_to, end_from, end_to, search
):
    if competition_type:
        query = query.filter(Competition.competition_type == competition_type.upper())
    if status:
        query = query.filter(Competition.status == status.upper())
    if pair:
        query = query.join(
            CompetitionTradingPair, CompetitionTradingPair.competition_id == Competition.id
        ).filter(CompetitionTradingPair.pair == pair.upper())
    if start_from:
        query = query.filter(Competition.start_time >= start_from)
    if start_to:
        query = query.filter(Competition.start_time <= start_to)
    if end_from:
        query = query.filter(Competition.end_time >= end_from)
    if end_to:
        query = query.filter(Competition.end_time <= end_to)
    if search:
        query = query.filter(Competition.competition_name.ilike(f"%{search}%"))
    return query


def _list(request: Request, db: Session, base_query, page: int, page_size: int, sort: str):
    check_rate_limit(request)
    try:
        total = base_query.count()
        order = _SORTS[sort]
        rows = base_query.order_by(*order).offset((page - 1) * page_size).limit(page_size).all()
        items = [_serialise(row, db) for row in rows]
    except SQLAlchemyError as exc:
        logger.warning("Competition list database error: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/competitions")
async def list_competitions(
    request: Request,
    competition_type: str | None = None,
    status: str | None = None,
    pair: str | None = None,
    start_from: datetime | None = None,
    start_to: datetime | None = None,
    end_from: datetime | None = None,
    end_to: datetime | None = None,
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort: str = Query("created_at_desc"),
    db: Session = Depends(get_db),
):
    if sort not in _SORTS:
        raise HTTPException(status_code=400, detail=f"Invalid sort: {sort}")
    query = _apply_filters(
        db.query(Competition),
        competition_type,
        status,
        pair,
        start_from,
        start_to,
        end_from,
        end_to,
        search,
    )
    return _list(request, db, query, page, page_size, sort)


def _status_list(status_value: str):
    async def handler(
        request: Request,
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
        sort: str = Query("created_at_desc"),
        db: Session = Depends(get_db),
    ):
        if sort not in _SORTS:
            raise HTTPException(status_code=400, detail=f"Invalid sort: {sort}")
        query = db.query(Competition).filter(Competition.status == status_value)
        return _list(request, db, query, page, page_size, sort)

    return handler


router.get("/competitions/active")(_status_list("ACTIVE"))
router.get("/competitions/upcoming")(_status_list("UPCOMING"))
router.get("/competitions/completed")(_status_list("ENDED"))


@router.get("/competitions/{competition_id}")
async def get_competition(request: Request, competition_id: int, db: Session = Depends(get_db)):
    check_rate_limit(request)
    try:
        competition = db.query(Competition).filter_by(id=competition_id).first()
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    if competition is None:
        raise HTTPException(status_code=404, detail="Competition not found")
    return _serialise(competition, db)


@router.get("/competitions/{competition_id}/updates")
async def list_competition_updates(
    request: Request,
    competition_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    check_rate_limit(request)
    try:
        competition = db.query(Competition).filter_by(id=competition_id).first()
        if competition is None:
            raise HTTPException(status_code=404, detail="Competition not found")
        query = db.query(CompetitionUpdate).filter_by(competition_id=competition_id)
        total = query.count()
        rows = (
            query.order_by(CompetitionUpdate.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        items = [
            {
                "id": row.id,
                "competition_id": row.competition_id,
                "update_type": row.update_type,
                "field_name": row.field_name,
                "old_value": row.old_value,
                "new_value": row.new_value,
                "note": row.note,
                "created_at": _iso(row.created_at),
            }
            for row in rows
        ]
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/competitions/{competition_id}/pairs")
async def list_competition_pairs(
    request: Request, competition_id: int, db: Session = Depends(get_db)
):
    check_rate_limit(request)
    try:
        competition = db.query(Competition).filter_by(id=competition_id).first()
        if competition is None:
            raise HTTPException(status_code=404, detail="Competition not found")
        rows = competition_pairs(db, competition_id)
        rewards = db.query(CompetitionReward).filter_by(competition_id=competition_id).all()
        rules = db.query(CompetitionRule).filter_by(competition_id=competition_id).all()
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {
        "pairs": [
            {"id": r.id, "pair": r.pair, "base_asset": r.base_asset, "quote_asset": r.quote_asset}
            for r in rows
        ],
        "rewards": [
            {
                "id": r.id,
                "rank_range": r.rank_range,
                "reward_amount": _dec(r.reward_amount),
                "reward_currency": r.reward_currency,
                "description": r.description,
            }
            for r in rewards
        ],
        "rules": [
            {
                "id": r.id,
                "rule_type": r.rule_type,
                "description": r.description,
                "source_text": r.source_text,
            }
            for r in rules
        ],
    }


@router.post("/competitions/collect")
async def collect_competitions(
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
        source = ensure_default_source(db)
        client = BinanceAnnouncementClient(base_url=source.base_url)
        await collect_from_source_async(db, source, client)
        summary = process_competitions(db)
    except AnnouncementAPIError as exc:
        return JSONResponse(
            status_code=502, content={"detail": f"Announcement collection failed: {exc}"}
        )
    except SQLAlchemyError as exc:
        logger.warning("Competition collection database error: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {"category": "TRADING_COMPETITION", **summary}
