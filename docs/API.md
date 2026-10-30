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

## Phase 3 endpoints

All announcement endpoints use real database data; no
announcement is fabricated. Database failures return HTTP
503. Admin authentication for manual collection and source
configuration is a Phase 8 feature; in Phase 3 those
endpoints are not admin-gated and must only be exposed
behind the deployment's own access controls.

- `GET /announcements?page=1&page_size=20&category=&source_id=&search=&published_from=&published_to=&sort=published_at_desc` — paginated list. Sort values: `published_at_desc` (default), `published_at_asc`, `collected_at_desc`. Response: `{total, page, page_size, items: [{id, source_id, source_name, external_id, code, title, slug, canonical_url, category, category_confidence, summary, published_at, collected_at, content_hash, verification_status, metadata, notification_status, notified_at, notification_attempts}]}`
- `GET /announcements/{id}` — one announcement; 404 if missing.
- `GET /announcements/categories` — `{categories: [...all categories...], counts: {category: count}}` from the database.
- `GET /announcements/sources` — `{sources: [{id, name, source_type, base_url, enabled, polling_interval_seconds, configuration, last_success_at, last_error_at, last_error_message, created_at, updated_at}]}`
- `GET /announcements/collection-runs?page=1&page_size=20&source_id=&status=` — paginated runs: `{total, page, page_size, items: [{id, source_id, started_at, completed_at, status, announcements_found, announcements_created, duplicates_skipped, error_message}]}`
- `POST /announcements/collect` — body (optional): `{"source_id": 1, "page_size": 20}`. When source_id is omitted, all enabled sources are collected (the default Binance source is created if none exists). Response: `{runs: [...], announcements_created, duplicates_skipped}`; 502 if all runs failed, 400 if the requested source is disabled, 404 if it does not exist.
- `POST /announcements/sources/{id}/collect` — same response shape for one source.
- `PATCH /announcements/sources/{id}` — body (any subset): `{"enabled": true, "polling_interval_seconds": 300, "configuration": {...}}`. Polling interval must be 60–86400. Returns the updated source; 404 if missing.

## Later phases

Later phases add versioned, authenticated API routes for Alpha,
airdrops, Prime Sales, competitions, volume analytics, market,
futures, news, listings, Telegram settings, integrations,
scheduler control, audit logs, and system health. Those routes
are documented here as they are added, not in advance.
