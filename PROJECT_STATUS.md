# Project Status

- **Current phase:** Phase 2 — Binance Market Integration
- **Current branch:** `phase-02-binance-integration`
- **Latest commit:** `5889e1364c69b686583694dc5811da2b79eab8c1` — "Integrate Binance market data endpoints", on `phase-02-binance-integration`, verified by reading the branch back after the push.
- **Merged into main:** No. Merging requires explicit approval.

## Completed features (Phase 2)

- Binance Spot API client: price, 24-hour ticker, and klines
  with volume, trade count, and UTC timestamps.
- Binance Futures API client: funding rate, premium index
  (mark price and next funding time), and open interest.
- Retry handling for network errors, HTTP 429, and HTTP 5xx
  with exponential backoff; other Binance errors are surfaced
  unchanged, including restricted-location responses.
- Persistence: `market_snapshots` and `futures_snapshots`
  tables with migration `0002`, and collection endpoints
  `POST /binance/collect/market` and `/binance/collect/futures`.
- API connection monitoring: `GET /binance/status` reports
  Spot and Futures separately with latency and error.
- Tracked symbols by default: BTCUSDT, ETHUSDT, BNBUSDT,
  SOLUSDT, XRPUSDT, configurable via `TRACKED_SYMBOLS`.
- Base URLs configurable via environment: Spot defaults to
  api.binance.com, with data-api.binance.vision documented as
  the alternative where the main endpoint is restricted.

## Completed features (Phase 1)

- Backend project structure with FastAPI, configuration management,
  logging, and SQLAlchemy database setup.
- Initial database models: AdminUser, TelegramGroup, SystemSetting,
  ApiIntegration, AuditLog.
- Alembic configuration and initial migration `0001`.
- FastAPI health endpoint (`/health`) and readiness endpoint
  (`/health/ready`) reporting database and Redis status honestly.
- Telegram bot connection structure with `/start`, `/help`, and
  `/status` handlers; polling starts only when a bot token is set.
- APScheduler job registry with no Phase 1 jobs registered.
- Basic Next.js + TypeScript frontend page that reads the live
  backend health endpoint.
- Docker and Docker Compose configuration for PostgreSQL, Redis,
  backend, bot, frontend, and Nginx.
- Environment template (`.env.example`) with placeholders only.
- Project documentation set for Phase 1.

## Pending features

- Phase 3 — Announcement Monitor, and all later phases
  (4–10). No work from those phases has been started.

## Known issues and limitations

- Docker is not available in the development environment used for
  testing, so Docker services were not started here. A full
  `docker compose up` run is still required on a machine with
  Docker before production use.
- Live PostgreSQL and Redis were not available during testing,
  so migration `0002` execution against live PostgreSQL and
  collection to a live database are still to be verified on a
  Docker host or VPS. Persistence was verified with an
  in-memory SQLite database in tests.
- Binance Futures endpoints are blocked from this test
  environment with a restricted-location response
  (api.binance.com and fapi.binance.com). Spot data was tested
  live via data-api.binance.vision. Futures code is complete,
  but live Futures testing must happen on a VPS in an allowed
  location. The status endpoint reports this honestly as
  Futures unavailable, rather than fabricating data.
- No announcement, Alpha, airdrop, Prime Sale, competition,
  volume, news, or dashboard features exist yet. Those are
  later phases.

## Latest test results

- Backend tests: `pytest` from `backend/` — 12 passed
  (Phase 1 health tests plus Phase 2 client, API, and
  persistence tests).
- Live Spot API (via data-api.binance.vision): BTCUSDT price,
  ETHUSDT 24-hour ticker, and BTCUSDT 1-hour klines all
  returned real data through the new client and API routes.
- Live Futures API: funding rate, open interest, and premium
  index all returned the restricted-location error from this
  environment, which the client surfaces as a 502 with the
  upstream message, and `/binance/status` reports as degraded.
- Alembic: `alembic history` shows migration `0002` as head.
- Full details are in `docs/DEVELOPMENT_LOG.md`.

## Next phase awaiting approval

Phase 3 — Announcement Monitor. Do not start it without
explicit approval, for example: "Approved. Start Phase 3."
