"""Background job registry for Phase 1.

APScheduler is the chosen scheduler: it runs in-process, needs no
extra broker for scheduled jobs, and keeps the Phase 1 architecture a
modular monolith. Redis remains in the stack for caching and for
deduplication keys in later phases. If job volume or multi-instance
deployment later requires it, the registry here is the single place
where a distributed queue would be introduced, with that decision
recorded in the development log first.
"""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler(timezone="UTC")


def register_jobs() -> None:
    """Register scheduled jobs, idempotently.

    Phase 3 adds one job: announcement collection, every 5
    minutes, with max_instances=1 so runs never overlap.
    Phase 4 adds three processing jobs on the same
    scheduler (no second scheduler is created): Alpha,
    airdrop, and Prime Sale processing, each every 10
    minutes by default. Calling register_jobs twice does
    not register any job twice: an existing job with the
    same id is left alone. Phase 6 adds one job:
    competition volume tracking, every 30 minutes,
    max_instances=1, processing only completed
    intervals, then the Telegram reporting pass.
    """
    from app.announcements.scheduler_job import JOB_ID, collect_all_announcements
    from app.competitions.scheduler_jobs import JOB_COMPETITION, process_competition_job
    from app.config import settings
    from app.marketintel.scheduler_jobs import (
        JOB_FUNDING,
        JOB_LISTINGS,
        JOB_MARKET_SNAPSHOT,
        JOB_MOVEMENT,
        JOB_NEWS,
        JOB_OPEN_INTEREST,
        process_funding_job,
        process_listing_job,
        process_market_snapshot_job,
        process_movement_job,
        process_news_job,
        process_open_interest_job,
    )
    from app.volume.scheduler_jobs import JOB_VOLUME, process_volume_job
    from app.intelligence.scheduler_jobs import (
        JOB_AIRDROP,
        JOB_ALPHA,
        JOB_PRIME,
        process_airdrop_job,
        process_alpha_job,
        process_prime_sale_job,
    )

    jobs = [
        (JOB_ID, collect_all_announcements, 5),
        (
            JOB_ALPHA,
            process_alpha_job,
            max(1, settings.intelligence_processing_interval_seconds // 60),
        ),
        (
            JOB_AIRDROP,
            process_airdrop_job,
            max(1, settings.intelligence_processing_interval_seconds // 60),
        ),
        (
            JOB_PRIME,
            process_prime_sale_job,
            max(1, settings.intelligence_processing_interval_seconds // 60),
        ),
        (
            JOB_COMPETITION,
            process_competition_job,
            max(1, settings.intelligence_processing_interval_seconds // 60),
        ),
        (
            JOB_VOLUME,
            process_volume_job,
            max(1, settings.volume_tracking_interval_minutes),
        ),
        (
            JOB_MARKET_SNAPSHOT,
            process_market_snapshot_job,
            max(1, settings.market_snapshot_interval_minutes),
        ),
        (JOB_FUNDING, process_funding_job, max(1, settings.futures_funding_interval_minutes)),
        (
            JOB_OPEN_INTEREST,
            process_open_interest_job,
            max(1, settings.futures_open_interest_interval_minutes),
        ),
        (JOB_NEWS, process_news_job, max(1, settings.news_collection_interval_minutes)),
        (JOB_LISTINGS, process_listing_job, max(1, settings.news_collection_interval_minutes)),
        (JOB_MOVEMENT, process_movement_job, max(1, settings.market_snapshot_interval_minutes)),
    ]
    # Paused-job flags are persisted in SystemSetting by
    # the scheduler admin endpoints. A restart used to
    # re-register every job as running while the flag
    # still said paused, so the dashboard misreported a
    # running job as disabled (Phase 9 audit). Restore
    # the paused state here, after registration.
    paused: set[str] = set()
    try:
        from app.api.admin_common import get_setting
        from app.database import SessionLocal as _SessionLocal

        _db = _SessionLocal()
        try:
            _flags = get_setting(_db, "scheduler_jobs", {}) or {}
            paused = {k for k, v in _flags.items() if not (v or {}).get("enabled", True)}
        finally:
            _db.close()
    except Exception:  # noqa: BLE001 - scheduler must start even if flags unreadable
        logger.warning("Could not read persisted scheduler job flags", exc_info=True)
    for job_id, func, minutes in jobs:
        if scheduler.get_job(job_id) is None:
            try:
                scheduler.add_job(
                    func,
                    "interval",
                    minutes=minutes,
                    id=job_id,
                    max_instances=1,
                    coalesce=True,
                    misfire_grace_time=60,
                    replace_existing=False,
                )
            except Exception:  # noqa: BLE001 - concurrent registration guard
                # Another registration won the race (the
                # check above is not atomic); the job is
                # registered either way, so continue.
                logger.info("Scheduled job %s already registered (race)", job_id)
                continue
            logger.info("Scheduled job %s registered", job_id)
        else:
            logger.info("Job %s already registered", job_id)
        if job_id in paused:
            try:
                scheduler.pause_job(job_id)
            except Exception:  # noqa: BLE001 - pause failure must not break startup
                logger.warning("Could not restore paused state for job %s", job_id)


def start_scheduler() -> None:
    register_jobs()
    if not scheduler.running:
        # A previous event loop may have been closed (for example
        # after a test run or a reload). APScheduler keeps that
        # loop reference, so clear it before starting again, or
        # the scheduler would try to use a closed loop.
        event_loop = getattr(scheduler, "_eventloop", None)
        if event_loop is not None and event_loop.is_closed():
            scheduler._eventloop = None
        scheduler.start()
        logger.info("Scheduler started")


def shutdown_scheduler() -> None:
    """Stop the scheduler if it is running. Safe to call when it
    was never started, which is the case for a plain test run.

    APScheduler's asyncio shutdown is scheduled on the event
    loop rather than executed immediately, so callers in an
    async context should allow a loop tick afterwards before
    asserting that the scheduler has stopped.
    """
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stop scheduled")
