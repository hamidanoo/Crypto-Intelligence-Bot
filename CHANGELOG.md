# Changelog

## Phase 3 — Announcement Monitor

- Add Binance website CMS announcement collector (GET
  article list, catalogs for listings, news, activities,
  delistings, maintenance, API updates, and airdrops),
  with the undocumented-endpoint limitation documented,
  not hidden.
- Add announcement models and migration 0004:
  announcement sources, announcements, and collection runs.
- Add category classification with high/medium/low
  confidence for 12 categories, extensible for later phases.
- Add duplicate detection by (source, external id) and
  canonical URL, with in-place updates on changed titles.
- Add scheduled collection (APScheduler, every 5 minutes,
  max_instances=1, idempotent registration) and manual
  collection API endpoints.
- Add announcement API endpoints with pagination, category,
  source, date, search, and sort filters, plus source
  configuration (PATCH) and collection-run listing.
- Add Telegram notification foundation: HTML messages,
  send-once marking, failure recording with up to 3
  attempts, and category enable/disable configuration.
  Live delivery remains unverified (no token); mock tests
  cover formatting, duplicates, and failures.
- Add a small "Latest announcements" section to the
  existing frontend home page, using real collected data.
- Add `docs/ANNOUNCEMENT_MONITOR.md` and update API,
  Architecture, Database, Status, and Development Log
  documentation.
- No Alpha, Airdrop, Prime Sale, or Competition modules
  were implemented in this phase; they reuse this
  foundation in later phases.

## Phase 1 + Phase 2 Bug-Fix Pass

- Start and stop the APScheduler scheduler from the API
  lifespan, including recovery from a previously closed event
  loop, and add lifespan tests.
- Run database migrations automatically on backend container
  start via `backend/entrypoint.sh` (`alembic upgrade head`
  before the API starts).
- Route the frontend through the `/api` proxy by default
  (Next.js rewrites, Nginx `/api/` proxy in production).
- Fail fast in production when `SECRET_KEY` is still the
  default placeholder, and tighten CORS methods and headers.
- Pick the Binance funding rate by latest funding time,
  not by last row position.
- Fix retry handling: non-numeric Retry-After no longer
  crashes, no sleep on the final attempt, and final 429/5xx
  errors report their real status and message.
- Store snapshot financial values as Numeric (Decimal) via
  migration `0003`, converting via string form on collection.
- Ping Spot and Futures concurrently in `/binance/status`.
- Add a JSON body contract to collect endpoints, a
  20-symbol limit, and a 503 for database failures.
- Add Redis-backed caching with an in-memory fallback for
  price, ticker, and klines, and a 120/minute per-IP rate
  limit on Binance routes.
- Add ruff and black configuration, a local check script,
  and 10 new tests for the fixes. (A GitHub Actions
  workflow file was prepared locally but could not be
  pushed via the GitHub integration; see PROJECT_STATUS.)
- Document issue classification in
  `docs/ISSUE_FIX_PLAN.md` and external verification steps
  in `docs/EXTERNAL_VERIFICATION.md`. Docker, live
  PostgreSQL, live Redis, live Telegram, and live Futures
  testing remain unverified and are documented, not faked.

## Phase 2 — Binance Market Integration

- Add Binance Spot API client with price, 24-hour ticker, and
  klines endpoints.
- Add Binance Futures API client with funding rate, premium
  index, and open interest endpoints.
- Add retry handling for transient Binance failures and
  honest error reporting for upstream failures.
- Add market and futures snapshot models and migration 0002.
- Add Binance API routes and collection endpoints.
- Add Binance connection monitoring via the status endpoint.
- Document the data-api.binance.vision alternative for
  restricted locations.

## Phase 1 — Project Foundation

- Set up backend project structure with FastAPI, configuration,
  logging, and database setup.
- Add database models and initial Alembic migration.
- Add backend health and readiness endpoints.
- Add Telegram bot connection structure with basic commands.
- Add APScheduler job registry.
- Create basic Next.js admin frontend with live backend health check.
- Configure Docker, Docker Compose, PostgreSQL, Redis, and Nginx.
- Add environment template and Phase 1 project documentation.
