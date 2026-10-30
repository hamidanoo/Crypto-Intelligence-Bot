# Changelog

## Phase 4 — Binance Alpha, Airdrop & Prime Sale Intelligence

- Add Alpha, airdrop, and Prime Sale models and
  migration 0005: `alpha_tokens`, `alpha_token_updates`,
  `airdrop_campaigns`, `airdrop_eligibility`,
  `prime_sales`, `prime_sale_allocation_rules`, and
  `campaign_notifications`, with unique constraints,
  indexes, UTC timestamps, and Decimal financial fields.
- Add title parsing for token name/symbol, contract
  addresses, and networks, with conservative status
  rules for airdrops and Prime Sales (anything not
  matching a listed phrase is UNKNOWN) and eligibility
  hints only for recognisable requirements. Removal
  announcements listing many tokens are recorded as
  multi-token removal announcements, never as a single
  fake token (found and fixed during live testing).
- Add announcement-to-module processing reusing the
  Phase 3 collector, with deduplication by
  announcement_id and Alpha market data from the
  Phase 2 Spot client; unavailable market data stays
  null with status "unavailable", never zero.
- Add a Decimal-only proportional allocation estimator
  for Prime Sales, labelled as an estimate, never a
  guarantee, rejecting missing or zero totals.
- Add Phase 4 API endpoints for Alpha tokens and
  updates, airdrops (including active), Prime Sales
  (including active), manual collection, and
  allocation estimation, with pagination, filtering,
  sorting, Decimal-as-string serialisation, 404/502/
  503 handling. Manual collect endpoints are not
  admin-gated until Phase 8 and must sit behind
  deployment access controls.
- Add three idempotent scheduler jobs on the existing
  APScheduler instance (Alpha, airdrop, Prime Sale
  processing, every 10 minutes, max_instances=1).
- Add Telegram commands `/alpha [token]`, `/airdrop`,
  `/airdrops active`, `/prime`, `/prime active`, and
  `/prime estimate <yours> <total> <allocation>`, plus
  notification formatters with duplicate prevention
  via `campaign_notifications`. Live Telegram delivery
  remains unverified (no token); mock formatting tests
  cover the messages.
- Add a small real-data frontend section (latest Alpha
  tokens, active airdrops, active Prime Sales, or
  "None recorded yet") — no dashboard, no fake data.
- Add `docs/ALPHA_INTELLIGENCE.md`,
  `docs/AIRDROP_INTELLIGENCE.md`, and
  `docs/PRIME_SALE_INTELLIGENCE.md`, and update API,
  Architecture, Database, Status, and Development Log
  documentation.
- No Phase 5 work (trading competitions or volume
  tracking) was implemented in this phase.

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
