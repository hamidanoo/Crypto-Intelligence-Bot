"""Phase 6 API: competition volume tracker.

Follows the Phase 3/4/5 API conventions: pagination
with page/page_size, filters, sorting, 404 for
missing records, 400 for invalid input, 502 when the
upstream Binance collection fails, and 503 on
database errors. Financial values are serialised as
strings, so Decimal precision survives JSON encoding.

Route naming divergence, stated explicitly: the
routes here are /competition-volume (no /api/v1
prefix), matching the existing routers
(/announcements, /alpha, /competitions). The
frontend calls /api/competition-volume, which the
frontend proxy maps to this backend route. There is
no /api/v1/competition-volume route.

Manual collection is gated in Phase 8 by the
collections.run permission and CSRF protection.

Accuracy labels are part of the contract: public
market volume comes from Binance public trade data
(aggTrades); estimated eligible volume is present
only with a verified multiplier, otherwise null;
official eligible volume is always null in Phase 6
and is serialised as null (displayed "Unavailable"
by clients), never zero. Official leaderboard data
is not implemented.
"""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.binance.client import BinanceAPIError, BinanceClient
from app.competitions.processing import competition_pairs
from app.config import settings
from app.database import get_db
from app.api.admin_common import audit as _audit_collection
from app.auth.dependencies import require_csrf, require_permission
from app.models import (
    Competition,
    CompetitionPairConfiguration,
    CompetitionVolumeCheckpoint,
    CompetitionVolumeCollectionRun,
    CompetitionVolumeInterval,
)
from app.rate_limit import check_rate_limit
from app.volume.aggregation import cumulative_volume
from app.volume.collection import collect_competition_volumes

logger = logging.getLogger(__name__)
router = APIRouter(tags=["competition-volume"])

_SORTS = {
    "interval_start_desc": (
        CompetitionVolumeInterval.interval_start.desc(),
        CompetitionVolumeInterval.id.desc(),
    ),
    "interval_start_asc": (
        CompetitionVolumeInterval.interval_start.asc(),
        CompetitionVolumeInterval.id.asc(),
    ),
    "public_quote_volume_desc": (
        CompetitionVolumeInterval.public_quote_volume.desc(),
        CompetitionVolumeInterval.id.desc(),
    ),
}


def _dec(value) -> str | None:
    return str(value) if value is not None else None


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def _serialise(row: CompetitionVolumeInterval) -> dict:
    return {
        "id": row.id,
        "competition_id": row.competition_id,
        "trading_pair": row.trading_pair,
        "base_asset": row.base_asset,
        "quote_asset": row.quote_asset,
        "interval_start": _iso(row.interval_start),
        "interval_end": _iso(row.interval_end),
        "public_base_volume": _dec(row.public_base_volume),
        "public_quote_volume": _dec(row.public_quote_volume),
        "estimated_eligible_volume": _dec(row.estimated_eligible_volume),
        "official_eligible_volume": _dec(row.official_eligible_volume),
        "calculation_method": row.calculation_method,
        "data_status": row.data_status,
        "recalculated": row.recalculated,
        "collected_at": _iso(row.collected_at),
    }


