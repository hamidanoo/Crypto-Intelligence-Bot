# Changelog

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
