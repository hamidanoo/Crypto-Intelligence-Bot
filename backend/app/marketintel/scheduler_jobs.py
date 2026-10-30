"""Phase 7 scheduled jobs, on the single APScheduler instance.

Each job logs and returns its result, never raising
to stop other jobs. Futures jobs degrade on
restriction instead of failing the whole scheduler.
Restart recovery is via stored snapshots, alerts,
and collection runs: a restarted job simply reads
the latest stored state and continues.
"""

import logging
from datetime import datetime, timezone

import httpx

from app.binance.client import BinanceClient
from app.binance.service import collect_market_snapshots
from app.config import settings
from app.database import SessionLocal
from app.marketintel.service import (
    collect_futures,
    collect_futures_ratios,
    collect_rss_items,
    detect_movements,
    funding_alerts,
    latest_snapshots_by_symbol,
    parse_rss,
    process_news,
)

logger = logging.getLogger(__name__)

JOB_MARKET_SNAPSHOT = "market_snapshot"
JOB_FUNDING = "funding_collection"
JOB_OPEN_INTEREST = "open_interest_collection"
JOB_NEWS = "news_collection"
JOB_LISTINGS = "listing_processing"
JOB_MOVEMENT = "market_movement_detection"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _client() -> BinanceClient:
    return BinanceClient(
        settings.binance_spot_base_url,
        settings.binance_futures_base_url,
        timeout_seconds=settings.binance_request_timeout_seconds,
        max_retries=settings.binance_max_retries,
    )


def _symbols() -> list[str]:
    return settings.tracked_symbol_list


async def process_market_snapshot_job() -> dict:
    db = SessionLocal()
    try:
        try:
            snapshots = await collect_market_snapshots(db, _client(), _symbols())
        except Exception as exc:  # noqa: BLE001 - job must not stop others
            logger.warning("Market snapshot job failed: %s", exc)
            return {"error": str(exc)}
        return {"collected": len(snapshots)}
    finally:
        db.close()


async def process_funding_job() -> dict:
    db = SessionLocal()
    try:
        result = await collect_futures(db, _client(), _symbols())
        try:
            funding_alerts(db)
        except Exception as exc:  # noqa: BLE001 - alerts must not hide collection
            logger.warning("Funding alerts failed: %s", exc)
        return result
    finally:
        db.close()


async def process_open_interest_job() -> dict:
    # Open interest lives in the same FuturesSnapshot
    # rows as funding, so this job refreshes those
    # rows (and ratios) on its own, slower schedule.
    db = SessionLocal()
    try:
        result = await collect_futures(db, _client(), _symbols())
        ratios = await collect_futures_ratios(db, _client(), _symbols())
        return {**result, "ratios": ratios}
    finally:
        db.close()


async def process_news_job() -> dict:
    db = SessionLocal()
    try:
        result = process_news(db)
        # Enabled RSS sources, if any are ever added
        # deliberately as NewsSource rows.
        from app.models import NewsSource

        for source in db.query(NewsSource).filter(NewsSource.enabled.is_(True)).all():
            if not source.feed_url:
                continue
            try:
                async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
                    response = await client.get(source.feed_url)
                response.raise_for_status()
                rss = collect_rss_items(db, source, parse_rss(response.text))
                result = {**result, "rss_created": result.get("rss_created", 0) + rss["created"]}
            except Exception as exc:  # noqa: BLE001 - one feed must not stop news
                logger.warning("RSS source %s failed: %s", source.name, exc)
        return result
    finally:
        db.close()


async def process_listing_job() -> dict:
    db = SessionLocal()
    try:
        return process_news(db, categories=["SPOT_LISTING", "FUTURES_LISTING", "DELISTING"])
    finally:
        db.close()


async def process_movement_job() -> dict:
    db = SessionLocal()
    try:
        latest = latest_snapshots_by_symbol(db)
        # Previous snapshot per symbol: the second
        # newest row for that symbol.
        from app.models import MarketSnapshot

        previous: dict[str, MarketSnapshot] = {}
        for symbol in latest:
            rows = (
                db.query(MarketSnapshot)
                .filter(MarketSnapshot.symbol == symbol)
                .order_by(MarketSnapshot.collected_at.desc(), MarketSnapshot.id.desc())
                .limit(2)
                .all()
            )
            if len(rows) >= 2:
                previous[symbol] = rows[1]
        alerts = detect_movements(db, list(latest.values()), previous)
        return {"alerts": len(alerts)}
    finally:
        db.close()
