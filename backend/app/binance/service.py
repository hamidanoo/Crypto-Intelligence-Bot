"""Persistence for Binance market data.

Collection functions take an explicit database session and client so
they can be tested without a live database or network. Each call
persists one snapshot per symbol and commits once, so a failure
mid-collection does not leave a half-written batch for a symbol.
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.binance.client import BinanceClient, validate_symbol
from app.models import FuturesSnapshot, MarketSnapshot

logger = logging.getLogger(__name__)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _decimal(value) -> Decimal | None:
    """Convert a numeric value to Decimal via its string form, so
    a binary float never introduces precision error on storage."""
    if value is None:
        return None
    return Decimal(str(value))


async def collect_market_snapshots(
    db: Session, client: BinanceClient, symbols: list[str]
) -> list[MarketSnapshot]:
    if len(symbols) > 20:
        raise ValueError("At most 20 symbols can be collected in one request")
    snapshots: list[MarketSnapshot] = []
    for raw_symbol in symbols:
        symbol = validate_symbol(raw_symbol)
        ticker = await client.get_ticker_24hr(symbol)
        snapshot = MarketSnapshot(
            symbol=symbol,
            source=ticker["source"],
            price=_decimal(ticker["price"]),
            price_change_24h=_decimal(ticker["price_change_24h"]),
            price_change_percent_24h=_decimal(ticker["price_change_percent_24h"]),
            high_24h=_decimal(ticker["high_24h"]),
            low_24h=_decimal(ticker["low_24h"]),
            volume_24h=_decimal(ticker["volume_24h"]),
            quote_volume_24h=_decimal(ticker["quote_volume_24h"]),
            collected_at=_now_utc(),
        )
        db.add(snapshot)
        snapshots.append(snapshot)
    db.commit()
    for snapshot in snapshots:
        db.refresh(snapshot)
    logger.info("Collected %s market snapshots", len(snapshots))
    return snapshots


async def collect_futures_snapshots(
    db: Session, client: BinanceClient, symbols: list[str]
) -> list[FuturesSnapshot]:
    if len(symbols) > 20:
        raise ValueError("At most 20 symbols can be collected in one request")
    snapshots: list[FuturesSnapshot] = []
    for raw_symbol in symbols:
        symbol = validate_symbol(raw_symbol)
        funding = await client.get_funding_rate(symbol)
        premium = await client.get_premium_index(symbol)
        interest = await client.get_open_interest(symbol)
        snapshot = FuturesSnapshot(
            symbol=symbol,
            source="binance_futures",
            funding_rate=_decimal(funding["funding_rate"]),
            next_funding_time=premium["next_funding_time"],
            mark_price=_decimal(premium["mark_price"]),
            open_interest=_decimal(interest["open_interest"]),
            collected_at=_now_utc(),
        )
        db.add(snapshot)
        snapshots.append(snapshot)
    db.commit()
    for snapshot in snapshots:
        db.refresh(snapshot)
    logger.info("Collected %s futures snapshots", len(snapshots))
    return snapshots


def record_integration_status(
    db: Session, provider: str, base_url: str, ok: bool, error: str | None
) -> None:
    """Upsert the connection-monitoring row for a Binance integration."""
    from app.models import ApiIntegration

    row = db.query(ApiIntegration).filter(ApiIntegration.provider == provider).first()
    if row is None:
        row = ApiIntegration(provider=provider, base_url=base_url, enabled=True)
        db.add(row)
    row.base_url = base_url
    row.enabled = True
    if ok:
        row.last_success_at = _now_utc()
        row.last_error = None
    else:
        row.last_error = error
    db.commit()
