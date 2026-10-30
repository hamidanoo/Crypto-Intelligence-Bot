# API

Base URL in development: http://localhost:8000

## Phase 1 endpoints

### GET /health

Liveness check. Does not require the database or Redis.

Response:
```json
{
  "status": "ok",
  "service": "crypto-intelligence-backend",
  "environment": "development",
  "timestamp": "2026-10-30T00:00:00+00:00"
}
```

### GET /health/ready

Readiness check. Reports each dependency honestly:

```json
{
  "status": "ready",
  "service": "crypto-intelligence-backend",
  "environment": "development",
  "timestamp": "2026-10-30T00:00:00+00:00",
  "components": {
    "database": "ok",
    "redis": "ok"
  }
}
```

If a dependency is unavailable, its component is reported as
`"unavailable"` and the overall status is `"degraded"`.

## Phase 2 endpoints

All Binance endpoints use public, read-only data and require no
API key. Symbols are validated (uppercase alphanumeric). A
Binance upstream failure, for example a restricted-location
response, is returned as HTTP 502 with the upstream message,
never as fabricated data.

- `GET /binance/status` — connection monitoring for Spot and
  Futures separately, with latency and error per integration.
  Overall status is `ok` only when both are ok, otherwise
  `degraded`.
- `GET /binance/price/{symbol}` — live Spot price.
- `GET /binance/ticker/{symbol}` — 24-hour Spot ticker: price,
  change, change percent, high, low, volume, quote volume.
- `GET /binance/klines/{symbol}?interval=1h&limit=100` — Spot
  klines with open, high, low, close, volume, quote volume,
  trade count, and UTC open/close times. Intervals:
  1m, 5m, 15m, 30m, 1h, 4h, 1d, 1w.
- `GET /binance/funding/{symbol}` — latest Futures funding rate,
  next funding time, and mark price.
- `GET /binance/open-interest/{symbol}` — Futures open interest.
- `POST /binance/collect/market` — persist 24-hour ticker
  snapshots for the tracked symbols (or a supplied list) to
  `market_snapshots`.
- `POST /binance/collect/futures` — persist funding, mark price,
  and open interest snapshots to `futures_snapshots`.

## Later phases

Later phases add versioned, authenticated API routes for Alpha,
airdrops, Prime Sales, competitions, volume analytics, market,
futures, news, listings, Telegram settings, integrations,
scheduler control, audit logs, and system health. Those routes
are documented here as they are added, not in advance.
