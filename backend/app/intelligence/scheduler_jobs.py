"""Scheduled Phase 4 processing jobs.

These jobs reuse the single existing APScheduler instance
and the Phase 3 announcement store: they process
announcements the collector already saved, they do not
re-fetch the CMS feed (that would quadruple CMS calls).
Each job records its own failure without stopping the
other jobs, and each processing function is idempotent,
so a repeated run only skips already-processed records.

Single-instance limitation: APScheduler runs in-process
in this phase, so a multi-instance deployment would run
each job on every instance. That is documented in
docs/ALPHA_INTELLIGENCE.md and the other Phase 4 docs;
distributed coordination is a later-phase item.
"""

import logging

from app.database import SessionLocal
from app.intelligence.processing import (
    process_airdrops,
    process_alpha,
    process_prime_sales,
    refresh_alpha_market_data,
)

logger = logging.getLogger(__name__)

JOB_ALPHA = "alpha_processing"
JOB_AIRDROP = "airdrop_processing"
JOB_PRIME = "prime_sale_processing"


async def process_alpha_job() -> dict:
    db = SessionLocal()
    try:
        try:
            summary = await process_alpha(db)
        except Exception as exc:  # noqa: BLE001 - one job failure must not stop others
            logger.warning("Alpha processing job failed: %s", exc)
            return {"created": 0, "skipped": 0, "error": str(exc)}
        try:
            refreshed = await refresh_alpha_market_data(db)
            summary["market_refreshed"] = refreshed["updated"]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Alpha market refresh failed: %s", exc)
        logger.info("Alpha processing job summary: %s", summary)
        return summary
    finally:
        db.close()


async def process_airdrop_job() -> dict:
    db = SessionLocal()
    try:
        try:
            summary = process_airdrops(db)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Airdrop processing job failed: %s", exc)
            return {"created": 0, "skipped": 0, "error": str(exc)}
        logger.info("Airdrop processing job summary: %s", summary)
        return summary
    finally:
        db.close()


async def process_prime_sale_job() -> dict:
    db = SessionLocal()
    try:
        try:
            summary = process_prime_sales(db)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Prime Sale processing job failed: %s", exc)
            return {"created": 0, "skipped": 0, "error": str(exc)}
        logger.info("Prime Sale processing job summary: %s", summary)
        return summary
    finally:
        db.close()
