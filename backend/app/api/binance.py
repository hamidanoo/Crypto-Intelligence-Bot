import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.binance.client import BinanceAPIError, BinanceClient, validate_symbol
from app.binance.service import (
    collect_futures_snapshots,
    collect_market_snapshots,
    record_integration_status,
)
from app.config import settings
from app.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/binance", tags=["binance"])


def get_binance_client() -> BinanceClient:
    return BinanceClient(
        spot_base_url=settings.binance_spot_base_url,
        futures_base_url=settings.binance_futures_base_url,
        timeout_seconds=settings.binance_request_timeout_seconds,
        max_retries=settings.binance_max_retries,
    )


def _serialise_snapshot(snapshot) -> dict:
    return {
        "id": snapshot.id,
        "symbol": snapshot.symbol,
        "source": snapshot.source,
        "collected_at": snapshot.collected_at.isoformat() if snapshot.collected_at else None,
        **{
            key: getattr(snapshot, key)
            for key in (
                "price", "price_change_24h", "price_change_percent_24h",
                "high_24h", "low_24h", "volume_24h", "quote_volume_24h",
                "funding_rate", "next_funding_time", "mark_price", "open_interest",
            )
            if hasattr(snapshot, key)
        },
    }


def _serialise_datetime(value):
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _serialise_kline(kline: dict) -> dict:
    return {key: _serialise_datetime(value) for key, value in kline.items()}


async def _handle_binance_error(exc: BinanceAPIError) -> HTTPException:
    # Binance client errors (for example a restricted location) are
    # upstream failures, not a bug in this API, so they are reported
    # as a bad gateway with the upstream message preserved.
    return HTTPException(status_code=502, detail=str(exc))


@router.get("/status")
async def binance_status(
    client: BinanceClient = Depends(get_binance_client),
    db: Session = Depends(get_db),
):
    """Basic API connection monitoring for Spot and Futures.

    Each integration is reported separately and honestly. A failure
    in one does not hide the other, and no data is fabricated when
    an endpoint is unavailable.
    """
    components: dict[str, dict] = {}
    for name, ping in (("binance_spot", client.spot_ping), ("binance_futures", client.futures_ping)):
        _data, latency_ms, error = await ping()
        components[name] = {
            "status": "ok" if error is None else "unavailable",
            "latency_ms": latency_ms,
            "error": error,
        }
        try:
            base_url = settings.binance_spot_base_url if name == "binance_spot" else settings.binance_futures_base_url
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
async def price(symbol: str, client: BinanceClient = Depends(get_binance_client)):
    try:
        return await client.get_price(symbol)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except BinanceAPIError as exc:
        raise await _handle_binance_error(exc) from exc


@router.get("/ticker/{symbol}")
async def ticker(symbol: str, client: BinanceClient = Depends(get_binance_client)):
    try:
        data = await client.get_ticker_24hr(symbol)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except BinanceAPIError as exc:
        raise await _handle_binance_error(exc) from exc
    return {key: _serialise_datetime(value) for key, value in data.items()}


@router.get("/klines/{symbol}")
async def klines(
    symbol: str,
    interval: str = Query("1h"),
    limit: int = Query(100, ge=1, le=1000),
    client: BinanceClient = Depends(get_binance_client),
):
    try:
        rows = await client.get_klines(symbol, interval=interval, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except BinanceAPIError as exc:
        raise await _handle_binance_error(exc) from exc
    return [_serialise_kline(row) for row in rows]


@router.get("/funding/{symbol}")
async def funding(symbol: str, client: BinanceClient = Depends(get_binance_client)):
    try:
        data = await client.get_funding_rate(symbol)
        premium = await client.get_premium_index(symbol)
        data["next_funding_time"] = premium["next_funding_time"].isoformat()
        data["mark_price"] = premium["mark_price"]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except BinanceAPIError as exc:
        raise await _handle_binance_error(exc) from exc
    return {key: _serialise_datetime(value) for key, value in data.items()}


@router.get("/open-interest/{symbol}")
async def open_interest(symbol: str, client: BinanceClient = Depends(get_binance_client)):
    try:
        data = await client.get_open_interest(symbol)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except BinanceAPIError as exc:
        raise await _handle_binance_error(exc) from exc
    return {key: _serialise_datetime(value) for key, value in data.items()}


@router.post("/collect/market")
async def collect_market(
    symbols: list[str] | None = None,
    client: BinanceClient = Depends(get_binance_client),
    db: Session = Depends(get_db),
):
    chosen = symbols or settings.tracked_symbol_list
    try:
        snapshots = await collect_market_snapshots(db, client, chosen)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except BinanceAPIError as exc:
        raise await _handle_binance_error(exc) from exc
    return {"collected": len(snapshots), "snapshots": [_serialise_snapshot(s) for s in snapshots]}


@router.post("/collect/futures")
async def collect_futures(
    symbols: list[str] | None = None,
    client: BinanceClient = Depends(get_binance_client),
    db: Session = Depends(get_db),
):
    chosen = symbols or settings.tracked_symbol_list
    try:
        snapshots = await collect_futures_snapshots(db, client, chosen)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except BinanceAPIError as exc:
        raise await _handle_binance_error(exc) from exc
    return {"collected": len(snapshots), "snapshots": [_serialise_snapshot(s) for s in snapshots]}
