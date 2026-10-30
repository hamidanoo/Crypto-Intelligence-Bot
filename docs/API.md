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

## Phase 4 endpoints

All Phase 4 endpoints use real database data; no token,
campaign, or sale is fabricated. Financial values are
serialised as strings, so Decimal precision survives
JSON. Database failures return HTTP 503, missing
records return 404, and invalid input returns 400
(422 for Pydantic validation of non-positive numbers).
Manual collection endpoints are not admin-gated in
this phase (authentication is Phase 8), so they must
only be exposed behind the deployment's own access
controls.

Alpha:

- `GET /alpha/tokens?page=1&page_size=20&symbol=&trading_status=&search=&sort=created_at_desc` — paginated tokens. Sort values: `created_at_desc` (default), `created_at_asc`, `token_name_asc`. Items include token name/symbol, contract address, network, trading status and pairs, announcement URL and timestamp, metadata, data source, verification status, current price, 24h change and volume, market data source, market data updated time, and market data status (`available` or `unavailable`; unavailable fields are null, never zero).
- `GET /alpha/tokens/{id}` — one token; 404 if missing.
- `GET /alpha/updates?page=1&page_size=20&token_id=&update_type=` — paginated token updates (creation and price updates).
- `POST /alpha/collect` — collects announcements via the Phase 3 service, then processes ALPHA announcements. Response: `{category: "ALPHA", created, skipped}`; 502 if announcement collection fails.

Airdrops:

- `GET /airdrops?page=1&page_size=20&status=&symbol=&search=&sort=created_at_desc` — paginated campaigns, each with eligibility records. When a campaign has no eligibility records, `eligibility_note` is "Eligibility details not officially confirmed."
- `GET /airdrops/active` — campaigns with status ACTIVE, UPCOMING, or CLAIMING.
- `GET /airdrops/{id}` — one campaign; 404 if missing.
- `POST /airdrops/collect` — collects announcements, then processes AIRDROP announcements; same response shape as Alpha collect.

Prime Sales:

- `GET /prime-sales?page=1&page_size=20&status=&symbol=&search=&sort=created_at_desc` — paginated sales, each with its allocation rule (formula_type "unknown" unless officially confirmed).
- `GET /prime-sales/active` — sales with status ACTIVE or UPCOMING.
- `GET /prime-sales/{id}` — one sale; 404 if missing.
- `POST /prime-sales/collect` — collects announcements, then processes PRIME_SALE announcements.
- `POST /prime-sales/estimate-allocation` — body: `{"user_commitment": "100", "total_commitment": "400", "total_token_allocation": "1000", "sale_price": null, "formula": null}`. All commitment/allocation values must be positive. Response includes `estimated_allocation` (string), the inputs, the formula, `is_estimate: true`, and a guarantee note stating the result is an estimate only, not a guaranteed allocation. A missing or zero total commitment is rejected, never replaced with an invented total.

## Phase 5 endpoints

All Phase 5 endpoints use real database data; no
competition, reward pool, trading pair, or date is
fabricated. Financial values are serialised as strings,
so Decimal precision survives JSON. Database failures
return HTTP 503, missing records return 404, and
invalid input returns 400. Manual collection is not
admin-gated in this phase (authentication is Phase 8),
so it must only be exposed behind the deployment's own
access controls. There is no volume endpoint here:
volume aggregation is Phase 6 work.

- `GET /competitions?page=1&page_size=20&competition_type=&status=&pair=&start_from=&start_to=&end_from=&end_to=&search=&sort=created_at_desc` — paginated competitions. Sort values: `created_at_desc` (default), `created_at_asc`, `start_time_asc`, `start_time_desc`, `reward_pool_desc`. Items include name, type, official URL, reward pool (string or null), reward currency, start/end/registration times (UTC, null when unconfirmed), status, `duration_seconds` (null when dates are missing), eligible pairs and assets, rules/eligibility/multiplier lists (empty in Phase 5), source, and verification status (`official_website` or `needs_review`).
- `GET /competitions/active` — competitions with status ACTIVE.
- `GET /competitions/upcoming` — competitions with status UPCOMING.
- `GET /competitions/completed` — competitions with status ENDED.
- `GET /competitions/{id}` — one competition; 404 if missing.
- `GET /competitions/{id}/updates` — the competition update timeline, newest first.
- `GET /competitions/{id}/pairs` — normalised trading pairs, rewards, and rules for the competition.
- `POST /competitions/collect` — collects announcements via the Phase 3 service, then processes TRADING_COMPETITION announcements. Response: `{category: "TRADING_COMPETITION", found, created, updated, skipped, errors, status_updates}`; 502 if announcement collection fails.

## Later phases

Later phases add versioned, authenticated API routes for
volume analytics, market, futures, news,
listings, Telegram settings, integrations, scheduler
control, audit logs, and system health. Those routes
are documented here as they are added, not in advance.
