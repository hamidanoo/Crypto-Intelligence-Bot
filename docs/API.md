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
  The two pings run concurrently. Overall status is `ok`
  only when both are ok, otherwise `degraded`.
- `GET /binance/price/{symbol}` — live Spot price, cached
  for 10 seconds (Redis when reachable, in-memory fallback;
  the response reports `"cached": true` on a cache hit).
- `GET /binance/ticker/{symbol}` — 24-hour Spot ticker: price,
  change, change percent, high, low, volume, quote volume,
  cached for 15 seconds.
- `GET /binance/klines/{symbol}?interval=1h&limit=100` — Spot
  klines with open, high, low, close, volume, quote volume,
  trade count, and UTC open/close times, cached for 60
  seconds. Intervals: 1m, 5m, 15m, 30m, 1h, 4h, 1d, 1w.
- `GET /binance/funding/{symbol}` — latest Futures funding rate
  (by latest funding time), next funding time, and mark price.
- `GET /binance/open-interest/{symbol}` — Futures open interest.
- `POST /binance/collect/market` — persist 24-hour ticker
  snapshots to `market_snapshots`. Body (optional):
  `{"symbols": ["BTCUSDT"]}`; when omitted, the tracked
  symbols are used. At most 20 symbols per request. A
  database failure returns HTTP 503.
- `POST /binance/collect/futures` — persist funding, mark price,
  and open interest snapshots to `futures_snapshots`, with
  the same body, limit, and 503 behaviour as above.

Binance routes are rate-limited to 120 requests per minute
per client IP (single-instance limit; HTTP 429 when exceeded).
In production behind Nginx, the frontend calls these routes
through `/api/`; in development, Next.js rewrites `/api/`
to the backend.

## Later phases

Later phases add versioned, authenticated API routes for Alpha,
airdrops, Prime Sales, competitions, volume analytics, market,
futures, news, listings, Telegram settings, integrations,
scheduler control, audit logs, and system health. Those routes
are documented here as they are added, not in advance.
