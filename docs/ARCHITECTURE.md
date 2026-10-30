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
  live in `backend/app/bot.py`. Phase 5 adds one more
  processing job on the same scheduler,
  `competition_processing`, every 10 minutes,
  max_instances=1, which processes stored
  TRADING_COMPETITION announcements and recomputes
  date-based statuses; it does not re-fetch the CMS
  feed. Phase 5 logic lives in
  `backend/app/competitions/` (parsing, processing,
  notifications, scheduler jobs); the API layer is
  `backend/app/api/competitions.py`, and bot commands
  live in `backend/app/bot.py`. Phase 6 adds one more
  job on the same scheduler,
  `competition_volume_tracking`, every 30 minutes,
  max_instances=1, which collects newly completed
  30-minute volume intervals from Binance Spot
  aggTrades for ACTIVE/UPCOMING competitions and
  then runs the Telegram reporting pass; only
  completed intervals are processed, so the job
  firing off :00/:30 boundaries is safe. Phase 6
  logic lives in `backend/app/volume/` (intervals,
  aggregation, collection, reporting, scheduler
  jobs); the API layer is
  `backend/app/api/volume.py`, and the home page
  gains a Competition Volume section (not the full
  Phase 8 dashboard). APScheduler remains
  single-instance only; distributed coordination is deferred.

Phase 7 logic lives in `backend/app/marketintel/` (classification, service, notifications, scheduler jobs); the API layer is `backend/app/api/market.py`, `backend/app/api/futures.py`, and `backend/app/api/news.py`, and bot commands live in `backend/app/bot.py`. It adds six jobs on the same scheduler, each max_instances=1: `market_snapshot` (5 minutes), `funding_collection` (5 minutes), `open_interest_collection` (15 minutes), `news_collection` (5 minutes), `listing_processing` (5 minutes), and `market_movement_detection` (5 minutes). Futures collection degrades on HTTP 451 instead of failing the app, and news is built from stored announcements plus any deliberately enabled RSS source (none enabled by default). 

## Later phases

Phases 2–7 add collectors and services inside the backend,
Phase 8 adds dashboard pages and authentication, Phase 9 tests and
hardens the whole system, and Phase 10 prepares VPS deployment.
No phase introduces a new service without recording the decision
in `docs/DEVELOPMENT_LOG.md`.
