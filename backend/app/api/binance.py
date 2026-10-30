import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.binance.client import BinanceAPIError, BinanceClient, validate_symbol
from app.binance.service import (
    collect_futures_snapshots,
    collect_market_snapshots,
    record_integration_status,
)
from app.cache import cache_get, cache_set
from app.config import settings
from app.database import get_db
from app.rate_limit import check_rate_limit

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/binance", tags=["binance"])


def get_binance_client() -> BinanceClient:
    return BinanceClient(
        spot_base_url=settings.binance_spot_base_url,
        futures_base_url=settings.binance_futures_base_url,
        timeout_seconds=settings.binance_request_timeout_seconds,
        max_retries=settings.binance_max_retries,
    )


class CollectRequest(BaseModel):
    """Request body for snapshot collection. When symbols is
    omitted or empty, the configured tracked symbols are used."""

    symbols: list[str] | None = Field(default=None, max_length=20)


def _serialise_value(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _serialise_snapshot(snapshot) -> dict:
    data: dict = {
        "id": snapshot.id,
        "symbol": snapshot.symbol,
        "source": snapshot.source,
        "collected_at": snapshot.collected_at.isoformat() if snapshot.collected_at else None,
    }
    for key in (
        "price",
        "price_change_24h",
        "price_change_percent_24h",
        "high_24h",
        "low_24h",
        "volume_24h",
        "quote_volume_24h",
        "funding_rate",
        "next_funding_time",
        "mark_price",
        "open_interest",
    ):
        if hasattr(snapshot, key):
            data[key] = _serialise_value(getattr(snapshot, key))
    return data


def _serialise_dict(data: dict) -> dict:
    return {key: _serialise_value(value) for key, value in data.items()}


def _serialise_kline(kline: dict) -> dict:
    return _serialise_dict(kline)


def _handle_binance_error(exc: BinanceAPIError) -> HTTPException:
    # Binance client errors (for example a restricted location) are
    # upstream failures, not a bug in this API, so they are reported
    # as a bad gateway with the upstream message preserved.
    return HTTPException(status_code=502, detail=str(exc))


@router.get("/status")
async def binance_status(
    request: Request,
    client: BinanceClient = Depends(get_binance_client),
    db: Session = Depends(get_db),
):
    """Basic API connection monitoring for Spot and Futures.

    Both pings run concurrently, each integration is reported
    separately and honestly, and a failure in one does not hide
    the other. No data is fabricated when an endpoint is
    unavailable.
    """
    check_rate_limit(request)
    spot_result, futures_result = await asyncio.gather(client.spot_ping(), client.futures_ping())
    components: dict[str, dict] = {}
    for name, result, base_url in (
        ("binance_spot", spot_result, settings.binance_spot_base_url),
        ("binance_futures", futures_result, settings.binance_futures_base_url),
    ):
        _data, latency_ms, error = result
        components[name] = {
            "status": "ok" if error is None else "unavailable",
            "latency_ms": latency_ms,
            "error": error,
        }
        try:
            record_integration_status(db, name, base_url, error is None, error)
        except Exception as exc:  # noqa: BLE001 - monitoring must not fail the status call
            logger.warning("Could not record %s integration status: %s", name, type(exc).__name__)
    overall = "ok" if all(c["status"] == "ok" for c in components.values()) else "degraded"
    return {
        "status": overall,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "components": components,
    }


@router.get("/price/{symbol}")
async def price(symbol: str, request: Request, client: BinanceClient = Depends(get_binance_client)):
    check_rate_limit(request)
    try:
        symbol = validate_symbol(symbol)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    cache_key = f"binance:price:{symbol}"
    cached = await cache_get(cache_key)
    if cached is not None:
        return {**cached, "cached": True}
    try:
        data = await client.get_price(symbol)
    except BinanceAPIError as exc:
        raise _handle_binance_error(exc) from exc
    await cache_set(cache_key, data, ttl_seconds=10)
    return {**data, "cached": False}


@router.get("/ticker/{symbol}")
async def ticker(
    symbol: str, request: Request, client: BinanceClient = Depends(get_binance_client)
):
    check_rate_limit(request)
    try:
        symbol = validate_symbol(symbol)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    cache_key = f"binance:ticker:{symbol}"
    cached = await cache_get(cache_key)
    if cached is not None:
        return {**cached, "cached": True}
    try:
        data = await client.get_ticker_24hr(symbol)
    except BinanceAPIError as exc:
        raise _handle_binance_error(exc) from exc
    serialised = _serialise_dict(data)
    await cache_set(cache_key, serialised, ttl_seconds=15)
    return {**serialised, "cached": False}


@router.get("/klines/{symbol}")
async def klines(
    symbol: str,
    request: Request,
    interval: str = Query("1h"),
    limit: int = Query(100, ge=1, le=1000),
    client: BinanceClient = Depends(get_binance_client),
):
    check_rate_limit(request)
    try:
        symbol = validate_symbol(symbol)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    cache_key = f"binance:klines:{symbol}:{interval}:{limit}"
    cached = await cache_get(cache_key)
    if cached is not None:
        return cached
    try:
        rows = await client.get_klines(symbol, interval=interval, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except BinanceAPIError as exc:
        raise _handle_binance_error(exc) from exc
    serialised = [_serialise_kline(row) for row in rows]
    await cache_set(cache_key, serialised, ttl_seconds=60)
    return serialised


@router.get("/funding/{symbol}")
async def funding(
    symbol: str, request: Request, client: BinanceClient = Depends(get_binance_client)
):
    check_rate_limit(request)
    try:
        data = await client.get_funding_rate(symbol)
        premium = await client.get_premium_index(symbol)
        data["next_funding_time"] = premium["next_funding_time"]
        data["mark_price"] = premium["mark_price"]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except BinanceAPIError as exc:
        raise _handle_binance_error(exc) from exc
    return _serialise_dict(data)


@router.get("/open-interest/{symbol}")
async def open_interest(
    symbol: str, request: Request, client: BinanceClient = Depends(get_binance_client)
):
    check_rate_limit(request)
    try:
        data = await client.get_open_interest(symbol)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except BinanceAPIError as exc:
        raise _handle_binance_error(exc) from exc
    return _serialise_dict(data)


@router.post("/collect/market")
async def collect_market(
    request: Request,
    payload: CollectRequest | None = Body(default=None),
    client: BinanceClient = Depends(get_binance_client),
    db: Session = Depends(get_db),
):
    check_rate_limit(request)
    chosen = payload.symbols if payload and payload.symbols else settings.tracked_symbol_list
    try:
        snapshots = await collect_market_snapshots(db, client, chosen)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except BinanceAPIError as exc:
        raise _handle_binance_error(exc) from exc
    except SQLAlchemyError as exc:
        logger.warning("Market collection database error: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Database unavailable for collection") from exc
    return {"collected": len(snapshots), "snapshots": [_serialise_snapshot(s) for s in snapshots]}


@router.post("/collect/futures")
async def collect_futures(
    request: Request,
    payload: CollectRequest | None = Body(default=None),
    client: BinanceClient = Depends(get_binance_client),
    db: Session = Depends(get_db),
):
    check_rate_limit(request)
    chosen = payload.symbols if payload and payload.symbols else settings.tracked_symbol_list
    try:
        snapshots = await collect_futures_snapshots(db, client, chosen)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except BinanceAPIError as exc:
        raise _handle_binance_error(exc) from exc
    except SQLAlchemyError as exc:
        logger.warning("Futures collection database error: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Database unavailable for collection") from exc
    return {"collected": len(snapshots), "snapshots": [_serialise_snapshot(s) for s in snapshots]}
