"""Phase 7 API: futures funding, open interest, ratios, summary.

Funding and open interest reuse the Phase 2
FuturesSnapshot table; ratios use the new
FuturesMarketRatio table. Availability is explicit:
"available" when snapshots exist, "degraded" when
the last collection run was degraded, and
"unavailable" when no futures data exists at all
(for example while fapi returns HTTP 451 from a
restricted location). Unavailable is never filled
with fabricated values. Routes are /futures (no
/api/v1 prefix), matching existing routers.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.binance.client import BinanceClient, validate_symbol
from app.config import settings
from app.database import get_db
from app.api.admin_common import audit as _audit_collection
from app.auth.dependencies import require_csrf, require_permission
from app.marketintel.service import (
    collect_futures,
    collect_futures_ratios,
    is_stale,
    latest_futures_by_symbol,
    open_interest_change,
)
from app.models import FuturesMarketRatio, FuturesSnapshot, MarketCollectionRun
from app.rate_limit import check_rate_limit

logger = logging.getLogger(__name__)
router = APIRouter(tags=["futures"])


def _dec(value) -> str | None:
    return str(value) if value is not None else None


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def _client() -> BinanceClient:
    return BinanceClient(
        settings.binance_spot_base_url,
        settings.binance_futures_base_url,
        timeout_seconds=settings.binance_request_timeout_seconds,
        max_retries=settings.binance_max_retries,
    )


def _latest(request: Request, db: Session) -> list[FuturesSnapshot]:
    check_rate_limit(request)
    try:
        latest = latest_futures_by_symbol(db)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return sorted(latest.values(), key=lambda row: row.symbol)


def _serialise(row: FuturesSnapshot, db: Session | None = None) -> dict:
    change = open_interest_change(db, row.symbol) if db is not None else None
    return {
        "symbol": row.symbol,
        "funding_rate": _dec(row.funding_rate),
        "next_funding_time": _iso(row.next_funding_time),
        "mark_price": _dec(row.mark_price),
        "open_interest": _dec(row.open_interest),
        "open_interest_change_percent_24h": None,
        "open_interest_change_percent_since_previous": _dec(change),
        "source": row.source,
        "collected_at": _iso(row.collected_at),
        "is_stale": is_stale(row.collected_at),
    }


@router.get("/futures/funding")
async def futures_funding(
    request: Request,
    sort: str = Query("highest"),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    if sort not in ("highest", "lowest"):
        raise HTTPException(status_code=400, detail=f"Invalid sort: {sort}")
    rows = _latest(request, db)
    rows = [row for row in rows if row.funding_rate is not None]
    rows.sort(key=lambda row: row.funding_rate, reverse=(sort == "highest"))
    return {
        "items": [_serialise(row, db) for row in rows[:limit]],
        "total": len(rows),
        "availability": "available" if rows else "unavailable",
    }


@router.get("/futures/funding/{symbol}")
async def futures_funding_symbol(request: Request, symbol: str, db: Session = Depends(get_db)):
    try:
        normalised = validate_symbol(symbol)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    rows = _latest(request, db)
    for row in rows:
        if row.symbol == normalised:
            return _serialise(row, db)
    raise HTTPException(status_code=404, detail=f"No futures data for {normalised}")


@router.get("/futures/open-interest")
async def futures_open_interest(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    rows = _latest(request, db)
    rows = [row for row in rows if row.open_interest is not None]
    rows.sort(key=lambda row: row.open_interest, reverse=True)
    return {
        "items": [_serialise(row, db) for row in rows[:limit]],
        "total": len(rows),
        "availability": "available" if rows else "unavailable",
    }


@router.get("/futures/open-interest/{symbol}")
async def futures_open_interest_symbol(
    request: Request, symbol: str, db: Session = Depends(get_db)
):
    try:
        normalised = validate_symbol(symbol)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    rows = _latest(request, db)
    for row in rows:
        if row.symbol == normalised:
            return _serialise(row, db)
    raise HTTPException(status_code=404, detail=f"No futures data for {normalised}")


@router.get("/futures/ratios")
async def futures_ratios(
    request: Request,
    symbol: str | None = None,
    ratio_type: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    check_rate_limit(request)
    try:
        query = db.query(FuturesMarketRatio)
        if symbol:
            query = query.filter(FuturesMarketRatio.symbol == symbol.upper())
        if ratio_type:
            query = query.filter(FuturesMarketRatio.ratio_type == ratio_type)
        total = query.count()
        rows = (
            query.order_by(FuturesMarketRatio.collected_at.desc(), FuturesMarketRatio.id.desc())
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
                "symbol": row.symbol,
                "ratio_type": row.ratio_type,
                "long_ratio": _dec(row.long_ratio),
                "short_ratio": _dec(row.short_ratio),
                "long_short_ratio": _dec(row.long_short_ratio),
                "period": row.period,
                "source": row.source,
                "collected_at": _iso(row.collected_at),
                "note": (
                    "Account ratios and position ratios are different datasets; "
                    "taker values are buy/sell volumes."
                ),
            }
            for row in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/futures/summary")
async def futures_summary(request: Request, db: Session = Depends(get_db)):
    rows = _latest(request, db)
    try:
        last_run = (
            db.query(MarketCollectionRun)
            .filter(MarketCollectionRun.job_name == "futures_collection")
            .order_by(MarketCollectionRun.started_at.desc(), MarketCollectionRun.id.desc())
            .first()
        )
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    funded = [row for row in rows if row.funding_rate is not None]
    availability = "available" if rows else "unavailable"
    if last_run is not None and last_run.status == "degraded":
        availability = "degraded"
    if last_run is not None and last_run.status == "unavailable":
        availability = "unavailable"
    return {
        "availability": availability,
        "symbols": len(rows),
        "highest_funding": (
            _serialise(max(funded, key=lambda r: r.funding_rate), db) if funded else None
        ),
        "lowest_funding": (
            _serialise(min(funded, key=lambda r: r.funding_rate), db) if funded else None
        ),
        "last_collection": _iso(last_run.completed_at) if last_run else None,
        "last_collection_status": last_run.status if last_run else None,
        "last_collection_error": last_run.error_message if last_run else None,
        "note": "Open interest alone does not imply market direction.",
    }


@router.post("/futures/collect")
async def collect_futures_endpoint(
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
        result = await collect_futures(db, _client(), settings.tracked_symbol_list)
        ratios = await collect_futures_ratios(db, _client(), settings.tracked_symbol_list)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable for collection") from exc
    if result["status"] == "unavailable":
        raise HTTPException(
            status_code=502, detail=f"Futures collection unavailable: {result['errors']}"
        )
    return {**result, "ratios": ratios}