def _paginate(request: Request, db: Session, query, page: int, page_size: int, sort: str):
    check_rate_limit(request)
    try:
        total = query.count()
        order = _SORTS[sort]
        rows = query.order_by(*order).offset((page - 1) * page_size).limit(page_size).all()
        items = [_serialise(row) for row in rows]
    except SQLAlchemyError as exc:
        logger.warning("Volume list database error: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {"items": items, "total": total, "page": page, "page_size": page_size}


def _get_competition_or_404(db: Session, competition_id: int) -> Competition:
    try:
        competition = db.query(Competition).filter_by(id=competition_id).first()
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    if competition is None:
        raise HTTPException(status_code=404, detail="Competition not found")
    return competition


@router.get("/competition-volume")
async def list_volume_intervals(
    request: Request,
    competition_id: int | None = None,
    trading_pair: str | None = None,
    interval_from: datetime | None = None,
    interval_to: datetime | None = None,
    data_status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort: str = Query("interval_start_desc"),
    db: Session = Depends(get_db),
):
    if sort not in _SORTS:
        raise HTTPException(status_code=400, detail=f"Invalid sort: {sort}")
    query = db.query(CompetitionVolumeInterval)
    if competition_id is not None:
        query = query.filter(CompetitionVolumeInterval.competition_id == competition_id)
    if trading_pair:
        query = query.filter(CompetitionVolumeInterval.trading_pair == trading_pair.upper())
    if interval_from:
        query = query.filter(CompetitionVolumeInterval.interval_start >= interval_from)
    if interval_to:
        query = query.filter(CompetitionVolumeInterval.interval_start <= interval_to)
    if data_status:
        query = query.filter(CompetitionVolumeInterval.data_status == data_status.lower())
    return _paginate(request, db, query, page, page_size, sort)


@router.get("/competition-volume/collection-runs")
async def list_volume_collection_runs(
    request: Request,
    competition_id: int | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    check_rate_limit(request)
    try:
        query = db.query(CompetitionVolumeCollectionRun)
        if competition_id is not None:
            query = query.filter(CompetitionVolumeCollectionRun.competition_id == competition_id)
        total = query.count()
        rows = (
            query.order_by(CompetitionVolumeCollectionRun.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        items = [
            {
                "id": row.id,
                "competition_id": row.competition_id,
                "started": _iso(row.started),
                "completed": _iso(row.completed),
                "status": row.status,
                "intervals_found": row.intervals_found,
                "intervals_created": row.intervals_created,
                "intervals_updated": row.intervals_updated,
                "intervals_skipped": row.intervals_skipped,
                "error_message": row.error_message,
            }
            for row in rows
        ]
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/competition-volume/{competition_id}")
async def list_volume_for_competition(
    request: Request,
    competition_id: int,
    trading_pair: str | None = None,
    data_status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort: str = Query("interval_start_desc"),
    db: Session = Depends(get_db),
):
    _get_competition_or_404(db, competition_id)
    if sort not in _SORTS:
        raise HTTPException(status_code=400, detail=f"Invalid sort: {sort}")
    query = db.query(CompetitionVolumeInterval).filter_by(competition_id=competition_id)
    if trading_pair:
        query = query.filter(CompetitionVolumeInterval.trading_pair == trading_pair.upper())
    if data_status:
        query = query.filter(CompetitionVolumeInterval.data_status == data_status.lower())
    return _paginate(request, db, query, page, page_size, sort)


@router.get("/competition-volume/{competition_id}/pairs")
async def list_volume_pairs(request: Request, competition_id: int, db: Session = Depends(get_db)):
    competition = _get_competition_or_404(db, competition_id)
    check_rate_limit(request)
    try:
        pairs = competition_pairs(db, competition_id)
        configs = {
            row.trading_pair: row
            for row in db.query(CompetitionPairConfiguration)
            .filter_by(competition_id=competition_id)
            .all()
        }
        checkpoints = {
            row.trading_pair: row
            for row in db.query(CompetitionVolumeCheckpoint)
            .filter_by(competition_id=competition_id)
            .all()
        }
        items = []
        for pair_row in pairs:
            config = configs.get(pair_row.pair)
            checkpoint = checkpoints.get(pair_row.pair)
            latest = (
                db.query(CompetitionVolumeInterval)
                .filter_by(competition_id=competition_id, trading_pair=pair_row.pair)
                .order_by(CompetitionVolumeInterval.interval_start.desc())
                .first()
            )
            items.append(
                {
                    "pair": pair_row.pair,
                    "base_asset": pair_row.base_asset,
                    "quote_asset": pair_row.quote_asset,
                    "tracking_enabled": config.tracking_enabled if config else True,
                    "multiplier": _dec(config.multiplier) if config else None,
                    "multiplier_verified": config.multiplier_verified if config else False,
                    "calculation_method": config.calculation_method if config else None,
                    "last_interval_end": _iso(checkpoint.last_interval_end) if checkpoint else None,
                    "latest_interval": _serialise(latest) if latest else None,
                }
            )
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {
        "competition_id": competition.id,
        "competition_name": competition.competition_name,
        "status": competition.status,
        "pairs": items,
    }


@router.get("/competition-volume/{competition_id}/history")
async def volume_history(
    request: Request,
    competition_id: int,
    trading_pair: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort: str = Query("interval_start_desc"),
    db: Session = Depends(get_db),
):
    _get_competition_or_404(db, competition_id)
    if sort not in _SORTS:
        raise HTTPException(status_code=400, detail=f"Invalid sort: {sort}")
    query = db.query(CompetitionVolumeInterval).filter_by(competition_id=competition_id)
    if trading_pair:
        query = query.filter(CompetitionVolumeInterval.trading_pair == trading_pair.upper())
    return _paginate(request, db, query, page, page_size, sort)


@router.get("/competition-volume/{competition_id}/summary")
async def volume_summary(request: Request, competition_id: int, db: Session = Depends(get_db)):
    competition = _get_competition_or_404(db, competition_id)
    check_rate_limit(request)
    try:
        pairs = competition_pairs(db, competition_id)
        per_pair = []
        for pair_row in pairs:
            latest = (
                db.query(CompetitionVolumeInterval)
                .filter_by(competition_id=competition_id, trading_pair=pair_row.pair)
                .order_by(CompetitionVolumeInterval.interval_start.desc())
                .first()
            )
            cum = cumulative_volume(db, competition_id, pair_row.pair)
            per_pair.append(
                {
                    "trading_pair": pair_row.pair,
                    "base_asset": pair_row.base_asset,
                    "quote_asset": pair_row.quote_asset,
                    "latest_interval": _serialise(latest) if latest else None,
                    "cumulative_public_base_volume": _dec(cum["public_base_volume"]),
                    "cumulative_public_quote_volume": _dec(cum["public_quote_volume"]),
                    "cumulative_estimated_eligible_volume": _dec(cum["estimated_eligible_volume"]),
                    "interval_count": cum["interval_count"],
                }
            )
        last_run = (
            db.query(CompetitionVolumeCollectionRun)
            .filter_by(competition_id=competition_id)
            .order_by(CompetitionVolumeCollectionRun.id.desc())
            .first()
        )
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {
        "competition_id": competition.id,
        "competition_name": competition.competition_name,
        "status": competition.status,
        "official_eligible_volume": None,
        "official_eligible_volume_display": "Unavailable",
        "per_pair": per_pair,
        "last_collection_at": _iso(last_run.completed) if last_run else None,
        "last_collection_status": last_run.status if last_run else None,
    }


async def _run_collect(db: Session, competitions: list[Competition] | None):
    from datetime import timezone

    client = BinanceClient(
        settings.binance_spot_base_url,
        settings.binance_futures_base_url,
        timeout_seconds=settings.binance_request_timeout_seconds,
        max_retries=settings.binance_max_retries,
    )
    return await collect_competition_volumes(db, client, datetime.now(timezone.utc), competitions)


def _binance_failure_response(summary: dict):
    """502 when the whole collect failed upstream and
    nothing was collected. Partial failures (some
    intervals collected, some pairs failed) stay 200
    with the errors recorded, because one pair's
    failure must not fail the whole run. A
    competition with no pairs is not an upstream
    failure, so its note never triggers a 502."""
    if summary.get("errors", 0) == 0:
        return None
    if summary.get("intervals_completed", 0):
        return None
    messages = summary.get("error_messages", [])
    real_failures = [m for m in messages if not m.startswith("No trading pairs")]
    if not real_failures:
        return None
    return JSONResponse(
        status_code=502, content={"detail": f"Binance volume failed: {'; '.join(real_failures)}"}
    )


@router.post("/competition-volume/collect")
async def collect_all_volumes(
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
        summary = await _run_collect(db, None)
    except BinanceAPIError as exc:
        return JSONResponse(status_code=502, content={"detail": f"Binance volume failed: {exc}"})
    except SQLAlchemyError as exc:
        logger.warning("Volume collection database error: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    failure = _binance_failure_response(summary)
    if failure is not None:
        return failure
    return summary


@router.post("/competition-volume/{competition_id}/collect")
async def collect_one_volume(
    request: Request,
    competition_id: int,
    db: Session = Depends(get_db),
    _admin=Depends(require_permission("collections.run")),
    _csrf=Depends(require_csrf),
):
    _audit_collection(
        db, _admin, "collection.requested", entity="collection", details={"path": request.url.path}
    )
    competition = _get_competition_or_404(db, competition_id)
    check_rate_limit(request)
    try:
        summary = await _run_collect(db, [competition])
    except BinanceAPIError as exc:
        return JSONResponse(status_code=502, content={"detail": f"Binance volume failed: {exc}"})
    except SQLAlchemyError as exc:
        logger.warning("Volume collection database error: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    failure = _binance_failure_response(summary)
    if failure is not None:
        return failure
    return summary
