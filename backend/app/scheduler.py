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
    """Register scheduled jobs. Phase 1 registers none: later phases
    add their collectors here with explicit, idempotent job ids."""
    logger.info("Scheduler initialised with no Phase 1 jobs registered")


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
