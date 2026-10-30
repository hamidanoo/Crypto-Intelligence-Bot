"""Scheduled Phase 6 volume tracking job.

Runs on the single existing APScheduler instance
(see app/scheduler.py): every 30 minutes, with
max_instances=1, it collects newly completed
intervals and then runs the Telegram reporting pass.
Only completed intervals are processed, so the job
firing off :00/:30 wall-clock boundaries is safe.
One job failure is logged and returned, never raised
to stop other scheduled jobs.
"""

import logging
from datetime import datetime, timezone

from app.binance.client import BinanceClient
from app.config import settings
from app.database import SessionLocal
from app.volume.collection import collect_competition_volumes
from app.volume.reporting import send_volume_reports

logger = logging.getLogger(__name__)
JOB_VOLUME = "competition_volume_tracking"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


async def process_volume_job() -> dict:
    db = SessionLocal()
    try:
        client = BinanceClient(
            settings.binance_spot_base_url,
            settings.binance_futures_base_url,
            timeout_seconds=settings.binance_request_timeout_seconds,
            max_retries=settings.binance_max_retries,
        )
        try:
            summary = await collect_competition_volumes(db, client, _now_utc())
        except Exception as exc:  # noqa: BLE001 - one job failure must not stop others
            logger.warning("Competition volume collection job failed: %s", exc)
            return {"error": str(exc)}
        try:
            reports = await send_volume_reports(db)
        except Exception as exc:  # noqa: BLE001 - reporting failure must not hide collection
            logger.warning("Competition volume reporting job failed: %s", exc)
            reports = {"error": str(exc)}
        result = {**summary, "reports": reports}
        logger.info("Competition volume job summary: %s", result)
        return result
    finally:
        db.close()
