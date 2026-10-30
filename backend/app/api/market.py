"""Phase 7 API: market overview, gainers/losers, watchlist, alerts.

Follows the Phase 3/4/5 conventions: pagination,
filters, sorting, 404 for missing records, 400 for
invalid input, 502 when the upstream Binance
collection fails, and 503 on database errors.
Decimals are serialised as strings. Route naming
divergence, stated explicitly: routes are /market
(no /api/v1 prefix), matching the existing routers;
the frontend calls /api/market, which the proxy maps
to this backend route.

Manual collection is gated in Phase 8 by the
collections.run permission and CSRF protection.
"""

import logging
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.binance.client import BinanceAPIError, BinanceClient, validate_symbol
from app.binance.service import collect_market_snapshots
from app.config import settings
from app.database import get_db
from app.api.admin_common import audit as _audit_collection
from app.auth.dependencies import require_csrf, require_permission
from app.marketintel.service import gainers_losers, is_stale, latest_snapshots_by_symbol
from app.models import MarketAlert, MarketSnapshot, MarketWatchlist
from app.rate_limit import check_rate_limit

logger = logging.getLogger(__name__)
router = APIRouter(tags=["market"])


def _dec(value) -> str | None:
    return str(value) if value is not None else None


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def _snapshot_serialise(row: MarketSnapshot) -> dict:
    return {
        "symbol": row.symbol,
        "price": _dec(row.price),
        "price_change_24h": _dec(row.price_change_24h),
        "price_change_percent_24h": _dec(row.price_change_percent_24h),
        "high_24h": _dec(row.high_24h),
        "low_24h": _dec(row.low_24h),
        "volume_24h": _dec(row.volume_24h),
        "quote_volume_24h": _dec(row.quote_volume_24h),
        "source": row.source,
        "collected_at": _iso(row.collected_at),
        "is_stale": is_stale(row.collected_at),
    }


def _gainer_serialise(row: dict) -> dict:
    return {
        key: (_dec(value) if key not in ("symbol", "source") else value)
        for key, value in row.items()
    }


def _client() -> BinanceClient:
    return BinanceClient(
        settings.binance_spot_base_url,
        settings.binance_futures_base_url,
        timeout_seconds=settings.binance_request_timeout_seconds,
        max_retries=settings.binance_max_retries,
    )


def _latest(request: Request, db: Session, symbol: str | None = None) -> list[MarketSnapshot]:
    check_rate_limit(request)
    try:
        latest = latest_snapshots_by_symbol(db)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    rows = list(latest.values())
    if symbol:
        rows = [row for row in rows if row.symbol == symbol]
    rows.sort(key=lambda row: row.symbol)
    return rows


@router.get("/market/overview")
async def market_overview(
    request: Request, symbol: str | None = None, db: Session = Depends(get_db)
):
    rows = _latest(request, db, symbol.upper() if symbol else None)
    return {
        "items": [_snapshot_serialise(row) for row in rows],
        "total": len(rows),
        "source": "binance_spot",
        "freshness_minutes": settings.market_freshness_minutes,
    }


