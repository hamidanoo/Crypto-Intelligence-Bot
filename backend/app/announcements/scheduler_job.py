"""Scheduled announcement collection job.

One job, registered once, runs every 5 minutes by default
and collects from every enabled source that is due according
to its own polling interval. This keeps the existing single
APScheduler instance, avoids overlapping runs
(max_instances=1), and makes job status observable through
CollectionRun rows, not through scheduler internals alone.

APScheduler is single-instance only in this phase: if the
API runs on multiple instances, each instance would run its
own job. That limitation is documented in
docs/ANNOUNCEMENT_MONITOR.md; distributed coordination
(Redis lock) is a later-phase item, not added here.
"""

import logging
from datetime import datetime, timezone

from app.announcements.client import BinanceAnnouncementClient
from app.announcements.notifications import notify_pending_announcements
from app.announcements.service import collect_from_source_async, ensure_default_source
from app.database import SessionLocal

logger = logging.getLogger(__name__)
JOB_ID = "announcement_collection"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


async def collect_all_announcements() -> dict:
    """Collect from all due enabled sources, then notify about
    pending announcements. Returns a summary dict for logging
    and for tests. A failure in one source does not stop the
    others; each failure is recorded as a failed run."""
    db = SessionLocal()
    try:
        source = ensure_default_source(db)
        sources = [source]
        # Any other enabled sources added later are included.
        from app.models import AnnouncementSource

        for other in db.query(AnnouncementSource).filter_by(enabled=True).all():
            if other.id != source.id:
                sources.append(other)
        summary = {"runs": 0, "created": 0, "skipped": 0, "failed": 0, "notified": 0}
        for src in sources:
            if src.last_success_at is not None:
                elapsed = (_now_utc() - src.last_success_at).total_seconds()
                if elapsed < src.polling_interval_seconds:
                    continue
            client = BinanceAnnouncementClient(base_url=src.base_url)
            try:
                run, created = await collect_from_source_async(db, src, client)
                summary["runs"] += 1
                summary["created"] += run.announcements_created
                summary["skipped"] += run.duplicates_skipped
            except Exception as exc:  # noqa: BLE001 - one source failure must not stop others
                summary["failed"] += 1
                logger.warning("Announcement collection failed for source %s: %s", src.name, exc)
        try:
            summary["notified"] = await notify_pending_announcements(db)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Announcement notification pass failed: %s", exc)
        logger.info("Announcement collection summary: %s", summary)
        return summary
    finally:
        db.close()
