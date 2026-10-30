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

## Phase 6 endpoints

All Phase 6 endpoints use real database data; no
volume is fabricated. Financial values are
serialised as strings, so Decimal precision
survives JSON. Database failures return HTTP 503,
missing records return 404, and invalid input
returns 400. Manual collection is not admin-gated
in this phase (authentication is Phase 8), so it
must only be exposed behind the deployment's own
access controls.

Route naming divergence, stated explicitly: the
routes are `/competition-volume` (no `/api/v1`
prefix), matching the existing routers
(`/announcements`, `/alpha`, `/competitions`). The
frontend calls `/api/competition-volume`, which the
frontend proxy maps to this backend route. There is
no `/api/v1/competition-volume` route.

Accuracy labels are part of the contract: public
market volume comes from Binance public trade data
(aggTrades); estimated eligible volume is present
only with a verified multiplier, otherwise null;
official eligible volume is always null in Phase 6
and is serialised as null (displayed "Unavailable"
by clients), never zero. Official leaderboard data
is not implemented.

- `GET /competition-volume?competition_id=&trading_pair=&interval_from=&interval_to=&data_status=&page=1&page_size=20&sort=interval_start_desc` — paginated intervals. Sort values: `interval_start_desc` (default), `interval_start_asc`, `public_quote_volume_desc`. Items include competition id, pair, base/quote assets, interval start/end (UTC), public base/quote volumes (strings or null), estimated eligible volume (string or null), official eligible volume (always null), calculation method, data status (complete/partial/incomplete), recalculated flag, and collected time.
- `GET /competition-volume/collection-runs?competition_id=&page=1&page_size=20` — volume collection runs, newest first, with found/created/updated/skipped counts, status, and error message.
- `GET /competition-volume/{id}` — intervals for one competition (same filters as the list, minus competition_id); 404 if the competition is missing.
- `GET /competition-volume/{id}/pairs` — pairs for the competition with tracking toggle, multiplier and verification flag, checkpoint end, and latest interval per pair.
- `GET /competition-volume/{id}/history?trading_pair=&page=1&page_size=20&sort=interval_start_desc` — paginated interval history for one competition, optionally for one pair.
- `GET /competition-volume/{id}/summary` — per-pair latest interval, cumulative public base/quote volumes (sums of stored complete/partial intervals), cumulative estimated eligible volume (null when no interval has an estimate), interval count, last collection time/status, and official eligible volume (null, with display "Unavailable").
- `POST /competition-volume/collect` — collects volumes for ACTIVE/UPCOMING competitions. (The scheduler job, not this endpoint, then runs the Telegram reporting pass.) Response: `{competitions, intervals_found, intervals_created, intervals_updated, intervals_skipped, intervals_completed, errors, error_messages}`; 502 when the whole collect fails upstream with nothing usable collected, 503 on database errors.
- `POST /competition-volume/{id}/collect` — collects volumes for one competition regardless of status; same response and error codes; 404 if the competition is missing.

## Phase 7 endpoints

Routes are `/market`, `/futures`, `/news` (no
`/api/v1` prefix), matching existing routers;
the frontend calls `/api/market` etc., which the
proxy maps to these backend routes. Decimals are
strings. Manual collect endpoints are ungated
until Phase 8 authentication and must only be
exposed behind deployment access controls.