@router.get("/market/prices")
async def market_prices(
    request: Request,
    symbol: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    rows = _latest(request, db, symbol.upper() if symbol else None)
    total = len(rows)
    page_rows = rows[(page - 1) * page_size : page * page_size]
    return {
        "items": [_snapshot_serialise(row) for row in page_rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/market/gainers")
async def market_gainers(
    request: Request,
    limit: int = Query(10, ge=1, le=50),
    min_quote_volume: float | None = None,
    db: Session = Depends(get_db),
):
    rows = _latest(request, db)
    ticker_rows = [
        {
            "symbol": row.symbol,
            "price": row.price,
            "price_change_24h": row.price_change_24h,
            "price_change_percent_24h": row.price_change_percent_24h,
            "high_24h": row.high_24h,
            "low_24h": row.low_24h,
            "volume_24h": row.volume_24h,
            "quote_volume_24h": row.quote_volume_24h,
            "source": row.source,
        }
        for row in rows
    ]
    minimum = (
        min_quote_volume if min_quote_volume is not None else settings.market_min_quote_volume_usdt
    )
    result = gainers_losers(ticker_rows, limit=limit, min_quote_volume=minimum)
    return {
        "gainers": [_gainer_serialise(row) for row in result["gainers"]],
        "excluded_low_liquidity": result["excluded_low_liquidity"],
        "eligible_count": result["eligible_count"],
        "min_quote_volume_usdt": str(minimum),
        "note": "Low-volume symbols are excluded from these lists.",
    }


@router.get("/market/losers")
async def market_losers(
    request: Request,
    limit: int = Query(10, ge=1, le=50),
    min_quote_volume: float | None = None,
    db: Session = Depends(get_db),
):
    rows = _latest(request, db)
    ticker_rows = [
        {
            "symbol": row.symbol,
            "price": row.price,
            "price_change_24h": row.price_change_24h,
            "price_change_percent_24h": row.price_change_percent_24h,
            "high_24h": row.high_24h,
            "low_24h": row.low_24h,
            "volume_24h": row.volume_24h,
            "quote_volume_24h": row.quote_volume_24h,
            "source": row.source,
        }
        for row in rows
    ]
    minimum = (
        min_quote_volume if min_quote_volume is not None else settings.market_min_quote_volume_usdt
    )
    result = gainers_losers(ticker_rows, limit=limit, min_quote_volume=minimum)
    return {
        "losers": [_gainer_serialise(row) for row in result["losers"]],
        "excluded_low_liquidity": result["excluded_low_liquidity"],
        "eligible_count": result["eligible_count"],
        "min_quote_volume_usdt": str(minimum),
        "note": "Low-volume symbols are excluded from these lists.",
    }


@router.get("/market/history")
async def market_history(
    request: Request,
    symbol: str | None = None,
    collected_from: datetime | None = None,
    collected_to: datetime | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    check_rate_limit(request)
    try:
        query = db.query(MarketSnapshot)
        if symbol:
            query = query.filter(MarketSnapshot.symbol == symbol.upper())
        if collected_from:
            query = query.filter(MarketSnapshot.collected_at >= collected_from)
        if collected_to:
            query = query.filter(MarketSnapshot.collected_at <= collected_to)
        total = query.count()
        rows = (
            query.order_by(MarketSnapshot.collected_at.desc(), MarketSnapshot.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {
        "items": [_snapshot_serialise(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/market/watchlist")
async def list_watchlist(request: Request, db: Session = Depends(get_db)):
    check_rate_limit(request)
    try:
        rows = db.query(MarketWatchlist).order_by(MarketWatchlist.symbol.asc()).all()
        latest = latest_snapshots_by_symbol(db)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    items = []
    for row in rows:
        snapshot = latest.get(row.symbol)
        items.append(
            {
                "id": row.id,
                "symbol": row.symbol,
                "note": row.note,
                "price": _dec(snapshot.price) if snapshot else None,
                "price_change_percent_24h": (
                    _dec(snapshot.price_change_percent_24h) if snapshot else None
                ),
                "is_stale": is_stale(snapshot.collected_at) if snapshot else True,
                "created_at": _iso(row.created_at),
            }
        )
    return {"items": items, "total": len(items)}


class WatchlistRequest(BaseModel):
    symbol: str = Field(min_length=3, max_length=20)
    note: str | None = None


@router.post("/market/watchlist")
async def add_watchlist(
    request: Request,
    body: WatchlistRequest,
    db: Session = Depends(get_db),
    _admin=Depends(require_permission("market.manage")),
    _csrf=Depends(require_csrf),
):
    check_rate_limit(request)
    try:
        symbol = validate_symbol(body.symbol)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        existing = db.query(MarketWatchlist).filter(MarketWatchlist.symbol == symbol).first()
        if existing is not None:
            return {
                "id": existing.id,
                "symbol": existing.symbol,
                "note": existing.note,
                "already_exists": True,
            }
        row = MarketWatchlist(symbol=symbol, note=body.note)
        db.add(row)
        db.commit()
        db.refresh(row)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {"id": row.id, "symbol": row.symbol, "note": row.note, "already_exists": False}


@router.delete("/market/watchlist/{watchlist_id}")
async def delete_watchlist(
    request: Request,
    watchlist_id: int,
    db: Session = Depends(get_db),
    _admin=Depends(require_permission("market.manage")),
    _csrf=Depends(require_csrf),
):
    check_rate_limit(request)
    try:
        row = db.query(MarketWatchlist).filter(MarketWatchlist.id == watchlist_id).first()
        if row is None:
            raise HTTPException(status_code=404, detail="Watchlist entry not found")
        db.delete(row)
        db.commit()
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {"deleted": True, "id": watchlist_id}


@router.get("/market/alerts")
async def list_alerts(
    request: Request,
    symbol: str | None = None,
    alert_type: str | None = None,
    triggered_from: datetime | None = None,
    triggered_to: datetime | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    check_rate_limit(request)
    try:
        query = db.query(MarketAlert)
        if symbol:
            query = query.filter(MarketAlert.symbol == symbol.upper())
        if alert_type:
            query = query.filter(MarketAlert.alert_type == alert_type)
        if triggered_from:
            query = query.filter(MarketAlert.triggered_at >= triggered_from)
        if triggered_to:
            query = query.filter(MarketAlert.triggered_at <= triggered_to)
        total = query.count()
        rows = (
            query.order_by(MarketAlert.triggered_at.desc(), MarketAlert.id.desc())
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
                "alert_type": row.alert_type,
                "threshold_percent": _dec(row.threshold_percent),
                "baseline_price": _dec(row.baseline_price),
                "current_price": _dec(row.current_price),
                "change_percent": _dec(row.change_percent),
                "triggered_at": _iso(row.triggered_at),
                "status": row.status,
                "source": row.source,
            }
            for row in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/market/{symbol}")
async def get_market_symbol(request: Request, symbol: str, db: Session = Depends(get_db)):
    check_rate_limit(request)
    try:
        normalised = validate_symbol(symbol)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    rows = _latest(request, db, normalised)
    if not rows:
        raise HTTPException(status_code=404, detail=f"No market data for {normalised}")
    return _snapshot_serialise(rows[0])


@router.post("/market/collect")
async def collect_market(
    request: Request,
    body: dict | None = Body(default=None),
    db: Session = Depends(get_db),
    _admin=Depends(require_permission("collections.run")),
    _csrf=Depends(require_csrf),
):
    _audit_collection(
        db, _admin, "collection.requested", entity="collection", details={"path": request.url.path}
    )
    check_rate_limit(request)
    symbols = settings.tracked_symbol_list
    if body and isinstance(body.get("symbols"), list) and body["symbols"]:
        try:
            symbols = [validate_symbol(s) for s in body["symbols"][:20]]
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        snapshots = await collect_market_snapshots(db, _client(), symbols)
    except BinanceAPIError as exc:
        raise HTTPException(status_code=502, detail=f"Binance collection failed: {exc}") from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database unavailable for collection") from exc
    return {"collected": len(snapshots), "symbols": [s.symbol for s in snapshots]}
