# Project Status

- **Current phase:** Phase 1 + Phase 2 bug-fix pass (Phase 3 NOT approved)
- **Current branch:** `fix-phase1-phase2-issues`, created from `phase-02-binance-integration`
- **Latest commit:** `b546e97f99f1619111c24190b27e0141d98f825d` — "Fix Phase 1 and Phase 2 issues: scheduler, migrations, proxy, secrets, CORS, funding order, retries, Decimal, cache and rate limits", on `fix-phase1-phase2-issues`, verified by reading the branch back after the push. A following status-update commit will head the branch after this file is pushed (see the fix report in chat).
- **Merged into main:** No. Merging requires explicit approval.

## Completed features (Phase 2, plus fixes)

- Binance Spot API client: price, 24-hour ticker, and klines
  with volume, trade count, and UTC timestamps.
- Binance Futures API client: funding rate, premium index
  (mark price and next funding time), and open interest.
  Funding rate now picks the row with the latest funding time,
  instead of assuming the last row is latest.
- Retry handling for network errors, HTTP 429, and HTTP 5xx
  with exponential backoff; a non-numeric Retry-After header
  no longer crashes, no sleep is wasted on the final attempt,
  and a final 429/5xx now reports its real status and message.
- Persistence: `market_snapshots` and `futures_snapshots`
  tables with migrations `0002` and `0003`. Migration `0003`
  stores financial values as Numeric (Decimal), not Float.
  Collection endpoints are `POST /binance/collect/market` and
  `/binance/collect/futures`, now with a JSON body
  (`{"symbols": [...]}`), a 20-symbol limit, and a 503 (not a
  raw 500) when the database is unavailable.
- API connection monitoring: `GET /binance/status` now pings
  Spot and Futures concurrently and reports each separately
  with latency and error.
- Caching and request controls: price, ticker, and klines
  responses are cached (Redis when reachable, in-memory
  fallback otherwise; price responses report `"cached"`),
  and Binance routes are rate-limited to 120 requests per
  minute per client IP (single-instance limit).
- Tracked symbols by default: BTCUSDT, ETHUSDT, BNBUSDT,
  SOLUSDT, XRPUSDT, configurable via `TRACKED_SYMBOLS`.
- Base URLs configurable via environment: Spot defaults to
  api.binance.com, with data-api.binance.vision documented as
  the alternative where the main endpoint is restricted.

## Completed features (Phase 1, plus fixes)

- Backend project structure with FastAPI, configuration management,
  logging, and SQLAlchemy database setup.
- Initial database models: AdminUser, TelegramGroup, SystemSetting,
  ApiIntegration, AuditLog.
- Alembic configuration and migrations `0001`, `0002`, `0003`.
  The backend Docker entrypoint now runs `alembic upgrade head`
  before starting the API, so a fresh deployment never starts
  with missing tables. Migration execution was verified
  against SQLite (head `0003`, all tables present); live
  PostgreSQL execution is still unverified (see below).
- FastAPI health endpoint (`/health`) and readiness endpoint
  (`/health/ready`) reporting database and Redis status honestly.
- Telegram bot connection structure with `/start`, `/help`, and
  `/status` handlers; polling starts only when a bot token is set.
- APScheduler job registry with no jobs registered yet, now
  actually started and stopped by the API lifespan, including
  handling a previously closed event loop on restart.
- Frontend: the page now uses the `/api` proxy by default
  (Next.js rewrites in development / direct Next.js serving,
  Nginx `/api/` proxy in production behind Nginx), instead of
  calling the backend directly at localhost:8000. Verified
  live: `GET /api/health` through the frontend returned the
  backend health JSON.
- Production secret validation: the app fails to start when
  `ENVIRONMENT=production` and `SECRET_KEY` is still the
  default placeholder.
- CORS: methods are now an explicit list (GET, POST, PUT,
  PATCH, DELETE, OPTIONS) and headers are limited to
  Authorization, Content-Type, and Accept, instead of `*`.
- Docker and Docker Compose configuration for PostgreSQL, Redis,
  backend, bot, frontend, and Nginx.
- Environment template (`.env.example`) with placeholders only.
- CI: linting (ruff) and formatting (black, ruff format)
  configuration live in `backend/pyproject.toml`;
  `scripts/check.sh` runs lint, format, tests, and the
  frontend build locally. A GitHub Actions workflow file
  (`.github/workflows/ci.yml`) was prepared in the local
  workspace but could NOT be pushed via the current GitHub
  integration: GitHub returned 403 "Resource not accessible
  by integration" for that file alone, while all other files
  pushed successfully. That file is therefore not on the
  branch yet; it can be added manually from the local copy,
  or after the GitHub App is granted workflow write access.
- Project documentation set, plus `docs/ISSUE_FIX_PLAN.md`
  (issue classification) and `docs/EXTERNAL_VERIFICATION.md`
  (exact commands for the checks that still need an external
  environment).

## Pending features

- Phase 3 — Announcement Monitor, and all later phases
  (4–10). No work from those phases has been started, and
  Phase 3 is NOT approved in this fix pass.

## Known issues and limitations (still open, not faked)

- Docker is not available in the development environment used for
  testing, so `docker compose up` was not run here. A full run
  is still required on a machine with Docker before production use.
- Live PostgreSQL and Redis were not available during testing,
  so migration execution against live PostgreSQL, collection to
  a live database, and Redis-backed caching are still to be
  verified on a Docker host or VPS. SQLite migration execution
  and in-memory cache fallback were verified; the Redis path
  was not.
- Live Telegram bot polling was not tested (no token available).
- Binance Futures endpoints are blocked from this test
  environment with a restricted-location response
  (api.binance.com and fapi.binance.com). Spot data was tested
  live via data-api.binance.vision. Futures code is complete,
  but live Futures testing must happen on a VPS in an allowed
  location. The status endpoint reports this honestly as
  Futures unavailable, rather than fabricating data.
- No announcement, Alpha, airdrop, Prime Sale, competition,
  volume, news, or dashboard features exist yet. Those are
  later phases. shadcn/ui components, dashboard auth, and
  Nginx TLS are documented for Phase 8 / Phase 10, not added here.

## Latest test results

- Backend tests: `pytest` from `backend/` — 22 passed
  (12 original Phase 1 + Phase 2 tests plus 10 new fix tests,
  covering production secret validation, scheduler lifecycle
  and lifespan, funding-rate ordering, retry after 429 with a
  non-numeric Retry-After, Decimal snapshot storage, cache
  fallback, rate limiting, and the collect JSON body).
- Lint/format: `ruff check`, `ruff format --check`, and
  `black --check` all pass on `backend/app` and `backend/tests`.
- Alembic: `alembic upgrade head` against SQLite succeeded,
  `alembic current` reports `0003` (head), all 7 tables present.
- Live Spot API (via data-api.binance.vision): BTCUSDT price
  returned 77799.9 at test time, with `"cached": false` on the
  first call and `"cached": true` on the immediate second call.
  `/binance/status` reported Spot ok and Futures unavailable
  with the restricted-location message (degraded overall).
- Frontend: `npm run build` succeeded, and a fresh
  `npm start` server proxied `GET /api/health` to the backend
  with HTTP 200 and the backend health JSON.
- Full details are in `docs/DEVELOPMENT_LOG.md`.

## Next phase awaiting approval

Phase 3 — Announcement Monitor. Do not start it without
explicit approval, for example: "Approved. Start Phase 3."
