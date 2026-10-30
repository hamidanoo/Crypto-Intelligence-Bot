# Architecture

## Overview

Modular monolith. One repository, one backend service, one frontend
service, PostgreSQL, Redis, and Nginx.

```
Telegram group
      |
Telegram Bot API -> bot handlers (backend/app/bot.py)
      |
FastAPI backend (backend/app/main.py)
      |-- SQLAlchemy models (backend/app/models.py)
      |-- Alembic migrations (backend/alembic/)
      |-- APScheduler job registry (backend/app/scheduler.py)
      |-- PostgreSQL (persistent data, UTC timestamps)
      |-- Redis (caching, deduplication keys in later phases)
      |
Next.js admin dashboard (frontend/)
      |
Nginx (reverse proxy: / -> frontend, /api/ -> backend)
```

## Module boundaries

- API layer: FastAPI routers under `backend/app/api/`.
- Data layer: SQLAlchemy models and Alembic migrations only;
  no raw SQL in routers except health checks.
- Bot layer: aiogram handlers only; business logic lives in
  backend services in later phases and is called from handlers.
- Frontend: Next.js pages call the backend API; they never talk
  directly to the database or to Telegram.
- Background work: jobs are registered in `scheduler.py` with
  explicit ids, so they are idempotent and restart-safe by design.
  Phase 3 adds one job, `announcement_collection`, every 5
  minutes, max_instances=1, collecting from due enabled
  announcement sources and then notifying about pending
  announcements. Announcement collection itself lives in
  `backend/app/announcements/` (client, classifier, service,
  notifications, scheduler job); the API layer is
  `backend/app/api/announcements.py`. Phase 4 adds three
  processing jobs on the same scheduler, each every 10
  minutes, max_instances=1: `alpha_processing`,
  `airdrop_processing`, and `prime_sale_processing`.
  They process announcements the collector already
  stored; they do not re-fetch the CMS feed. Phase 4
  logic lives in `backend/app/intelligence/` (parsing,
  allocation, processing, notifications, scheduler
  jobs); the API layer is
  `backend/app/api/intelligence.py`, and bot commands
  live in `backend/app/bot.py`. APScheduler remains
  single-instance only; distributed coordination is deferred.

## Later phases

Phases 2–7 add collectors and services inside the backend,
Phase 8 adds dashboard pages and authentication, Phase 9 tests and
hardens the whole system, and Phase 10 prepares VPS deployment.
No phase introduces a new service without recording the decision
in `docs/DEVELOPMENT_LOG.md`.
