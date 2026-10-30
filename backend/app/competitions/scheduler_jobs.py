"""Scheduled Phase 5 competition processing job.

Reuses the single existing APScheduler instance: this
job processes announcements the Phase 3 collector
already stored, it does not re-fetch the CMS feed (the
manual collect endpoint does that). One failure is
recorded on the collection run and in the returned
summary; it never stops the other scheduled jobs.

Single-instance limitation: APScheduler runs
in-process, so a multi-instance deployment would run
this job on every instance. That is documented in
docs/COMPETITION_INTELLIGENCE.md; distributed
coordination is a later-phase item.
"""

import logging

from app.competitions.processing import run_competition_collection
from app.database import SessionLocal

logger = logging.getLogger(__name__)

JOB_COMPETITION = "competition_processing"


async def process_competition_job() -> dict:
    db = SessionLocal()
    try:
        try:
            summary = run_competition_collection(db)
        except Exception as exc:  # noqa: BLE001 - one job failure must not stop others
            logger.warning("Competition processing job failed: %s", exc)
            return {"created": 0, "skipped": 0, "error": str(exc)}
        logger.info("Competition processing job summary: %s", summary)
        return summary
    finally:
        db.close()