- `GET /market/overview?symbol=` — latest snapshot per symbol, with `is_stale` and freshness window.
- `GET /market/prices?symbol=&page=&page_size=` — paginated latest snapshots.
- `GET /market/gainers?limit=&min_quote_volume=` and `GET /market/losers` — top gainers/losers by 24h percent change, excluding symbols below the minimum quote volume (counted in `excluded_low_liquidity`).
- `GET /market/{symbol}` — latest snapshot; 400 invalid symbol, 404 no data.
- `GET /market/history?symbol=&collected_from=&collected_to=&page=&page_size=` — snapshot history.
- `GET /market/watchlist`, `POST /market/watchlist` (symbol, note; duplicate returns `already_exists`), `DELETE /market/watchlist/{id}` (404 missing).
- `GET /market/alerts?symbol=&alert_type=&triggered_from=&triggered_to=&page=&page_size=` — movement and funding alerts.
- `POST /market/collect` — collects tracked symbols (or a body `symbols` list, max 20); 502 on Binance failure, 503 on database errors.
- `GET /futures/funding?sort=highest|lowest&limit=` — latest funding rates; 400 invalid sort.
- `GET /futures/funding/{symbol}`, `GET /futures/open-interest`, `GET /futures/open-interest/{symbol}` — 400 invalid symbol, 404 no data.
- `GET /futures/ratios?symbol=&ratio_type=&page=&page_size=` — long/short ratios, each labelled by dataset type.
- `GET /futures/summary` — availability (`available`/`degraded`/`unavailable`), highest/lowest funding, last collection status and error. Open interest alone does not imply direction.
- `POST /futures/collect` — collects funding/open interest and ratios; 502 when the whole collection is unavailable (for example HTTP 451), 200 with `degraded` status on partial failure.
- `GET /news?category=&publisher=&search=&published_from=&published_to=&page=&page_size=` — paginated news; 400 invalid category.
- `GET /news/{id}` — 404 missing. Summary is "Summary unavailable" with `summary_available: false` when article bodies are unavailable.
- `GET /news/categories` — category list with counts.
- `GET /news/sources` — news sources with reliability notes.
- `GET /news/collection-runs` — paginated collection runs.
- `GET /news/listings`, `GET /news/delistings` — listing and delisting news.
- `POST /news/collect` — processes stored announcements into news; returns found/created/skipped.

## Later phases

Later phases add versioned, authenticated API routes for
volume analytics, market, futures, news,
listings, Telegram settings, integrations, scheduler
control, audit logs, and system health. Those routes
are documented here as they are added, not in advance.

## Phase 8 endpoints

Authentication is session-based (see docs/ADMIN_SETUP.md).
All `/admin/*` endpoints require a session cookie plus,
for state-changing requests, the `X-CSRF-Token` header.
Unauthenticated requests return 401, unauthorised
requests return 403, and failed authorisation attempts
are audited.

### Authentication

- `POST /auth/login` — username + password, sets
  HttpOnly session cookie and CSRF cookie.
- `POST /auth/logout` — revokes the session, clears cookies.
- `GET /auth/me` — current administrator and permissions.
- `POST /auth/refresh` — rotates the session token.
- `POST /auth/change-password` — requires the current password.
- `POST /auth/forgot-password` — always the same generic
  response (no account enumeration).
- `POST /auth/reset-password` — single-use, 60-minute token.

### Administration

- `GET /admin/dashboard/overview`, `/admin/dashboard/activity`,
  `/admin/dashboard/health` — real aggregated data and
  actual service checks (dashboard.view).
- `GET/POST /admin/users`, `GET/PATCH /admin/users/{id}`,
  `POST /admin/users/{id}/deactivate` (users.view / users.manage).
- `GET/POST/PATCH /admin/roles`, `GET /admin/permissions`
  (roles.view / roles.manage).
- `GET/PATCH /admin/telegram`, `POST /admin/telegram/test-message`
  (telegram.view / telegram.manage). Test messages are
  sent only on explicit request.
- `GET/POST/PATCH /admin/integrations`,
  `POST /admin/integrations/{id}/test-connection`
  (integrations.view / integrations.manage). Responses
  are masked; secrets are AES-GCM encrypted at rest.
- `GET/PATCH /admin/notifications`,
  `GET /admin/notifications/history`
  (notifications.view / notifications.manage).
- `GET /admin/scheduler`,
  `POST /admin/scheduler/{id}/pause|resume|trigger`
  (scheduler.view / scheduler.manage / scheduler.trigger).
  Job ids are validated against a server-side allowlist.
- `GET /admin/audit-logs` — paginated, filterable
  (audit.view). No update or delete endpoint exists.
- `GET/PATCH /admin/system-settings`
  (settings.view / settings.manage).
- `GET/POST/PATCH /admin/news-sources`,
  `POST /admin/news-sources/{id}/test`
  (news_sources.view / news_sources.manage). Feed tests
  apply SSRF protection (see docs/ADMIN_DASHBOARD.md).

### Protected collection endpoints (Phase 8 change)

Every manual collection endpoint from Phases 3-7 now
requires `collections.run` plus CSRF; see docs/RBAC.md
for the full list. `PATCH /announcements/sources/{id}`
requires announcements.manage, and market watchlist
writes require market.manage. `POST
/prime-sales/estimate-allocation` remains public: it is
a pure calculation from caller-supplied inputs.
