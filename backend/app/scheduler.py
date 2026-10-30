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
    Calling register_jobs twice does not register the job
    twice: an existing job with the same id is left alone.
    """
    from app.announcements.scheduler_job import JOB_ID, collect_all_announcements

    if scheduler.get_job(JOB_ID) is None:
        scheduler.add_job(
            collect_all_announcements,
            "interval",
            minutes=5,
            id=JOB_ID,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=60,
            replace_existing=False,
        )
        logger.info("Scheduled announcement collection job registered")
    else:
        logger.info("Announcement collection job already registered")


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
