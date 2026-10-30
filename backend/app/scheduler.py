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
        scheduler.start()
        logger.info("Scheduler started")
